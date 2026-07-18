# Configuration du bot
# ⚠️ Ne partage JAMAIS ton token publiquement (GitHub, Discord, etc.)
# En production, préfère charger ça depuis un fichier .env (voir python-dotenv)

import os
TOKEN = os.environ["DISCORD_TOKEN"]

# --- IDs des channels (à remplir avec les vrais IDs de ton serveur) ---
CHANNEL_SPAWN_CLASSIQUE_ID = 1524432178694455346
CHANNEL_SPAWN_VIP_ID = 1524433167874920509
CHANNEL_POKESTOP_ID = 1524432806912983241
CHANNEL_BOUTIQUE_ID = 1524503716982689827
CHANNEL_MAITRE_TYPES_ID = None  # crée un channel dédié et mets son ID ici pour afficher le PNJ (sinon /maitre-types marche partout)
CHANNEL_EXPLORATION_ID = 1525908138203807926
CHANNEL_QUETES_ID = 1525970082264514730
CHANNEL_AVENTURE_ID = 1526201523867226192
CHANNEL_LABORATOIRE_ID = 1526365279855054952  # Incubateur + Race, regroupés dans un seul channel
CHANNEL_LOGS_ID = 1527415638371598526  # channel dédié aux logs bot + joueurs

# --- Dresseurs PvE (combat contre une IA, PV liés au même pool persistant que les raids) ---
INTERVALLE_DRESSEUR = 20 * 60  # 20 min entre deux spawns (plus rare qu'un raid pour limiter le farming solo)
DUREE_DISPONIBILITE_DRESSEUR = 10 * 60  # le dresseur repart si personne ne le défie dans ce délai
DRESSEUR_VARIANCE_PC = 0.15  # l'équipe adverse vise le PC cumulé du joueur, ± cette variance
DRESSEUR_FACTEUR_DOLLARS = 0.015  # récompense = PC cible de l'équipe adverse × ce facteur
DRESSEUR_FACTEUR_XP = 0.01  # baissés (avant 0.05 / 0.03) : à l'ancien taux, une équipe proche du plafond
# de PC, multipliée par le fait que chaque spawn est désormais accessible à tout le monde, dépassait le
# seuil de 600-900 PD/h déjà jugé abusif pour le PvP avant son propre nerf anti-collusion.
CHANNEL_PROFIL_ID = 1524512674942156851
CHANNEL_CLASSEMENT_ID = 1524802617455284404

# --- Rythme des spawns (en secondes) ---
INTERVALLE_SPAWN_CLASSIQUE = 60
INTERVALLE_SPAWN_VIP = 45

# --- Disparition d'un spawn non capturé (en secondes) ---
DUREE_AVANT_DISPARITION = 45

# --- PokéStop ---
COOLDOWN_POKESTOP = 300  # 5 minutes, en secondes

# --- Rôle VIP (pour vérifier l'accès si besoin dans le code) ---
ROLE_VIP_ID = 1524443826956271838
ROLE_PING_RAID_ID = 1525883524396355675

# --- Serveur de test (pour synchroniser les commandes instantanément dessus) ---
GUILD_ID = 1496856137583296562

# --- Shiny ---
CHANCE_SHINY_BASE = 1 / 200  # ~0.5% de base, indépendant pour chaque joueur à chaque tentative

# --- Boutique (Poké Dollars) ---
PRIX_BALLS = {
    "pokeball": 15,
    "superball": 35,
    "hyperball": 70,
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

# --- CT au Maître des Types : coût en Poké Dollars pour apprendre une attaque que le
# Pokémon n'a pas encore débloquée par son niveau (ou qui ne se débloque jamais par
# niveau — CT/tuteur/œuf uniquement dans les vrais jeux). Une attaque déjà débloquée par
# le niveau reste gratuite à équiper, comme dans les jeux (le Pokémon la connaît déjà).
PRIX_CT_STATUT = 150  # attaque sans dégâts (statut, buff/debuff...)
PRIX_CT_PAR_PUISSANCE = {  # puissance minimale -> prix (le seuil le plus haut atteint s'applique)
    0: 120,
    40: 200,
    70: 350,
    90: 550,
    120: 900,
}

# --- Stockage des Pokémon et objets (extensible en boutique) ---
LIMITE_STOCKAGE_POKEMON_BASE = 300
LIMITE_STOCKAGE_OBJETS_BASE = 50

EXTENSION_STOCKAGE_POKEMON = 10  # slots ajoutés PAR ACHAT
PRIX_EXTENSION_STOCKAGE_POKEMON = 400  # prix par achat de +10 (même tarif au slot qu'avant : 40 PD/slot)

EXTENSION_STOCKAGE_OBJETS = 10  # slots ajoutés PAR ACHAT
PRIX_EXTENSION_STOCKAGE_OBJETS = 400  # prix par achat de +10 (même tarif au slot qu'avant : 40 PD/slot)

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

DUREE_SALLE_ATTENTE_RAID = 90  # secondes avant que le combat ne démarre vraiment
DUREE_RAID_MINUTES = 15  # temps de combat avant que le boss ne s'échappe si non vaincu
INTERVALLE_TICK_COMBAT_RAID = 5  # secondes entre chaque attaque automatique de tous les participants

DEGATS_VARIANCE_MIN = 0.8
DEGATS_VARIANCE_MAX = 1.2
DEGATS_DIVISEUR_RAID = 12  # ramène le PC (échelle "collection", jusqu'à 3000) à une échelle de dégâts raisonnable

# Nombre d'Honor Ball reçues par CHAQUE participant à la victoire (peu importe les dégâts infligés)
# Chaque participant a le même nombre de tentatives de capture (Honor Ball), peu importe
# le palier d'étoiles — seul le TAUX DE RÉUSSITE varie selon la rareté (voir TAUX_CAPTURE
# dans pokemon_data.py, clé "honorball"). Ces tentatives ne sont PAS stockées dans
# l'inventaire général : elles n'existent que pour ce raid précis.
TENTATIVES_CAPTURE_RAID = 5
DUREE_AFFICHAGE_VICTOIRE_RAID = 180  # 3 minutes avant suppression automatique du message de résumé

# Récompenses Poké Dollars / XP par participant, selon le nombre d'étoiles du raid vaincu
DOLLARS_RAID_PAR_ETOILE = {1: 50, 2: 100, 3: 150, 4: 250, 5: 400}

# --- PV des Pokémon personnels (utilisés en raid) ---
FACTEUR_PV_PAR_PC = 0.8  # PV max = PC × ce facteur (raids uniquement — ticks automatiques, gros PV OK)

# --- PvP : système séparé des raids ---
# Un combat PvP à ~45s par tour doit se résoudre en peu de tours (3-5 par Pokémon à
# puissance égale, comme les vrais jeux Pokémon), d'où des PV réduits par rapport aux raids.
FACTEUR_PV_COMBAT_PVP = 0.4  # PV en combat PvP = PC × ce facteur

# Dégâts que le boss inflige en retour à CHAQUE participant, à chaque tick, répartis
# entre ses Pokémon d'équipe encore en vie (0 PV = K.O., ne contribue plus aux dégâts
# jusqu'à un soin).
DEGATS_BOSS_PAR_ETOILE = {1: 40, 2: 90, 3: 180, 4: 350, 5: 650}

# --- Objets de soin (boutique) ---
PRIX_SOINS = {
    "potion": 20,
    "superpotion": 55,
    "hyperpotion": 140,
    "totalsoin": 80,
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
# rentable par heure que le 24h, ce qui poussait à spammer des explorations courtes au
# lieu de vraiment s'engager sur la durée — l'inverse de l'intention). Désormais, au
# plafond de PC : 1h ≈ 80 PD/h, 6h ≈ 100 PD/h, 24h ≈ 120 PD/h (croissant).
EXPLORATION_FACTEUR_DOLLARS = {"1h": 0.0133, "6h": 0.10, "24h": 0.48}
EXPLORATION_FACTEUR_XP = {"1h": 0.00833, "6h": 0.065, "24h": 0.32}
# Chance d'obtenir un Cristal de Mutation (objet de reroll de race) : base + bonus selon
# la puissance de l'équipe (jusqu'au plafond), plafonnée à CHANCE_MAX
EXPLORATION_CHANCE_CRISTAL = {
    "1h":  {"base": 0.05, "bonus_max": 0.10, "max": 0.15},
    "6h":  {"base": 0.15, "bonus_max": 0.20, "max": 0.35},
    "24h": {"base": 0.30, "bonus_max": 0.30, "max": 0.60},
}
EXTENSION_SLOT_EXPLORATION_PRIX = 3000  # achat unique du 2e emplacement d'exploration

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
