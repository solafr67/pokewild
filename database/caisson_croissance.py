"""Sous-module database — domaine caisson de croissance (3 emplacements par joueur,
XP passive au fil du temps). Voir caisson_croissance.py pour le calcul d'XP.

Domaine isolé : ne dépend que de get_connexion.
"""

from . import get_connexion

NB_SLOTS_CAISSON = 3


def obtenir_caisson(user_id: int) -> dict:
    """Retourne {1: {pokemon_nom, date_debut} ou None, 2: ..., 3: ...} — toujours les
    NB_SLOTS_CAISSON emplacements, occupés ou non."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT slot, pokemon_nom, date_debut FROM caisson_croissance_slots WHERE user_id = ?",
        (user_id,),
    )
    occupes = {row["slot"]: {"pokemon_nom": row["pokemon_nom"], "date_debut": row["date_debut"]} for row in cur.fetchall()}
    conn.close()
    return {slot: occupes.get(slot) for slot in range(1, NB_SLOTS_CAISSON + 1)}


def deposer_caisson(user_id: int, slot: int, pokemon_nom: str, maintenant: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO caisson_croissance_slots (user_id, slot, pokemon_nom, date_debut) VALUES (?, ?, ?, ?)",
        (user_id, slot, pokemon_nom, maintenant),
    )
    conn.commit()
    conn.close()


def retirer_caisson(user_id: int, slot: int) -> dict:
    """Retire l'occupant de cet emplacement et le retourne ({pokemon_nom, date_debut}),
    ou None si l'emplacement était déjà vide — à l'appelant de calculer l'XP à partir de
    date_debut avant d'appeler cette fonction (ou juste après, peu importe, la ligne est
    supprimée ici mais l'info est retournée pour ne rien perdre)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pokemon_nom, date_debut FROM caisson_croissance_slots WHERE user_id = ? AND slot = ?",
        (user_id, slot),
    )
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    resultat = {"pokemon_nom": row["pokemon_nom"], "date_debut": row["date_debut"]}
    cur.execute("DELETE FROM caisson_croissance_slots WHERE user_id = ? AND slot = ?", (user_id, slot))
    conn.commit()
    conn.close()
    return resultat
