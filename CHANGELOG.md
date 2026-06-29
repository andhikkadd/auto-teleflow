# Changelog

Semua perubahan penting pada proyek ini akan dicatat di dalam berkas ini.

---

## [1.0.0] - 2026-05-31

### Added
- **Bootstrap Login**: Otentikasi interaktif pertama kali via konsol menggunakan OTP dan password 2FA, dengan penyimpanan berkas sesi aman di folder `sessions/`.
- **Database SQLite**: Layer persistensi menggunakan SQLite di `data/bot.db` yang terintegrasi dengan thread-executor asinkron untuk performa maksimal.
- **Background Scheduler**: Mesin penjadwalan wave otomatis berbasis delay menit acak dengan dukungan responsive-sleep.
- **Anti Double-Wave Lock**: Proteksi anti tumpang tindih wave promosi untuk menghindari spamming.
- **GPG AES256 Backup**: Pencadangan berkas sumber, database, dan sesi yang terenkripsi aman menggunakan kata sandi yang disalurkan via stdin.
- **Monitor Performa**: Modul status server untuk melacak penggunaan CPU, RAM, Disk, dan Uptime.
- **Sistem Otorisasi Master**: Pembatasan akses command Telegram yang ketat berbasis ID dan username admin.
- **Dokumentasi Lengkap**: Panduan deploy umum, diagram arsitektur, panduan keamanan, troubleshooting, alur git, dan perintah manual.
