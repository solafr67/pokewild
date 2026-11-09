"""duopvp_service.py — Défis de double combat (2v2) entre deux joueurs du site.

Chaque joueur contrôle 2 Pokémon de son équipe de combat. Le combat lui-même est géré par
duo_service (mêmes règles, même moteur) ; ce module ne gère que les défis.
"""

import time

import database
import duo_service
import pvp_service
from combat_service import ErreurCombatWeb

DUREE_DEFI = 300


def _init():
    pvp_service._init()
    conn = database.get_connexion()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS duo_web_defis (
            id INTEGER PRIMARY KEY AUTOINCREMENT, de_id INTEGER NOT NULL, de_pseudo TEXT NOT NULL,
            a_id INTEGER NOT NULL, a_pseudo TEXT NOT NULL, cree_a INTEGER NOT NULL, statut TEXT NOT NULL DEFAULT 'attente')""")
    conn.commit()
    conn.close()


def _fiche(r):
    return {"id": r["id"], "de_pseudo": r["de_pseudo"], "a_pseudo": r["a_pseudo"],
            "secondes_restantes": max(0, r["cree_a"] + DUREE_DEFI - int(time.time()))}


def etat(uid: int) -> dict:
    _init()
    conn = database.get_connexion()
    conn.execute("UPDATE duo_web_defis SET statut = 'expire' WHERE statut = 'attente' AND cree_a < ?", (int(time.time()) - DUREE_DEFI,))
    conn.commit()
    rows = conn.execute("SELECT * FROM duo_web_defis WHERE statut = 'attente' AND (de_id = ? OR a_id = ?) ORDER BY id DESC", (uid, uid)).fetchall()
    conn.close()
    return {"recus": [_fiche(r) for r in rows if r["a_id"] == uid], "envoyes": [_fiche(r) for r in rows if r["de_id"] == uid]}


def defier(uid: int, pseudo: str, cible_id: int) -> dict:
    _init()
    pvp_service.noter_joueur(uid, pseudo)
    if cible_id == uid:
        raise ErreurCombatWeb("Cible invalide.")
    conn = database.get_connexion()
    cible = conn.execute("SELECT pseudo FROM web_joueurs WHERE user_id = ?", (cible_id,)).fetchone()
    deja = conn.execute("SELECT 1 FROM duo_web_defis WHERE statut = 'attente' AND de_id = ? AND a_id = ?", (uid, cible_id)).fetchone()
    conn.close()
    if cible is None:
        raise ErreurCombatWeb("Ce joueur ne s'est jamais connecté au site : il ne peut pas être défié ici.")
    if deja:
        raise ErreurCombatWeb("Tu as déjà un défi 2v2 en attente pour ce joueur.")
    if database.combat_en_cours_pour_joueur(uid) is not None:
        raise ErreurCombatWeb("Tu as déjà un combat en cours !")
    if database.combat_en_cours_pour_joueur(cible_id) is not None:
        raise ErreurCombatWeb(f"{cible['pseudo']} a déjà un combat en cours !")
    duo_service._equipe_reelle(uid)  # lève une erreur claire si l'équipe est insuffisante
    conn = database.get_connexion()
    conn.execute("INSERT INTO duo_web_defis (de_id, de_pseudo, a_id, a_pseudo, cree_a) VALUES (?,?,?,?,?)", (uid, pseudo, cible_id, cible["pseudo"], int(time.time())))
    conn.commit()
    conn.close()
    return {"message": f"Défi 2v2 envoyé à {cible['pseudo']} (valable {DUREE_DEFI // 60} min)."}


def annuler(uid: int, defi_id: int) -> dict:
    _init()
    conn = database.get_connexion()
    cur = conn.execute("UPDATE duo_web_defis SET statut = 'annule' WHERE id = ? AND statut = 'attente' AND (de_id = ? OR a_id = ?)", (defi_id, uid, uid))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise ErreurCombatWeb("Ce défi n'est plus disponible.")
    return {"message": "Défi retiré."}


def accepter(uid: int, defi_id: int) -> dict:
    _init()
    conn = database.get_connexion()
    d = conn.execute("SELECT * FROM duo_web_defis WHERE id = ? AND statut = 'attente' AND a_id = ? AND cree_a >= ?", (defi_id, uid, int(time.time()) - DUREE_DEFI)).fetchone()
    conn.close()
    if d is None:
        raise ErreurCombatWeb("Ce défi n'est plus disponible.")
    res = duo_service.creer_pvp(d["de_id"], d["de_pseudo"], uid, d["a_pseudo"])
    conn = database.get_connexion()
    conn.execute("UPDATE duo_web_defis SET statut = 'accepte' WHERE id = ?", (defi_id,))
    conn.commit()
    conn.close()
    return res
