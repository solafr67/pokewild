"""Sous-module database — domaine mini-jeu Plus ou Moins (record personnel).
Domaine isolé (vérifié par grep exhaustif avant extraction, comme roguelike.py) :
aucune fonction ailleurs dans database/ ne l'appelle, et ce fichier ne dépend
que de get_connexion."""

from . import get_connexion


def obtenir_record_plus_ou_moins(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT meilleur_score FROM record_plus_ou_moins WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["meilleur_score"] if row else 0


def definir_record_plus_ou_moins(user_id: int, score: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO record_plus_ou_moins (user_id, meilleur_score) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET meilleur_score = excluded.meilleur_score
        """,
        (user_id, score),
    )
    conn.commit()
    conn.close()
