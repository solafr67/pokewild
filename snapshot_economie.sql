-- =====================================================================
-- Snapshot économique — distribution des soldes de Poké Dollars
-- À relancer dans 1-2 semaines pour comparer l'effet du nerf Exploration
-- (voir /areas/pokewild.md ou la conv du 11/08/2026 pour le contexte)
--
-- Utilisation : sqlite3 pokebot.sqlite3 < snapshot_economie.sql
-- (ou copier-coller chaque requête une par une en SSH)
-- =====================================================================

-- 1) Vue d'ensemble globale (tous joueurs ayant une ligne 'users')
SELECT
    COUNT(*)                                   AS nb_joueurs_total,
    ROUND(AVG(poke_dollars), 0)                AS moyenne_pd,
    MIN(poke_dollars)                          AS min_pd,
    MAX(poke_dollars)                          AS max_pd,
    SUM(poke_dollars)                          AS masse_monetaire_totale
FROM users;

-- 2) Médiane (SQLite n'a pas de fonction MEDIAN native, on la calcule à la main)
SELECT poke_dollars AS mediane_pd
FROM users
ORDER BY poke_dollars
LIMIT 1
OFFSET (SELECT COUNT(*) FROM users) / 2;

-- 3) Uniquement les joueurs ACTIFS récemment (au moins 1 capture dans les 7 derniers
--    jours) — le vrai indicateur qui compte, les comptes abandonnés à 0 PD ou avec un
--    vieux pactole faussent sinon la moyenne dans les deux sens.
SELECT
    COUNT(*)                                   AS nb_joueurs_actifs_7j,
    ROUND(AVG(u.poke_dollars), 0)              AS moyenne_pd_actifs,
    MIN(u.poke_dollars)                        AS min_pd_actifs,
    MAX(u.poke_dollars)                        AS max_pd_actifs
FROM users u
WHERE u.user_id IN (
    SELECT DISTINCT user_id FROM captures
    WHERE date_capture > CAST(strftime('%s','now') AS INTEGER) - 7*86400
);

-- 4) Répartition par tranches (pour voir la FORME de la distribution, pas juste la
--    moyenne — utile pour repérer si quelques joueurs très riches tirent la moyenne
--    vers le haut alors que la médiane, elle, reste basse)
SELECT
    CASE
        WHEN poke_dollars < 1000        THEN '0 - 999'
        WHEN poke_dollars < 5000        THEN '1 000 - 4 999'
        WHEN poke_dollars < 15000       THEN '5 000 - 14 999'
        WHEN poke_dollars < 30000       THEN '15 000 - 29 999'
        WHEN poke_dollars < 60000       THEN '30 000 - 59 999'
        ELSE '60 000+'
    END AS tranche,
    COUNT(*) AS nb_joueurs
FROM users
GROUP BY tranche
ORDER BY MIN(poke_dollars);

-- 5) Top 10 des soldes les plus élevés (pour repérer d'éventuels cas extrêmes / abus)
SELECT user_id, poke_dollars
FROM users
ORDER BY poke_dollars DESC
LIMIT 10;
