"""Sous-module database — domaine connexion quotidienne (série de jours consécutifs,
récompense croissante). Domaine isolé (mêmes garanties que les autres extractions du
chantier de découpage) : ne dépend que de get_connexion.

`dernier_jour` est stocké comme un entier "jour UTC" (int(time.time()) // 86400), le même
découpage que _periode_id utilisé pour les quêtes journalières — cohérent avec le reste
du jeu, évite toute ambiguïté de fuseau horaire.
"""

from . import get_connexion


def obtenir_statut_connexion(user_id: int) -> dict:
    """Retourne {streak, dernier_jour} — streak=0 et dernier_jour=0 si le joueur n'a
    jamais réclamé (première connexion)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT streak, dernier_jour FROM connexion_quotidienne WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"streak": 0, "dernier_jour": 0}
    return {"streak": row["streak"], "dernier_jour": row["dernier_jour"]}


def enregistrer_connexion(user_id: int, streak: int, jour: int):
    """Enregistre la nouvelle série et le jour de la réclamation (upsert)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO connexion_quotidienne (user_id, streak, dernier_jour) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET streak = excluded.streak, dernier_jour = excluded.dernier_jour
        """,
        (user_id, streak, jour),
    )
    conn.commit()
    conn.close()
