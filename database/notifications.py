"""Sous-module database — notifications des joueurs (cloche du site).

Remplace les messages privés/annonces Discord pour les événements qui concernent un joueur
précis : vente d'un Pokémon, surenchère, défi reçu, échange proposé, niveau gagné...
`notifier` ne lève jamais d'exception : une notification ratée ne doit jamais casser une
action de jeu."""

import time

from . import get_connexion

MAX_PAR_JOUEUR = 100


def _init(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, type TEXT NOT NULL,
            titre TEXT NOT NULL, texte TEXT NOT NULL DEFAULT '', lien TEXT, cle TEXT,
            cree_a INTEGER NOT NULL, lu INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications (user_id, lu, id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notif_cle ON notifications (user_id, cle) WHERE cle IS NOT NULL")


def notifier(user_id: int, type_: str, titre: str, texte: str = "", lien: str | None = None, cle: str | None = None) -> bool:
    """Crée une notification. `cle` évite les doublons (une seule notification par clé et joueur)."""
    if not isinstance(user_id, int) or user_id <= 0 or user_id >= 10**18 * 2:
        return False
    try:
        conn = get_connexion()
        try:
            _init(conn)
            cur = conn.execute(
                "INSERT OR IGNORE INTO notifications (user_id, type, titre, texte, lien, cle, cree_a) VALUES (?,?,?,?,?,?,?)",
                (user_id, type_, titre[:120], texte[:300], lien, cle, int(time.time())))
            if cur.rowcount:
                conn.execute(
                    "DELETE FROM notifications WHERE user_id = ? AND id NOT IN (SELECT id FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
                    (user_id, user_id, MAX_PAR_JOUEUR))
            conn.commit()
            return bool(cur.rowcount)
        finally:
            conn.close()
    except Exception:
        return False


def lister_notifications(user_id: int, limite: int = 30) -> list:
    conn = get_connexion()
    try:
        _init(conn)
        rows = conn.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def compter_notifications_non_lues(user_id: int) -> int:
    conn = get_connexion()
    try:
        _init(conn)
        return conn.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND lu = 0", (user_id,)).fetchone()["n"]
    finally:
        conn.close()


def marquer_notifications_lues(user_id: int, notif_id: int | None = None):
    conn = get_connexion()
    try:
        _init(conn)
        if notif_id is None:
            conn.execute("UPDATE notifications SET lu = 1 WHERE user_id = ? AND lu = 0", (user_id,))
        else:
            conn.execute("UPDATE notifications SET lu = 1 WHERE user_id = ? AND id = ?", (user_id, notif_id))
        conn.commit()
    finally:
        conn.close()


def vider_notifications(user_id: int):
    conn = get_connexion()
    try:
        _init(conn)
        conn.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
