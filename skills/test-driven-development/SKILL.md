---
name: test-driven-development
description: Mengembangkan dan mengubah perilaku dengan siklus RED-GREEN-REFACTOR. Gunakan untuk logic baru, bug fix, regression, edge case, dan perubahan contract.
---

# Test-Driven Development

## Tujuan

Test adalah bukti perilaku, bukan formalitas. Setiap perubahan perilaku harus memiliki guard yang gagal sebelum fix dan lulus sesudahnya bila surface dapat diuji.

## Kapan digunakan

- Menambah logic atau endpoint.
- Mengubah perilaku yang sudah ada.
- Memperbaiki bug atau error.
- Menambah validasi dan edge-case handling.

Dokumentasi murni dan konfigurasi statis tanpa perubahan perilaku boleh memakai verifikasi ringan.

## Proses

1. **Discover stack** — Identifikasi language, package manager, framework, test runner, lokasi test, focused-test command, full suite, build, typecheck, dan lint dari file project/CI. Jangan mengasumsikan `npm test`.
2. **RED** — Tulis test yang mendeskripsikan outcome. Untuk bug, test harus mereproduksi failure dan benar-benar gagal. Jika test langsung lulus, periksa apakah ia membuktikan bug.
3. **GREEN** — Implementasikan perubahan minimum yang membuat test lulus. Jangan menambahkan abstraksi yang belum diperlukan.
4. **REFACTOR** — Bersihkan nama, duplication, dan struktur tanpa mengubah behavior; jalankan test setelah tiap langkah berarti.
5. **Layer test** — Unit untuk pure logic, integration untuk boundary/API/database, E2E hanya untuk critical user flow. Utamakan implementasi nyata; gunakan mock hanya untuk dependency eksternal, lambat, non-deterministik, atau side effect.
6. **Verify regression** — Jalankan focused test lalu suite relevan. Jalankan build/typecheck/lint sesuai repository. Smoke-test surface aktual bila tersedia.
7. **Report evidence** — Catat command dan hasil; failure mengikuti `debugging-and-error-recovery`, bukan diabaikan.

## Exit criteria

- [ ] Test menguji outcome dan nama test menjelaskan perilaku.
- [ ] Bug fix memiliki regression test jika dapat diuji.
- [ ] RED teramati atau alasan teknisnya tercatat.
- [ ] GREEN dan refactor tetap lulus.
- [ ] Boundary, error path, dan edge case yang relevan tercakup.
- [ ] Focused test, suite relevan, dan check build/type/lint dijalankan sesuai project.
- [ ] Tidak ada test yang dihapus atau dilemahkan untuk menyembunyikan failure.

## Red flags

- Kode ditulis lebih dahulu.
- Test hanya memeriksa internal call sequence atau mock.
- Semua test dilewati karena “perubahan kecil”.
- Bug fix tanpa reproducer/regression guard.
- Test lulus karena tidak pernah menjalankan assertion yang bermakna.

## Anti-rationalization

| Alasan untuk melewati | Kenyataannya |
|---|---|
| “Saya yakin fix-nya benar” | Test reproduksi membedakan tebakan benar dari root cause yang sebenarnya. |
| “Nanti test ditambahkan” | Setelah implementasi, test cenderung mengikuti kode dan melewatkan kontrak yang salah. |
| “Mock lebih cepat” | Mock berlebihan dapat lulus ketika implementasi nyata rusak. |
