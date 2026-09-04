# Deploy Worker DOR-XL ke VM OCI — Monitoring, systemd, smoke test

> Konteks: memigrasikan worker auto-renew DOR-XL dari Vercel cron ke VM OCI
> (`129.225.2.6`, Ubuntu, akses SSH `ubuntu@129.225.2.6`).
> **Status crypto service `me-crypto.mashu.lol`: DOWN (DNS `gaierror`), belum pulih.**

Folder ini berisi artefak yang harus **di-copy ke VM** lalu dijalankan di sana.
Karena private key lokal tidak tersedia untuk tooling ini, seluruh artefak ditulis
di sini (repo) dan deployment dilakukan manual lewat SSH/scp.

---

## 0. Prasyarat di VM

- Repo sudah di-clone di VM (mis. `~/DOR XL`, `~/dor-xl`, dst.—deteksi otomatis).
- `.venv` sudah dibuat: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- `.env` di repo berisi **semua** variabel yang dipakai worker:

| Variabel | Diperlukan |
|----------|-----------|
| `SUPABASE_URL` | worker (`auto_renew.SupabaseStore`) |
| `SUPABASE_SERVICE_ROLE_KEY` | worker (`auto_renew.SupabaseStore`) |
| `API_KEY` (atau `USER_API_KEY`) | worker → `encrypt.API_KEY` (`x-api-key`) |
| `AES_KEY_ASCII` | enkripsi payload |
| `AX_FP_KEY` | fingerprint |
| `BASE_API_URL` | `engsel.send_api_request` |
| `UA` | user-agent XL |

> **PENTING:** `nslookup` tidak terpasang di VM. Semua skrip di sini memakai
> `python3 socket` + `urllib` (stdlib), jadi tidak butuh dependency tambahan.

---

## 1. Copy artefak ke VM

Dari mesin lokal (sesuaikan path key):

```bash
scp -i /path/ke/ssh-key-2026-09-01.key \
  deploy/OCI/monitor_crypto.sh \
  deploy/OCI/install_monitor.sh \
  deploy/OCI/smoke_worker.sh \
  deploy/OCI/dor-worker.service.template \
  deploy/OCI/install_worker_service.sh \
  ubuntu@129.225.2.6:~/dor-xl-deploy/
```

Atau `pscp` (PuTTY). Sesuaikan path repo di VM lewat `REPO_DIR`.

---

## 2. Monitoring kapan crypto service pulih

Pasang cron tiap 5 menit di VM:

```bash
cd ~/dor-xl-deploy
bash install_monitor.sh
# verifikasi
crontab -l
bash monitor_crypto.sh; echo "exit=$?"   # sekarang harus exit=1 (DOWN)
```

Hasilnya ditulis ke `$HOME/dor-xl/monitor/crypto_health.log`:

```
2026-09-01 10:15:00 WIB status=DOWN dns=DOWN(none) http=DOWN(none)
```

Begitu `status=UP dns=UP(203.x.x.x) ...` muncul → service pulih.

**Notifikasi Telegram (opsional):** export `TELEGRAM_BOT_TOKEN` dan
`TELEGRAM_CHAT_ID` (mis. di `~/.bashrc`) maka saat transisi DOWN→UP skrip kirim
pesan. Tanpa itu, cukup pantau log.

### Alternatif (tanpa cron), tail manual setiap beberapa jam
```bash
tail -n 40 ~/dor-xl/monitor/crypto_health.log
```

---

## 3. Smoke test worker — cek kapan pulih

```bash
cd ~/dor-xl-deploy
bash smoke_worker.sh
# selama DOWN: "... [worker] 1 diproses | 0 ok, 1 error ..."
# setelah pulih: "... [worker] 1 diproses | 1 ok ..."
```

Ini menjalankan `worker.py --once` (satu siklus, tidak loop). Bisa juga dijadwalkan
via cron setiap beberapa jam untuk titik data otomatis.

---

## 4. Aktifkan worker via systemd

**HAKUS menunggu** sampai smoke test menghasilkan `1 ok, 0 error` (crypto pulih).
Jangan aktifkan lebih awal — worker akan terus mencatat error (tidak crash, tapi
mengotoris log).

```bash
cd ~/dor-xl-deploy
REPO_DIR=/home/ubuntu/dor-xl bash install_worker_service.sh
# lalu
sudo systemctl enable --now dor-worker.service
systemctl status dor-worker.service
journalctl -u dor-worker.service -f
```

### Detail unit
- `User=ubuntu`, `Group=ubuntu`, `WorkingDirectory=<repo>`.
- `ExecStart=<repo>/.venv/bin/python worker.py`, `Restart=always`, `RestartSec=15`.
- `RuntimeMaxSec=86400` → restart bersih tiap 24 jam (bisa dihapus bila tidak diinginkan).
- Log ke `worker.log` (append).

---

## 5. Setelah worker live — matikan cron Vercel

Nonaktifkan route cron `/api/cron/auto-refill` di Vercel agar tidak terjadi
pembelian ganda (cron harian + worker polling). Toggle ke OFF di dashboard/vercel.json.

---

## 6. Ringkasan keputusan (root cause)

- **Gejala:** `run_auto_renew` gagal dengan `1 error`; `last_error` =
  `NameResolutionError` (DNS gagal resolve `me-crypto.mashu.lol`).
- **Bukan** token/format nomor/CIAM. Semua request API XL lewat
  `encryptsign_xdata` → `send_api_request`, jadi satu service mati = semua mati.
- **Outage global, bukan VM.** VM resolve `google.com` OK, `me-crypto.mashu.lol`
  gagal. Dari jaringan lain juga gagal.
- **Domain `mashu.lol` masih aktif** (expires 2026-08-30, NS Cloudflare), repo
  upstream `purplemashu/me-cli` masih memakai domain yang sama → **bukan migrasi
  domain**, melainkan **outage sementara** (record `me-crypto` di Cloudflare hilang).
- **Keputusan:** tunggu & monitor (Opsi A). Self-host / ganti service adalah Opsi B
  berisiko tinggi (API key terikat ke service mashu.lol, perlu reverse-engineer).

---

## Catatan & risiko

- **Tidak ada perubahan kode di `app/client/encrypt.py:17`** — domain dibiarkan
  karena outage, bukan migrasi. Kalau ternyata **permanen** (> 48 jam), barulah
  evaluasi ganti `BASE_CRYPTO_URL` / self-host.
- Worker **tidak crash** saat crypto mati (`tick()` menangkap exception), jadi
  aman dibiarkan selalu-on; hanya log yang penuh error selama DOWN.
- Vercel cron **jangan dimatikan dulu** sampai crypto pulih & worker terbukti
  `1 ok`; kedua sumber pakai `encryptsign` yang sama.
