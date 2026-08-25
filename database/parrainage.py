"""Sous-module database — domaine parrainage (invitations confirmées, paliers de
récompense reçus). Domaine isolé (vérifié exhaustivement avant extraction) : aucune
fonction ailleurs dans database/ n'appelle une fonction de ce fichier, et ce fichier ne
dépend que de get_connexion."""

import time

from . import get_connexion


def enregistrer_parrainage(filleul_id: int, inviteur_id: int) -> bool:
    """Enregistre qu'un nouveau membre (filleul_id) a rejoint via l'invitation de
    inviteur_id — EN ATTENTE de confirmation (voir confirmer_parrainage), pas encore
    compté dans les récompenses. Retourne False si ce filleul est déjà enregistré (ne
    compte jamais deux fois, même s'il quitte et revient)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM parrainages WHERE filleul_id = ?", (filleul_id,))
    if cur.fetchone() is not None:
        conn.close()
        return False
    cur.execute(
        "INSERT INTO parrainages (filleul_id, inviteur_id, date_join, confirme) VALUES (?, ?, ?, 0)",
        (filleul_id, inviteur_id, int(time.time())),
    )
    conn.commit()
    conn.close()
    return True


def supprimer_parrainage_non_confirme(filleul_id: int):
    """À appeler quand un filleul quitte le serveur AVANT d'être confirmé (voir
    config.PARRAINAGE_DELAI_JOURS) — son parrainage ne doit jamais compter. Ne fait rien
    si le parrainage est déjà confirmé (aucune reprise après coup)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM parrainages WHERE filleul_id = ? AND confirme = 0", (filleul_id,))
    conn.commit()
    conn.close()


def obtenir_parrainages_a_confirmer(delai_secondes: int) -> list:
    """Parrainages encore en attente dont le délai minimum (config.PARRAINAGE_DELAI_JOURS)
    est écoulé — à vérifier (le filleul est-il toujours là ?) puis confirmer si oui."""
    conn = get_connexion()
    cur = conn.cursor()
    seuil = int(time.time()) - delai_secondes
    cur.execute(
        "SELECT filleul_id, inviteur_id FROM parrainages WHERE confirme = 0 AND date_join <= ?",
        (seuil,),
    )
    resultats = [(row["filleul_id"], row["inviteur_id"]) for row in cur.fetchall()]
    conn.close()
    return resultats


def confirmer_parrainage(filleul_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE parrainages SET confirme = 1 WHERE filleul_id = ?", (filleul_id,))
    conn.commit()
    conn.close()


def compter_parrainages(inviteur_id: int) -> int:
    """Ne compte que les parrainages CONFIRMÉS (filleul resté le délai minimum)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS n FROM parrainages WHERE inviteur_id = ? AND confirme = 1",
        (inviteur_id,),
    )
    n = cur.fetchone()["n"]
    conn.close()
    return n


def obtenir_paliers_parrainage_recus(user_id: int) -> set:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT palier FROM parrainage_paliers_recus WHERE user_id = ?", (user_id,))
    resultats = {row["palier"] for row in cur.fetchall()}
    conn.close()
    return resultats


def marquer_palier_parrainage_recu(user_id: int, palier: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO parrainage_paliers_recus (user_id, palier) VALUES (?, ?)",
        (user_id, palier),
    )
    conn.commit()
    conn.close()
