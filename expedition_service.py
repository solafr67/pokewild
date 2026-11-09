"""expedition_service.py — Centre des Explorations sur le site (sans Discord).

Réutilise directement les règles de exploration.py (calcul des récompenses, affinités,
événements aléatoires, destinations) et les fonctions database.* : une exploration lancée
sur le site est visible et récupérable sur Discord, et inversement.

La Faille Spatio-Temporelle est ouverte/fermée par le bot (en mémoire) ; le site relit son
créneau du jour dans la base (faille_exploration_debut) pour savoir si elle est ouverte.
"""

import random
import time

import config
import database
import exploration
import formes_objets as formes_objets_module
import inventaire
import leveling
import niveaux_pokemon
from combat_service import ErreurCombatWeb, _quetes_json
from equipe_combat import _stats_par_espece
from exploration import DESTINATIONS_EXPLORATION, FAILLE_EXPLORATION

SLOT_FAILLE = config.SLOT_FAILLE_EXPLORATION


def faille_ouverte() -> bool:
    try:
        debut = int(database.obtenir_parametre("faille_exploration_debut") or 0)
    except ValueError:
        return False
    return debut > 0 and debut <= time.time() < debut + config.DUREE_FAILLE_EXPLORATION


def _synchroniser_faille() -> bool:
    """Ajoute/retire la Faille de DESTINATIONS_EXPLORATION dans CE process (comme le fait le bot)."""
    ouverte = faille_ouverte()
    if ouverte:
        DESTINATIONS_EXPLORATION["faille"] = FAILLE_EXPLORATION
    else:
        DESTINATIONS_EXPLORATION.pop("faille", None)
    return ouverte


def _fiche_slot(row, maintenant: int) -> dict:
    dest = row["destination"]
    info = DESTINATIONS_EXPLORATION.get(dest) or (FAILLE_EXPLORATION if dest == "faille" else None)
    prete = row["date_fin"] <= maintenant
    return {
        "slot": row["slot"],
        "pokemon": [p for p in (row["pokemon1"], row["pokemon2"], row["pokemon3"]) if p],
        "destination": dest, "destination_nom": info["nom"] if info else None,
        "destination_emoji": info["emoji"] if info else None,
        "duree": row["duree_label"], "prete": prete,
        "secondes_restantes": max(0, row["date_fin"] - maintenant),
        # l'événement n'est révélé qu'une fois son heure passée (comme la notification Discord)
        "evenement": row["evenement_texte"] if (row["evenement_planifie_a"] and row["evenement_planifie_a"] <= maintenant) else None,
    }


def etat(user_id: int) -> dict:
    ouverte = _synchroniser_faille()
    maintenant = int(time.time())
    nb_slots = database.nb_slots_exploration(user_id)
    lignes = {r["slot"]: r for r in database.obtenir_explorations_actives(user_id)}
    slots = []
    for s in range(1, nb_slots + 1):
        slots.append(_fiche_slot(lignes[s], maintenant) if s in lignes else {"slot": s, "libre": True})
    faille = None
    if SLOT_FAILLE in lignes:
        faille = _fiche_slot(lignes[SLOT_FAILLE], maintenant)
    elif ouverte:
        faille = {"slot": SLOT_FAILLE, "libre": True}

    destinations = [
        {"cle": c, "nom": i["nom"], "emoji": i["emoji"], "description": i["description"],
         "types": i["types_affinite"] if len(i["types_affinite"]) <= 6 else None,
         "durees": ["1h"] if c == "faille" else list(config.EXPLORATION_DUREES)}
        for c, i in DESTINATIONS_EXPLORATION.items()
    ]
    indispos = database.especes_en_exploration(user_id) | database.especes_en_caisson(user_id)
    stats = _stats_par_espece(user_id)
    especes = []
    for nom in sorted((n for n in stats if n not in indispos), key=lambda n: -stats[n]["pc"]):
        p = exploration.obtenir_pokemon_par_nom(nom) or {}
        especes.append({"nom": nom, "pc": stats[nom]["pc"], "types": p.get("types", []),
                        "affinites": [c for c in DESTINATIONS_EXPLORATION if exploration._pokemon_correspond_destination(nom, c)]})
    return {
        "slots": slots, "faille": faille, "destinations": destinations, "especes": especes,
        "taille_equipe": config.EXPLORATION_TAILLE_EQUIPE, "nb_prets": sum(1 for s in slots + ([faille] if faille else []) if s.get("prete")),
        "slot_supplementaire": {"achetable": nb_slots < 2, "prix": config.EXTENSION_SLOT_EXPLORATION_PRIX},
        "poke_dollars": database.obtenir_poke_dollars(user_id),
        "nb_affinite_requis": exploration.NB_AFFINITE_REQUIS,
    }


def acheter_slot(user_id: int) -> dict:
    if database.nb_slots_exploration(user_id) >= 2:
        raise ErreurCombatWeb("Tu as déjà 2 emplacements d'exploration !")
    prix = config.EXTENSION_SLOT_EXPLORATION_PRIX
    solde = database.obtenir_poke_dollars(user_id)
    if solde < prix:
        raise ErreurCombatWeb(f"Solde insuffisant : il te faut {prix} Poké Dollars, tu en as {solde}.")
    database.ajouter_poke_dollars(user_id, -prix)
    database.acheter_slot_exploration(user_id)
    return {"poke_dollars": database.obtenir_poke_dollars(user_id)}


def demarrer(user_id: int, slot: int, destination: str, pokemons: list, duree_label: str) -> dict:
    _synchroniser_faille()
    if destination not in DESTINATIONS_EXPLORATION:
        raise ErreurCombatWeb("Destination inconnue ou fermée.")
    if destination == "faille":
        if slot != SLOT_FAILLE:
            raise ErreurCombatWeb("La Faille utilise son emplacement bonus.")
        duree_label = "1h"
    elif slot == SLOT_FAILLE:
        raise ErreurCombatWeb("L'emplacement Faille est réservé à la Faille Spatio-Temporelle.")
    elif not 1 <= slot <= database.nb_slots_exploration(user_id):
        raise ErreurCombatWeb("Emplacement invalide.")
    if duree_label not in config.EXPLORATION_DUREES:
        raise ErreurCombatWeb("Durée invalide.")
    if slot in {r["slot"] for r in database.obtenir_explorations_actives(user_id)}:
        raise ErreurCombatWeb("Cet emplacement est déjà occupé.")
    n = config.EXPLORATION_TAILLE_EQUIPE
    if len(pokemons) != n or len(set(pokemons)) != n:
        raise ErreurCombatWeb(f"Choisis exactement {n} Pokémon différents.")
    stats = _stats_par_espece(user_id)
    if any(p not in stats for p in pokemons):
        raise ErreurCombatWeb("Tu ne possèdes pas un de ces Pokémon.")
    indispos = database.especes_en_exploration(user_id) | database.especes_en_caisson(user_id)
    if any(p in indispos for p in pokemons):
        raise ErreurCombatWeb("Un des Pokémon choisis est déjà en exploration ou au Caisson de Croissance.")

    secondes = config.EXPLORATION_DUREES[duree_label]
    debut = int(time.time())
    planifie, texte, bonus = exploration._tirer_evenement(duree_label, debut, debut + secondes)
    database.demarrer_exploration(
        user_id, slot, pokemons, secondes, duree_label, destination=destination,
        evenement_planifie_a=planifie, evenement_texte=texte, evenement_bonus_dollars=bonus,
    )
    return {"retour_dans": secondes, "duree": duree_label, "destination": destination}


def recuperer(user_id: int, slot: int | None = None) -> dict:
    """Récupère une exploration terminée (slot donné) ou TOUTES celles qui sont prêtes."""
    _synchroniser_faille()
    maintenant = int(time.time())
    pretes = [r for r in database.obtenir_explorations_actives(user_id) if r["date_fin"] <= maintenant]
    if slot is not None:
        pretes = [r for r in pretes if r["slot"] == slot]
    if not pretes:
        raise ErreurCombatWeb("Aucune exploration prête à être récupérée.")

    total_dollars = total_xp = 0
    cristaux, oeufs, objets_forme, details, quetes, montees = 0, [], [], [], [], []
    for row in pretes:
        pokemons = [p for p in (row["pokemon1"], row["pokemon2"], row["pokemon3"]) if p]
        duree = row["duree_label"] or exploration._retrouver_duree_label(row["date_fin"] - row["date_debut"])
        dest = row["destination"]
        stats = _stats_par_espece(user_id)
        pc_total = sum(stats.get(n, {}).get("pc", 0) for n in pokemons)
        rec = exploration._calculer_recompense(user_id, pc_total, duree, dest, pokemons)

        mult_rep = database.enregistrer_completion_exploration_repetition(user_id)
        dollars = round(rec["dollars"] * mult_rep * database.multiplicateur_boost(user_id, "argent")) + (row["evenement_bonus_dollars"] or 0)
        database.ajouter_poke_dollars(user_id, dollars)
        leveling.gagner_xp(user_id, rec["xp"])
        total_xp += round(rec["xp"] * database.multiplicateur_boost(user_id, "xp"))
        montees.extend(niveaux_pokemon.gagner_xp_equipe(user_id, rec["xp"], noms=pokemons))

        cristal = random.random() < rec["chance_cristal"]
        if cristal:
            database.ajouter_balls(user_id, "cristal_mutation", 1)
            cristaux += 1
        if random.random() < rec["chance_oeuf"]:
            palier = exploration._tirer_palier_oeuf()
            database.ajouter_balls(user_id, f"oeuf_{palier}", 1)
            oeufs.append(inventaire.NOMS_OBJETS.get(f"oeuf_{palier}", palier))
        if random.random() < rec["chance_objet_forme"]:
            cle = exploration._tirer_objet_forme_aleatoire()
            database.ajouter_balls(user_id, cle, 1)
            info = formes_objets_module.FORMES_OBJETS[cle]
            objets_forme.append(f"{info['objet_nom']} ({info['espece']} uniquement)")

        database.terminer_exploration(user_id, row["slot"])
        database.incrementer_explorations_terminees(user_id)
        for q in _quetes_json(database.incrementer_progression_quete(user_id, "exploration_collectee")):
            if q["id"] not in {x["id"] for x in quetes}:
                quetes.append(q)
        total_dollars += dollars
        info_dest = DESTINATIONS_EXPLORATION.get(dest) or (FAILLE_EXPLORATION if dest == "faille" else None)
        details.append({
            "slot": row["slot"], "pokemon": pokemons, "cristal": cristal, "affinite": bool(rec.get("a_affinite")),
            "destination": info_dest["nom"] if info_dest else None, "emoji": info_dest["emoji"] if info_dest else None,
            "evenement": row["evenement_texte"],
        })
    return {
        "nb": len(pretes), "details": details, "dollars": total_dollars, "xp": total_xp, "cristaux": cristaux,
        "oeufs": oeufs, "objets_forme": objets_forme,
        "montees_niveau": niveaux_pokemon.texte_montees_niveau(montees) if montees else None,
        "quetes_completees": quetes,
    }
