-- =============================================================================
-- deploy/OCI/diagnose_worker.sql
-- Query Diagnostik untuk Investigasi Error Worker Auto-Renew DOR-XL
-- =============================================================================
-- Jalankan query ini di Supabase SQL Editor (Dashboard -> SQL Editor).
-- Semua query bersifat READ-ONLY (SELECT) dan AMAN dijalankan di production:
-- - Tidak mengubah/menghapus data.
-- - Tidak menampilkan kolom sensitif penuh (refresh_token sengaja TIDAK diseleksi).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. STATUS TERKINI SEMUA AKUN (Kesehatan Keseluruhan)
--    Menjawab: "Akun mana yang aktif? Kapan terakhir dicek? Apa error-nya?"
-- -----------------------------------------------------------------------------
SELECT
    id,
    number,
    enabled,
    last_status,
    substring(coalesce(last_error, '-') from 1 for 120) AS last_error_preview,
    last_checked_at,
    last_purchase_at,
    locked_until,
    CASE
        WHEN locked_until IS NOT NULL AND locked_until > now() THEN 'LOCKED'
        WHEN NOT enabled THEN 'DISABLED'
        WHEN last_status = 'ok' THEN 'HEALTHY'
        WHEN last_status = 'purchased' THEN 'PURCHASED'
        WHEN last_status = 'purchase_cooldown' THEN 'COOLDOWN'
        WHEN last_status = 'quota_unavailable' THEN 'NO_MAIN_PKG'
        WHEN last_status = 'error' THEN 'ERROR'
        ELSE 'UNKNOWN'
    END AS account_state,
    updated_at
FROM public.auto_renew_accounts
ORDER BY
    enabled DESC,
    CASE WHEN last_status = 'error' THEN 0 ELSE 1 END,
    updated_at DESC;


-- -----------------------------------------------------------------------------
-- 2. AKUN YANG BERSTATUS 'ERROR' DENGAN DETAIL LENGKAP
--    Menjawab: "Error apa persisnya yang dialami akun yang gagal?"
-- -----------------------------------------------------------------------------
SELECT
    number,
    enabled,
    last_status,
    last_error,
    last_checked_at,
    updated_at,
    round(extract(epoch from (now() - last_checked_at)) / 60, 1) AS menit_sejak_cek_terakhir
FROM public.auto_renew_accounts
WHERE last_status = 'error'
ORDER BY updated_at DESC;


-- -----------------------------------------------------------------------------
-- 3. RINGKASAN AGREGAT PER STATUS
--    Menjawab: "Berapa total akun di tiap status? (ok/error/cooldown/skip)"
-- -----------------------------------------------------------------------------
SELECT
    coalesce(last_status, '(belum pernah dicek)') AS last_status,
    enabled,
    count(*) AS total_akun,
    count(*) FILTER (WHERE locked_until > now()) AS sedang_terkunci
FROM public.auto_renew_accounts
GROUP BY last_status, enabled
ORDER BY enabled DESC, total_akun DESC;


-- -----------------------------------------------------------------------------
-- 4. AKUN YANG SEDANG TERKUNCI (locked_until aktif)
--    Menjawab: "Apakah ada akun yang nyangkut di lock sehingga tidak diproses worker?"
-- -----------------------------------------------------------------------------
SELECT
    number,
    enabled,
    last_status,
    locked_until,
    round(extract(epoch from (locked_until - now())), 1) AS sisa_lock_detik
FROM public.auto_renew_accounts
WHERE locked_until IS NOT NULL
  AND locked_until > now()
ORDER BY locked_until DESC;


-- -----------------------------------------------------------------------------
-- 5. DAFTAR TRANSAKSI GAGAL TERBARU DARI LEDGER (20 Terakhir)
--    Menjawab: "Saat pembelian dicoba, kenapa gagal? (pulsa kurang/API reject)"
-- -----------------------------------------------------------------------------
SELECT
    id,
    number,
    option_code,
    package_name,
    amount,
    error,
    occurred_at
FROM public.auto_renew_transactions
WHERE status = 'failed'
ORDER BY occurred_at DESC
LIMIT 20;


-- -----------------------------------------------------------------------------
-- 6. HISTORI SUKSES VS GAGAL PER NOMOR (7 Hari Terakhir)
--    Menjawab: "Nomor mana yang paling sering gagal auto-renew?"
-- -----------------------------------------------------------------------------
SELECT
    number,
    count(*) FILTER (WHERE status = 'success') AS sukses_count,
    count(*) FILTER (WHERE status = 'failed')  AS gagal_count,
    max(occurred_at) FILTER (WHERE status = 'success') AS sukses_terakhir,
    max(occurred_at) FILTER (WHERE status = 'failed')  AS gagal_terakhir
FROM public.auto_renew_transactions
WHERE occurred_at >= now() - interval '7 days'
GROUP BY number
ORDER BY gagal_count DESC, sukses_count DESC;
