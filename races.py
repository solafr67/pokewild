"""Races de dresseur : bonus permanents obtenus par reroll aléatoire (Cristal de
Mutation, gagné au Centre des Explorations). Chaque reroll REMPLACE la race actuelle.

Chaque palier de rareté (les mêmes que pour les Pokémon) mélange volontairement des
races généralistes (plusieurs bonus modérés) et spécialistes (un seul bonus fort),
pour donner un vrai choix de profil de jeu à chaque niveau de puissance.
"""

import random

import config

# bonus = dict {"xp": +0.05, "argent": +0.05, "shiny": +0.05, "capture": +0.05, "chance": +0.05}
# "chance" boost les taux de drop d'objets rares (Repaires, Exploration, PokéStop) —
# voir database.multiplicateur_boost, repaires.py, exploration.py et main.py::VuePokestop.
# Les valeurs sont des bonus ADDITIFS en pourcentage (0.05 = +5%).
RACES = [
    # --- Commun ---
    {"nom": "Voyageur", "palier": "commun", "bonus": {"xp": 0.03, "argent": 0.03, "capture": 0.03, "shiny": 0.03},
     "description": "Un peu de tout, sans grand talent particulier."},
    {"nom": "Apprenti Dresseur", "palier": "commun", "bonus": {"xp": 0.08},
     "description": "Apprend vite de chaque capture."},
    {"nom": "Petit Commerçant", "palier": "commun", "bonus": {"argent": 0.08},
     "description": "A le sens des affaires, même modestement."},
    {"nom": "Fouineur", "palier": "commun", "bonus": {"chance": 0.05},
     "description": "Fouille toujours un peu plus loin que les autres."},
    {"nom": "Opportuniste", "palier": "commun", "bonus": {"xp": 0.04, "argent": 0.04, "chance": 0.04},
     "description": "Sait saisir une occasion quand elle se présente."},

    # --- Peu commun ---
    {"nom": "Éclaireur", "palier": "peu_commun", "bonus": {"xp": 0.06, "capture": 0.06},
     "description": "Repère les angles morts d'un Pokémon sauvage."},
    {"nom": "Traqueur", "palier": "peu_commun", "bonus": {"capture": 0.15},
     "description": "Ne laisse presque jamais un Pokémon s'échapper."},
    {"nom": "Œil de Lynx", "palier": "peu_commun", "bonus": {"shiny": 0.20},
     "description": "Repère le moindre reflet inhabituel dans les herbes hautes."},
    {"nom": "Dénicheur", "palier": "peu_commun", "bonus": {"chance": 0.12},
     "description": "Trouve toujours quelque chose là où personne ne regarde."},
    {"nom": "Marchand Futé", "palier": "peu_commun", "bonus": {"argent": 0.08, "chance": 0.08},
     "description": "Flaire les bonnes affaires avant tout le monde."},

    # --- Rare ---
    {"nom": "Globe-Trotter", "palier": "rare", "bonus": {"xp": 0.12, "argent": 0.12},
     "description": "A parcouru assez de terrain pour rentabiliser chaque sortie."},
    {"nom": "Maître Chasseur", "palier": "rare", "bonus": {"capture": 0.25},
     "description": "Une précision redoutable au lancer de ball."},
    {"nom": "Collectionneur Chevronné", "palier": "rare", "bonus": {"shiny": 0.35},
     "description": "Une intuition presque surnaturelle pour les couleurs rares."},
    {"nom": "Flaireur de Trésors", "palier": "rare", "bonus": {"chance": 0.22},
     "description": "Un sixième sens pour deviner ce qui se cache derrière chaque porte."},
    {"nom": "Baroudeur Chanceux", "palier": "rare", "bonus": {"xp": 0.10, "argent": 0.10, "chance": 0.10},
     "description": "L'aventure lui sourit, dans tous les sens du terme."},

    # --- Hyper Rare ---
    {"nom": "Stratège", "palier": "hyper_rare", "bonus": {"xp": 0.15, "argent": 0.15, "capture": 0.15},
     "description": "Optimise chaque sortie sur le terrain, sans exception."},
    {"nom": "Négociant d'Élite", "palier": "hyper_rare", "bonus": {"argent": 0.40},
     "description": "Ses contacts dans le marché noir des PokéDollars sont... discutables."},
    {"nom": "Œil du Légendaire", "palier": "hyper_rare", "bonus": {"shiny": 0.60},
     "description": "On raconte qu'il a déjà vu un Pokémon chromatique dans ses rêves."},
    {"nom": "Béni des Objets", "palier": "hyper_rare", "bonus": {"chance": 0.35},
     "description": "Les objets les plus précieux semblent toujours finir entre ses mains."},
    {"nom": "Magnat Fortuné", "palier": "hyper_rare", "bonus": {"argent": 0.18, "chance": 0.18},
     "description": "La fortune et la chance vont souvent de pair chez lui."},

    # --- Légendaire ---
    {"nom": "Légende Vivante", "palier": "legendaire", "bonus": {"xp": 0.20, "argent": 0.20, "capture": 0.20, "shiny": 0.20},
     "description": "Un talent qui dépasse l'entendement, dans tous les domaines."},
    {"nom": "Roi des Dresseurs", "palier": "legendaire", "bonus": {"xp": 0.50},
     "description": "Chaque capture devient une leçon magistrale."},
    {"nom": "Avatar de la Chance", "palier": "legendaire", "bonus": {"shiny": 1.00},
     "description": "La chance elle-même semble le suivre pas à pas."},
    {"nom": "Élu de la Fortune", "palier": "legendaire", "bonus": {"chance": 0.50},
     "description": "Le sort ne lui refuse jamais grand-chose."},
    {"nom": "Élu Universel", "palier": "legendaire", "bonus": {"xp": 0.18, "argent": 0.18, "capture": 0.18, "shiny": 0.18, "chance": 0.18},
     "description": "Un don qui touche absolument tout ce qu'il entreprend."},

    # --- Secrète : encore plus rare que Légendaire, jamais garantie par le pity (voir
    # tirer_race ci-dessous) — un pur coup de chance au-dessus du plancher habituel. ---
    {"nom": "Élu des Cieux", "palier": "secrete", "bonus": {"xp": 0.35, "argent": 0.35, "capture": 0.35, "shiny": 0.35},
     "description": "Une légende parmi les légendes — son nom se murmure plus qu'il ne se raconte."},
    {"nom": "Ombre Insaisissable", "palier": "secrete", "bonus": {"shiny": 1.75},
     "description": "Certains doutent même de son existence — jusqu'à croiser un chromatique dans son sillage."},
    {"nom": "Architecte du Hasard", "palier": "secrete", "bonus": {"capture": 0.75},
     "description": "Aucune ball ne lui échappe — on dit qu'il réécrit le destin d'un lancer avant même qu'il ne parte."},
    {"nom": "Faiseur de Miracles", "palier": "secrete", "bonus": {"chance": 0.90},
     "description": "Ce qui relève du miracle pour les autres est son quotidien."},
    {"nom": "Architecte des Opportunités", "palier": "secrete", "bonus": {"xp": 0.35, "argent": 0.35, "chance": 0.35},
     "description": "Chaque instant recèle une occasion en or — lui seul semble savoir où regarder."},
]

RACES_PAR_NOM = {r["nom"]: r for r in RACES}
RACES_PAR_PALIER = {}
for _r in RACES:
    RACES_PAR_PALIER.setdefault(_r["palier"], []).append(_r)

EMOJI_STAT = {"xp": "✨", "argent": "💰", "shiny": "🌟", "capture": "🎯", "chance": "🍀"}
NOM_STAT = {"xp": "XP", "argent": "Argent", "shiny": "Shiny", "capture": "Capture", "chance": "Chance"}


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
