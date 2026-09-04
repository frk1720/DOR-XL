---
name: planning-and-task-breakdown
description: Memecah spec atau requirement jelas menjadi task kecil berurutan dengan dependency, acceptance criteria, dan verifikasi. Gunakan sebelum implementasi pekerjaan non-trivial.
---

# Planning and Task Breakdown

## Tujuan

Menghasilkan rencana implementasi yang dapat dieksekusi dan diverifikasi tanpa membuat agent menebak urutan kerja atau dependency.

## Kapan digunakan

- Spec sudah ada atau requirement cukup jelas untuk direncanakan.
- Pekerjaan menyentuh beberapa file, layer, atau subsystem.
- Task terlalu besar, urutan implementasi belum jelas, atau ada peluang paralelisasi.

Perubahan satu file dengan scope dan verifikasi yang jelas boleh langsung dikerjakan.

## Proses

1. **Read-only reconnaissance** — Baca spec, struktur repository, pola tetangga, test, konfigurasi, dan command yang benar-benar tersedia. Jangan mengedit saat merencanakan.
2. **Map dependencies** — Catat fondasi, boundary/interface, consumer, migration, dan urutan dependency. Hindari cycle; letakkan contract di boundary pemiliknya.
3. **Slice vertically** — Prioritaskan slice yang menghasilkan jalur perilaku lengkap dan dapat diuji, bukan memisahkan seluruh database, API, lalu UI secara horizontal.
4. **Size tasks** — Target XS/S/M. Pecah task jika menyentuh subsystem independen, acceptance criteria terlalu banyak, atau tidak selesai dalam satu sesi fokus. Hindari task XL.
5. **Tulis setiap task** dengan format:
   - Tujuan dan file/symbol kemungkinan tersentuh.
   - Acceptance criteria yang observable.
   - Command atau observasi verifikasi.
   - Dependency dan risiko.
6. **Set checkpoints** setelah setiap 2–3 task atau phase besar: test, build, smoke test, dan keputusan lanjut.
7. **Simpan rencana** di `tasks/plan.md` dan daftar task di `tasks/todo.md`, kecuali project menetapkan tracker lain. Gunakan todo harness juga untuk status eksekusi.
8. **Gate** — Jangan BUILD sebelum dependency, acceptance criteria, verification, dan checkpoint lengkap.

## Exit criteria

- [ ] Semua task memiliki acceptance criteria.
- [ ] Semua task memiliki verifikasi yang dapat dijalankan.
- [ ] Dependency dan implementation order eksplisit.
- [ ] Tidak ada task XL; task besar sudah dipecah menjadi slice.
- [ ] Parallel work hanya diizinkan setelah contract bersama jelas.
- [ ] Checkpoint ada di antara phase penting.
- [ ] Plan dan task list tersimpan pada lokasi yang disepakati.

## Red flags

- “Implementasikan fitur” menjadi satu task tanpa detail.
- Task diurutkan berdasarkan file, bukan dependency.
- Tidak ada verification command.
- Planning menulis kode.
- Dua agent mengubah contract yang sama tanpa keputusan interface.

## Anti-rationalization

| Alasan untuk melewati | Kenyataannya |
|---|---|
| “Task-nya sudah jelas di kepala” | Task tertulis mengekspos dependency dan bertahan melewati context compaction. |
| “Planning memperlambat” | Beberapa menit planning lebih murah daripada rework lintas layer. |
| “Semua bisa dikerjakan paralel” | Shared state dan interface tetap memerlukan urutan dan contract. |
