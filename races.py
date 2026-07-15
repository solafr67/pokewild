"""Races de dresseur : bonus permanents obtenus par reroll aléatoire (Cristal de
Mutation, gagné au Centre des Explorations). Chaque reroll REMPLACE la race actuelle.

Chaque palier de rareté (les mêmes que pour les Pokémon) mélange volontairement des
races généralistes (plusieurs bonus modérés) et spécialistes (un seul bonus fort),
pour donner un vrai choix de profil de jeu à chaque niveau de puissance.
"""

import random

import config

# bonus = dict {"xp": +0.05, "argent": +0.05, "shiny": +0.05, "capture": +0.05}
# Les valeurs sont des bonus ADDITIFS en pourcentage (0.05 = +5%).
RACES = [
    # --- Commun ---
    {"nom": "Voyageur", "palier": "commun", "bonus": {"xp": 0.03, "argent": 0.03, "capture": 0.03, "shiny": 0.03},
     "description": "Un peu de tout, sans grand talent particulier."},
    {"nom": "Apprenti Dresseur", "palier": "commun", "bonus": {"xp": 0.08},
     "description": "Apprend vite de chaque capture."},
    {"nom": "Petit Commerçant", "palier": "commun", "bonus": {"argent": 0.08},
     "description": "A le sens des affaires, même modestement."},

    # --- Peu commun ---
    {"nom": "Éclaireur", "palier": "peu_commun", "bonus": {"xp": 0.06, "capture": 0.06},
     "description": "Repère les angles morts d'un Pokémon sauvage."},
    {"nom": "Traqueur", "palier": "peu_commun", "bonus": {"capture": 0.15},
     "description": "Ne laisse presque jamais un Pokémon s'échapper."},
    {"nom": "Œil de Lynx", "palier": "peu_commun", "bonus": {"shiny": 0.20},
     "description": "Repère le moindre reflet inhabituel dans les herbes hautes."},

    # --- Rare ---
    {"nom": "Globe-Trotter", "palier": "rare", "bonus": {"xp": 0.12, "argent": 0.12},
     "description": "A parcouru assez de terrain pour rentabiliser chaque sortie."},
    {"nom": "Maître Chasseur", "palier": "rare", "bonus": {"capture": 0.25},
     "description": "Une précision redoutable au lancer de ball."},
    {"nom": "Collectionneur Chevronné", "palier": "rare", "bonus": {"shiny": 0.35},
     "description": "Une intuition presque surnaturelle pour les couleurs rares."},

    # --- Hyper Rare ---
    {"nom": "Stratège", "palier": "hyper_rare", "bonus": {"xp": 0.15, "argent": 0.15, "capture": 0.15},
     "description": "Optimise chaque sortie sur le terrain, sans exception."},
    {"nom": "Négociant d'Élite", "palier": "hyper_rare", "bonus": {"argent": 0.40},
     "description": "Ses contacts dans le marché noir des PokéDollars sont... discutables."},
    {"nom": "Œil du Légendaire", "palier": "hyper_rare", "bonus": {"shiny": 0.60},
     "description": "On raconte qu'il a déjà vu un Pokémon chromatique dans ses rêves."},

    # --- Légendaire ---
    {"nom": "Légende Vivante", "palier": "legendaire", "bonus": {"xp": 0.20, "argent": 0.20, "capture": 0.20, "shiny": 0.20},
     "description": "Un talent qui dépasse l'entendement, dans tous les domaines."},
    {"nom": "Roi des Dresseurs", "palier": "legendaire", "bonus": {"xp": 0.50},
     "description": "Chaque capture devient une leçon magistrale."},
    {"nom": "Avatar de la Chance", "palier": "legendaire", "bonus": {"shiny": 1.00},
     "description": "La chance elle-même semble le suivre pas à pas."},
]

RACES_PAR_NOM = {r["nom"]: r for r in RACES}
RACES_PAR_PALIER = {}
for _r in RACES:
    RACES_PAR_PALIER.setdefault(_r["palier"], []).append(_r)

EMOJI_STAT = {"xp": "✨", "argent": "💰", "shiny": "🌟", "capture": "🎯"}
NOM_STAT = {"xp": "XP", "argent": "Argent", "shiny": "Shiny", "capture": "Capture"}


def texte_bonus(bonus: dict) -> str:
    """Formate un dict de bonus {'xp': 0.15, ...} en texte lisible avec émojis."""
    morceaux = [f"{EMOJI_STAT[stat]} {NOM_STAT[stat]} +{round(valeur * 100)}%" for stat, valeur in bonus.items()]
    return " • ".join(morceaux)


def tirer_race(pity_compteur: int) -> tuple:
    """Tire une race au hasard selon les poids de palier, avec système de pity : si
    pity_compteur atteint config.PITY_SEUIL, le tirage est forcé sur au moins 'rare'.
    Retourne (race, nouveau_pity_compteur)."""
    paliers_pity_actifs = {"rare", "hyper_rare", "legendaire"}

    if pity_compteur >= config.PITY_SEUIL:
        poids_effectifs = {p: w for p, w in config.POIDS_TIRAGE_RACE.items() if p in paliers_pity_actifs}
    else:
        poids_effectifs = config.POIDS_TIRAGE_RACE

    palier_tire = random.choices(list(poids_effectifs.keys()), weights=list(poids_effectifs.values()), k=1)[0]
    race = random.choice(RACES_PAR_PALIER[palier_tire])

    nouveau_pity = 0 if palier_tire in paliers_pity_actifs else pity_compteur + 1
    return race, nouveau_pity


def obtenir_race_par_nom(nom: str) -> dict:
    return RACES_PAR_NOM.get(nom)
