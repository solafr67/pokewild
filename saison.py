"""Passe saisonnier — piste de progression qui se réinitialise chaque saison
(config.SAISON_DUREE_JOURS), distincte du niveau de dresseur permanent (leveling.py).

Alimentée automatiquement via leveling.gagner_xp : chaque gain d'XP dresseur, peu
importe sa source (capture, PokéStop, quête, raid, dresseur, PvP...), alimente aussi
les points de saison — un seul point d'accroche plutôt que de modifier chaque système
un par un. Récompenses accordées automatiquement à chaque palier franchi, comme les
paliers de niveau de dresseur déjà en place.
"""

import time
from datetime import datetime, timezone

import config
import database

# Début fixe de la Saison 1 — ne JAMAIS changer une fois des joueurs engagés dedans,
# ça décalerait le calcul du numéro de saison de tout le monde.
EPOQUE_SAISON_1 = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp())


def numero_saison_actuelle() -> int:
    """Numéro de la saison en cours (1, 2, 3...), calculé depuis une date de référence
    fixe — aucun état à maintenir, aucune boucle de fond nécessaire pour la transition."""
    duree_secondes = config.SAISON_DUREE_JOURS * 86400
    return max(1, int((time.time() - EPOQUE_SAISON_1) // duree_secondes) + 1)


def temps_restant_saison() -> int:
    """Secondes avant le début de la prochaine saison."""
    duree_secondes = config.SAISON_DUREE_JOURS * 86400
    numero = numero_saison_actuelle()
    fin = EPOQUE_SAISON_1 + numero * duree_secondes
    return max(0, round(fin - time.time()))


def palier_depuis_points(points: int) -> int:
    return min(config.SAISON_NB_PALIERS, points // config.SAISON_XP_PAR_PALIER)


def points_requis_palier(palier: int) -> int:
    return palier * config.SAISON_XP_PAR_PALIER


def _construire_recompenses() -> dict:
    """Une récompense par palier : Poké Dollars croissants, avec des bonus d'objets aux
    paliers ronds (tous les 5) et un Cristal de Mutation au palier final."""
    recompenses = {}
    for palier in range(1, config.SAISON_NB_PALIERS + 1):
        objets = []
        if palier % 5 == 0:
            objets.append(("superball", 3))
        if palier % 10 == 0:
            objets.append(("hyperball", 2))
            objets.append(("superpotion", 3))
        if palier == config.SAISON_NB_PALIERS:
            objets.append(("cristal_mutation", 1))
        recompenses[palier] = {"dollars": 30 + palier * 10, "objets": objets}
    return recompenses


RECOMPENSES_PAR_PALIER = _construire_recompenses()


def texte_recompense_palier(palier: int) -> str:
    recompense = RECOMPENSES_PAR_PALIER.get(palier)
    if not recompense:
        return ""
    morceaux = [f"{recompense['dollars']} Poké Dollars"]
    for objet, quantite in recompense["objets"]:
        morceaux.append(f"{quantite}× {objet.replace('_', ' ').title()}")
    return ", ".join(morceaux)


def _appliquer_recompense_palier(user_id: int, palier: int):
    recompense = RECOMPENSES_PAR_PALIER.get(palier)
    if not recompense:
        return
    if recompense["dollars"]:
        database.ajouter_poke_dollars(user_id, recompense["dollars"])
    for objet, quantite in recompense["objets"]:
        database.ajouter_balls(user_id, objet, quantite)


def gagner_points(user_id: int, montant_xp: int) -> list:
    """À appeler à chaque gain d'XP dresseur (voir leveling.gagner_xp). Convertit en
    points de saison (config.SAISON_RATIO_XP), accorde les récompenses de tout palier
    franchi, et retourne la liste des paliers franchis (pour une notification si besoin)."""
    montant = round(montant_xp * config.SAISON_RATIO_XP)
    if montant <= 0:
        return []

    saison = numero_saison_actuelle()
    points_avant = database.obtenir_points_saison(user_id, saison)
    if points_avant >= points_requis_palier(config.SAISON_NB_PALIERS):
        return []  # déjà au palier max cette saison

    palier_avant = palier_depuis_points(points_avant)
    points_apres = database.ajouter_points_saison(user_id, saison, montant)
    palier_apres = palier_depuis_points(points_apres)

    paliers_franchis = []
    for palier in range(palier_avant + 1, palier_apres + 1):
        _appliquer_recompense_palier(user_id, palier)
        paliers_franchis.append(palier)

    return paliers_franchis


def obtenir_statut(user_id: int) -> dict:
    """Statut lisible pour /passe-saison."""
    saison = numero_saison_actuelle()
    points = database.obtenir_points_saison(user_id, saison)
    palier = palier_depuis_points(points)
    palier_max = config.SAISON_NB_PALIERS
    points_debut_palier = points_requis_palier(palier)
    points_fin_palier = points_requis_palier(min(palier + 1, palier_max))
    return {
        "saison": saison,
        "points": points,
        "palier": palier,
        "palier_max": palier_max,
        "points_dans_palier": points - points_debut_palier,
        "points_requis_palier": max(1, points_fin_palier - points_debut_palier),
        "temps_restant": temps_restant_saison(),
    }
