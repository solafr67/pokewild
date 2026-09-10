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
    "intrepide": {
        "nom": "Intrépide", "emoji": "⚔️",
        "description": "Augmente sa propre Attaque de +1 à l'entrée en jeu.",
        "sur_entree": True, "cible_entree": "soi", "stat_entree": ("atk", 1),
    },
    "bouclier_royal": {
        "nom": "Bouclier Royal", "emoji": "🛡️",
        "description": "Augmente sa propre Défense de +1 à l'entrée en jeu.",
        "sur_entree": True, "cible_entree": "soi", "stat_entree": ("def", 1),
    },
    "tenacite": {
        "nom": "Ténacité", "emoji": "💪",
        "description": "+50% dégâts physiques quand ce Pokémon a un problème de statut (ignore aussi le malus d'Attaque de la Brûlure).",
        "mult_degats_infliges": "cran",
    },
    "telechargement": {
        "nom": "Téléchargement", "emoji": "💾",
        "description": "À l'entrée, +1 Attaque si la Défense adverse est plus basse que sa Défense Spéciale, sinon +1 Attaque Spéciale.",
        # Traité comme cas spécial directement dans combat.py::_declencher_talent_entree —
        # la stat boostée est choisie dynamiquement selon l'adversaire, impossible à
        # exprimer avec le simple stat_entree=(stat, delta) fixe des autres talents d'entrée.
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
    "etoile_victoire": {
        "nom": "Étoile Victoire", "emoji": "⭐",
        "description": "+10% de Précision sur les attaques de ce Pokémon (et de ses alliés en combat 2v2).",
        "boost_precision_attaque": 1.1,
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
    "voile_sucre": {
        "nom": "Voile Sucré", "emoji": "🍬",
        "description": "Ne peut jamais s'endormir.",
        "immunite_statut": ["sleep"],
    },
    "moelleux": {
        "nom": "Moelleux", "emoji": "🧸",
        "description": "Dégâts physiques subis divisés par 2, dégâts Feu subis doublés.",
        "moelleux": True,
    },
    "dommage_sec": {
        "nom": "Dommage Sec", "emoji": "💢",
        "description": "En étant mis K.O. par une attaque physique au contact, inflige 25% des PV max de l'attaquant en retour.",
        "dommage_sec": True,
    },
    "expuls_organes": {
        "nom": "Expuls'Organes", "emoji": "🫀",
        "description": "En étant mis K.O. (n'importe quelle attaque), inflige à l'attaquant des dégâts égaux à ses propres PV restants avant le coup fatal.",
        "expuls_organes": True,
    },
    "supermutation": {
        "nom": "Supermutation", "emoji": "🦸",
        "description": "Passe en forme Super (stats bien plus élevées, v1 approximée à x1.9 uniforme) après un changement hors puis retour sur le terrain, pour le reste du combat.",
        "supermutation": True,
    },
    "bancosphere": {
        "nom": "Bancosphère", "emoji": "🐟",
        "description": "Forme École (x6 Attaque/Défense/Attaque Spé/Défense Spé, x0.75 Vitesse, v1 approximé) tant que niveau 20+ et PV au-dessus de 25%.",
        "bancosphere": True,
    },
    "anti_air": {
        "nom": "Anti-Air", "emoji": "🎯",
        "description": "Toute attaque touche toujours, que ce Pokémon attaque ou soit visé.",
        "anti_air": True,
    },
    "poigne_de_fer": {
        "nom": "Poigne de Fer", "emoji": "✊",
        "description": "+30% sur ses attaques au contact.",
        "boost_contact": True,
    },
    "machoire_brute": {
        "nom": "Mâchoire Brute", "emoji": "🦷",
        "description": "+50% sur ses attaques de morsure (liste limitée).",
        "boost_morsure": True,
    },
    "momie": {
        "nom": "Momie", "emoji": "🧟",
        "description": "Au contact, transforme la capacité de l'attaquant en Momie — qui se propage à son tour à qui la touche.",
        "momie": True,
    },
    "esprit_vagabond": {
        "nom": "Esprit Vagabond", "emoji": "👻",
        "description": "Au contact, échange sa propre capacité avec celle de l'attaquant.",
        "esprit_vagabond": True,
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
    "lenteur": {
        "nom": "Lenteur", "emoji": "🐌",
        "description": "Attaque et Vitesse divisées par 2 pendant les 5 premiers tours après l'envoi sur le terrain.",
        "debut_lent": 5,
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
    "prisme_armure": {
        "nom": "Prisme Armure", "emoji": "💎",
        "description": "-25% de dégâts subis sur les attaques super efficaces.",
        "mult_degats_subis": "solide_roc",  # même effet mécanique que Filtre, juste un autre nom/porteur
    },
    "poing_de_fer": {
        "nom": "Poing de Fer", "emoji": "🥊",
        "description": "+20% sur ses attaques de poing (liste limitée, voir ATTAQUES_POING).",
        "boost_poing": True,
    },
    "electro_surge": {
        "nom": "Électro Surge", "emoji": "⚡",
        "description": "Déclenche le Terrain Électrique à l'entrée en jeu.",
        "terrain_entree": "electrique",
    },
    "chloro_surge": {
        "nom": "Chloro Surge", "emoji": "🌿",
        "description": "Déclenche le Terrain Herbu à l'entrée en jeu.",
        "terrain_entree": "herbu",
    },
    "aura_surge": {
        "nom": "Aura Surge", "emoji": "🌫️",
        "description": "Déclenche le Terrain Brumeux à l'entrée en jeu.",
        "terrain_entree": "brumeux",
    },
    "psycho_surge": {
        "nom": "Psycho Surge", "emoji": "🔮",
        "description": "Déclenche le Terrain Psychique à l'entrée en jeu.",
        "terrain_entree": "psychique",
    },
    "bouclier_ombre": {
        "nom": "Bouclier de l'Ombre", "emoji": "🌑",
        "description": "Dégâts subis divisés par 2 tant que ce Pokémon est à pleine vie.",
        "reduit_degats_pleine_vie": True,
    },
    "carapace_tera": {
        "nom": "Carapace Téra", "emoji": "🐢",
        "description": "Tant qu'à pleine vie, toute attaque qui touche est plafonnée à \"pas très efficace\", même si elle aurait dû être neutre ou super efficace.",
        "plafonne_efficacite_pleine_vie": True,
    },
    "corps_contraire": {
        "nom": "Corps Contraire", "emoji": "🔄",
        "description": "Tout changement de stat que subit ce Pokémon est inversé — une baisse devient une hausse, et vice versa.",
        "inverse_stats": True,
    },
    "garde_feuille": {
        "nom": "Garde Feuille", "emoji": "🍃",
        "description": "Immunisé à tout problème de statut tant que le Soleil brille.",
        "immunite_statut_meteo": ("soleil", ["burn", "poison", "paralysis", "sleep", "freeze"]),
    },
    "multitype": {
        "nom": "Multitype", "emoji": "💠",
        "description": "Change de type selon la Plaque tenue (voir Boutique/Exploration) — sans Plaque, reste Normal.",
        # Purement informatif : le vrai changement de type/stats vit dans
        # formes_objets.py (FORMES_OBJETS, entrées "plaque_*"), qui ne dépend PAS de
        # cette capacité pour s'activer (uniquement de l'objet tenu + l'espèce).
    },
    "systeme_alpha": {
        "nom": "Système Alpha", "emoji": "💠",
        "description": "Change de type selon la ROM tenue (voir Boutique/Exploration) — sans ROM, reste Normal.",
        # Idem Multitype : mécanisme réel dans formes_objets.py (entrées "rom_*").
    },
    "fleau_tablettes": {
        "nom": "Fléau des Tablettes", "emoji": "📜",
        "description": "-25% d'Attaque chez tous les autres Pokémon sur le terrain (jamais chez lui-même).",
        "fleau_stat": "atk",
    },
    "fleau_epee": {
        "nom": "Fléau de l'Épée", "emoji": "⚔️",
        "description": "-25% de Défense chez tous les autres Pokémon sur le terrain (jamais chez lui-même).",
        "fleau_stat": "def",
    },
    "fleau_urne": {
        "nom": "Fléau de l'Urne", "emoji": "🏺",
        "description": "-25% d'Attaque Spéciale chez tous les autres Pokémon sur le terrain (jamais chez lui-même).",
        "fleau_stat": "atk_spe",
    },
    "fleau_perles": {
        "nom": "Fléau des Perles", "emoji": "📿",
        "description": "-25% de Défense Spéciale chez tous les autres Pokémon sur le terrain (jamais chez lui-même).",
        "fleau_stat": "def_spe",
    },
    "rupture_aura": {
        "nom": "Rupture Aura", "emoji": "💔",
        "description": "Inverse Aura Fée/Aura Sombre en malus (-25% au lieu de +33%) tant qu'elles sont actives.",
        "aura_break": True,
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
        "description": "Soigne 33% de ses PV max en quittant le combat (changement volontaire, pas K.O.).",
        "soin_sortie_terrain": 0.33,
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
    "rustique": {
        "nom": "Rustique", "emoji": "🪨",
        "description": "Survit toujours avec 1 PV à un coup qui l'aurait mis K.O. depuis ses PV max.",
        "sturdy": True,
    },
    "tete_de_roc": {
        "nom": "Tête de Roc", "emoji": "🗿",
        "description": "Immunisé aux dégâts de contrecoup (Boutefeu, Bélier, etc. — pas Lutte).",
        "immunite_recul": True,
    },
    "synchro": {
        "nom": "Synchro", "emoji": "🔗",
        "description": "Renvoie à l'adversaire le même statut (Poison/Brûlure/Paralysie) qu'il vient d'infliger.",
        "synchronize": True,
    },
    "mue": {
        "nom": "Mue", "emoji": "🐍",
        "description": "30% de chance de guérir son propre problème de statut à la fin de chaque tour.",
        "shed_skin": True,
    },
    "corps_sain": {
        "nom": "Corps Sain", "emoji": "🛡️",
        "description": "Immunisé aux baisses de stats infligées par l'adversaire (les siennes restent possibles).",
        "immunite_baisse_stat_adverse": True,
    },
    "grace_sereine": {
        "nom": "Grâce Sereine", "emoji": "🌸",
        "description": "Double les chances des effets secondaires de ses attaques (statut, altération...).",
        "double_chance_secondaire": True,
    },
    "pression": {
        "nom": "Pression", "emoji": "😤",
        "description": "Les attaques utilisées contre lui consomment 2 PP au lieu d'1.",
        "double_cout_pp_adverse": True,
    },
    "gourmandise": {
        "nom": "Gourmandise", "emoji": "🍒",
        "description": "Mange sa Baie de soin dès 50% de ses PV max au lieu de 25%.",
        "double_seuil_baie": True,
    },
    "vigilance": {
        "nom": "Vigilance", "emoji": "🌿",
        "description": "Guérit automatiquement son propre problème de statut en quittant le combat (changement volontaire, pas K.O.).",
        "soin_statut_sortie_terrain": True,
    },
    "herbivore": {
        "nom": "Herbivore", "emoji": "🌾",
        "description": "Immunisé aux attaques Plante — gagne +1 Attaque au lieu d'en subir les dégâts.",
        "immunite_type": "plante", "immunite_type_boost_stat": ("atk", 1),
    },
    "cuisson_parfaite": {
        "nom": "Cuisson Parfaite", "emoji": "🥖",
        "description": "Immunisé aux attaques Feu — gagne +2 Défense au lieu d'en subir les dégâts.",
        "immunite_type": "feu", "immunite_type_boost_stat": ("def", 2),
    },
    "magnetisme": {
        "nom": "Magnétisme", "emoji": "🧲",
        "description": "Immunisé aux attaques Électrik — gagne +1 Attaque Spéciale au lieu d'en subir les dégâts.",
        "immunite_type": "electrik", "immunite_type_boost_stat": ("atk_spe", 1),
    },
    "absorbe_averse": {
        "nom": "Absorbe Averse", "emoji": "🌊",
        "description": "Immunisé aux attaques Eau — gagne +1 Attaque Spéciale au lieu d'en subir les dégâts.",
        "immunite_type": "eau", "immunite_type_boost_stat": ("atk_spe", 1),
    },
    "carapace": {
        "nom": "Carapace", "emoji": "🐚",
        "description": "Ne peut jamais subir de coup critique.",
        "immunite_critique": True,
    },
    "cauchemar": {
        "nom": "Cauchemar", "emoji": "😴",
        "description": "Tant que ce Pokémon est sur le terrain, l'adversaire actif endormi perd 1/8 de ses PV max à la fin de chaque tour.",
        "degats_sommeil_adverse": 1 / 8,
    },
    "determination": {
        "nom": "Détermination", "emoji": "🎯",
        "description": "Ne peut jamais flancher (Flinch).",
        "immunite_flinch": True,
    },
    "chlorophylle": {
        "nom": "Chlorophylle", "emoji": "🌻",
        "description": "Double sa Vitesse sous le Soleil.",
        "double_vitesse_meteo": "soleil",
    },
    "nage_rapide": {
        "nom": "Nage Rapide", "emoji": "🏊",
        "description": "Double sa Vitesse sous la Pluie.",
        "double_vitesse_meteo": "pluie",
    },
    "secheresse": {
        "nom": "Sécheresse", "emoji": "☀️",
        "description": "Fait briller le soleil (5 tours) à l'entrée en jeu.",
        "sur_entree": True, "meteo_entree": "soleil",
    },
    "pulsion_orichalque": {
        "nom": "Pulsion Orichalque", "emoji": "🔥",
        "description": "Fait briller le soleil (5 tours) à l'entrée en jeu, et +33% d'Attaque tant que le Soleil brille.",
        "sur_entree": True, "meteo_entree": "soleil",
        "boost_stat_meteo": ("soleil", "atk", 4 / 3),
    },
    "moteur_hadron": {
        "nom": "Moteur Hadron", "emoji": "⚡",
        "description": "Déclenche le Terrain Électrique (5 tours) à l'entrée en jeu, et +33% d'Attaque Spéciale tant que ce terrain est actif.",
        "terrain_entree": "electrique",
        "boost_stat_terrain": ("electrique", "atk_spe", 4 / 3),
    },
    "vigueur_ancestrale": {
        "nom": "Vigueur Ancestrale", "emoji": "☀️",
        "description": "+30% (ou +50% si c'est la Vitesse) sur sa stat de base la plus élevée, tant que le Soleil brille.",
        "stat_dominante_condition": ("meteo", "soleil"),
    },
    "turbo_circuit": {
        "nom": "Turbo Circuit", "emoji": "🔋",
        "description": "+30% (ou +50% si c'est la Vitesse) sur sa stat de base la plus élevée, tant que le Terrain Électrique est actif.",
        "stat_dominante_condition": ("terrain", "electrique"),
    },
    "ecailles_magiques": {
        "nom": "Écailles Magiques", "emoji": "🐟",
        "description": "+50% Défense tant qu'il a un problème de statut.",
        "boost_defense_si_statut": True,
    },
    "pied_veloce": {
        "nom": "Pied Véloce", "emoji": "🏃",
        "description": "+50% Vitesse tant qu'il a un problème de statut.",
        "boost_vitesse_si_statut": True,
    },
    "ronfleur": {
        "nom": "Ronfleur", "emoji": "🔇",
        "description": "Immunisé aux attaques sonores (liste limitée).",
        "immunite_sonore": True,
    },
    "cran_vital": {
        "nom": "Cran Vital", "emoji": "💨",
        "description": "+1 Vitesse à la fin de chaque tour passé actif sur le terrain.",
        "cran_vital": True,
    },
    "wonder_guard": {
        "nom": "Wonder Guard", "emoji": "🌟",
        "description": "Immunisé à toute attaque qui n'est pas super efficace.",
        "wonder_guard": True,
    },
    "absenteisme": {
        "nom": "Absentéisme", "emoji": "😴",
        "description": "N'agit qu'un tour sur deux, glande l'autre.",
        "absenteisme": True,
    },
    "facsimile": {
        "nom": "Fac-similé", "emoji": "🎎",
        "description": "Bloque intégralement un coup sur toute la durée du combat (1/8 PV max perdu à la place).",
        "facsimile": True,
    },
    "ombre_portee": {
        "nom": "Ombre Portée", "emoji": "🕶️",
        "description": "Empêche l'adversaire de changer volontairement de Pokémon tant qu'il est en vie.",
        "piege_adversaire": True,
    },
    "chochotte": {
        "nom": "Chochotte", "emoji": "😟",
        "description": "Attaque et Attaque Spéciale divisées par 2 dès que les PV tombent à 50% ou moins.",
        "chochotte": True,
    },
    "pure_puissance": {
        "nom": "Pure Puissance", "emoji": "💪",
        "description": "Double sa propre Attaque physique (jamais l'Attaque Spéciale).",
        "pure_puissance": True,
    },
    "tactiques_simiesques": {
        "nom": "Tactiques Simiesques", "emoji": "🦍",
        "description": "+50% Attaque physique (v1 simplifiée : ne verrouille pas sur la première attaque choisie, contrairement aux vrais jeux).",
        "tactiques_simiesques": True,
    },
    "fourrure_renforcee": {
        "nom": "Fourrure Renforcée", "emoji": "🧥",
        "description": "Dégâts physiques subis divisés par 2 (jamais les dégâts spéciaux).",
        "fourrure_renforcee": True,
    },
    "or_pur": {
        "nom": "Or Pur", "emoji": "🪙",
        "description": "Immunisé à toute attaque de statut adverse.",
        "bloque_statut_adverse": True,
    },
    "armure_fragile": {
        "nom": "Armure Fragile", "emoji": "🔨",
        "description": "Quand touché par une attaque physique : -1 Défense, +2 Vitesse.",
        "armure_fragile": True,
    },
    "pixelisation": {
        "nom": "Pixilate", "emoji": "🌸",
        "description": "Ses attaques Normal deviennent Fée, avec +30% de puissance.",
        "transforme_normal_en": "fee",
    },
    "porte_secours": {
        "nom": "Porte de Secours", "emoji": "🚪",
        "description": "Se retire automatiquement du combat la première fois que ses PV passent sous 50%.",
        "porte_secours": True,
    },
    "corps_maudit": {
        "nom": "Corps Maudit", "emoji": "👻",
        "description": "30% de chance de désactiver (4 tours) l'attaque adverse qui vient de toucher.",
        "chance_desactivation": 0.30,
    },
    "stance_change": {
        "nom": "Stance Change", "emoji": "⚔️",
        "description": "Passe en forme Lame (Attaque/Attaque Spé élevées) sur une attaque offensive, en forme Bouclier (Défense/Défense Spé élevées) sur Bouclier Royal.",
        "stance_change": True,
    },
    "averse": {
        "nom": "Averse", "emoji": "🌧️",
        "description": "Fait pleuvoir (5 tours) à l'entrée en jeu.",
        "sur_entree": True, "meteo_entree": "pluie",
    },
    "sable_volant": {
        "nom": "Sable Volant", "emoji": "🌪️",
        "description": "Déclenche une tempête de sable (5 tours) à l'entrée en jeu.",
        "sur_entree": True, "meteo_entree": "sable",
    },
    "alerte_neige": {
        "nom": "Alerte Neige", "emoji": "🌨️",
        "description": "Déclenche la grêle (5 tours) à l'entrée en jeu.",
        "sur_entree": True, "meteo_entree": "grele",
    },
    "fouille": {
        "nom": "Fouille", "emoji": "🔍",
        "description": "Révèle l'objet tenu de l'adversaire à l'entrée en jeu.",
        "sur_entree": True, "revele_objet_entree": True,
    },
    "coeur_de_coq": {
        "nom": "Cœur de Coq", "emoji": "🐓",
        "description": "Immunisé aux baisses de Défense infligées par l'adversaire (les siennes restent possibles).",
        "protege_stat_adverse": "def",
    },
    "bras_seca": {
        "nom": "Bras Séca", "emoji": "✂️",
        "description": "Immunisé aux baisses d'Attaque infligées par l'adversaire (les siennes restent possibles).",
        "protege_stat_adverse": "atk",
    },
    "chloro_semence": {
        "nom": "Chloro Semence", "emoji": "🌱",
        "description": "Déclenche le Terrain Herbu (5 tours) quand touché par une attaque offensive.",
        "terrain_entree": "herbu",
    },
    "force_brute": {
        "nom": "Force Brute", "emoji": "💥",
        "description": "+30% de puissance sur ses attaques ayant un effet secondaire, mais annule cet effet secondaire.",
        "force_brute": True,
    },
    "corrosion": {
        "nom": "Corrosion", "emoji": "🧪",
        "description": "Peut empoisonner un Pokémon Poison ou Acier malgré leur immunité de type naturelle.",
        "corrosion": True,
    },
    "mega_blaster": {
        "nom": "Méga Blaster", "emoji": "💦",
        "description": "+50% sur ses attaques de la famille vibration/aura (liste limitée, voir ATTAQUES_PULSE).",
        "boost_pulse": True,
    },
    "turbine_eolienne": {
        "nom": "Turbine Éolienne", "emoji": "🌬️",
        "description": "Immunisé aux dégâts d'une attaque de la famille vent (liste limitée), et gagne +1 Attaque en plus.",
        "immunite_vent": True,
    },
    "mycelium_might": {
        "nom": "Mycelium Might", "emoji": "🍄",
        "description": "Ses attaques de statut agissent toujours en dernier dans leur tranche de priorité, mais ignorent l'immunité de capacité de la cible.",
        "mycelium_might": True,
    },
    "illusion": {
        "nom": "Illusion", "emoji": "🎭",
        "description": "Se déguise en le dernier Pokémon conscient de l'équipe jusqu'à subir un coup.",
        "illusion": True,
    },
    "metal_leger": {
        "nom": "Métal Léger", "emoji": "🪶",
        "description": "Son poids effectif est divisé par 2 pour le calcul des attaques basées sur le poids (Nœud Herbe, Balayage, Tacle Lourd, Tacle Feu).",
        "mult_poids": 0.5,
    },
    "metal_lourd": {
        "nom": "Métal Lourd", "emoji": "⚓",
        "description": "Son poids effectif est doublé pour le calcul des attaques basées sur le poids (Nœud Herbe, Balayage, Tacle Lourd, Tacle Feu).",
        "mult_poids": 2.0,
    },
    "hospitalite": {
        "nom": "Hospitalité", "emoji": "🍵",
        "description": "Soigne son allié de 25% de ses PV max à l'entrée en jeu (2v2 uniquement — aucun effet en 1v1).",
        "soin_allie_entree": 0.25,
    },
    "voile_floral": {
        "nom": "Voile Floral", "emoji": "🌸",
        "description": "Protège les alliés Plante des baisses de stats et des problèmes de statut (2v2 uniquement — aucun effet en 1v1).",
        "protege_allie_type": "plante",
    },
    "ordre_royal": {
        "nom": "Ordre Royal", "emoji": "👑",
        "description": "Bloque toute attaque adverse à priorité positive (liste limitée).",
        "bloque_priorite": True,
    },
    "miroir_magik": {
        "nom": "Miroir Magik", "emoji": "🪞",
        "description": "Renvoie une attaque de statut adverse vers son lanceur au lieu de la subir.",
        "miroir_magik": True,
    },
    "adaptabilite": {
        "nom": "Adaptabilité", "emoji": "🔥",
        "description": "Le STAB (bonus de même type) passe de x1.5 à x2.0.",
        "adaptabilite": True,
    },
    "garde_magique": {
        "nom": "Garde Magique", "emoji": "🛡️",
        "description": "Immunisé à tout dégât indirect (statut, météo).",
        "garde_magique": True,
    },
    "camouflage": {
        "nom": "Camouflage", "emoji": "🦎",
        "description": "Change son propre type pour correspondre à la dernière attaque offensive subie.",
        "camouflage": True,
    },
    "forme_meteo": {
        "nom": "Forme Météo", "emoji": "🌈",
        "description": "Change son propre type selon la météo active : Soleil -> Feu, Pluie -> Eau, Grêle -> Glace, sinon Normal.",
        "forme_meteo": True,
    },
    "tension": {
        "nom": "Tension", "emoji": "😰",
        "description": "L'adversaire ne peut pas manger sa Baie de soin face à ce Pokémon.",
        "empeche_baie_adverse": True,
    },
    "multi_coups": {
        "nom": "Multi-Coups", "emoji": "🔢",
        "description": "Les attaques à coups multiples portent toujours le nombre maximal de coups (liste limitée).",
        "multi_coups": True,
    },
    "charme_ensorceleur": {
        "nom": "Charme Ensorceleur", "emoji": "💕",
        "description": "30% de chance d'infatuer l'attaquant au contact, si son genre est opposé au sien.",
        "charme_ensorceleur": True,
    },
    "technicien": {
        "nom": "Technicien", "emoji": "🔧",
        "description": "+50% de puissance sur les attaques de 60 ou moins de puissance de base.",
        "boost_attaques_faible_puissance": True,
    },
    "ecran_poudre": {
        "nom": "Écran Poudre", "emoji": "💨",
        "description": "Immunisé aux effets secondaires (statut/altération) des attaques subies — pas aux dégâts eux-mêmes.",
        "bloque_effets_secondaires_subis": True,
    },
    "boost_chimere": {
        "nom": "Boost Chimère", "emoji": "👽",
        "description": "+1 à sa statistique la plus élevée à chaque K.O. infligé.",
        "boost_apres_ko": True,
    },
    "querelleur": {
        "nom": "Querelleur", "emoji": "👊",
        "description": "Ses attaques Normal/Combat touchent les Spectre. Immunisé à Intimidation.",
        "touche_spectre_normal_combat": True, "immunite_intimidation": True,
    },
    "lentiteintee": {
        "nom": "Lentiteintée", "emoji": "🕶️",
        "description": "Double les dégâts de ses attaques pas très efficaces (x0.5/x0.25).",
        "double_pas_tres_efficace": True,
    },
    "farceur": {
        "nom": "Farceur", "emoji": "🃏",
        "description": "Priorité +1 sur ses attaques de statut.",
        "priorite_attaques_statut": True,
    },
    "force_sable": {
        "nom": "Force Sable", "emoji": "🏜️",
        "description": "+30% de puissance sur les attaques Roche/Sol/Acier sous la Tempête de Sable.",
        "boost_types_meteo": ("sable", {"roche", "sol", "acier"}),
    },
    "envelocape": {
        "nom": "Envelocape", "emoji": "🧥",
        "description": "Immunisé aux dégâts de fin de tour de la météo (Tempête de Sable/Grêle).",
        "immunite_degats_meteo": True,
    },
    "hydratation": {
        "nom": "Hydratation", "emoji": "💧",
        "description": "Guérit automatiquement son statut en fin de tour sous la Pluie.",
        "soin_statut_meteo": "pluie",
    },
    "sniper": {
        "nom": "Sniper", "emoji": "🎯",
        "description": "Coups critiques encore plus dévastateurs (x2.25 au lieu de x1.5).",
        "boost_critique": 2.25,
    },
    "regard_vif": {
        "nom": "Regard Vif", "emoji": "👁️",
        "description": "Immunisé aux baisses de Précision infligées par l'adversaire. Ignore l'Esquive de sa cible quand il attaque.",
        "protege_stat_adverse": "precision", "ignore_esquive_cible": True,
    },
    "voile_sable": {
        "nom": "Voile Sable", "emoji": "🏖️",
        "description": "+25% d'Esquive sous la Tempête de Sable. Immunisé aux dégâts de Tempête de Sable.",
        "boost_esquive_meteo": ("sable", 0.25), "immunite_degats_meteo_specifique": "sable",
    },
    "voile_neige": {
        "nom": "Voile Neige", "emoji": "❄️",
        "description": "+25% d'Esquive sous la Grêle. Immunisé aux dégâts de Grêle.",
        "boost_esquive_meteo": ("grele", 0.25), "immunite_degats_meteo_specifique": "grele",
    },
    "vagues_electriques": {
        "nom": "Vagues Électriques", "emoji": "🏄",
        "description": "Double sa Vitesse tant que le Terrain Électrique est actif.",
        "boost_stat_terrain": ("electrique", "vit", 2.0),
    },
    "oeil_compose": {
        "nom": "Œil Composé", "emoji": "🪰",
        "description": "+30% de Précision sur ses propres attaques.",
        "boost_precision_attaque": 1.3,
    },
    "pieds_confus": {
        "nom": "Pieds Confus", "emoji": "🌀",
        "description": "+20% d'Esquive tant qu'il est confus.",
        "boost_esquive_confusion": 0.20,
    },
    "air_lock": {
        "nom": "Air Lock", "emoji": "🌬️",
        "description": "Annule l'effet de la météo sur les dégâts tant que ce Pokémon est sur le terrain.",
        "annule_meteo": True,
    },
    "aura_fee": {
        "nom": "Aura Fée", "emoji": "💗",
        "description": "+33% sur les attaques Fée de tous les Pokémon présents sur le terrain (y compris le porteur lui-même).",
        "boost_aura_type": "fee",
    },
    "transistor": {
        "nom": "Transistor", "emoji": "🔌",
        "description": "+50% sur ses propres attaques Électrik.",
        "boost_propre_type": "electrik",
    },
    "gueule_draconique": {
        "nom": "Gueule Draconique", "emoji": "🐉",
        "description": "+50% sur ses propres attaques Dragon.",
        "boost_propre_type": "dragon",
    },
    "justicier": {
        "nom": "Justicier", "emoji": "⚖️",
        "description": "+1 Attaque quand touché par une attaque Ténèbres.",
        "boost_si_touche_par_type": "tenebres",
    },
    "phobique": {
        "nom": "Phobique", "emoji": "😱",
        "description": "+1 Vitesse quand touché par une attaque Ténèbres, Spectre ou Insecte (v1 : pas de déclenchement par Intimidation).",
        "phobique": True,
    },
    "competiteur": {
        "nom": "Compétiteur", "emoji": "📈",
        "description": "+2 Attaque Spéciale dès qu'une de ses stats est abaissée par l'adversaire.",
        "boost_si_stat_baissee": ("atk_spe", 2),
    },
    "defiant": {
        "nom": "Défiant", "emoji": "😤",
        "description": "+2 Attaque dès qu'une de ses stats est abaissée par l'adversaire.",
        "boost_si_stat_baissee": ("atk", 2),
    },
    "ossature": {
        "nom": "Ossature", "emoji": "💢",
        "description": "+1 Attaque Spéciale la première fois que ses PV passent sous 50% suite à des dégâts.",
        "boost_ossature": True,
    },
    "hennissement_glace": {
        "nom": "Hennissement Glacé", "emoji": "🐴",
        "description": "+1 Attaque quand ce Pokémon inflige lui-même un K.O. avec une attaque offensive.",
        "boost_si_ko": ("atk", 1),
    },
    "hennissement_sepulcral": {
        "nom": "Hennissement Sépulcral", "emoji": "👻",
        "description": "+1 Attaque Spéciale quand ce Pokémon inflige lui-même un K.O. avec une attaque offensive.",
        "boost_si_ko": ("atk_spe", 1),
    },
    "coeur_ame": {
        "nom": "Cœur d'Âme", "emoji": "💗",
        "description": "+1 Attaque Spéciale à chaque K.O. survenant au combat, peu importe qui l'inflige.",
        "boost_si_ko_temoin": ("atk_spe", 1),
    },
    "magicien": {
        "nom": "Magicien", "emoji": "🎩",
        "description": "Vole l'objet tenu de la cible en la touchant avec une attaque offensive, s'il ne tient déjà rien lui-même.",
        "vole_objet": True,
    },
    "turboblaze": {
        "nom": "Turboblaze", "emoji": "🔥",
        "description": "Ignore la capacité défensive de l'adversaire (immunités, réductions de dégâts liées à une capacité).",
        "ignore_capacite_def": True,
    },
    "teravolt": {
        "nom": "Teravolt", "emoji": "⚡",
        "description": "Ignore la capacité défensive de l'adversaire (immunités, réductions de dégâts liées à une capacité).",
        "ignore_capacite_def": True,
    },
    "brise_moule": {
        "nom": "Brise Moule", "emoji": "🔨",
        "description": "Ignore la capacité défensive de l'adversaire (immunités, réductions de dégâts liées à une capacité).",
        "ignore_capacite_def": True,
    },
    "pose_spore": {
        "nom": "Pose Spore", "emoji": "🍄",
        "description": "30% de chance totale d'infliger poison/paralysie/sommeil à l'attaquant au contact.",
        "pose_spore": True,
    },
    "coloforce": {
        "nom": "Coloforce", "emoji": "🖐️",
        "description": "Vole l'objet tenu de l'attaquant au contact.",
        "vole_objet_contact": True,
    },
    "bajoues": {
        "nom": "Bajoues", "emoji": "😋",
        "description": "Soigne 33% des PV max en plus après avoir consommé une Baie.",
        "bajoues": True,
    },
    "delestage": {
        "nom": "Délestage", "emoji": "🏃",
        "description": "+2 stages de Vitesse en consommant son objet tenu (v1 : approximation, pas un x2 garanti).",
        "delestage": True,
    },
    "coeur_soin": {
        "nom": "Cœur Soin", "emoji": "💗",
        "description": "30% de chance de guérir le statut d'un allié en fin de tour (2v2 uniquement — aucun effet en 1v1).",
        "coeur_soin": True,
    },
    "danseuse": {
        "nom": "Danseuse", "emoji": "💃",
        "description": "Copie automatiquement toute attaque de danse utilisée par un autre Pokémon, sans consommer de tour ni de PP (aucun effet dans ce jeu — pas de système de catégorie \"danse\").",
    },
    "degobage": {
        "nom": "Dégobage", "emoji": "🤢",
        "description": "Inflige 1/4 des PV max au premier Pokémon qui l'attaque après l'usage de Plongée/Surf (aucun effet dans ce jeu — déclencheur trop spécifique non câblé).",
    },
    "declic_fringale": {
        "nom": "Déclic Fringale", "emoji": "🍫",
        "description": "Alterne chaque tour entre Ventre Creux et Faim de Loup, changeant le type de sa capacité signature (aucun effet dans ce jeu — cette attaque n'existe pas ici).",
    },
    "escampette": {
        "nom": "Escampette", "emoji": "🏃",
        "description": "Permet de fuir n'importe quel Pokémon sauvage (aucun effet en combat contre un autre joueur).",
    },
    "poing_fantome": {
        "nom": "Poing Fantôme", "emoji": "👊",
        "description": "Ignore Abri/Protection de l'adversaire.",
        "ignore_protection": True,
    },
    "temeraire": {
        "nom": "Téméraire", "emoji": "😶",
        "description": "Ignore les changements de stats de l'adversaire (ses boosts d'Attaque quand il défend, ses boosts de Défense quand il attaque).",
        "ignore_stage_adverse": True,
    },
    "chaine_toxique": {
        "nom": "Chaîne Toxique", "emoji": "⛓️",
        "description": "30% de chance d'empoisonner la cible sur une attaque offensive.",
        "chance_poison_sur_coup": 0.30,
    },
    "marionnettiste_toxique": {
        "nom": "Marionnettiste Toxique", "emoji": "🎭",
        "description": "Quand ce Pokémon empoisonne sa cible avec une de ses attaques, elle devient aussi confuse.",
        "confond_si_poison": True,
    },
    "aura_sombre": {
        "nom": "Aura Sombre", "emoji": "🖤",
        "description": "+33% sur les attaques Ténèbres de tous les Pokémon présents sur le terrain (y compris le porteur lui-même).",
        "boost_aura_type": "tenebres",
    },
    "agitation": {
        "nom": "Agitation", "emoji": "💪",
        "description": "+50% d'Attaque physique, mais -20% de Précision sur ses attaques physiques.",
        "mult_degats_infliges": "agitation", "malus_precision_physique": 0.80,
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
    """Tire un talent au hasard dans le pool implémenté — dernier recours absolu, si même
    talent_semi_coherent() n'a rien trouvé pour aucun des types de l'espèce."""
    return random.choice(list(CAPACITES.keys()))


# Rapprochement TEMPORAIRE par type — pour une espèce absente de POKEMON_CAPACITES (donc
# sans vraie liste d'aptitudes officielle curatée), pioche parmi les talents qui ont au
# moins un sens thématique avec SES types, plutôt qu'un talent totalement déconnecté
# (ex: Xerneas avec Absorb Volt). Ce n'est PAS de la fidélité réelle aux jeux — juste un
# pis-aller "moins absurde" en attendant la vraie curation espèce par espèce dans
# POKEMON_CAPACITES. Un type absent d'ici (aucune affinité claire trouvée) retombe sur
# talent_aleatoire(), pas d'entrée forcée juste pour en avoir une.
AFFINITE_TYPE_CAPACITES = {
    "feu": ["brasier", "corps_ardent", "cache_flamme", "ignifugation", "armure_magma"],
    "eau": ["torrent", "absorb_eau", "peau_seche", "voile_eau", "hydratation", "nage_rapide", "parapluie"],
    "plante": ["plante", "chlorophylle"],
    "electrik": ["absorb_volt", "statik"],
    "roche": ["solide_roc", "rustique", "tete_de_roc", "peau_pierre", "force_sable"],
    "sol": ["force_sable", "solide_roc", "rustique", "tete_de_roc"],
    "acier": ["solide_roc", "tete_de_roc", "rustique", "filtre", "coeur_de_fer"],
    "glace": ["corps_gele", "peau_epaisse", "alerte_neige"],
    "poison": ["poison_de_contact", "immunite", "bouclier_poison"],
    "combat": ["tenacite", "querelleur", "agitation", "technicien"],
    "insecte": ["essaim", "oeil_compose", "poison_de_contact", "ecran_poudre", "mue", "technicien"],
    "fee": ["grace_sereine", "simple", "pieds_confus"],
    "dragon": ["rustique", "agitation", "boost_chimere"],
    "tenebres": ["farceur", "querelleur", "agitation", "boost_chimere"],
    "psy": ["synchro", "carapace_mentale"],
    "spectre": ["synchro", "mue"],
    "normal": ["simple", "tempo_perso", "rustique"],
    # vol : aucune affinité claire trouvée parmi les 62 — retombe sur talent_aleatoire()
}


def talent_semi_coherent(types_pokemon: list) -> str | None:
    """Pioche parmi les talents ayant une affinité avec AU MOINS un des types donnés.
    Retourne None si aucune affinité connue pour ces types (appelant retombe alors sur
    talent_aleatoire())."""
    pool = []
    for type_ in types_pokemon or []:
        pool.extend(AFFINITE_TYPE_CAPACITES.get(type_, []))
    if not pool:
        return None
    return random.choice(list(dict.fromkeys(pool)))  # dédoublonne en préservant un pool équilibré


# Vraies capacités possibles par espèce (fidèles aux jeux officiels), limitées aux
# capacités qui ont un effet RÉELLEMENT implémenté ci-dessus — chantier progressif, pas
# encore exhaustif sur les 1025 espèces. Une espèce absente de ce dict retombe sur
# talent_aleatoire() (un talent générique au hasard) en attendant d'être curatée ici.
POKEMON_CAPACITES = {
    "Sovkipou": ["escampette"],
    "Plumeline": ["danseuse"],
    "Nigosier": ["degobage"],
    "Morpeko": ["declic_fringale"],
    "Fluvetin": ["coeur_soin"],
    "Cocotine": ["coeur_soin"],
    "Balignon": ["pose_spore"],
    "Spododo": ["pose_spore"],
    "Lampignon": ["pose_spore"],
    "Sapereau": ["coloforce"],
    "Dedenne": ["bajoues"],
    "Goupilou": ["delestage"],
    "Roublenard": ["delestage"],
    "Délestin": ["brise_moule"],
    "Monaflèmit": ["absenteisme"],
    "Flingouste": ["mega_blaster"],
    "Hexadron": ["carapace"],
    "Froussardine": ["bancosphere"],
    "Morphéo": ["forme_meteo"],
    "Rondoudou": ["charme_ensorceleur"],
    "Toudoudou": ["charme_ensorceleur"],
    "Skitty": ["charme_ensorceleur"],
    "Delcatty": ["charme_ensorceleur"],
    "Capumain": ["multi_coups"],
    "Théffroi": ["corps_maudit"],
    "Bibichut": ["miroir_magik"],
    "Chapotus": ["miroir_magik"],
    "Croquine": ["garde_feuille"],
    "Candine": ["garde_feuille"],
    "Mimantis": ["garde_feuille"],
    "Floramantis": ["garde_feuille"],
    "Briochien": ["cuisson_parfaite"],
    "Toutombe": ["moelleux"],
    "Tomberro": ["moelleux"],
    "Mordudor": ["phobique"],
    "Superdofin": ["supermutation"],
    "Concombaffe": ["expuls_organes"],
    "Nigirigon": ["absorbe_averse"],
    "Wattapik": ["electro_surge"],
    "Dolman": ["psycho_surge"],
    "Bekaglaçon": ["psycho_surge"],
    "Charibari": ["metal_lourd"],
    "Denticrisse": ["ordre_royal"],
    "Dodoala": ["carapace"],
    "Météno": ["carapace"],
    "Quartermac": ["defiant"],
    "Darumacho de Galar": ["tactiques_simiesques"],
    "Lilia": ["absorbe_averse"],
    "Vacilys": ["absorbe_averse"],
    "Tutafeh": ["momie"],
    "Tutankafer": ["momie"],
    "Tutétékri": ["esprit_vagabond"],
    "Monorpale": ["anti_air"],
    "Dimoclès": ["anti_air"],
    "Berserkatt": ["poigne_de_fer"],
    "Voltoutou": ["machoire_brute"],
    "Fulgudog": ["machoire_brute"],
    "Sucroquin": ["voile_sucre"],
    "Cupcanaille": ["voile_sucre"],
    "Crèmy": ["voile_sucre"],
    "Charmilly": ["voile_sucre"],
    "Nounourson": ["moelleux"],
    "Moumouton": ["moelleux"],
    "Moumouflon": ["moelleux"],
    "Baudrive": ["dommage_sec"],
    "Grodrive": ["dommage_sec"],
    "Grindur": ["peau_dure"],
    "Noacier": ["peau_dure"],
    "Tadmorv": ["poison_de_contact"],
    "Méditikka": ["pure_puissance"],
    "Charmina": ["pure_puissance"],
    "Charkos": ["force_brute"],
    "Ceriflor": ["chlorophylle"],
    "Miasmax": ["armure_fragile"],
    "Tritox": ["corrosion"],
    "Malamandre": ["corrosion"],
    "Chrysapile": ["oeil_compose"],
    "Excavarenne": ["pure_puissance"],
    "Couafarel": ["fourrure_renforcee"],
    "Sepiatop": ["corps_contraire"],
    "Sepiatroce": ["corps_contraire"],
    "Manglouton": ["adaptabilite"],
    "Argouste": ["adaptabilite"],
    "Crabagarre": ["bras_seca"],
    "Crabominable": ["bras_seca"],
    "Posipi": ["magnetisme"],
    "Arkéapti": ["chochotte"],
    "Momartik": ["voile_neige"],
    "Bargantua": ["adaptabilite"],
    "Darumacho": ["force_brute"],
    "Miamiasme": ["armure_fragile"],
    "Polarhume": ["voile_neige"],
    "Gringolem": ["voile_sable"],
    "Golemastoc": ["voile_sable"],
    "Qulbutoké": ["ombre_portee"],
    "Okéoké": ["ombre_portee"],
    "Mimiqui": ["facsimile"],
    "Olivini": ["chloro_semence"],
    "Olivado": ["chloro_semence"],
    "Corayon de Galar": ["corps_maudit"],
    "Parecool": ["absenteisme"],
    "Munja": ["wonder_guard"],
    "Medhyèna": ["pied_veloce"],
    "Teddiursa": ["pied_veloce"],
    "Chuchmur": ["ronfleur"],
    "Ninjask": ["cran_vital"],
    "Kranidos": ["force_brute"],
    "Kraknoix": ["bras_seca"],
    "Évoli": ["adaptabilite"],
    "Mélofée": ["garde_magique"],
    "Mélo": ["garde_magique"],
    "Mélodelfe": ["garde_magique"],
    "Porygon": ["telechargement"],
    "Kecleon": ["camouflage"],
    "Poltchageist": ["armure_fragile"],
    "Terracool": ["mycelium_might"],
    "Germéclat": ["corrosion"],
    "Virevorreur": ["turbine_eolienne"],
    "Virovent": ["turbine_eolienne"],
    "Flabébé": ["voile_floral"],
    "Floette": ["voile_floral"],
    "Zorua": ["illusion"],
    "Zorua d'Hisui": ["illusion"],
    "Zoroark d'Hisui": ["illusion"],
    "Ponyta de Galar": ["immunite"],
    "Sablaireau d'Alola": ["voile_neige"],
    "Sabelette d'Alola": ["voile_neige"],
    "Raichu d'Alola": ["vagues_electriques"],
    "Fort-Ivoire": ["vigueur_ancestrale"],
    "Hurle-Queue": ["vigueur_ancestrale"],
    "Fongus-Furie": ["vigueur_ancestrale"],
    "Flotte-Mèche": ["vigueur_ancestrale"],
    "Rampe-Ailes": ["vigueur_ancestrale"],
    "Pelage-Sablé": ["vigueur_ancestrale"],
    "Rugit-Lune": ["vigueur_ancestrale"],
    "Serpente-Eau": ["vigueur_ancestrale"],
    "Feu-Perçant": ["vigueur_ancestrale"],
    "Ire-Foudre": ["vigueur_ancestrale"],
    "Roue-de-Fer": ["turbo_circuit"],
    "Hotte-de-Fer": ["turbo_circuit"],
    "Paume-de-Fer": ["turbo_circuit"],
    "Têtes-de-Fer": ["turbo_circuit"],
    "Mite-de-Fer": ["turbo_circuit"],
    "Épine-de-Fer": ["turbo_circuit"],
    "Garde-de-Fer": ["turbo_circuit"],
    "Vert-de-Fer": ["turbo_circuit"],
    "Roc-de-Fer": ["turbo_circuit"],
    "Chef-de-Fer": ["turbo_circuit"],
    "Abo": ["intimidation", "mue", "tension"],
    "Abra": ["determination", "synchro"],
    "Absol": ["pression"],
    "Aflamanoir": ["cache_flamme", "gourmandise"],
    "Airmure": ["regard_vif", "rustique"],
    "Akwakwak": ["nage_rapide"],
    "Alakazam": ["determination", "synchro"],
    "Aligatueur": ["torrent"],
    "Altaria": ["vigilance"],
    "Ama-Ama": ["boost_chimere"],
    "Amagara": ["alerte_neige"],
    "Amassel": ["corps_sain", "rustique"],
    "Amonistar": ["carapace", "nage_rapide"],
    "Amonita": ["carapace", "nage_rapide"],
    "Amovénus": ["corps_contraire"],
    "Amphinobi": ["torrent"],
    "Ampibidou": ["statik"],
    "Anchwatt": ["levitation"],
    "Angoliath": ["farceur", "fouille"],
    "Anorith": ["nage_rapide"],
    "Apireine": ["pression", "tension"],
    "Apitrini": ["agitation"],
    "Aquali": ["absorb_eau", "hydratation"],
    "Arakdo": ["nage_rapide"],
    "Araqua": ["absorb_eau"],
    "Arbok": ["intimidation", "mue", "tension"],
    "Arboliva": ["chloro_semence"],
    "Arceus": ["multitype"],
    "Arcanin": ["cache_flamme", "intimidation"],
    "Arcanin d'Hisui": ["cache_flamme", "intimidation", "tete_de_roc"],
    "Archéduc": ["plante"],
    "Archéduc d'Hisui": ["plante", "querelleur"],
    "Archéodong": ["levitation"],
    "Archéomire": ["levitation"],
    "Arcko": ["plante"],
    "Armaldo": ["nage_rapide"],
    "Armulys": ["mue"],
    "Arrozard": ["sniper", "torrent"],
    "Artikodin": ["pression"],
    "Artikodin de Galar": ["competiteur"],
    "Aspicot": ["ecran_poudre"],
    "Astronelle": ["essaim", "fouille"],
    "Avaltout": ["gourmandise"],
    "Axoloto": ["absorb_eau"],
    "Axoloto de Paldea": ["absorb_eau", "poison_de_contact"],
    "Azumarill": ["herbivore", "peau_epaisse"],
    "Azurill": ["herbivore", "peau_epaisse"],
    "Aéromite": ["ecran_poudre", "lentiteintee"],
    "Aéroptéryx": ["tete_de_roc"],
    "Babimanta": ["absorb_eau", "nage_rapide", "voile_eau"],
    "Bacabouh": ["voile_sable"],
    "Badabouin": ["plante"],
    "Baggaïd": ["intimidation", "mue"],
    "Baggiguane": ["intimidation", "mue"],
    "Balbalèze": ["peau_epaisse"],
    "Balbuto": ["levitation"],
    "Bamboiselle": ["boost_chimere"],
    "Banshitrouye": ["fouille", "insomnia"],
    "Barbicha": ["hydratation"],
    "Barloche": ["hydratation"],
    "Baojian": ["fleau_epee"],
    "Barpau": ["nage_rapide"],
    "Bastiodon": ["rustique"],
    "Batracné": ["absorb_eau", "hydratation", "nage_rapide"],
    "Bazoucan": ["regard_vif"],
    "Bekipan": ["averse", "regard_vif"],
    "Beldeneige": ["ecran_poudre"],
    "Blancoton": ["regenerescence"],
    "Bleuseille": ["coeur_de_coq", "regard_vif", "tension"],
    "Blindalys": ["mue"],
    "Blindépique": ["plante"],
    "Blizzaroi": ["alerte_neige"],
    "Blizzi": ["alerte_neige"],
    "Blizzeval": ["hennissement_glace"],
    "Boguérisse": ["plante"],
    "Bombydou": ["ecran_poudre"],
    "Boréas": ["farceur"],
    "Boskara": ["carapace", "plante"],
    "Bouldeneu": ["chlorophylle", "regenerescence"],
    "Boumata": ["carapace"],
    "Bourrinos": ["determination", "tempo_perso"],
    "Boustiflor": ["chlorophylle", "gourmandise"],
    "Braisillon": ["corps_ardent"],
    "Branette": ["fouille", "insomnia"],
    "Braségali": ["brasier"],
    "Brindibou": ["plante"],
    "Brocélôme": ["fouille", "vigilance"],
    "Brouhabam": ["querelleur"],
    "Brutalibré": ["limber"],
    "Brutapode": ["essaim", "poison_de_contact"],
    "Bruyverne": ["fouille"],
    "Bulbizarre": ["chlorophylle", "plante"],
    "Bébécaille": ["envelocape"],
    "Bérasca": ["synchro"],
    "Bétochef": ["tenacite"],
    "Cabriolaine": ["herbivore"],
    "Cacnea": ["absorb_eau", "voile_sable"],
    "Cacturne": ["absorb_eau", "voile_sable"],
    "Cadoizo": ["agitation", "esprit_vital", "insomnia"],
    "Camérupt": ["armure_magma", "solide_roc"],
    "Canarbello": ["torrent"],
    "Canarticho": ["determination", "regard_vif"],
    "Canarticho de Galar": ["querelleur"],
    "Cancrelove": ["boost_chimere"],
    "Caninos": ["cache_flamme", "intimidation"],
    "Caninos d'Hisui": ["cache_flamme", "intimidation", "tete_de_roc"],
    "Capidextre": ["technicien"],
    "Carabaffe": ["torrent"],
    "Carabing": ["essaim", "mue"],
    "Carapagos": ["nage_rapide", "rustique", "solide_roc"],
    "Carapuce": ["torrent"],
    "Caratroc": ["gourmandise", "rustique"],
    "Carchacrok": ["peau_dure", "voile_sable"],
    "Carmache": ["peau_dure", "voile_sable"],
    "Carmadura": ["cache_flamme"],
    "Carvanha": ["peau_dure"],
    "Castorno": ["simple"],
    "Celebi": ["vigilance"],
    "Cerbyllin": ["fouille", "herbivore", "intimidation"],
    "Cerfrousse": ["fouille", "herbivore", "intimidation"],
    "Ceribou": ["chlorophylle"],
    "Chacripan": ["farceur", "limber"],
    "Chaffreux": ["peau_epaisse", "tempo_perso"],
    "Chaglam": ["limber", "regard_vif", "tempo_perso"],
    "Chamallot": ["simple", "tempo_perso"],
    "Chapignon": ["technicien"],
    "Charbambin": ["cache_flamme", "corps_ardent"],
    "Charbi": ["cache_flamme"],
    "Charmillon": ["essaim"],
    "Charpenti": ["tenacite"],
    "Chartor": ["carapace", "secheresse"],
    "Chelours": ["tension"],
    "Chenipan": ["ecran_poudre"],
    "Chenipotte": ["ecran_poudre"],
    "Cheniselle": ["envelocape"],
    "Cheniti": ["envelocape", "mue"],
    "Chevroum": ["herbivore"],
    "Chimpenfeu": ["brasier"],
    "Chinchidou": ["technicien"],
    "Chlorobule": ["chlorophylle", "tempo_perso"],
    "Chongjian": ["fleau_tablettes"],
    "Chochodile": ["brasier"],
    "Chovsourir": ["simple"],
    "Chrysacier": ["mue"],
    "Chétiflor": ["chlorophylle", "gourmandise"],
    "Cizayox": ["essaim", "technicien"],
    "Clamiral": ["carapace", "torrent"],
    "Clamiral d'Hisui": ["torrent"],
    "Clic": ["corps_sain"],
    "Cliticlic": ["corps_sain"],
    "Cléopsytra": ["fouille"],
    "Coatox": ["peau_seche"],
    "Cobaltium": ["justicier"],
    "Cochignon": ["peau_epaisse"],
    "Coconfort": ["mue"],
    "Coiffeton": ["torrent"],
    "Colhomard": ["carapace"],
    "Colimucus": ["herbivore", "hydratation"],
    "Colombeau": ["coeur_de_coq"],
    "Colossinge": ["esprit_vital"],
    "Coléodôme": ["essaim", "oeil_compose"],
    "Compagnol": ["tempo_perso"],
    "Coquiperl": ["carapace"],
    "Corayôme": ["armure_fragile"],
    "Corayon": ["agitation", "regenerescence", "vigilance"],
    "Corboss": ["insomnia"],
    "Cornèbre": ["farceur", "insomnia"],
    "Corvaillus": ["pression", "tension"],
    "Cosmog": ["temeraire"],
    "Cosmovum": ["rustique"],
    "Cotovol": ["chlorophylle"],
    "Couaneton": ["coeur_de_coq", "hydratation", "regard_vif"],
    "Coudlangue": ["tempo_perso"],
    "Coupenotte": ["tension"],
    "Courrousinge": ["determination", "esprit_vital"],
    "Couverdure": ["chlorophylle", "envelocape"],
    "Coxy": ["essaim"],
    "Coxyclaque": ["essaim"],
    "Crabaraque": ["carapace", "rustique"],
    "Crabicoque": ["carapace", "rustique"],
    "Cradopaud": ["peau_seche"],
    "Craparoi": ["carapace", "regenerescence"],
    "Crapustule": ["absorb_eau", "nage_rapide"],
    "Cresselia": ["levitation"],
    "Crikzik": ["mue"],
    "Crocogril": ["brasier"],
    "Crocorible": ["intimidation"],
    "Crocrodil": ["torrent"],
    "Croâporal": ["torrent"],
    "Crustabri": ["carapace", "envelocape"],
    "Cryodo": ["corps_gele"],
    "Cryptéro": ["lentiteintee"],
    "Créfadet": ["levitation"],
    "Créfollet": ["levitation"],
    "Créhelf": ["levitation"],
    "Câblifère": ["boost_chimere"],
    "Dardargnan": ["essaim", "sniper"],
    "Darkrai": ["cauchemar"],
    "Darumarond": ["agitation", "determination"],
    "Darumarond de Galar": ["agitation", "determination"],
    "Debugant": ["esprit_vital", "tenacite"],
    "Deoxys": ["pression"],
    "Desséliande": ["fouille", "vigilance"],
    "Deusolourdo": ["grace_sereine"],
    "Dialga": ["pression"],
    "Diamat": ["agitation"],
    "Diancie": ["corps_sain"],
    "Dimoret": ["pression"],
    "Dinglu": ["fleau_urne"],
    "Dinoclier": ["rustique"],
    "Dispareptil": ["corps_sain"],
    "Dodrio": ["pieds_confus"],
    "Doduo": ["pieds_confus"],
    "Dofin": ["voile_eau"],
    "Dogrino": ["intimidation"],
    "Donphan": ["rustique", "voile_sable"],
    "Doudouvet": ["chlorophylle", "farceur"],
    "Draby": ["tete_de_roc"],
    "Dracaufeu": ["brasier"],
    "Drackhaus": ["envelocape", "tete_de_roc"],
    "Draco": ["mue"],
    "Dracolosse": ["determination"],
    "Dragmara": ["alerte_neige"],
    "Drakkarmin": ["peau_dure"],
    "Drascore": ["regard_vif", "sniper"],
    "Dratatin": ["gourmandise", "peau_epaisse"],
    "Drattak": ["intimidation"],
    "Draïeul": ["herbivore"],
    "Dunaconda": ["mue", "voile_sable"],
    "Dunaja": ["mue", "voile_sable"],
    "Duralugon": ["metal_leger"],
    "Dynavolt": ["statik"],
    "Déflaisan": ["coeur_de_coq"],
    "Démanta": ["absorb_eau", "nage_rapide", "voile_eau"],
    "Démolosse": ["cache_flamme", "tension"],
    "Démétéros": ["force_sable"],
    "Ectoplasma": ["corps_maudit"],
    "Efflèche": ["plante"],
    "Embrochet": ["nage_rapide"],
    "Embrylex": ["tenacite", "voile_sable"],
    "Emolga": ["statik"],
    "Empiflor": ["chlorophylle", "gourmandise"],
    "Engloutyran": ["boost_chimere"],
    "Entei": ["determination", "pression"],
    "Escargaume": ["carapace", "envelocape", "hydratation"],
    "Escroco": ["intimidation"],
    "Exagide": ["stance_change"],
    "Excelangue": ["tempo_perso"],
    "Famignol": ["technicien"],
    "Fantominus": ["levitation"],
    "Fantyrm": ["corps_sain"],
    "Farfaduvet": ["chlorophylle", "farceur"],
    "Farfuret": ["determination", "regard_vif"],
    "Farfuret d'Hisui": ["determination", "regard_vif"],
    "Farfurex": ["pression"],
    "Farigiraf": ["herbivore"],
    "Favianos": ["chaine_toxique"],
    "Félicanis": ["chaine_toxique"],
    "Ferdeter": ["voile_sable"],
    "Fermite": ["agitation", "essaim"],
    "Feuforêve": ["levitation"],
    "Feuillajou": ["gourmandise", "plante"],
    "Feuiloutan": ["gourmandise", "plante"],
    "Feunard": ["cache_flamme", "secheresse"],
    "Feunard d'Alola": ["alerte_neige"],
    "Feunnec": ["brasier"],
    "Feurisson": ["brasier", "cache_flamme"],
    "Filentrappe": ["insomnia"],
    "Flagadoss": ["regenerescence", "tempo_perso"],
    "Flagadoss de Galar": ["regenerescence", "tempo_perso"],
    "Flamajou": ["brasier", "gourmandise"],
    "Flambino": ["brasier"],
    "Flambusard": ["corps_ardent"],
    "Flamenroule": ["pieds_confus", "querelleur"],
    "Flamiaou": ["brasier", "intimidation"],
    "Flamoutan": ["brasier", "gourmandise"],
    "Flobio": ["torrent"],
    "Floravol": ["chlorophylle"],
    "Floréclat": ["corrosion"],
    "Florges": ["voile_floral"],
    "Florizarre": ["chlorophylle", "plante"],
    "Flotajou": ["gourmandise", "torrent"],
    "Flotillon": ["fouille"],
    "Flotoutan": ["gourmandise", "torrent"],
    "Flâmigator": ["brasier"],
    "Foretress": ["envelocape", "rustique"],
    "Forgelina": ["tempo_perso"],
    "Forgella": ["tempo_perso"],
    "Forgerette": ["tempo_perso"],
    "Fortusimia": ["chaine_toxique"],
    "Fouinar": ["fouille", "regard_vif"],
    "Fouinette": ["fouille", "regard_vif"],
    "Fourbelin": ["farceur", "fouille"],
    "Fragilady": ["chlorophylle", "tempo_perso"],
    "Fragilady d'Hisui": ["agitation", "chlorophylle"],
    "Fragroin": ["gourmandise", "peau_epaisse"],
    "Frigodo": ["corps_gele"],
    "Frison": ["herbivore"],
    "Frissonille": ["ecran_poudre"],
    "Fulgulairo": ["absorb_volt"],
    "Fulguris": ["farceur"],
    "Funécire": ["cache_flamme", "corps_ardent"],
    "Furaiglon": ["agitation", "regard_vif"],
    "Félinferno": ["brasier", "intimidation"],
    "Férosinge": ["esprit_vital"],
    "Galegon": ["rustique", "tete_de_roc"],
    "Galekid": ["rustique", "tete_de_roc"],
    "Galeking": ["rustique", "tete_de_roc"],
    "Galifeu": ["brasier"],
    "Gallame": ["determination"],
    "Galopa": ["cache_flamme", "corps_ardent"],
    "Galopa de Galar": ["immunite"],
    "Galvagla": ["absorb_volt", "statik"],
    "Galvagon": ["absorb_volt", "agitation"],
    "Galvaran": ["peau_seche", "voile_sable"],
    "Gamblast": ["mega_blaster"],
    "Gambex": ["essaim", "lentiteintee"],
    "Gardevoir": ["synchro"],
    "Gaulet": ["regenerescence"],
    "Germignon": ["plante"],
    "Gigalithe": ["force_sable", "rustique", "sable_volant"],
    "Gigansel": ["corps_sain", "rustique"],
    "Genesect": ["telechargement"],
    "Girafarig": ["determination", "herbivore"],
    "Giratina": ["pression"],
    "Givrali": ["corps_gele"],
    "Glaivodo": ["corps_gele"],
    "Gloupti": ["gourmandise"],
    "Gobou": ["torrent"],
    "Goinfrex": ["gourmandise", "peau_epaisse"],
    "Golgopathe": ["sniper"],
    "Gorythmic": ["plante"],
    "Goupelin": ["brasier"],
    "Goupix": ["cache_flamme", "secheresse"],
    "Goupix d'Alola": ["alerte_neige"],
    "Gourmelet": ["gourmandise", "peau_epaisse"],
    "Gouroutan": ["determination"],
    "Goélise": ["hydratation", "regard_vif"],
    "Grahyèna": ["intimidation"],
    "Grainipiot": ["chlorophylle"],
    "Granbull": ["intimidation"],
    "Granivol": ["chlorophylle"],
    "Gravalanch": ["rustique", "tete_de_roc", "voile_sable"],
    "Gravalanch d'Alola": ["rustique"],
    "Grelaçon": ["corps_gele", "rustique", "tempo_perso"],
    "Grenousse": ["torrent"],
    "Gribouraigne": ["farceur"],
    "Griknot": ["peau_dure", "voile_sable"],
    "Grillepattes": ["cache_flamme", "corps_ardent"],
    "Grimalin": ["farceur", "fouille"],
    "Grodoudou": ["fouille"],
    "Grolem": ["rustique", "tete_de_roc", "voile_sable"],
    "Grolem d'Alola": ["rustique"],
    "Gromago": ["or_pur"],
    "Grondogue": ["intimidation"],
    "Groret": ["gourmandise", "peau_epaisse", "tempo_perso"],
    "Grotadmorv": ["poison_de_contact"],
    "Grotadmorv d'Alola": ["gourmandise"],
    "Grotichon": ["brasier", "peau_epaisse"],
    "Groudon": ["secheresse"],
    "Gruikui": ["brasier", "peau_epaisse"],
    "Gueriaigle": ["regard_vif"],
    "Gueriaigle d'Hisui": ["lentiteintee", "regard_vif"],
    "Guérilande": ["vigilance"],
    "Géolithe": ["force_sable", "rustique"],
    "Hachécateur": ["essaim"],
    "Hariyama": ["peau_epaisse", "tenacite"],
    "Hastacuda": ["nage_rapide"],
    "Haydaim": ["chlorophylle", "grace_sereine", "herbivore"],
    "Heatran": ["cache_flamme", "corps_ardent"],
    "Herbizarre": ["chlorophylle", "plante"],
    "Hexagel": ["levitation"],
    "Hippodocus": ["force_sable", "sable_volant"],
    "Hippopotas": ["force_sable", "sable_volant"],
    "Ho-Oh": ["pression", "regenerescence"],
    "Hoopa": ["magicien"],
    "Hoothoot": ["insomnia", "lentiteintee", "regard_vif"],
    "Hydragla": ["absorb_eau", "corps_gele"],
    "Hydragon": ["absorb_eau"],
    "Hypnomade": ["determination", "insomnia"],
    "Hypocéan": ["poison_de_contact", "sniper"],
    "Hyporoi": ["nage_rapide", "sniper"],
    "Hypotrempe": ["nage_rapide", "sniper"],
    "Héliatronc": ["chlorophylle"],
    "Hélionceau": ["tension"],
    "Hélédelle": ["querelleur", "tenacite"],
    "Héricendre": ["brasier", "cache_flamme"],
    "Iguolta": ["peau_seche", "voile_sable"],
    "Incisache": ["tension"],
    "Insolourdo": ["grace_sereine"],
    "Insécateur": ["essaim", "technicien"],
    "Ixon": ["tenacite"],
    "Jirachi": ["grace_sereine"],
    "Joliflor": ["chlorophylle"],
    "Judokrak": ["determination", "tenacite"],
    "Jungko": ["plante"],
    "Kabuto": ["nage_rapide"],
    "Kabutops": ["nage_rapide"],
    "Kadabra": ["determination", "synchro"],
    "Kaiminus": ["torrent"],
    "Kaimorse": ["corps_gele", "peau_epaisse"],
    "Kangourex": ["determination", "querelleur"],
    "Kaorine": ["levitation"],
    "Kapoera": ["intimidation", "technicien"],
    "Karaclée": ["determination", "rustique"],
    "Katagami": ["boost_chimere"],
    "Keunotor": ["simple"],
    "Khélocrok": ["carapace", "nage_rapide"],
    "Keldeo": ["justicier"],
    "Kicklee": ["limber"],
    "Kirlia": ["synchro"],
    "Kokiyas": ["carapace", "envelocape"],
    "Koraidon": ["pulsion_orichalque"],
    "Korillon": ["levitation"],
    "Krabboss": ["carapace"],
    "Krabby": ["carapace"],
    "Krakos": ["limber", "technicien"],
    "Kravarech": ["poison_de_contact"],
    "Kungfouine": ["determination", "regenerescence"],
    "Kyogre": ["averse"],
    "Kyurem": ["pression"],
    "Laggron": ["torrent"],
    "Lainergie": ["statik"],
    "Lakmécygne": ["coeur_de_coq", "hydratation", "regard_vif"],
    "Lamantine": ["corps_gele", "hydratation", "peau_epaisse"],
    "Lampéroie": ["levitation"],
    "Lanssorien": ["corps_sain"],
    "Lanturn": ["absorb_eau", "absorb_volt"],
    "Lançargot": ["carapace", "envelocape", "essaim"],
    "Laporeille": ["limber"],
    "Lapyro": ["brasier"],
    "Larméléon": ["sniper", "torrent"],
    "Larvadar": ["essaim", "oeil_compose"],
    "Larveyette": ["chlorophylle", "envelocape", "essaim"],
    "Larvibule": ["essaim"],
    "Latias": ["levitation"],
    "Latios": ["levitation"],
    "Lestombaile": ["coeur_de_coq", "regard_vif"],
    "Leuphorie": ["grace_sereine", "vigilance"],
    "Leveinard": ["grace_sereine", "vigilance"],
    "Lewsor": ["synchro"],
    "Lianaja": ["plante"],
    "Libégon": ["levitation"],
    "Lilliterelle": ["essaim", "lentiteintee"],
    "Limagma": ["armure_magma", "corps_ardent"],
    "Limaspeed": ["hydratation"],
    "Limonde": ["limber", "statik", "voile_sable"],
    "Linéon": ["gourmandise"],
    "Linéon de Galar": ["gourmandise"],
    "Lippouti": ["hydratation"],
    "Lippoutou": ["peau_seche"],
    "Lixy": ["intimidation", "tenacite"],
    "Lockpin": ["limber"],
    "Lokhlass": ["absorb_eau", "carapace", "hydratation"],
    "Lombre": ["nage_rapide", "tempo_perso"],
    "Lougaroc": ["regard_vif"],
    "Loupio": ["absorb_eau", "absorb_volt"],
    "Lovdisc": ["hydratation", "nage_rapide"],
    "Lucanon": ["levitation"],
    "Lucario": ["determination"],
    "Ludicolo": ["nage_rapide", "tempo_perso"],
    "Lugia": ["pression"],
    "Lunala": ["bouclier_ombre"],
    "Lugulabre": ["cache_flamme", "corps_ardent"],
    "Luminéon": ["nage_rapide", "voile_eau"],
    "Lumivole": ["farceur", "lentiteintee"],
    "Luxio": ["intimidation", "tenacite"],
    "Luxray": ["intimidation", "tenacite"],
    "Léboulérou": ["mue", "oeil_compose"],
    "Léopardus": ["farceur", "limber"],
    "Lépidonille": ["ecran_poudre", "oeil_compose"],
    "Léviator": ["intimidation"],
    "Lézargus": ["sniper", "torrent"],
    "M. Glaquette": ["corps_gele", "pieds_confus"],
    "M. Mime": ["filtre", "technicien"],
    "M. Mime de Galar": ["corps_gele", "esprit_vital"],
    "Machoc": ["tenacite"],
    "Machopeur": ["tenacite"],
    "Mackogneur": ["tenacite"],
    "Macronium": ["plante"],
    "Maganon": ["corps_ardent", "esprit_vital"],
    "Magby": ["corps_ardent", "esprit_vital"],
    "Magearna": ["coeur_ame"],
    "Magicarpe": ["nage_rapide"],
    "Magirêve": ["levitation"],
    "Magmar": ["corps_ardent", "esprit_vital"],
    "Magnéti": ["rustique"],
    "Magnéton": ["rustique"],
    "Magnézone": ["rustique"],
    "Majaspic": ["plante"],
    "Makuhita": ["peau_epaisse", "tenacite"],
    "Malosse": ["cache_flamme", "tension"],
    "Malvalame": ["cache_flamme"],
    "Mamanbo": ["hydratation", "regenerescence"],
    "Mammochon": ["peau_epaisse"],
    "Manaphy": ["hydratation"],
    "Mandrillon": ["boost_chimere"],
    "Mangriff": ["immunite"],
    "Manternel": ["chlorophylle", "envelocape", "essaim"],
    "Manzaï": ["rustique", "tete_de_roc"],
    "Maracachi": ["absorb_eau", "chlorophylle"],
    "Maraiste": ["absorb_eau"],
    "Marcacrin": ["peau_epaisse"],
    "Marill": ["herbivore", "peau_epaisse"],
    "Marisson": ["plante"],
    "Marshadow": ["technicien"],
    "Mascaïman": ["intimidation"],
    "Maskadra": ["intimidation", "tension"],
    "Massko": ["plante"],
    "Mastouffe": ["intimidation", "querelleur"],
    "Mateloutre": ["carapace", "torrent"],
    "Matoufeu": ["brasier", "intimidation"],
    "Matourgeon": ["plante"],
    "Melmetal": ["poing_de_fer"],
    "Meloetta": ["grace_sereine"],
    "Meltan": ["poing_de_fer"],
    "Mentali": ["synchro"],
    "Mesmérella": ["fouille"],
    "Mew": ["synchro"],
    "Mewtwo": ["pression", "tension"],
    "Miaouss": ["technicien", "tension"],
    "Miaouss d'Alola": ["technicien"],
    "Miaouss de Galar": ["tension"],
    "Miascarade": ["plante"],
    "Migalos": ["essaim", "insomnia", "sniper"],
    "Milobellus": ["ecailles_magiques"],
    "Mime Jr.": ["filtre", "technicien"],
    "Mimigal": ["essaim", "insomnia", "sniper"],
    "Mimitoss": ["lentiteintee", "oeil_compose"],
    "Minidraco": ["mue"],
    "Minisange": ["coeur_de_coq", "regard_vif", "tension"],
    "Minotaupe": ["force_sable"],
    "Miradar": ["regard_vif"],
    "Miraidon": ["moteur_hadron"],
    "Mistigrix": ["farceur", "regard_vif"],
    "Monthracite": ["cache_flamme", "corps_ardent"],
    "Motisma": ["levitation"],
    "Motorizard": ["mue", "regenerescence"],
    "Moufflair": ["regard_vif"],
    "Moufouette": ["regard_vif"],
    "Mouscoto": ["boost_chimere"],
    "Moustillon": ["carapace", "torrent"],
    "Moyade": ["absorb_eau"],
    "Muciole": ["essaim", "farceur"],
    "Mucuscule": ["herbivore", "hydratation"],
    "Mucuscule d'Hisui": ["carapace", "herbivore"],
    "Munna": ["synchro"],
    "Muplodocus": ["herbivore", "hydratation"],
    "Muplodocus d'Hisui": ["carapace", "herbivore"],
    "Mushana": ["synchro"],
    "Mustébouée": ["nage_rapide", "voile_eau"],
    "Mustéflott": ["nage_rapide", "voile_eau"],
    "Mygavolt": ["essaim", "oeil_compose", "tension"],
    "Mysdibule": ["intimidation"],
    "Mystherbe": ["chlorophylle"],
    "Méganium": ["plante"],
    "Mégapagos": ["nage_rapide", "rustique", "solide_roc"],
    "Méios": ["envelocape", "regenerescence"],
    "Mélancolux": ["cache_flamme", "corps_ardent"],
    "Mélokrik": ["essaim", "technicien"],
    "Métalosse": ["corps_sain"],
    "Métamorph": ["limber"],
    "Métang": ["corps_sain"],
    "Nanméouïe": ["regenerescence"],
    "Natu": ["synchro"],
    "Neitram": ["synchro"],
    "Necrozma": ["prisme_armure"],
    "Nidoking": ["poison_de_contact"],
    "Nidoqueen": ["poison_de_contact"],
    "Nidoran♀": ["agitation", "poison_de_contact"],
    "Nidoran♂": ["agitation", "poison_de_contact"],
    "Nidorina": ["agitation", "poison_de_contact"],
    "Nidorino": ["agitation", "poison_de_contact"],
    "Ningale": ["oeil_compose"],
    "Nirondelle": ["querelleur", "tenacite"],
    "Noadkoko": ["chlorophylle"],
    "Noadkoko d'Alola": ["fouille"],
    "Noarfang": ["insomnia", "lentiteintee", "regard_vif"],
    "Noctali": ["determination", "synchro"],
    "Noctunoir": ["fouille", "pression"],
    "Nodulithe": ["force_sable", "rustique"],
    "Noeunoeuf": ["chlorophylle"],
    "Nosferalto": ["determination"],
    "Nosferapti": ["determination"],
    "Nostenfer": ["determination"],
    "Nymphali": ["pixelisation"],
    "Nucléos": ["envelocape", "regenerescence"],
    "Négapi": ["absorb_volt"],
    "Némélios": ["tension"],
    "Nénupiot": ["nage_rapide", "tempo_perso"],
    "Obalie": ["corps_gele", "peau_epaisse"],
    "Octillery": ["sniper"],
    "Ogerpon": ["defiant"],
    "Ohmassacre": ["levitation"],
    "Oniglali": ["corps_gele", "determination"],
    "Onix": ["rustique", "tete_de_roc"],
    "Opermine": ["sniper"],
    "Oratoria": ["torrent"],
    "Ortide": ["chlorophylle"],
    "Ossatueur": ["tete_de_roc"],
    "Ossatueur d'Alola": ["tete_de_roc"],
    "Osselait": ["tete_de_roc"],
    "Otaquin": ["torrent"],
    "Otaria": ["corps_gele", "hydratation", "peau_epaisse"],
    "Otarlette": ["torrent"],
    "Ouistempo": ["plante"],
    "Ouisticram": ["brasier"],
    "Ouvrifier": ["tenacite"],
    "Oyacata": ["voile_eau"],
    "Pachirisu": ["absorb_volt"],
    "Pachyradjah": ["force_brute"],
    "Palarticho": ["querelleur"],
    "Palkia": ["pression"],
    "Palmaval": ["torrent"],
    "Pandarbare": ["querelleur"],
    "Pandespiègle": ["querelleur"],
    "Papilord": ["essaim", "lentiteintee"],
    "Papilusion": ["lentiteintee", "oeil_compose"],
    "Papinox": ["ecran_poudre", "oeil_compose"],
    "Paragruel": ["nage_rapide"],
    "Paras": ["peau_seche"],
    "Parasect": ["peau_seche"],
    "Pashmilla": ["technicien"],
    "Passerouge": ["coeur_de_coq"],
    "Pêchaminus": ["marionnettiste_toxique"],
    "Persian": ["limber", "technicien", "tension"],
    "Persian d'Alola": ["technicien"],
    "Phanpy": ["voile_sable"],
    "Pharamp": ["statik"],
    "Phione": ["hydratation"],
    "Phogleur": ["corps_gele", "peau_epaisse"],
    "Phyllali": ["chlorophylle"],
    "Piafabec": ["regard_vif", "sniper"],
    "Picassaut": ["regard_vif"],
    "Pichu": ["statik"],
    "Piclairon": ["regard_vif"],
    "Pierroteknik": ["boost_chimere"],
    "Pifeuil": ["chlorophylle"],
    "Pijako": ["coeur_de_coq", "pieds_confus", "regard_vif"],
    "Pikachu": ["statik"],
    "Pimito": ["chlorophylle", "insomnia"],
    "Pingoléon": ["torrent"],
    "Pitrouille": ["fouille", "insomnia"],
    "Piétacé": ["peau_epaisse"],
    "Pohm": ["statik", "vigilance"],
    "Pohmarmotte": ["absorb_volt", "vigilance"],
    "Pohmotte": ["absorb_volt", "vigilance"],
    "Poichigeon": ["coeur_de_coq"],
    "Poissirène": ["nage_rapide", "voile_eau"],
    "Poissoroy": ["nage_rapide", "voile_eau"],
    "Polagriffe": ["nage_rapide"],
    "Polichombr": ["fouille", "insomnia"],
    "Polthégeist": ["armure_fragile"],
    "Pomdepik": ["envelocape", "rustique"],
    "Pomdorochi": ["regenerescence"],
    "Pomdramour": ["gourmandise"],
    "Pomdrapi": ["agitation", "gourmandise"],
    "Ponchien": ["intimidation", "querelleur"],
    "Ponchiot": ["esprit_vital"],
    "Pondralugon": ["rustique"],
    "Ponyta": ["cache_flamme", "corps_ardent"],
    "Porygon2": ["telechargement"],
    "Porygon-Z": ["telechargement"],
    "Poulpaf": ["limber", "technicien"],
    "Poussacha": ["plante"],
    "Poussifeu": ["brasier"],
    "Prinplouf": ["torrent"],
    "Prismillon": ["ecran_poudre", "oeil_compose"],
    "Prédastérie": ["limber", "regenerescence"],
    "Psykokwak": ["nage_rapide"],
    "Psystigri": ["regard_vif", "tempo_perso"],
    "Ptiravi": ["grace_sereine", "vigilance"],
    "Ptitard": ["absorb_eau", "nage_rapide"],
    "Ptyranidur": ["rustique"],
    "Ptéra": ["pression", "tension", "tete_de_roc"],
    "Pyrax": ["corps_ardent", "essaim"],
    "Pyrobut": ["brasier"],
    "Pyroli": ["cache_flamme", "tenacite"],
    "Pyronille": ["corps_ardent", "essaim"],
    "Pâtachiot": ["tempo_perso"],
    "Pérégrain": ["mue"],
    "Queulorior": ["technicien", "tempo_perso"],
    "Qwilfish": ["intimidation", "nage_rapide", "poison_de_contact"],
    "Qwilfish d'Hisui": ["intimidation", "nage_rapide", "poison_de_contact"],
    "Qwilpik": ["intimidation", "nage_rapide", "poison_de_contact"],
    "Racaillou": ["rustique", "tete_de_roc", "voile_sable"],
    "Racaillou d'Alola": ["rustique"],
    "Rafflesia": ["chlorophylle"],
    "Raichu": ["statik"],
    "Raikou": ["determination", "pression"],
    "Ramboum": ["querelleur"],
    "Ramoloss": ["regenerescence", "tempo_perso"],
    "Ramoloss de Galar": ["gourmandise", "regenerescence", "tempo_perso"],
    "Rapasdepic": ["regard_vif", "sniper"],
    "Rapion": ["regard_vif", "sniper"],
    "Ratentif": ["regard_vif"],
    "Rattata": ["agitation", "tenacite"],
    "Rayquaza": ["air_lock"],
    "Rattata d'Alola": ["agitation", "gourmandise", "peau_epaisse"],
    "Rattatac": ["agitation", "tenacite"],
    "Rattatac d'Alola": ["agitation", "gourmandise", "peau_epaisse"],
    "Regice": ["corps_gele", "corps_sain"],
    "Regirock": ["corps_sain", "rustique"],
    "Registeel": ["corps_sain"],
    "Regigigas": ["lenteur"],
    "Regieleki": ["transistor"],
    "Regidrago": ["gueule_draconique"],
    "Relicanth": ["nage_rapide", "rustique", "tete_de_roc"],
    "Reshiram": ["turboblaze"],
    "Reptincel": ["brasier"],
    "Rexillius": ["tete_de_roc"],
    "Rhinastoc": ["solide_roc"],
    "Rhinocorne": ["tete_de_roc"],
    "Rhinoféros": ["tete_de_roc"],
    "Rhinolove": ["simple"],
    "Riolu": ["determination", "farceur"],
    "Rocabot": ["esprit_vital", "regard_vif"],
    "Roigada": ["regenerescence", "tempo_perso"],
    "Roigada de Galar": ["regenerescence", "tempo_perso"],
    "Roitiflam": ["brasier"],
    "Ronflex": ["gourmandise", "immunite", "peau_epaisse"],
    "Rongourmand": ["gourmandise"],
    "Rongrigou": ["gourmandise"],
    "Rosabyss": ["hydratation", "nage_rapide"],
    "Roserade": ["poison_de_contact", "technicien", "vigilance"],
    "Rosélia": ["poison_de_contact", "vigilance"],
    "Rototaupe": ["force_sable"],
    "Roucarnage": ["coeur_de_coq", "pieds_confus", "regard_vif"],
    "Roucool": ["coeur_de_coq", "pieds_confus", "regard_vif"],
    "Roucoups": ["coeur_de_coq", "pieds_confus", "regard_vif"],
    "Roussil": ["brasier"],
    "Rozbouton": ["poison_de_contact", "vigilance"],
    "Rubombelle": ["ecran_poudre"],
    "Rémoraid": ["agitation", "sniper"],
    "Sabelette": ["voile_sable"],
    "Sablaireau": ["voile_sable"],
    "Salamèche": ["brasier"],
    "Salarsen": ["technicien"],
    "Sancoki": ["force_sable"],
    "Sarmuraï": ["porte_secours"],
    "Saquedeneu": ["chlorophylle", "regenerescence"],
    "Scalpereur": ["pression"],
    "Scalpion": ["determination", "pression"],
    "Scalproie": ["determination", "pression"],
    "Scarabrute": ["bras_seca"],
    "Scarhino": ["essaim", "tenacite"],
    "Scobolide": ["essaim", "poison_de_contact"],
    "Scolocendre": ["cache_flamme", "corps_ardent"],
    "Scorplane": ["immunite", "voile_sable"],
    "Scorvol": ["voile_sable"],
    "Scovilain": ["chlorophylle", "insomnia"],
    "Scrutella": ["fouille"],
    "Selutin": ["corps_sain", "rustique"],
    "Serpang": ["nage_rapide", "voile_eau"],
    "Shaofouine": ["determination", "regenerescence"],
    "Sharpedo": ["peau_dure"],
    "Shaymin": ["vigilance"],
    "Shifours": ["poing_fantome"],
    "Sidérella": ["fouille"],
    "Silvallié": ["systeme_alpha"],
    "Simiabraz": ["brasier"],
    "Simularbre": ["rustique", "tete_de_roc"],
    "Sinistrail": ["hospitalite"],
    "Skelénox": ["fouille", "levitation"],
    "Smogo": ["levitation"],
    "Smogogo": ["levitation"],
    "Smogogo de Galar": ["levitation"],
    "Snubbull": ["intimidation"],
    "Solgaleo": ["corps_sain"],
    "Solaroc": ["levitation"],
    "Solochi": ["agitation"],
    "Sonistrelle": ["fouille"],
    "Sorcilence": ["miroir_magik"],
    "Soporifik": ["determination", "insomnia"],
    "Sorbouboul": ["alerte_neige", "corps_gele"],
    "Sorboul": ["corps_gele"],
    "Sorbébé": ["corps_gele"],
    "Spectreval": ["hennissement_sepulcral"],
    "Spectrum": ["levitation"],
    "Spinda": ["pieds_confus", "tempo_perso"],
    "Spiritomb": ["pression"],
    "Spoink": ["gourmandise", "peau_epaisse", "tempo_perso"],
    "Stalgamin": ["corps_gele", "determination"],
    "Stari": ["vigilance"],
    "Staross": ["vigilance"],
    "Statitik": ["essaim", "oeil_compose", "tension"],
    "Steelix": ["rustique", "tete_de_roc"],
    "Strassie": ["corps_sain", "rustique"],
    "Sucreine": ["ordre_royal"],
    "Suicune": ["determination", "pression"],
    "Sulfura": ["corps_ardent", "pression"],
    "Sulfura de Galar": ["ossature"],
    "Sylveroy": ["tension"],
    "Symbios": ["envelocape", "regenerescence"],
    "Séléroc": ["levitation"],
    "Séracrawl": ["corps_gele", "rustique", "tempo_perso"],
    "Séracrawl d'Hisui": ["corps_gele", "rustique"],
    "Séviper": ["mue"],
    "Tadmorv d'Alola": ["gourmandise"],
    "Tag-Tag": ["farceur"],
    "Tapatoès": ["agitation", "intimidation", "tenacite"],
    "Tarenbulle": ["absorb_eau"],
    "Terrakium": ["justicier"],
    "Théffroyable": ["turbine_eolienne"],
    "Tarinor": ["force_sable", "rustique"],
    "Tarinorme": ["force_sable", "rustique"],
    "Tarpaud": ["absorb_eau", "averse"],
    "Tarsal": ["synchro"],
    "Tartard": ["absorb_eau", "nage_rapide"],
    "Taupikeau": ["voile_sable"],
    "Taupiqueur": ["force_sable", "voile_sable"],
    "Taupiqueur d'Alola": ["force_sable", "voile_sable"],
    "Tauros": ["intimidation"],
    "Tauros de Paldea (Aqua)": ["intimidation"],
    "Tauros de Paldea (Combat)": ["intimidation"],
    "Tauros de Paldea (Flamme)": ["intimidation"],
    "Tengalice": ["chlorophylle"],
    "Tentacool": ["corps_sain"],
    "Tentacruel": ["corps_sain"],
    "Terapagos": ["carapace_tera"],
    "Terhal": ["corps_sain"],
    "Terracruel": ["mycelium_might"],
    "Terraiste": ["absorb_eau", "poison_de_contact"],
    "Tiboudet": ["determination", "tempo_perso"],
    "Tic": ["corps_sain"],
    "Tiplouf": ["torrent"],
    "Tissenboule": ["insomnia"],
    "Togedemaru": ["rustique"],
    "Togekiss": ["agitation", "grace_sereine"],
    "Togepi": ["agitation", "grace_sereine"],
    "Togetic": ["agitation", "grace_sereine"],
    "Tokopiyon": ["psycho_surge"],
    "Tokopisco": ["aura_surge"],
    "Tokorico": ["electro_surge"],
    "Tokotoro": ["chloro_surge"],
    "Torgamord": ["carapace", "nage_rapide"],
    "Tortank": ["torrent"],
    "Torterra": ["carapace", "plante"],
    "Tortipouss": ["carapace", "plante"],
    "Tournegrin": ["chlorophylle"],
    "Tournicoton": ["regenerescence"],
    "Toxizap": ["statik"],
    "Tranchodon": ["tension"],
    "Triopikeau": ["voile_sable"],
    "Triopikeur": ["force_sable", "voile_sable"],
    "Triopikeur d'Alola": ["force_sable", "voile_sable"],
    "Trioxhydre": ["levitation"],
    "Tritonde": ["absorb_eau", "hydratation", "nage_rapide"],
    "Tritosor": ["force_sable"],
    "Trompignon": ["regenerescence"],
    "Tropius": ["chlorophylle"],
    "Trousselin": ["farceur"],
    "Trépassable": ["voile_sable"],
    "Tygnon": ["determination", "regard_vif"],
    "Tylton": ["vigilance"],
    "Type:0": ["carapace"],
    "Typhlosion": ["brasier", "cache_flamme"],
    "Typhlosion d'Hisui": ["brasier", "fouille"],
    "Tyranocif": ["sable_volant", "tension"],
    "Ténéfix": ["farceur", "regard_vif"],
    "Téraclope": ["fouille", "pression"],
    "Têtampoule": ["statik", "tempo_perso"],
    "Têtarte": ["absorb_eau", "nage_rapide"],
    "Ursaking": ["tenacite", "tension"],
    "Ursaring": ["tenacite", "tension"],
    "Vaututrice": ["coeur_de_coq", "envelocape"],
    "Venalgue": ["poison_de_contact"],
    "Venipatte": ["essaim", "poison_de_contact"],
    "Verpom": ["gourmandise"],
    "Vibraninf": ["levitation"],
    "Viridium": ["justicier"],
    "Victini": ["etoile_victoire"],
    "Vigoroth": ["esprit_vital"],
    "Vipélierre": ["plante"],
    "Viskuse": ["absorb_eau"],
    "Vivaldaim": ["chlorophylle", "grace_sereine", "herbivore"],
    "Volcanion": ["absorb_eau"],
    "Volcaropod": ["armure_magma", "corps_ardent"],
    "Voltali": ["absorb_volt"],
    "Voltorbe": ["statik"],
    "Voltorbe d'Hisui": ["statik"],
    "Vorastérie": ["limber", "regenerescence"],
    "Vortente": ["levitation"],
    "Vostourno": ["coeur_de_coq", "envelocape"],
    "Vrombi": ["envelocape"],
    "Vrombotor": ["envelocape", "filtre"],
    "Vémini": ["boost_chimere"],
    "Wagomine": ["cache_flamme", "corps_ardent"],
    "Wailmer": ["pression", "voile_eau"],
    "Wailord": ["pression", "voile_eau"],
    "Wattouat": ["statik"],
    "Wimessir": ["determination", "synchro"],
    "Wushours": ["determination"],
    "Xatu": ["synchro"],
    "Xerneas": ["aura_fee"],
    "Yanma": ["fouille", "oeil_compose"],
    "Yuyu": ["fleau_perles"],
    "Yanmega": ["fouille", "lentiteintee"],
    "Ymphect": ["mue"],
    "Yveltal": ["aura_sombre"],
    "Zapétrel": ["absorb_volt"],
    "Zacian": ["intrepide"],
    "Zamazenta": ["bouclier_royal"],
    "Zarude": ["garde_feuille"],
    "Zarbi": ["levitation"],
    "Zekrom": ["teravolt"],
    "Zeraora": ["absorb_volt"],
    "Zoroark": ["illusion"],
    "Zygarde": ["rupture_aura"],
    "Zigzaton": ["gourmandise"],
    "Zigzaton de Galar": ["gourmandise"],
    "Zébibron": ["herbivore"],
    "Zéblitz": ["herbivore"],
    "Zéroïd": ["boost_chimere"],
    "Écayon": ["nage_rapide", "voile_eau"],
    "Écaïd": ["envelocape"],
    "Écrapince": ["carapace"],
    "Écrémeuh": ["herbivore", "peau_epaisse", "querelleur"],
    "Ékaïser": ["envelocape"],
    "Élecsprint": ["statik"],
    "Électhor": ["pression", "statik"],
    "Électhor de Galar": ["defiant"],
    "Électrode": ["statik"],
    "Électrode d'Hisui": ["statik"],
    "Élekable": ["esprit_vital"],
    "Élekid": ["esprit_vital", "statik"],
    "Élektek": ["esprit_vital", "statik"],
    "Éoko": ["levitation"],
    "Éthernatos": ["pression"],
    "Étouraptor": ["intimidation"],
    "Étourmi": ["regard_vif"],
    "Étourvol": ["intimidation"],
}


def capacite_pour_espece(pokemon_nom: str) -> str:
    """Tire une capacité pour cette espèce précise, en 3 paliers :
    1. Ses vraies capacités possibles si elle est déjà curatée dans POKEMON_CAPACITES.
    2. Sinon, un talent qui a au moins une affinité de TYPE avec elle (temporaire, pas
       de la vraie fidélité — voir AFFINITE_TYPE_CAPACITES / talent_semi_coherent).
    3. Sinon (aucune affinité connue pour ses types), un talent générique au hasard."""
    import pokemon_data

    possibles = POKEMON_CAPACITES.get(pokemon_nom)
    if possibles:
        return random.choice(possibles)

    pokemon = pokemon_data.obtenir_pokemon_par_nom(pokemon_nom)
    types_pokemon = pokemon.get("types") if pokemon else None
    semi_coherent = talent_semi_coherent(types_pokemon)
    if semi_coherent:
        return semi_coherent

    return talent_aleatoire()


def tire_genre_pour_espece(pokemon_nom: str) -> str:
    """Tire un genre pour ce Pokémon selon le VRAI ratio de son espèce (genre_taux dans
    pokedex_complet.json, valeur PokeAPI officielle : -1 = asexué, 0 = toujours mâle,
    8 = toujours femelle, valeurs intermédiaires = huitièmes de femelle). SNAPSHOTÉ une
    fois par combat (voir initialiser_equipe_combat_pvp) plutôt que fixé une fois pour
    toutes par capture — aucune donnée de genre n'existe côté captures pour l'instant."""
    import pokemon_data

    pokemon = pokemon_data.obtenir_pokemon_par_nom(pokemon_nom)
    taux = pokemon.get("genre_taux", -1) if pokemon else -1
    if taux == -1:
        return "aucun"
    if random.randint(0, 7) < taux:
        return "femelle"
    return "male"


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


def bloque_statut_sous_meteo(capacite: str, code_statut: str, meteo_active: str | None) -> bool:
    """Garde Feuille (Zarude) — immunisé aux problèmes de statut UNIQUEMENT sous Soleil,
    contrairement à bloque_statut qui protège en toutes circonstances."""
    info = CAPACITES.get(capacite)
    if not info or "immunite_statut_meteo" not in info:
        return False
    meteo_requise, statuts_bloques = info["immunite_statut_meteo"]
    return meteo_active == meteo_requise and code_statut in statuts_bloques


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
        if cle == "agitation" and classe_attaque == "physical":
            mult *= 1.5  # Agitation : +50% Attaque physique, inconditionnel
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


def multiplicateur_degats_pleine_vie(capacite: str, pv_actuels: int, pv_max: int) -> float:
    """Bouclier de l'Ombre (Lunala) — dégâts subis divisés par 2 tant que ce Pokémon est
    encore à pleine vie (redevient normal dès la première blessure, comme Multi-Écailles
    dans les vrais jeux)."""
    info = CAPACITES.get(capacite)
    if info and info.get("reduit_degats_pleine_vie") and pv_actuels >= pv_max:
        return 0.5
    return 1.0


def plafonne_efficacite_pleine_vie(capacite: str, pv_actuels: int, pv_max: int, multi_type_actuel: float) -> float:
    """Carapace Téra (Terapagos) — tant qu'à pleine vie, toute attaque qui touche est
    PLAFONNÉE à "pas très efficace" (0.5x), même si elle aurait normalement été neutre
    ou super efficace — remplace multi_type plutôt que de le multiplier. Ne s'applique
    jamais si l'attaque était déjà totalement inefficace (immunité de type, multi_type
    == 0) ni si le multiplicateur réel est DÉJÀ inférieur ou égal à 0.5 (pas d'aggravation)."""
    info = CAPACITES.get(capacite)
    if info and info.get("plafonne_efficacite_pleine_vie") and pv_actuels >= pv_max:
        if multi_type_actuel > 0.5:
            return 0.5
    return multi_type_actuel


def talent_declenche_sturdy(capacite: str) -> bool:
    """Rustique — même effet que l'objet Ceinture Force (survit à 1 PV depuis les PV
    max), mais permanent au lieu de se consommer une fois."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("sturdy"))


def immunise_contre_recul(capacite: str) -> bool:
    """Tête de Roc — aucun dégât de contrecoup (Boutefeu, Bélier, Ultimaton...)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_recul"))


def a_synchro(capacite: str) -> bool:
    info = CAPACITES.get(capacite)
    return bool(info and info.get("synchronize"))


def a_mue(capacite: str) -> bool:
    info = CAPACITES.get(capacite)
    return bool(info and info.get("shed_skin"))


def immunise_contre_baisse_stat_adverse(capacite: str) -> bool:
    """Corps Sain — immunisé aux baisses de stats infligées par l'ADVERSAIRE
    uniquement (un changement infligé par soi-même, ex: Damoclès, reste possible)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_baisse_stat_adverse"))


def multiplicateur_chance_secondaire(capacite: str) -> float:
    """Grâce Sereine — double la chance des effets secondaires (statut/altération) des
    attaques de ce Pokémon."""
    info = CAPACITES.get(capacite)
    return 2.0 if info and info.get("double_chance_secondaire") else 1.0


def defenseur_double_cout_pp(capacite: str) -> bool:
    """Pression — les attaques utilisées CONTRE ce Pokémon consomment 2 PP au lieu d'1."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("double_cout_pp_adverse"))


def multiplicateur_seuil_baie(capacite: str) -> float:
    """Gourmandise — la Baie de soin se déclenche à 50% des PV max au lieu de 25%."""
    info = CAPACITES.get(capacite)
    return 2.0 if info and info.get("double_seuil_baie") else 1.0


def soin_sortie_terrain(capacite: str) -> float | None:
    """Régénération — pourcentage de PV max soigné en quittant volontairement le
    combat (changement, PAS K.O.), sinon None."""
    info = CAPACITES.get(capacite)
    if info and "soin_sortie_terrain" in info:
        return info["soin_sortie_terrain"]
    return None


def soigne_statut_a_la_sortie(capacite: str) -> bool:
    """Vigilance — guérit automatiquement le statut en quittant volontairement le combat."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("soin_statut_sortie_terrain"))


def immunise_contre_critiques(capacite: str) -> bool:
    """Carapace — ne peut jamais subir de coup critique."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_critique"))


def immunise_contre_flinch(capacite: str) -> bool:
    """Détermination — ne peut jamais flancher."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_flinch"))


def multiplicateur_vitesse_meteo(capacite: str, meteo_active: str | None) -> float:
    """Chlorophylle/Nage Rapide — double la Vitesse sous la bonne météo."""
    info = CAPACITES.get(capacite)
    if info and info.get("double_vitesse_meteo") == meteo_active:
        return 2.0
    return 1.0


def multiplicateur_stat_meteo_signature(capacite: str, meteo_active: str | None, stat: str) -> float:
    """Pulsion Orichalque (Koraidon) — +33% sur UNE stat précise (son Attaque) tant
    qu'UNE météo précise (Soleil) est active — combiné avec meteo_declenchee_a_entree
    qui déclenche cette météo à l'entrée."""
    info = CAPACITES.get(capacite)
    if info and "boost_stat_meteo" in info:
        meteo_requise, stat_requise, mult = info["boost_stat_meteo"]
        if meteo_active == meteo_requise and stat == stat_requise:
            return mult
    return 1.0


def multiplicateur_stat_terrain_signature(capacite: str, terrain_actif: str | None, stat: str) -> float:
    """Moteur Hadron (Miraidon) — même principe que multiplicateur_stat_meteo_signature,
    mais pour un terrain de zone (Électrique) plutôt qu'une météo."""
    info = CAPACITES.get(capacite)
    if info and "boost_stat_terrain" in info:
        terrain_requis, stat_requise, mult = info["boost_stat_terrain"]
        if terrain_actif == terrain_requis and stat == stat_requise:
            return mult
    return 1.0


def multiplicateur_stat_dominante(
    capacite: str, meteo_active: str | None, terrain_actif: str | None, row: dict, cle_stat: str
) -> float:
    """Vigueur Ancestrale (Protosynthesis, les 10 Paradoxes du passé) / Turbo Circuit
    (Quark Drive, les 10 Paradoxes du futur) — +30% (ou +50% si c'est la Vitesse) sur
    la stat de BASE la plus élevée du Pokémon, tant que le Soleil brille (Vigueur
    Ancestrale) ou que le Terrain Électrique est actif (Turbo Circuit). En cas d'égalité
    entre plusieurs stats, priorité Attaque > Défense > Attaque Spé > Défense Spé >
    Vitesse, comme dans les vrais jeux. v1 : ne couvre pas la Capsule Dynamo (Booster
    Energy), qui donnerait le même effet en continu sans dépendre de la météo/du
    terrain — cet objet n'existe pas encore dans ce jeu."""
    info = CAPACITES.get(capacite)
    if not info or "stat_dominante_condition" not in info:
        return 1.0
    type_condition, valeur_requise = info["stat_dominante_condition"]
    if type_condition == "meteo" and meteo_active != valeur_requise:
        return 1.0
    if type_condition == "terrain" and terrain_actif != valeur_requise:
        return 1.0

    candidats = [
        ("atk", row["atq"]), ("def", row["defe"]), ("atk_spe", row["atq_spe"]),
        ("def_spe", row["def_spe"]), ("vit", row["vit"]),
    ]
    stat_dominante = max(candidats, key=lambda c: c[1])[0]  # max() garde le 1er trouvé en cas d'égalité, déjà dans l'ordre de départage voulu

    if cle_stat != stat_dominante:
        return 1.0
    return 1.5 if stat_dominante == "vit" else 1.3


def multiplicateur_defense_si_statut(capacite: str, a_statut: bool) -> float:
    """Écailles Magiques (Marvel Scale, Milobellus) — +50% Défense tant qu'il a un
    problème de statut (poison/brûlure/paralysie/sommeil/gel — pas la confusion, qui
    est un statut volatil séparé, jamais un "problème de statut" au sens classique)."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_defense_si_statut") and a_statut:
        return 1.5
    return 1.0


def multiplicateur_vitesse_si_statut(capacite: str, a_statut: bool) -> float:
    """Pied Véloce (Quick Feet, Teddiursa) — +50% Vitesse tant qu'il a un problème de
    statut (même principe qu'Écailles Magiques, mais sur la Vitesse)."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_vitesse_si_statut") and a_statut:
        return 1.5
    return 1.0


# Attaques "sonores" reconnues par Ronfleur (Soundproof, Chuchmur) — liste limitée aux
# attaques identifiées avec confiance dans ce Pokédex.
ATTAQUES_SONORES = {"Ultrason", "Grondement", "Voix Envoûtante", "Hurlement", "Rugissement", "Ronflement", "Requiem"}


def immunise_attaque_sonore(capacite: str, nom_attaque: str) -> bool:
    """Ronfleur (Soundproof, Chuchmur) — immunisé aux attaques sonores reconnues (voir
    ATTAQUES_SONORES)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_sonore") and nom_attaque in ATTAQUES_SONORES)


def a_cran_vital(capacite: str) -> bool:
    """Cran Vital (Speed Boost, Ninjask) — +1 Vitesse à la fin de chaque tour où ce
    Pokémon est resté actif. Le déclenchement (une fois par tour) se fait côté
    combat.py, cette fonction ne fait que détecter la capacité."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("cran_vital"))


def a_wonder_guard(capacite: str) -> bool:
    """Wonder Guard (Munja) — immunisé à toute attaque qui n'est pas super efficace.
    v1 : ne protège que des attaques offensives typées (comme dans les vrais jeux, où
    Lutte/Struggle et les dégâts indirects passent quand même) — la vérification du
    multiplicateur de type et l'exclusion de Lutte se font côté combat.py."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("wonder_guard"))


def a_absenteisme(capacite: str) -> bool:
    """Absentéisme (Truant, Parecool) — n'agit qu'un tour sur deux, glande l'autre.
    Toute la logique d'alternance (glande_prochain_tour) se fait côté combat.py, cette
    fonction ne fait que détecter la capacité."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("absenteisme"))


def multiplicateur_moelleux(capacite: str, classe_attaque: str | None, type_attaque: str | None) -> float:
    """Moelleux (Fluffy, Nounourson/Moumouton/Moumouflon) — dégâts physiques (contact,
    approximé par classe == physical comme Peau Dure) divisés par 2, dégâts Feu
    doublés. Si l'attaque est À LA FOIS physique ET Feu, les deux s'annulent (comme
    dans les vrais jeux — Moelleux ne fait alors ni bien ni mal)."""
    info = CAPACITES.get(capacite)
    if not info or not info.get("moelleux"):
        return 1.0
    mult = 1.0
    if classe_attaque == "physical":
        mult *= 0.5
    if type_attaque == "feu":
        mult *= 2.0
    return mult


def declenche_dommage_sec(capacite: str, classe_attaque: str | None) -> bool:
    """Dommage Sec (Aftermath, Baudrive/Grodrive) — en étant mis K.O. par une attaque
    physique (approximé "au contact" comme Peau Dure), inflige 25% des PV max de
    l'attaquant en retour. Le déclenchement (vérifier le K.O.) se fait côté combat.py."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("dommage_sec") and classe_attaque == "physical")


def a_expuls_organes(capacite: str) -> bool:
    """Expuls'Organes (Innards Out, Concombaffe) — en étant mis K.O. (n'importe quelle
    classe d'attaque, contrairement à Dommage Sec/Peau Dure qui exigent le contact),
    inflige à l'attaquant des dégâts égaux à SES PROPRES PV restants avant le coup
    fatal (pas un pourcentage fixe). Le calcul se fait côté combat.py."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("expuls_organes"))


def a_supermutation(capacite: str) -> bool:
    """Supermutation (Zero to Hero, Superdofin) — passe en forme Super (stats bien
    plus élevées) après un changement volontaire hors puis retour sur le terrain,
    définitivement pour le reste du combat. v1 : approxime le vrai bond de stats par
    un x1.9 uniforme sur toutes les stats de combat, plutôt que les vraies valeurs de
    base précises de la forme Super (proche, pas identique)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("supermutation"))


def en_forme_ecole(capacite: str, niveau: int, pv_actuels: int, pv_max: int) -> bool:
    """Bancosphère (Schooling, Froussardine) — forme École (stats bien plus élevées,
    sauf Vitesse qui baisse) tant que le niveau est 20+ ET les PV au-dessus de 25%,
    recalculé EN DIRECT à chaque instant (jamais persistant, comme Forme Météo — les
    vrais jeux le réévaluent aussi à chaque tour, pas seulement à l'entrée). v1 :
    approxime le vrai bond de stats (x7/x6.5/x5.6/x5.4 selon la stat précisément) par
    un x6 uniforme sur Attaque/Défense/Attaque Spé/Défense Spé, et x0.75 sur la
    Vitesse — proche, pas identique aux vraies valeurs de base de la forme École."""
    info = CAPACITES.get(capacite)
    if not info or not info.get("bancosphere"):
        return False
    return niveau >= 20 and pv_max > 0 and pv_actuels / pv_max > 0.25


def a_anti_air(capacite: str) -> bool:
    """Anti-Air (No Guard, Monorpale/Dimoclès) — toute attaque touche toujours, que ce
    Pokémon attaque ou soit visé."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("anti_air"))


def boost_attaque_contact(capacite: str, classe_attaque: str | None) -> float:
    """Poigne de Fer (Tough Claws, Berserkatt) — +30% sur les attaques au contact
    (approximé classe == physical, comme Peau Dure)."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_contact") and classe_attaque == "physical":
        return 1.3
    return 1.0


# Attaques "morsure" reconnues par Mâchoire Brute (Strong Jaw) — liste limitée aux
# attaques identifiées avec confiance dans ce Pokédex.
ATTAQUES_MORSURE = {"Morsure", "Croc Fatal", "Crochet Venin", "Crocs Éclair", "Crocs Givre", "Crocs Feu", "Psycho-Croc"}


def boost_attaque_morsure(capacite: str, nom_attaque: str) -> float:
    """Mâchoire Brute (Strong Jaw, Voltoutou/Fulgudog) — +50% sur les attaques de
    morsure reconnues (voir ATTAQUES_MORSURE)."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_morsure") and nom_attaque in ATTAQUES_MORSURE:
        return 1.5
    return 1.0


def change_capacite_au_contact(capacite: str, classe_attaque: str | None) -> str | None:
    """Momie (Mummy, Tutafeh/Tutankafer) / Esprit Vagabond (Wandering Spirit,
    Tutétékri) — au contact (approximé classe == physical), transforme la capacité de
    L'ATTAQUANT. Momie devient toujours "momie" (qui se propage à son tour, un
    Pokémon Momie touché au contact rend Momie l'attaquant suivant). Esprit Vagabond
    ÉCHANGE les deux capacités au lieu de forcer la sienne — géré différemment côté
    combat.py, cette fonction retourne juste la NOUVELLE capacité à donner à
    l'attaquant pour le cas Momie (simple à sens unique), ou None si inapplicable/pas
    Momie (Esprit Vagabond est détecté séparément via a_esprit_vagabond)."""
    info = CAPACITES.get(capacite)
    if info and info.get("momie") and classe_attaque == "physical":
        return "momie"
    return None


def a_esprit_vagabond(capacite: str, classe_attaque: str | None) -> bool:
    """Esprit Vagabond (Wandering Spirit, Tutétékri) — au contact, ÉCHANGE sa propre
    capacité avec celle de l'attaquant (contrairement à Momie qui impose la sienne à
    sens unique). L'échange lui-même se fait côté combat.py."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("esprit_vagabond") and classe_attaque == "physical")


def riposte_contact(capacite: str, classe_attaque: str | None) -> float:
    """Peau Dure (Rough Skin) / Piquant (Iron Barbs) — inflige un pourcentage des PV
    max de l'ATTAQUANT en retour, sur toute attaque au CONTACT subie. v1 : "au contact"
    approximé par classe == "physical" (heuristique raisonnable — la plupart des
    attaques physiques font contact dans les vrais jeux, quelques exceptions comme
    Séisme ne sont pas distinguées ici, faute d'un champ "contact" dans ce Pokédex).
    Retourne le pourcentage (0.0 si inapplicable)."""
    info = CAPACITES.get(capacite)
    if info and info.get("contact_riposte") and classe_attaque == "physical":
        return info.get("riposte_pourcent", 0.0)
    return 0.0


def a_facsimile(capacite: str) -> bool:
    """Fac-similé (Disguise, Mimiqui) — bloque intégralement UN SEUL coup sur toute la
    durée du combat (1/8 PV max perdu à la place). Toute la logique de consommation
    (facsimile_brise) se fait côté combat.py, cette fonction ne fait que détecter la
    capacité."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("facsimile"))


def piege_adversaire(capacite: str) -> bool:
    """Ombre Portée (Shadow Tag, Qulbutoké/Okéoké) — empêche l'adversaire de changer
    volontairement de Pokémon tant qu'il est en vie. v1 : bloqué au moment de la
    résolution plutôt que dans l'interface de choix (le joueur peut toujours cliquer
    sur changer, l'action échoue avec un message)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("piege_adversaire"))


def multiplicateur_chochotte(capacite: str, pv_actuels: int, pv_max: int) -> float:
    """Chochotte (Defeatist, Arkéapti) — Attaque et Attaque Spéciale divisées par 2 dès
    que les PV tombent à 50% ou moins (pas seulement en-dessous, contrairement à
    Ossature/Porte de Secours — le seuil de 50% pile compte déjà)."""
    info = CAPACITES.get(capacite)
    if info and info.get("chochotte") and pv_max > 0 and pv_actuels / pv_max <= 0.5:
        return 0.5
    return 1.0


def a_pure_puissance(capacite: str) -> bool:
    """Pure Puissance (Huge Power, Excavarenne) — double sa propre Attaque de base
    (physique uniquement, jamais l'Attaque Spéciale)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("pure_puissance"))


def a_tactiques_simiesques(capacite: str) -> bool:
    """Tactiques Simiesques (Gorilla Tactics, Darumacho de Galar) — +50% Attaque
    physique. v1 SIMPLIFIÉE : dans les vrais jeux, cette capacité verrouille aussi le
    porteur sur sa PREMIÈRE attaque choisie pour tout le combat (comme un objet Choix)
    — cette contrainte n'est PAS reproduite ici, seul le bonus de puissance l'est."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("tactiques_simiesques"))


def multiplicateur_fourrure_renforcee(capacite: str, classe_attaque: str | None) -> float:
    """Fourrure Renforcée (Fur Coat, Couafarel) — dégâts physiques subis divisés par 2
    (jamais les dégâts spéciaux)."""
    info = CAPACITES.get(capacite)
    if info and info.get("fourrure_renforcee") and classe_attaque == "physical":
        return 0.5
    return 1.0


def bloque_attaque_statut_adverse(capacite: str, classe_attaque: str | None) -> bool:
    """Or Pur (Good as Gold, Gromago) — immunisé à toute attaque de STATUT adverse
    (jamais aux attaques offensives, même avec un effet secondaire de statut — seules
    les attaques 100% statut comme Toxic ou Rugissement sont bloquées)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("bloque_statut_adverse") and classe_attaque == "status")


# Dupliquée localement plutôt qu'importée de combat.py (qui importe déjà capacites.py —
# un import inverse créerait un cycle). Doit rester synchronisée avec
# ATTAQUES_PRIORITE_POSITIVE dans combat.py si cette liste est un jour étendue.
ATTAQUES_PRIORITE_POSITIVE_CAPACITES = {"Vive-Attaque", "Ombre Portée", "Poing Éclair", "Direct Toxik"}


def bloque_attaque_prioritaire(capacite: str, nom_attaque: str) -> bool:
    """Ordre Royal (Queenly Majesty, Sucreine) — bloque toute attaque adverse à
    priorité positive (voir ATTAQUES_PRIORITE_POSITIVE dans combat.py). v1 : ne couvre
    que les attaques à priorité FIXE de cette liste, pas les attaques de statut
    dynamiquement boostées en priorité par Farceur/Mycelium Might chez l'attaquant."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("bloque_priorite") and nom_attaque in ATTAQUES_PRIORITE_POSITIVE_CAPACITES)


def a_miroir_magik(capacite: str, classe_attaque: str | None) -> bool:
    """Miroir Magik (Magic Bounce, Sorcilence) — sur une attaque de STATUT adverse
    (jamais offensive), renvoie l'effet vers son lanceur au lieu de le subir. v1 : ne
    couvre pas la Malédiction spectrale (exception réelle qui touche quand même la
    cible), ni les capacités Brise Moule/Turbo Brasier/Téra-Voltage qui devraient
    ignorer ce renvoi. Toute la logique de redirection se fait côté combat.py."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("miroir_magik") and classe_attaque == "status")


def a_adaptabilite(capacite: str) -> bool:
    """Adaptabilité (Adaptability, Évoli) — le STAB passe de x1.5 à x2.0."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("adaptabilite"))


def a_garde_magique(capacite: str) -> bool:
    """Garde Magique (Magic Guard, Mélofée/Mélo/Mélodelfe) — immunisé à tout dégât
    INDIRECT (statut, météo...). v1 : ne couvre que le statut (poison/brûlure) et la
    météo (sable/grêle), pas le recul (Life Orb) ni les hazards à l'entrée."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("garde_magique"))


def a_camouflage(capacite: str) -> bool:
    """Camouflage (Color Change, Kecleon) — change son propre type pour correspondre à
    la dernière attaque offensive subie. Toute la logique de déclenchement/lecture se
    fait côté combat.py (colonne type_camouflage), cette fonction ne fait que détecter
    la capacité."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("camouflage"))


def type_forme_meteo(capacite: str, meteo_active: str | None) -> str | None:
    """Forme Météo (Forecast, Morphéo) — change son propre type selon la météo
    ACTIVE, recalculé en direct (jamais persistant, contrairement à Camouflage) :
    Soleil -> Feu, Pluie -> Eau, Grêle -> Glace, sinon (ou Tempête de Sable) -> Normal
    (son type de base). Retourne le type à utiliser, ou None si inapplicable (pas
    Forme Météo)."""
    info = CAPACITES.get(capacite)
    if not info or not info.get("forme_meteo"):
        return None
    return {"soleil": "feu", "pluie": "eau", "grele": "glace"}.get(meteo_active, "normal")


def boost_si_touche_physique(capacite: str) -> tuple | None:
    """Armure Fragile (Weak Armor, Polthégeist/Corayôme) — quand touché par une attaque
    PHYSIQUE (peu importe le type), -1 Défense et +2 Vitesse. Retourne
    (stat_baissee, stat_haussee) si applicable, sinon None."""
    info = CAPACITES.get(capacite)
    if info and info.get("armure_fragile"):
        return ("def", -1), ("vit", 2)
    return None


def transforme_type_normal(capacite: str) -> bool:
    """Pixilate (Nymphali) — transforme ses propres attaques Normal en Fée (+30% de
    puissance). Le VRAI travail (copie sûre du dict d'attaque, jamais de mutation du
    catalogue partagé) se fait côté combat.py — cette fonction ne fait que détecter la
    capacité."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("transforme_normal_en"))


def multiplicateur_debut_lent(capacite: str, tours_en_jeu: int) -> dict:
    """Lenteur (Slow Start) — Attaque et Vitesse divisées par 2 pendant les
    NB_TOURS_DEBUT_LENT premiers tours après l'envoi (tours_en_jeu 0-indexé : le tour de
    l'envoi lui-même compte comme le premier). Retourne {"atk": mult, "vit": mult}, tous
    deux à 1.0 si inapplicable."""
    info = CAPACITES.get(capacite)
    if info and info.get("debut_lent") and tours_en_jeu < info["debut_lent"]:
        return {"atk": 0.5, "vit": 0.5}
    return {"atk": 1.0, "vit": 1.0}


def meteo_declenchee_a_entree(capacite: str) -> str | None:
    """Sécheresse/Averse/Sable Volant/Alerte Neige — météo déclenchée à l'entrée en jeu."""
    info = CAPACITES.get(capacite)
    if info and info.get("sur_entree"):
        return info.get("meteo_entree")
    return None


def terrain_declenche_a_entree(capacite: str) -> str | None:
    """Électro Surge/Chloro Surge/Aura Surge/Psycho Surge (les 4 Tapu) — terrain de zone
    déclenché à l'entrée en jeu, même principe que meteo_declenchee_a_entree."""
    info = CAPACITES.get(capacite)
    if info and info.get("terrain_entree"):
        return info["terrain_entree"]
    return None


def revele_objet_a_entree(capacite: str) -> bool:
    """Fouille — révèle l'objet tenu de l'adversaire à l'entrée en jeu."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("revele_objet_entree"))


def stat_protegee_contre_adversaire(capacite: str) -> str | None:
    """Cœur de Coq (et similaires futurs) — un SEUL stat protégé des baisses infligées
    par l'adversaire, contrairement à Corps Sain qui protège tout."""
    info = CAPACITES.get(capacite)
    return info.get("protege_stat_adverse") if info else None


def empeche_baie_adverse(capacite: str) -> bool:
    """Tension — l'adversaire ne peut pas manger sa Baie de soin face à ce Pokémon."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("empeche_baie_adverse"))


def boost_attaques_faible_puissance(capacite: str) -> bool:
    """Technicien — +50% sur les attaques ≤60 de puissance de base."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("boost_attaques_faible_puissance"))


def a_force_brute(capacite: str) -> bool:
    """Force Brute (Sheer Force, Pachyradjah) — +30% de puissance sur toute attaque
    ayant un effet secondaire (ailment ou changement de stat), mais annule CET effet
    secondaire en échange. La détection ET la suppression se font côté combat.py
    (nécessite de lire/modifier les champs de l'attaque avant le calcul de dégâts)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("force_brute"))


def a_corrosion(capacite: str) -> bool:
    """Corrosion (Floréclat) — peut empoisonner un Poison/Acier malgré leur immunité de
    type naturelle. Passé en paramètre ignore_immunite_poison_type de
    database.definir_statut par l'appelant."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("corrosion"))


def bloque_effets_secondaires_subis(capacite: str) -> bool:
    """Écran Poudre — immunisé aux effets secondaires (pas aux dégâts) des attaques subies."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("bloque_effets_secondaires_subis"))


def boost_apres_ko(capacite: str) -> bool:
    """Boost Chimère — +1 à la stat la plus élevée après avoir mis K.O. l'adversaire."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("boost_apres_ko"))


def touche_spectre_normal_combat(capacite: str) -> bool:
    """Querelleur — les attaques Normal/Combat de ce Pokémon touchent les Spectre."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("touche_spectre_normal_combat"))


def immunise_contre_intimidation(capacite: str) -> bool:
    """Querelleur — immunisé à Intimidation."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_intimidation"))


def double_pas_tres_efficace(capacite: str) -> bool:
    """Lentiteintée — double les dégâts de ses propres attaques pas très efficaces."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("double_pas_tres_efficace"))


def a_priorite_attaques_statut(capacite: str) -> bool:
    """Farceur — priorité +1 sur les attaques de statut de ce Pokémon."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("priorite_attaques_statut"))


def a_mycelium_might(capacite: str) -> bool:
    """Mycelium Might (Terracruel) — symétrique de Farceur : SES PROPRES attaques de
    statut agissent toujours en dernier dans leur tranche de priorité (géré côté
    combat.py, symétrique de a_priorite_attaques_statut ci-dessus), mais ignorent en
    échange la capacité d'immunité de statut de la cible. v1 : ne couvre que cette
    immunité de statut précise — pas les autres capacités "ignorables" que les vrais
    jeux bypassent aussi (Corps Sain contre une baisse de stat, par exemple)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("mycelium_might"))


def a_illusion(capacite: str) -> bool:
    """Illusion (Zoroark) — se déguise en le dernier Pokémon conscient de l'équipe
    jusqu'à subir un coup. ⚠️ Adaptation : dans les vrais jeux, ne trompe que
    l'adversaire, jamais son propre dresseur — ici visible de tout le monde (voir
    commentaire sur la colonne deguise_en dans database/__init__.py pour le pourquoi).
    Toute la détection/révélation se fait côté combat.py, cette fonction ne fait que
    détecter la capacité."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("illusion"))


def pourcent_soin_allie_entree(capacite: str) -> float:
    """Hospitalité (Sinistrail) — soigne son allié de 25% de ses PV max à l'entrée en
    jeu. Utile UNIQUEMENT en 2v2 (aucun allié en 1v1) — retourne 0.0 si inapplicable."""
    info = CAPACITES.get(capacite)
    if info and "soin_allie_entree" in info:
        return info["soin_allie_entree"]
    return 0.0


def protege_allie_type(capacite: str) -> str | None:
    """Voile Floral (Flower Veil, Florges) — protège les alliés d'UN TYPE précis
    (Plante) des baisses de stats et des problèmes de statut. Utile UNIQUEMENT en 2v2
    (aucun allié en 1v1) — retourne le type protégé, ou None si inapplicable."""
    info = CAPACITES.get(capacite)
    return info.get("protege_allie_type") if info else None


def multiplicateur_poids_effectif(capacite: str) -> float:
    """Métal Léger (Light Metal) divise son PROPRE poids effectif par 2, Métal Lourd
    (Heavy Metal) le double — affecte uniquement le calcul de puissance des attaques
    basées sur le poids (Nœud Herbe, Balayage, Tacle Lourd, Tacle Feu), jamais le poids
    réel affiché ailleurs (Pokédex, etc.)."""
    info = CAPACITES.get(capacite)
    if info and "mult_poids" in info:
        return info["mult_poids"]
    return 1.0


def multiplicateur_types_meteo(capacite: str, meteo_active: str | None, type_attaque: str) -> float:
    """Force Sable (et similaires futurs) — +30% sur certains types sous une météo précise."""
    info = CAPACITES.get(capacite)
    if not info or "boost_types_meteo" not in info:
        return 1.0
    meteo_requise, types_boostes = info["boost_types_meteo"]
    if meteo_active == meteo_requise and type_attaque in types_boostes:
        return 1.3
    return 1.0


def immunise_contre_degats_meteo(capacite: str) -> bool:
    """Envelocape — immunisé aux dégâts de fin de tour de la météo."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_degats_meteo"))


def inflige_degats_sommeil_adverse(capacite: str) -> float:
    """Cauchemar (Bad Dreams) — tant que ce Pokémon est sur le terrain, l'adversaire actif
    endormi perd une fraction de ses PV max à la fin de chaque tour. Retourne la fraction
    à infliger (0.0 si cette capacité n'a pas cet effet)."""
    info = CAPACITES.get(capacite)
    if info and "degats_sommeil_adverse" in info:
        return info["degats_sommeil_adverse"]
    return 0.0


def meteo_guerissant_statut(capacite: str) -> str | None:
    """Hydratation — guérit le statut en fin de tour sous la bonne météo."""
    info = CAPACITES.get(capacite)
    return info.get("soin_statut_meteo") if info else None


def multiplicateur_degats_critique(capacite: str) -> float:
    """Sniper — coup critique renforcé (x2.25 au lieu de x1.5 de base)."""
    info = CAPACITES.get(capacite)
    if info and "boost_critique" in info:
        return info["boost_critique"]
    return 1.5


def ignore_esquive_adverse(capacite: str) -> bool:
    """Regard Vif — ignore le stage d'Esquive de la cible quand ce Pokémon attaque."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("ignore_esquive_cible"))


def multiplicateur_precision_attaque(capacite: str) -> float:
    """Œil Composé — +30% de Précision sur les attaques de ce Pokémon."""
    info = CAPACITES.get(capacite)
    if info and "boost_precision_attaque" in info:
        return info["boost_precision_attaque"]
    return 1.0


def multiplicateur_precision_physique(capacite: str) -> float:
    """Agitation — -20% de Précision sur les attaques PHYSIQUES de ce Pokémon."""
    info = CAPACITES.get(capacite)
    if info and "malus_precision_physique" in info:
        return info["malus_precision_physique"]
    return 1.0


def bonus_esquive_defenseur(capacite: str, meteo_active: str | None, est_confus: bool) -> float:
    """Voile Sable (sous tempête de sable) + Pieds Confus (si confus) — bonus additif au
    stage d'Esquive effectif du défenseur, exprimé directement en fraction de précision
    à soustraire (approximation simple plutôt qu'un vrai stage, pour rester lisible)."""
    info = CAPACITES.get(capacite)
    bonus = 0.0
    if info and "boost_esquive_meteo" in info:
        meteo_requise, valeur = info["boost_esquive_meteo"]
        if meteo_active == meteo_requise:
            bonus += valeur
    if info and est_confus and "boost_esquive_confusion" in info:
        bonus += info["boost_esquive_confusion"]
    return bonus


def immunise_contre_degats_meteo_specifique(capacite: str, type_meteo: str) -> bool:
    """Voile Sable — immunisé aux dégâts d'UNE météo précise (contrairement à Envelocape
    qui protège de toutes)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_degats_meteo_specifique") == type_meteo)


def annule_meteo(capacite: str) -> bool:
    """Air Lock (Rayquaza) — annule l'effet de la météo sur les dégâts tant que ce
    Pokémon est sur le terrain, peu importe le camp. v1 : ne couvre que le boost/malus
    de dégâts Feu/Eau sous Soleil/Pluie et les boosts de type liés (Force Sable...) — ne
    couvre pas encore les dégâts de fin de tour du sable/grêle ni le doublement de
    Vitesse (Chlorophylle...), et n'empêche pas une météo d'être déclenchée à l'entrée
    par une autre capacité (limitation connue, comme les autres effets \"sur_entree\")."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("annule_meteo"))


def multiplicateur_aura(capacite_1: str, capacite_2: str, type_attaque: str) -> float:
    """Aura Fée (Xerneas) / Aura Sombre (Yveltal) — +33% sur les attaques du type
    correspondant utilisées par N'IMPORTE QUI sur le terrain (attaquant ET défenseur
    confondus, y compris le porteur de l'aura lui-même) tant que l'un des deux
    combattants a la bonne aura active. Rupture Aura (Zygarde), chez l'un OU l'autre
    combattant, inverse cet effet en -25% au lieu de +33% si une aura est bien active
    (sans effet si aucune aura n'est présente — rien à "casser")."""
    aura_active = any(
        (info := CAPACITES.get(capacite)) and info.get("boost_aura_type") == type_attaque
        for capacite in (capacite_1, capacite_2)
    )
    if not aura_active:
        return 1.0
    rupture_active = any(
        (info := CAPACITES.get(capacite)) and info.get("aura_break")
        for capacite in (capacite_1, capacite_2)
    )
    return 0.75 if rupture_active else 1.33


def multiplicateur_type_signature(capacite: str, type_attaque: str) -> float:
    """Transistor (Regieleki) / Gueule Draconique (Regidrago) — +50% sur les attaques
    d'UN TYPE PRÉCIS de CE Pokémon uniquement (contrairement à Aura Fée/Sombre qui
    profite à tout le monde) — peu importe le vrai type du porteur."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_propre_type") == type_attaque:
        return 1.5
    return 1.0

# Attaques de poing reconnues par Poing de Fer (Meltan/Melmetal) — liste EXPLICITE plutôt
# qu'une recherche de sous-chaîne "Poing", qui inclurait à tort des attaques comme
# "Poing Karaté" (= Karate Chop dans les vrais jeux, jamais concernée par Poing de Fer
# malgré son nom). Liste volontairement limitée aux attaques identifiées avec confiance
# dans ce Pokédex — quelques attaques au nom ambigu (Poing Dard, Poing Obscur, Poing
# Sonique, Poing de Colère, Mitra-Poing, Écrous d'Poing) sont omises faute de certitude
# sur leur correspondance exacte avec une vraie attaque de poing des jeux officiels.
ATTAQUES_POING = {
    "Poing Comète", "Poing Feu", "Poing Glace", "Poing Éclair", "Dynamo-Poing",
    "Poing Météore", "Poing Ombre", "Marto-Poing", "Vampi-Poing", "Pisto-Poing",
    "Poing Boost", "Ultimapoing",
}


# Attaques de la famille "vibration/aura" (pulse) reconnues par Méga Blaster (Mega
# Launcher, Gamblast) — liste limitée aux attaques identifiées avec confiance dans ce
# Pokédex (Aura Sphere, Water Pulse, Origin Pulse). D'autres membres réels de la famille
# (Dark Pulse, Dragon Pulse, Heal Pulse, Terrain Pulse) n'ont pas été retrouvés sous un
# nom français univoque dans ce jeu — omis faute de certitude plutôt que devinés.
ATTAQUES_PULSE = {"Aurasphère", "Vibraqua", "Onde Originelle"}


# Attaques "vent" reconnues par Turbine Éolienne (Wind Rider, Théffroyable) — liste
# limitée aux attaques identifiées avec confiance (Hurricane, Tailwind, Icy Wind, Fairy
# Wind). D'autres membres réels de la famille (Gust, Twister, Whirlwind, Petal Blizzard,
# Sandstorm) n'ont pas de correspondance française univoque retrouvée dans ce jeu.
ATTAQUES_VENT = {"Ouragan", "Vent Arrière", "Vent Glace", "Vent Féérique"}


def immunise_et_boost_si_vent(capacite: str, nom_attaque: str) -> bool:
    """Turbine Éolienne (Wind Rider, Théffroyable) — immunisé aux dégâts d'une attaque
    de la famille "vent" reconnue (voir ATTAQUES_VENT), et gagne +1 Attaque en plus. Le
    boost de stat est appliqué côté combat.py (retourne juste si applicable ici)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("immunite_vent") and nom_attaque in ATTAQUES_VENT)


# Attaques dont la puissance dépend du POIDS — Nœud Herbe/Balayage (poids de LA CIBLE),
# Tacle Lourd/Tacle Feu (ratio attaquant/cible). Nécessite pokemon_data.poids_kg,
# ajouté au Pokédex spécifiquement pour ces 4 attaques et Métal Léger/Lourd.
ATTAQUES_POIDS_CIBLE = {"Nœud Herbe", "Balayage"}
ATTAQUES_POIDS_RATIO = {"Tacle Lourd", "Tacle Feu"}


# Attaques à coups multiples reconnues — (min, max) coups. Liste limitée aux attaques
# identifiées avec confiance dans ce Pokédex. v1 : le nombre de coups tirés au hasard
# APPROXIME l'effet en multipliant la puissance totale par le nombre de coups, plutôt
# que de résoudre chaque coup séparément (crit/effet indirect par coup) — un choix
# délibéré à faible risque pour ne pas restructurer toute la boucle de dégâts déjà
# construite autour d'un seul coup par attaque.
ATTAQUES_COUPS_MULTIPLES = {
    "Furie": (2, 5), "Dard-Nuée": (2, 5), "Double Pied": (2, 2),
}


def declenche_charme_ensorceleur(capacite_def: str, genre_def: str, genre_atk: str, classe_attaque: str | None) -> bool:
    """Charme Ensorceleur (Cute Charm, Rondoudou/Toudoudou/Skitty/Delcatty) — 30% de
    chance d'infatuer L'ATTAQUANT au contact (approximé classe == physical, comme
    Peau Dure), SEULEMENT si les deux ont un genre opposé (jamais si l'un des deux est
    asexué — "aucun" ne matche jamais rien, même pas un autre "aucun")."""
    info = CAPACITES.get(capacite_def)
    if not info or not info.get("charme_ensorceleur") or classe_attaque != "physical":
        return False
    if genre_def == "aucun" or genre_atk == "aucun" or genre_def == genre_atk:
        return False
    return random.random() < 0.30


def tire_nombre_coups(nom_attaque: str, capacite_atk: str) -> int | None:
    """Retourne le nombre de coups tirés pour une attaque à coups multiples reconnue
    (voir ATTAQUES_COUPS_MULTIPLES), ou None si l'attaque n'en fait pas partie. Multi-
    Coups (Skill Link, Capumain) force TOUJOURS le maximum. Sinon, distribution
    officielle des vrais jeux pour du 2-5 coups : 35%/35%/15%/15% pour 2/3/4/5 coups."""
    if nom_attaque not in ATTAQUES_COUPS_MULTIPLES:
        return None
    mini, maxi = ATTAQUES_COUPS_MULTIPLES[nom_attaque]
    if mini == maxi:
        return mini
    info = CAPACITES.get(capacite_atk)
    if info and info.get("multi_coups"):
        return maxi
    tirage = random.random()
    if tirage < 0.35:
        return 2
    if tirage < 0.70:
        return 3
    if tirage < 0.85:
        return 4
    return 5


def puissance_selon_poids_cible(poids_kg: float) -> int:
    """Nœud Herbe (Grass Knot) / Balayage (Low Kick) — puissance selon le poids RÉEL
    (déjà ajusté par Métal Léger/Lourd si applicable) de la cible."""
    if poids_kg < 10:
        return 20
    if poids_kg < 25:
        return 40
    if poids_kg < 50:
        return 60
    if poids_kg < 100:
        return 80
    if poids_kg < 200:
        return 100
    return 120


def puissance_selon_ratio_poids(poids_atk_kg: float, poids_def_kg: float) -> int:
    """Tacle Lourd (Heavy Slam) / Tacle Feu (Heat Crash) — puissance selon le RATIO du
    poids de l'attaquant sur celui du défenseur (déjà ajustés par Métal Léger/Lourd)."""
    if poids_def_kg <= 0:
        return 40
    ratio = poids_atk_kg / poids_def_kg
    if ratio >= 5:
        return 120
    if ratio >= 4:
        return 100
    if ratio >= 3:
        return 80
    if ratio >= 2:
        return 60
    return 40


def boost_attaque_pulse(capacite: str, nom_attaque: str) -> float:
    """Méga Blaster (Mega Launcher, Gamblast) — +50% sur les attaques de la famille
    vibration/aura reconnues (voir ATTAQUES_PULSE)."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_pulse") and nom_attaque in ATTAQUES_PULSE:
        return 1.5
    return 1.0


def boost_attaque_poing(capacite: str, nom_attaque: str) -> float:
    """Poing de Fer (Meltan/Melmetal) — +20% sur les attaques de poing reconnues (voir
    ATTAQUES_POING)."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_poing") and nom_attaque in ATTAQUES_POING:
        return 1.2
    return 1.0



    """Fléau (Chongjian/Baojian/Dinglu/Yuyu) — -25% sur UNE stat précise de TOUS LES
    AUTRES Pokémon (jamais son propre porteur) tant qu'il est sur le terrain. Vérifié
    depuis le point de vue de l'ADVERSAIRE du porteur : si LUI a un Fléau visant cette
    stat précisément, elle est réduite de 25% chez qui la calcule — jamais chez le
    porteur lui-même (d'où capacite_adverse, jamais la propre capacité du Pokémon dont
    on calcule la stat)."""
    info = CAPACITES.get(capacite_adverse)
    if info and info.get("fleau_stat") == stat:
        return 0.75
    return 1.0


def boost_attaque_si_touche_par_type(capacite: str, type_recu: str) -> tuple | None:
    """Justicier (Cobalium/Terrakium/Viridium) — +1 Attaque quand touché par une attaque
    du type indiqué. Retourne (stat, delta) si applicable, sinon None."""
    info = CAPACITES.get(capacite)
    if info and info.get("boost_si_touche_par_type") == type_recu:
        return ("atk", 1)
    return None


def boost_vitesse_phobique(capacite: str, type_recu: str) -> bool:
    """Phobique (Rattled, Mordudor) — +1 Vitesse quand touché par une attaque
    Ténèbres/Spectre/Insecte. v1 : ne couvre PAS le déclenchement par Intimidation
    (celui-ci vit dans un point de code différent, l'entrée en jeu adverse, jamais
    câblé pour cette capacité précise faute de temps)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("phobique") and type_recu in ("tenebres", "spectre", "insecte"))


def boost_si_stat_baissee_par_adversaire(capacite: str) -> tuple | None:
    """Compétiteur (Artikodin de Galar) / Défiant (Électhor de Galar) — +2 sur une stat
    propre dès que N'IMPORTE LAQUELLE de ses stats est abaissée par l'adversaire (peu
    importe laquelle). Retourne (stat, delta) si applicable, sinon None."""
    info = CAPACITES.get(capacite)
    if info and "boost_si_stat_baissee" in info:
        return info["boost_si_stat_baissee"]
    return None


def declenche_ossature(capacite: str, pv_avant: int, pv_apres: int, pv_max: int) -> tuple | None:
    """Ossature (Berserk, Sulfura de Galar) — +1 Attaque Spéciale la première fois que
    les PV passent SOUS 50% suite à des dégâts (jamais si déjà sous 50% avant le coup,
    jamais si K.O.). Retourne (stat, delta) si applicable, sinon None."""
    info = CAPACITES.get(capacite)
    if not info or not info.get("boost_ossature"):
        return None
    seuil = pv_max / 2
    if pv_avant > seuil >= pv_apres > 0:
        return ("atk_spe", 1)
    return None


def declenche_porte_secours(capacite: str, pv_avant: int, pv_apres: int, pv_max: int) -> bool:
    """Porte de Secours (Emergency Exit, Sarmuraï) — se retire automatiquement du combat
    la première fois que les PV passent SOUS 50% suite à des dégâts (même seuil de
    franchissement qu'Ossature, mais déclenche un changement forcé plutôt qu'un boost —
    voir combat.py, qui réutilise le même mécanisme "switches_volontaires" que Change
    Éclair/Demi-Tour pour l'envoi du remplaçant). Jamais si déjà sous 50% avant le coup,
    jamais si K.O. (retirer un Pokémon déjà K.O. n'a pas de sens)."""
    info = CAPACITES.get(capacite)
    if not info or not info.get("porte_secours"):
        return False
    seuil = pv_max / 2
    return pv_avant > seuil >= pv_apres > 0


def chance_corps_maudit(capacite: str) -> float:
    """Corps Maudit (Cursed Body, Ectoplasma) — 30% de chance de désactiver (4 tours)
    l'attaque de l'adversaire qui vient de toucher ce Pokémon. Retourne la probabilité
    (0.0 si inapplicable) — la durée (4 tours) et le nom de l'attaque à désactiver sont
    gérés côté combat.py, cette fonction ne fait que détecter la capacité et sa chance."""
    info = CAPACITES.get(capacite)
    if info and info.get("chance_desactivation"):
        return info["chance_desactivation"]
    return 0.0


def a_stance_change(capacite: str) -> bool:
    """Stance Change (Exagide) — détecte la capacité. Le VRAI changement de forme (Lame
    à l'usage d'une attaque offensive, Bouclier à Bouclier Royal) et le swap de stats
    associé (Attaque<->Défense, Attaque Spé<->Défense Spé en forme Lame) se gèrent
    entièrement côté combat.py — centralisés dans infos_actif() pour le swap, et au
    moment du choix d'attaque pour le changement de forme lui-même."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("stance_change"))


def stats_echangees_si_lame(row: dict, en_forme_lame: bool) -> dict:
    """Applique le swap Attaque<->Défense / Attaque Spé<->Défense Spé de Stance Change
    si en_forme_lame est vrai — retourne une COPIE modifiée de row, ne mute jamais
    l'original (même principe de sécurité que pour Pixilate : ne jamais muter un objet
    potentiellement partagé/réutilisé ailleurs)."""
    if not en_forme_lame:
        return row
    return {**row, "atq": row["defe"], "defe": row["atq"], "atq_spe": row["def_spe"], "def_spe": row["atq_spe"]}


def boost_si_ko_inflige(capacite: str) -> tuple | None:
    """Hennissement Glacé (Blizzeval) / Hennissement Sépulcral (Spectreval) — +1 sur une
    stat propre quand ce Pokémon inflige lui-même le K.O. avec une attaque offensive.
    Retourne (stat, delta) si applicable, sinon None."""
    info = CAPACITES.get(capacite)
    if info and "boost_si_ko" in info:
        return info["boost_si_ko"]
    return None


def boost_si_ko_temoin(capacite: str) -> tuple | None:
    """Cœur d'Âme (Soul-Heart, Magearna) — +1 sur une stat propre à chaque fois qu'UN
    K.O. survient au combat, peu importe qui l'inflige (contrairement à Hennissement
    Glacé/Sépulcral, qui exige que CE Pokémon soit lui-même l'auteur du coup). v1 :
    ne couvre que les K.O. par coup direct, pas ceux par statut (poison/brûlure) en fin
    de tour. Retourne (stat, delta) si applicable, sinon None."""
    info = CAPACITES.get(capacite)
    if info and "boost_si_ko_temoin" in info:
        return info["boost_si_ko_temoin"]
    return None


def vole_objet_sur_coup(capacite: str) -> bool:
    """Magicien (Hoopa) — vole l'objet tenu de la cible dès qu'il la touche avec une
    attaque offensive, à condition de ne rien tenir lui-même. v1 : ne bloque pas le vol
    des objets liés à une transformation (Plaques, ROM, Orbes...) — voir
    ESPECES_A_NE_JAMAIS_VOLER dans combat.py pour cette exclusion précise, gérée côté
    appelant plutôt qu'ici."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("vole_objet"))


def vole_objet_au_contact(capacite: str, classe_attaque: str | None) -> bool:
    """Coloforce (Pickpocket, Sapereau) — sens INVERSE de Magicien : quand CE Pokémon
    (le défenseur) est touché au contact (approximé classe == physical, comme Peau
    Dure), vole l'objet tenu de L'ATTAQUANT plutôt que l'inverse. Mêmes conditions de
    validité (jamais s'il tient déjà quelque chose, jamais un objet de transformation)
    gérées côté appelant, comme pour Magicien."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("vole_objet_contact") and classe_attaque == "physical")


def tire_statut_pose_spore(capacite: str, classe_attaque: str | None) -> str | None:
    """Pose Spore (Effect Spore, Balignon/Spododo/Lampignon) — au contact, 30% de
    chance totale d'infliger à L'ATTAQUANT poison (9%)/paralysie (10%)/sommeil (11%),
    taux exacts officiels. Retourne le statut à infliger, ou None si rien ne se
    déclenche."""
    info = CAPACITES.get(capacite)
    if not info or not info.get("pose_spore") or classe_attaque != "physical":
        return None
    tirage = random.random()
    if tirage < 0.09:
        return "poison"
    if tirage < 0.19:
        return "paralysis"
    if tirage < 0.30:
        return "sleep"
    return None


def a_bajoues(capacite: str) -> bool:
    """Bajoues (Cheek Pouch, Dedenne) — soigne 33% des PV max EN PLUS après avoir
    consommé une Baie."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("bajoues"))


def a_delestage(capacite: str) -> bool:
    """Délestage (Unburden, Goupilou/Roublenard) — accélère fortement en consommant
    son objet tenu. v1 : approxime le vrai doublement hors-stage des vrais jeux par
    +2 stages de Vitesse (plus simple à intégrer au système de stages déjà existant,
    mais pas un x2 garanti si un adversaire baisse ensuite cette même stat)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("delestage"))


def a_coeur_soin(capacite: str) -> bool:
    """Cœur Soin (Healer, Fluvetin/Cocotine) — 30% de chance de guérir le statut d'un
    allié en fin de tour, avant les dégâts de brûlure/poison de ce même tour. Utile
    UNIQUEMENT en 2v2 (aucun allié en 1v1, jamais câblée côté combat.py 1v1)."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("coeur_soin"))


def ignore_capacite_defensive(capacite: str) -> bool:
    """Turboblaze (Reshiram) / Teravolt (Zekrom) — ignore la capacité DÉFENSIVE de
    l'adversaire lors du calcul de dégâts (immunité de type par capacité, Filtre/Prisme
    Armure, Bouclier de l'Ombre/Carapace Téra...). v1 : ne couvre que les 4 hooks
    "défensifs" identifiés dans combat.py au moment de l'implémentation — n'ignore
    JAMAIS les capacités réactives/de riposte de l'adversaire (Justicier,
    Compétiteur/Défiant, Ossature...), fidèle aux vrais jeux où Cassure Moule ne bloque
    que les capacités qui empêcheraient/réduiraient le coup, pas celles qui ripostent
    après qu'il ait porté."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("ignore_capacite_def"))


def ignore_protection(capacite: str) -> bool:
    """Poing Fantôme (Unseen Fist, Shifours) — ignore Abri/Protection de l'adversaire.
    v1 : bypass universel pour toutes les attaques de ce Pokémon, plutôt que de vérifier
    si l'attaque fait spécifiquement "contact" (cette notion n'existe pas encore dans
    les données d'attaques de ce jeu) — dans les vrais jeux, Poing Fantôme ne
    fonctionne QUE sur les attaques de contact."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("ignore_protection"))


def ignore_stage_adverse(capacite: str) -> bool:
    """Téméraire (Unaware, Cosmog) — ignore les changements de stats de L'AUTRE Pokémon
    lors du calcul de dégâts : ignore les boosts d'Attaque adverse quand il défend,
    ignore les boosts de Défense adverse quand il attaque. Ses PROPRES stages restent
    inchangés dans les deux cas."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("ignore_stage_adverse"))


def chance_poison_chaine_toxique(capacite: str) -> float:
    """Chaîne Toxique (Félicanis/Fortusimia/Favianos) — 30% de chance d'empoisonner la
    cible sur une attaque OFFENSIVE (jamais une attaque de statut). v1 : applique un
    poison classique (dégâts fixes), pas la version "gravement empoisonné" à dégâts
    croissants des vrais jeux — cette distinction n'existe pas encore dans ce système
    de statuts. Retourne la probabilité (0.0 si inapplicable)."""
    info = CAPACITES.get(capacite)
    if info and info.get("chance_poison_sur_coup"):
        return info["chance_poison_sur_coup"]
    return 0.0


def confond_aussi_si_poison(capacite: str) -> bool:
    """Marionnettiste Toxique (Pêchaminus) — quand ce Pokémon empoisonne sa cible avec
    UNE DE SES ATTAQUES, la cible devient aussi confuse. Réintégrée après séparation de
    la confusion du statut principal (voir combat_confusion) — auparavant impossible,
    la confusion et le poison partageaient le même emplacement unique de statut."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("confond_si_poison"))




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


def inverse_changements_stats(capacite: str) -> bool:
    """Corps Contraire (Contrary, Amovénus) — inverse TOUT changement de stat que subit
    ce Pokémon (une baisse devient une hausse et vice versa), peu importe la source :
    sa propre attaque (Léviathan le boosterait au lieu de le pénaliser), une attaque
    adverse (Rugissement le boosterait au lieu de l'affaiblir), ou une capacité
    déclenchée (Justicier/Compétiteur...). Centralisé dans
    database.modifier_boost — jamais vérifié directement ici en dehors de ce point
    unique."""
    info = CAPACITES.get(capacite)
    return bool(info and info.get("inverse_stats"))

