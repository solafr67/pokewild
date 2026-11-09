"""laboratoire_service.py — Laboratoire sur le site (sans Discord) : Incubateur,
Transformateur, Caisson de Croissance et Mutation de dresseur.

Mêmes règles que elevage.py / race_ui.py / caisson_croissance.py, via les mêmes fonctions
de base de données : un œuf mis à incuber sur le site éclot aussi côté Discord, etc.
"""

import random
import time

import caisson_croissance as caisson_croissance_module
import config
import database
import leveling
import niveaux_pokemon
import races
from combat_service import ErreurCombatWeb, _quetes_json
from equipe_combat import _stats_par_espece
from pokedex import ORDRE_RARETE
from pokemon_data import (
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
    calculer_pc_derive,
    cle_tri_alphabetique_fr,
    obtenir_pokemon_par_nom,
    tirer_ivs,
    tirer_niveau_spawn,
    tirer_pokemon_par_rarete,
)


def _nom_oeuf(palier: str) -> str:
    return NOM_OBJETS_DIVERS.get(f"oeuf_{palier}", f"Œuf {palier}")


def _nom_objet(cle: str) -> str:
    return NOM_BALL_AFFICHAGE.get(cle) or NOM_SOIN_AFFICHAGE.get(cle, cle)


# ----------------------------------------------------------------------------
# Incubateur
# ----------------------------------------------------------------------------

def etat_incubateur(user_id: int) -> dict:
    row = database.obtenir_incubation_active(user_id)
    maintenant = int(time.time())
    inv = database.obtenir_inventaire_balls(user_id)
    slot = None
    if row is not None and row["palier"] is not None:
        slot = {
            "palier": row["palier"], "nom": _nom_oeuf(row["palier"]),
            "prete": row["date_fin"] <= maintenant, "secondes_restantes": max(0, row["date_fin"] - maintenant),
        }
    return {
        "slot": slot,
        "oeufs": [
            {"palier": p, "nom": _nom_oeuf(p), "quantite": inv.get(f"oeuf_{p}", 0),
             "duree": config.OEUF_DUREE_INCUBATION[p]}
            for p in config.OEUF_PALIERS if inv.get(f"oeuf_{p}", 0) > 0
        ],
    }


def incuber(user_id: int, palier: str) -> dict:
    if palier not in config.OEUF_PALIERS:
        raise ErreurCombatWeb("Œuf inconnu.")
    row = database.obtenir_incubation_active(user_id)
    if row is not None and row["palier"] is not None:
        raise ErreurCombatWeb("Ton incubateur est déjà occupé.")
    if not database.retirer_ball(user_id, f"oeuf_{palier}"):
        raise ErreurCombatWeb("Tu n'as plus cet œuf !")
    database.demarrer_incubation(user_id, 1, palier, config.OEUF_DUREE_INCUBATION[palier])
    return {"duree": config.OEUF_DUREE_INCUBATION[palier]}


def eclore(user_id: int) -> dict:
    row = database.obtenir_incubation_active(user_id)
    if row is None or row["palier"] is None:
        raise ErreurCombatWeb("Aucun œuf en incubation.")
    if row["date_fin"] > time.time():
        raise ErreurCombatWeb("Cet œuf n'est pas encore prêt à éclore.")
    palier = row["palier"]
    database.terminer_incubation(user_id, 1)

    dist = config.OEUF_DISTRIBUTION_ECLOSION[palier]
    rarete = random.choices(list(dist.keys()), weights=list(dist.values()))[0]
    pokemon = tirer_pokemon_par_rarete(rarete)
    ivs = tirer_ivs()
    niveau = tirer_niveau_spawn(pokemon["rarete"])
    pc = calculer_pc_derive(pokemon, ivs, niveau)
    shiny = random.random() < config.CHANCE_SHINY_BASE * config.OEUF_MULTIPLICATEUR_SHINY * database.multiplicateur_boost(user_id, "shiny")

    nouvelle = database.compter_captures_espece(user_id, pokemon["nom"]) == 0
    database.ajouter_capture(user_id, pokemon["nom"], pc, shiny=shiny, ivs=ivs)
    actuel, _ = database.obtenir_niveau_pokemon(user_id, pokemon["nom"])
    if niveau > actuel:
        database.definir_niveau_xp_pokemon(user_id, pokemon["nom"], niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau))
    quetes = database.incrementer_progression_quete(user_id, "capture", {"rarete": pokemon["rarete"]})

    xp = config.XP_PAR_RARETE[pokemon["rarete"]] + (config.XP_BONUS_SHINY if shiny else 0)
    xp_affichee = round(xp * database.multiplicateur_boost(user_id, "xp"))
    leveling.gagner_xp(user_id, xp)
    return {
        "nom": pokemon["nom"], "pc": pc, "shiny": shiny, "oeuf": _nom_oeuf(palier), "xp": xp_affichee,
        "nouvelle_entree": nouvelle, "quetes_completees": _quetes_json(quetes),
    }


# ----------------------------------------------------------------------------
# Transformateur
# ----------------------------------------------------------------------------

def etat_transformateur(user_id: int) -> dict:
    inv = database.obtenir_inventaire_balls(user_id)
    return {"chaines": [
        {"source": s, "source_nom": _nom_objet(s), "cible": c, "cible_nom": _nom_objet(c), "requis": q,
         "possede": inv.get(s, 0), "lots_possibles": inv.get(s, 0) // q}
        for s, (c, q) in config.CHAINES_TRANSFORMATION.items()
    ]}


def transformer(user_id: int, source: str, lots: int) -> dict:
    if source not in config.CHAINES_TRANSFORMATION:
        raise ErreurCombatWeb("Cet objet ne peut pas être transformé.")
    if not isinstance(lots, int) or lots < 1:
        raise ErreurCombatWeb("Le nombre de lots doit être positif.")
    nb, cible, consommes = database.transformer_objets(user_id, source, lots)
    if nb <= 0:
        raise ErreurCombatWeb("Pas assez d'objets pour faire un lot complet.")
    return {"message": f"{consommes} {_nom_objet(source)} transformés en {nb} {_nom_objet(cible)} !"}


# ----------------------------------------------------------------------------
# Caisson de Croissance
# ----------------------------------------------------------------------------

def etat_caisson(user_id: int, tri: str = "alphabetique", recherche: str = "") -> dict:
    caisson = database.obtenir_caisson(user_id)
    maintenant = int(time.time())
    slots = []
    for s, info in caisson.items():
        if info is None:
            slots.append({"slot": s, "libre": True})
        else:
            slots.append({"slot": s, "nom": info["pokemon_nom"], "secondes": maintenant - info["date_debut"],
                          "xp_en_attente": caisson_croissance_module.xp_en_attente(info["date_debut"])})
    dedans = {i["pokemon_nom"] for i in caisson.values() if i}
    stats = _stats_par_espece(user_id)
    noms = [n for n in stats if n not in dedans]
    if recherche:
        terme = cle_tri_alphabetique_fr(recherche)
        noms = [n for n in noms if terme in cle_tri_alphabetique_fr(n)]
    if tri == "rarete":
        noms.sort(key=lambda n: (ORDRE_RARETE.get((obtenir_pokemon_par_nom(n) or {}).get("rarete"), 99), cle_tri_alphabetique_fr(n)))
    elif tri == "niveau_asc":
        noms.sort(key=lambda n: (database.obtenir_niveau_pokemon(user_id, n)[0], cle_tri_alphabetique_fr(n)))
    else:
        noms.sort(key=cle_tri_alphabetique_fr)
    indispos = database.especes_en_exploration(user_id)
    return {
        "slots": slots, "xp_par_heure": caisson_croissance_module.XP_PAR_HEURE,
        "especes": [
            {"nom": n, "pc": stats[n]["pc"], "niveau": database.obtenir_niveau_pokemon(user_id, n)[0],
             "en_exploration": n in indispos}
            for n in noms[:60]
        ],
        "nb_especes": len(noms),
    }


def deposer_caisson(user_id: int, nom: str) -> dict:
    if nom in database.especes_en_exploration(user_id):
        raise ErreurCombatWeb(f"{nom} est parti en exploration.")
    ok, message = caisson_croissance_module.deposer(user_id, nom)
    if not ok:
        raise ErreurCombatWeb(message.replace("**", ""))
    return {"message": message.replace("**", "")}


def retirer_caisson(user_id: int, slot: int) -> dict:
    res = caisson_croissance_module.retirer(user_id, slot)
    if res is None:
        raise ErreurCombatWeb("Cet emplacement est déjà vide.")
    return {
        "nom": res["pokemon_nom"], "xp": res["xp_gagnee"],
        "montees_niveau": niveaux_pokemon.texte_montees_niveau(res["montees_niveau"]) if res["montees_niveau"] else None,
    }


# ----------------------------------------------------------------------------
# Mutation de dresseur
# ----------------------------------------------------------------------------

def _fiche_race(nom: str) -> dict | None:
    r = races.obtenir_race_par_nom(nom) if nom else None
    if not r:
        return None
    return {"nom": r["nom"], "palier": r["palier"], "description": r["description"], "bonus": races.texte_bonus(r["bonus"])}


def etat_mutation(user_id: int) -> dict:
    nom, pity = database.obtenir_race(user_id)
    return {
        "race": _fiche_race(nom), "pity": pity, "pity_seuil": config.PITY_SEUIL,
        "cristaux": database.obtenir_inventaire_balls(user_id).get("cristal_mutation", 0),
    }


def muter(user_id: int) -> dict:
    if not database.retirer_ball(user_id, "cristal_mutation"):
        raise ErreurCombatWeb("Tu n'as plus de Cristal de Mutation !")
    _, pity = database.obtenir_race(user_id)
    race, nouveau_pity = races.tirer_race(pity)
    database.definir_race(user_id, race["nom"], nouveau_pity)
    return etat_mutation(user_id)
