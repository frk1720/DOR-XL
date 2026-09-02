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
