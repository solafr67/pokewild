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

# Saison 1 exceptionnelle : du 20 juillet au 30 août 2026 (41 jours, plus longue que les
# suivantes) pour démarrer tout de suite plutôt que d'attendre le 1er août. À partir de la
# Saison 2, cadence normale de config.SAISON_DUREE_JOURS (30 jours) depuis cette date de fin.
DEBUT_SAISON_1 = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp())
FIN_SAISON_1 = int(datetime(2026, 8, 30, tzinfo=timezone.utc).timestamp())


def _fin_saison(numero: int) -> int:
    if numero <= 1:
        return FIN_SAISON_1
    duree_secondes = config.SAISON_DUREE_JOURS * 86400
    return FIN_SAISON_1 + (numero - 1) * duree_secondes


def numero_saison_actuelle() -> int:
    """Numéro de la saison en cours (1, 2, 3...). La Saison 1 est exceptionnelle (durée
    différente des suivantes) — ne pas re-caler cette logique sur un simple calcul
    proportionnel, sinon les saisons suivantes seraient mal calées."""
    maintenant = time.time()
    if maintenant < FIN_SAISON_1:
        return 1
    duree_secondes = config.SAISON_DUREE_JOURS * 86400
    return 2 + int((maintenant - FIN_SAISON_1) // duree_secondes)


def temps_restant_saison() -> int:
    """Secondes avant le début de la prochaine saison."""
    numero = numero_saison_actuelle()
    fin = _fin_saison(numero)
    return max(0, round(fin - time.time()))


def palier_depuis_points(points: int) -> int:
    return min(config.SAISON_NB_PALIERS, points // config.SAISON_XP_PAR_PALIER)


def points_requis_palier(palier: int) -> int:
    return palier * config.SAISON_XP_PAR_PALIER


def _construire_recompenses() -> dict:
    """Une récompense par palier : Poké Dollars croissants + un petit objet varié à
    CHAQUE palier (pas juste les ronds), avec des bonus plus généreux tous les 5/10
    paliers, et un lot spécial (Cristal de Mutation + Master Ball) au palier final."""
    # Cycle de petits objets, un par palier, pour que ça ne soit jamais juste des Poké
    # Dollars — varié plutôt que répétitif sur 30 paliers.
    cycle_objets = [
        ("pokeball", 2), ("potion", 2), ("superball", 1), ("superpotion", 1),
        ("pokeball", 3), ("hyperpotion", 1), ("superball", 2), ("potion", 3),
    ]

    recompenses = {}
    for palier in range(1, config.SAISON_NB_PALIERS + 1):
        objet_cycle, quantite_cycle = cycle_objets[(palier - 1) % len(cycle_objets)]
        objets = [(objet_cycle, quantite_cycle)]

        if palier % 5 == 0:
            objets.append(("superball", 3))
        if palier % 10 == 0:
            objets.append(("hyperball", 2))
            objets.append(("superpotion", 3))
        if palier == config.SAISON_NB_PALIERS:
            objets.append(("cristal_mutation", 1))
            objets.append(("masterball", 1))

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
