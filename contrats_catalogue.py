"""Catalogue des Contrats — missions à la demande d'un PNJ, différentes des quêtes
jour/semaine classiques : un pool personnel de 3 contrats tirés au sort chaque jour
(recommence à zéro à chaque reset, pas de progression conservée d'un jour à l'autre),
récompense appliquée automatiquement dès l'objectif atteint (pas de bouton "réclamer"
séparé — l'esprit "contrat rempli = payé sur le champ").

Réutilise EXACTEMENT les mêmes événements que les quêtes classiques (voir
database/quetes_evenements.py::incrementer_progression_quete, qui fait déjà tourner
clan/défi-collectif/quête-principale/quêtes à chaque action de jeu — les contrats
s'ajoutent au même endroit, aucun nouveau point d'accroche à semer ailleurs dans le
code). "shiny" et "type" ont été ajoutés au contexte de capture (voir views.py) pour
permettre des contrats plus variés que les simples quêtes de rareté.

`filtre` : {cle: valeur} pour une correspondance exacte, {cle: [valeurs]} pour accepter
plusieurs valeurs (ex: rareté rare OU mieux). `poids` contrôle la fréquence de tirage
(un contrat difficile a un poids plus faible, donc plus rare/excitant à voir apparaître).
"""

CONTRATS_CATALOGUE = [
    # --- Capture générique ---
    {"id": "capture_5", "nom": "Capturer 5 Pokémon", "evenement": "capture", "cible": 5,
     "emoji": "🎯", "poids": 10, "recompense": {"dollars": 100, "xp": 40}},
    {"id": "capture_10", "nom": "Capturer 10 Pokémon", "evenement": "capture", "cible": 10,
     "emoji": "🎯", "poids": 6, "recompense": {"dollars": 190, "xp": 75}},
    {"id": "capture_15", "nom": "Capturer 15 Pokémon", "evenement": "capture", "cible": 15,
     "emoji": "🎯", "poids": 3, "recompense": {"dollars": 280, "xp": 110}},

    # --- Capture par rareté ---
    {"id": "capture_peu_commun_3", "nom": "Capturer 3 Pokémon Peu Communs (ou mieux)", "evenement": "capture", "cible": 3,
     "filtre": {"rarete": ["peu_commun", "rare", "hyper_rare", "legendaire"]}, "emoji": "🟢", "poids": 8,
     "recompense": {"dollars": 130, "xp": 50}},
    {"id": "capture_rare_1", "nom": "Capturer 1 Pokémon Rare (ou mieux)", "evenement": "capture", "cible": 1,
     "filtre": {"rarete": ["rare", "hyper_rare", "legendaire"]}, "emoji": "🔵", "poids": 5,
     "recompense": {"dollars": 160, "xp": 65}},
    {"id": "capture_hyper_rare_1", "nom": "Capturer 1 Pokémon Hyper Rare (ou mieux)", "evenement": "capture", "cible": 1,
     "filtre": {"rarete": ["hyper_rare", "legendaire"]}, "emoji": "🟣", "poids": 3,
     "recompense": {"dollars": 220, "xp": 90}},
    {"id": "capture_legendaire_1", "nom": "Capturer 1 Pokémon Légendaire", "evenement": "capture", "cible": 1,
     "filtre": {"rarete": "legendaire"}, "emoji": "🟠", "poids": 1,
     "recompense": {"dollars": 400, "xp": 160, "objet": ("superball", 3)}},

    # --- Capture shiny (rare, très gratifiant) ---
    {"id": "capture_shiny_1", "nom": "Capturer 1 Pokémon Shiny", "evenement": "capture", "cible": 1,
     "filtre": {"shiny": True}, "emoji": "✨", "poids": 1,
     "recompense": {"dollars": 350, "xp": 140, "objet": ("cristal_mutation", 1)}},

    # --- Capture par type ---
    {"id": "capture_type_feu_3", "nom": "Capturer 3 Pokémon de type Feu", "evenement": "capture", "cible": 3,
     "filtre": {"type": "feu"}, "emoji": "🔥", "poids": 4, "recompense": {"dollars": 140, "xp": 55}},
    {"id": "capture_type_eau_3", "nom": "Capturer 3 Pokémon de type Eau", "evenement": "capture", "cible": 3,
     "filtre": {"type": "eau"}, "emoji": "💧", "poids": 4, "recompense": {"dollars": 140, "xp": 55}},
    {"id": "capture_type_plante_3", "nom": "Capturer 3 Pokémon de type Plante", "evenement": "capture", "cible": 3,
     "filtre": {"type": "plante"}, "emoji": "🌿", "poids": 4, "recompense": {"dollars": 140, "xp": 55}},
    {"id": "capture_type_electrik_3", "nom": "Capturer 3 Pokémon de type Électrik", "evenement": "capture", "cible": 3,
     "filtre": {"type": "electrik"}, "emoji": "⚡", "poids": 4, "recompense": {"dollars": 140, "xp": 55}},
    {"id": "capture_type_vol_3", "nom": "Capturer 3 Pokémon de type Vol", "evenement": "capture", "cible": 3,
     "filtre": {"type": "vol"}, "emoji": "🪽", "poids": 4, "recompense": {"dollars": 140, "xp": 55}},

    # --- Combat ---
    {"id": "pvp_1", "nom": "Gagner 1 combat PvP", "evenement": "pvp_victoire", "cible": 1,
     "emoji": "🥊", "poids": 8, "recompense": {"dollars": 150, "xp": 60}},
    {"id": "pvp_3", "nom": "Gagner 3 combats PvP", "evenement": "pvp_victoire", "cible": 3,
     "emoji": "🥊", "poids": 4, "recompense": {"dollars": 320, "xp": 130}},
    {"id": "pve_1", "nom": "Battre 1 dresseur", "evenement": "pve_victoire", "cible": 1,
     "emoji": "🥾", "poids": 8, "recompense": {"dollars": 130, "xp": 50}},
    {"id": "pve_3", "nom": "Battre 3 dresseurs", "evenement": "pve_victoire", "cible": 3,
     "emoji": "🥾", "poids": 4, "recompense": {"dollars": 270, "xp": 110}},
    {"id": "raid_1", "nom": "Gagner 1 raid", "evenement": "raid_victoire", "cible": 1,
     "emoji": "⚔️", "poids": 6, "recompense": {"dollars": 160, "xp": 65}},

    # --- Exploration / PokéStop ---
    {"id": "exploration_2", "nom": "Récupérer 2 explorations", "evenement": "exploration_collectee", "cible": 2,
     "emoji": "🗺️", "poids": 7, "recompense": {"dollars": 120, "xp": 45}},
    {"id": "pokestop_1", "nom": "Faire tourner le PokéStop", "evenement": "pokestop", "cible": 1,
     "emoji": "🔵", "poids": 8, "recompense": {"dollars": 90, "xp": 35}},
]

CONTRATS_PAR_ID = {c["id"]: c for c in CONTRATS_CATALOGUE}
