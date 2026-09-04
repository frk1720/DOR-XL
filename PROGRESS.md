# Progress DOR XL

Dokumen ini merangkum pembaruan dan fitur yang telah diimplementasikan ke dalam ekosistem DOR XL (Worker dan API).

## 1. Migrasi Kriptografi Lokal (Local Crypto)
- **Problem**: Ketergantungan pada server enkripsi eksternal (me-crypto.mashu.lol) menyebabkan NameResolutionError saat domain mati, melumpuhkan seluruh sistem auto-renew.
- **Solution**: Mengimplementasikan pp/service/crypto_helper.py untuk mengenkripsi payload (XDATA) sepenuhnya di dalam memori VM menggunakan kunci AES/HMAC lokal (XDATA_KEY, X_API_BASE_SECRET, dll).
- **Result**: Sistem menjadi 100% independen dan lebih aman. Kunci rahasia murni tersimpan di .env server tanpa data yang mengalir ke pihak ketiga.

## 2. Worker Auto-Renew Mandiri & Notifikasi Telegram
- **Problem**: Ketergantungan pada Vercel Cron menyebabkan isu environment saat transisi kripto lokal.
- **Solution**: 
  - Mendeploy dan mengaktifkan worker 24/7 di OCI VM menggunakan systemd (dor-worker).
  - Membangun fungsi _notify_telegram() mandiri di dalam worker.py menggunakan pustaka equests.
  - Sistem kini menarik 
otify_chat_id secara dinamis langsung dari tabel Supabase uto_renew_accounts.
- **Result**: Worker mengeksekusi loop pemeriksaan secara persisten dan langsung memancarkan notifikasi sukses/gagal ke bot Telegram pengguna secara *real-time*.

## 3. Hardening & Stabilitas Worker (Safe-Fail)
- **Problem**: Kegagalan API Telegram (timeout, chat ID tidak valid, atau penolakan markup) berisiko memicu exception yang bisa merusak perulangan (loop) worker.
- **Solution**: 
  - Membungkus pengiriman notifikasi dengan blok 	ry-except ketat.
  - Menambahkan *fallback retry* untuk menghilangkan tag parse_mode HTML apabila Telegram menolak pesan akibat format karakter invalid (HTTP 400 Bad Request).
- **Result**: Daemon tahan banting. Apapun yang terjadi pada API eksternal, worker tidak akan pernah mati.

## 4. Keamanan Pembelian (DRY RUN Guard)
- **Problem**: Pengujian atau *debugging* pada fungsi jalur pembelian berisiko melewati logika ambang batas (threshold) dan memotong pulsa riil secara prematur.
- **Solution**: Menambahkan flag pengaman DRY_RUN di pp/service/auto_renew.py (pada level uy_addon()).
- **Result**: Saat DRY_RUN=1 diaktifkan di dalam environment (hanya untuk pengujian/debug), payload dan enkripsi divalidasi penuh namun eksekusi berhenti tepat sebelum menembakkan *request settlement*. (Catatan: flag ini **dimatikan** di lingkungan *production* VM agar proses auto-renew berjalan normal).

## 5. Rekonsiliasi Database (Ledger)
- Mengonfirmasi pencatatan historis yang presisi. Setiap mutasi pembelian kini dicatat langsung ke tabel uto_renew_transactions, memastikan laporan riwayat (termasuk kompensasi *manual insertion* diagnostik) konsisten dengan pemotongan saldo pulsa pengguna.


## 6. Stealth Layers: Jitter, Backoff Dini Hari, Token Cache, Multi-Account Staggering
- **Problem**: Worker polling dengan interval statis (10 mnt / 3 mnt) terlihat seperti *background scraper* oleh WAF XL; setiap siklus selalu me-refresh token ke CIAM (boros request auth); dan banyak akun diproses serempak (rentan burst / rate-limit).
- **Solution**:
  - **Random jitter polling**: interval normal menjadi acak 28–35 detik, interval kritis acak 13–18 detik (aktif saat `WORKER_POLL_NORMAL <= 60` dan `WORKER_POLL_CRITICAL <= 30`). Pola request tidak lagi statis.
  - **Backoff dini hari (02:00–06:00 WIB)**: saat kuota aman, polling dilambatkan ke 300–420 detik (5–7 mnt) untuk memutus pola 24 jam non-stop; bila kuota kritis, interval tetap gesit agar auto-renew tidak telat.
  - **Token cache in-memory per subscriber_id** (TTL 8 menit = 480 detik sesuai lifespan `id_token` CIAM): `_get_cached_token()` dipakai sebelum memanggil CIAM, hanya refresh saat TTL habis. Auto-fallback: cache dibersihkan dan token di-refresh saat respons mengindikasikan 401/token invalid (`_looks_like_token_error`). Supabase hanya di-PATCH saat refresh token benar-benar berotasi.
  - **Multi-account staggering**: jeda acak 1,5–3,0 detik antar akun di `run_auto_renew()` agar tidak terjadi burst request serempak ke API XL.
- **Result**: Terverifikasi di VPS OCI — log menunjukkan `polling normal 28-35s (jitter), kritis 13-18s (jitter), ambang kritis 50 MB, sleep dini hari 02:00-06:00 WIB aktif`; token hanya di-refresh sekali saat cold start lalu dipakai dari cache pada siklus berikutnya; semua akun `1 ok` tanpa error; service stabil (`NRestarts=0`).


## 7. Rotasi Log Harian worker.log (Systemd Timer @ 00:00 WIB)
- **Problem**: `worker.log` memakai mode `append:` systemd sehingga menumpuk tanpa batas; user hanya butuh progress 24 jam terakhir (00:00–23:59 WIB).
- **Solution**: Unit systemd baru di VPS OCI:
  - `dor-worker-logrotate.timer` → `OnCalendar=*-*-* 17:00:00 UTC` (`Persistent=true`), yang bertepatan dengan **00:00 WIB**.
  - `dor-worker-logrotate.service` (oneshot) menjalankan `deploy/OCI/rotate_worker_log.sh`.
  - Script: `cp worker.log → worker.log.old`, lalu `truncate -s 0 worker.log` (inode & file descriptor worker tetap valid — worker tidak perlu restart), lalu menulis marker `[.... WIB] === NEW 24H LOG CYCLE STARTED ===`.
- **Result**: Terverifikasi di VPS — `worker.log` selalu berisi data hari ini saja; `worker.log.old` menyimpan 1 hari sebelumnya sebagai cadangan; worker tetap `active` dan menulis normal setelah truncate; timer tampil di `systemctl list-timers` dengan NEXT `17:00:00 UTC`. Artefak disimpan di `deploy/OCI/` (terversi git).
