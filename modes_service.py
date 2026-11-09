"""modes_service.py — Gladio, Arènes et Repaires de méchants sur le site (sans Discord).

Mêmes règles que arene.py / repaires.py / dresseurs.defier_gladio : les arènes et repaires
sont ouverts par le bot (table arene_spawn / repaire_spawn), les joueurs du site rejoignent
les mêmes ouvertures et leurs runs, badges et récompenses sont partagés avec Discord.
Les combats eux-mêmes passent par combat_service (modes "gladio", "arene", "repaire").
"""

import random
import time

import arene as arene_module
import config
import database
import dresseurs as dresseurs_module
import equipe_combat
import formes_objets as formes_objets_module
import repaires as repaires_module
from combat_service import ErreurCombatWeb, demarrer_combat_dresseur
from pokemon_data import EMOJI_TYPES, POKEDEX  # noqa: F401
import gestion_service
import quetes_service  # noqa: F401  (noms d'objets)

NOMS_CATEGORIE = {"capture": "chance de capture", "shiny": "chance de shiny", "argent": "gains de Poké Dollars", "xp": "gains d'XP"}


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------

def _combat_actif_web(user_id: int):
    return database.combat_en_cours_pour_joueur(user_id)


def _equipe_vivante(user_id: int) -> bool:
    return dresseurs_module._equipe_a_un_vivant(user_id)


def _table(kind: str) -> dict:
    if kind == "arene":
        return {"spawn": "arene_spawn", "runs": "arene_runs", "col": "arene_spawn_id"}
    return {"spawn": "repaire_spawn", "runs": "repaire_runs", "col": "repaire_spawn_id"}


def _spawns_actifs(kind: str) -> list:
    t = _table(kind)
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {t['spawn']} WHERE date_expiration > ? ORDER BY id DESC LIMIT 5", (int(time.time()),))
    rows = cur.fetchall()
    conn.close()
    return rows


def _run(kind: str, spawn_id: int, user_id: int):
    return database.obtenir_run_arene(spawn_id, user_id) if kind == "arene" else _run_repaire(spawn_id, user_id)


def _run_repaire(repaire_id: int, user_id: int):
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM repaire_runs WHERE repaire_spawn_id = ? AND user_id = ?", (repaire_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def _theme(kind: str, spawn) -> dict:
    if kind == "arene":
        t = spawn["type_arene"]
        return {"cle": t, "nom": f"Arène {t.capitalize()}", "emoji": EMOJI_TYPES.get(t, "🏟️"),
                "chef": arene_module._nom_champion(t), "types": [t]}
    e = spawn["equipe_mechante"]
    info = config.EQUIPES_MECHANTES[e]
    return {"cle": e, "nom": f"Repaire {e}", "emoji": info["emoji"], "chef": repaires_module._nom_boss(e),
            "types": list(info["types_theme"])}


def _fiche_spawn(kind: str, spawn, user_id: int, combats_actifs: dict) -> dict:
    run = _run(kind, spawn["id"], user_id)
    th = _theme(kind, spawn)
    etat_run = None
    if run is not None:
        etat_run = {"etape": run["etape"], "statut": run["statut"],
                    "combat_id": combats_actifs.get((kind, spawn["id"])),
                    "prochaine": run["etape"] + 1 if run["statut"] == "en_cours" and run["etape"] < 3 else None}
    return {"id": spawn["id"], **th, "secondes_restantes": max(0, spawn["date_expiration"] - int(time.time())), "run": etat_run}


def _combats_actifs_modes(user_id: int) -> dict:
    """Combat web actif du joueur : {(kind, spawn_id): combat_id}."""
    import json
    out = {}
    cid = _combat_actif_web(user_id)
    if cid:
        conn = database.get_connexion()
        cur = conn.cursor()
        try:
            cur.execute("SELECT mode, contexte FROM combat_web_meta WHERE combat_id = ?", (cid,))
            row = cur.fetchone()
        finally:
            conn.close()
        if row and row["mode"] in ("arene", "repaire"):
            out[(row["mode"], json.loads(row["contexte"] or "{}").get("spawn_id"))] = cid
    return out


def etat(user_id: int) -> dict:
    actifs = _combats_actifs_modes(user_id)
    return {
        "gladio": {"secondes_cooldown": database.temps_restant_defi_gladio(user_id),
                   "recompense": [config.GLADIO_RECOMPENSE_MIN, config.GLADIO_RECOMPENSE_MAX]},
        "arenes": [_fiche_spawn("arene", s, user_id, actifs) for s in _spawns_actifs("arene")],
        "repaires": [_fiche_spawn("repaire", s, user_id, actifs) for s in _spawns_actifs("repaire")],
        "badges_arene": sorted(database.obtenir_badges_arene(user_id)),
        "badges_repaire": sorted(database.obtenir_badges_repaire(user_id)),
        "combat_en_cours": _combat_actif_web(user_id),
    }


# ----------------------------------------------------------------------------
# Gladio
# ----------------------------------------------------------------------------

async def defier_gladio(user_id: int, nom_joueur: str) -> dict:
    restant = database.temps_restant_defi_gladio(user_id)
    if restant > 0:
        raise ErreurCombatWeb(f"Gladio n'est pas disponible : reviens dans {restant // 3600}h{(restant % 3600) // 60:02d}.")
    res = await demarrer_combat_dresseur(
        user_id, nom_joueur, archetype_direct=dresseurs_module.ARCHETYPE_GLADIO, multiplicateur_pc=1.15, mode="gladio",
    )
    database.marquer_defi_gladio(user_id)  # seulement une fois le combat vraiment lancé
    return res


# ----------------------------------------------------------------------------
# Arènes et Repaires : entrer, continuer
# ----------------------------------------------------------------------------

def _spawn_valide(kind: str, spawn_id: int):
    spawn = (database.obtenir_arene_spawn if kind == "arene" else database.obtenir_repaire_spawn)(spawn_id)
    if not spawn or time.time() >= spawn["date_expiration"]:
        raise ErreurCombatWeb("Cette ouverture n'est plus disponible.")
    return spawn


async def _lancer_etape(user_id: int, nom_joueur: str, kind: str, spawn, etape: int) -> dict:
    th = _theme(kind, spawn)
    if kind == "arene":
        archetype = arene_module._archetype_etape(th["cle"], etape)
        mult = config.ARENE_MULTIPLICATEUR_CHAMPION if etape == 3 else 1.0
    else:
        archetype = repaires_module._archetype_etape(th["cle"], etape)
        mult = config.REPAIRE_MULTIPLICATEUR_BOSS if etape == 3 else 1.0
    res = await demarrer_combat_dresseur(
        user_id, nom_joueur, archetype_direct=archetype, multiplicateur_pc=mult, mode=kind,
        contexte={"spawn_id": spawn["id"], "etape": etape, "cle": th["cle"]},
    )
    res["etape"] = etape
    return res


async def entrer(user_id: int, nom_joueur: str, kind: str, spawn_id: int) -> dict:
    spawn = _spawn_valide(kind, spawn_id)
    if _combat_actif_web(user_id):
        raise ErreurCombatWeb("Tu es déjà en combat !")
    if not database.obtenir_equipe_combat_disponible(user_id):
        raise ErreurCombatWeb("Configure ton équipe de combat d'abord.")
    if not _equipe_vivante(user_id):
        raise ErreurCombatWeb("Toute ton équipe est K.O. ! Soigne-la avant d'entrer.")
    if _run(kind, spawn_id, user_id) is not None:
        raise ErreurCombatWeb("Tu as déjà tenté cette ouverture (gagnée ou perdue, une seule chance).")
    creer = database.creer_run_arene if kind == "arene" else database.creer_run_repaire
    if not creer(spawn_id, user_id):
        raise ErreurCombatWeb("Tu as déjà tenté cette ouverture.")
    try:
        return await _lancer_etape(user_id, nom_joueur, kind, spawn, 1)
    except Exception:
        (database.terminer_run_arene if kind == "arene" else database.terminer_run_repaire)(spawn_id, user_id, "defaite")
        raise


async def continuer(user_id: int, nom_joueur: str, kind: str, spawn_id: int, soin_auto: bool = False) -> dict:
    spawn = _spawn_valide(kind, spawn_id)
    if _combat_actif_web(user_id):
        raise ErreurCombatWeb("Tu es déjà en combat !")
    run = _run(kind, spawn_id, user_id)
    if run is None or run["statut"] != "en_cours" or not 1 <= run["etape"] <= 2:
        raise ErreurCombatWeb("Aucun run en cours à poursuivre.")
    soin = None
    if soin_auto:
        try:
            soin = gestion_service.soin_auto(user_id)
        except ErreurCombatWeb:
            soin = None
        if soin is not None and not soin["lignes"]:
            raise ErreurCombatWeb("Tu n'as aucune potion en stock.")
    if not _equipe_vivante(user_id):
        raise ErreurCombatWeb("Toute ton équipe est K.O. ! Soigne-la d'abord (Soin auto) pour continuer.")
    res = await _lancer_etape(user_id, nom_joueur, kind, spawn, run["etape"] + 1)
    if soin:
        res["soin"] = soin
    return res


# ----------------------------------------------------------------------------
# Fin d'étape (appelé par combat_service à la fin d'un combat de run)
# ----------------------------------------------------------------------------

def resoudre_etape(meta, gagne: bool) -> dict:
    import json
    kind = meta["mode"]
    ctx = json.loads(meta["contexte"] or "{}")
    spawn_id, etape, cle = ctx["spawn_id"], ctx["etape"], ctx["cle"]
    joueur_id = meta["joueur_id"]
    terminer = database.terminer_run_arene if kind == "arene" else database.terminer_run_repaire
    avancer = database.avancer_run_arene if kind == "arene" else database.avancer_run_repaire
    out = {"kind": kind, "spawn_id": spawn_id, "etape": etape, "gagne": gagne}

    if not gagne:
        terminer(spawn_id, joueur_id, "defaite")
        out["fin"] = True
        return out
    avancer(spawn_id, joueur_id, etape)

    if kind == "arene":
        mini, maxi = config.ARENE_RECOMPENSE_DOLLARS_APPRENTI if etape < 3 else config.ARENE_RECOMPENSE_DOLLARS_CHAMPION
        mult_jour = database.multiplicateur_arene_du_jour(joueur_id) if etape < 3 else database.enregistrer_victoire_arene_repetition(joueur_id)
    else:
        mini, maxi = config.REPAIRE_RECOMPENSE_DOLLARS_SBIRE if etape < 3 else config.REPAIRE_RECOMPENSE_DOLLARS_BOSS
        mult_jour = database.multiplicateur_repaire_du_jour(joueur_id) if etape < 3 else database.enregistrer_victoire_repaire_repetition(joueur_id)
    dollars = round(random.randint(mini, maxi) * mult_jour * database.multiplicateur_boost(joueur_id, "argent"))
    database.ajouter_poke_dollars(joueur_id, dollars)
    out.update({"dollars": dollars, "reduite": mult_jour < 1.0, "fin": etape >= 3})
    if etape < 3:
        return out

    terminer(spawn_id, joueur_id, "victoire")
    if kind == "arene":
        out["badge_nouveau"] = database.accorder_badge_arene(joueur_id, cle)
        ct = arene_module._ct_aleatoire_pour_type(cle, joueur_id)
        if ct:
            database.acheter_ct(joueur_id, ct)
            out["ct"] = ct
        out["bonus"] = f"+{round(config.ARENE_BONUS_DEGATS_PAR_BADGE * 100)}% de dégâts permanents avec les attaques de ce type" if out["badge_nouveau"] else None
    else:
        out["badge_nouveau"] = database.accorder_badge_repaire(joueur_id, cle)
        chance = config.REPAIRE_CHANCE_OBJET_PAR_OBJET * database.multiplicateur_boost(joueur_id, "chance")
        objets = []
        for cle_objet, info in formes_objets_module.FORMES_OBJETS.items():
            if random.random() < chance:
                database.ajouter_balls(joueur_id, cle_objet, 1)
                objets.append(f"{info['objet_nom']} ({info['espece']} uniquement)")
        out["objets"] = objets
        cat = config.EQUIPES_MECHANTES[cle]["categorie_bonus"]
        out["bonus"] = f"+{round(config.REPAIRE_BONUS_PAR_BADGE * 100)}% de {NOMS_CATEGORIE.get(cat, cat)} en permanence" if out["badge_nouveau"] else None
    return out
