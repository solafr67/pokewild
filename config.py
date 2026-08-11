# Configuration du bot
# ⚠️ Ne partage JAMAIS ton token publiquement (GitHub, Discord, etc.)
# En production, préfère charger ça depuis un fichier .env (voir python-dotenv)

import os
TOKEN = os.environ["DISCORD_TOKEN"]


def _id_env(nom_variable: str, valeur_defaut):
    """Permet de faire tourner une 2e instance du bot (serveur de test) sans toucher au
    code : chaque ID ci-dessous peut être surchargé par une variable d'environnement du
    même nom (ex: CHANNEL_SPAWN_CLASSIQUE_ID=123456789012345678 dans le .env du bot de
    test). Sans variable définie, on garde exactement le comportement actuel (l'ID de
    production codé en dur) — donc aucun changement pour le bot déjà en prod."""
    valeur_brute = os.environ.get(nom_variable)
    if valeur_brute is None:
        return valeur_defaut
    if valeur_brute == "" and valeur_defaut is None:
        return None
    return int(valeur_brute)


# --- IDs des channels (à remplir avec les vrais IDs de ton serveur) ---
CHANNEL_SPAWN_CLASSIQUE_ID = _id_env("CHANNEL_SPAWN_CLASSIQUE_ID", 1524432178694455346)
CHANNEL_SPAWN_VIP_ID = _id_env("CHANNEL_SPAWN_VIP_ID", 1524433167874920509)
CHANNEL_POKESTOP_ID = _id_env("CHANNEL_POKESTOP_ID", 1524432806912983241)
CHANNEL_BOUTIQUE_ID = _id_env("CHANNEL_BOUTIQUE_ID", 1524503716982689827)
CHANNEL_MAITRE_TYPES_ID = _id_env("CHANNEL_MAITRE_TYPES_ID", 1525581819901251726)  # channel #maitre-des-capacités
CHANNEL_EXPLORATION_ID = _id_env("CHANNEL_EXPLORATION_ID", 1525908138203807926)
CHANNEL_QUETES_ID = _id_env("CHANNEL_QUETES_ID", 1525970082264514730)
CHANNEL_AVENTURE_ID = _id_env("CHANNEL_AVENTURE_ID", 1526201523867226192)
CHANNEL_LABORATOIRE_ID = _id_env("CHANNEL_LABORATOIRE_ID", 1526365279855054952)  # Incubateur + Race, regroupés dans un seul channel
CHANNEL_LOGS_ID = _id_env("CHANNEL_LOGS_ID", 1527415638371598526)  # channel dédié aux logs bot + joueurs
CHANNEL_PING_RAID_ID = _id_env("CHANNEL_PING_RAID_ID", 1530858928731193374)  # message fixe pour (dés)activer le rôle de ping raid
CHANNEL_MARKETPLACE_ID = _id_env("CHANNEL_MARKETPLACE_ID", 1530862635967582208)  # annonces de vente de Pokémon entre joueurs
CHANNEL_ROGUELIKE_ID = _id_env("CHANNEL_ROGUELIKE_ID", 1530873209245663302)  # mini-jeu roguelike (catégorie mini-jeux, indépendant de l'économie principale)

# --- Roguelike (mini-jeu, salon dédié, aucune récompense liée au bot principal) ---
ROGUELIKE_NB_SALLES_MIN = 8
ROGUELIKE_NB_SALLES_MAX = 12
ROGUELIKE_TAILLE_EQUIPE_DEPART = 1  # 1 seul starter choisi au lancement (parmi 6 candidats)
ROGUELIKE_TAILLE_EQUIPE_MAX = 3  # nombre max de coéquipiers recrutables en cours de run
ROGUELIKE_NIVEAU_DEPART = 15
ROGUELIKE_NIVEAU_PAR_ETAGE = 2  # le niveau des ennemis (et donc la difficulté) monte avec l'étage
ROGUELIKE_SOIN_REPOS_POURCENT = 0.45

# --- Marketplace (vente à prix fixe entre joueurs, pas d'enchères pour l'instant) ---
MARKETPLACE_DUREE_ANNONCE_SECONDES = 7 * 86400  # 1 semaine avant disparition automatique
MARKETPLACE_PRIX_MIN = 1
MARKETPLACE_PRIX_MAX = 1_000_000  # garde-fou anti-erreur de saisie (pas une vraie limite de jeu)
MARKETPLACE_INTERVALLE_VERIFICATION_SECONDES = 15 * 60  # fréquence de la purge des annonces expirées

# --- Dresseurs PvE (combat contre une IA, PV liés au même pool persistant que les raids) ---
INTERVALLE_DRESSEUR = 20 * 60  # 20 min entre deux spawns (plus rare qu'un raid pour limiter le farming solo)
CHANCE_DUO_DRESSEUR = 0.2  # ~1 spawn sur 5 est un combat DUO 2v2 (voir combat_2v2.py) plutôt qu'un dresseur solo
DUREE_DISPONIBILITE_DRESSEUR = 10 * 60  # le dresseur repart si personne ne le défie dans ce délai
DRESSEUR_VARIANCE_PC = 0.15  # l'équipe adverse vise le PC cumulé du joueur, ± cette variance
DRESSEUR_FACTEUR_DOLLARS = 0.015  # récompense = PC cible de l'équipe adverse × ce facteur
DRESSEUR_FACTEUR_XP = 0.01  # baissés (avant 0.05 / 0.03) : à l'ancien taux, une équipe proche du plafond
# de PC, multipliée par le fait que chaque spawn est désormais accessible à tout le monde, dépassait le
# seuil de 600-900 PD/h déjà jugé abusif pour le PvP avant son propre nerf anti-collusion.
CHANNEL_PROFIL_ID = _id_env("CHANNEL_PROFIL_ID", 1524512674942156851)
CHANNEL_CLASSEMENT_ID = _id_env("CHANNEL_CLASSEMENT_ID", 1524802617455284404)

# --- Rythme des spawns (en secondes) ---
INTERVALLE_SPAWN_CLASSIQUE = 60
INTERVALLE_SPAWN_VIP = 45

# --- Disparition d'un spawn non capturé (en secondes) ---
DUREE_AVANT_DISPARITION = 180  # 3 minutes (relevé de 45s)

# --- PokéStop ---
COOLDOWN_POKESTOP = 300  # 5 minutes, en secondes

# --- Rôle VIP (pour vérifier l'accès si besoin dans le code) ---
ROLE_VIP_ID = _id_env("ROLE_VIP_ID", 1524443826956271838)
ROLE_PING_RAID_ID = _id_env("ROLE_PING_RAID_ID", 1525883524396355675)

# --- Serveur de test (pour synchroniser les commandes instantanément dessus) ---
GUILD_ID = _id_env("GUILD_ID", 1496856137583296562)

# --- Shiny ---
CHANCE_SHINY_BASE = 1 / 200  # ~0.5% de base, indépendant pour chaque joueur à chaque tentative

# --- Boutique (Poké Dollars) ---
# Prix relevés légèrement (2e passe d'équilibrage éco, en miroir du nerf d'exploration) —
# la Master Ball ne bouge pas : déjà calibrée comme objectif de fin de partie.
PRIX_BALLS = {
    "pokeball": 18,
    "superball": 40,
    "hyperball": 80,
    "masterball": 2500,
}

# --- Expérience et niveau de dresseur ---
XP_PAR_RARETE = {
    "commun": 5,
    "peu_commun": 10,
    "rare": 20,
    "hyper_rare": 35,
    "legendaire": 50,
}
XP_BONUS_SHINY = 20
XP_POKESTOP = 5

# --- Heure de pointe PokéStop : un créneau de 30 min tiré aléatoirement chaque jour
# entre 9h et 23h (heure de Paris), pendant lequel les récompenses sont meilleures.
DUREE_HEURE_DE_POINTE_POKESTOP = 30 * 60
HEURE_DEBUT_FENETRE_POINTE = 9
HEURE_FIN_FENETRE_POINTE = 23
MULTIPLICATEUR_HEURE_DE_POINTE = 2.0  # Poké Dollars et quantités d'objets doublés

# --- Niveau par Pokémon (coexiste avec le PC : le PC reste la mesure de potentiel/IV,
# le niveau devient la progression via le jeu). Seuls les Pokémon de l'équipe de combat
# active gagnent cette XP (capture, PokéStop...) — équipe vide = XP perdue.
NIVEAU_MAX_PAR_RARETE = {
    "commun": 100,
    "peu_commun": 100,
    "rare": 100,
    "hyper_rare": 100,
    "legendaire": 100,
}
# Fourchette de niveau (min, max) tirée aléatoirement à l'apparition d'un Pokémon
# sauvage, selon sa rareté — affiché sur la carte de spawn au même titre que le PC.
NIVEAU_SPAWN_PAR_RARETE = {
    "commun": (1, 15),
    "peu_commun": (10, 30),
    "rare": (25, 45),
    "hyper_rare": (35, 55),
    "legendaire": (50, 70),
}
# XP donnée à CHAQUE Pokémon de l'équipe active (pas divisée entre eux) selon la rareté
# du Pokémon capturé, et à chaque tirage PokéStop.
XP_POKEMON_PAR_RARETE = {
    "commun": 15,
    "peu_commun": 30,
    "rare": 60,
    "hyper_rare": 100,
    "legendaire": 150,
}
XP_POKEMON_POKESTOP = 20
# XP cumulée pour atteindre un niveau N = COEFFICIENT * (N-1)^2 — courbe quadratique.
# Avec ce coefficient, niveau 100 demande environ 245 000 XP cumulée (~1600 captures
# "communes" à répartir sur 6 emplacements d'équipe). Un seul chiffre à modifier pour
# retendre toute la courbe si le rythme ne convient pas.
COEFFICIENT_COURBE_NIVEAU_POKEMON = 25

# --- Mini-jeu Défi Base Stat (pur fun, aucune récompense) ---
DEFI_STATS_NB_ROUNDS = 5

# --- Quiz communautaire multi-thèmes (Qui est-ce / Anagramme / Quiz de types / Trivia) ---
CHANNEL_QUIZ_ID = _id_env("CHANNEL_QUIZ_ID", 1528155287213572306)
CHANNEL_WIKI_ID = _id_env("CHANNEL_WIKI_ID", 1528849699812151447)
QUIZ_TIMEOUT_QUESTION = 60  # secondes avant de révéler la réponse si personne ne trouve
QUIZ_DELAI_PROCHAINE_QUESTION = 5  # pause entre deux questions

# --- Passe saisonnier ---
SAISON_DUREE_JOURS = 30
SAISON_NB_PALIERS = 30
SAISON_XP_PAR_PALIER = 400  # points de saison requis par palier (linéaire, simple à suivre)
SAISON_RATIO_XP = 1.0  # 1 XP dresseur gagnée (partout dans le jeu) = ce nombre de points de saison

# --- Parrainage ---
PARRAINAGE_PALIER = 3  # récompense tous les X invitations réussies (3, 6, 9...)
PARRAINAGE_DELAI_JOURS = 7  # le filleul doit rester au moins ce délai avant que ça compte (anti-abus)
PARRAINAGE_RECOMPENSE_DOLLARS = 150
PARRAINAGE_RECOMPENSE_BALLS = [("superball", 3), ("hyperball", 1)]

# --- Bonus des boosters du serveur Discord (argent/xp/shiny uniquement, pas capture) ---
MULTIPLICATEUR_BOOSTER_SERVEUR = {"argent": 1.15, "xp": 1.15, "shiny": 1.5}

# --- Draft PvP : niveau standardisé pour tous les Pokémon draftés (compétition équitable,
# indépendante de la collection/progression de chacun) ---
DRAFT_NIVEAU = 50
DRAFT_TAILLE_POOL = 8
DRAFT_PICKS_PAR_JOUEUR = 3

# --- Arène (PvE) : spawn à intervalle fixe dans le channel Aventure, 3 combats
# (2 Apprentis + le Champion), type tiré au hasard à chaque spawn. Plusieurs joueurs
# peuvent tenter la même arène en parallèle, chacun son run indépendant. Une défaite
# met fin au run entier (retenter au prochain spawn).
CHANNEL_ARENE_ID = CHANNEL_AVENTURE_ID
ARENE_INTERVALLE_HEURES = 2
ARENE_DUREE_DISPONIBLE_MINUTES = 20  # fenêtre pour démarrer un run après le spawn
ARENE_TAILLE_APPRENTI_1 = 3
ARENE_TAILLE_APPRENTI_2 = 4
ARENE_TAILLE_CHAMPION = 5
ARENE_MULTIPLICATEUR_CHAMPION = 1.15  # comme Gladio : légèrement plus fort que le joueur
ARENE_RARETES_CHAMPION = {"rare", "hyper_rare", "legendaire"}
ARENE_RECOMPENSE_DOLLARS_APPRENTI = (80, 150)
ARENE_RECOMPENSE_DOLLARS_CHAMPION = (250, 400)
# Dégression journalière des Poké Dollars d'arène par RUN COMPLÉTÉ (champion battu) :
# 1er run du jour plein tarif, puis ×0.6, puis ×0.35 pour tous les suivants. Badges, XP
# et plaisir de jeu non concernés — seule la récompense économique est contenue.
ARENE_MULTIPLICATEURS_REPETITION_JOUR = [1.0, 0.6, 0.35]

# Image de transition affichée entre le 2e Apprenti et le Champion (style "VS" des jeux).
# Clé = type d'arène (mêmes clés que EMOJI_TYPES) ; les 18 types sont couverts —
# ARENE_IMAGE_CHAMPION_DEFAUT reste le filet de sécurité si une clé venait à manquer.
ARENE_IMAGES_CHAMPION = {
    "normal":   "https://www.pokepedia.fr/images/9/9f/VS_Tcheren_NB.png",
    "feu":      "https://www.pokepedia.fr/images/a/a2/VS_Auguste_HGSS.png",
    "eau":      "https://www.pokepedia.fr/images/e/ef/Sprite_Donna_EB.png",
    "electrik": "https://www.pokepedia.fr/images/8/8e/VS_Tanguy_Pt.png",
    "plante":   "https://www.pokepedia.fr/images/5/56/VS_Flo_Pt.png",
    "glace":    "https://www.pokepedia.fr/images/7/77/VS_Watson_NB.png",
    "combat":   "https://www.pokepedia.fr/images/d/d2/Sprite_Fa%C3%AFza_EB.png",
    "poison":   "https://www.pokepedia.fr/images/c/c6/VS_Koga_HGSS.png",
    "sol":      "https://www.pokepedia.fr/images/8/84/VS_Bardane_NB.png",
    "vol":      "https://www.pokepedia.fr/images/f/f5/VS_Carolina_NB.png",
    "psy":      "https://www.pokepedia.fr/images/5/5b/VS_Morgane_HGSS.png",
    "insecte":  "https://www.pokepedia.fr/images/3/31/VS_Hector_HGSS.png",
    "roche":    "https://www.pokepedia.fr/images/1/10/VS_Pierrick_Pt.png",
    "spectre":  "https://www.pokepedia.fr/images/0/0d/Sprite_Mystimaniac_XY.png",
    "dragon":   "https://www.pokepedia.fr/images/6/60/VS_Cynthia_Pt.png",
    "tenebres": "https://www.pokepedia.fr/images/3/38/VS_Marion_HGSS.png",
    "acier":    "https://www.pokepedia.fr/images/6/6a/Sprite_Thym%C3%A9o_XY.png",
    "fee":      "https://www.pokepedia.fr/images/a/a2/Sprite_Val%C3%A9riane_XY.png",
}
ARENE_IMAGE_CHAMPION_DEFAUT = "https://www.pokepedia.fr/images/8/8e/VS_Tanguy_Pt.png"

# --- Repaires de méchants (Team Rocket, Aqua, Magma, Galactic...) — même principe que
# l'arène, spawn dans le même channel que les dresseurs (CHANNEL_AVENTURE_ID), voir
# repaires.py. "types_theme" alimente le pool de Pokémon des combats. "categorie_bonus"
# détermine à QUELLE catégorie de multiplicateur_boost (capture/shiny/argent/xp) le
# badge de cette équipe donne un bonus permanent une fois débloqué. Noms et images des
# chefs vérifiés (Poképédia) : Arthur = nom FR d'Archie (Team Aqua), Max = nom FR de
# Maxie (Team Magma), Hélio = nom FR de Cyrus (Team Galactic).
EQUIPES_MECHANTES = {
    "Team Rocket": {
        "types_theme": ["poison", "tenebres"],
        "emoji": "🌹",
        "chef": "Giovanni",
        "image_chef": "https://www.pokepedia.fr/images/d/d5/VS_Giovanni_%28Classique%29_PM.png",
        "categorie_bonus": "argent",
    },
    "Team Aqua": {
        "types_theme": ["eau"],
        "emoji": "🌊",
        "chef": "Arthur",
        "image_chef": "https://www.pokepedia.fr/images/2/2d/Sprite_Arthur_ROSA.png",
        "categorie_bonus": "capture",
    },
    "Team Magma": {
        "types_theme": ["feu", "sol"],
        "emoji": "🌋",
        "chef": "Max",
        "image_chef": "https://www.pokepedia.fr/images/6/61/Sprite_Max_ROSA.png",
        "categorie_bonus": "shiny",
    },
    "Team Galactic": {
        "types_theme": ["poison", "acier", "spectre"],
        "emoji": "🌌",
        "chef": "Hélio",
        "image_chef": "https://www.pokepedia.fr/images/1/1e/Sprite_H%C3%A9lio_USUL.png",
        "categorie_bonus": "xp",
    },
}

CHANNEL_REPAIRE_ID = CHANNEL_AVENTURE_ID  # même channel que les dresseurs/l'arène, plus simple
REPAIRE_INTERVALLE_HEURES = 3
REPAIRE_DUREE_DISPONIBLE_MINUTES = 20
REPAIRE_TAILLE_SBIRE_1 = 3
REPAIRE_TAILLE_SBIRE_2 = 4
REPAIRE_TAILLE_BOSS = 5
REPAIRE_MULTIPLICATEUR_BOSS = 1.15
REPAIRE_RARETES_BOSS = {"rare", "hyper_rare", "legendaire"}
REPAIRE_RECOMPENSE_DOLLARS_SBIRE = (80, 150)
REPAIRE_RECOMPENSE_DOLLARS_BOSS = (250, 400)
REPAIRE_MULTIPLICATEURS_REPETITION_JOUR = [1.0, 0.6, 0.35]
REPAIRE_BONUS_PAR_BADGE = 0.03
REPAIRE_CHANCE_OBJET_PAR_OBJET = 0.02

# Temps laissé à un joueur pour choisir son prochain Pokémon quand le sien tombe K.O.
# en combat (dresseur/Arène/Gladio/PvP) — au-delà, le premier vivant est envoyé
# automatiquement (anti-AFK, même durée qu'un tour de combat).
CHOIX_KO_DUREE_SECONDES = 45
ARENE_BONUS_DEGATS_PAR_BADGE = 0.03  # +3% de dégâts pour les attaques du type d'un badge obtenu

# --- Rival (Gladio) ---
GLADIO_JOURS_PAR_PALIER_DECAY = 14  # perd 1 palier de familiarité tous les X jours d'inactivité
GLADIO_COOLDOWN_DEFI = 24 * 3600  # un défi contre Gladio par jour et par joueur
GLADIO_RECOMPENSE_MIN = 400  # récompense fixe en Poké Dollars (une fois par jour, indépendante du PC)
GLADIO_RECOMPENSE_MAX = 600

# Facteur purement cosmétique appliqué au PC affiché (calculer_pc_derive) pour rester
# dans un ordre de grandeur proche de l'ancien système (pré-refonte stats/combat). N'a
# aucun effet sur le combat — juste sur le nombre affiché. Ajustable si besoin après avoir
# vu quelques exemples en jeu (~3.4x rapprochait un Zekrom niveau 61 de son ancien PC).
PC_MULTIPLICATEUR_AFFICHAGE = 3.4

# --- CT au Maître des Types : coût en Poké Dollars pour apprendre une attaque que le
# Pokémon n'a pas encore débloquée par son niveau (ou qui ne se débloque jamais par
# niveau — CT/tuteur/œuf uniquement dans les vrais jeux). Une attaque déjà débloquée par
# le niveau reste gratuite à équiper, comme dans les jeux (le Pokémon la connaît déjà).
PRIX_CT_STATUT = 100  # attaque sans dégâts (statut, buff/debuff...)
# Paliers utiles baissés de ~25-30% (équilibrage éco : builder une équipe de 6 coûtait
# 1500-3000 PD d'entrée de jeu) — le palier 120+ reste cher : c'est le luxe de fin de partie.
PRIX_CT_PAR_PUISSANCE = {  # puissance minimale -> prix (le seuil le plus haut atteint s'applique)
    0: 80,
    40: 150,
    70: 250,
    90: 450,
    120: 900,
}

# --- Stockage des Pokémon et objets (extensible en boutique) ---
LIMITE_STOCKAGE_POKEMON_BASE = 300
LIMITE_STOCKAGE_OBJETS_BASE = 50

EXTENSION_STOCKAGE_POKEMON = 20  # slots ajoutés PAR ACHAT
PRIX_EXTENSION_STOCKAGE_POKEMON = 450  # relevé légèrement (2e passe d'équilibrage, ~22 PD/slot)

EXTENSION_STOCKAGE_OBJETS = 20  # slots ajoutés PAR ACHAT
PRIX_EXTENSION_STOCKAGE_OBJETS = 450  # relevé légèrement (2e passe d'équilibrage, ~22 PD/slot)

RECOMPENSE_RELACHER = 5  # fixe, peu importe la rareté

# --- PC des Pokémon sauvages (façon Pokémon Go : pas de niveau, juste stats + rareté + variance) ---
# Multiplicateurs calibrés pour qu'un légendaire touche RAREMENT le plafond (avant : ~56% du
# temps, ce qui donnait l'impression d'un PC max garanti). Avec ces valeurs, même Arceus
# (meilleur total de stats du jeu) plafonne autour de 3600 sur un excellent tirage, loin du cap.
MULTIPLICATEUR_PC_PAR_RARETE = {
    "commun": 1.0,
    "peu_commun": 1.8,
    "rare": 2.6,
    "hyper_rare": 3.3,
    "legendaire": 4.0,
}
PC_VARIANCE_MIN = 0.75  # plage élargie (avant 0.85-1.15) pour un vrai étalement des tirages
PC_VARIANCE_MAX = 1.25
PC_MAXIMUM = 4000  # relevé (avant 3000) — sert de garde-fou, quasiment jamais atteint désormais

# --- Couleurs des équipes (hex, utilisées pour les rôles Discord) ---
COULEURS_EQUIPES = {
    "Bleu": 0x3498DB,
    "Rouge": 0xE74C3C,
    "Jaune": 0xF1C40F,
}

EMOJI_EQUIPES = {
    "Bleu": "<:26181teammystic:1524813500633845811>",
    "Rouge": "<:39101teamvalor:1524813534717018222>",
    "Jaune": "<:17720teaminstinct:1524813430563934340>",
}

# IDs des VRAIS rôles Discord déjà créés sur le serveur pour chaque clan — recherche par
# ID plutôt que par nom (voir profil.py VueChoixClan.choisir), pour ne jamais dépendre du
# nom exact du rôle (qui peut différer légèrement, ex: avec un emoji devant).
ROLES_EQUIPES_ID = {
    "Bleu": _id_env("ROLE_EQUIPE_BLEU_ID", 1524800469216661518),
    "Jaune": _id_env("ROLE_EQUIPE_JAUNE_ID", 1525177640242122783),
    "Rouge": _id_env("ROLE_EQUIPE_ROUGE_ID", 1525198697703411913),
}

# --- Objectif hebdomadaire de clan (coopératif au sein d'une équipe, compétitif entre
# les 3) — voir database.obtenir_objectif_semaine_actif / ajouter_contribution_clan.
# Chaque tuple = (type, cible). "capture" = 1 point par capture ; "combat" = 2 points par
# victoire (PvP, dresseur, ou raid). Un nouveau tirage a lieu automatiquement chaque lundi.
OBJECTIFS_CLAN_POSSIBLES = [
    ("capture", 3000), ("capture", 5000), ("capture", 8000),
    ("combat", 500), ("combat", 900), ("combat", 1500),
]
# Récompense (Poké Dollars) versée à CHAQUE membre de l'équipe dès qu'elle atteint
# l'objectif — bonus supplémentaire pour la toute première équipe des 3 à y arriver.
CLAN_OBJECTIF_RECOMPENSE_BASE = 150
CLAN_OBJECTIF_BONUS_PREMIER = 150

# --- Grille de titres de contribution au clan (rang personnel, remis à 0 si changement
# d'équipe — voir database.clan_contribution).
TITRES_CONTRIBUTION_CLAN = [
    (0, "Recrue", "🔹"),
    (100, "Membre", "🔸"),
    (300, "Vétéran", "🥈"),
    (700, "Élite", "🥇"),
    (1500, "Champion", "💎"),
    (3000, "Légende de l'équipe", "👑"),
]

# Délai minimum entre deux changements gratuits de clan
COOLDOWN_CHANGEMENT_EQUIPE = 7 * 24 * 3600  # 1 semaine, en secondes

# --- Classements ---
INTERVALLE_CLASSEMENT = 3600  # 1 heure, en secondes
TAILLE_TOP_CLASSEMENT = 10

# --- Raids ---
# Les raids apparaissent directement dans les channels de spawn (classique/VIP),
# pas de channel dédié. Vérification toutes les 15 min.
INTERVALLE_RAID = 15 * 60

# Correspondance étoiles <-> rareté (1★ = commun, jusqu'à 5★ = légendaire)
ETOILES_PAR_RARETE = {
    "commun": 1,
    "peu_commun": 2,
    "rare": 3,
    "hyper_rare": 4,
    "legendaire": 5,
}
RARETE_PAR_ETOILES = {v: k for k, v in ETOILES_PAR_RARETE.items()}

# Poids relatifs de chaque palier d'étoiles QUAND un raid se déclenche
# (plus d'étoiles = plus rare)
POIDS_ETOILES_RAID = {1: 40, 2: 25, 3: 20, 4: 10, 5: 5}

# Points de vie du boss selon son nombre d'étoiles (plus d'étoiles = plus long à vaincre)
# PV de base pour un raid affronté SOLO (1 joueur dans le lobby). Chaque joueur
# supplémentaire dans le lobby au moment où le combat démarre augmente les PV réels
# du boss d'autant de fois FACTEUR_PV_PAR_JOUEUR_SUPPLEMENTAIRE. Un 1★/2★ reste donc
# tout à fait solo-able si peu de monde s'est présenté, mais un raid avec beaucoup
# de participants devient un vrai défi collectif.
PV_BASE_PAR_ETOILE = {1: 8000, 2: 16000, 3: 35000, 4: 70000, 5: 110000}
FACTEUR_PV_PAR_JOUEUR_SUPPLEMENTAIRE = 0.35  # réduit : le facteur 0.6 rendait les gros raids impossibles même en groupe

DUREE_SALLE_ATTENTE_RAID = 180  # secondes avant que le combat ne démarre vraiment (relevé de 90s à 180s)
DUREE_RAID_MINUTES = 15  # temps de combat avant que le boss ne s'échappe si non vaincu
INTERVALLE_TICK_COMBAT_RAID = 5  # secondes entre chaque attaque automatique de tous les participants

DEGATS_VARIANCE_MIN = 0.8
DEGATS_VARIANCE_MAX = 1.2
DEGATS_DIVISEUR_RAID = 12  # conservé pour compat historique, plus utilisé par calculer_degats (voir FACTEUR_DEGATS_RAID)
FACTEUR_DEGATS_RAID = 1.1  # dégâts d'un tick = (Atq + Atq Spé)/2 × ce facteur — à retendre après test en jeu
# Riposte du boss = pourcentage des PV MAX réels du Pokémon touché (pas un nombre fixe) :
# reste cohérent quelle que soit l'échelle de PV en vigueur (IV/niveau réels désormais).
# RE-CALIBRÉ (2e passe d'équilibrage) : la division par ~2 de la session précédente avait
# rendu les raids trop faciles à l'usage — un 3★ se terminait souvent sans qu'aucune
# potion ne soit nécessaire. Remontée ciblée : 1★/2★ restent quasi anodins (raids
# d'initiation, jamais de soin obligatoire), 3★ doit typiquement coûter au moins UNE
# potion de soin sur un clear normal, 4★/5★ montent en vraie difficulté (plusieurs
# potions, un vrai effort de groupe) — sans revenir à l'excès d'avant (~198% cumulé sur
# la durée max d'un 3★, qui rendait le soin obligatoire ET plus cher que la récompense).
RIPOSTE_POURCENT_PAR_ETOILE = {1: 0.0028, 2: 0.0055, 3: 0.013, 4: 0.021, 5: 0.033}

# Nombre d'Honor Ball reçues par CHAQUE participant à la victoire (peu importe les dégâts infligés)
# Chaque participant a le même nombre de tentatives de capture (Honor Ball), peu importe
# le palier d'étoiles — seul le TAUX DE RÉUSSITE varie selon la rareté (voir TAUX_CAPTURE
# dans pokemon_data.py, clé "honorball"). Ces tentatives ne sont PAS stockées dans
# l'inventaire général : elles n'existent que pour ce raid précis.
TENTATIVES_CAPTURE_RAID = 5
DUREE_AFFICHAGE_VICTOIRE_RAID = 180  # 3 minutes avant suppression automatique du message de résumé

# Récompenses Poké Dollars / XP par participant, selon le nombre d'étoiles du raid vaincu
# Relevées une 1ère fois, puis réajustées ici (2e passe) pour les paliers 3-5★ dont la
# riposte remonte : la récompense doit rester nettement positive même après 1-3 potions
# de soin, sans pour autant annuler la difficulté qu'on vient de réintroduire.
DOLLARS_RAID_PAR_ETOILE = {1: 75, 2: 150, 3: 280, 4: 450, 5: 650}

# --- PV des Pokémon personnels (utilisés en raid) ---
FACTEUR_PV_PAR_PC = 0.8  # PV max = PC × ce facteur (raids uniquement — ticks automatiques, gros PV OK)

# --- PvP : système séparé des raids ---
# Un combat PvP à ~45s par tour doit se résoudre en peu de tours (3-5 par Pokémon à
# puissance égale, comme les vrais jeux Pokémon), d'où des PV réduits par rapport aux raids.
FACTEUR_PV_COMBAT_PVP = 0.4  # PV en combat PvP = PC × ce facteur

# Dégâts que le boss inflige en retour à CHAQUE participant, à chaque tick, répartis
# entre ses Pokémon d'équipe encore en vie (0 PV = K.O., ne contribue plus aux dégâts
# jusqu'à un soin).
DEGATS_BOSS_PAR_ETOILE = {1: 40, 2: 90, 3: 180, 4: 350, 5: 650}  # OBSOLÈTE — remplacé par RIPOSTE_POURCENT_PAR_ETOILE

# --- Objets de soin (boutique) ---
# Prix relevés légèrement (2e passe d'équilibrage éco) — restent couverts par une
# récompense de raid 3-5★ typique, mais pèsent un peu plus sur le budget quotidien.
PRIX_SOINS = {
    "potion": 24,
    "superpotion": 65,
    "hyperpotion": 160,
    "totalsoin": 90,
}

# --- Transformateur (Laboratoire) : convertit 10 objets d'un palier en 1 du palier
# supérieur. Master Ball et Total Soin sont volontairement hors chaîne — uniquement
# achetables en boutique, jamais obtenables par transformation. {type_source: (type_cible, quantite_requise)}
CHAINES_TRANSFORMATION = {
    "pokeball": ("superball", 10),
    "superball": ("hyperball", 10),
    "potion": ("superpotion", 10),
    "superpotion": ("hyperpotion", 10),
}

# --- Objets tenus de combat (boutique — voir capacites.OBJETS_TENUS pour les effets) ---
# Analyse : ces objets sont des équipements PERMANENTS (jamais consommés hors combat, même
# les baies/Ceinture Force qui ne se "grillent" que pour LE combat en cours — voir
# capacites.py) — donc à comparer à un investissement durable (extension de stockage à
# 450 PD) plutôt qu'à un consommable à usage unique (potion). Prix échelonnés par
# puissance : baies de statut/PV (soin automatique gratuit à VIE à chaque combat) <
# bonus passifs simples (+30% une stat, sans contrepartie) < Reste/Ceinture Force
# (sustain/sécurité plus fortes) < Objets Choix et Orbes (+50%/+30% dégâts, avec un vrai
# revers : verrouillage d'attaque ou recul) — les plus chers, au niveau d'une grosse
# récompense de raid 4-5★, jamais au niveau de la Master Ball.
PRIX_OBJETS_TENUS = {
    # Baies de statut (guérison automatique d'1 statut précis, à chaque combat)
    "baie_pecha": 180, "baie_cheri": 180, "baie_kika": 180,
    "baie_lombre": 180, "baie_rawst": 180, "baie_persim": 180,
    # Baies de PV (soin automatique sous un seuil de PV, à chaque combat)
    "baie_oran": 150, "baie_sitrus": 220,
    # Bonus passifs simples (+30% une stat, sans contrepartie)
    "lunettes_cerema": 300, "ceinture_musclor": 300, "chaussures_agiles": 300,
    "carapace_dure": 300, "ecaille_lumiere": 300,
    # Sustain / sécurité plus marquée
    "reste": 350, "ceinture_force": 400,
    # Objets Choix (+50% une stat, mais verrouillage de l'attaque)
    "bandeau_choix": 500, "specs_choix": 500, "bandana_choix": 500,
    # Orbes (+30% dégâts, mais recul à chaque attaque) — le haut de gamme
    "orbe_vie": 550, "orbe_feu": 550,
}

SOIN_POURCENT = {
    "potion": 0.20,       # soigne 20% des PV max
    "superpotion": 0.40,  # soigne 40% des PV max
    "hyperpotion": 1.0,   # soin complet
}

# Limite d'utilisations de potions de SOIN (PV) par combat PvP/dresseur, par joueur — le
# Total Soin n'est PAS concerné (il ne rend pas de PV, juste les statuts, donc pas de vraie
# stratégie de stall dessus). Sans cette limite, spammer les potions permettait d'enchaîner
# les tours de heal en boucle contre les statuts adverses (poison/brûlure...) au lieu d'un
# vrai combat.
LIMITE_POTIONS_SOIN_COMBAT = 3

# --- Total Soin : soigne toutes les altérations de statut (brûlure, poison, paralysie,
# sommeil, gel, confusion) en combat. Ne soigne pas les PV. Fait maintenant partie du tirage
# "Potions" du PokéStop (voir POTIONS_POIDS_POKESTOP plus bas), au même titre que les autres.
POTIONS_POIDS_POKESTOP = {"potion": 0.50, "superpotion": 0.28, "hyperpotion": 0.10, "totalsoin": 0.07}
# Le reste (5%) ne donne rien ce tirage-ci.

# --- Cristal de Mutation au PokéStop : tirage "Objet rare" indépendant, très bas exprès —
# le Cristal reste avant tout un objet d'Exploration (5-60%) et de quête hebdo (15%), qui
# demandent un vrai investissement ; le PokéStop se tourne toutes les 5 minutes, donc même
# une petite proba ici représente un flux constant s'il n'est pas gardé faible.
CHANCE_CRISTAL_POKESTOP = 0.01  # 1%

# --- Cristal/Œuf en récompense de capture (~20x plus bas que le PokéStop) ---
# Une capture peut arriver bien plus souvent qu'un tirage PokéStop (limité à 1/5min/joueur) —
# sans ce facteur d'échelle, l'offre totale de Cristaux/Œufs (surtout Légendaires) exploserait
# largement au-delà de ce qui a été calibré comme "très très rare". Sert aussi à donner un
# objectif aux joueurs ayant déjà fini le Pokédex : capturer des doublons reste utile.
CHANCE_CRISTAL_CAPTURE = 0.0005  # 0.05%
OEUF_POIDS_CAPTURE = {
    "commun": 0.0025,
    "peu_commun": 0.00125,
    "rare": 0.0004,
    "hyper_rare": 0.000075,
    "legendaire": 0.000025,  # 1 capture sur 40 000 en moyenne
}

# --- Boosts temporaires ---
# Ne sont PLUS achetables en boutique (retiré : cumulé avec les bonus permanents de Race,
# ça devenait trop fort). Le mécanisme reste disponible pour les admins via /give-boost
# (récompense d'événement ponctuelle), et sert de brique technique partagée avec les Races.
MULTIPLICATEURS_BOOST = {
    "xp": 1.5,
    "argent": 1.5,
    "shiny": 2.0,
}
DUREES_BOOST = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
}
XP_RAID_PAR_ETOILE = {1: 50, 2: 75, 3: 100, 4: 150, 5: 250}

# Anti-collusion PvP : contre un MÊME adversaire, seule la 1ère victoire de la journée
# rapporte la récompense pleine (PD + XP) ; les suivantes contre cette même personne
# sont fortement réduites (mais pas nulles, pour ne pas frustrer un vrai rematch).
# N'affecte pas les combats contre des adversaires variés, ni la progression des
# quêtes/accomplissements (seule la récompense économique brute est concernée).
PVP_MULTIPLICATEUR_REPETITION = 0.2

# --- Anti-farming Dresseurs (PvE) ---
# Dégression PROGRESSIVE (pas juste un palier comme le PvP) sur les récompenses PD/XP des
# victoires contre dresseur, regroupées TOUS archétypes confondus par jour — index 0 = 1ère
# victoire du jour (plein tarif), index 1 = 2e, etc. Le dernier palier s'applique à toute
# victoire suivante.
DRESSEUR_MULTIPLICATEURS_REPETITION_JOUR = [1.0, 0.6, 0.35, 0.2]

# --- Races (bonus permanents de dresseur) ---
# Obtenues uniquement par reroll aléatoire (Cristal de Mutation, gagné au Centre des
# Explorations). Un reroll REMPLACE la race actuelle — pas de stockage de races
# "débloquées" à switcher librement. Système de pity : après PITY_SEUIL rerolls sans
# obtenir au moins "rare", le prochain reroll est garanti rare ou mieux.
POIDS_TIRAGE_RACE = {"commun": 50, "peu_commun": 28, "rare": 13, "hyper_rare": 6, "legendaire": 3}
PITY_SEUIL = 10

# --- Centre des Explorations ---
EXPLORATION_TAILLE_EQUIPE = 3
EXPLORATION_DUREES = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
}
# Le PC total de l'équipe envoyée est plafonné pour le calcul de récompense, pour éviter
# qu'une équipe de 3 légendaires ne rende le système infini une fois la collection montée.
EXPLORATION_PLAFOND_PC = 6000
# Récompense = min(pc_total_equipe, PLAFOND) × facteur, par durée (plus long = meilleur taux)
# Récompense = min(pc_total_equipe, PLAFOND) × facteur, par durée. Facteurs recalibrés
# pour que le rendement PAR HEURE augmente avec la durée (avant : le 1h était 5x plus
# rentable par heure que le 24h). RE-NERFÉS (2e passe) : encore jugés trop forts en
# pratique — ×0,7 sur les 3 facteurs, forme (croissance par durée) conservée à l'identique.
# Au plafond de PC : 1h ≈ 56 PD/h, 6h ≈ 70 PD/h, 24h ≈ 84 PD/h (toujours croissant).
EXPLORATION_FACTEUR_DOLLARS = {"1h": 0.0093, "6h": 0.07, "24h": 0.336}
EXPLORATION_FACTEUR_XP = {"1h": 0.00833, "6h": 0.065, "24h": 0.32}
# Chance d'obtenir un Cristal de Mutation (objet de reroll de race) : base + bonus selon
# la puissance de l'équipe (jusqu'au plafond), plafonnée à CHANCE_MAX
EXPLORATION_CHANCE_CRISTAL = {
    "1h":  {"base": 0.05, "bonus_max": 0.10, "max": 0.15},
    "6h":  {"base": 0.15, "bonus_max": 0.20, "max": 0.35},
    "24h": {"base": 0.30, "bonus_max": 0.30, "max": 0.60},
}
# Objets de transformation (Fleur Gracidea, Orbe Griséous...) — voir formes_objets.py.
# Volontairement rares et réservés aux longues explorations (objets clés, pas des
# consommables) : jamais achetables en boutique (décision du 01/08/2026), uniquement
# trouvables ici ou déjà tenus par le Pokémon sauvage correspondant à la capture.
EXPLORATION_CHANCE_OBJET_FORME = {
    "1h":  {"base": 0.0, "bonus_max": 0.0, "max": 0.0},
    "6h":  {"base": 0.005, "bonus_max": 0.005, "max": 0.01},
    "24h": {"base": 0.01, "bonus_max": 0.02, "max": 0.03},
}
# Chance qu'un Pokémon sauvage tienne DÉJÀ son objet de transformation au moment de sa
# capture (uniquement pertinent pour Shaymin/Giratina/Dialga/Palkia, ignoré sinon).
# Chance qu'une capture (n'importe quelle espèce, exactement comme le Cristal de
# Mutation/les œufs ci-dessus) donne AUSSI un objet de transformation au hasard —
# calibré sous le taux du Cristal (0.05%) : ces objets sont encore plus exceptionnels
# (ils débloquent une forme alternative permanente sur une des 4 légendaires concernées).
CHANCE_OBJET_FORME_A_LA_CAPTURE = 0.0003  # 0.03%
# Relevé (équilibrage éco) : à 3000 PD, ce ×2 permanent des revenus d'exploration se
# remboursait en une seule journée au plafond — c'est désormais un vrai objectif long terme.
EXTENSION_SLOT_EXPLORATION_PRIX = 10000  # achat unique du 2e emplacement d'exploration

# --- Œufs (Laboratoire) ---
# Pas achetables — uniquement en drop (PokéStop, Exploration) pour l'instant. Éclosion =
# un Pokémon aléatoire du palier de rareté correspondant (même valeurs que "rarete" dans
# le Pokédex). Chaque palier garantit son propre niveau, avec une petite chance de "monter"
# d'un cran — sauf Légendaire, qui reste 100% Légendaire (déjà assez rare à l'entrée).
OEUF_PALIERS = ["commun", "peu_commun", "rare", "hyper_rare", "legendaire"]

OEUF_DUREE_INCUBATION = {
    "commun": 30 * 60,
    "peu_commun": 60 * 60,
    "rare": 3 * 3600,
    "hyper_rare": 8 * 3600,
    "legendaire": 24 * 3600,
}

# {palier_oeuf: {palier_resultat: probabilité}} — doit sommer à 1.0 par palier d'œuf.
OEUF_DISTRIBUTION_ECLOSION = {
    "commun": {"commun": 1.0},
    "peu_commun": {"peu_commun": 0.85, "rare": 0.15},
    "rare": {"rare": 0.85, "hyper_rare": 0.15},
    "hyper_rare": {"hyper_rare": 1.0},
    "legendaire": {"legendaire": 1.0},
}

# Chance de shiny à l'éclosion : base × ce facteur (combiné ensuite avec le bonus de Race
# comme partout ailleurs).
OEUF_MULTIPLICATEUR_SHINY = 2.0

# PokéStop : tirage "Œuf" indépendant des 3 autres (Balls/Potions/Objet rare). Le Légendaire
# est volontairement écrasé de rareté — sur 2000 tirages en moyenne pour en voir un seul.
OEUF_POIDS_POKESTOP = {
    "commun": 0.05,
    "peu_commun": 0.025,
    "rare": 0.008,
    "hyper_rare": 0.0015,
    "legendaire": 0.0005,
}  # le reste (91.5%) ne donne pas d'œuf ce tirage-ci

# Exploration : chance d'obtenir UN œuf (tous paliers confondus), indépendante du Cristal de
# Mutation. Le palier obtenu est ensuite tiré selon les proportions de OEUF_POIDS_POKESTOP.
# Comme le Cristal, ça scale avec le PC de l'équipe envoyée (jusqu'au plafond) et la durée.
EXPLORATION_CHANCE_OEUF = {
    "1h":  {"base": 0.02, "bonus_max": 0.03, "max": 0.05},
    "6h":  {"base": 0.05, "bonus_max": 0.05, "max": 0.10},
    "24h": {"base": 0.10, "bonus_max": 0.08, "max": 0.18},
}


# --- Quêtes ---
# Reset aligné sur des périodes fixes depuis l'epoch Unix (00h UTC pour les journalières,
# calé sur un jeudi pour les hebdomadaires) — identique et prévisible pour tout le monde.
QUETE_RECOMPENSE_JOUR = {"dollars": 50, "xp": 30}
QUETE_RECOMPENSE_SEMAINE = {"dollars": 350, "xp": 200}
QUETE_CHANCE_OBJET_BONUS_JOUR = 0.12  # chance d'un objet un peu rare en plus (Hyperball/Total Soin)
QUETE_CHANCE_CRISTAL_SEMAINE = 0.15   # chance de Cristal de Mutation en plus (bien plus rare qu'en exploration)


# --- Quête principale (narration) ---
# Optionnelle et non-bloquante par choix explicite : tout le contenu du bot reste
# accessible indépendamment de la progression ici, c'est un fil narratif qui suit ce que
# le joueur fait déjà plutôt qu'une restriction. TOUS les joueurs (même déjà avancés)
# démarrent au chapitre 1 — pas de rattrapage rétroactif basé sur leur progression déjà
# faite, par choix explicite (simplicité, pas de risque de mal détecter un "juste palier").
# "evenement" correspond soit à un evenement existant de incrementer_progression_quete
# (capture/pve_victoire/pvp_victoire/raid_victoire/exploration_collectee/pokestop), soit à
# un des 3 événements dédiés (badge_arene/badge_repaire/gladio_victoire) déclenchés
# directement depuis leurs points d'octroi respectifs (voir database.avancer_quete_principale).
QUETE_PRINCIPALE_CHAPITRES = [
    {
        "titre": "Premiers Pas",
        "intro": (
            "Le monde de PokéWild s'ouvre devant toi. Chaque buisson, chaque recoin peut "
            "cacher un Pokémon sauvage — à toi de les trouver et de les capturer.\n\n"
            "**Objectif : capturer 5 Pokémon.**"
        ),
        "outro": "Ton équipe prend forme. Un dresseur t'a repéré au loin — il n'attend qu'un signe pour t'affronter...",
        "evenement": "capture",
        "cible": 5,
        "recompense": {"dollars": 100, "xp": 50},
    },
    {
        "titre": "Face à un Dresseur",
        "intro": (
            "Un dresseur croise ta route et te met au défi. C'est l'occasion de tester "
            "tes Pokémon en combat réel, pas seulement contre des sauvages.\n\n"
            "**Objectif : gagner 1 combat contre un dresseur.**"
        ),
        "outro": (
            "Victoire ! Au loin, tu aperçois les couleurs d'une Arène — les maîtres qui "
            "l'occupent n'accordent leur badge qu'aux dresseurs qui les battent en duel."
        ),
        "evenement": "pve_victoire",
        "cible": 1,
        "recompense": {"dollars": 150, "xp": 75},
    },
    {
        "titre": "Défi de l'Arène",
        "intro": (
            "L'Arène t'attend. Un Apprenti d'abord, puis le Champion en personne — "
            "seule une victoire complète te vaudra le badge.\n\n"
            "**Objectif : obtenir 1 badge d'Arène.**"
        ),
        "outro": (
            "Le badge brille sur ton profil. Mais tout n'est pas paisible dans cette région — "
            "des rumeurs parlent d'une équipe aux intentions bien moins nobles..."
        ),
        "evenement": "badge_arene",
        "cible": 1,
        "recompense": {"dollars": 250, "xp": 120},
    },
    {
        "titre": "Repaire Infiltré",
        "intro": (
            "Une organisation criminelle a établi un repaire non loin. Ses sbires, puis "
            "son chef, s'opposeront à toi si tu t'y aventures.\n\n"
            "**Objectif : obtenir 1 badge de Repaire de méchants.**"
        ),
        "outro": "Le repaire est neutralisé, pour cette fois. Mais ta réputation grandit — un rival bien connu commence à s'intéresser à toi.",
        "evenement": "badge_repaire",
        "cible": 1,
        "recompense": {"dollars": 300, "xp": 150},
    },
    {
        "titre": "L'Esprit de Compétition",
        "intro": (
            "Un autre dresseur, un vrai, humain celui-là, accepte de croiser le fer avec toi. "
            "Le combat entre joueurs demande une autre approche que le sauvage ou le dresseur PNJ.\n\n"
            "**Objectif : gagner 1 combat PvP.**"
        ),
        "outro": "Ta première victoire en PvP ! Ce genre de duel va vite devenir une habitude...",
        "evenement": "pvp_victoire",
        "cible": 1,
        "recompense": {"dollars": 200, "xp": 100},
    },
    {
        "titre": "Force du Nombre",
        "intro": (
            "Certains Pokémon sont bien trop puissants pour être affrontés seul. "
            "Rallie d'autres dresseurs pour un Raid.\n\n"
            "**Objectif : remporter 1 Raid.**"
        ),
        "outro": "Ensemble, vous avez triomphé là où un seul dresseur aurait échoué. La coopération a du bon.",
        "evenement": "raid_victoire",
        "cible": 1,
        "recompense": {"dollars": 300, "xp": 150},
    },
    {
        "titre": "Rival de Toujours",
        "intro": (
            "Gladio te suit depuis le début, t'observant grandir. Il est temps de savoir "
            "qui, de vous deux, est réellement le plus fort.\n\n"
            "**Objectif : battre Gladio en combat.**"
        ),
        "outro": (
            "Gladio accepte sa défaite avec un sourire en coin — le respect entre vous est "
            "réel, désormais. Ton aventure continue, mais ce chapitre de ton histoire "
            "s'achève ici. Le reste du monde de PokéWild n'attend que toi."
        ),
        "evenement": "gladio_victoire",
        "cible": 1,
        "recompense": {"dollars": 500, "xp": 300, "objet": "cristal_mutation"},
    },
]
