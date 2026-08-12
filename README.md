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

# Info

## PS for Certain Indonesian mobile internet service provider

Instead of just delisting the package from the app, ensure the user cannot purchase it.
What's the point of strong client side security when the server don't enforce it?

## Terms of Service
By using this tool, the user agrees to comply with all applicable laws and regulations and to release the developer from any and all claims arising from its use.

## Contact

contact@mashu.lol
