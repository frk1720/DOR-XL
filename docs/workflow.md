# Workflow Engineering DOR XL

Repository ini menggunakan `AGENTS.md` sebagai kontrak project dan folder `skills/` sebagai workflow reusable. Keduanya berasal dari `omp-project-template` dan telah disesuaikan untuk CLI Python, Telegram bot, serta deployment Flask/Vercel DOR XL.

## Struktur

```text
DOR-XL/
├── AGENTS.md
├── skills/
│   ├── spec-driven-development/
│   ├── planning-and-task-breakdown/
│   ├── test-driven-development/
│   ├── debugging-and-error-recovery/
│   ├── code-review-and-quality/
│   ├── security-and-hardening/
│   └── shipping-and-launch/
├── docs/
│   └── workflow.md
├── app/
├── api/
├── main.py
└── bot.py
```

## Lifecycle

Untuk perubahan non-trivial, gunakan:

```text
DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP
```

- `DEFINE`: tujuan, scope, non-goals, acceptance criteria, asumsi, dan risiko.
- `PLAN`: struktur source, dependency, caller, urutan implementasi, dan command verifikasi.
- `BUILD`: perubahan minimum mengikuti pola kode yang sudah ada.
- `VERIFY`: compile check, test yang tersedia, dan smoke test surface aktual.
- `REVIEW`: correctness, readability, architecture, security, performance, callsites, dan diff.
- `SHIP`: hanya untuk deployment, migration, atau release; sertakan monitoring dan rollback.

## Routing skill

| Intent | Skill |
|---|---|
| Feature baru atau requirement ambigu | `spec-driven-development` |
| Memecah pekerjaan multi-file | `planning-and-task-breakdown` |
| Mengubah behavior atau memperbaiki bug | `test-driven-development` |
| Test/build/runtime failure | `debugging-and-error-recovery` |
| Review sebelum merge | `code-review-and-quality` |
| Input, auth, PII, webhook, API eksternal | `security-and-hardening` |
| Release, deployment, migration, rollout | `shipping-and-launch` |

Jika beberapa kondisi berlaku, gunakan semua skill yang relevan. Skill memberi prosedur; `AGENTS.md` dan verifikasi runtime project tetap menjadi sumber keputusan.

## Command verifikasi

```text
Install: pip install -r requirements.txt
Compile check: python -m compileall -q .
CLI smoke: python main.py
HTTP smoke: flask --app api.index:app run
Bot runtime: python bot.py
Tests: belum ada test runner atau test suite di repository ini
```

Entry point interaktif atau bot memerlukan environment yang valid. Jangan menjalankan command tersebut dengan credential yang tidak dimaksudkan untuk testing.

## Konvensi pekerjaan

- Source berada di `app/` dan `api/`.
- Dependency berada di `requirements.txt`.
- Konfigurasi deployment berada di `vercel.json`.
- Secret lokal seperti `.env`, `api.key`, token, dan file session tetap di-ignore Git.
- Bila test harness belum tersedia, lakukan smoke test langsung pada surface yang berubah dan catat batasannya.
- Untuk spec atau plan yang benar-benar diperlukan, gunakan konvensi `SPEC-<feature>.md`, `tasks/plan.md`, dan `tasks/todo.md`; jangan memasukkan credential atau data operasional.

## Update workflow

Perubahan pada aturan project harus dilakukan di `AGENTS.md`. Perubahan reusable pada skill perlu ditinjau agar tidak mengubah perilaku agent secara diam-diam. Setiap perubahan workflow harus diverifikasi dengan membaca file yang berubah dan menjalankan command yang relevan.
