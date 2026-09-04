---
name: code-review-and-quality
description: Melakukan review perubahan pada lima dimensi sebelum merge: correctness, readability, architecture, security, dan performance.
---

# Code Review and Quality

## Tujuan

Menilai apakah perubahan benar-benar meningkatkan kesehatan codebase dan memenuhi acceptance criteria, bukan hanya apakah build berhasil.

## Proses

1. **Understand context** — Baca request/spec/plan dan definisikan behavior yang seharusnya berubah.
2. **Review tests first** — Pastikan test menguji outcome, error path, boundary, edge case, dan regression yang tepat.
3. **Review implementation** pada lima axis:
   - **Correctness** — contract, state transition, null/empty/boundary, concurrency, error handling.
   - **Readability** — nama, control flow, duplication, dead code, abstraksi yang benar-benar diperlukan.
   - **Architecture** — module boundary, dependency direction, ownership, type boundary, caller compatibility.
   - **Security** — validation, authz, secrets, injection, output encoding, external data, dependency risk.
   - **Performance** — N+1, unbounded work, sync I/O, rerender, pagination, allocation, query/index.
4. **Inspect integration** — Periksa diff, callsites, exported symbols dengan LSP bila tersedia, migration/config/docs, dan unexpected files.
5. **Use structural remedies** — Untuk masalah structural, usulkan dispatcher/model, pemisahan orchestration, pemindahan logic ke owner, penghapusan wrapper, atau pemecahan module. Jangan hanya menyebut “terlalu kompleks”.
6. **Classify findings** — Urutkan Critical/Required lebih dahulu, lalu Optional/Nit/FYI. Jangan rubber-stamp.
7. **Verify verification** — Cocokkan klaim test/build/smoke dengan bukti aktual. Review bukan pengganti test.

## Exit criteria

- [ ] Context dan expected behavior dipahami.
- [ ] Test quality dan coverage boundary ditinjau.
- [ ] Lima axis review selesai.
- [ ] Callsite, diff, dead code, dependency, dan docs relevan diperiksa.
- [ ] Temuan diberi severity dan remedy yang konkret.
- [ ] Critical/Required findings terselesaikan atau eksplisit diblokir.
- [ ] Tidak ada klaim “approved” tanpa evidence verification.

## Red flags

- Review hanya memeriksa formatting/build.
- Review hanya memberi “LGTM” tanpa evidence.
- Structural issue ditutup dengan conditional tambahan.
- Feature-specific logic bocor ke shared module.
- Backward compatibility dan caller tidak diperiksa.

## Anti-rationalization

| Alasan untuk melewati | Kenyataannya |
|---|---|
| “Test lulus berarti aman” | Test tidak otomatis menemukan masalah arsitektur, security, dan performance. |
| “Ini hanya perubahan kecil” | Perubahan kecil pada boundary dapat berdampak besar; gunakan review ringkas tetapi tetap lima axis. |
| “Nanti dirapikan” | Deferred cleanup biasanya menjadi permanent debt. |
