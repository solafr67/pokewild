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
    "tenacite": {
        "nom": "Ténacité", "emoji": "💪",
        "description": "+50% dégâts physiques quand ce Pokémon a un problème de statut (ignore aussi le malus d'Attaque de la Brûlure).",
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
    "carapace": {
        "nom": "Carapace", "emoji": "🐚",
        "description": "Ne peut jamais subir de coup critique.",
        "immunite_critique": True,
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
    "tension": {
        "nom": "Tension", "emoji": "😰",
        "description": "L'adversaire ne peut pas manger sa Baie de soin face à ce Pokémon.",
        "empeche_baie_adverse": True,
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
    "Aspicot": ["ecran_poudre"],
    "Astronelle": ["essaim", "fouille"],
    "Avaltout": ["gourmandise"],
    "Axoloto": ["absorb_eau"],
    "Axoloto de Paldea": ["absorb_eau", "poison_de_contact"],
    "Azumarill": ["herbivore", "peau_epaisse"],
    "Azurill": ["herbivore", "peau_epaisse"],
    "Aéromite": ["ecran_poudre", "lentiteintee"],
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
    "Corayon": ["agitation", "regenerescence", "vigilance"],
    "Corboss": ["insomnia"],
    "Cornèbre": ["farceur", "insomnia"],
    "Corvaillus": ["pression", "tension"],
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
    "Dynavolt": ["statik"],
    "Déflaisan": ["coeur_de_coq"],
    "Démanta": ["absorb_eau", "nage_rapide", "voile_eau"],
    "Démolosse": ["cache_flamme", "tension"],
    "Démétéros": ["force_sable"],
    "Efflèche": ["plante"],
    "Embrochet": ["nage_rapide"],
    "Embrylex": ["tenacite", "voile_sable"],
    "Emolga": ["statik"],
    "Empiflor": ["chlorophylle", "gourmandise"],
    "Engloutyran": ["boost_chimere"],
    "Entei": ["determination", "pression"],
    "Escargaume": ["carapace", "envelocape", "hydratation"],
    "Escroco": ["intimidation"],
    "Excelangue": ["tempo_perso"],
    "Famignol": ["technicien"],
    "Fantominus": ["levitation"],
    "Fantyrm": ["corps_sain"],
    "Farfaduvet": ["chlorophylle", "farceur"],
    "Farfuret": ["determination", "regard_vif"],
    "Farfuret d'Hisui": ["determination", "regard_vif"],
    "Farfurex": ["pression"],
    "Farigiraf": ["herbivore"],
    "Favianos": ["technicien"],
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
    "Florizarre": ["chlorophylle", "plante"],
    "Flotajou": ["gourmandise", "torrent"],
    "Flotillon": ["fouille"],
    "Flotoutan": ["gourmandise", "torrent"],
    "Flâmigator": ["brasier"],
    "Foretress": ["envelocape", "rustique"],
    "Forgelina": ["tempo_perso"],
    "Forgella": ["tempo_perso"],
    "Forgerette": ["tempo_perso"],
    "Fortusimia": ["fouille"],
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
    "Galopa": ["cache_flamme", "corps_ardent"],
    "Galvagla": ["absorb_volt", "statik"],
    "Galvagon": ["absorb_volt", "agitation"],
    "Galvaran": ["peau_seche", "voile_sable"],
    "Gambex": ["essaim", "lentiteintee"],
    "Gardevoir": ["synchro"],
    "Gaulet": ["regenerescence"],
    "Germignon": ["plante"],
    "Gigalithe": ["force_sable", "rustique", "sable_volant"],
    "Gigansel": ["corps_sain", "rustique"],
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
    "Grondogue": ["intimidation"],
    "Groret": ["gourmandise", "peau_epaisse", "tempo_perso"],
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
    "Kicklee": ["limber"],
    "Kirlia": ["synchro"],
    "Kokiyas": ["carapace", "envelocape"],
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
    "Meloetta": ["grace_sereine"],
    "Mentali": ["synchro"],
    "Mesmérella": ["fouille"],
    "Mew": ["synchro"],
    "Mewtwo": ["pression", "tension"],
    "Miaouss": ["technicien", "tension"],
    "Miaouss d'Alola": ["technicien"],
    "Miaouss de Galar": ["tension"],
    "Miascarade": ["plante"],
    "Migalos": ["essaim", "insomnia", "sniper"],
    "Mime Jr.": ["filtre", "technicien"],
    "Mimigal": ["essaim", "insomnia", "sniper"],
    "Mimitoss": ["lentiteintee", "oeil_compose"],
    "Minidraco": ["mue"],
    "Minisange": ["coeur_de_coq", "regard_vif", "tension"],
    "Minotaupe": ["force_sable"],
    "Miradar": ["regard_vif"],
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
    "Nucléos": ["envelocape", "regenerescence"],
    "Négapi": ["absorb_volt"],
    "Némélios": ["tension"],
    "Nénupiot": ["nage_rapide", "tempo_perso"],
    "Obalie": ["corps_gele", "peau_epaisse"],
    "Octillery": ["sniper"],
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
    "Pomdepik": ["envelocape", "rustique"],
    "Pomdorochi": ["regenerescence"],
    "Pomdramour": ["gourmandise"],
    "Pomdrapi": ["agitation", "gourmandise"],
    "Ponchien": ["intimidation", "querelleur"],
    "Ponchiot": ["esprit_vital"],
    "Pondralugon": ["rustique"],
    "Ponyta": ["cache_flamme", "corps_ardent"],
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
    "Rattata d'Alola": ["agitation", "gourmandise", "peau_epaisse"],
    "Rattatac": ["agitation", "tenacite"],
    "Rattatac d'Alola": ["agitation", "gourmandise", "peau_epaisse"],
    "Regice": ["corps_gele", "corps_sain"],
    "Regirock": ["corps_sain", "rustique"],
    "Registeel": ["corps_sain"],
    "Relicanth": ["nage_rapide", "rustique", "tete_de_roc"],
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
    "Saquedeneu": ["chlorophylle", "regenerescence"],
    "Scalpereur": ["pression"],
    "Scalpion": ["determination", "pression"],
    "Scalproie": ["determination", "pression"],
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
    "Sidérella": ["fouille"],
    "Simiabraz": ["brasier"],
    "Simularbre": ["rustique", "tete_de_roc"],
    "Skelénox": ["fouille", "levitation"],
    "Smogo": ["levitation"],
    "Smogogo": ["levitation"],
    "Smogogo de Galar": ["levitation"],
    "Snubbull": ["intimidation"],
    "Solaroc": ["levitation"],
    "Solochi": ["agitation"],
    "Sonistrelle": ["fouille"],
    "Soporifik": ["determination", "insomnia"],
    "Sorbouboul": ["alerte_neige", "corps_gele"],
    "Sorboul": ["corps_gele"],
    "Sorbébé": ["corps_gele"],
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
    "Suicune": ["determination", "pression"],
    "Sulfura": ["corps_ardent", "pression"],
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
    "Terhal": ["corps_sain"],
    "Terraiste": ["absorb_eau", "poison_de_contact"],
    "Tiboudet": ["determination", "tempo_perso"],
    "Tic": ["corps_sain"],
    "Tiplouf": ["torrent"],
    "Tissenboule": ["insomnia"],
    "Togedemaru": ["rustique"],
    "Togekiss": ["agitation", "grace_sereine"],
    "Togepi": ["agitation", "grace_sereine"],
    "Togetic": ["agitation", "grace_sereine"],
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
    "Yanma": ["fouille", "oeil_compose"],
    "Yanmega": ["fouille", "lentiteintee"],
    "Ymphect": ["mue"],
    "Zapétrel": ["absorb_volt"],
    "Zarbi": ["levitation"],
    "Zeraora": ["absorb_volt"],
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


def meteo_declenchee_a_entree(capacite: str) -> str | None:
    """Sécheresse/Averse/Sable Volant/Alerte Neige — météo déclenchée à l'entrée en jeu."""
    info = CAPACITES.get(capacite)
    if info and info.get("sur_entree"):
        return info.get("meteo_entree")
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
