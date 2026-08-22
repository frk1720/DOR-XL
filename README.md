# MYnyak Engsel

![banner](bnr.png)

CLI client for a certain Indonesian mobile internet service provider.

# How to get API Key
Chat telegram bot [@fykxt_bot](https://t.me/fykxt_bot) with message `/viewkey`. Copy the API key.

# How to run with TERMUX
1. Update & Upgrade Termux
```
pkg update && pkg upgrade -y
```
2. Install Git
```
pkg install git -y
```
3. Clone this repo
```
git clone https://github.com/purplemashu/me-cli
```
4. Open the folder
```
cd me-cli
```
5. Setup
```
bash setup.sh
```
6. Run the script
```
python main.py
```
7. Input your API key when prompted

# How to run as a Telegram Bot

1. Create a bot via [@BotFather](https://t.me/BotFather) and copy the token.
2. Add it to your `.env` file:
```
BOT_TOKEN=123456:ABC-DEF...
```
3. Make sure your `.env` also contains `API_KEY` (see "How to get API Key" above).
4. Run the bot:
```
python bot.py
```
5. Open your bot on Telegram and use the commands:
   - `/login 6281234567890` — login dengan nomor XL, lalu balas dengan kode OTP
   - `/status` — cek saldo & info akun
   - `/paket` — lihat paket aktif
   - `/riwayat` — riwayat transaksi
   - `/notifikasi` — notifikasi terbaru
   - `/family` — info Family Plan/Akrab
   - `/circle` — info Circle
   - `/familycode <kode>` — lihat paket berdasarkan family code
   - `/optioncode <kode>` — detail paket berdasarkan option code
   - `/validate <nomor>` — validasi nomor msisdn
   - `/logout` — keluar dari akun

Perintah pembelian paket (beli/QRIS/ewallet) belum tersedia di bot — gunakan CLI (`python main.py`) untuk itu.

Sessions are saved per Telegram user in `tg_sessions.json`, so users stay logged in across restarts.

## Monitoring lokal multi-nomor

`auto_refill.py` dapat memproses semua akun yang tersimpan di `refresh-tokens.json`
secara sequential dalam satu proses. Tambahkan akun melalui CLI (`python main.py`),
lalu jalankan diagnostik read-only:

```powershell
python auto_refill.py --diagnose-quota
```

Perintah tersebut memeriksa setiap nomor, mencetak saldo dan seluruh quota, serta
tidak melakukan pembelian. Untuk monitoring normal yang dapat membeli add-on saat
kuota Instagram habis:

```powershell
python auto_refill.py
```

Satu siklus memproses semua nomor satu per satu, lalu menunggu 120 detik. Jangan
menjalankan dua instance lokal atau cron Vercel untuk nomor yang sama karena
keduanya dapat memicu transaksi bersamaan. Untuk otomatisasi produksi beberapa
nomor, tetap gunakan cron Vercel dengan akun di Supabase.

### Kontrak paket auto-renew online

`auto_refill.py` lokal dan service Vercel menggunakan konfigurasi paket yang
berbeda. Service online membeli paket berdasarkan `option_code` pada row
`auto_renew_accounts`, bukan berdasarkan konstanta default di `auto_refill.py`.
Pastikan `option_code` setiap nomor adalah option code add-on Instagram 3GB
seharga sesuai detail option sebelum mengaktifkan pembelian otomatis. Service online membaca
harga aktual dari detail option dan membeli ketika benefit Instagram memiliki sisa
`0 B`. Jika benefit Instagram tidak tersedia (`quota_unavailable`), sistem terlebih
dahulu memastikan paket induk aktif bernama `Xtra Combo Plus 3GB`. Jika paket induk
tersebut tidak ada atau sudah kedaluwarsa, add-on tidak dibeli.

## Auto-renew Instagram di Vercel

Pemeriksaan memicu pembelian add-on Instagram jika kuota Instagram tidak ditemukan
(`quota_unavailable`) atau sisa kuotanya `0 B`, dengan guard paket induk `Xtra Combo
Plus 3GB` untuk kasus `quota_unavailable`.

1. Buat project Supabase Free, lalu jalankan isi `supabase_schema.sql` di SQL Editor.
2. Isi tabel `auto_renew_accounts` untuk maksimal empat nomor. Simpan `option_code`
   paket Instagram yang benar untuk setiap nomor. Jangan memasukkan refresh token
   ke Git atau membagikannya.
3. Tambahkan environment variables berikut di Vercel: `BOT_TOKEN`, `API_KEY`,
   `BASE_API_URL`, `BASE_CIAM_URL`, `BASIC_AUTH`, `AX_DEVICE_ID`, `AX_FP`, `UA`,
   `AES_KEY_ASCII`, `CRON_SECRET`, `SUPABASE_URL`, dan
   `SUPABASE_SERVICE_ROLE_KEY`. Gunakan service-role key hanya di server Vercel.
4. Deploy ulang Vercel dan uji endpoint dengan header:

   `Authorization: Bearer <CRON_SECRET>`

   ke `https://domain-anda.vercel.app/api/cron/auto-refill`.
5. Buat job di cron-job.org (atau layanan cron gratis sejenis) setiap 5 atau 10
   menit. Gunakan method `POST`, URL endpoint tersebut, dan header
   `Authorization: Bearer <CRON_SECRET>`. Periksa execution time pada percobaan
   pertama. Vercel Free memiliki batas waktu function yang pendek; jika empat
   akun membuat satu invocation terlalu lama, buat empat job cron dengan jeda
   berbeda dan tambahkan parameter filter akun pada deployment berikutnya, atau
   gunakan worker gratis yang memiliki timeout lebih panjang.

Endpoint mengunci akun selama lima menit sebelum memprosesnya. Selain lock tersebut,
setiap pembelian berhasil menyimpan `last_purchase_at` dan menerapkan cooldown 30 menit.
Selama cooldown, sistem tetap memeriksa kuota tetapi tidak melakukan pembelian ulang,
sehingga keterlambatan API XL dalam menampilkan bonus baru tidak menyebabkan transaksi ganda.
Mekanisme ini mencegah dua panggilan cron bersamaan membeli paket dua kali untuk nomor
yang sama. File JSON lokal tidak dipakai sebagai sumber data auto-renew karena filesystem
Vercel tidak persisten.

Setelah login Telegram berhasil, bot sekarang otomatis memperbarui
`subscriber_id` dan `refresh_token` pada row Supabase dengan nomor yang sama.
Row tersebut harus sudah dibuat lebih dulu dan memiliki `option_code`; proses
sinkronisasi tidak membuat konfigurasi auto-renew baru secara otomatis.

Jika auto-renew gagal saat refresh token, kolom `last_error` sekarang menyimpan
alasan CIAM yang sudah disanitasi, misalnya `CIAM menolak refresh token: ...`.
Isi token tidak pernah ditulis ke log atau pesan Telegram.

# Info

## PS for Certain Indonesian mobile internet service provider

Instead of just delisting the package from the app, ensure the user cannot purchase it.
What's the point of strong client side security when the server don't enforce it?

## Terms of Service
By using this tool, the user agrees to comply with all applicable laws and regulations and to release the developer from any and all claims arising from its use.

## Contact

contact@mashu.lol
