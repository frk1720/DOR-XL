---
name: security-and-hardening
description: Mengidentifikasi dan mengurangi risiko pada input, auth, data sensitif, upload, webhook, API eksternal, dan output model. Gunakan pada setiap trust boundary.
---

# Security and Hardening

## Prinsip

Semua input eksternal, output LLM, log, error, webhook, dan response API pihak ketiga adalah data tidak tepercaya. Secret tidak boleh masuk source, log, test fixture publik, atau output user.

## Proses

1. **Map trust boundaries** — Tandai HTTP/form, file upload, webhook, queue, database, third-party API, browser, CLI, dan LLM output.
2. **Name assets** — Identifikasi credential, PII, payment data, session, admin action, money movement, dan availability yang harus dilindungi.
3. **Threat model** — Gunakan STRIDE secara ringkas: spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege.
4. **Write abuse cases** — Untuk setiap use case penting, tulis cara penyalahgunaan yang paling mungkin dan jadikan test/control.
5. **Harden boundaries** — Validasi schema, ukuran, tipe, dan encoding input; parameterize query; enforce authentication dan authorization; gunakan least privilege; batasi timeout/rate/redirect; encode output; cegah SSRF; gunakan secure cookie dan security headers sesuai stack.
6. **Protect operations** — Secret lewat environment/binding aman; error publik generik; log terstruktur tanpa token/PII; audit event security; dependency audit memakai package manager project.
7. **Review exceptions** — Auth flow, PII baru, external integration, CORS, upload, rate limit, role/permission, migration security, dan perubahan header memerlukan keputusan serta risiko tertulis.
8. **Verify** — Jalankan security-focused test/check, dependency audit yang relevan, dan smoke test negative path. Jangan menganggap client-side validation sebagai boundary.

## Always / Ask first / Never

### Always

- Validasi input di server/boundary.
- Enforce authorization, bukan hanya authentication.
- Parameterize database query.
- Simpan secret di secret manager/environment.
- Hindari stack trace dan data sensitif di response/log.

### Ask first

- Auth/session/permission baru atau berubah.
- PII/payment data baru.
- Integrasi eksternal, upload, CORS, rate limiting.
- Perubahan schema atau retention data sensitif.

### Never

- Commit secret.
- Trust client validation.
- Menjalankan `eval`/unsafe HTML dengan input user.
- Menyimpan auth token di client-accessible storage tanpa alasan dan mitigasi kuat.
- Mematikan security control demi kemudahan.

## Exit criteria

- [ ] Trust boundary, asset, dan abuse case relevan terdokumentasi.
- [ ] Input, output, authz, secret, error, dan dependency controls ditinjau.
- [ ] Negative path/security tests atau observasi dijalankan.
- [ ] High/critical risk tidak dibiarkan tanpa keputusan eksplisit.
- [ ] Tidak ada secret/PII dalam diff, fixture, log, atau laporan.
- [ ] Exception dan residual risk dicatat.

## Red flags

- Endpoint baru tanpa authorization check.
- URL user langsung di-fetch server.
- SQL/query dibangun dengan concatenation.
- Error internal dikirim ke user.
- Wildcard CORS, insecure cookie, atau rate limit dihapus tanpa threat model.
