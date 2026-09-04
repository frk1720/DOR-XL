---
name: shipping-and-launch
description: Menyiapkan release/deployment yang observable, reversible, dan aman. Gunakan untuk production launch, migration, rollout, atau perubahan berisiko.
---

# Shipping and Launch

## Tujuan

Deployment bukan selesai saat command deploy berhasil. Release harus memiliki bukti kualitas, observability, rollback, dan pemahaman tentang kondisi sukses.

## Proses

1. **Release scope** — Catat perubahan, owner, dependency, compatibility, migration, risk, success metric, dan abort condition.
2. **Quality gate** — Pastikan test relevan, build, typecheck, lint, review, error handling, dan tidak ada debug/placeholder yang tertinggal.
3. **Security gate** — Pastikan tidak ada secret, input/authz control, dependency audit, security headers, CORS, dan rate limit yang diperlukan.
4. **Operational readiness** — Pastikan environment variable/binding, migration, health check, logging, error reporting, metrics, alert, dan runbook tersedia.
5. **Rollback plan** — Tulis trigger, langkah rollback code/flag, database compatibility/restore, owner, dan estimasi waktu. Migration harus backward-compatible atau memiliki recovery plan.
6. **Staged rollout** — Jika risikonya berarti, deploy ke staging, smoke test, production dengan flag off/canary, monitor baseline, lalu naikkan exposure bertahap. Feature flag memiliki owner dan expiry.
7. **Post-launch check** — Periksa health, error rate, latency, resource, critical flow, logs, dan business metric pada window awal.
8. **Closeout** — Dokumentasikan hasil, issue, keputusan, dan hapus feature flag/dead path sesuai lifecycle-nya.

## Exit criteria

- [ ] Scope, owner, success metric, dan abort condition jelas.
- [ ] Test/build/type/lint/review/security gate yang relevan lulus.
- [ ] Config, migration, health check, monitoring, dan alert siap.
- [ ] Rollback code/flag/database tertulis dan dapat dilakukan.
- [ ] Rollout stage dan monitoring window ditentukan.
- [ ] Feature flag punya owner/expiry jika digunakan.
- [ ] Post-launch verification dilakukan dan hasil dicatat.

## Red flags

- Deploy tanpa rollback plan.
- Menganggap staging identik dengan production.
- Feature flag tanpa owner atau expiry.
- Migration irreversible tanpa backup/recovery.
- Tidak ada health check atau error monitoring.
- Big-bang release pada perubahan berisiko.

## Anti-rationalization

| Alasan untuk melewati | Kenyataannya |
|---|---|
| “Perubahannya kecil” | Perubahan kecil tetap dapat memutus production boundary; ukur risiko, bukan jumlah baris. |
| “Rollback nanti saja” | Saat incident, langkah yang belum ditulis sering terlambat atau salah. |
| “Monitoring bisa ditambahkan nanti” | Tanpa observability, failure ditemukan dari user dan sulit dilokalisasi. |
