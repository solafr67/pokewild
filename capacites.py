"""Talents (capacités) et objets tenus — système v1, branché uniquement sur le PvP 1v1
classique (combat.py / resoudre_tour) pour l'instant, comme demandé.

Architecture à POINTS D'ACCROCHE : chaque talent/objet est un dict décrivant lequel de
ses "hooks" il implémente (fonctions optionnelles), et combat.py appelle ces hooks aux
bons moments du tour (entrée en jeu, calcul de dégâts infligés/subis, tentative de
statut, contact, fin de tour). Ajouter un nouveau talent/objet = ajouter une entrée ici,
RIEN d'autre à toucher dans combat.py.

Portée volontairement assumée pour cette v1 : ~25 talents et ~10 objets, hand-picked pour
couvrir des mécaniques bien distinctes (immunités de type, immunité de statut, riposte au
contact, dégâts conditionnels, +stats à l'entrée, fin de tour, objets Choix/Vie/Baie). La
couverture "fidèle aux vrais jeux" (300+ talents) est un chantier CONTINU — ce lot est un
point de départ solide, pas la totalité.

Chaque talent est attribué à la capture au moment où elle est créée, tiré au hasard dans
CAPACITES (voir database.ajouter_capture) — PAS encore lié à un vrai pool par espèce
(ça nécessite de régénérer le Pokédex avec les données de capacités de la PokéAPI, absentes
pour l'instant ; voir generer_pokedex.py). /definir-capacite permet de le changer à la main
en attendant.
"""

import random

# --- Talents ---------------------------------------------------------------------------
# hooks possibles par talent :
#   "immunite_type": type bloqué totalement (dégâts = 0), avec option "soin" (guérit un %
#       des PV max au lieu de subir les dégâts, ex: Absorb Volt) ou "boost" (ex: Cache-Flamme)
#   "immunite_statut": liste des statuts bloqués (jamais appliqués)
#   "sur_entree": (log, user_id, pokemon_nom, adversaire_id, adversaire_nom) -> texte de log
#       ou None — déclenché à l'entrée en jeu (soi ou adversaire selon "cible_entree")
#   "mult_degats_infliges": (contexte) -> multiplicateur (1.0 = neutre)
#   "mult_degats_subis": (contexte) -> multiplicateur (1.0 = neutre)
#   "contact_riposte": (contexte) -> (degats_pourcent_max_pv, statut_inflige, chance) ou None
#   "fin_de_tour": (pv_actuels, pv_max, statut_code) -> delta_pv (positif = soin, négatif = dégâts)
CAPACITES = {
    "intimidation": {
        "nom": "Intimidation", "emoji": "😠",
        "description": "Baisse l'Attaque de l'adversaire de -1 à l'entrée en jeu.",
        "sur_entree": True, "cible_entree": "adversaire", "stat_entree": ("atk", -1),
    },
    "cran": {
        "nom": "Cran", "emoji": "💪",
        "description": "+50% dégâts physiques quand ce Pokémon a un problème de statut.",
        "mult_degats_infliges": "cran",
    },
    "insomnia": {
        "nom": "Insomnia", "emoji": "😳",
        "description": "Ne peut jamais s'endormir.",
        "immunite_statut": ["sleep"],
    },
    "esprit_vital": {
        "nom": "Esprit Vital", "emoji": "✨",
        "description": "Ne peut jamais s'endormir.",
        "immunite_statut": ["sleep"],
    },
    "voile_eau": {
        "nom": "Voile Eau", "emoji": "💧",
        "description": "Ne peut jamais être brûlé.",
        "immunite_statut": ["burn"],
    },
    "armure_magma": {
        "nom": "Armure Magma", "emoji": "🌋",
        "description": "Ne peut jamais être gelé.",
        "immunite_statut": ["freeze"],
    },
    "immunite": {
        "nom": "Immunité", "emoji": "🛡️",
        "description": "Ne peut jamais être empoisonné.",
        "immunite_statut": ["poison"],
    },
    "limber": {
        "nom": "Limber", "emoji": "🤸",
        "description": "Ne peut jamais être paralysé.",
        "immunite_statut": ["paralysis"],
    },
    "absorb_volt": {
        "nom": "Absorb Volt", "emoji": "⚡",
        "description": "Immunisé aux attaques Électrik — soigne 25% de ses PV max à la place.",
        "immunite_type": "electrik", "immunite_type_soin": 0.25,
    },
    "absorb_eau": {
        "nom": "Absorb Eau", "emoji": "🌊",
        "description": "Immunisé aux attaques Eau — soigne 25% de ses PV max à la place.",
        "immunite_type": "eau", "immunite_type_soin": 0.25,
    },
    "levitation": {
        "nom": "Lévitation", "emoji": "🎈",
        "description": "Immunisé aux attaques Sol.",
        "immunite_type": "sol",
    },
    "peau_dure": {
        "nom": "Peau Dure", "emoji": "🦔",
        "description": "Toute attaque physique subie au contact inflige 1/8 des PV max en retour à l'attaquant.",
        "contact_riposte": True, "riposte_pourcent": 0.125,
    },
    "statik": {
        "nom": "Static", "emoji": "🔌",
        "description": "30% de chance de paralyser l'attaquant sur une attaque physique subie au contact.",
        "contact_riposte": True, "riposte_statut": "paralysis", "riposte_chance": 0.30,
    },
    "corps_ardent": {
        "nom": "Corps Ardent", "emoji": "🔥",
        "description": "Ne peut jamais être brûlé. 30% de chance de brûler l'attaquant sur une attaque physique subie au contact.",
        "immunite_statut": ["burn"],
        "contact_riposte": True, "riposte_statut": "burn", "riposte_chance": 0.30,
    },
    "cache_flamme": {
        "nom": "Cache-Flamme", "emoji": "🕯️",
        "description": "Immunisé aux attaques Feu.",
        "immunite_type": "feu",
    },
    "solide_roc": {
        "nom": "Solide Roc", "emoji": "🪨",
        "description": "-25% de dégâts subis sur les attaques super efficaces.",
        "mult_degats_subis": "solide_roc",
    },
    "filtre": {
        "nom": "Filtre", "emoji": "🔍",
        "description": "-25% de dégâts subis sur les attaques super efficaces.",
        "mult_degats_subis": "solide_roc",
    },
    "simple": {
        "nom": "Simple", "emoji": "🎯",
        "description": "Les changements de stats (siens ou infligés) sont doublés.",
        "double_boosts": True,
    },
    "torrent": {
        "nom": "Torrent", "emoji": "💦",
        "description": "+50% de puissance sur les attaques Eau quand les PV sont sous 1/3.",
        "mult_degats_infliges": "torrent", "type_associe": "eau",
    },
    "brasier": {
        "nom": "Brasier", "emoji": "🔥",
        "description": "+50% de puissance sur les attaques Feu quand les PV sont sous 1/3.",
        "mult_degats_infliges": "torrent", "type_associe": "feu",
    },
    "plante": {
        "nom": "Engrais", "emoji": "🌱",
        "description": "+50% de puissance sur les attaques Plante quand les PV sont sous 1/3.",
        "mult_degats_infliges": "torrent", "type_associe": "plante",
    },
    "essaim": {
        "nom": "Essaim", "emoji": "🐝",
        "description": "+50% de puissance sur les attaques Insecte quand les PV sont sous 1/3.",
        "mult_degats_infliges": "torrent", "type_associe": "insecte",
    },
    "regenerescence": {
        "nom": "Régénération", "emoji": "💚",
        "description": "Soigne 1/16 de ses PV max en fin de chaque tour.",
        "fin_de_tour": "soin_fixe", "soin_pourcent": 0.0625,
    },
    "bouclier_poison": {
        "nom": "Bouclier Poison", "emoji": "☠️",
        "description": "Le poison le soigne (1/8 des PV max) au lieu de lui faire perdre des PV.",
        "fin_de_tour": "poison_heal", "soin_pourcent": 0.125,
    },
    "ignifugation": {
        "nom": "Ignifugation", "emoji": "🧯",
        "description": "Ne peut jamais être brûlé, ni empoisonné.",
        "immunite_statut": ["burn", "poison"],
    },
    "tempo_perso": {
        "nom": "Tempo Perso", "emoji": "😵‍💫",
        "description": "Ne peut jamais être confus.",
        "immunite_statut": ["confusion"],
    },
    "aqua_voile": {
        "nom": "Aqua Voile", "emoji": "💦",
        "description": "Ne peut jamais être brûlé.",
        "immunite_statut": ["burn"],
    },
    "coeur_de_fer": {
        "nom": "Cœur de Fer", "emoji": "🔩",
        "description": "-25% de dégâts subis sur les attaques super efficaces.",
        "mult_degats_subis": "solide_roc",
    },
    "male_a_tout_faire": {
        "nom": "Pur Sang", "emoji": "🩸",
        "description": "+50% dégâts physiques quand ce Pokémon a un problème de statut.",
        "mult_degats_infliges": "cran",
    },
    "sec_resse": {
        "nom": "Éponge", "emoji": "🧽",
        "description": "Immunisé aux attaques Plante — soigne 25% de ses PV max à la place.",
        "immunite_type": "plante", "immunite_type_soin": 0.25,
    },
    "coeur_noble": {
        "nom": "Cœur Noble", "emoji": "🖤",
        "description": "Immunisé aux attaques Spectre.",
        "immunite_type": "spectre",
    },
    "roue_libre": {
        "nom": "Roue Libre", "emoji": "🌪️",
        "description": "Immunisé aux attaques Vol.",
        "immunite_type": "vol",
    },
    "parapluie": {
        "nom": "Parapluie", "emoji": "☂️",
        "description": "Immunisé aux attaques Eau.",
        "immunite_type": "eau",
    },
    "bouclier_de_sable": {
        "nom": "Bouclier de Sable", "emoji": "🛡️",
        "description": "Immunisé aux attaques Roche.",
        "immunite_type": "roche",
    },
    "peau_epaisse": {
        "nom": "Peau Épaisse", "emoji": "🐘",
        "description": "-25% de dégâts subis sur les attaques super efficaces.",
        "mult_degats_subis": "solide_roc",
    },
    "carapace_mentale": {
        "nom": "Carapace Mentale", "emoji": "🧠",
        "description": "Immunisé aux attaques Psy.",
        "immunite_type": "psy",
    },
    "griffe_rugueuse": {
        "nom": "Griffe Rugueuse", "emoji": "🐾",
        "description": "Toute attaque physique subie au contact inflige 1/8 des PV max en retour à l'attaquant.",
        "contact_riposte": True, "riposte_pourcent": 0.125,
    },
    "poison_de_contact": {
        "nom": "Point Poison", "emoji": "🟣",
        "description": "30% de chance d'empoisonner l'attaquant sur une attaque physique subie au contact.",
        "contact_riposte": True, "riposte_statut": "poison", "riposte_chance": 0.30,
    },
    "sommeil_de_contact": {
        "nom": "Épine Songe", "emoji": "💤",
        "description": "20% de chance d'endormir l'attaquant sur une attaque physique subie au contact.",
        "contact_riposte": True, "riposte_statut": "sleep", "riposte_chance": 0.20,
    },
    "vampirisme": {
        "nom": "Absorption", "emoji": "🩸",
        "description": "Soigne 1/16 de ses PV max en fin de chaque tour.",
        "fin_de_tour": "soin_fixe", "soin_pourcent": 0.0625,
    },
    "peau_seche": {
        "nom": "Peau Douce", "emoji": "🌵",
        "description": "Immunisé aux attaques Eau — soigne 25% de ses PV max à la place.",
        "immunite_type": "eau", "immunite_type_soin": 0.25,
    },
    "chlorophylle_defense": {
        "nom": "Barbe Végétale", "emoji": "🌾",
        "description": "-25% de dégâts subis sur les attaques super efficaces.",
        "mult_degats_subis": "solide_roc",
    },
    "peau_pierre": {
        "nom": "Peau de Pierre", "emoji": "🗿",
        "description": "Toute attaque physique subie au contact inflige 1/8 des PV max en retour à l'attaquant.",
        "contact_riposte": True, "riposte_pourcent": 0.125,
    },
    "corps_gele": {
        "nom": "Corps Gelé", "emoji": "🧊",
        "description": "Ne peut jamais être gelé. 30% de chance de geler l'attaquant sur une attaque physique subie au contact.",
        "immunite_statut": ["freeze"],
        "contact_riposte": True, "riposte_statut": "freeze", "riposte_chance": 0.30,
    },
}

# --- Objets tenus (v1 : Choix + Vie + une Baie de statut) ------------------------------
# hooks possibles :
#   "mult_stat": (stat, multiplicateur) — bonus de stat passif (ex: Bandeau Choix +50% Atq)
#   "verrouille_attaque": True — force à répéter la même attaque tant que l'objet est tenu
#       (approximation simplifiée : pas de vrai verrouillage inter-tours pour cette v1,
#       seul le bonus de stat est appliqué — le "vrai" verrouillage sera pour un futur lot)
#   "mult_degats_infliges": multiplicateur fixe sur les dégâts infligés
#   "recul_pourcent": % des PV max de l'attaquant perdus après CHAQUE attaque offensive
#   "guerison_statut_seuil": (statuts_soignés, seuil_pv_pourcent) — la baie se déclenche
#       une fois sous ce seuil de PV puis SE CONSOMME (retirée de l'inventaire du combat)
OBJETS_TENUS = {
    "bandeau_choix": {
        "nom": "Bandeau Choix", "emoji": "📿",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/bandeau_choix.png",
        "description": "+50% Attaque, mais oblige à utiliser la même attaque à chaque tour.",
        "mult_stat": ("atk", 1.5), "verrouille_attaque": True,
    },
    "specs_choix": {
        "nom": "Lunettes Choix", "emoji": "👓",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/specs_choix.png",
        "description": "+50% Attaque Spéciale, mais oblige à utiliser la même attaque à chaque tour.",
        "mult_stat": ("atk_spe", 1.5), "verrouille_attaque": True,
    },
    "bandana_choix": {
        "nom": "Mouchoir Choix", "emoji": "🧣",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/bandana_choix.png",
        "description": "+50% Vitesse, mais oblige à utiliser la même attaque à chaque tour.",
        "mult_stat": ("vit", 1.5), "verrouille_attaque": True,
    },
    "orbe_vie": {
        "nom": "Orbe Vie", "emoji": "🔮",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_vie.png",
        "description": "+30% de dégâts infligés, mais perd 10% de ses PV max après chaque attaque.",
        "mult_degats_infliges": 1.30, "recul_pourcent": 0.10,
    },
    "baie_sitrus": {
        "nom": "Baie Sitrus", "emoji": "🍇",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_sitrus.png",
        "description": "Se déclenche automatiquement sous 50% des PV max : soigne 25% des PV max (une fois).",
        "guerison_pv_seuil": 0.50, "guerison_pv_pourcent": 0.25,
    },
    "baie_pecha": {
        "nom": "Baie Pêcha", "emoji": "🍑",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_pecha.png",
        "description": "Guérit automatiquement l'empoisonnement (une fois).",
        "guerison_statut_seuil": (["poison"], 1.0),
    },
    "baie_cheri": {
        "nom": "Baie Cheri", "emoji": "🍒",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_cheri.png",
        "description": "Guérit automatiquement la paralysie (une fois).",
        "guerison_statut_seuil": (["paralysis"], 1.0),
    },
    "baie_kika": {
        "nom": "Baie Kika", "emoji": "🍋",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_kika.png",
        "description": "Guérit automatiquement la brûlure (une fois).",
        "guerison_statut_seuil": (["burn"], 1.0),
    },
    "ceinture_force": {
        "nom": "Ceinture Force", "emoji": "🥊",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/ceinture_force.png",
        "description": "Survit toujours à 1 PV si l'attaque qui devait l'achever partait de PV pleins (une fois).",
        "sturdy_like": True,
    },
    "reste": {
        "nom": "Reste", "emoji": "🍃",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/reste.png",
        "description": "Soigne 1/16 de ses PV max en fin de chaque tour.",
        "fin_de_tour_soin_pourcent": 0.0625,
    },
    "baie_oran": {
        "nom": "Baie Oran", "emoji": "🫐",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_oran.png",
        "description": "Se déclenche automatiquement sous 50% des PV max : soigne 10% des PV max (une fois).",
        "guerison_pv_seuil": 0.50, "guerison_pv_pourcent": 0.10,
    },
    "baie_lombre": {
        "nom": "Baie Lombre", "emoji": "☁️",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_lombre.png",
        "description": "Guérit automatiquement le sommeil (une fois).",
        "guerison_statut_seuil": (["sleep"], 1.0),
    },
    "baie_rawst": {
        "nom": "Baie Rawst", "emoji": "🍏",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_rawst.png",
        "description": "Guérit automatiquement la brûlure (une fois).",
        "guerison_statut_seuil": (["burn"], 1.0),
    },
    "baie_persim": {
        "nom": "Baie Persim", "emoji": "🍊",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/baie_persim.png",
        "description": "Guérit automatiquement la confusion (une fois).",
        "guerison_statut_seuil": (["confusion"], 1.0),
    },
    "lunettes_cerema": {
        "nom": "Lunettes Cérema", "emoji": "🥽",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/lunettes_cerema.png",
        "description": "+30% Attaque Spéciale (bonus passif, pas de verrouillage d'attaque).",
        "mult_stat": ("atk_spe", 1.30),
    },
    "ceinture_musclor": {
        "nom": "Ceinture Musclor", "emoji": "🏋️",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/ceinture_musclor.png",
        "description": "+30% Attaque (bonus passif, pas de verrouillage d'attaque).",
        "mult_stat": ("atk", 1.30),
    },
    "chaussures_agiles": {
        "nom": "Chaussures Agiles", "emoji": "👟",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/chaussures_agiles.png",
        "description": "+30% Vitesse (bonus passif, pas de verrouillage d'attaque).",
        "mult_stat": ("vit", 1.30),
    },
    "carapace_dure": {
        "nom": "Carapace Dure", "emoji": "🐢",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/carapace_dure.png",
        "description": "+30% Défense (bonus passif).",
        "mult_stat": ("def", 1.30),
    },
    "ecaille_lumiere": {
        "nom": "Écaille Lumière", "emoji": "✨",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/ecaille_lumiere.png",
        "description": "+30% Défense Spéciale (bonus passif).",
        "mult_stat": ("def_spe", 1.30),
    },
    "orbe_feu": {
        "nom": "Orbe Feu", "emoji": "🔥",
        "image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_feu.png",
        "description": "+30% de dégâts infligés, mais perd 10% de ses PV max après chaque attaque.",
        "mult_degats_infliges": 1.30, "recul_pourcent": 0.10,
    },
}


def talent_aleatoire() -> str:
    """Tire un talent au hasard dans le pool implémenté — utilisé en dernier recours pour
    une espèce sans entrée dans POKEMON_CAPACITES (voir capacite_pour_espece)."""
    return random.choice(list(CAPACITES.keys()))


# Vraies capacités possibles par espèce (fidèles aux jeux officiels), limitées aux
# capacités qui ont un effet RÉELLEMENT implémenté ci-dessus — chantier progressif, pas
# encore exhaustif sur les 1025 espèces. Une espèce absente de ce dict retombe sur
# talent_aleatoire() (un talent générique au hasard) en attendant d'être curatée ici.
POKEMON_CAPACITES = {
    "Bulbizarre": ["plante"], "Herbizarre": ["plante"], "Florizarre": ["plante"],
    "Salamèche": ["brasier"], "Reptincel": ["brasier"], "Dracaufeu": ["brasier"],
    "Carapuce": ["torrent"], "Carabaffe": ["torrent"], "Tortank": ["torrent"],
    "Machoc": ["cran"], "Machopeur": ["cran"], "Machamp": ["cran"],
    "Ronflex": ["immunite"],
    "Motisma": ["levitation"],
    "Ponyta": ["corps_ardent"], "Galopa": ["corps_ardent"],
    "Dardargnan": ["essaim"],
    "Goupix": ["cache_flamme"], "Feunard": ["cache_flamme"],
    "Simiabraz": ["brasier"],
    "Pharamp": ["statik"],
    "Léviator": ["intimidation"],
    "Scarabrute": ["cran"],
}


def capacite_pour_espece(pokemon_nom: str) -> str:
    """Tire une capacité pour cette espèce précise — parmi ses vraies capacités possibles
    si elle est déjà curatée dans POKEMON_CAPACITES, sinon un talent générique au hasard
    (voir la docstring de POKEMON_CAPACITES)."""
    possibles = POKEMON_CAPACITES.get(pokemon_nom)
    if possibles:
        return random.choice(possibles)
    return talent_aleatoire()


def infos_capacite(cle: str) -> dict | None:
    return CAPACITES.get(cle)


def infos_objet(cle: str) -> dict | None:
    return OBJETS_TENUS.get(cle)


# --- Hooks appelés par combat.py --------------------------------------------------------

def bloque_statut(capacite: str, code_statut: str) -> bool:
    info = CAPACITES.get(capacite)
    if not info:
        return False
    return code_statut in info.get("immunite_statut", [])


def immunite_type(capacite: str, type_attaque: str) -> dict | None:
    """Retourne des infos si ce talent bloque totalement ce type d'attaque, sinon None."""
    info = CAPACITES.get(capacite)
    if not info or info.get("immunite_type") != type_attaque:
        return None
    return info


def multiplicateur_degats_infliges(capacite: str, objet: str, pv_actuels: int, pv_max: int, type_attaque: str, classe_attaque: str) -> float:
    mult = 1.0
    info = CAPACITES.get(capacite)
    if info:
        cle = info.get("mult_degats_infliges")
        if cle == "cran" and classe_attaque == "physical":
            pass  # géré séparément (dépend d'avoir un statut, pas d'ici) — voir combat.py
        if cle == "torrent" and info.get("type_associe") == type_attaque and pv_actuels <= pv_max / 3:
            mult *= 1.5
    obj = OBJETS_TENUS.get(objet)
    if obj and "mult_degats_infliges" in obj:
        mult *= obj["mult_degats_infliges"]
    return mult


def multiplicateur_degats_subis(capacite: str, multi_type: float) -> float:
    info = CAPACITES.get(capacite)
    if info and info.get("mult_degats_subis") == "solide_roc" and multi_type >= 2.0:
        return 0.75
    return 1.0


def effet_fin_de_tour(capacite: str, objet: str, pv_actuels: int, pv_max: int, statut_code: str | None) -> tuple:
    """Retourne (delta_pv, texte_log) pour les effets de fin de tour (talent OU objet —
    le talent est prioritaire s'il gère aussi le statut concerné, ex: Bouclier Poison)."""
    info = CAPACITES.get(capacite)
    if info:
        cle = info.get("fin_de_tour")
        if cle == "poison_heal" and statut_code == "poison":
            soin = max(1, round(pv_max * info["soin_pourcent"]))
            return soin, f"☠️➡️💚 soigné par son propre poison grâce à **{info['nom']}**"
        if cle == "soin_fixe" and pv_actuels < pv_max:
            soin = max(1, round(pv_max * info["soin_pourcent"]))
            return soin, f"💚 récupère un peu de PV grâce à **{info['nom']}**"
    obj = OBJETS_TENUS.get(objet)
    if obj and "fin_de_tour_soin_pourcent" in obj and pv_actuels < pv_max and pv_actuels > 0:
        soin = max(1, round(pv_max * obj["fin_de_tour_soin_pourcent"]))
        return soin, f"🍃 récupère un peu de PV grâce à **{obj['nom']}**"
    return 0, None


def multiplicateur_stat_objet(objet: str, cle_stat: str) -> float:
    """Bonus passif de stat d'un objet tenu (ex: Bandeau Choix +50% Attaque). cle_stat
    parmi 'atk'/'atk_spe'/'vit'/'def'/'def_spe' — 1.0 si aucun bonus applicable."""
    obj = OBJETS_TENUS.get(objet)
    if obj and "mult_stat" in obj:
        stat_associee, mult = obj["mult_stat"]
        if stat_associee == cle_stat:
            return mult
    return 1.0


def verrouille_attaque(objet: str) -> bool:
    """True si tenir cet objet force à répéter la même attaque tant qu'il est tenu et que
    le Pokémon reste sur le terrain (Objets Choix)."""
    obj = OBJETS_TENUS.get(objet)
    return bool(obj and obj.get("verrouille_attaque"))


def guerison_statut_objet(objet: str, code_statut: str) -> dict | None:
    """Retourne les infos de l'objet s'il guérit CE statut précis à l'usage unique (baies
    Pêcha/Chéri/Kika...), sinon None."""
    obj = OBJETS_TENUS.get(objet)
    if not obj or "guerison_statut_seuil" not in obj:
        return None
    statuts_soignes, _seuil = obj["guerison_statut_seuil"]
    return obj if code_statut in statuts_soignes else None


def double_les_boosts(capacite: str) -> bool:
    """Talent Simple : tout changement de stat (subi ou infligé par ce Pokémon) est doublé."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("double_boosts"))
