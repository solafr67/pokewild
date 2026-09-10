"""Caisson de Croissance — 3 emplacements par joueur dans le Laboratoire, où un Pokémon
possédé gagne de l'XP passivement en fonction du temps passé dedans. Réutilise
niveaux_pokemon.gagner_xp_equipe (même mécanisme que l'XP par Pokémon gagnée en combat/
capture/exploration) — le plafond de niveau par rareté s'applique donc normalement,
aucune XP n'est gaspillée au-delà.

Le système est basé sur le NOM D'ESPÈCE (comme l'équipe de combat, pas une capture
individuelle). Déposer une espèce au Caisson la rend INDISPONIBLE en équipe de combat ET
en exploration tant qu'elle n'est pas retirée (voir database.especes_en_caisson, croisé
avec database.especes_en_exploration à chaque point de sélection concerné) — même
principe que l'indisponibilité déjà en place pour l'exploration.
"""

import time

import database

XP_PAR_HEURE = 200  # voir la discussion complète dans la mémoire du projet : à 3 XP/h,
# la courbe quadratique d'XP (25*(niveau-1)²) rendait le Caisson quasiment inutile passé
# le niveau 20-30 (70->100 aurait pris ~1750 jours). 200 XP/h ramène 70->100 à ~26 jours
# et 1->10 à ~10h — un taux fixe ne peut jamais être parfait sur une courbe quadratique
# (rapide en bas, lent en haut quoi qu'il arrive), mais celui-ci rend le late-game
# réellement praticable sur une absence de quelques semaines plutôt que des années.


def especes_possedees(user_id: int) -> set:
    return {row["pokemon_nom"] for row in database.obtenir_pokedex_joueur(user_id)}


def especes_deja_en_caisson(user_id: int) -> set:
    caisson = database.obtenir_caisson(user_id)
    return {info["pokemon_nom"] for info in caisson.values() if info}


def xp_en_attente(date_debut: int) -> int:
    heures_ecoulees = (int(time.time()) - date_debut) / 3600
    return round(heures_ecoulees * XP_PAR_HEURE)


def deposer(user_id: int, pokemon_nom: str) -> tuple:
    """Dépose une espèce possédée dans le premier emplacement libre. Retourne
    (succes: bool, message: str)."""
    if pokemon_nom not in especes_possedees(user_id):
        return False, f"Tu ne possèdes aucun **{pokemon_nom}**."

    if pokemon_nom in especes_deja_en_caisson(user_id):
        return False, f"**{pokemon_nom}** est déjà dans le Caisson (un autre emplacement)."

    caisson = database.obtenir_caisson(user_id)
    slot_libre = next((slot for slot, info in caisson.items() if info is None), None)
    if slot_libre is None:
        return False, "Les 3 emplacements du Caisson sont déjà occupés — retire quelqu'un d'abord."

    database.deposer_caisson(user_id, slot_libre, pokemon_nom, int(time.time()))
    return True, f"**{pokemon_nom}** placé dans le Caisson de Croissance (emplacement {slot_libre})."


def retirer(user_id: int, slot: int) -> dict:
    """Retire l'occupant d'un emplacement et lui crédite l'XP accumulée. Retourne
    {pokemon_nom, xp_gagnee, montees_niveau} ou None si l'emplacement était vide."""
    import niveaux_pokemon

    occupant = database.retirer_caisson(user_id, slot)
    if occupant is None:
        return None

    xp = xp_en_attente(occupant["date_debut"])
    montees = niveaux_pokemon.gagner_xp_equipe(user_id, xp, noms=[occupant["pokemon_nom"]]) if xp > 0 else []

    return {"pokemon_nom": occupant["pokemon_nom"], "xp_gagnee": xp, "montees_niveau": montees}
