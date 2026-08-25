"""Sous-module database — domaine codes promo (création admin, utilisation joueur).
Domaine isolé (vérifié exhaustivement avant extraction) : aucune fonction ailleurs
dans database/ n'appelle une fonction de ce fichier, et ce fichier ne dépend que
de get_connexion."""

import sqlite3
import time

from . import get_connexion


def creer_code_promo(
    code: str, dollars: int, xp: int, objet: str | None, quantite_objet: int,
    max_utilisations: int | None, date_expiration: int | None, cree_par: int,
) -> bool:
    """Crée un nouveau code promo. Retourne False si ce code existe déjà (peu importe
    qu'il soit encore actif ou non — les codes ne se réutilisent pas)."""
    code = code.strip().upper()
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM codes_promo WHERE code = ?", (code,))
    if cur.fetchone() is not None:
        conn.close()
        return False
    cur.execute(
        """
        INSERT INTO codes_promo
            (code, dollars, xp, objet, quantite_objet, max_utilisations, date_expiration, cree_par, date_creation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (code, dollars, xp, objet, quantite_objet, max_utilisations, date_expiration, cree_par, int(time.time())),
    )
    conn.commit()
    conn.close()
    return True


def obtenir_code_promo(code: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM codes_promo WHERE code = ?", (code.strip().upper(),))
    row = cur.fetchone()
    conn.close()
    return row


def lister_codes_promo() -> list:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM codes_promo ORDER BY date_creation DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def desactiver_code_promo(code: str) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    code = code.strip().upper()
    cur.execute("SELECT 1 FROM codes_promo WHERE code = ?", (code,))
    if cur.fetchone() is None:
        conn.close()
        return False
    cur.execute("UPDATE codes_promo SET actif = 0 WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    return True


def utiliser_code_promo(code: str, user_id: int) -> tuple:
    """Tente d'utiliser un code pour ce joueur. Retourne (True, ligne_code) si réussi —
    à charge de l'appelant de distribuer les récompenses décrites dans la ligne. Retourne
    (False, raison_texte) sinon. N'accorde jamais deux fois le même code au même joueur
    (contrainte PRIMARY KEY sur codes_promo_utilises)."""
    code = code.strip().upper()
    conn = get_connexion()
    cur = conn.cursor()

    cur.execute("SELECT * FROM codes_promo WHERE code = ?", (code,))
    ligne = cur.fetchone()
    if ligne is None:
        conn.close()
        return False, "Ce code n'existe pas."
    if not ligne["actif"]:
        conn.close()
        return False, "Ce code n'est plus actif."
    if ligne["date_expiration"] and ligne["date_expiration"] < int(time.time()):
        conn.close()
        return False, "Ce code a expiré."
    if ligne["max_utilisations"] is not None and ligne["utilisations_actuelles"] >= ligne["max_utilisations"]:
        conn.close()
        return False, "Ce code a atteint son nombre maximum d'utilisations."

    cur.execute("SELECT 1 FROM codes_promo_utilises WHERE code = ? AND user_id = ?", (code, user_id))
    if cur.fetchone() is not None:
        conn.close()
        return False, "Tu as déjà utilisé ce code."

    try:
        cur.execute(
            "INSERT INTO codes_promo_utilises (code, user_id, date_utilisation) VALUES (?, ?, ?)",
            (code, user_id, int(time.time())),
        )
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Tu as déjà utilisé ce code."  # garde-fou en cas de double-clic simultané

    cur.execute("UPDATE codes_promo SET utilisations_actuelles = utilisations_actuelles + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    return True, ligne
