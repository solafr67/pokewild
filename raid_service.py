"""raid_service.py — Raids du bot Discord, jouables depuis le site.

Le bot ouvre les raids (salle d'attente → combat automatique → victoire) et fait tourner
la boucle de combat : le site ne fait que rejoindre/quitter, afficher l'état, soigner
l'équipe et tenter la capture après la victoire. Les participants du site sont de
vrais participants (mêmes tables), donc leurs dégâts comptent dans le même boss.
"""

import random
import time

import combat as combat_module
import config
import database
import equipe_combat
import etat_jeu
import formes_objets as formes_objets_module
import niveaux_pokemon
import raid as raid_module
from combat_service import ErreurCombatWeb
from pokemon_data import TAUX_CAPTURE, calculer_pc_derive, obtenir_pokemon_par_nom, tirer_ivs

FENETRE_CAPTURE = 1800  # une victoire reste capturable ~30 min après sa date de fin théorique


def _pseudos() -> dict:
    conn = database.get_connexion()
    try:
        return {r["user_id"]: r["pseudo"] for r in conn.execute("SELECT user_id, pseudo FROM web_joueurs")}
    except Exception:
        return {}
    finally:
        conn.close()


def _nom(p, uid):
    return p.get(uid) or f"Dresseur #{str(uid)[-4:]}"


def _phase(r) -> str:
    """'attente' tant que le combat n'a pas commencé (date_fin = début + durée du combat)."""
    if not r["actif"]:
        return "victoire" if r["pv_actuel"] <= 0 else "fini"
    return "attente" if time.time() < r["date_fin"] - config.DUREE_RAID_MINUTES * 60 else "combat"


def _raid(raid_id):
    r = database.obtenir_raid_par_id(raid_id)
    if r is None:
        raise ErreurCombatWeb("Raid introuvable.")
    return r


def _equipe(uid, contexte):
    res = []
    for nom in database.obtenir_equipe_combat(uid):
        dispo = nom in set(database.obtenir_equipe_combat_disponible(uid))
        pv_max = combat_module.stats_combattant_reel(uid, nom)["pv"]
        pv = database.obtenir_pv_actuels(uid, nom, pv_max, contexte=contexte)
        res.append({"nom": nom, "pv": pv, "pv_max": pv_max, "dispo": dispo})
    return res


def _fiche(r, uid, pseudos, detail=False):
    phase = _phase(r)
    parts = database.obtenir_participants_raid(r["id"])
    moi = next((p for p in parts if p["user_id"] == uid), None)
    boss = obtenir_pokemon_par_nom(r["boss_nom"]) or {}
    debut = r["date_fin"] - config.DUREE_RAID_MINUTES * 60
    f = {
        "id": r["id"], "boss": r["boss_nom"], "etoiles": r["etoiles"], "phase": phase,
        "pv": r["pv_actuel"], "pv_max": r["pv_max"], "participants": len(parts),
        "rejoint": moi is not None, "mes_degats": moi["degats_total"] if moi else 0,
        "secondes": max(0, (debut if phase == "attente" else r["date_fin"]) - int(time.time())),
        "recompense": {"pd": config.DOLLARS_RAID_PAR_ETOILE.get(r["etoiles"], 50), "xp": config.XP_RAID_PAR_ETOILE.get(r["etoiles"], 50)},
        "classement": [{"pseudo": _nom(pseudos, p["user_id"]), "degats": p["degats_total"], "moi": p["user_id"] == uid} for p in parts[:10]],
        "taux_capture": TAUX_CAPTURE[boss["rarete"]]["honorball"] if boss else None,
    }
    if phase == "victoire" and moi:
        conn = database.get_connexion()
        try:
            row = conn.execute("SELECT tentatives_capture_restantes t, capture_reussie c FROM raid_participants WHERE raid_id=? AND user_id=?", (r["id"], uid)).fetchone()
        finally:
            conn.close()
        f["tentatives"] = row["t"]
        f["capture_reussie"] = bool(row["c"])
    return f


def etat(uid):
    pseudos = _pseudos()
    conn = database.get_connexion()
    try:
        actifs = conn.execute("SELECT * FROM raid_actuel WHERE actif = 1 AND date_fin > ? ORDER BY id DESC", (int(time.time()) - 600,)).fetchall()
        victoires = conn.execute(
            """SELECT r.* FROM raid_actuel r JOIN raid_participants p ON p.raid_id = r.id
               WHERE r.actif = 0 AND r.pv_actuel <= 0 AND r.date_fin > ? AND p.user_id = ? ORDER BY r.id DESC""",
            (int(time.time()) - FENETRE_CAPTURE, uid)).fetchall()
    finally:
        conn.close()
    raids = [_fiche(r, uid, pseudos) for r in actifs] + [_fiche(r, uid, pseudos) for r in victoires]
    en_combat = any(f["rejoint"] and f["phase"] == "combat" for f in raids)
    return {"raids": raids, "equipe": _equipe(uid, "raid" if en_combat else "normal"), "equipe_en_raid": en_combat,
            "potions": {k: v for k, v in database.obtenir_inventaire_balls(uid).items() if k in raid_module.ORDRE_POTIONS_SOIN and v}}


def rejoindre(uid, raid_id):
    r = _raid(raid_id)
    if _phase(r) != "attente":
        raise ErreurCombatWeb("On ne peut rejoindre un raid que pendant sa salle d'attente.")
    database.inscrire_participant_raid(raid_id, uid)
    dispo = set(database.obtenir_equipe_combat_disponible(uid))
    absents = [n for n in database.obtenir_equipe_combat(uid) if n not in dispo]
    if not database.obtenir_equipe_combat(uid):
        return {"message": "Tu as rejoint le raid, mais ton équipe est vide : configure-la ou utilise « Équipe la plus forte » !"}
    msg = "🙋 Tu as rejoint le raid !"
    if absents:
        msg += f" ⚠️ {', '.join(absents)} ne participera(ont) pas (exploration ou Caisson)."
    return {"message": msg}


def quitter(uid, raid_id):
    r = _raid(raid_id)
    if _phase(r) not in ("attente", "combat"):
        raise ErreurCombatWeb("Ce raid est terminé.")
    if not database.quitter_raid(raid_id, uid):
        raise ErreurCombatWeb("Tu n'avais pas rejoint ce raid.")
    return {"message": "🚪 Tu as quitté le raid."}


def equipe_auto(uid):
    noms = equipe_combat.equiper_meilleure_equipe(uid)
    if not noms:
        raise ErreurCombatWeb("Tu n'as encore aucun Pokémon capturé.")
    return {"message": "🛡️ Équipe remplie avec tes meilleurs Pokémon : " + ", ".join(noms)}


def soigner(uid, raid_id):
    r = _raid(raid_id)
    if _phase(r) != "combat" or not database.est_participant_raid(raid_id, uid):
        raise ErreurCombatWeb("Le soin automatique n'est possible que pendant un raid auquel tu participes.")
    res = raid_module.soigner_auto_equipe_raid(uid)
    if not res["potions_utilisees"]:
        raise ErreurCombatWeb("Rien à soigner, ou plus de potions.")
    return {"message": f"💊 {res['pv_rendus_total']} PV rendus ({sum(res['potions_utilisees'].values())} potion(s))."}


def capturer(uid, raid_id):
    r = _raid(raid_id)
    if r["actif"] or r["pv_actuel"] > 0:
        raise ErreurCombatWeb("La capture n'est possible qu'après la victoire.")
    if not database.est_participant_raid(raid_id, uid):
        raise ErreurCombatWeb("Tu n'as pas participé à ce raid.")
    if database.a_deja_capture_raid(raid_id, uid):
        raise ErreurCombatWeb("Tu as déjà capturé ce Pokémon pour ce raid !")
    boss = obtenir_pokemon_par_nom(r["boss_nom"])
    etoiles = r["etoiles"]
    peut, restantes = database.tenter_capture_raid(raid_id, uid)
    if not peut:
        raise ErreurCombatWeb("Tu n'as plus de tentatives pour ce raid.")
    limite = database.limite_stockage_pokemon(uid)
    if database.compter_captures_totales(uid) >= limite:
        return {"reussite": False, "restantes": restantes, "message": f"📦 Stockage plein ({limite}/{limite}) : tentative perdue, libère de la place !"}
    solo = 2.0 if len(database.obtenir_participants_raid(raid_id)) == 1 else 1.0
    taux = min(1.0, TAUX_CAPTURE[boss["rarete"]]["honorball"] * database.multiplicateur_boost(uid, "capture") * solo)
    if random.random() >= taux:
        return {"reussite": False, "restantes": restantes,
                "message": f"💨 {boss['nom']} s'est échappé... ({restantes} tentative(s) restante(s))"}
    ivs = tirer_ivs()
    niveau = etoiles * 15
    pc = calculer_pc_derive(boss, ivs, niveau)
    shiny = random.random() < config.CHANCE_SHINY_BASE * etat_jeu.obtenir_multiplicateur_shiny() * database.multiplicateur_boost(uid, "shiny")
    objet_forme = database.ajouter_capture(uid, boss["nom"], pc, shiny=shiny, ivs=ivs)
    n0, _ = database.obtenir_niveau_pokemon(uid, boss["nom"])
    if niveau > n0:
        database.definir_niveau_xp_pokemon(uid, boss["nom"], niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau))
    database.marquer_capture_reussie_raid(raid_id, uid)
    quetes = database.incrementer_progression_quete(uid, "capture", {"rarete": boss["rarete"]})
    msg = f"🎉 Tu as capturé {'✨ SHINY ✨ ' if shiny else ''}{boss['nom']} ({pc} PC) !"
    if quetes:
        msg += " 📜 Quête complétée : " + ", ".join(q["nom"] for q in quetes)
    if objet_forme:
        msg += f" 🎁 Il tenait un(e) {formes_objets_module.FORMES_OBJETS[objet_forme]['objet_nom']} !"
    return {"reussite": True, "restantes": restantes, "message": msg}
