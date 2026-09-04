---
name: spec-driven-development
description: Membuat spesifikasi sebelum implementasi. Gunakan untuk feature baru, perubahan signifikan, requirement ambigu, atau perubahan yang menyentuh beberapa module.
---

# Spec-Driven Development

## Tujuan

Menjadikan spesifikasi sebagai sumber kebenaran bersama sebelum kode diubah. Jangan mengubah kode ketika tujuan, batasan, atau definisi selesai masih berupa asumsi.

## Kapan digunakan

- Feature baru atau perubahan yang menyentuh lebih dari satu file/module.
- Requirement ambigu, terlalu umum, atau memiliki beberapa interpretasi.
- Perubahan arsitektur, API, data model, auth, atau integrasi eksternal.
- Pekerjaan yang diperkirakan memerlukan lebih dari 30 menit.

Untuk typo, dokumentasi murni, atau perubahan satu baris dengan tujuan jelas, gunakan acceptance criteria ringkas tanpa spec panjang.

## Proses

1. **Scope check** — Jika request berisi beberapa capability yang dapat diuji dan dirilis terpisah, buat capability map berisi module id, tanggung jawab, dependency, dan build order.
2. **Surface assumptions** — Tulis asumsi tentang user, platform, stack, data, compatibility, dan target. Tandai pertanyaan yang memerlukan keputusan manusia.
3. **Define success** — Ubah kata seperti “bagus”, “cepat”, atau “aman” menjadi kondisi yang dapat diamati dan diuji.
4. **Tulis spec** — Jika project memiliki konvensi spec, ikuti itu. Jika tidak, gunakan `SPEC-<feature>.md` atau lokasi dokumentasi yang sudah ada. Minimal berisi:
   - Objective dan user impact.
   - Scope dan non-goals.
   - Commands build/test/dev yang terdeteksi.
   - Project structure dan code conventions.
   - Testing strategy.
   - Boundaries: Always, Ask first, Never.
   - Acceptance/success criteria.
   - Open questions dan risiko.
5. **Gate** — Jangan masuk `PLAN` sebelum spec dan asumsi tervalidasi oleh user atau jelas dari konteks. Jika keputusan manusia benar-benar diperlukan, berhenti pada pertanyaan spesifik.
6. **Keep alive** — Perbarui spec lebih dulu jika scope, keputusan arsitektur, atau success criteria berubah.

## Exit criteria

- [ ] Objective, scope, non-goals, dan user impact jelas.
- [ ] Success criteria spesifik, observable, dan testable.
- [ ] Commands dan struktur project didasarkan pada repository, bukan asumsi.
- [ ] Batasan Always/Ask first/Never tertulis.
- [ ] Risiko dan open questions ditandai.
- [ ] Spec tersimpan dan disetujui sebelum implementation plan.
- [ ] Capability map disetujui lebih dahulu bila request multi-capability.

## Red flags

- Agent mulai coding sebelum spec tersedia.
- Spec hanya mengulang requirement tanpa acceptance criteria.
- Asumsi penting disembunyikan.
- Satu spec mencampur capability independen tanpa dependency map.

## Anti-rationalization

| Alasan untuk melewati | Kenyataannya |
|---|---|
| “Fiturnya sederhana” | Spec boleh pendek, tetapi tujuan dan acceptance criteria tetap harus jelas. |
| “Requirement pasti berubah” | Spec memang living document; perubahan harus terlihat sebelum kode ikut berubah. |
| “Saya bisa memutuskan sambil coding” | Itu memindahkan keputusan mahal ke tahap paling sulit untuk dikoreksi. |
