"""pvp_service.py — Combats joueur contre joueur sur le site (sans Discord).

Mêmes règles que le PvP de Discord (/defier, /defier-mise) : équipes complètes (pas de PV
persistants), 45 s par tour, récompense de victoire et XP de consolation, dégression
anti-collusion, série de victoires, mise optionnelle (pot au vainqueur, plafonnée à 20 % du
solde du plus pauvre). Le défi se fait entre joueurs connus du site (ceux qui s'y sont
connectés au moins une fois) ; les combats passent par combat_service (mode "pvp").
"""

import json
import time

import combat as combat_module
import config
import database
import leveling
from combat_service import (
    ErreurCombatWeb, _enregistrer_resultat, _meta, _init_tables, _nettoyer_log, _quetes_json,
)
import combat_service

DUREE_DEFI = 120  # secondes pour accepter un défi


def _init():
    _init_tables()
    conn = database.get_connexion()
    conn.execute("CREATE TABLE IF NOT EXISTS web_joueurs (user_id INTEGER PRIMARY KEY, pseudo TEXT NOT NULL, vu_a INTEGER NOT NULL)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pvp_web_defis (
            id INTEGER PRIMARY KEY AUTOINCREMENT, de_id INTEGER NOT NULL, de_pseudo TEXT NOT NULL,
            a_id INTEGER NOT NULL, a_pseudo TEXT NOT NULL, mise INTEGER NOT NULL DEFAULT 0,
            cree_a INTEGER NOT NULL, statut TEXT NOT NULL DEFAULT 'attente')"""
    )
    conn.commit()
    conn.close()


def noter_joueur(user_id: int, pseudo: str):
    _init()
    conn = database.get_connexion()
    conn.execute(
        "INSERT INTO web_joueurs (user_id, pseudo, vu_a) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET pseudo = excluded.pseudo, vu_a = excluded.vu_a",
        (user_id, pseudo, int(time.time())),
    )
    conn.commit()
    conn.close()


def _pseudo(user_id: int) -> str:
    conn = database.get_connexion()
    row = conn.execute("SELECT pseudo FROM web_joueurs WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row["pseudo"] if row else f"Joueur…{str(user_id)[-4:]}"


def _nettoyer_defis():
    conn = database.get_connexion()
    conn.execute("UPDATE pvp_web_defis SET statut = 'expire' WHERE statut = 'attente' AND cree_a < ?", (int(time.time()) - DUREE_DEFI,))
    conn.commit()
    conn.close()


def _fiche_defi(r) -> dict:
    return {"id": r["id"], "de_id": r["de_id"], "de_pseudo": r["de_pseudo"], "a_id": r["a_id"], "a_pseudo": r["a_pseudo"],
            "mise": r["mise"], "secondes_restantes": max(0, r["cree_a"] + DUREE_DEFI - int(time.time()))}


def etat(user_id: int, recherche: str = "") -> dict:
    _init()
    _nettoyer_defis()
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pvp_web_defis WHERE statut = 'attente' AND (de_id = ? OR a_id = ?) ORDER BY id DESC", (user_id, user_id))
    defis = cur.fetchall()
    cur.execute("SELECT user_id, pseudo, vu_a FROM web_joueurs WHERE user_id != ? ORDER BY vu_a DESC LIMIT 300", (user_id,))
    joueurs = cur.fetchall()
    conn.close()
    terme = recherche.strip().lower()
    if terme:
        joueurs = [j for j in joueurs if terme in j["pseudo"].lower()]
    maintenant = int(time.time())
    return {
        "recus": [_fiche_defi(d) for d in defis if d["a_id"] == user_id],
        "envoyes": [_fiche_defi(d) for d in defis if d["de_id"] == user_id],
        "joueurs": [{"id": j["user_id"], "pseudo": j["pseudo"], "en_ligne": maintenant - j["vu_a"] < 300} for j in joueurs[:30]],
        "combat_en_cours": _combat_id_en_cours(user_id),
        "solde": database.obtenir_poke_dollars(user_id),
    }


def _combat_id_en_cours(user_id: int):
    c = database.combat_en_cours_pour_joueur(user_id)
    return c["id"] if c else None


def defier(user_id: int, pseudo: str, cible_id: int, mise: int = 0) -> dict:
    _init()
    _nettoyer_defis()
    noter_joueur(user_id, pseudo)
    if cible_id == user_id:
        raise ErreurCombatWeb("Cible invalide.")
    conn = database.get_connexion()
    cible = conn.execute("SELECT pseudo FROM web_joueurs WHERE user_id = ?", (cible_id,)).fetchone()
    deja = conn.execute("SELECT 1 FROM pvp_web_defis WHERE statut = 'attente' AND de_id = ? AND a_id = ?", (user_id, cible_id)).fetchone()
    conn.close()
    if cible is None:
        raise ErreurCombatWeb("Ce joueur ne s'est jamais connecté au site : il ne peut pas être défié ici.")
    if deja:
        raise ErreurCombatWeb("Tu as déjà un défi en attente pour ce joueur.")
    if _combat_id_en_cours(user_id):
        raise ErreurCombatWeb("Tu as déjà un combat en cours !")
    if _combat_id_en_cours(cible_id):
        raise ErreurCombatWeb(f"{cible['pseudo']} a déjà un combat en cours !")
    if not combat_module.preparer_equipe_pour_combat(user_id):
        raise ErreurCombatWeb("Configure ton équipe de combat d'abord.")
    if not isinstance(mise, int) or mise < 0:
        raise ErreurCombatWeb("Mise invalide.")
    if mise:
        s1, s2 = database.obtenir_poke_dollars(user_id), database.obtenir_poke_dollars(cible_id)
        if s1 < mise:
            raise ErreurCombatWeb(f"Tu n'as que {s1} Poké Dollars, pas assez pour miser {mise}.")
        if s2 < mise:
            raise ErreurCombatWeb(f"{cible['pseudo']} n'a pas assez de Poké Dollars pour tenir cette mise.")
        plafond = round(min(s1, s2) * combat_module.PLAFOND_MISE_DUEL_RATIO)
        if mise > plafond:
            raise ErreurCombatWeb(f"Mise trop élevée : maximum {plafond} Poké Dollars (20 % du solde du plus pauvre des deux).")
    conn = database.get_connexion()
    conn.execute(
        "INSERT INTO pvp_web_defis (de_id, de_pseudo, a_id, a_pseudo, mise, cree_a) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, pseudo, cible_id, cible["pseudo"], mise, int(time.time())),
    )
    conn.commit()
    conn.close()
    return {"message": f"Défi envoyé à {cible['pseudo']} (valable {DUREE_DEFI // 60} min)."}


def annuler(user_id: int, defi_id: int) -> dict:
    _init()
    conn = database.get_connexion()
    cur = conn.execute("UPDATE pvp_web_defis SET statut = 'annule' WHERE id = ? AND statut = 'attente' AND (de_id = ? OR a_id = ?)", (defi_id, user_id, user_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise ErreurCombatWeb("Ce défi n'est plus disponible.")
    return {"message": "Défi retiré."}


def accepter(user_id: int, defi_id: int) -> dict:
    """Crée le combat (retourne {combat_id}). La boucle de résolution est lancée par l'appelant."""
    _init()
    _nettoyer_defis()
    conn = database.get_connexion()
    d = conn.execute("SELECT * FROM pvp_web_defis WHERE id = ? AND statut = 'attente' AND a_id = ?", (defi_id, user_id)).fetchone()
    conn.close()
    if d is None:
        raise ErreurCombatWeb("Ce défi n'est plus disponible.")
    j1, j2 = d["de_id"], d["a_id"]
    if _combat_id_en_cours(j1) or _combat_id_en_cours(j2):
        raise ErreurCombatWeb("L'un des deux joueurs a déjà un combat en cours.")
    equipe1 = combat_module.preparer_equipe_pour_combat(j1)
    equipe2 = combat_module.preparer_equipe_pour_combat(j2)
    if not equipe1:
        raise ErreurCombatWeb(f"{d['de_pseudo']} n'a plus d'équipe de combat valide.")
    if not equipe2:
        raise ErreurCombatWeb("Configure ton équipe de combat d'abord.")
    mise = d["mise"]
    if mise and (database.obtenir_poke_dollars(j1) < mise or database.obtenir_poke_dollars(j2) < mise):
        raise ErreurCombatWeb("Un des deux joueurs n'a plus assez de Poké Dollars pour la mise : duel annulé, rien n'a été prélevé.")

    date_limite = int(time.time()) + combat_module.DUREE_TOUR
    combat_id = database.creer_combat(j1, j2, equipe1[0]["nom"], equipe2[0]["nom"], date_limite)
    database.initialiser_equipe_combat_pvp(combat_id, j1, equipe1)
    database.initialiser_equipe_combat_pvp(combat_id, j2, equipe2)
    if mise:
        database.ajouter_poke_dollars(j1, -mise)
        database.ajouter_poke_dollars(j2, -mise)
        database.definir_mise_combat(combat_id, mise * 2)
    conn = database.get_connexion()
    conn.execute(
        "INSERT INTO combat_web_meta (combat_id, joueur_id, id_adversaire, archetype_nom, pc_cible, nom_joueur, mode, contexte) "
        "VALUES (?, ?, ?, ?, 0, ?, 'pvp', ?)",
        (combat_id, j1, j2, d["a_pseudo"], d["de_pseudo"], json.dumps({"mise": mise})),
    )
    conn.execute("UPDATE pvp_web_defis SET statut = 'accepte' WHERE id = ?", (defi_id,))
    conn.commit()
    conn.close()
    return {"combat_id": combat_id}


# ----------------------------------------------------------------------------
# Résolution
# ----------------------------------------------------------------------------

def _recompenses(vainqueur_id: int, perdant_id: int, forfait: bool) -> dict:
    """Mêmes gains que combat.py (_tick_resolution_pvp / resoudre_abandon)."""
    combat_id_mise = None  # la mise est traitée par l'appelant (déjà liée au combat)
    mult = database.enregistrer_victoire_pvp_repetition(vainqueur_id, perdant_id)
    dollars = round(combat_module.DOLLARS_VICTOIRE * mult * database.multiplicateur_boost(vainqueur_id, "argent"))
    database.ajouter_poke_dollars(vainqueur_id, dollars)
    quetes = [] if forfait else database.incrementer_progression_quete(vainqueur_id, "pvp_victoire")
    database.incrementer_victoires_pvp(vainqueur_id)
    xp = round(combat_module.XP_VICTOIRE * mult)
    leveling.gagner_xp(vainqueur_id, xp)
    leveling.gagner_xp(perdant_id, combat_module.XP_DEFAITE)
    database.incrementer_serie_victoires_pvp(vainqueur_id)
    database.reinitialiser_serie_victoires_pvp(perdant_id)
    return {
        "vainqueur": {"dollars": dollars, "xp": round(xp * database.multiplicateur_boost(vainqueur_id, "xp")),
                      "reduite": mult < 1.0, "quetes_completees": _quetes_json(quetes)},
        "perdant": {"dollars": 0, "xp": round(combat_module.XP_DEFAITE * database.multiplicateur_boost(perdant_id, "xp")),
                    "reduite": False, "quetes_completees": []},
    }


def _cloturer(combat_id: int, vainqueur_id: int, perdant_id: int, forfait: bool):
    database.terminer_combat_pvp(combat_id)
    mise = database.obtenir_mise_combat(combat_id)
    if mise:
        database.ajouter_poke_dollars(vainqueur_id, mise)
        database.retirer_mise_combat(combat_id)
    rec = _recompenses(vainqueur_id, perdant_id, forfait)
    _enregistrer_resultat(combat_id, {"pvp": True, "vainqueur_id": vainqueur_id, "forfait": forfait, "mise": mise or 0, "recompenses": rec})


def resultat_pour(res: dict | None, user_id: int) -> dict | None:
    """Résultat PvP vu par un des deux joueurs (même forme que les combats PvE)."""
    if not res or not res.get("pvp"):
        return res
    gagne = res["vainqueur_id"] == user_id
    g = dict(res["recompenses"]["vainqueur" if gagne else "perdant"])
    if gagne and res.get("mise"):
        g["mise"] = res["mise"]
    g["niveau_dresseur"] = {"avant": 0, "apres": 0}
    issue = "victoire" if gagne else "defaite"
    return {"issue": issue, "recompenses": g, "forfait": res["forfait"], "pvp": True}


async def tick(combat_id: int, meta) -> dict:
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return {"statut": "inactif"}
    if await combat_module.traiter_choix_ko(None, combat_id, None):
        return {"statut": "attente_remplacant"}

    c1 = database.obtenir_charge(combat_id, combat["joueur1_id"], combat["actif1_nom"])
    c2 = database.obtenir_charge(combat_id, combat["joueur2_id"], combat["actif2_nom"])
    pret1 = combat["action1"] is not None or bool(c1["attaque_en_charge"]) or bool(c1["doit_recharger"])
    pret2 = combat["action2"] is not None or bool(c2["attaque_en_charge"]) or bool(c2["doit_recharger"])
    if not (pret1 and pret2) and int(time.time()) < combat["date_limite_tour"]:
        return {"statut": "attente_joueur"}

    tour = combat["tour"]
    log = _nettoyer_log(await combat_module.resoudre_tour(combat_id), meta)
    conn = database.get_connexion()
    conn.execute("INSERT OR REPLACE INTO combat_web_journal (combat_id, tour, lignes) VALUES (?, ?, ?)",
                 (combat_id, tour, json.dumps(log, ensure_ascii=False)))
    conn.commit()
    conn.close()

    vainqueur = combat_module.verifier_fin_combat(combat_id)
    if vainqueur is not None:
        perdant = combat["joueur2_id"] if vainqueur == combat["joueur1_id"] else combat["joueur1_id"]
        _cloturer(combat_id, vainqueur, perdant, False)
        return {"statut": "termine", "tour": tour, "journal": log}
    database.passer_tour_pvp(combat_id, int(time.time()) + combat_module.DUREE_TOUR)
    return {"statut": "tour_resolu", "tour": tour, "journal": log}


def abandonner(combat_id: int, user_id: int) -> dict:
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        raise ErreurCombatWeb("Ce combat est déjà terminé.")
    vainqueur = combat["joueur2_id"] if user_id == combat["joueur1_id"] else combat["joueur1_id"]
    _cloturer(combat_id, vainqueur, user_id, True)
    return {"ok": True, "message": "Tu as abandonné : victoire par forfait pour ton adversaire."}
