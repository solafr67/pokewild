import json
import os
import random
import sqlite3
import time

import config

# Surchargeable via DB_PATH dans l'environnement — permet à un 2e bot (serveur de test)
# de tourner avec sa propre base sans jamais toucher aux vraies données de production.
DB_PATH = os.environ.get("DB_PATH", "pokebot.sqlite3")

BALLS_DEPART = {"pokeball": 5, "superball": 1, "hyperball": 0}

# Si un combat reste actif = 1 sans que son tour n'avance depuis plus longtemps que ça, on
# considère que la boucle de résolution qui devait le terminer a disparu (redémarrage du bot
# en plein combat) et on le clôture nous-même — sinon il bloquerait le joueur pour toujours.
COMBAT_ABANDON_SECONDES = 600


import unicodedata


def _collation_alphabet_fr(a: str, b: str) -> int:
    """Trie en ignorant les accents — SQLite trie par défaut par valeur d'octet, ce qui
    placerait "É" après "Z" au lieu de le mélanger avec les autres "E"/"e"."""
    def _sans_accents(s):
        return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    a2, b2 = _sans_accents(a), _sans_accents(b)
    return -1 if a2 < b2 else (1 if a2 > b2 else 0)


def get_connexion():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_collation("ALPHABET_FR", _collation_alphabet_fr)
    return conn


def init_db():
    conn = get_connexion()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS boosts_actifs (
            user_id INTEGER NOT NULL,
            type_boost TEXT NOT NULL,
            date_expiration INTEGER NOT NULL,
            PRIMARY KEY (user_id, type_boost)
        )
        """
    )

    # --- Events serveur : boost global, défi collectif, chasse aux shiny (/event) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS evenement_boost_global (
            type_boost TEXT PRIMARY KEY,
            multiplicateur REAL NOT NULL,
            date_expiration INTEGER NOT NULL,
            channel_annonce_id INTEGER,
            message_id INTEGER
        )
        """
    )
    try:
        cur.execute("ALTER TABLE evenement_boost_global ADD COLUMN message_id INTEGER")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS defi_collectif_serveur (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_evenement TEXT NOT NULL,
            cible INTEGER NOT NULL,
            progres INTEGER NOT NULL DEFAULT 0,
            actif INTEGER NOT NULL DEFAULT 1,
            date_debut INTEGER NOT NULL,
            channel_annonce_id INTEGER,
            recompense_donnee INTEGER NOT NULL DEFAULT 0,
            message_id INTEGER
        )
        """
    )
    try:
        cur.execute("ALTER TABLE defi_collectif_serveur ADD COLUMN message_id INTEGER")
    except sqlite3.OperationalError:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS defi_collectif_participants (
            defi_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            contribution INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (defi_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chasse_shiny_evenement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_debut INTEGER NOT NULL,
            date_fin INTEGER NOT NULL,
            actif INTEGER NOT NULL DEFAULT 1,
            channel_annonce_id INTEGER,
            annoncee INTEGER NOT NULL DEFAULT 0,
            message_id INTEGER
        )
        """
    )
    try:
        cur.execute("ALTER TABLE chasse_shiny_evenement ADD COLUMN message_id INTEGER")
    except sqlite3.OperationalError:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS joueur_race (
            user_id INTEGER PRIMARY KEY,
            race_nom TEXT NOT NULL,
            pity_compteur INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS quete_progression (
            user_id INTEGER NOT NULL,
            quete_id TEXT NOT NULL,
            periode_id INTEGER NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            reclamee INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, quete_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stats_lifetime (
            user_id INTEGER PRIMARY KEY,
            victoires_pvp INTEGER NOT NULL DEFAULT 0,
            explorations_terminees INTEGER NOT NULL DEFAULT 0,
            victoires_pve INTEGER NOT NULL DEFAULT 0,
            captures_totales INTEGER NOT NULL DEFAULT 0,
            shiny_totaux INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Compteur d'interactions avec Gladio (le rival) — détermine le palier de familiarité
    # utilisé pour choisir le ton de ses répliques (distant -> familier -> respect bourru).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gladio_relation (
            user_id INTEGER PRIMARY KEY,
            compteur INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Migration pour les bases créées avant le suivi de décroissance par inactivité
    try:
        cur.execute("ALTER TABLE gladio_relation ADD COLUMN derniere_interaction INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gladio_defis (
            user_id INTEGER PRIMARY KEY,
            dernier_defi INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Série de victoires PvP consécutives (remise à zéro à la première défaite) — sert de
    # déclencheur pour un commentaire de Gladio, indépendant du suivi anti-collusion existant.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pvp_serie_victoires (
            user_id INTEGER PRIMARY KEY,
            serie INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Migration pour les joueurs déjà en base avant l'ajout des compteurs de captures à vie
    # (classements "Plus de captures"/"Plus de shiny" comptaient auparavant les lignes ENCORE
    # en base, donc relâcher des doublons faisait artificiellement baisser le classement).
    for colonne in ("captures_totales", "shiny_totaux"):
        try:
            cur.execute(f"ALTER TABLE stats_lifetime ADD COLUMN {colonne} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    # Rattrapage ponctuel (une seule fois) : initialise captures_totales/shiny_totaux à partir
    # des captures ENCORE en base au moment de la migration, pour ne pas remettre tout le monde
    # à zéro sur les classements concernés. Les captures relâchées avant cette migration restent
    # malheureusement perdues pour ce compteur (elles n'existent plus nulle part pour les compter).
    # La table settings est créée plus bas dans init_db : sur une base VIERGE, la lire ici
    # plantait (no such table) et empêchait tout démarrage. On s'assure qu'elle existe, et
    # s'il n'y a pas encore de table captures (installation neuve), il n'y a tout simplement
    # rien à rattraper : on pose le marqueur et on passe.
    cur.execute("CREATE TABLE IF NOT EXISTS settings (cle TEXT PRIMARY KEY, valeur TEXT)")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='captures'")
    if cur.fetchone() is None:
        cur.execute(
            "INSERT OR IGNORE INTO settings (cle, valeur) VALUES ('backfill_captures_totales_fait', '1')"
        )
    cur.execute("SELECT valeur FROM settings WHERE cle = 'backfill_captures_totales_fait'")
    if cur.fetchone() is None:
        cur.execute(
            """
            INSERT INTO stats_lifetime (user_id, captures_totales)
            SELECT user_id, COUNT(*) FROM captures GROUP BY user_id
            ON CONFLICT(user_id) DO UPDATE SET captures_totales = excluded.captures_totales
            """
        )
        cur.execute(
            """
            INSERT INTO stats_lifetime (user_id, shiny_totaux)
            SELECT user_id, COUNT(*) FROM captures WHERE shiny = 1 GROUP BY user_id
            ON CONFLICT(user_id) DO UPDATE SET shiny_totaux = excluded.shiny_totaux
            """
        )
        cur.execute(
            "INSERT INTO settings (cle, valeur) VALUES ('backfill_captures_totales_fait', '1')"
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots_economie (
            date INTEGER PRIMARY KEY,
            nb_joueurs INTEGER,
            total_pd INTEGER
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pvp_victoires_jour (
            vainqueur_id INTEGER NOT NULL,
            perdant_id INTEGER NOT NULL,
            jour_id INTEGER NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (vainqueur_id, perdant_id, jour_id)
        )
        """
    )

    # Dégression PvP générale (tous adversaires confondus), en complément de
    # pvp_victoires_jour ci-dessus qui ne couvre que l'anti-collusion par adversaire
    # précis — voir database.enregistrer_victoire_pvp_generale_repetition.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pvp_victoires_jour_generale (
            user_id INTEGER NOT NULL,
            jour_id INTEGER NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, jour_id)
        )
        """
    )

    # Dégression économique de l'Exploration (harmonisée avec Dresseur/Arène/Repaire/PvP) —
    # voir database.enregistrer_completion_exploration_repetition.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exploration_completions_jour (
            user_id INTEGER NOT NULL,
            jour_id INTEGER NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, jour_id)
        )
        """
    )

    # Contrairement au PvP (par adversaire précis), ici on regroupe TOUS les dresseurs
    # confondus : peu importe l'archétype battu, seul le nombre de victoires PvE du jour
    # compte pour la dégression (voir enregistrer_victoire_dresseur_repetition).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pve_victoires_jour (
            user_id INTEGER NOT NULL,
            jour_id INTEGER NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, jour_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS titre_actif (
            user_id INTEGER PRIMARY KEY,
            categorie TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS codes_promo (
            code TEXT PRIMARY KEY,
            dollars INTEGER NOT NULL DEFAULT 0,
            xp INTEGER NOT NULL DEFAULT 0,
            objet TEXT,
            quantite_objet INTEGER NOT NULL DEFAULT 0,
            max_utilisations INTEGER,
            utilisations_actuelles INTEGER NOT NULL DEFAULT 0,
            date_expiration INTEGER,
            actif INTEGER NOT NULL DEFAULT 1,
            cree_par INTEGER NOT NULL,
            date_creation INTEGER NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS codes_promo_utilises (
            code TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            date_utilisation INTEGER NOT NULL,
            PRIMARY KEY (code, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications_attente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            texte TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exploration_slots (
            user_id INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            pokemon1 TEXT,
            pokemon2 TEXT,
            pokemon3 TEXT,
            date_debut INTEGER,
            date_fin INTEGER,
            duree_label TEXT,
            notifie INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, slot)
        )
        """
    )

    # Migration pour les emplacements déjà en base avant l'ajout des notifications MP
    try:
        cur.execute("ALTER TABLE exploration_slots ADD COLUMN notifie INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # 1 seul emplacement pour l'instant (pas d'extension achetable comme l'Exploration,
    # volontairement laissé simple en V1).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS incubateur_slots (
            user_id INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            palier TEXT,
            date_debut INTEGER,
            date_fin INTEGER,
            notifie INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, slot)
        )
        """
    )

    try:
        cur.execute("ALTER TABLE incubateur_slots ADD COLUMN notifie INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            poke_dollars INTEGER NOT NULL DEFAULT 0,
            team TEXT,
            pokestop_last_used INTEGER NOT NULL DEFAULT 0,
            xp_dresseur INTEGER NOT NULL DEFAULT 0,
            team_last_change INTEGER NOT NULL DEFAULT 0,
            extensions_stockage_pokemon INTEGER NOT NULL DEFAULT 0,
            extensions_stockage_objets INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Migration pour les bases créées avant l'ajout des extensions de stockage
    for colonne in ("extensions_stockage_pokemon", "extensions_stockage_objets"):
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {colonne} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    # Migration pour les bases créées avant l'ajout du 2e emplacement d'exploration
    try:
        cur.execute("ALTER TABLE users ADD COLUMN slot_exploration_achete INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant l'ajout de duree_label (nécessaire pour /finir-exploration)
    try:
        cur.execute("ALTER TABLE exploration_slots ADD COLUMN duree_label TEXT")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant l'ajout du compteur d'explorations à vie
    try:
        cur.execute("ALTER TABLE stats_lifetime ADD COLUMN explorations_terminees INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant l'ajout du compteur de victoires PvE
    try:
        cur.execute("ALTER TABLE stats_lifetime ADD COLUMN victoires_pve INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant l'ajout du changement de clan
    try:
        cur.execute("ALTER TABLE users ADD COLUMN team_last_change INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant l'ajout de l'XP
    try:
        cur.execute("ALTER TABLE users ADD COLUMN xp_dresseur INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS inventaire_balls (
            user_id INTEGER NOT NULL,
            ball_type TEXT NOT NULL,
            quantite INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, ball_type)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            pc INTEGER NOT NULL,
            date_capture INTEGER NOT NULL,
            shiny INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Migration pour les bases créées avant la suppression du niveau des Pokémon sauvages
    try:
        cur.execute("ALTER TABLE captures DROP COLUMN niveau")
    except sqlite3.OperationalError:
        pass  # la colonne n'existe déjà plus (ou base neuve)

    # Migration : talent (capacité) et objet tenu — système d'objets/talents en combat PvP
    try:
        cur.execute("ALTER TABLE captures ADD COLUMN capacite TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE captures ADD COLUMN objet_tenu TEXT")
    except sqlite3.OperationalError:
        pass

    # Migration : verrouillage d'un exemplaire précis — protège un doublon du relâcher
    # automatique (/relacher) sans avoir à le décocher manuellement à chaque fois.
    try:
        cur.execute("ALTER TABLE captures ADD COLUMN verrouille INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Migration pour les bases créées avant l'ajout de la colonne shiny
    try:
        cur.execute("ALTER TABLE captures ADD COLUMN shiny INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant les vrais IV par individu (refonte combat/stats)
    for colonne in ("iv_pv", "iv_attaque", "iv_defense", "iv_attaque_spe", "iv_defense_spe", "iv_vitesse"):
        try:
            cur.execute(f"ALTER TABLE captures ADD COLUMN {colonne} INTEGER")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            cle TEXT PRIMARY KEY,
            valeur TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS equipe_combat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            UNIQUE(user_id, pokemon_nom)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS equipe_presets_combat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nom_preset TEXT NOT NULL,
            pokemon_nom TEXT NOT NULL,
            UNIQUE(user_id, nom_preset, pokemon_nom)
        )
        """
    )

    # --- Système de clan (3 équipes fixes façon Pokémon GO) : contribution perso,
    # objectif hebdomadaire coopératif/compétitif, historique de saisons ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clan_contribution (
            user_id INTEGER PRIMARY KEY,
            equipe TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clan_objectif_semaine (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semaine_debut INTEGER NOT NULL UNIQUE,
            type TEXT NOT NULL,
            cible INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clan_objectif_progres (
            objectif_id INTEGER NOT NULL,
            equipe TEXT NOT NULL,
            progres INTEGER NOT NULL DEFAULT 0,
            complete_le INTEGER,
            butin_recupere INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (objectif_id, equipe)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clan_saison_historique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saison TEXT NOT NULL,
            equipe TEXT NOT NULL,
            rang INTEGER NOT NULL,
            score INTEGER NOT NULL,
            UNIQUE(saison, equipe)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS niveaux_pokemon (
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            niveau INTEGER NOT NULL DEFAULT 1,
            xp INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, pokemon_nom)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ct_possedees (
            user_id INTEGER NOT NULL,
            nom_attaque TEXT NOT NULL,
            PRIMARY KEY (user_id, nom_attaque)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS record_plus_ou_moins (
            user_id INTEGER PRIMARY KEY,
            meilleur_score INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS saison_points (
            user_id INTEGER NOT NULL,
            saison INTEGER NOT NULL,
            points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, saison)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS parrainages (
            filleul_id INTEGER PRIMARY KEY,
            inviteur_id INTEGER NOT NULL,
            date_join INTEGER NOT NULL,
            confirme INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS parrainage_paliers_recus (
            user_id INTEGER NOT NULL,
            palier INTEGER NOT NULL,
            PRIMARY KEY (user_id, palier)
        )
        """
    )

    # Migration pour le statut booster serveur (pré-existant : ajouté à la table users)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN booster_serveur INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS etat_combat_pokemon (
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            pv_actuels INTEGER NOT NULL,
            PRIMARY KEY (user_id, pokemon_nom)
        )
        """
    )

    # Table séparée pour les PV persistants EN RAID — auparavant partagée avec
    # etat_combat_pokemon (PvP/dresseurs/Arène/Gladio), ce qui faisait que combattre en
    # raid et en dresseur en même temps affectait la même barre de vie. Même structure,
    # juste un espace de PV totalement indépendant le temps d'un raid.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS etat_combat_pokemon_raid (
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            pv_actuels INTEGER NOT NULL,
            PRIMARY KEY (user_id, pokemon_nom)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS echanges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            joueur1_id INTEGER NOT NULL,
            joueur2_id INTEGER NOT NULL,
            joueur1_pd INTEGER NOT NULL DEFAULT 0,
            joueur2_pd INTEGER NOT NULL DEFAULT 0,
            joueur1_valide INTEGER NOT NULL DEFAULT 0,
            joueur2_valide INTEGER NOT NULL DEFAULT 0,
            actif INTEGER NOT NULL DEFAULT 1,
            thread_id TEXT,
            message_id TEXT,
            date_creation INTEGER NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_annonces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendeur_id INTEGER NOT NULL,
            capture_id INTEGER NOT NULL,
            prix INTEGER NOT NULL,
            date_creation INTEGER NOT NULL,
            date_expiration INTEGER NOT NULL,
            statut TEXT NOT NULL DEFAULT 'active',
            message_id TEXT,
            acheteur_id INTEGER
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS roguelike_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            joueur_id INTEGER NOT NULL,
            actif INTEGER NOT NULL DEFAULT 1,
            salle_index INTEGER NOT NULL DEFAULT 0,
            chemin TEXT NOT NULL,
            reliques TEXT NOT NULL DEFAULT '[]',
            thread_id TEXT,
            message_id TEXT,
            date_creation INTEGER NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS roguelike_equipe (
            run_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            niveau INTEGER NOT NULL,
            pv_max INTEGER NOT NULL,
            pv_actuels INTEGER NOT NULL,
            PRIMARY KEY (run_id, position)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS roguelike_combat (
            run_id INTEGER PRIMARY KEY,
            ennemi_nom TEXT NOT NULL,
            ennemi_niveau INTEGER NOT NULL,
            ennemi_pv_max INTEGER NOT NULL,
            ennemi_pv_actuels INTEGER NOT NULL,
            actif_position INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS roguelike_records (
            joueur_id INTEGER PRIMARY KEY,
            meilleur_etage INTEGER NOT NULL DEFAULT 0,
            date_record INTEGER
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS echange_pokemon (
            echange_id INTEGER NOT NULL,
            capture_id INTEGER NOT NULL,
            proposant_id INTEGER NOT NULL,
            PRIMARY KEY (echange_id, capture_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_pvp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            joueur1_id INTEGER NOT NULL,
            joueur2_id INTEGER NOT NULL,
            thread_id TEXT,
            actif INTEGER NOT NULL DEFAULT 1,
            tour INTEGER NOT NULL DEFAULT 1,
            actif1_nom TEXT NOT NULL,
            actif2_nom TEXT NOT NULL,
            action1 TEXT,
            action2 TEXT,
            date_debut INTEGER NOT NULL,
            date_limite_tour INTEGER NOT NULL,
            potions_soin1 INTEGER NOT NULL DEFAULT 0,
            potions_soin2 INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_2v2_joueurs (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            equipe INTEGER NOT NULL,
            actif_nom TEXT,
            action TEXT,
            abandonne INTEGER NOT NULL DEFAULT 0,
            potions_soin INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (combat_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_choix_ko (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            date_limite INTEGER NOT NULL,
            relais INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (combat_id, user_id)
        )
        """
    )

    # Migration pour les bases créées avant l'ajout de Relais (Baton Pass)
    try:
        cur.execute("ALTER TABLE combat_choix_ko ADD COLUMN relais INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les combats déjà en base avant l'ajout de la limite de potions de soin
    for colonne in ("potions_soin1", "potions_soin2"):
        try:
            cur.execute(f"ALTER TABLE combat_pvp ADD COLUMN {colonne} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_equipe (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            pv_max INTEGER NOT NULL,
            pv_actuels INTEGER NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (combat_id, user_id, pokemon_nom)
        )
        """
    )

    # Migration : stats de combat complètes calculées une fois au début du combat (vraie
    # formule IV + niveau), pour ne plus avoir à les re-dériver à chaque tour de résolution.
    for colonne in ("atq", "defe", "atq_spe", "def_spe", "vit"):
        try:
            cur.execute(f"ALTER TABLE combat_equipe ADD COLUMN {colonne} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà
    try:
        cur.execute("ALTER TABLE combat_equipe ADD COLUMN niveau INTEGER NOT NULL DEFAULT 50")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Snapshot du talent/objet tenu AU MOMENT du début du combat — pour un vrai joueur,
    # copié depuis captures.capacite/objet_tenu ; pour un dresseur/boss IA (user_id < 0,
    # jamais présent dans captures), tiré au hasard directement ici. Centraliser sur ce
    # snapshot (plutôt que d'aller chercher dans captures à chaque tour) permet au moteur
    # de combat de fonctionner IDENTIQUEMENT pour un vrai joueur ET une IA, sans code
    # spécial — voir database.definir_capacite_combat/definir_objet_combat.
    for colonne in ("capacite", "objet_tenu"):
        try:
            cur.execute(f"ALTER TABLE combat_equipe ADD COLUMN {colonne} TEXT")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attaques_equipees (
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            slot INTEGER NOT NULL,
            attaque_nom TEXT NOT NULL,
            PRIMARY KEY (user_id, pokemon_nom, slot)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS draft_attaques_equipees (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            slot INTEGER NOT NULL,
            attaque_nom TEXT NOT NULL,
            PRIMARY KEY (combat_id, user_id, pokemon_nom, slot)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS arene_spawn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_arene TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            date_expiration INTEGER NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS arene_runs (
            arene_spawn_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            etape INTEGER NOT NULL DEFAULT 0,
            statut TEXT NOT NULL DEFAULT 'en_cours',
            PRIMARY KEY (arene_spawn_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS arene_victoires_jour (
            user_id INTEGER NOT NULL,
            jour_id INTEGER NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, jour_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS arene_badges (
            user_id INTEGER NOT NULL,
            type_pokemon TEXT NOT NULL,
            date_obtenu INTEGER NOT NULL,
            PRIMARY KEY (user_id, type_pokemon)
        )
        """
    )

    # --- Repaires de méchants (Team Rocket, Aqua, Magma, Galactic...) — même principe
    # que l'arène (2 sbires + 1 boss), voir repaires.py.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS repaire_spawn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipe_mechante TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            date_expiration INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS repaire_runs (
            repaire_spawn_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            etape INTEGER NOT NULL DEFAULT 0,
            statut TEXT NOT NULL DEFAULT 'en_cours',
            PRIMARY KEY (repaire_spawn_id, user_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS repaire_victoires_jour (
            user_id INTEGER NOT NULL,
            jour_id INTEGER NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, jour_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS repaire_badges (
            user_id INTEGER NOT NULL,
            equipe_mechante TEXT NOT NULL,
            date_obtenu INTEGER NOT NULL,
            PRIMARY KEY (user_id, equipe_mechante)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_boosts (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            stage_atk INTEGER NOT NULL DEFAULT 0,
            stage_def INTEGER NOT NULL DEFAULT 0,
            stage_vit INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (combat_id, user_id, pokemon_nom)
        )
        """
    )

    # Migration : Attaque Spé / Défense Spé distinctes de Attaque / Défense (avant, un
    # boost visant l'une ou l'autre catégorie physique/spéciale était confondu avec la
    # même colonne — une attaque boostant Atq ET Atq Spé ne boostait donc que l'Atq, deux fois).
    for colonne in ("stage_atk_spe", "stage_def_spe"):
        try:
            cur.execute(f"ALTER TABLE combat_boosts ADD COLUMN {colonne} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    # Migration : Précision / Esquive (6e et 7e dimension de boost) — indépendantes des 5
    # stats offensives/défensives, gèrent les changements de chance de toucher/d'esquiver
    # (Regard Vif, Voile Sable, Œil Composé, Pieds Confus, Agitation...).
    for colonne in ("stage_precision", "stage_esquive"):
        try:
            cur.execute(f"ALTER TABLE combat_boosts ADD COLUMN {colonne} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    # Attaques à deux tours (charge type Lance-Soleil, recharge type Ultimaton/Ultralaser) —
    # voir ATTAQUES_CHARGE / ATTAQUES_RECHARGE dans pokemon_data.py.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_charge (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            attaque_en_charge TEXT,
            doit_recharger INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (combat_id, user_id, pokemon_nom)
        )
        """
    )

    # Attaques de FURIE (ex: Colère/Dracocolère) : verrouille sur la même attaque 2-3
    # tours d'affilée dès le premier usage (pas de tour de charge préalable, contrairement
    # à combat_charge ci-dessus), puis confusion automatique à la fin du verrouillage.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_furie (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            attaque TEXT NOT NULL,
            tours_restants INTEGER NOT NULL,
            PRIMARY KEY (combat_id, user_id, pokemon_nom)
        )
        """
    )

    # Météo de combat (Soleil/Pluie/Tempête de sable/Grêle) — un seul état par combat,
    # affecte les DEUX joueurs également (contrairement aux pièges de terrain qui sont
    # par côté, voir combat_terrain plus haut).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_meteo (
            combat_id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            tours_restants INTEGER NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_choix (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            attaque_verrouillee TEXT,
            PRIMARY KEY (combat_id, user_id, pokemon_nom)
        )
        """
    )

    # Migration 2v2 : cible mémorisée au tour de charge (NULL en 1v1, ciblage implicite)
    try:
        cur.execute("ALTER TABLE combat_charge ADD COLUMN cible_user_id INTEGER")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_statuts (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            statut TEXT NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (combat_id, user_id, pokemon_nom)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_terrain (
            combat_id INTEGER NOT NULL,
            cible_user_id INTEGER NOT NULL,
            effet TEXT NOT NULL,
            stacks INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (combat_id, cible_user_id, effet)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_pp (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            attaque_nom TEXT NOT NULL,
            pp_restant INTEGER NOT NULL,
            PRIMARY KEY (combat_id, user_id, pokemon_nom, attaque_nom)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS spawns_actifs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS raid_actuel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_nom TEXT NOT NULL,
            etoiles INTEGER NOT NULL DEFAULT 1,
            channel_id TEXT,
            pv_max INTEGER NOT NULL,
            pv_actuel INTEGER NOT NULL,
            date_fin INTEGER NOT NULL,
            message_id TEXT,
            actif INTEGER NOT NULL DEFAULT 1,
            ko_declenche INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dresseurs_actifs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archetype_nom TEXT NOT NULL,
            channel_id TEXT,
            message_id TEXT,
            date_expiration INTEGER NOT NULL,
            defie_par INTEGER,
            combat_id INTEGER,
            actif INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    # Un spawn de dresseur est désormais accessible à TOUS les joueurs pendant sa fenêtre
    # de disponibilité (comme un spawn Pokémon classique), pas juste au premier arrivé.
    # Cette table retient qui a déjà affronté quel spawn, pour empêcher un même joueur de
    # le re-défier en boucle tant qu'il est actif.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dresseur_defis (
            dresseur_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (dresseur_id, user_id)
        )
        """
    )

    # Migration pour les bases créées avant l'ajout de la fenêtre de grâce
    try:
        cur.execute("ALTER TABLE raid_actuel ADD COLUMN ko_declenche INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant la refonte multi-channel des raids
    for colonne, definition in (
        ("etoiles", "INTEGER NOT NULL DEFAULT 1"),
        ("channel_id", "TEXT"),
    ):
        try:
            cur.execute(f"ALTER TABLE raid_actuel ADD COLUMN {colonne} {definition}")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS raid_participants (
            raid_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            degats_total INTEGER NOT NULL DEFAULT 0,
            dernier_attaque INTEGER NOT NULL DEFAULT 0,
            tentatives_capture_restantes INTEGER NOT NULL DEFAULT 0,
            capture_reussie INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (raid_id, user_id)
        )
        """
    )

    # Migration pour les bases créées avant les tentatives de capture multiples par raid
    for colonne, definition in (
        ("tentatives_capture_restantes", "INTEGER NOT NULL DEFAULT 0"),
        ("capture_reussie", "INTEGER NOT NULL DEFAULT 0"),
    ):
        try:
            cur.execute(f"ALTER TABLE raid_participants ADD COLUMN {colonne} {definition}")
        except sqlite3.OperationalError:
            pass  # la colonne existe déjà

    # Emoji Discord personnalisés (sprite réel) uploadés sur le serveur pour remplacer
    # les emoji Unicode génériques dans les menus déroulants d'objets (boutique, équiper).
    # Rempli par la commande admin /admin-importer-emojis-objets, pas au démarrage.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS emoji_objet (
            cle TEXT PRIMARY KEY,
            emoji_id INTEGER NOT NULL,
            emoji_nom TEXT NOT NULL
        )
        """
    )

    # Quête principale (narration) — chapitre courant + progression dans CE chapitre.
    # Tout le monde démarre à chapitre=1 (pas de rattrapage rétroactif, choix explicite).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS quete_principale_progression (
            user_id INTEGER PRIMARY KEY,
            chapitre INTEGER NOT NULL DEFAULT 1,
            compteur INTEGER NOT NULL DEFAULT 0,
            termine INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    conn.commit()
    conn.close()


def enregistrer_emoji_objet(cle: str, emoji_id: int, emoji_nom: str):
    """Sauvegarde l'ID d'un emoji personnalisé Discord uploadé pour un objet
    (clé interne de capacites.OBJETS_TENUS / formes_objets.FORMES_OBJETS / pokemon_data.IMAGE_SOINS)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO emoji_objet (cle, emoji_id, emoji_nom) VALUES (?, ?, ?)",
        (cle, emoji_id, emoji_nom),
    )
    conn.commit()
    conn.close()


def obtenir_emojis_objets() -> dict:
    """Retourne {cle: (emoji_id, emoji_nom)} pour tous les emoji personnalisés déjà importés."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT cle, emoji_id, emoji_nom FROM emoji_objet")
    resultat = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    conn.close()
    return resultat


def obtenir_progression_quete_principale(user_id: int) -> dict:
    """Retourne {"chapitre": int, "compteur": int, "termine": bool} — crée la ligne au
    chapitre 1 si le joueur n'a encore jamais été vu par ce système."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO quete_principale_progression (user_id) VALUES (?)",
        (user_id,),
    )
    conn.commit()
    cur.execute(
        "SELECT chapitre, compteur, termine FROM quete_principale_progression WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return {"chapitre": row["chapitre"], "compteur": row["compteur"], "termine": bool(row["termine"])}


def avancer_quete_principale(user_id: int, evenement: str, montant: int = 1) -> dict | None:
    """Fait progresser la quête principale si `evenement` correspond à l'objectif du
    chapitre EN COURS du joueur (les événements pour un chapitre déjà passé ou pas encore
    atteint sont ignorés silencieusement). Retourne un dict de notification de chapitre
    tout juste complété (titre/outro/récompense + éventuel nouveau chapitre à annoncer) si
    CET appel vient de faire franchir le seuil, sinon None. La récompense est créditée
    immédiatement (pas d'étape de réclamation séparée, contrairement aux quêtes jour/semaine)."""
    import config

    chapitres = config.QUETE_PRINCIPALE_CHAPITRES
    progression = obtenir_progression_quete_principale(user_id)
    if progression["termine"]:
        return None

    index_chapitre = progression["chapitre"] - 1
    if index_chapitre >= len(chapitres):
        return None

    chapitre_actuel = chapitres[index_chapitre]
    if chapitre_actuel["evenement"] != evenement:
        return None

    conn = get_connexion()
    cur = conn.cursor()
    nouveau_compteur = min(chapitre_actuel["cible"], progression["compteur"] + montant)
    cur.execute(
        "UPDATE quete_principale_progression SET compteur = ? WHERE user_id = ?",
        (nouveau_compteur, user_id),
    )
    conn.commit()

    if nouveau_compteur < chapitre_actuel["cible"]:
        conn.close()
        return None

    # Chapitre complété à l'instant : crédite la récompense, avance au suivant (ou marque
    # la quête entière comme terminée si c'était le dernier chapitre).
    recompense = chapitre_actuel["recompense"]
    if recompense.get("dollars"):
        ajouter_poke_dollars(user_id, round(recompense["dollars"] * multiplicateur_boost(user_id, "argent")))
    if recompense.get("xp"):
        import leveling
        leveling.gagner_xp(user_id, recompense["xp"])
    if recompense.get("objet"):
        ajouter_balls(user_id, recompense["objet"], 1)

    est_dernier_chapitre = index_chapitre + 1 >= len(chapitres)
    if est_dernier_chapitre:
        cur.execute(
            "UPDATE quete_principale_progression SET termine = 1 WHERE user_id = ?",
            (user_id,),
        )
    else:
        cur.execute(
            "UPDATE quete_principale_progression SET chapitre = chapitre + 1, compteur = 0 WHERE user_id = ?",
            (user_id,),
        )
    conn.commit()
    conn.close()

    return {
        "chapitre_titre": chapitre_actuel["titre"],
        "chapitre_outro": chapitre_actuel["outro"],
        "recompense": recompense,
        "termine": est_dernier_chapitre,
        "prochain_chapitre": chapitres[index_chapitre + 1] if not est_dernier_chapitre else None,
    }



def obtenir_parametre(cle: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT valeur FROM settings WHERE cle = ?", (cle,))
    row = cur.fetchone()
    conn.close()
    return row["valeur"] if row else None


def definir_parametre(cle: str, valeur: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings (cle, valeur) VALUES (?, ?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        (cle, valeur),
    )
    conn.commit()
    conn.close()


TAILLE_MAX_EQUIPE_COMBAT = 6


def obtenir_equipe_combat(user_id: int) -> list:
    """Retourne la liste des noms de Pokémon dans l'équipe de combat, dans l'ordre d'ajout."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pokemon_nom FROM equipe_combat WHERE user_id = ? ORDER BY id",
        (user_id,),
    )
    resultats = [row["pokemon_nom"] for row in cur.fetchall()]
    conn.close()
    return resultats


def deplacer_pokemon_equipe(user_id: int, pokemon_nom: str, direction: int) -> list:
    """Déplace un Pokémon d'un cran dans l'équipe (direction=-1 pour monter, +1 pour
    descendre), en échangeant sa place avec son voisin. Ne fait rien s'il est déjà en
    bout de liste. Retourne le nouvel ordre complet de l'équipe."""
    ordre = obtenir_equipe_combat(user_id)
    if pokemon_nom not in ordre:
        return ordre

    index_actuel = ordre.index(pokemon_nom)
    nouvel_index = index_actuel + direction
    if not (0 <= nouvel_index < len(ordre)):
        return ordre  # déjà tout en haut ou tout en bas

    ordre[index_actuel], ordre[nouvel_index] = ordre[nouvel_index], ordre[index_actuel]

    # Réécrit l'équipe dans le nouvel ordre (l'ordre suit l'id d'insertion, donc on
    # vide puis on réinsère dans la séquence voulue — aucune autre table ne référence
    # equipe_combat.id, cette réécriture est donc sans risque).
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM equipe_combat WHERE user_id = ?", (user_id,))
    for nom in ordre:
        cur.execute("INSERT INTO equipe_combat (user_id, pokemon_nom) VALUES (?, ?)", (user_id, nom))
    conn.commit()
    conn.close()
    return ordre


def ajouter_a_equipe_combat(user_id: int, pokemon_nom: str) -> bool:
    """Ajoute une espèce à l'équipe de combat. Retourne False si l'équipe est déjà pleine
    ou si l'espèce y est déjà (l'appelant doit aussi vérifier que le joueur la possède)."""
    equipe_actuelle = obtenir_equipe_combat(user_id)
    if len(equipe_actuelle) >= TAILLE_MAX_EQUIPE_COMBAT or pokemon_nom in equipe_actuelle:
        return False

    conn = get_connexion()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO equipe_combat (user_id, pokemon_nom) VALUES (?, ?)",
            (user_id, pokemon_nom),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True


def retirer_de_equipe_combat(user_id: int, pokemon_nom: str) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM equipe_combat WHERE user_id = ? AND pokemon_nom = ?",
        (user_id, pokemon_nom),
    )
    supprime = cur.rowcount > 0
    conn.commit()
    conn.close()
    return supprime


def vider_equipe_combat(user_id: int):
    """Retire tous les Pokémon de l'équipe de combat (utile avant de la reconstituer)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM equipe_combat WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


TAILLE_MAX_PRESETS_EQUIPE = 5


def obtenir_noms_presets_equipe(user_id: int) -> list:
    """Retourne les noms des équipes pré-configurées du joueur, dans l'ordre de création."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT nom_preset, MIN(id) AS premier_id FROM equipe_presets_combat "
        "WHERE user_id = ? GROUP BY nom_preset ORDER BY premier_id",
        (user_id,),
    )
    resultats = [row["nom_preset"] for row in cur.fetchall()]
    conn.close()
    return resultats


def obtenir_preset_equipe(user_id: int, nom_preset: str) -> list:
    """Retourne la liste ordonnée des Pokémon d'une équipe pré-configurée."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pokemon_nom FROM equipe_presets_combat WHERE user_id = ? AND nom_preset = ? ORDER BY id",
        (user_id, nom_preset),
    )
    resultats = [row["pokemon_nom"] for row in cur.fetchall()]
    conn.close()
    return resultats


def sauvegarder_preset_equipe(user_id: int, nom_preset: str, noms_pokemon: list) -> bool:
    """Enregistre (ou écrase si le nom existe déjà) une équipe pré-configurée à partir de
    la liste de noms donnée. Retourne False si le joueur a atteint son nombre maximum
    d'équipes sauvegardées et que nom_preset n'en fait pas déjà partie."""
    presets_existants = obtenir_noms_presets_equipe(user_id)
    if nom_preset not in presets_existants and len(presets_existants) >= TAILLE_MAX_PRESETS_EQUIPE:
        return False

    conn = get_connexion()
    cur = conn.cursor()
    # Écrase l'ancienne version si ce nom existait déjà (permet de "mettre à jour" une
    # équipe sauvegardée en la resauvegardant sous le même nom).
    cur.execute(
        "DELETE FROM equipe_presets_combat WHERE user_id = ? AND nom_preset = ?",
        (user_id, nom_preset),
    )
    for nom in noms_pokemon[:TAILLE_MAX_EQUIPE_COMBAT]:
        cur.execute(
            "INSERT INTO equipe_presets_combat (user_id, nom_preset, pokemon_nom) VALUES (?, ?, ?)",
            (user_id, nom_preset, nom),
        )
    conn.commit()
    conn.close()
    return True


def supprimer_preset_equipe(user_id: int, nom_preset: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM equipe_presets_combat WHERE user_id = ? AND nom_preset = ?",
        (user_id, nom_preset),
    )
    conn.commit()
    conn.close()


def obtenir_niveau_pokemon(user_id: int, pokemon_nom: str) -> tuple:
    """Retourne (niveau, xp) d'un Pokémon précis pour ce joueur — (1, 0) par défaut s'il
    n'a encore jamais gagné d'XP dans l'équipe."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT niveau, xp FROM niveaux_pokemon WHERE user_id = ? AND pokemon_nom = ?",
        (user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return 1, 0
    return row["niveau"], row["xp"]


def definir_niveau_xp_pokemon(user_id: int, pokemon_nom: str, niveau: int, xp: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO niveaux_pokemon (user_id, pokemon_nom, niveau, xp) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, pokemon_nom) DO UPDATE SET niveau = excluded.niveau, xp = excluded.xp
        """,
        (user_id, pokemon_nom, niveau, xp),
    )
    conn.commit()
    conn.close()


def possede_ct(user_id: int, nom_attaque: str) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM ct_possedees WHERE user_id = ? AND nom_attaque = ?",
        (user_id, nom_attaque),
    )
    trouve = cur.fetchone() is not None
    conn.close()
    return trouve


def acheter_ct(user_id: int, nom_attaque: str):
    """Enregistre la CT comme possédée définitivement par ce joueur — utilisable sur
    n'importe lequel de ses Pokémon, sans limite, dès maintenant et pour toujours."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO ct_possedees (user_id, nom_attaque) VALUES (?, ?)",
        (user_id, nom_attaque),
    )
    conn.commit()
    conn.close()


def obtenir_ct_possedees(user_id: int) -> set:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT nom_attaque FROM ct_possedees WHERE user_id = ?", (user_id,))
    resultats = {row["nom_attaque"] for row in cur.fetchall()}
    conn.close()
    return resultats


def obtenir_paires_sans_niveau() -> list:
    """Paires (user_id, pokemon_nom) qui ont au moins une capture mais aucune ligne dans
    niveaux_pokemon — Pokémon capturés avant la mise en place du système de niveau.
    Utilisé uniquement par la commande d'admin /backfill-niveaux."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT c.user_id AS user_id, c.pokemon_nom AS pokemon_nom
        FROM captures c
        LEFT JOIN niveaux_pokemon n ON n.user_id = c.user_id AND n.pokemon_nom = c.pokemon_nom
        WHERE n.user_id IS NULL
        """
    )
    resultats = [(row["user_id"], row["pokemon_nom"]) for row in cur.fetchall()]
    conn.close()
    return resultats


def obtenir_toutes_paires_capturees() -> list:
    """Toutes les paires (user_id, pokemon_nom) distinctes ayant au moins une capture,
    qu'elles aient déjà une ligne de niveau ou non. Utilisé uniquement par le mode
    --forcer de /backfill-niveaux (écrase un niveau déjà acquis par un nouveau tirage)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id, pokemon_nom FROM captures")
    resultats = [(row["user_id"], row["pokemon_nom"]) for row in cur.fetchall()]
    conn.close()
    return resultats


def reinitialiser_pool_raid_joueur(user_id: int):
    """(Re)synchronise le pool de PV du raid (etat_combat_pokemon_raid) sur l'état RÉEL et
    ACTUEL du joueur (etat_combat_pokemon, le pool "normal") — appelé au démarrage du
    combat de CHAQUE raid.

    Historique : la 1ère version de cette fonction se contentait de VIDER le pool raid
    (donc, faute de ligne, obtenir_pv_actuels le lisait comme "plein" par défaut). Ça
    corrigeait bien le bug du boss increvable (une équipe K.O. par un raid précédent ne
    restait plus bloquée à vie), MAIS ça soignait aussi gratuitement, sans potion,
    n'importe quel dégât pris juste avant en combat dresseur/Arène/PvP (signalé par un
    joueur : "je sors d'un combat dresseur, je lance un raid, mon équipe est full vie").
    En copiant l'état RÉEL du pool normal au lieu de tout remettre à plein, on corrige les
    deux bugs à la fois : l'équipe entre dans le raid dans l'état où elle était vraiment
    (blessée si elle l'était, pleine sinon), sans jamais rester bloquée par une VIEILLE
    riposte de raid oubliée. Les dégâts pris PENDANT ce raid sont resynchronisés vers le
    pool normal à la fin du raid (voir terminer_raid) : la blessure persiste après,
    comme n'importe quel autre combat — plus de soin gratuit d'un côté ni de l'autre."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM etat_combat_pokemon_raid WHERE user_id = ?", (user_id,))
    cur.execute(
        """
        INSERT INTO etat_combat_pokemon_raid (user_id, pokemon_nom, pv_actuels)
        SELECT user_id, pokemon_nom, pv_actuels FROM etat_combat_pokemon WHERE user_id = ?
        """,
        (user_id,),
    )
    conn.commit()
    conn.close()


def joueur_dans_raid_actif(user_id: int) -> bool:
    """True si ce joueur est actuellement inscrit à un raid en cours — sert à savoir si
    le soin depuis le profil doit cibler le pool de PV du raid (voir contexte="raid" sur
    obtenir_pv_actuels/modifier_pv_pokemon) plutôt que le pool normal."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM raid_participants rp
        JOIN raid_actuel r ON r.id = rp.raid_id
        WHERE rp.user_id = ? AND r.actif = 1
        LIMIT 1
        """,
        (user_id,),
    )
    trouve = cur.fetchone() is not None
    conn.close()
    return trouve


def obtenir_points_saison(user_id: int, saison: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT points FROM saison_points WHERE user_id = ? AND saison = ?", (user_id, saison))
    row = cur.fetchone()
    conn.close()
    return row["points"] if row else 0


def ajouter_points_saison(user_id: int, saison: int, montant: int) -> int:
    """Ajoute des points de saison, retourne le nouveau total pour cette saison."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO saison_points (user_id, saison, points) VALUES (?, ?, ?)
        ON CONFLICT(user_id, saison) DO UPDATE SET points = points + excluded.points
        """,
        (user_id, saison, montant),
    )
    conn.commit()
    cur.execute("SELECT points FROM saison_points WHERE user_id = ? AND saison = ?", (user_id, saison))
    total = cur.fetchone()["points"]
    conn.close()
    return total


def enregistrer_parrainage(filleul_id: int, inviteur_id: int) -> bool:
    """Enregistre qu'un nouveau membre (filleul_id) a rejoint via l'invitation de
    inviteur_id — EN ATTENTE de confirmation (voir confirmer_parrainage), pas encore
    compté dans les récompenses. Retourne False si ce filleul est déjà enregistré (ne
    compte jamais deux fois, même s'il quitte et revient)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM parrainages WHERE filleul_id = ?", (filleul_id,))
    if cur.fetchone() is not None:
        conn.close()
        return False
    cur.execute(
        "INSERT INTO parrainages (filleul_id, inviteur_id, date_join, confirme) VALUES (?, ?, ?, 0)",
        (filleul_id, inviteur_id, int(time.time())),
    )
    conn.commit()
    conn.close()
    return True


def supprimer_parrainage_non_confirme(filleul_id: int):
    """À appeler quand un filleul quitte le serveur AVANT d'être confirmé (voir
    config.PARRAINAGE_DELAI_JOURS) — son parrainage ne doit jamais compter. Ne fait rien
    si le parrainage est déjà confirmé (aucune reprise après coup)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM parrainages WHERE filleul_id = ? AND confirme = 0", (filleul_id,))
    conn.commit()
    conn.close()


def obtenir_parrainages_a_confirmer(delai_secondes: int) -> list:
    """Parrainages encore en attente dont le délai minimum (config.PARRAINAGE_DELAI_JOURS)
    est écoulé — à vérifier (le filleul est-il toujours là ?) puis confirmer si oui."""
    conn = get_connexion()
    cur = conn.cursor()
    seuil = int(time.time()) - delai_secondes
    cur.execute(
        "SELECT filleul_id, inviteur_id FROM parrainages WHERE confirme = 0 AND date_join <= ?",
        (seuil,),
    )
    resultats = [(row["filleul_id"], row["inviteur_id"]) for row in cur.fetchall()]
    conn.close()
    return resultats


def confirmer_parrainage(filleul_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE parrainages SET confirme = 1 WHERE filleul_id = ?", (filleul_id,))
    conn.commit()
    conn.close()


def compter_parrainages(inviteur_id: int) -> int:
    """Ne compte que les parrainages CONFIRMÉS (filleul resté le délai minimum)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS n FROM parrainages WHERE inviteur_id = ? AND confirme = 1",
        (inviteur_id,),
    )
    n = cur.fetchone()["n"]
    conn.close()
    return n


def obtenir_paliers_parrainage_recus(user_id: int) -> set:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT palier FROM parrainage_paliers_recus WHERE user_id = ?", (user_id,))
    resultats = {row["palier"] for row in cur.fetchall()}
    conn.close()
    return resultats


def marquer_palier_parrainage_recu(user_id: int, palier: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO parrainage_paliers_recus (user_id, palier) VALUES (?, ?)",
        (user_id, palier),
    )
    conn.commit()
    conn.close()


def est_booster_serveur(user_id: int) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute("SELECT booster_serveur FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row["booster_serveur"]) if row else False


def definir_booster_serveur(user_id: int, actif: bool):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute("UPDATE users SET booster_serveur = ? WHERE user_id = ?", (int(actif), user_id))
    conn.commit()
    conn.close()


def obtenir_record_plus_ou_moins(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT meilleur_score FROM record_plus_ou_moins WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["meilleur_score"] if row else 0


def definir_record_plus_ou_moins(user_id: int, score: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO record_plus_ou_moins (user_id, meilleur_score) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET meilleur_score = excluded.meilleur_score
        """,
        (user_id, score),
    )
    conn.commit()
    conn.close()


def _assurer_joueur_existe(cur, user_id: int):
    """Crée l'entrée du joueur avec ses balls de départ s'il n'existe pas encore."""
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        for ball_type, quantite in BALLS_DEPART.items():
            cur.execute(
                "INSERT INTO inventaire_balls (user_id, ball_type, quantite) VALUES (?, ?, ?)",
                (user_id, ball_type, quantite),
            )


# --- Joueur / économie ---

def ajouter_poke_dollars(user_id: int, montant: int):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "UPDATE users SET poke_dollars = poke_dollars + ? WHERE user_id = ?",
        (montant, user_id),
    )
    conn.commit()
    conn.close()


def obtenir_poke_dollars(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute("SELECT poke_dollars FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["poke_dollars"] if row else 0


def obtenir_xp(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute("SELECT xp_dresseur FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["xp_dresseur"] if row else 0


def ajouter_xp(user_id: int, montant: int) -> int:
    """Ajoute de l'XP et retourne la nouvelle XP totale du joueur."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "UPDATE users SET xp_dresseur = xp_dresseur + ? WHERE user_id = ?",
        (montant, user_id),
    )
    conn.commit()
    cur.execute("SELECT xp_dresseur FROM users WHERE user_id = ?", (user_id,))
    nouvelle_xp = cur.fetchone()["xp_dresseur"]
    conn.close()
    return nouvelle_xp


# --- Équipes ---

def obtenir_statut_equipe(user_id: int):
    """Retourne (equipe_actuelle, peut_changer_gratuitement, secondes_avant_prochain_changement)."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute("SELECT team, team_last_change FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()

    equipe = row["team"]
    if equipe is None:
        return equipe, True, 0  # premier choix toujours gratuit

    dernier_changement = row["team_last_change"] or 0
    temps_ecoule = time.time() - dernier_changement
    if temps_ecoule >= config.COOLDOWN_CHANGEMENT_EQUIPE:
        return equipe, True, 0

    return equipe, False, int(config.COOLDOWN_CHANGEMENT_EQUIPE - temps_ecoule)


def changer_equipe(user_id: int, nouvelle_equipe: str):
    """Change le clan d'un joueur et enregistre la date du changement (à n'appeler qu'après
    avoir vérifié via obtenir_statut_equipe que c'est autorisé). Remet aussi à zéro sa
    contribution personnelle (rang au sein du clan) — elle ne suit pas le joueur d'une
    équipe à l'autre, comme demandé."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "UPDATE users SET team = ?, team_last_change = ? WHERE user_id = ?",
        (nouvelle_equipe, int(time.time()), user_id),
    )
    cur.execute(
        """
        INSERT INTO clan_contribution (user_id, equipe, points) VALUES (?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET equipe = excluded.equipe, points = 0
        """,
        (user_id, nouvelle_equipe),
    )
    conn.commit()
    conn.close()


def obtenir_equipe(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute("SELECT team FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["team"] if row else None


def classement_equipes():
    """Retourne un score par équipe : nombre de captures À VIE (jamais réduit par un
    relâcher de doublon) + somme des PC des membres (celle-ci reste "en direct", cohérent
    puisque c'est une mesure de la force ACTUELLE de l'équipe, pas d'un cumul historique)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            u.team AS equipe,
            COALESCE((
                SELECT SUM(s.captures_totales) FROM stats_lifetime s
                JOIN users u2 ON u2.user_id = s.user_id WHERE u2.team = u.team
            ), 0) AS total_captures,
            COALESCE((
                SELECT SUM(c.pc) FROM captures c
                JOIN users u3 ON u3.user_id = c.user_id WHERE u3.team = u.team
            ), 0) AS total_pc
        FROM users u
        WHERE u.team IS NOT NULL
        GROUP BY u.team
        """
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def classement_contribution_clan(equipe: str, limite: int = 10) -> list:
    """Top contributeurs AU SEIN d'une équipe précise (classement interne)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, points FROM clan_contribution WHERE equipe = ? ORDER BY points DESC LIMIT ?",
        (equipe, limite),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def obtenir_contribution_clan(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT points FROM clan_contribution WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["points"] if row else 0


def _debut_semaine_courante() -> int:
    """Timestamp (UTC, 00:00) du lundi de la semaine en cours — sert de clé stable pour
    savoir si un nouvel objectif hebdomadaire doit être généré."""
    maintenant = time.gmtime()
    jours_depuis_lundi = maintenant.tm_wday  # 0 = lundi
    minuit_aujourdhui = int(time.time()) - (maintenant.tm_hour * 3600 + maintenant.tm_min * 60 + maintenant.tm_sec)
    return minuit_aujourdhui - jours_depuis_lundi * 86400


def obtenir_objectif_semaine_actif() -> dict:
    """Retourne l'objectif hebdomadaire de clan en cours — le CRÉE s'il n'existe pas
    encore pour cette semaine (1er appel de la semaine, par n'importe quel joueur ou par
    la boucle de fond). Toujours le même objectif pour les 3 équipes, tirage aléatoire
    dans OBJECTIFS_CLAN_POSSIBLES (voir config.py)."""
    import random as _random

    semaine_debut = _debut_semaine_courante()
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clan_objectif_semaine WHERE semaine_debut = ?", (semaine_debut,))
    row = cur.fetchone()

    if row is None:
        type_choisi, cible = _random.choice(config.OBJECTIFS_CLAN_POSSIBLES)
        cur.execute(
            "INSERT INTO clan_objectif_semaine (semaine_debut, type, cible) VALUES (?, ?, ?)",
            (semaine_debut, type_choisi, cible),
        )
        objectif_id = cur.lastrowid
        for equipe in config.COULEURS_EQUIPES:
            cur.execute(
                "INSERT INTO clan_objectif_progres (objectif_id, equipe, progres) VALUES (?, ?, 0)",
                (objectif_id, equipe),
            )
        conn.commit()
        resultat = {"id": objectif_id, "semaine_debut": semaine_debut, "type": type_choisi, "cible": cible}
    else:
        resultat = dict(row)

    conn.close()
    return resultat


def obtenir_progres_objectif(objectif_id: int, equipe: str) -> dict:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM clan_objectif_progres WHERE objectif_id = ? AND equipe = ?",
        (objectif_id, equipe),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {"progres": 0, "complete_le": None, "butin_recupere": 0}


def obtenir_tous_progres_objectif(objectif_id: int) -> dict:
    """{equipe: dict(progres, complete_le, butin_recupere)} pour les 3 équipes d'un coup."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clan_objectif_progres WHERE objectif_id = ?", (objectif_id,))
    resultats = {row["equipe"]: dict(row) for row in cur.fetchall()}
    conn.close()
    return resultats


def ajouter_contribution_clan(user_id: int, categorie: str, points: int):
    """Ajoute des points de contribution à un joueur (rang personnel au sein de son
    équipe) ET fait avancer l'objectif hebdomadaire de SON équipe si `categorie`
    correspond au type de l'objectif actif. Ne fait rien si le joueur n'a pas encore
    choisi d'équipe. `categorie` : "capture" ou "combat".

    Si l'équipe vient tout juste d'atteindre l'objectif avec cet appel, récompense
    IMMÉDIATEMENT tous ses membres actuels (voir config.CLAN_OBJECTIF_RECOMPENSE_BASE /
    CLAN_OBJECTIF_BONUS_PREMIER) — pas de réclamation manuelle séparée, pour rester simple."""
    equipe = obtenir_equipe(user_id)
    if not equipe:
        return

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO clan_contribution (user_id, equipe, points) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET points = points + excluded.points
        """,
        (user_id, equipe, points),
    )
    conn.commit()
    conn.close()

    objectif = obtenir_objectif_semaine_actif()
    if objectif["type"] != categorie:
        return

    progres_avant = obtenir_progres_objectif(objectif["id"], equipe)
    if progres_avant["complete_le"]:
        return  # cette équipe a déjà fini cet objectif cette semaine, plus rien à avancer

    conn = get_connexion()
    cur = conn.cursor()
    nouveau_progres = progres_avant["progres"] + points
    vient_de_finir = progres_avant["progres"] < objectif["cible"] <= nouveau_progres
    if vient_de_finir:
        cur.execute(
            "UPDATE clan_objectif_progres SET progres = ?, complete_le = ? WHERE objectif_id = ? AND equipe = ?",
            (nouveau_progres, int(time.time()), objectif["id"], equipe),
        )
    else:
        cur.execute(
            "UPDATE clan_objectif_progres SET progres = ? WHERE objectif_id = ? AND equipe = ?",
            (nouveau_progres, objectif["id"], equipe),
        )
    conn.commit()
    conn.close()

    if vient_de_finir:
        _distribuer_recompense_objectif_clan(objectif["id"], equipe)


def _distribuer_recompense_objectif_clan(objectif_id: int, equipe: str):
    """Verse la récompense à TOUS les membres actuels de l'équipe qui vient de finir
    l'objectif — un bonus supplémentaire si c'est la toute première équipe des 3 à
    l'avoir fait cette semaine (déterminé par le complete_le le plus ancien)."""
    import journal

    tous_progres = obtenir_tous_progres_objectif(objectif_id)
    completions = [(e, p["complete_le"]) for e, p in tous_progres.items() if p["complete_le"]]
    premiere_equipe = min(completions, key=lambda t: t[1])[0] if completions else None
    est_premiere = equipe == premiere_equipe

    recompense = config.CLAN_OBJECTIF_RECOMPENSE_BASE + (config.CLAN_OBJECTIF_BONUS_PREMIER if est_premiere else 0)

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE team = ?", (equipe,))
    membres = [row["user_id"] for row in cur.fetchall()]
    conn.close()

    for membre_id in membres:
        ajouter_poke_dollars(membre_id, recompense)

    cur_texte = "🏆 première équipe à finir !" if est_premiere else "objectif atteint"
    journal.logger(
        f"🛡️ Clan {equipe} a atteint l'objectif hebdomadaire ({cur_texte}) — "
        f"{recompense} PD versés à {len(membres)} membre(s)."
    )


def cloturer_saison_clan_si_necessaire():
    """Archive le classement du mois PRÉCÉDENT dans clan_saison_historique, une seule
    fois par mois — à appeler périodiquement (boucle de fond). Ne fait rien tant qu'on
    est encore dans le même mois que la dernière clôture."""
    import journal

    maintenant = time.gmtime()
    saison_actuelle = time.strftime("%Y-%m", maintenant)

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT MAX(saison) AS derniere FROM clan_saison_historique")
    row = cur.fetchone()
    derniere_saison_archivee = row["derniere"] if row else None
    conn.close()

    if derniere_saison_archivee == saison_actuelle:
        return  # déjà fait pour ce mois-ci

    premier_du_mois = time.struct_time((maintenant.tm_year, maintenant.tm_mon, 1, 0, 0, 0, 0, 0, 0))
    dernier_jour_mois_precedent = time.gmtime(time.mktime(premier_du_mois) - 86400)
    saison_a_archiver = time.strftime("%Y-%m", dernier_jour_mois_precedent)

    if derniere_saison_archivee == saison_a_archiver:
        return  # déjà archivé

    classement = sorted(classement_equipes(), key=lambda r: r["total_pc"], reverse=True)
    if not classement:
        return

    conn = get_connexion()
    cur = conn.cursor()
    for rang, row in enumerate(classement, start=1):
        cur.execute(
            "INSERT OR IGNORE INTO clan_saison_historique (saison, equipe, rang, score) VALUES (?, ?, ?, ?)",
            (saison_a_archiver, row["equipe"], rang, row["total_pc"]),
        )
    conn.commit()
    conn.close()
    journal.logger(f"🛡️ Saison de clan {saison_a_archiver} archivée ({len(classement)} équipe(s) classée(s)).")


def obtenir_historique_saisons_clan(limite_saisons: int = 6) -> list:
    """Les N dernières saisons archivées, plus récente d'abord — [(saison, [(equipe,
    rang, score), ...]), ...]."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT saison FROM clan_saison_historique ORDER BY saison DESC LIMIT ?",
        (limite_saisons,),
    )
    saisons = [row["saison"] for row in cur.fetchall()]

    resultats = []
    for saison in saisons:
        cur.execute(
            "SELECT equipe, rang, score FROM clan_saison_historique WHERE saison = ? ORDER BY rang ASC",
            (saison,),
        )
        resultats.append((saison, [(r["equipe"], r["rang"], r["score"]) for r in cur.fetchall()]))
    conn.close()
    return resultats


def classement_captures_individuelles(limite: int = 5):
    """Top joueurs par nombre total de captures À VIE (jamais réduit par un relâcher de
    doublon, contrairement à un simple COUNT sur les captures encore en base)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, captures_totales AS total_captures
        FROM stats_lifetime
        WHERE captures_totales > 0
        ORDER BY total_captures DESC
        LIMIT ?
        """,
        (limite,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def classement_poke_dollars(limite: int = 5):
    """Top joueurs par solde de Poké Dollars."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, poke_dollars FROM users ORDER BY poke_dollars DESC LIMIT ?",
        (limite,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def classement_completion_pokedex(limite: int = 5):
    """Top joueurs par nombre d'espèces différentes capturées."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, COUNT(DISTINCT pokemon_nom) AS especes_distinctes
        FROM captures
        GROUP BY user_id
        ORDER BY especes_distinctes DESC
        LIMIT ?
        """,
        (limite,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def obtenir_classement_personnel(user_id: int) -> dict:
    """Position exacte d'un joueur (et sa valeur) parmi TOUS les joueurs enregistrés,
    pour Poké Dollars, captures totales et complétion du pokédex."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()

    # Poké Dollars
    cur.execute("SELECT user_id, poke_dollars, RANK() OVER (ORDER BY poke_dollars DESC) AS rang FROM users")
    lignes = cur.fetchall()
    total_joueurs = len(lignes)
    rang_dollars = valeur_dollars = 0
    for row in lignes:
        if row["user_id"] == user_id:
            rang_dollars, valeur_dollars = row["rang"], row["poke_dollars"]
            break

    # Captures totales (tous les joueurs comptent, même à 0 capture)
    cur.execute(
        """
        WITH agg AS (
            SELECT u.user_id AS uid, COALESCE(COUNT(c.id), 0) AS total
            FROM users u LEFT JOIN captures c ON c.user_id = u.user_id
            GROUP BY u.user_id
        )
        SELECT uid, total, RANK() OVER (ORDER BY total DESC) AS rang FROM agg
        """
    )
    rang_captures = valeur_captures = 0
    for row in cur.fetchall():
        if row["uid"] == user_id:
            rang_captures, valeur_captures = row["rang"], row["total"]
            break

    # Complétion du pokédex (espèces distinctes)
    cur.execute(
        """
        WITH agg AS (
            SELECT u.user_id AS uid, COUNT(DISTINCT c.pokemon_nom) AS especes
            FROM users u LEFT JOIN captures c ON c.user_id = u.user_id
            GROUP BY u.user_id
        )
        SELECT uid, especes, RANK() OVER (ORDER BY especes DESC) AS rang FROM agg
        """
    )
    rang_pokedex = valeur_pokedex = 0
    for row in cur.fetchall():
        if row["uid"] == user_id:
            rang_pokedex, valeur_pokedex = row["rang"], row["especes"]
            break

    conn.close()
    return {
        "total_joueurs": total_joueurs,
        "rang_dollars": rang_dollars,
        "valeur_dollars": valeur_dollars,
        "rang_captures": rang_captures,
        "valeur_captures": valeur_captures,
        "rang_pokedex": rang_pokedex,
        "valeur_pokedex": valeur_pokedex,
    }


# --- Inventaire de balls ---

def obtenir_inventaire_balls(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute(
        "SELECT ball_type, quantite FROM inventaire_balls WHERE user_id = ?",
        (user_id,),
    )
    # "honorball" est géré séparément par raid (tentatives de capture, table raid_participants)
    # et ne doit jamais figurer dans l'inventaire général — un résidu peut néanmoins traîner
    # en base depuis une ancienne version, d'où ce filtre systématique.
    resultats = {row["ball_type"]: row["quantite"] for row in cur.fetchall() if row["ball_type"] != "honorball"}
    conn.close()
    return resultats


def retirer_ball(user_id: int, ball_type: str) -> bool:
    """Retire une ball de l'inventaire si disponible. Retourne False si le stock est vide."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "SELECT quantite FROM inventaire_balls WHERE user_id = ? AND ball_type = ?",
        (user_id, ball_type),
    )
    row = cur.fetchone()
    if not row or row["quantite"] <= 0:
        conn.close()
        return False
    cur.execute(
        "UPDATE inventaire_balls SET quantite = quantite - 1 WHERE user_id = ? AND ball_type = ?",
        (user_id, ball_type),
    )
    conn.commit()
    conn.close()
    return True


def retirer_plusieurs_balls(user_id: int, ball_type: str, quantite: int) -> bool:
    """Retire une quantité précise d'un objet, seulement si le stock est suffisant.
    Retourne False (sans rien retirer) si le joueur n'en a pas assez."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "SELECT quantite FROM inventaire_balls WHERE user_id = ? AND ball_type = ?",
        (user_id, ball_type),
    )
    row = cur.fetchone()
    if not row or row["quantite"] < quantite:
        conn.close()
        return False
    cur.execute(
        "UPDATE inventaire_balls SET quantite = quantite - ? WHERE user_id = ? AND ball_type = ?",
        (quantite, user_id, ball_type),
    )
    conn.commit()
    conn.close()
    return True


def ajouter_balls(user_id: int, ball_type: str, quantite: int):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        """
        INSERT INTO inventaire_balls (user_id, ball_type, quantite)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, ball_type) DO UPDATE SET quantite = quantite + excluded.quantite
        """,
        (user_id, ball_type, quantite),
    )
    conn.commit()
    conn.close()


def transformer_objets(user_id: int, type_source: str) -> tuple:
    """Convertit AUTANT DE LOTS COMPLETS que possible de `type_source` (10 par lot, voir
    config.CHAINES_TRANSFORMATION) vers le palier supérieur — ex: 47 Poké Balls → 4 Super
    Balls + il reste 7 Poké Balls. Retourne (nb_lots_convertis, type_cible, quantite_source_consommee).
    (0, None, 0) si le type n'est pas convertible ou s'il n'y a pas de quoi faire un lot complet."""
    if type_source not in config.CHAINES_TRANSFORMATION:
        return 0, None, 0
    type_cible, quantite_requise = config.CHAINES_TRANSFORMATION[type_source]

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT quantite FROM inventaire_balls WHERE user_id = ? AND ball_type = ?",
        (user_id, type_source),
    )
    row = cur.fetchone()
    quantite_actuelle = row["quantite"] if row else 0
    nb_lots = quantite_actuelle // quantite_requise
    if nb_lots <= 0:
        conn.close()
        return 0, None, 0

    quantite_consommee = nb_lots * quantite_requise
    cur.execute(
        "UPDATE inventaire_balls SET quantite = quantite - ? WHERE user_id = ? AND ball_type = ?",
        (quantite_consommee, user_id, type_source),
    )
    conn.commit()
    conn.close()

    ajouter_balls(user_id, type_cible, nb_lots)
    return nb_lots, type_cible, quantite_consommee


# --- Captures / Pokédex ---

def obtenir_captures_sans_ivs() -> list:
    """IDs des captures qui n'ont pas encore d'IV (créées avant cette refonte). Utilisé
    uniquement par la commande d'admin /backfill-ivs."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT id FROM captures WHERE iv_pv IS NULL")
    resultats = [row["id"] for row in cur.fetchall()]
    conn.close()
    return resultats


def obtenir_captures_sans_talent() -> list:
    """(id, pokemon_nom) des captures qui n'ont pas encore de talent (créées avant cette
    fonctionnalité). Utilisé uniquement par la commande d'admin /backfill-talents."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT id, pokemon_nom FROM captures WHERE capacite IS NULL")
    resultats = [(row["id"], row["pokemon_nom"]) for row in cur.fetchall()]
    conn.close()
    return resultats


def obtenir_captures_avec_talent() -> list:
    """(id, pokemon_nom, capacite) de TOUTES les captures ayant déjà un talent — pour que
    /backfill-talents puisse repérer celles dont le talent actuel ne correspond plus aux
    vraies aptitudes curatées de l'espèce (attribué avant que sa curation n'existe) et le
    re-tirer. Le filtrage précis (quelles espèces/talents sont concernés) se fait côté
    Python dans main.py, contre capacites.POKEMON_CAPACITES."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT id, pokemon_nom, capacite FROM captures WHERE capacite IS NOT NULL")
    resultats = [(row["id"], row["pokemon_nom"], row["capacite"]) for row in cur.fetchall()]
    conn.close()
    return resultats


def definir_capacite_capture(capture_id: int, capacite: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE captures SET capacite = ? WHERE id = ?", (capacite, capture_id))
    conn.commit()
    conn.close()


def definir_ivs_capture(capture_id: int, ivs: dict):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE captures SET iv_pv = ?, iv_attaque = ?, iv_defense = ?,
            iv_attaque_spe = ?, iv_defense_spe = ?, iv_vitesse = ?
        WHERE id = ?
        """,
        (
            ivs.get("pv"), ivs.get("attaque"), ivs.get("defense"),
            ivs.get("attaque_spe"), ivs.get("defense_spe"), ivs.get("vitesse"),
            capture_id,
        ),
    )
    conn.commit()
    conn.close()


def creer_arene_spawn(type_arene: str, channel_id: int, date_expiration: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO arene_spawn (type_arene, channel_id, date_expiration) VALUES (?, ?, ?)",
        (type_arene, str(channel_id), date_expiration),
    )
    arene_id = cur.lastrowid
    conn.commit()
    conn.close()
    return arene_id


def obtenir_arene_spawn(arene_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM arene_spawn WHERE id = ?", (arene_id,))
    row = cur.fetchone()
    conn.close()
    return row


def obtenir_run_arene(arene_id: int, user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM arene_runs WHERE arene_spawn_id = ? AND user_id = ?", (arene_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def creer_run_arene(arene_id: int, user_id: int) -> bool:
    """Crée le run d'un joueur pour cette arène — retourne False s'il en a déjà un
    (une seule tentative par joueur et par spawn, gagnée ou perdue)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM arene_runs WHERE arene_spawn_id = ? AND user_id = ?", (arene_id, user_id))
    if cur.fetchone() is not None:
        conn.close()
        return False
    cur.execute(
        "INSERT INTO arene_runs (arene_spawn_id, user_id, etape, statut) VALUES (?, ?, 0, 'en_cours')",
        (arene_id, user_id),
    )
    conn.commit()
    conn.close()
    return True


def avancer_run_arene(arene_id: int, user_id: int, nouvelle_etape: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE arene_runs SET etape = ? WHERE arene_spawn_id = ? AND user_id = ?",
        (nouvelle_etape, arene_id, user_id),
    )
    conn.commit()
    conn.close()


def terminer_run_arene(arene_id: int, user_id: int, statut: str):
    """statut : 'victoire' (Champion battu) ou 'defaite'."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE arene_runs SET statut = ? WHERE arene_spawn_id = ? AND user_id = ?",
        (statut, arene_id, user_id),
    )
    conn.commit()
    conn.close()


def possede_badge_arene(user_id: int, type_pokemon: str) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM arene_badges WHERE user_id = ? AND type_pokemon = ?", (user_id, type_pokemon))
    trouve = cur.fetchone() is not None
    conn.close()
    return trouve


def accorder_badge_arene(user_id: int, type_pokemon: str) -> bool:
    """Retourne True si c'est un NOUVEAU badge (première fois), False s'il l'avait déjà."""
    if possede_badge_arene(user_id, type_pokemon):
        return False
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO arene_badges (user_id, type_pokemon, date_obtenu) VALUES (?, ?, ?)",
        (user_id, type_pokemon, int(time.time())),
    )
    conn.commit()
    conn.close()
    avancer_quete_principale(user_id, "badge_arene")
    return True


def obtenir_badges_arene(user_id: int) -> set:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type_pokemon FROM arene_badges WHERE user_id = ?", (user_id,))
    resultats = {row["type_pokemon"] for row in cur.fetchall()}
    conn.close()
    return resultats


# ----------------------------------------------------------------------------
# Repaires de méchants — mêmes mécaniques que l'arène ci-dessus, mais indexées par
# équipe_mechante (ex: "Team Rocket") au lieu du type Pokémon, et le badge donne un
# bonus permanent à une CATÉGORIE (capture/shiny/argent/xp, voir
# config.EQUIPES_MECHANTES["categorie_bonus"]) plutôt qu'un bonus de dégâts par type —
# se greffe sur le même multiplicateur_boost() que les Races. Voir repaires.py.
# ----------------------------------------------------------------------------

def creer_repaire_spawn(equipe_mechante: str, channel_id: int, date_expiration: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO repaire_spawn (equipe_mechante, channel_id, date_expiration) VALUES (?, ?, ?)",
        (equipe_mechante, str(channel_id), date_expiration),
    )
    repaire_id = cur.lastrowid
    conn.commit()
    conn.close()
    return repaire_id


def obtenir_repaire_spawn(repaire_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM repaire_spawn WHERE id = ?", (repaire_id,))
    row = cur.fetchone()
    conn.close()
    return row


def creer_run_repaire(repaire_id: int, user_id: int) -> bool:
    """Crée le run d'un joueur pour ce repaire — retourne False s'il en a déjà un
    (une seule tentative par joueur et par spawn, gagnée ou perdue)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM repaire_runs WHERE repaire_spawn_id = ? AND user_id = ?", (repaire_id, user_id))
    if cur.fetchone() is not None:
        conn.close()
        return False
    cur.execute(
        "INSERT INTO repaire_runs (repaire_spawn_id, user_id, etape, statut) VALUES (?, ?, 0, 'en_cours')",
        (repaire_id, user_id),
    )
    conn.commit()
    conn.close()
    return True


def avancer_run_repaire(repaire_id: int, user_id: int, nouvelle_etape: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE repaire_runs SET etape = ? WHERE repaire_spawn_id = ? AND user_id = ?",
        (nouvelle_etape, repaire_id, user_id),
    )
    conn.commit()
    conn.close()


def terminer_run_repaire(repaire_id: int, user_id: int, statut: str):
    """statut : 'victoire' (Boss battu) ou 'defaite'."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE repaire_runs SET statut = ? WHERE repaire_spawn_id = ? AND user_id = ?",
        (statut, repaire_id, user_id),
    )
    conn.commit()
    conn.close()


def possede_badge_repaire(user_id: int, equipe_mechante: str) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM repaire_badges WHERE user_id = ? AND equipe_mechante = ?", (user_id, equipe_mechante))
    trouve = cur.fetchone() is not None
    conn.close()
    return trouve


def accorder_badge_repaire(user_id: int, equipe_mechante: str) -> bool:
    """Retourne True si c'est un NOUVEAU badge (première fois), False s'il l'avait déjà."""
    if possede_badge_repaire(user_id, equipe_mechante):
        return False
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO repaire_badges (user_id, equipe_mechante, date_obtenu) VALUES (?, ?, ?)",
        (user_id, equipe_mechante, int(time.time())),
    )
    conn.commit()
    conn.close()
    avancer_quete_principale(user_id, "badge_repaire")
    return True


def obtenir_badges_repaire(user_id: int) -> set:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT equipe_mechante FROM repaire_badges WHERE user_id = ?", (user_id,))
    resultats = {row["equipe_mechante"] for row in cur.fetchall()}
    conn.close()
    return resultats


def multiplicateur_repaire_du_jour(user_id: int) -> float:
    """Équivalent de multiplicateur_arene_du_jour, pour les repaires."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM repaire_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    conn.close()
    compteur = row["compteur"] if row else 0
    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    return paliers[min(compteur, len(paliers) - 1)]


def enregistrer_victoire_repaire_repetition(user_id: int) -> float:
    """Équivalent de enregistrer_victoire_arene_repetition, pour les repaires."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM repaire_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0

    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    multiplicateur = paliers[min(compteur_avant, len(paliers) - 1)]

    cur.execute(
        """
        INSERT INTO repaire_victoires_jour (user_id, jour_id, compteur)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (user_id, jour_id),
    )
    conn.commit()
    conn.close()
    return multiplicateur


def obtenir_meilleures_ivs(user_id: int, pokemon_nom: str) -> dict:
    """IV de la MEILLEURE capture (plus haut PC) de cette espèce pour ce joueur — c'est
    cet individu-là qui est utilisé en combat (équipe de combat = par espèce, pas par
    capture précise). Retourne None si aucune capture n'a d'IV enregistrées (anciennes
    captures d'avant cette refonte) — l'appelant doit alors utiliser un profil neutre."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT iv_pv, iv_attaque, iv_defense, iv_attaque_spe, iv_defense_spe, iv_vitesse
        FROM captures WHERE user_id = ? AND pokemon_nom = ? AND iv_pv IS NOT NULL
        ORDER BY pc DESC LIMIT 1
        """,
        (user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "pv": row["iv_pv"], "attaque": row["iv_attaque"], "defense": row["iv_defense"],
        "attaque_spe": row["iv_attaque_spe"], "defense_spe": row["iv_defense_spe"], "vitesse": row["iv_vitesse"],
    }


def obtenir_capacite_reelle(user_id: int, pokemon_nom: str) -> str | None:
    """Talent de la MEILLEURE capture (plus haut PC) de cette espèce — même individu que
    celui utilisé en combat (voir obtenir_meilleures_ivs)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT capacite FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC LIMIT 1",
        (user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["capacite"] if row else None


def definir_capacite_reelle(user_id: int, pokemon_nom: str, capacite: str):
    """Change le talent de la MEILLEURE capture de cette espèce (celle utilisée en combat)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE captures SET capacite = ? WHERE id = (
            SELECT id FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC LIMIT 1
        )
        """,
        (capacite, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def obtenir_objet_tenu_reel(user_id: int, pokemon_nom: str) -> str | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT objet_tenu FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC LIMIT 1",
        (user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["objet_tenu"] if row else None


def definir_objet_tenu_reel(user_id: int, pokemon_nom: str, objet: str | None):
    """objet=None retire l'objet tenu."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE captures SET objet_tenu = ? WHERE id = (
            SELECT id FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC LIMIT 1
        )
        """,
        (objet, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def ajouter_capture(user_id: int, pokemon_nom: str, pc: int, shiny: bool = False, ivs: dict = None) -> str | None:
    import capacites as capacites_module
    import formes_objets as formes_objets_module
    import random as _random

    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    ivs = ivs or {}

    cur.execute(
        """
        INSERT INTO captures (
            user_id, pokemon_nom, pc, date_capture, shiny,
            iv_pv, iv_attaque, iv_defense, iv_attaque_spe, iv_defense_spe, iv_vitesse,
            capacite
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, pokemon_nom, pc, int(time.time()), int(shiny),
            ivs.get("pv"), ivs.get("attaque"), ivs.get("defense"),
            ivs.get("attaque_spe"), ivs.get("defense_spe"), ivs.get("vitesse"),
            capacites_module.capacite_pour_espece(pokemon_nom),
        ),
    )
    # Compteurs à VIE (jamais décrémentés, même si la capture est relâchée plus tard) —
    # utilisés par les classements "Plus de captures"/"Plus de shiny", qui comptaient
    # auparavant les lignes encore en base et baissaient donc quand on relâchait des doublons.
    cur.execute(
        """
        INSERT INTO stats_lifetime (user_id, captures_totales, shiny_totaux)
        VALUES (?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            captures_totales = captures_totales + 1,
            shiny_totaux = shiny_totaux + excluded.shiny_totaux
        """,
        (user_id, int(shiny)),
    )
    conn.commit()
    conn.close()

    # Chance qu'une capture (N'IMPORTE QUELLE espèce, comme les cristaux de mutation ou
    # les œufs) donne AUSSI un objet de transformation au hasard dans le sac — voir
    # formes_objets.py. Ne s'équipe jamais automatiquement sur le Pokémon capturé, comme
    # une baie de mutation ou un œuf : le joueur l'équipe lui-même ensuite s'il le veut.
    objet_forme_obtenu = None
    if _random.random() < config.CHANCE_OBJET_FORME_A_LA_CAPTURE:
        objet_forme_obtenu = _random.choice(list(formes_objets_module.FORMES_OBJETS.keys()))
        ajouter_balls(user_id, objet_forme_obtenu, 1)
    return objet_forme_obtenu


def obtenir_pokedex_joueur(user_id: int):
    """Retourne, par espèce (et par variante shiny) : nombre capturé et meilleur PC obtenu."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pokemon_nom, shiny, COUNT(*) AS quantite, MAX(pc) AS meilleur_pc
        FROM captures
        WHERE user_id = ?
        GROUP BY pokemon_nom, shiny
        ORDER BY pokemon_nom COLLATE ALPHABET_FR
        """,
        (user_id,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def obtenir_stats_joueur(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(DISTINCT pokemon_nom) AS especes, COUNT(*) AS total FROM captures WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return (row["especes"] or 0), (row["total"] or 0)


def compter_captures_totales(user_id: int) -> int:
    """Nombre total de Pokémon stockés par un joueur (toutes espèces confondues)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total FROM captures WHERE user_id = ?", (user_id,))
    total = cur.fetchone()["total"]
    conn.close()
    return total


# --- PV de combat (par joueur + espèce, voir raid.py pour la formule de calcul du max) ---

def obtenir_pv_actuels(user_id: int, pokemon_nom: str, pv_max: int, contexte: str = "normal") -> int:
    """Retourne les PV actuels d'une espèce en combat (initialisés au max si jamais vue).
    Si le max a augmenté depuis (meilleur PC capturé), les PV actuels sont juste plafonnés
    au nouveau max, sans soin gratuit. contexte="raid" utilise un pool de PV totalement
    séparé (voir etat_combat_pokemon_raid) — combattre en raid n'affecte jamais les PV
    utilisés en PvP/dresseur/Arène/Gladio, et inversement."""
    table = "etat_combat_pokemon_raid" if contexte == "raid" else "etat_combat_pokemon"
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        f"SELECT pv_actuels FROM {table} WHERE user_id = ? AND pokemon_nom = ?",
        (user_id, pokemon_nom),
    )
    row = cur.fetchone()
    if row is None:
        cur.execute(
            f"INSERT INTO {table} (user_id, pokemon_nom, pv_actuels) VALUES (?, ?, ?)",
            (user_id, pokemon_nom, pv_max),
        )
        conn.commit()
        conn.close()
        return pv_max

    pv_actuels = min(row["pv_actuels"], pv_max)
    conn.close()
    return pv_actuels


def modifier_pv_pokemon(user_id: int, pokemon_nom: str, delta: int, pv_max: int, contexte: str = "normal") -> int:
    """Applique un delta (positif = soin, négatif = dégâts) aux PV actuels d'une espèce,
    borné entre 0 et pv_max. Retourne les PV après modification. Voir obtenir_pv_actuels
    pour le paramètre contexte."""
    table = "etat_combat_pokemon_raid" if contexte == "raid" else "etat_combat_pokemon"
    pv_actuels = obtenir_pv_actuels(user_id, pokemon_nom, pv_max, contexte)
    nouveau_pv = max(0, min(pv_max, pv_actuels + delta))

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {table} (user_id, pokemon_nom, pv_actuels) VALUES (?, ?, ?)
        ON CONFLICT(user_id, pokemon_nom) DO UPDATE SET pv_actuels = excluded.pv_actuels
        """,
        (user_id, pokemon_nom, nouveau_pv),
    )
    conn.commit()
    conn.close()
    return nouveau_pv


def soigner_completement_equipe(user_id: int, contexte: str = "normal"):
    """Remet à pleine vie TOUT le pool de PV persistants d'un joueur pour ce contexte
    (normal ou raid) — gratuit, sans consommer de potion. Supprimer les lignes suffit :
    obtenir_pv_actuels initialise déjà à pv_max quand aucune ligne n'existe (voir
    ci-dessus), donc l'absence de ligne = pleine vie, pas besoin de connaître le pv_max
    de chaque espèce individuellement.

    Utilisé quand un combat/raid est annulé pour une raison INDÉPENDANTE du joueur (ex:
    redémarrage du serveur en pleine partie) — jamais laisser une équipe blessée à cause
    d'un incident technique qui n'est pas de sa faute."""
    table = "etat_combat_pokemon_raid" if contexte == "raid" else "etat_combat_pokemon"
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def compter_captures_espece(user_id: int, pokemon_nom: str) -> int:
    """Nombre d'exemplaires possédés d'une espèce précise."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS total FROM captures WHERE user_id = ? AND pokemon_nom = ?",
        (user_id, pokemon_nom),
    )
    total = cur.fetchone()["total"]
    conn.close()
    return total


def relacher_pokemon(user_id: int, pokemon_nom: str, quantite: int) -> int:
    """Relâche jusqu'à `quantite` exemplaires d'une espèce, en gardant toujours les
    meilleurs PC (les moins bons sont relâchés en premier). Retourne le nombre réellement relâché."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc ASC LIMIT ?",
        (user_id, pokemon_nom, quantite),
    )
    ids = [row["id"] for row in cur.fetchall()]
    if ids:
        cur.executemany("DELETE FROM captures WHERE id = ?", [(i,) for i in ids])
        conn.commit()
    conn.close()
    return len(ids)



def relacher_captures_par_id(user_id: int, capture_ids: list) -> int:
    """Relâche des exemplaires précis (sélectionnés manuellement par le joueur), en
    vérifiant qu'ils appartiennent bien à ce joueur. Retourne le nombre réellement supprimé."""
    if not capture_ids:
        return 0

    conn = get_connexion()
    cur = conn.cursor()
    marqueurs = ",".join("?" for _ in capture_ids)
    cur.execute(
        f"DELETE FROM captures WHERE user_id = ? AND id IN ({marqueurs})",
        (user_id, *capture_ids),
    )
    nb_supprimes = cur.rowcount
    conn.commit()
    conn.close()
    return nb_supprimes


def previsualiser_doublons(user_id: int) -> dict:
    """Calcule ce qui SERAIT relâché par relacher_tous_doublons, sans rien supprimer.
    Retourne {pokemon_nom: quantite_relachable}. Les exemplaires VERROUILLÉS (voir
    definir_verrouillage_capture) ne sont jamais comptés, même si ce ne sont pas le
    meilleur PC de leur espèce — protège un doublon qu'on veut garder sans avoir à le
    décocher manuellement à chaque fois."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pokemon_nom, verrouille,
               ROW_NUMBER() OVER (PARTITION BY pokemon_nom ORDER BY pc DESC, id ASC) AS rang
        FROM captures
        WHERE user_id = ?
        """,
        (user_id,),
    )
    resultats = {}
    for row in cur.fetchall():
        if row["rang"] > 1 and not row["verrouille"]:
            resultats[row["pokemon_nom"]] = resultats.get(row["pokemon_nom"], 0) + 1
    conn.close()
    return resultats


def obtenir_doublons_detailles(user_id: int):
    """Comme previsualiser_doublons, mais retourne chaque exemplaire individuel
    (id, pokemon_nom, pc, shiny) plutôt qu'un simple total par espèce — utilisé pour la
    sélection manuelle (cocher précisément lesquels relâcher). Les exemplaires
    verrouillés n'apparaissent jamais dans cette liste."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, pokemon_nom, pc, shiny, verrouille,
               ROW_NUMBER() OVER (PARTITION BY pokemon_nom ORDER BY pc DESC, id ASC) AS rang
        FROM captures
        WHERE user_id = ?
        """,
        (user_id,),
    )
    resultats = [row for row in cur.fetchall() if row["rang"] > 1 and not row["verrouille"]]
    conn.close()
    return resultats


def obtenir_toutes_captures_detaillees(user_id: int):
    """Retourne TOUS les exemplaires de la collection du joueur (id, pokemon_nom, pc, shiny,
    verrouille, rang) triés par nom puis par PC décroissant. Rang = 1 signifie que c'est le
    seul/meilleur exemplaire de son espèce — utile pour afficher un avertissement si
    l'utilisateur tente de relâcher le dernier représentant d'une espèce (perte de
    l'entrée Pokédex)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, pokemon_nom, pc, shiny, verrouille,
               ROW_NUMBER() OVER (PARTITION BY pokemon_nom ORDER BY pc DESC, id ASC) AS rang,
               COUNT(*) OVER (PARTITION BY pokemon_nom) AS total_espece
        FROM captures
        WHERE user_id = ?
        ORDER BY pokemon_nom COLLATE ALPHABET_FR ASC, pc DESC
        """,
        (user_id,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def definir_verrouillage_capture(capture_id: int, verrouille: bool):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE captures SET verrouille = ? WHERE id = ?", (int(verrouille), capture_id))
    conn.commit()
    conn.close()


def obtenir_captures_verrouillees(user_id: int):
    """Tous les exemplaires actuellement verrouillés d'un joueur (id, pokemon_nom, pc,
    shiny) — utilisé pour l'écran de gestion des verrous (voir/déverrouiller)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, pokemon_nom, pc, shiny FROM captures WHERE user_id = ? AND verrouille = 1 "
        "ORDER BY pokemon_nom COLLATE ALPHABET_FR ASC, pc DESC",
        (user_id,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def relacher_tous_doublons(user_id: int) -> dict:
    """Relâche automatiquement TOUS les doublons de toutes les espèces d'un coup,
    en gardant systématiquement le meilleur PC de chaque espèce ET tout exemplaire
    verrouillé (voir definir_verrouillage_capture).
    Retourne {pokemon_nom: quantite_relachee} pour les espèces concernées."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, pokemon_nom, verrouille,
               ROW_NUMBER() OVER (PARTITION BY pokemon_nom ORDER BY pc DESC, id ASC) AS rang
        FROM captures
        WHERE user_id = ?
        """,
        (user_id,),
    )
    a_supprimer = [row for row in cur.fetchall() if row["rang"] > 1 and not row["verrouille"]]

    resultats = {}
    for row in a_supprimer:
        resultats[row["pokemon_nom"]] = resultats.get(row["pokemon_nom"], 0) + 1

    if a_supprimer:
        cur.executemany("DELETE FROM captures WHERE id = ?", [(row["id"],) for row in a_supprimer])
        conn.commit()
    conn.close()
    return resultats


def obtenir_extensions_stockage(user_id: int):
    """Retourne (nb_extensions_pokemon_achetees, nb_extensions_objets_achetees)."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute(
        "SELECT extensions_stockage_pokemon, extensions_stockage_objets FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["extensions_stockage_pokemon"], row["extensions_stockage_objets"]


def limite_stockage_pokemon(user_id: int) -> int:
    extensions_pokemon, _ = obtenir_extensions_stockage(user_id)
    return config.LIMITE_STOCKAGE_POKEMON_BASE + extensions_pokemon * config.EXTENSION_STOCKAGE_POKEMON


def limite_stockage_objets(user_id: int) -> int:
    _, extensions_objets = obtenir_extensions_stockage(user_id)
    return config.LIMITE_STOCKAGE_OBJETS_BASE + extensions_objets * config.EXTENSION_STOCKAGE_OBJETS


def acheter_extension_stockage_pokemon(user_id: int, quantite: int = 1):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "UPDATE users SET extensions_stockage_pokemon = extensions_stockage_pokemon + ? WHERE user_id = ?",
        (quantite, user_id),
    )
    conn.commit()
    conn.close()


def acheter_extension_stockage_objets(user_id: int, quantite: int = 1):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "UPDATE users SET extensions_stockage_objets = extensions_stockage_objets + ? WHERE user_id = ?",
        (quantite, user_id),
    )
    conn.commit()
    conn.close()


def compter_objets_totaux(user_id: int) -> int:
    """Nombre total d'objets possédés (toutes les balls confondues, tous types)."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute(
        "SELECT COALESCE(SUM(quantite), 0) AS total FROM inventaire_balls WHERE user_id = ?",
        (user_id,),
    )
    total = cur.fetchone()["total"]
    conn.close()
    return total


# --- PokéStop ---

def peut_utiliser_pokestop(user_id: int, cooldown_secondes: int):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute("SELECT pokestop_last_used FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    dernier_usage = row["pokestop_last_used"] if row else 0
    temps_ecoule = time.time() - dernier_usage
    if temps_ecoule >= cooldown_secondes:
        return True, 0
    return False, int(cooldown_secondes - temps_ecoule)


def marquer_pokestop_utilise(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET pokestop_last_used = ? WHERE user_id = ?",
        (int(time.time()), user_id),
    )
    conn.commit()
    conn.close()


def reinitialiser_pokestop(user_id: int):
    """Remet le cooldown PokéStop à zéro pour un joueur (utile après un bug ou pour les tests)."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "UPDATE users SET pokestop_last_used = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


# --- Raids ---

def obtenir_raid_actif_pour_channel(channel_id: int):
    """Retourne le raid actif dans CE channel précis, ou None. Permet plusieurs raids
    simultanés (un par channel de spawn).

    Auto-guérison : si un raid est resté marqué "actif" bien après sa date de fin
    théorique (ex: suite à une erreur qui a interrompu sa boucle de combat avant
    qu'elle n'ait pu le terminer proprement), il est automatiquement désactivé ici
    plutôt que de bloquer indéfiniment tout nouveau raid dans ce channel."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM raid_actuel WHERE actif = 1 AND channel_id = ? ORDER BY id DESC LIMIT 1",
        (str(channel_id),),
    )
    row = cur.fetchone()

    if row is not None:
        marge_securite = 600  # 10 minutes de marge après la date de fin théorique
        if int(time.time()) > row["date_fin"] + marge_securite:
            cur.execute("UPDATE raid_actuel SET actif = 0 WHERE id = ?", (row["id"],))
            conn.commit()
            conn.close()
            return None

    conn.close()
    return row


def obtenir_raid_par_id(raid_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM raid_actuel WHERE id = ?", (raid_id,))
    row = cur.fetchone()
    conn.close()
    return row


def demarrer_raid(boss_nom: str, etoiles: int, pv_max: int, date_fin: int, channel_id: int) -> int:
    """Crée un nouveau raid actif et retourne son id."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO raid_actuel (boss_nom, etoiles, channel_id, pv_max, pv_actuel, date_fin, actif)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (boss_nom, etoiles, str(channel_id), pv_max, pv_max, date_fin),
    )
    raid_id = cur.lastrowid
    conn.commit()
    conn.close()
    return raid_id


def definir_message_raid(raid_id: int, message_id: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE raid_actuel SET message_id = ? WHERE id = ?", (message_id, raid_id))
    conn.commit()
    conn.close()


def definir_date_fin_raid(raid_id: int, date_fin: int):
    """Repousse la date de fin du combat (utilisé quand la salle d'attente se termine
    et que le vrai chrono de combat démarre)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE raid_actuel SET date_fin = ? WHERE id = ?", (date_fin, raid_id))
    conn.commit()
    conn.close()


def redefinir_pv_max_raid(raid_id: int, nouveau_pv_max: int):
    """Fixe les PV réels du boss une fois qu'on connaît le nombre de joueurs dans le lobby
    (appelé au moment où le combat démarre, après la salle d'attente). Remet aussi les PV
    actuels au max puisque le combat n'a pas encore commencé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE raid_actuel SET pv_max = ?, pv_actuel = ? WHERE id = ?",
        (nouveau_pv_max, nouveau_pv_max, raid_id),
    )
    conn.commit()
    conn.close()


def terminer_raid(raid_id: int):
    """Termine le raid (victoire, timeout, ou annulation) ET resynchronise les dégâts pris
    par chaque participant pendant CE raid vers son pool de PV normal (persistant, partagé
    avec les combats dresseur/Arène/PvP) — sinon les dégâts de riposte s'évaporaient à la
    fin du raid : l'équipe réapparaissait full vie ailleurs, sans avoir rien soigné. Seul
    point d'appel pour toute fin de raid (victoire/timeout/annulation), donc un seul
    endroit à maintenir."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM raid_participants WHERE raid_id = ?", (raid_id,))
    participants = [row["user_id"] for row in cur.fetchall()]
    for user_id in participants:
        cur.execute(
            """
            INSERT INTO etat_combat_pokemon (user_id, pokemon_nom, pv_actuels)
            SELECT user_id, pokemon_nom, pv_actuels FROM etat_combat_pokemon_raid WHERE user_id = ?
            ON CONFLICT(user_id, pokemon_nom) DO UPDATE SET pv_actuels = excluded.pv_actuels
            """,
            (user_id,),
        )
    cur.execute("UPDATE raid_actuel SET actif = 0 WHERE id = ?", (raid_id,))
    conn.commit()
    conn.close()


def obtenir_raids_actifs() -> list:
    """Retourne tous les raids marqués actifs, tous channels confondus — utilisé
    uniquement par le nettoyage des messages orphelins au démarrage du bot."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM raid_actuel WHERE actif = 1")
    resultats = cur.fetchall()
    conn.close()
    return resultats


def enregistrer_spawn_actif(channel_id: int, message_id: int) -> int:
    """Note un spawn Pokémon (classique/VIP) en base le temps qu'il est affiché, pour
    pouvoir supprimer son message s'il traîne encore après un redémarrage du bot (sa vue
    n'est pas persistante d'un process à l'autre, donc son bouton Capturer ne fonctionne
    de toute façon plus). Retourne l'id de l'entrée créée."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO spawns_actifs (channel_id, message_id) VALUES (?, ?)",
        (str(channel_id), str(message_id)),
    )
    spawn_id = cur.lastrowid
    conn.commit()
    conn.close()
    return spawn_id


def retirer_spawn_actif(spawn_id: int):
    """À appeler une fois le message de spawn supprimé normalement (fin du timer), pour
    ne pas le considérer comme orphelin au prochain démarrage."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM spawns_actifs WHERE id = ?", (spawn_id,))
    conn.commit()
    conn.close()


def obtenir_spawns_actifs() -> list:
    """Retourne tous les spawns actuellement suivis — utilisé uniquement par le
    nettoyage des messages orphelins au démarrage du bot."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM spawns_actifs")
    resultats = cur.fetchall()
    conn.close()
    return resultats


def inscrire_participant_raid(raid_id: int, user_id: int):
    """Enregistre un joueur comme participant au combat (dégâts à 0 s'il n'existe pas déjà).
    Une fois inscrit, il est automatiquement inclus dans chaque tick de combat."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO raid_participants (raid_id, user_id, degats_total, dernier_attaque)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(raid_id, user_id) DO NOTHING
        """,
        (raid_id, user_id, int(time.time())),
    )
    conn.commit()
    conn.close()


def quitter_raid(raid_id: int, user_id: int) -> bool:
    """Retire un joueur de la liste des participants (il arrête d'être inclus dans les
    ticks de combat et ne recevra pas les récompenses si le raid est vaincu ensuite).
    Retourne True s'il a bien été retiré, False s'il n'était pas inscrit."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM raid_participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    )
    supprime = cur.rowcount > 0
    conn.commit()
    conn.close()
    return supprime


def est_participant_raid(raid_id: int, user_id: int) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM raid_participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    )
    existe = cur.fetchone() is not None
    conn.close()
    return existe


def appliquer_degats_multiples(raid_id: int, degats_par_joueur: dict) -> int:
    """Applique en une fois les dégâts d'un tick de combat pour tous les participants
    inscrits (degats_par_joueur = {user_id: degats}). Retourne les PV restants (min 0)."""
    conn = get_connexion()
    cur = conn.cursor()

    total_degats = sum(degats_par_joueur.values())
    cur.execute(
        "UPDATE raid_actuel SET pv_actuel = MAX(0, pv_actuel - ?) WHERE id = ?",
        (total_degats, raid_id),
    )
    for user_id, degats in degats_par_joueur.items():
        cur.execute(
            """
            INSERT INTO raid_participants (raid_id, user_id, degats_total, dernier_attaque)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(raid_id, user_id) DO UPDATE SET
                degats_total = degats_total + excluded.degats_total,
                dernier_attaque = excluded.dernier_attaque
            """,
            (raid_id, user_id, degats, int(time.time())),
        )
    conn.commit()

    cur.execute("SELECT pv_actuel FROM raid_actuel WHERE id = ?", (raid_id,))
    pv_restants = cur.fetchone()["pv_actuel"]
    conn.close()
    return pv_restants


def obtenir_participants_raid(raid_id: int):
    """Retourne la liste des participants (user_id, degats_total), triée par dégâts décroissants."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, degats_total FROM raid_participants WHERE raid_id = ? ORDER BY degats_total DESC",
        (raid_id,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def initialiser_tentatives_capture_raid(raid_id: int, nb_tentatives: int):
    """Donne à TOUS les participants d'un raid leurs tentatives de capture (Honor Ball
    spécifiques à ce raid — pas un objet stocké dans l'inventaire général)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE raid_participants SET tentatives_capture_restantes = ? WHERE raid_id = ?",
        (nb_tentatives, raid_id),
    )
    conn.commit()
    conn.close()


def tenter_capture_raid(raid_id: int, user_id: int):
    """Consomme atomiquement une tentative de capture si disponible et si le joueur n'a
    pas déjà capturé ce boss. Retourne (peut_tenter: bool, tentatives_restantes_apres: int)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE raid_participants
        SET tentatives_capture_restantes = tentatives_capture_restantes - 1
        WHERE raid_id = ? AND user_id = ? AND tentatives_capture_restantes > 0 AND capture_reussie = 0
        """,
        (raid_id, user_id),
    )
    peut_tenter = cur.rowcount > 0
    conn.commit()

    cur.execute(
        "SELECT tentatives_capture_restantes FROM raid_participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return peut_tenter, (row["tentatives_capture_restantes"] if row else 0)


def marquer_capture_reussie_raid(raid_id: int, user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE raid_participants SET capture_reussie = 1 WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    )
    conn.commit()
    conn.close()


def a_deja_capture_raid(raid_id: int, user_id: int) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT capture_reussie FROM raid_participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return bool(row and row["capture_reussie"])


# --- Combats PvP ---

def creer_combat(joueur1_id: int, joueur2_id: int, actif1_nom: str, actif2_nom: str, date_limite: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_pvp
            (joueur1_id, joueur2_id, actif1_nom, actif2_nom, date_debut, date_limite_tour, actif, tour)
        VALUES (?, ?, ?, ?, ?, ?, 1, 1)
        """,
        (joueur1_id, joueur2_id, actif1_nom, actif2_nom, int(time.time()), date_limite),
    )
    combat_id = cur.lastrowid
    conn.commit()
    conn.close()
    return combat_id


def definir_adversaire_combat(combat_id: int, joueur2_id: int):
    """Fixe joueur2_id après coup — utilisé pour les dresseurs, où l'ID synthétique
    de l'adversaire doit être dérivé du combat_id (connu seulement après l'INSERT)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET joueur2_id = ? WHERE id = ?", (joueur2_id, combat_id))
    conn.commit()
    conn.close()


def initialiser_equipe_combat_pvp(combat_id: int, user_id: int, equipe: list, id_reel_pour_capture: int = None):
    """Enregistre l'équipe d'un joueur pour ce combat. `equipe` est une liste de dicts
    {nom, pv, attaque, defense, attaque_spe, defense_spe, vitesse, niveau} — les stats
    complètes, déjà calculées une fois (IV + niveau) pour ne plus être re-dérivées à
    chaque tour.

    Le talent/objet tenu est fixé (snapshot) ICI, au début du combat :
    - Vrai joueur (user_id > 0) : copié depuis captures.capacite/objet_tenu (meilleur PC).
      `id_reel_pour_capture` sert pour le 2v2 : le 2e Pokémon d'un joueur y vit sous un ID
      délégué synthétique (toujours positif) différent de son vrai ID Discord — sans ce
      paramètre, la recherche dans captures échouerait puisque ses vraies captures sont
      enregistrées sous son ID réel, pas sous l'ID délégué.
    - Dresseur/boss IA (user_id < 0, jamais dans captures) : talent tiré au hasard, et un
      objet dans 50% des cas — pour que les combats PvE aient aussi du relief, pas
      seulement les combats PvP."""
    import capacites as capacites_module

    id_pour_recherche = id_reel_pour_capture if id_reel_pour_capture is not None else user_id
    conn = get_connexion()
    cur = conn.cursor()
    for i, mon in enumerate(equipe):
        if id_pour_recherche > 0:
            cur.execute(
                "SELECT capacite, objet_tenu FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC LIMIT 1",
                (id_pour_recherche, mon["nom"]),
            )
            row_source = cur.fetchone()
            capacite = row_source["capacite"] if row_source else None
            objet_tenu = row_source["objet_tenu"] if row_source else None
        else:
            capacite = capacites_module.capacite_pour_espece(mon["nom"])
            objet_tenu = random.choice(list(capacites_module.OBJETS_TENUS.keys())) if random.random() < 0.5 else None

        cur.execute(
            """
            INSERT INTO combat_equipe
                (combat_id, user_id, pokemon_nom, pv_max, pv_actuels, position, atq, defe, atq_spe, def_spe, vit, niveau, capacite, objet_tenu)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                combat_id, user_id, mon["nom"], mon["pv"], mon["pv"], i,
                mon["attaque"], mon["defense"], mon["attaque_spe"], mon["defense_spe"], mon["vitesse"],
                mon.get("niveau", 50), capacite, objet_tenu,
            ),
        )
    conn.commit()
    conn.close()


def obtenir_capacite_combat(combat_id: int, user_id: int, pokemon_nom: str) -> str | None:
    """Talent SNAPSHOTÉ pour ce combat précis (voir initialiser_equipe_combat_pvp) — à
    utiliser dans le moteur de combat plutôt que obtenir_capacite_reelle, pour que ça
    fonctionne identiquement pour un vrai joueur ET un dresseur/boss IA."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT capacite FROM combat_equipe WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["capacite"] if row else None


def obtenir_objet_combat(combat_id: int, user_id: int, pokemon_nom: str) -> str | None:
    """Objet tenu SNAPSHOTÉ pour ce combat précis — voir obtenir_capacite_combat."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT objet_tenu FROM combat_equipe WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["objet_tenu"] if row else None


def definir_objet_combat(combat_id: int, user_id: int, pokemon_nom: str, objet: str | None):
    """Consomme/retire l'objet tenu SNAPSHOTÉ pour ce combat (baie utilisée, Ceinture
    Force déclenchée...) — n'affecte JAMAIS l'objet réel hors combat (captures.objet_tenu),
    seulement cette instance de combat."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_equipe SET objet_tenu = ? WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (objet, combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def obtenir_combat(combat_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM combat_pvp WHERE id = ?", (combat_id,))
    row = cur.fetchone()
    conn.close()
    return row


def obtenir_equipe_pvp(combat_id: int, user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM combat_equipe WHERE combat_id = ? AND user_id = ? ORDER BY position",
        (combat_id, user_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def enregistrer_action_pvp(combat_id: int, user_id: int, action: str):
    """Enregistre l'action choisie par un joueur pour le tour en cours.
    action = 'attaquer' | 'potion:<type>' | 'changer:<nom>'"""
    conn = get_connexion()
    cur = conn.cursor()
    combat = obtenir_combat(combat_id)
    if combat["joueur1_id"] == user_id:
        cur.execute("UPDATE combat_pvp SET action1 = ? WHERE id = ?", (action, combat_id))
    else:
        cur.execute("UPDATE combat_pvp SET action2 = ? WHERE id = ?", (action, combat_id))
    conn.commit()
    conn.close()


def compter_potions_soin_utilisees(combat_id: int, user_id: int) -> int:
    """Nombre de potions de SOIN (PV) déjà utilisées par ce joueur dans ce combat — le
    Total Soin n'est pas compté (voir LIMITE_POTIONS_SOIN_COMBAT)."""
    combat = obtenir_combat(combat_id)
    if combat is None:
        return 0
    colonne = "potions_soin1" if combat["joueur1_id"] == user_id else "potions_soin2"
    return combat[colonne]


def incrementer_potions_soin_utilisees(combat_id: int, user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    combat = obtenir_combat(combat_id)
    colonne = "potions_soin1" if combat["joueur1_id"] == user_id else "potions_soin2"
    cur.execute(f"UPDATE combat_pvp SET {colonne} = {colonne} + 1 WHERE id = ?", (combat_id,))
    conn.commit()
    conn.close()


def appliquer_degats_pvp(combat_id: int, user_id: int, pokemon_nom: str, degats: int) -> int:
    """Applique des dégâts au Pokémon actif d'un joueur. Retourne les PV restants."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_equipe SET pv_actuels = MAX(0, pv_actuels - ?) WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (degats, combat_id, user_id, pokemon_nom),
    )
    cur.execute(
        "SELECT pv_actuels FROM combat_equipe WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    pv = cur.fetchone()["pv_actuels"]
    conn.commit()
    conn.close()
    return pv


def soigner_pvp(combat_id: int, user_id: int, pokemon_nom: str, montant: int) -> int:
    """Soigne un Pokémon pendant le combat. Retourne les nouveaux PV."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pv_max FROM combat_equipe WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    pv_max = row["pv_max"] if row else 0
    cur.execute(
        "UPDATE combat_equipe SET pv_actuels = MIN(pv_max, pv_actuels + ?) WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (montant, combat_id, user_id, pokemon_nom),
    )
    cur.execute(
        "SELECT pv_actuels FROM combat_equipe WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    pv = cur.fetchone()["pv_actuels"]
    conn.commit()
    conn.close()
    return pv


def changer_pokemon_actif_pvp(combat_id: int, user_id: int, nouveau_nom: str):
    conn = get_connexion()
    cur = conn.cursor()
    combat = obtenir_combat(combat_id)
    if combat["joueur1_id"] == user_id:
        cur.execute("UPDATE combat_pvp SET actif1_nom = ? WHERE id = ?", (nouveau_nom, combat_id))
    else:
        cur.execute("UPDATE combat_pvp SET actif2_nom = ? WHERE id = ?", (nouveau_nom, combat_id))
    conn.commit()
    conn.close()


def passer_tour_pvp(combat_id: int, date_limite: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_pvp SET tour = tour + 1, action1 = NULL, action2 = NULL, date_limite_tour = ? WHERE id = ?",
        (date_limite, combat_id),
    )
    conn.commit()
    conn.close()


def creer_choix_ko(combat_id: int, user_id: int, date_limite: int, relais: bool = False):
    """Le Pokémon actif de ce joueur vient de tomber K.O. (ou quitte volontairement le
    combat, Change Éclair/Demi-Tour/Relais) : on attend son choix de remplaçant jusqu'à
    date_limite (au-delà, envoi automatique — anti-AFK). `relais=True` signale que les
    boosts de stats de l'actif sortant doivent être transférés au remplaçant choisi
    (Relais/Baton Pass) au lieu d'être simplement réinitialisés — voir copier_boosts."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO combat_choix_ko (combat_id, user_id, date_limite, relais) VALUES (?, ?, ?, ?)",
        (combat_id, user_id, date_limite, int(relais)),
    )
    conn.commit()
    conn.close()


def obtenir_choix_ko(combat_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT user_id, date_limite, relais FROM combat_choix_ko WHERE combat_id = ?", (combat_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def supprimer_choix_ko(combat_id: int, user_id: int) -> bool:
    """Retire le choix en attente (le joueur a choisi, ou l'envoi auto a eu lieu).
    Retourne False si la ligne n'existait plus (déjà traitée — évite les doubles envois)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM combat_choix_ko WHERE combat_id = ? AND user_id = ?", (combat_id, user_id))
    supprime = cur.rowcount > 0
    conn.commit()
    conn.close()
    return supprime


def creer_joueurs_2v2(combat_id: int, inscriptions: list):
    """inscriptions = [(user_id, equipe, actif_nom), ...] — les 4 joueurs d'un combat 2v2.
    Le combat_id est celui de la ligne d'ancrage dans combat_pvp (même espace d'IDs que
    toutes les tables annexes : combat_equipe, combat_pp, combat_boosts...)."""
    conn = get_connexion()
    cur = conn.cursor()
    for user_id, equipe, actif_nom in inscriptions:
        cur.execute(
            "INSERT INTO combat_2v2_joueurs (combat_id, user_id, equipe, actif_nom) VALUES (?, ?, ?, ?)",
            (combat_id, user_id, equipe, actif_nom),
        )
    conn.commit()
    conn.close()


def obtenir_joueurs_2v2(combat_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, equipe, actif_nom, action, abandonne, potions_soin FROM combat_2v2_joueurs "
        "WHERE combat_id = ? ORDER BY equipe, user_id",
        (combat_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def definir_action_2v2(combat_id: int, user_id: int, action: str) -> bool:
    """Enregistre l'action du tour pour ce joueur. False si une action était déjà posée
    (protection double-clic, comme enregistrer_action_pvp en 1v1)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_2v2_joueurs SET action = ? WHERE combat_id = ? AND user_id = ? AND action IS NULL",
        (action, combat_id, user_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def vider_actions_2v2(combat_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_2v2_joueurs SET action = NULL WHERE combat_id = ?", (combat_id,))
    conn.commit()
    conn.close()


def definir_actif_2v2(combat_id: int, user_id: int, actif_nom: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_2v2_joueurs SET actif_nom = ? WHERE combat_id = ? AND user_id = ?",
        (actif_nom, combat_id, user_id),
    )
    conn.commit()
    conn.close()


def marquer_abandon_2v2(combat_id: int, user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_2v2_joueurs SET abandonne = 1, action = NULL WHERE combat_id = ? AND user_id = ?",
        (combat_id, user_id),
    )
    conn.commit()
    conn.close()


def incrementer_potions_2v2(combat_id: int, user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_2v2_joueurs SET potions_soin = potions_soin + 1 WHERE combat_id = ? AND user_id = ?",
        (combat_id, user_id),
    )
    cur.execute("SELECT potions_soin FROM combat_2v2_joueurs WHERE combat_id = ? AND user_id = ?", (combat_id, user_id))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    return row["potions_soin"] if row else 0


def obtenir_combats_pvp_actifs():
    """Tous les combats (PvP, dresseur, Arène, Gladio) encore marqués actifs — utilisé
    uniquement par le nettoyage au démarrage : après un redémarrage, leurs boucles de
    résolution n'existent plus dans le nouveau process, ils doivent être clôturés en
    forfait pour ne pas bloquer les joueurs ("déjà en combat")."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT id, joueur1_id, joueur2_id, thread_id FROM combat_pvp WHERE actif = 1")
    rows = cur.fetchall()
    conn.close()
    return rows


def marquer_runs_arene_en_cours_defaite() -> int:
    """Marque perdus tous les runs d'arène encore 'en_cours' (nettoyage au démarrage :
    leur combat a été clôturé en forfait, le run ne peut plus continuer). Retourne le
    nombre de runs concernés."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE arene_runs SET statut = 'defaite' WHERE statut = 'en_cours'")
    nb = cur.rowcount
    conn.commit()
    conn.close()
    return nb


def terminer_combat_pvp(combat_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET actif = 0 WHERE id = ?", (combat_id,))
    cur.execute("DELETE FROM combat_choix_ko WHERE combat_id = ?", (combat_id,))
    cur.execute("DELETE FROM combat_2v2_joueurs WHERE combat_id = ?", (combat_id,))
    conn.commit()
    conn.close()


def combat_en_cours_pour_joueur(user_id: int):
    """Retourne le combat actif d'un joueur, ou None. Nettoie au passage tout combat resté
    actif=1 dont le tour n'a plus avancé depuis longtemps — signe que la boucle de résolution
    censée le terminer a disparu avec un redémarrage du bot en plein combat. Sans ça, un
    combat fantôme bloquerait le joueur indéfiniment."""
    conn = get_connexion()
    cur = conn.cursor()
    seuil_abandon = int(time.time()) - COMBAT_ABANDON_SECONDES
    cur.execute(
        "UPDATE combat_pvp SET actif = 0 WHERE actif = 1 AND (joueur1_id = ? OR joueur2_id = ?) "
        "AND date_limite_tour < ?",
        (user_id, user_id, seuil_abandon),
    )
    conn.commit()
    cur.execute(
        "SELECT * FROM combat_pvp WHERE actif = 1 AND (joueur1_id = ? OR joueur2_id = ?) LIMIT 1",
        (user_id, user_id),
    )
    row = cur.fetchone()
    if row is None:
        # Combats 2v2 : seuls 2 des 4 joueurs figurent sur la ligne d'ancrage combat_pvp
        # (capitaines) — les deux autres sont dans combat_2v2_joueurs. Sans cette jointure,
        # ils pourraient s'inscrire à un 2e combat en parallèle.
        cur.execute(
            """
            SELECT c.* FROM combat_pvp c
            JOIN combat_2v2_joueurs j ON j.combat_id = c.id
            WHERE c.actif = 1 AND j.user_id = ?
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
    conn.close()
    return row


def obtenir_combat_par_thread(thread_id: int):
    """Retourne le combat (actif ou récemment terminé) associé à un fil Discord, ou None.
    Utilisé pour la modération du fil public (seuls les combattants peuvent y écrire)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM combat_pvp WHERE thread_id = ? ORDER BY id DESC LIMIT 1", (str(thread_id),))
    row = cur.fetchone()
    conn.close()
    return row


# --- Attaques équipées (choisies chez le Maître des Types, persistantes hors combat) ---

def equiper_attaque(user_id: int, pokemon_nom: str, slot: int, attaque_nom: str):
    """Place une attaque dans un des 4 emplacements (1-4) d'un Pokémon."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO attaques_equipees (user_id, pokemon_nom, slot, attaque_nom)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, pokemon_nom, slot) DO UPDATE SET attaque_nom = excluded.attaque_nom
        """,
        (user_id, pokemon_nom, slot, attaque_nom),
    )
    conn.commit()
    conn.close()


def equiper_attaque_draft(combat_id: int, user_id: int, pokemon_nom: str, slot: int, attaque_nom: str):
    """Comme equiper_attaque, mais dans une table dédiée au Draft PvP (draft_pvp.py) —
    ne touche JAMAIS le loadout permanent du joueur pour cette espèce, même s'il la
    possède réellement. Voir obtenir_attaques_equipees(..., combat_id=...)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO draft_attaques_equipees (combat_id, user_id, pokemon_nom, slot, attaque_nom)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(combat_id, user_id, pokemon_nom, slot) DO UPDATE SET attaque_nom = excluded.attaque_nom
        """,
        (combat_id, user_id, pokemon_nom, slot, attaque_nom),
    )
    conn.commit()
    conn.close()


def retirer_attaque(user_id: int, pokemon_nom: str, slot: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM attaques_equipees WHERE user_id = ? AND pokemon_nom = ? AND slot = ?",
        (user_id, pokemon_nom, slot),
    )
    conn.commit()
    conn.close()


def obtenir_attaques_equipees(user_id: int, pokemon_nom: str, combat_id: int = None) -> dict:
    """Retourne {slot: attaque_nom} pour un Pokémon (slots 1-4, absents si vides). Si
    combat_id est fourni et qu'un loadout Draft PvP existe pour ce combat précis, il a
    priorité sur le loadout permanent du joueur (jamais modifié par le Draft)."""
    conn = get_connexion()
    cur = conn.cursor()

    if combat_id is not None:
        cur.execute(
            "SELECT slot, attaque_nom FROM draft_attaques_equipees WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ? ORDER BY slot",
            (combat_id, user_id, pokemon_nom),
        )
        resultat_draft = {row["slot"]: row["attaque_nom"] for row in cur.fetchall()}
        if resultat_draft:
            conn.close()
            return resultat_draft

    cur.execute(
        "SELECT slot, attaque_nom FROM attaques_equipees WHERE user_id = ? AND pokemon_nom = ? ORDER BY slot",
        (user_id, pokemon_nom),
    )
    resultat = {row["slot"]: row["attaque_nom"] for row in cur.fetchall()}
    conn.close()
    return resultat


# --- Boosts de stats en combat (stages -6..+6, réinitialisés au changement de Pokémon) ---

def obtenir_boosts(combat_id: int, user_id: int, pokemon_nom: str) -> dict:
    """Retourne {'atk','def','atk_spe','def_spe','vit','precision','esquive'} (0 partout
    si jamais boosté)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT stage_atk, stage_def, stage_atk_spe, stage_def_spe, stage_vit, stage_precision, stage_esquive "
        "FROM combat_boosts WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"atk": 0, "def": 0, "atk_spe": 0, "def_spe": 0, "vit": 0, "precision": 0, "esquive": 0}
    return {
        "atk": row["stage_atk"], "def": row["stage_def"],
        "atk_spe": row["stage_atk_spe"], "def_spe": row["stage_def_spe"],
        "vit": row["stage_vit"], "precision": row["stage_precision"], "esquive": row["stage_esquive"],
    }


def modifier_boost(combat_id: int, user_id: int, pokemon_nom: str, stat: str, delta: int) -> int:
    """Applique un delta de stage à une stat (atk/def/atk_spe/def_spe/vit/precision/esquive),
    borné entre -6 et +6. Retourne le nouveau stage."""
    boosts = obtenir_boosts(combat_id, user_id, pokemon_nom)
    nouveau = max(-6, min(6, boosts[stat] + delta))
    boosts[stat] = nouveau

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_boosts
            (combat_id, user_id, pokemon_nom, stage_atk, stage_def, stage_atk_spe, stage_def_spe, stage_vit, stage_precision, stage_esquive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(combat_id, user_id, pokemon_nom) DO UPDATE SET
            stage_atk = excluded.stage_atk,
            stage_def = excluded.stage_def,
            stage_atk_spe = excluded.stage_atk_spe,
            stage_def_spe = excluded.stage_def_spe,
            stage_vit = excluded.stage_vit,
            stage_precision = excluded.stage_precision,
            stage_esquive = excluded.stage_esquive
        """,
        (
            combat_id, user_id, pokemon_nom, boosts["atk"], boosts["def"], boosts["atk_spe"], boosts["def_spe"],
            boosts["vit"], boosts["precision"], boosts["esquive"],
        ),
    )
    conn.commit()
    conn.close()
    return nouveau


def reinitialiser_boosts(combat_id: int, user_id: int, pokemon_nom: str):
    """Réinitialise les boosts d'un Pokémon (appelé quand il quitte le terrain)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM combat_boosts WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def copier_boosts(combat_id: int, user_id: int, nom_source: str, nom_dest: str):
    """Relais/Baton Pass : transfère les stages de stats de l'actif sortant (nom_source)
    au remplaçant qui entre (nom_dest), au lieu de les réinitialiser comme un changement
    normal. Écrase les boosts déjà présents chez le remplaçant (ne les additionne pas —
    comme dans les vrais jeux, où un seul Pokémon n'a jamais de boosts avant d'entrer).
    N'efface PAS les boosts de la source : à appeler juste avant reinitialiser_boosts sur
    la source, pas à la place."""
    boosts_source = obtenir_boosts(combat_id, user_id, nom_source)
    if all(v == 0 for v in boosts_source.values()):
        return  # rien à transférer, évite une ligne combat_boosts vide inutile
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_boosts
            (combat_id, user_id, pokemon_nom, stage_atk, stage_def, stage_atk_spe, stage_def_spe, stage_vit, stage_precision, stage_esquive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(combat_id, user_id, pokemon_nom) DO UPDATE SET
            stage_atk = excluded.stage_atk,
            stage_def = excluded.stage_def,
            stage_atk_spe = excluded.stage_atk_spe,
            stage_def_spe = excluded.stage_def_spe,
            stage_vit = excluded.stage_vit,
            stage_precision = excluded.stage_precision,
            stage_esquive = excluded.stage_esquive
        """,
        (
            combat_id, user_id, nom_dest,
            boosts_source["atk"], boosts_source["def"], boosts_source["atk_spe"],
            boosts_source["def_spe"], boosts_source["vit"], boosts_source["precision"], boosts_source["esquive"],
        ),
    )
    conn.commit()
    conn.close()


# --- Charge / recharge (attaques à deux tours type Lance-Soleil, Ultimaton) ---

def obtenir_charge(combat_id: int, user_id: int, pokemon_nom: str) -> dict:
    """Retourne {'attaque_en_charge': str|None, 'doit_recharger': bool, 'cible_user_id': int|None}.
    cible_user_id n'est utilisé qu'en 2v2 : la cible choisie au tour de charge, relâchée
    dessus au tour suivant (redirigée si elle est tombée entre-temps). En 1v1 le ciblage
    est implicite, la colonne reste NULL."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT attaque_en_charge, doit_recharger, cible_user_id FROM combat_charge "
        "WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"attaque_en_charge": None, "doit_recharger": False, "cible_user_id": None}
    return {
        "attaque_en_charge": row["attaque_en_charge"],
        "doit_recharger": bool(row["doit_recharger"]),
        "cible_user_id": row["cible_user_id"],
    }


def definir_charge(combat_id: int, user_id: int, pokemon_nom: str, attaque_en_charge: str | None, doit_recharger: bool, cible_user_id: int | None = None):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_charge (combat_id, user_id, pokemon_nom, attaque_en_charge, doit_recharger, cible_user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(combat_id, user_id, pokemon_nom) DO UPDATE SET
            attaque_en_charge = excluded.attaque_en_charge,
            doit_recharger = excluded.doit_recharger,
            cible_user_id = excluded.cible_user_id
        """,
        (combat_id, user_id, pokemon_nom, attaque_en_charge, int(doit_recharger), cible_user_id),
    )
    conn.commit()
    conn.close()


def reinitialiser_charge(combat_id: int, user_id: int, pokemon_nom: str):
    """Annule toute charge/recharge en cours (appelé quand le Pokémon quitte le terrain)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM combat_charge WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


# --- Attaques de FURIE (ex: Colère/Dracocolère) : verrouillage 2-3 tours + confusion ---

def obtenir_furie(combat_id: int, user_id: int, pokemon_nom: str) -> dict | None:
    """Retourne {'attaque': str, 'tours_restants': int} si ce Pokémon est actuellement
    verrouillé sur une attaque de furie, sinon None."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT attaque, tours_restants FROM combat_furie WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {"attaque": row["attaque"], "tours_restants": row["tours_restants"]}


def definir_furie(combat_id: int, user_id: int, pokemon_nom: str, attaque: str | None, tours_restants: int = 0):
    """attaque=None efface le verrouillage (fin de la furie, ou le Pokémon quitte le terrain)."""
    conn = get_connexion()
    cur = conn.cursor()
    if attaque is None:
        cur.execute(
            "DELETE FROM combat_furie WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
            (combat_id, user_id, pokemon_nom),
        )
    else:
        cur.execute(
            """
            INSERT INTO combat_furie (combat_id, user_id, pokemon_nom, attaque, tours_restants)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(combat_id, user_id, pokemon_nom) DO UPDATE SET
                attaque = excluded.attaque, tours_restants = excluded.tours_restants
            """,
            (combat_id, user_id, pokemon_nom, attaque, tours_restants),
        )
    conn.commit()
    conn.close()


# --- Météo de combat (Soleil/Pluie/Tempête de sable/Grêle) -----------------------------

def obtenir_meteo(combat_id: int) -> dict | None:
    """Retourne {'type': str, 'tours_restants': int} ou None si ciel dégagé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type, tours_restants FROM combat_meteo WHERE combat_id = ?", (combat_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {"type": row["type"], "tours_restants": row["tours_restants"]}


def definir_meteo(combat_id: int, type_meteo: str | None, tours: int = 5):
    """type_meteo=None efface la météo (ciel dégagé). Une nouvelle météo remplace
    toujours l'ancienne (pas de cumul), avec sa propre durée (5 tours par défaut)."""
    conn = get_connexion()
    cur = conn.cursor()
    if type_meteo is None:
        cur.execute("DELETE FROM combat_meteo WHERE combat_id = ?", (combat_id,))
    else:
        cur.execute(
            """
            INSERT INTO combat_meteo (combat_id, type, tours_restants) VALUES (?, ?, ?)
            ON CONFLICT(combat_id) DO UPDATE SET type = excluded.type, tours_restants = excluded.tours_restants
            """,
            (combat_id, type_meteo, tours),
        )
    conn.commit()
    conn.close()


def decrementer_meteo(combat_id: int) -> str | None:
    """À appeler une fois par tour résolu. Retourne le type de météo qui vient de
    prendre fin à l'instant (pour un message de log), sinon None."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type, tours_restants FROM combat_meteo WHERE combat_id = ?", (combat_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    nouveau = row["tours_restants"] - 1
    if nouveau <= 0:
        cur.execute("DELETE FROM combat_meteo WHERE combat_id = ?", (combat_id,))
        conn.commit()
        conn.close()
        return row["type"]
    cur.execute("UPDATE combat_meteo SET tours_restants = ? WHERE combat_id = ?", (nouveau, combat_id))
    conn.commit()
    conn.close()
    return None


def obtenir_attaque_verrouillee(combat_id: int, user_id: int, pokemon_nom: str) -> str | None:
    """Attaque imposée par un Objet Choix tenu (Bandeau/Spécs/Bandana Choix) — None si le
    Pokémon n'a encore rien utilisé depuis son entrée en jeu (ou ne tient pas cet objet)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT attaque_verrouillee FROM combat_choix WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["attaque_verrouillee"] if row else None


def definir_attaque_verrouillee(combat_id: int, user_id: int, pokemon_nom: str, nom_attaque: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_choix (combat_id, user_id, pokemon_nom, attaque_verrouillee)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(combat_id, user_id, pokemon_nom) DO UPDATE SET attaque_verrouillee = excluded.attaque_verrouillee
        """,
        (combat_id, user_id, pokemon_nom, nom_attaque),
    )
    conn.commit()
    conn.close()


def reinitialiser_verrouillage_choix(combat_id: int, user_id: int, pokemon_nom: str):
    """Le verrouillage saute quand le Pokémon quitte le terrain (switch) — comme dans les
    vrais jeux, un nouveau Pokémon envoyé peut choisir librement sa 1ère attaque."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM combat_choix WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def obtenir_statut(combat_id: int, user_id: int, pokemon_nom: str):
    """Retourne (statut, compteur) ou None si le Pokémon n'a aucune altération."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT statut, compteur FROM combat_statuts WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return (row["statut"], row["compteur"]) if row else None


IMMUNITE_STATUT_PAR_TYPE = {
    "poison": {"poison", "acier"},
    "paralysis": {"electrik"},
    "burn": {"feu"},
    "freeze": {"glace"},
}


def definir_statut(combat_id: int, user_id: int, pokemon_nom: str, statut: str, compteur: int = 0) -> bool:
    """Applique une altération de statut, seulement si le Pokémon n'en a pas déjà une
    (un seul statut à la fois, comme dans les vrais jeux). Retourne True si appliqué.

    ⚠️ Respecte aussi les immunités de type des vrais jeux (voir IMMUNITE_STATUT_PAR_TYPE)
    — un Poison/Acier ne peut jamais être empoisonné, un Électrik jamais paralysé, un Feu
    jamais brûlé, un Glace jamais gelé. Centralisé ici pour s'appliquer partout sans
    exception (1v1, 2v2, dresseurs, raids, ripostes au contact...)."""
    types_a_eviter = IMMUNITE_STATUT_PAR_TYPE.get(statut)
    if types_a_eviter:
        import pokemon_data

        pokemon = pokemon_data.obtenir_pokemon_par_nom(pokemon_nom)
        if pokemon and types_a_eviter & set(pokemon.get("types", [])):
            return False
    if obtenir_statut(combat_id, user_id, pokemon_nom) is not None:
        return False
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO combat_statuts (combat_id, user_id, pokemon_nom, statut, compteur) VALUES (?, ?, ?, ?, ?)",
        (combat_id, user_id, pokemon_nom, statut, compteur),
    )
    conn.commit()
    conn.close()
    return True


def retirer_statut(combat_id: int, user_id: int, pokemon_nom: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM combat_statuts WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def decrementer_compteur_statut(combat_id: int, user_id: int, pokemon_nom: str) -> int:
    """Décrémente le compteur du statut (utilisé pour le sommeil). Retourne le nouveau compteur."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_statuts SET compteur = MAX(0, compteur - 1) WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    cur.execute(
        "SELECT compteur FROM combat_statuts WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["compteur"] if row else 0


# --- Pièges de terrain (entry hazards) posés contre un joueur ---

def poser_hazard(combat_id: int, cible_user_id: int, effet: str, stacks_max: int = 3) -> int:
    """Pose (ou empile) un piège de terrain contre le camp d'un joueur.
    Retourne le nombre de couches après pose (plafonné à stacks_max)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT stacks FROM combat_terrain WHERE combat_id = ? AND cible_user_id = ? AND effet = ?",
        (combat_id, cible_user_id, effet),
    )
    row = cur.fetchone()
    nouveau = min(stacks_max, (row["stacks"] if row else 0) + 1)
    cur.execute(
        """
        INSERT INTO combat_terrain (combat_id, cible_user_id, effet, stacks)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(combat_id, cible_user_id, effet) DO UPDATE SET stacks = excluded.stacks
        """,
        (combat_id, cible_user_id, effet, nouveau),
    )
    conn.commit()
    conn.close()
    return nouveau


def obtenir_hazards(combat_id: int, cible_user_id: int) -> dict:
    """Retourne {effet: stacks} des pièges posés contre le camp de ce joueur."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT effet, stacks FROM combat_terrain WHERE combat_id = ? AND cible_user_id = ?",
        (combat_id, cible_user_id),
    )
    resultat = {row["effet"]: row["stacks"] for row in cur.fetchall()}
    conn.close()
    return resultat


# --- Boosts temporaires (XP, argent, shiny) ---

def activer_boost(user_id: int, type_boost: str, duree_secondes: int) -> int:
    """Active un boost, en ADDITIONNANT la durée à un boost déjà actif du même type
    (acheter un 2e boost pendant que le 1er tourne encore prolonge sa durée au lieu de
    le remplacer). Retourne le nouveau timestamp d'expiration."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT date_expiration FROM boosts_actifs WHERE user_id = ? AND type_boost = ?",
        (user_id, type_boost),
    )
    row = cur.fetchone()
    maintenant = int(time.time())
    base = row["date_expiration"] if row and row["date_expiration"] is not None and row["date_expiration"] > maintenant else maintenant
    nouvelle_expiration = base + duree_secondes

    cur.execute(
        """
        INSERT INTO boosts_actifs (user_id, type_boost, date_expiration)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, type_boost) DO UPDATE SET date_expiration = excluded.date_expiration
        """,
        (user_id, type_boost, nouvelle_expiration),
    )
    conn.commit()
    conn.close()
    return nouvelle_expiration


def obtenir_boost_actif(user_id: int, type_boost: str):
    """Retourne le timestamp d'expiration si un boost de ce type est encore actif, sinon None."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT date_expiration FROM boosts_actifs WHERE user_id = ? AND type_boost = ?",
        (user_id, type_boost),
    )
    row = cur.fetchone()
    conn.close()
    if row and row["date_expiration"] is not None and row["date_expiration"] > int(time.time()):
        return row["date_expiration"]
    return None


def obtenir_tous_boosts_actifs(user_id: int) -> dict:
    """Retourne {type_boost: date_expiration} pour tous les boosts encore actifs de ce joueur."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type_boost, date_expiration FROM boosts_actifs WHERE user_id = ?", (user_id,))
    maintenant = int(time.time())
    resultat = {
        row["type_boost"]: row["date_expiration"]
        for row in cur.fetchall()
        if row["date_expiration"] is not None and row["date_expiration"] > maintenant
    }
    conn.close()
    return resultat


def multiplicateur_boost(user_id: int, type_boost: str) -> float:
    """Retourne le multiplicateur total à appliquer pour ce type ("xp", "argent",
    "shiny", "capture") : bonus permanent de Race combiné multiplicativement à un boost
    temporaire éventuel (admin), et au bonus booster serveur (argent/xp/shiny
    uniquement) si le joueur boost activement le serveur Discord. Retourne 1.0 si rien
    de tout ça n'est actif."""
    import config
    import races

    multiplicateur = 1.0

    race_nom, _ = obtenir_race(user_id)
    if race_nom:
        race = races.obtenir_race_par_nom(race_nom)
        if race:
            multiplicateur *= 1.0 + race["bonus"].get(type_boost, 0.0)

    # Bonus permanent des badges de Repaire de méchants (voir repaires.py) — chaque
    # équipe vaincue pour la première fois donne un petit bonus à SA catégorie précise
    # (capture/shiny/argent/xp — voir config.EQUIPES_MECHANTES["categorie_bonus"]).
    for equipe in obtenir_badges_repaire(user_id):
        info = config.EQUIPES_MECHANTES.get(equipe)
        if info and info.get("categorie_bonus") == type_boost:
            multiplicateur *= 1.0 + config.REPAIRE_BONUS_PAR_BADGE

    if obtenir_boost_actif(user_id, type_boost) is not None:
        multiplicateur *= config.MULTIPLICATEURS_BOOST.get(type_boost, 1.0)

    if type_boost in config.MULTIPLICATEUR_BOOSTER_SERVEUR and est_booster_serveur(user_id):
        multiplicateur *= config.MULTIPLICATEUR_BOOSTER_SERVEUR[type_boost]

    boost_global = obtenir_boost_global_actif(type_boost)
    if boost_global is not None:
        multiplicateur *= boost_global

    return multiplicateur


# --- Events serveur : boost global (/event) ---

def activer_boost_global(type_boost: str, multiplicateur: float, duree_secondes: int, channel_annonce_id: int | None = None):
    """Démarre (ou remplace) un boost GLOBAL, appliqué à TOUS les joueurs, sans exception
    de user_id — contrairement à boosts_actifs qui est personnel."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO evenement_boost_global (type_boost, multiplicateur, date_expiration, channel_annonce_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(type_boost) DO UPDATE SET
            multiplicateur = excluded.multiplicateur,
            date_expiration = excluded.date_expiration,
            channel_annonce_id = excluded.channel_annonce_id
        """,
        (type_boost, multiplicateur, int(time.time()) + duree_secondes, channel_annonce_id),
    )
    conn.commit()
    conn.close()


def obtenir_boost_global_actif(type_boost: str) -> float | None:
    """Retourne le multiplicateur si un boost global de ce type est encore actif, sinon None."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT multiplicateur, date_expiration FROM evenement_boost_global WHERE type_boost = ?",
        (type_boost,),
    )
    row = cur.fetchone()
    conn.close()
    if row and row["date_expiration"] > int(time.time()):
        return row["multiplicateur"]
    return None


def obtenir_tous_boosts_globaux() -> list:
    """Retourne toutes les lignes (actives ou tout juste expirées) — pour la boucle de
    vérification périodique, qui doit détecter la transition actif->expiré pour annoncer
    la fin, ce qu'un simple filtre 'encore actif' ne permettrait pas de repérer."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type_boost, multiplicateur, date_expiration, channel_annonce_id, message_id FROM evenement_boost_global")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def desactiver_boost_global(type_boost: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM evenement_boost_global WHERE type_boost = ?", (type_boost,))
    conn.commit()
    conn.close()


def definir_message_boost_global(type_boost: str, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE evenement_boost_global SET message_id = ? WHERE type_boost = ?", (message_id, type_boost))
    conn.commit()
    conn.close()


# --- Events serveur : défi collectif (/event) ---

def demarrer_defi_collectif(type_evenement: str, cible: int, channel_annonce_id: int | None = None) -> int:
    """Démarre un nouveau défi collectif, désactivant silencieusement tout défi encore actif
    (un seul à la fois). Retourne l'id du nouveau défi."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE defi_collectif_serveur SET actif = 0 WHERE actif = 1")
    cur.execute(
        """
        INSERT INTO defi_collectif_serveur (type_evenement, cible, progres, actif, date_debut, channel_annonce_id)
        VALUES (?, ?, 0, 1, ?, ?)
        """,
        (type_evenement, cible, int(time.time()), channel_annonce_id),
    )
    defi_id = cur.lastrowid
    conn.commit()
    conn.close()
    return defi_id


def obtenir_defi_collectif_actif() -> dict | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM defi_collectif_serveur WHERE actif = 1 LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def definir_message_defi_collectif(defi_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE defi_collectif_serveur SET message_id = ? WHERE id = ?", (message_id, defi_id))
    conn.commit()
    conn.close()


def progresser_defi_collectif(user_id: int, type_evenement: str, montant: int = 1) -> dict | None:
    """Fait progresser le défi collectif actif s'il correspond à `type_evenement`.
    Retourne un dict avec l'état à jour (et 'vient_de_finir': bool) si un défi actif
    correspondait, sinon None (aucun défi actif de ce type, rien à faire)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM defi_collectif_serveur WHERE actif = 1 AND type_evenement = ? LIMIT 1", (type_evenement,))
    defi = cur.fetchone()
    if defi is None:
        conn.close()
        return None

    nouveau_progres = min(defi["cible"], defi["progres"] + montant)
    vient_de_finir = nouveau_progres >= defi["cible"] and defi["progres"] < defi["cible"]
    cur.execute("UPDATE defi_collectif_serveur SET progres = ? WHERE id = ?", (nouveau_progres, defi["id"]))
    cur.execute(
        """
        INSERT INTO defi_collectif_participants (defi_id, user_id, contribution) VALUES (?, ?, ?)
        ON CONFLICT(defi_id, user_id) DO UPDATE SET contribution = contribution + excluded.contribution
        """,
        (defi["id"], user_id, montant),
    )
    if vient_de_finir:
        cur.execute("UPDATE defi_collectif_serveur SET actif = 0 WHERE id = ?", (defi["id"],))
    conn.commit()
    conn.close()
    return {
        "id": defi["id"], "type_evenement": type_evenement, "cible": defi["cible"],
        "progres": nouveau_progres, "vient_de_finir": vient_de_finir,
        "channel_annonce_id": defi["channel_annonce_id"],
    }


def arreter_defi_collectif():
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE defi_collectif_serveur SET actif = 0 WHERE actif = 1")
    conn.commit()
    conn.close()


def obtenir_participants_defi_collectif(defi_id: int) -> list:
    """Retourne [(user_id, contribution)] triés par contribution décroissante — pour la
    distribution de récompense et l'annonce des meilleurs contributeurs."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, contribution FROM defi_collectif_participants WHERE defi_id = ? ORDER BY contribution DESC",
        (defi_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [(r["user_id"], r["contribution"]) for r in rows]


def obtenir_defis_collectifs_a_recompenser() -> list:
    """Défis désactivés (actif=0) dont la cible a bien été ATTEINTE (pas juste annulés
    par un admin) et pas encore récompensés — pour la boucle de vérification."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM defi_collectif_serveur WHERE actif = 0 AND recompense_donnee = 0 AND progres >= cible"
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def marquer_defi_collectif_recompense(defi_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE defi_collectif_serveur SET recompense_donnee = 1 WHERE id = ?", (defi_id,))
    conn.commit()
    conn.close()


# --- Events serveur : chasse aux shiny (/event) ---

def demarrer_chasse_shiny(duree_secondes: int, channel_annonce_id: int | None = None) -> int:
    """Démarre une nouvelle chasse aux shiny, désactivant silencieusement toute chasse
    encore active (une seule à la fois). Retourne l'id de la nouvelle chasse."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE chasse_shiny_evenement SET actif = 0 WHERE actif = 1")
    maintenant = int(time.time())
    cur.execute(
        """
        INSERT INTO chasse_shiny_evenement (date_debut, date_fin, actif, channel_annonce_id, annoncee)
        VALUES (?, ?, 1, ?, 0)
        """,
        (maintenant, maintenant + duree_secondes, channel_annonce_id),
    )
    chasse_id = cur.lastrowid
    conn.commit()
    conn.close()
    return chasse_id


def obtenir_chasse_shiny_active() -> dict | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chasse_shiny_evenement WHERE actif = 1 LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def definir_message_chasse_shiny(chasse_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE chasse_shiny_evenement SET message_id = ? WHERE id = ?", (message_id, chasse_id))
    conn.commit()
    conn.close()


def obtenir_chasses_shiny_a_terminer() -> list:
    """Chasses actives dont la date de fin est dépassée — pour la boucle de vérification."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chasse_shiny_evenement WHERE actif = 1 AND date_fin <= ?", (int(time.time()),))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def terminer_chasse_shiny(chasse_id: int) -> list:
    """Clôture la chasse et retourne le classement final [(user_id, nb_shiny)] trié
    décroissant, en comptant les captures shiny du joueur sur la fenêtre de la chasse."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT date_debut, date_fin FROM chasse_shiny_evenement WHERE id = ?", (chasse_id,))
    chasse = cur.fetchone()
    if chasse is None:
        conn.close()
        return []
    cur.execute(
        """
        SELECT user_id, COUNT(*) AS nb_shiny FROM captures
        WHERE shiny = 1 AND date_capture BETWEEN ? AND ?
        GROUP BY user_id ORDER BY nb_shiny DESC
        """,
        (chasse["date_debut"], chasse["date_fin"]),
    )
    classement = [(r["user_id"], r["nb_shiny"]) for r in cur.fetchall()]
    cur.execute("UPDATE chasse_shiny_evenement SET actif = 0, annoncee = 1 WHERE id = ?", (chasse_id,))
    conn.commit()
    conn.close()
    return classement


def arreter_chasse_shiny():
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE chasse_shiny_evenement SET actif = 0 WHERE actif = 1")
    conn.commit()
    conn.close()


# --- Codes promo ---

def creer_code_promo(
    code: str, dollars: int, xp: int, objet: str | None, quantite_objet: int,
    max_utilisations: int | None, date_expiration: int | None, cree_par: int,
) -> bool:
    """Crée un nouveau code promo. Retourne False si ce code existe déjà (peu importe
    qu'il soit encore actif ou non — les codes ne se réutilisent pas)."""
    code = code.strip().upper()
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM codes_promo WHERE code = ?", (code,))
    if cur.fetchone() is not None:
        conn.close()
        return False
    cur.execute(
        """
        INSERT INTO codes_promo
            (code, dollars, xp, objet, quantite_objet, max_utilisations, date_expiration, cree_par, date_creation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (code, dollars, xp, objet, quantite_objet, max_utilisations, date_expiration, cree_par, int(time.time())),
    )
    conn.commit()
    conn.close()
    return True


def obtenir_code_promo(code: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM codes_promo WHERE code = ?", (code.strip().upper(),))
    row = cur.fetchone()
    conn.close()
    return row


def lister_codes_promo() -> list:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM codes_promo ORDER BY date_creation DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def desactiver_code_promo(code: str) -> bool:
    conn = get_connexion()
    cur = conn.cursor()
    code = code.strip().upper()
    cur.execute("SELECT 1 FROM codes_promo WHERE code = ?", (code,))
    if cur.fetchone() is None:
        conn.close()
        return False
    cur.execute("UPDATE codes_promo SET actif = 0 WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    return True


def utiliser_code_promo(code: str, user_id: int) -> tuple:
    """Tente d'utiliser un code pour ce joueur. Retourne (True, ligne_code) si réussi —
    à charge de l'appelant de distribuer les récompenses décrites dans la ligne. Retourne
    (False, raison_texte) sinon. N'accorde jamais deux fois le même code au même joueur
    (contrainte PRIMARY KEY sur codes_promo_utilises)."""
    code = code.strip().upper()
    conn = get_connexion()
    cur = conn.cursor()

    cur.execute("SELECT * FROM codes_promo WHERE code = ?", (code,))
    ligne = cur.fetchone()
    if ligne is None:
        conn.close()
        return False, "Ce code n'existe pas."
    if not ligne["actif"]:
        conn.close()
        return False, "Ce code n'est plus actif."
    if ligne["date_expiration"] and ligne["date_expiration"] < int(time.time()):
        conn.close()
        return False, "Ce code a expiré."
    if ligne["max_utilisations"] is not None and ligne["utilisations_actuelles"] >= ligne["max_utilisations"]:
        conn.close()
        return False, "Ce code a atteint son nombre maximum d'utilisations."

    cur.execute("SELECT 1 FROM codes_promo_utilises WHERE code = ? AND user_id = ?", (code, user_id))
    if cur.fetchone() is not None:
        conn.close()
        return False, "Tu as déjà utilisé ce code."

    try:
        cur.execute(
            "INSERT INTO codes_promo_utilises (code, user_id, date_utilisation) VALUES (?, ?, ?)",
            (code, user_id, int(time.time())),
        )
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Tu as déjà utilisé ce code."  # garde-fou en cas de double-clic simultané

    cur.execute("UPDATE codes_promo SET utilisations_actuelles = utilisations_actuelles + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    return True, ligne


# --- Réinitialisation complète d'un joueur (admin) ---

def reinitialiser_joueur(user_id: int):
    """Supprime TOUTES les données d'un joueur : profil, PC/PD/XP, captures, inventaire,
    équipe de combat, attaques équipées, boosts actifs. Action irréversible, réservée
    aux admins. Le joueur repart de zéro à sa prochaine interaction avec le bot."""
    conn = get_connexion()
    cur = conn.cursor()
    for table in (
        "users",
        "captures",
        "inventaire_balls",
        "equipe_combat",
        "etat_combat_pokemon",
        "attaques_equipees",
        "boosts_actifs",
        "raid_participants",
    ):
        cur.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# --- Race du dresseur (bonus permanents) ---

def obtenir_race(user_id: int):
    """Retourne (race_nom, pity_compteur), ou (None, 0) si aucune race obtenue encore."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT race_nom, pity_compteur FROM joueur_race WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None, 0
    return row["race_nom"], row["pity_compteur"]


def definir_race(user_id: int, race_nom: str, pity_compteur: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO joueur_race (user_id, race_nom, pity_compteur)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET race_nom = excluded.race_nom, pity_compteur = excluded.pity_compteur
        """,
        (user_id, race_nom, pity_compteur),
    )
    conn.commit()
    conn.close()


# --- Centre des Explorations ---

def nb_slots_exploration(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    conn.commit()
    cur.execute("SELECT slot_exploration_achete FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return 1 + (row["slot_exploration_achete"] if row else 0)


def acheter_slot_exploration(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute("UPDATE users SET slot_exploration_achete = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def obtenir_explorations_actives(user_id: int) -> list:
    """Retourne la liste des explorations en cours (actives OU terminées mais pas encore
    récupérées) pour ce joueur, une ligne par slot occupé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM exploration_slots WHERE user_id = ? AND date_fin IS NOT NULL ORDER BY slot",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def demarrer_exploration(user_id: int, slot: int, pokemons: list, duree_secondes: int, duree_label: str):
    conn = get_connexion()
    cur = conn.cursor()
    maintenant = int(time.time())
    cur.execute(
        """
        INSERT INTO exploration_slots (user_id, slot, pokemon1, pokemon2, pokemon3, date_debut, date_fin, duree_label, notifie)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(user_id, slot) DO UPDATE SET
            pokemon1 = excluded.pokemon1, pokemon2 = excluded.pokemon2, pokemon3 = excluded.pokemon3,
            date_debut = excluded.date_debut, date_fin = excluded.date_fin, duree_label = excluded.duree_label,
            notifie = 0
        """,
        (user_id, slot, pokemons[0], pokemons[1], pokemons[2], maintenant, maintenant + duree_secondes, duree_label),
    )
    conn.commit()
    conn.close()


def forcer_fin_exploration(user_id: int, slot: int) -> bool:
    """[Admin] Rend une exploration immédiatement récupérable, sans attendre le timer
    (la récompense reste calculée sur la durée D'ORIGINE choisie par le joueur, stockée
    à part — forcer la fin ne réduit donc pas la récompense). Retourne False si aucune
    exploration n'est en cours sur cet emplacement."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM exploration_slots WHERE user_id = ? AND slot = ?",
        (user_id, slot),
    )
    if cur.fetchone() is None:
        conn.close()
        return False
    cur.execute(
        "UPDATE exploration_slots SET date_fin = ? WHERE user_id = ? AND slot = ?",
        (int(time.time()), user_id, slot),
    )
    conn.commit()
    conn.close()
    return True


def terminer_exploration(user_id: int, slot: int):
    """Libère un emplacement d'exploration (après récupération de la récompense)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM exploration_slots WHERE user_id = ? AND slot = ?", (user_id, slot))
    conn.commit()
    conn.close()


def especes_en_exploration(user_id: int) -> set:
    """Retourne l'ensemble des NOMS d'espèces actuellement parties en exploration pour ce
    joueur (peu importe si l'exploration est terminée mais pas encore récupérée — les
    Pokémon ne reviennent qu'au moment où le joueur récupère sa récompense)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pokemon1, pokemon2, pokemon3 FROM exploration_slots WHERE user_id = ?",
        (user_id,),
    )
    especes = set()
    for row in cur.fetchall():
        for p in (row["pokemon1"], row["pokemon2"], row["pokemon3"]):
            if p:
                especes.add(p)
    conn.close()
    return especes


def obtenir_equipe_combat_disponible(user_id: int) -> list:
    """Équipe de combat, en excluant les espèces actuellement parties en exploration."""
    indisponibles = especes_en_exploration(user_id)
    return [nom for nom in obtenir_equipe_combat(user_id) if nom not in indisponibles]


# --- Incubateur (Laboratoire) ---
# 1 seul emplacement en V1, volontairement simple — pas d'extension achetable pour l'instant
# (contrairement à l'Exploration), à ajouter plus tard si le système plaît.

def obtenir_incubation_active(user_id: int, slot: int = 1):
    """Retourne la ligne d'incubation en cours sur cet emplacement, ou None."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM incubateur_slots WHERE user_id = ? AND slot = ? AND date_fin IS NOT NULL",
        (user_id, slot),
    )
    row = cur.fetchone()
    conn.close()
    return row


def demarrer_incubation(user_id: int, slot: int, palier: str, duree_secondes: int):
    conn = get_connexion()
    cur = conn.cursor()
    maintenant = int(time.time())
    cur.execute(
        """
        INSERT INTO incubateur_slots (user_id, slot, palier, date_debut, date_fin, notifie)
        VALUES (?, ?, ?, ?, ?, 0)
        ON CONFLICT(user_id, slot) DO UPDATE SET
            palier = excluded.palier, date_debut = excluded.date_debut, date_fin = excluded.date_fin, notifie = 0
        """,
        (user_id, slot, palier, maintenant, maintenant + duree_secondes),
    )
    conn.commit()
    conn.close()


def terminer_incubation(user_id: int, slot: int):
    """Libère l'emplacement une fois l'œuf récupéré (éclos ou annulé)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE incubateur_slots SET palier = NULL, date_debut = NULL, date_fin = NULL, notifie = 0 "
        "WHERE user_id = ? AND slot = ?",
        (user_id, slot),
    )
    conn.commit()
    conn.close()


# --- Notifications MP de fin (Exploration + Incubateur) ---

def obtenir_explorations_a_notifier() -> list:
    """Explorations terminées (date_fin passée) pas encore notifiées par MP, tous joueurs
    confondus — utilisé par la boucle de fond qui envoie les MP."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM exploration_slots WHERE date_fin IS NOT NULL AND date_fin <= ? AND notifie = 0",
        (int(time.time()),),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def marquer_exploration_notifiee(user_id: int, slot: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE exploration_slots SET notifie = 1 WHERE user_id = ? AND slot = ?",
        (user_id, slot),
    )
    conn.commit()
    conn.close()


def obtenir_incubations_a_notifier() -> list:
    """Œufs prêts à éclore (date_fin passée) pas encore notifiés par MP, tous joueurs
    confondus — utilisé par la boucle de fond qui envoie les MP."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM incubateur_slots WHERE palier IS NOT NULL AND date_fin IS NOT NULL "
        "AND date_fin <= ? AND notifie = 0",
        (int(time.time()),),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def marquer_incubation_notifiee(user_id: int, slot: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE incubateur_slots SET notifie = 1 WHERE user_id = ? AND slot = ?",
        (user_id, slot),
    )
    conn.commit()
    conn.close()


def forcer_fin_incubation(user_id: int, slot: int = 1) -> bool:
    """[Admin] Rend un œuf immédiatement prêt à éclore, sans attendre le timer. Retourne
    False si aucun œuf n'est en incubation sur cet emplacement."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM incubateur_slots WHERE user_id = ? AND slot = ? AND palier IS NOT NULL",
        (user_id, slot),
    )
    if cur.fetchone() is None:
        conn.close()
        return False
    cur.execute(
        "UPDATE incubateur_slots SET date_fin = ? WHERE user_id = ? AND slot = ?",
        (int(time.time()), user_id, slot),
    )
    conn.commit()
    conn.close()
    return True


# --- PP (Points de Pouvoir) des attaques en combat PvP ---

def obtenir_pp(combat_id: int, user_id: int, pokemon_nom: str, attaque_nom: str, pp_max: int) -> int:
    """Retourne le PP restant pour cette attaque sur ce Pokémon dans ce combat.
    Initialise au PP max lors du tout premier appel (pas besoin de tout pré-remplir
    au démarrage du combat)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pp_restant FROM combat_pp WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ? AND attaque_nom = ?",
        (combat_id, user_id, pokemon_nom, attaque_nom),
    )
    row = cur.fetchone()
    if row is not None:
        conn.close()
        return row["pp_restant"]

    cur.execute(
        "INSERT INTO combat_pp (combat_id, user_id, pokemon_nom, attaque_nom, pp_restant) VALUES (?, ?, ?, ?, ?)",
        (combat_id, user_id, pokemon_nom, attaque_nom, pp_max),
    )
    conn.commit()
    conn.close()
    return pp_max


def consommer_pp(combat_id: int, user_id: int, pokemon_nom: str, attaque_nom: str, pp_max: int, montant: int = 1) -> int:
    """Consomme `montant` PP (initialise d'abord si jamais utilisée) — montant=2 pour
    une attaque utilisée contre un Pokémon avec Pression. Retourne le PP restant après
    consommation (jamais négatif)."""
    pp_actuel = obtenir_pp(combat_id, user_id, pokemon_nom, attaque_nom, pp_max)
    nouveau_pp = max(0, pp_actuel - montant)
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_pp SET pp_restant = ? WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ? AND attaque_nom = ?",
        (nouveau_pp, combat_id, user_id, pokemon_nom, attaque_nom),
    )
    conn.commit()
    conn.close()
    return nouveau_pp


# --- Quêtes journalières / hebdomadaires ---

def _periode_id(type_quete: str) -> int:
    """Identifiant de période courante : change à date fixe pour tout le monde
    (00h UTC pour les journalières, tous les 7 jours pour les hebdomadaires).
    Deux appels dans la même fenêtre de temps retournent le même id."""
    maintenant = int(time.time())
    if type_quete == "jour":
        return maintenant // 86400
    return maintenant // (7 * 86400)


def _obtenir_ou_reinitialiser_progression(cur, user_id: int, quete_id: str, type_quete: str):
    """Retourne (compteur, reclamee) pour cette quête, en réinitialisant si la période
    a changé depuis le dernier suivi."""
    periode_actuelle = _periode_id(type_quete)
    cur.execute(
        "SELECT periode_id, compteur, reclamee FROM quete_progression WHERE user_id = ? AND quete_id = ?",
        (user_id, quete_id),
    )
    row = cur.fetchone()
    if row is None or row["periode_id"] != periode_actuelle:
        cur.execute(
            """
            INSERT INTO quete_progression (user_id, quete_id, periode_id, compteur, reclamee)
            VALUES (?, ?, ?, 0, 0)
            ON CONFLICT(user_id, quete_id) DO UPDATE SET periode_id = excluded.periode_id, compteur = 0, reclamee = 0
            """,
            (user_id, quete_id, periode_actuelle),
        )
        return 0, 0
    return row["compteur"], row["reclamee"]


def obtenir_progression_quete(user_id: int, quete_id: str, type_quete: str) -> tuple:
    """Retourne (compteur, reclamee) pour cette quête, à jour de la période actuelle."""
    conn = get_connexion()
    cur = conn.cursor()
    compteur, reclamee = _obtenir_ou_reinitialiser_progression(cur, user_id, quete_id, type_quete)
    conn.commit()
    conn.close()
    return compteur, reclamee


def incrementer_progression_quete(user_id: int, evenement: str, contexte: dict = None, montant: int = 1) -> list:
    """Fait progresser toutes les quêtes actives (jour + semaine) correspondant à cet
    événement, en respectant leur filtre éventuel (ex: rareté). Plafonne au max requis,
    ne dépasse jamais et ne touche pas les quêtes déjà réclamées. Retourne la liste des
    quêtes qui viennent tout juste d'être complétées par CET appel (pour notifier le
    joueur immédiatement, sans attendre qu'il aille checker /quetes)."""
    import quetes as quetes_module

    _CATEGORIE_CONTRIBUTION_CLAN = {
        "capture": ("capture", 1),
        "pvp_victoire": ("combat", 2),
        "pve_victoire": ("combat", 2),
        "raid_victoire": ("combat", 2),
    }
    if evenement in _CATEGORIE_CONTRIBUTION_CLAN:
        categorie, points = _CATEGORIE_CONTRIBUTION_CLAN[evenement]
        ajouter_contribution_clan(user_id, categorie, points * montant)

    # Défi collectif du serveur (/event) : capture / combat dresseur / tour de PokéStop —
    # no-op silencieux si aucun défi actif ou si son type ne correspond pas (voir
    # progresser_defi_collectif). La détection de complétion + l'annonce + la récompense
    # se font dans la boucle périodique (main.py), pas ici, car database.py n'a pas accès
    # au bot Discord pour poster un message.
    if evenement in ("capture", "pve_victoire", "pokestop"):
        progresser_defi_collectif(user_id, evenement, montant)

    # Quête principale (narration) : suit les mêmes événements que les quêtes jour/semaine
    # (capture/pve_victoire/pvp_victoire/raid_victoire/exploration_collectee/pokestop) —
    # avancer_quete_principale ignore silencieusement tout événement qui ne correspond pas
    # au chapitre EN COURS du joueur, donc aucun risque de double-avancement. Le résultat
    # n'est pas propagé aux appelants ici (le joueur découvre la progression via
    # /quete-principale) pour éviter de devoir modifier tous les points d'appel existants.
    avancer_quete_principale(user_id, evenement, montant)

    contexte = contexte or {}
    conn = get_connexion()
    cur = conn.cursor()
    tout_juste_completees = []

    for type_quete, catalogue in (("jour", quetes_module.QUETES_JOUR), ("semaine", quetes_module.QUETES_SEMAINE)):
        for quete in catalogue:
            if quete["evenement"] != evenement:
                continue
            filtre = quete.get("filtre")
            if filtre and any(contexte.get(cle) != valeur for cle, valeur in filtre.items()):
                continue

            compteur, reclamee = _obtenir_ou_reinitialiser_progression(cur, user_id, quete["id"], type_quete)
            if reclamee:
                continue
            nouveau_compteur = min(quete["cible"], compteur + montant)
            cur.execute(
                "UPDATE quete_progression SET compteur = ? WHERE user_id = ? AND quete_id = ?",
                (nouveau_compteur, user_id, quete["id"]),
            )
            if compteur < quete["cible"] <= nouveau_compteur:
                tout_juste_completees.append({"id": quete["id"], "nom": quete["nom"], "emoji": quete["emoji"], "type": type_quete})

    conn.commit()
    conn.close()
    return tout_juste_completees


def reclamer_quete(user_id: int, quete_id: str, type_quete: str) -> bool:
    """Marque une quête comme réclamée si elle est complète. Retourne True si réclamée
    à l'instant (False si déjà réclamée ou pas encore complète)."""
    import quetes as quetes_module

    quete = quetes_module.QUETES_PAR_ID[quete_id]
    conn = get_connexion()
    cur = conn.cursor()
    compteur, reclamee = _obtenir_ou_reinitialiser_progression(cur, user_id, quete_id, type_quete)

    if reclamee or compteur < quete["cible"]:
        conn.commit()
        conn.close()
        return False

    cur.execute(
        "UPDATE quete_progression SET reclamee = 1 WHERE user_id = ? AND quete_id = ?",
        (user_id, quete_id),
    )
    conn.commit()
    conn.close()
    return True


# --- Statistiques à vie (pour les accomplissements) ---

def incrementer_victoires_pvp(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO stats_lifetime (user_id, victoires_pvp) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET victoires_pvp = victoires_pvp + 1
        """,
        (user_id,),
    )
    conn.commit()
    conn.close()


def obtenir_victoires_pvp(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT victoires_pvp FROM stats_lifetime WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["victoires_pvp"] if row else 0


# --- Titre actif (accomplissements) ---

def obtenir_titre_actif(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT categorie FROM titre_actif WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["categorie"] if row else None


def definir_titre_actif(user_id: int, categorie: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO titre_actif (user_id, categorie) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET categorie = excluded.categorie
        """,
        (user_id, categorie),
    )
    conn.commit()
    conn.close()


# --- Notifications en attente (ex: quête complétée via une victoire de raid, où la
# récompense se distribue depuis une boucle automatique sans interaction Discord
# disponible pour un vrai message éphémère immédiat). Affichées au prochain clic du
# joueur sur un bouton lié (ex: "Capturer" sur le message de victoire du raid). ---

def ajouter_notification_attente(user_id: int, texte: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notifications_attente (user_id, texte) VALUES (?, ?)",
        (user_id, texte),
    )
    conn.commit()
    conn.close()


def recuperer_et_vider_notifications_attente(user_id: int) -> list:
    """Retourne tous les textes en attente pour ce joueur, puis les supprime (à usage
    unique — affichés une seule fois, dès le prochain clic)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT texte FROM notifications_attente WHERE user_id = ?", (user_id,))
    textes = [row["texte"] for row in cur.fetchall()]
    cur.execute("DELETE FROM notifications_attente WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return textes


# --- Anti-collusion PvP ---

def enregistrer_victoire_pvp_repetition(vainqueur_id: int, perdant_id: int) -> float:
    """Enregistre une victoire de vainqueur_id contre perdant_id pour la journée en cours,
    et retourne le multiplicateur à appliquer sur la récompense ÉCONOMIQUE (PD + XP) de
    CETTE victoire : 1.0 si c'est la première fois aujourd'hui qu'il bat CET adversaire,
    sinon config.PVP_MULTIPLICATEUR_REPETITION (fortement réduit, contre la collusion).
    Combiné (le plus bas des deux) avec la dégression générale journalière (harmonisée
    avec Dresseur/Arène/Repaire, voir enregistrer_victoire_pvp_generale_repetition) —
    donc même un joueur qui varie ses adversaires reste soumis au même anti-farm que les
    autres systèmes de combat, en plus de l'anti-collusion par adversaire précis."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM pvp_victoires_jour WHERE vainqueur_id = ? AND perdant_id = ? AND jour_id = ?",
        (vainqueur_id, perdant_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0
    multiplicateur_collusion = 1.0 if compteur_avant == 0 else config.PVP_MULTIPLICATEUR_REPETITION

    cur.execute(
        """
        INSERT INTO pvp_victoires_jour (vainqueur_id, perdant_id, jour_id, compteur)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(vainqueur_id, perdant_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (vainqueur_id, perdant_id, jour_id),
    )
    conn.commit()
    conn.close()

    multiplicateur_general = enregistrer_victoire_pvp_generale_repetition(vainqueur_id)
    return min(multiplicateur_collusion, multiplicateur_general)


def enregistrer_victoire_pvp_generale_repetition(user_id: int) -> float:
    """Dégression journalière générale des victoires PvP (harmonisée avec Dresseur/Arène/
    Repaire), TOUS adversaires confondus — complète l'anti-collusion par adversaire précis
    ci-dessus, qui à lui seul ne freinait pas un joueur enchaînant des victoires contre des
    adversaires DIFFÉRENTS chaque fois."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM pvp_victoires_jour_generale WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0

    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    multiplicateur = paliers[min(compteur_avant, len(paliers) - 1)]

    cur.execute(
        """
        INSERT INTO pvp_victoires_jour_generale (user_id, jour_id, compteur)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (user_id, jour_id),
    )
    conn.commit()
    conn.close()
    return multiplicateur


def enregistrer_completion_exploration_repetition(user_id: int) -> float:
    """Dégression journalière des Poké Dollars d'Exploration, harmonisée avec les autres
    systèmes (Dresseur/Arène/Repaire/PvP) — l'Exploration n'avait jusqu'ici AUCUNE limite
    de répétition quotidienne. Compte les explorations RÉCUPÉRÉES (pas lancées) dans la
    journée, tous emplacements confondus. N'affecte que les Poké Dollars, pas l'XP ni les
    chances de Cristal/Œuf/objet de forme."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM exploration_completions_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0

    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    multiplicateur = paliers[min(compteur_avant, len(paliers) - 1)]

    cur.execute(
        """
        INSERT INTO exploration_completions_jour (user_id, jour_id, compteur)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (user_id, jour_id),
    )
    conn.commit()
    conn.close()
    return multiplicateur


def multiplicateur_arene_du_jour(user_id: int) -> float:
    """Multiplicateur de dégression économique d'arène applicable MAINTENANT, sans rien
    incrémenter — utilisé pour les récompenses d'Apprentis en cours de run (le compteur
    ne monte qu'au run complété, voir enregistrer_victoire_arene_repetition)."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM arene_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    conn.close()
    compteur = row["compteur"] if row else 0
    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    return paliers[min(compteur, len(paliers) - 1)]


def enregistrer_victoire_arene_repetition(user_id: int) -> float:
    """Enregistre un run d'arène COMPLÉTÉ (champion battu) pour la journée en cours, et
    retourne le multiplicateur à appliquer sur la récompense économique de CE run —
    dégression progressive au fil des runs du jour (config.MULTIPLICATEURS_REPETITION_JOUR_ECO).
    Un run perdu avant le champion n'incrémente rien : on peut retenter au plein tarif."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM arene_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0

    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    multiplicateur = paliers[min(compteur_avant, len(paliers) - 1)]

    cur.execute(
        """
        INSERT INTO arene_victoires_jour (user_id, jour_id, compteur)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (user_id, jour_id),
    )
    conn.commit()
    conn.close()
    return multiplicateur


def enregistrer_victoire_dresseur_repetition(user_id: int) -> float:
    """Enregistre une victoire PvE contre dresseur pour la journée en cours (TOUS
    archétypes confondus), et retourne le multiplicateur à appliquer sur la récompense
    ÉCONOMIQUE (PD + XP) de CETTE victoire — dégression progressive au fil des victoires
    du jour, voir config.MULTIPLICATEURS_REPETITION_JOUR_ECO."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM pve_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0

    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    multiplicateur = paliers[min(compteur_avant, len(paliers) - 1)]

    cur.execute(
        """
        INSERT INTO pve_victoires_jour (user_id, jour_id, compteur)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (user_id, jour_id),
    )
    conn.commit()
    conn.close()
    return multiplicateur


# --- Échanges entre joueurs ---

def creer_echange(joueur1_id: int, joueur2_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO echanges (joueur1_id, joueur2_id, date_creation) VALUES (?, ?, ?)",
        (joueur1_id, joueur2_id, int(time.time())),
    )
    echange_id = cur.lastrowid
    conn.commit()
    conn.close()
    return echange_id


def obtenir_echange(echange_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM echanges WHERE id = ?", (echange_id,))
    row = cur.fetchone()
    conn.close()
    return row


def echange_en_cours_pour_joueur(user_id: int):
    """Retourne l'échange actif d'un joueur, ou None (un seul échange à la fois)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM echanges WHERE actif = 1 AND (joueur1_id = ? OR joueur2_id = ?) LIMIT 1",
        (user_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row


def definir_offre_echange(echange_id: int, proposant_id: int, capture_ids: list, pd: int):
    """Remplace entièrement l'offre d'un joueur (Pokémon + PD) et RÉINITIALISE les deux
    validations — toute modification de l'offre annule les validations précédentes,
    évite qu'un joueur ne modifie discrètement son offre après que l'autre a validé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM echange_pokemon WHERE echange_id = ? AND proposant_id = ?",
        (echange_id, proposant_id),
    )
    for capture_id in capture_ids:
        cur.execute(
            "INSERT INTO echange_pokemon (echange_id, capture_id, proposant_id) VALUES (?, ?, ?)",
            (echange_id, capture_id, proposant_id),
        )

    echange = obtenir_echange(echange_id)
    if echange["joueur1_id"] == proposant_id:
        cur.execute(
            "UPDATE echanges SET joueur1_pd = ?, joueur1_valide = 0, joueur2_valide = 0 WHERE id = ?",
            (pd, echange_id),
        )
    else:
        cur.execute(
            "UPDATE echanges SET joueur2_pd = ?, joueur1_valide = 0, joueur2_valide = 0 WHERE id = ?",
            (pd, echange_id),
        )
    conn.commit()
    conn.close()


def obtenir_offre_echange(echange_id: int, proposant_id: int) -> list:
    """Retourne les captures proposées par ce joueur, avec leurs détails (nom, pc, shiny)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.pokemon_nom, c.pc, c.shiny
        FROM echange_pokemon e
        JOIN captures c ON c.id = e.capture_id
        WHERE e.echange_id = ? AND e.proposant_id = ?
        """,
        (echange_id, proposant_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def valider_offre_echange(echange_id: int, proposant_id: int) -> bool:
    """Marque ce joueur comme ayant validé l'offre actuelle. Retourne True si les DEUX
    joueurs ont maintenant validé (échange prêt à être exécuté)."""
    conn = get_connexion()
    cur = conn.cursor()
    echange = obtenir_echange(echange_id)
    colonne = "joueur1_valide" if echange["joueur1_id"] == proposant_id else "joueur2_valide"
    cur.execute(f"UPDATE echanges SET {colonne} = 1 WHERE id = ?", (echange_id,))
    conn.commit()

    cur.execute("SELECT joueur1_valide, joueur2_valide FROM echanges WHERE id = ?", (echange_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row["joueur1_valide"] and row["joueur2_valide"])


def annuler_echange(echange_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE echanges SET actif = 0 WHERE id = ?", (echange_id,))
    conn.commit()
    conn.close()


def executer_echange(echange_id: int) -> tuple:
    """Exécute l'échange de façon atomique : re-vérifie que chaque joueur possède
    toujours ce qu'il a proposé (au cas où sa collection aurait changé entre-temps),
    puis transfère les Pokémon et les PD des deux côtés. Retourne (succes, message_erreur)."""
    echange = obtenir_echange(echange_id)
    if echange is None or not echange["actif"]:
        return False, "Cet échange n'est plus actif."

    j1, j2 = echange["joueur1_id"], echange["joueur2_id"]
    offre_j1 = obtenir_offre_echange(echange_id, j1)
    offre_j2 = obtenir_offre_echange(echange_id, j2)

    conn = get_connexion()
    cur = conn.cursor()

    # Re-vérification : chaque Pokémon proposé appartient toujours bien à son proposant
    for offre, proposant in ((offre_j1, j1), (offre_j2, j2)):
        for row in offre:
            cur.execute("SELECT user_id FROM captures WHERE id = ?", (row["id"],))
            capture = cur.fetchone()
            if capture is None or capture["user_id"] != proposant:
                conn.close()
                return False, f"Un Pokémon proposé par <@{proposant}> n'est plus disponible (déjà échangé, relâché...)."

    # Re-vérification des soldes
    solde_j1 = obtenir_poke_dollars(j1)
    solde_j2 = obtenir_poke_dollars(j2)

    if solde_j1 < echange["joueur1_pd"]:
        conn.close()
        return False, f"<@{j1}> n'a plus assez de Poké Dollars pour honorer son offre."
    if solde_j2 < echange["joueur2_pd"]:
        conn.close()
        return False, f"<@{j2}> n'a plus assez de Poké Dollars pour honorer son offre."

    # Transfert des Pokémon (changement de propriétaire, id/historique conservés)
    for row in offre_j1:
        cur.execute("UPDATE captures SET user_id = ? WHERE id = ?", (j2, row["id"]))
    for row in offre_j2:
        cur.execute("UPDATE captures SET user_id = ? WHERE id = ?", (j1, row["id"]))

    # Transfert des Poké Dollars
    cur.execute("UPDATE users SET poke_dollars = poke_dollars - ? WHERE user_id = ?", (echange["joueur1_pd"], j1))
    cur.execute("UPDATE users SET poke_dollars = poke_dollars + ? WHERE user_id = ?", (echange["joueur1_pd"], j2))
    cur.execute("UPDATE users SET poke_dollars = poke_dollars - ? WHERE user_id = ?", (echange["joueur2_pd"], j2))
    cur.execute("UPDATE users SET poke_dollars = poke_dollars + ? WHERE user_id = ?", (echange["joueur2_pd"], j1))

    cur.execute("UPDATE echanges SET actif = 0 WHERE id = ?", (echange_id,))
    conn.commit()
    conn.close()
    return True, None


def creer_run_roguelike(joueur_id: int, chemin: list) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO roguelike_runs (joueur_id, chemin, date_creation) VALUES (?, ?, ?)",
        (joueur_id, json.dumps(chemin), int(time.time())),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def obtenir_run_roguelike_actif(joueur_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM roguelike_runs WHERE joueur_id = ? AND actif = 1", (joueur_id,))
    row = cur.fetchone()
    conn.close()
    return row


def obtenir_run_roguelike_par_thread(thread_id: int):
    """Chaque run vit dans son propre fil dédié — c'est la clé la plus fiable pour
    retrouver la bonne run après un redémarrage du bot (une seule instance de vue
    générique est ré-enregistrée pour TOUS les fils actifs, self.run_id serait donc faux
    pour n'importe quelle run sauf celle qui a créé cette instance dans la session en cours)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM roguelike_runs WHERE thread_id = ? AND actif = 1", (str(thread_id),))
    row = cur.fetchone()
    conn.close()
    return row


def obtenir_run_roguelike(run_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM roguelike_runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    conn.close()
    return row


def definir_message_run_roguelike(run_id: int, thread_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE roguelike_runs SET thread_id = ?, message_id = ? WHERE id = ?",
        (str(thread_id), str(message_id), run_id),
    )
    conn.commit()
    conn.close()


def avancer_salle_roguelike(run_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE roguelike_runs SET salle_index = salle_index + 1 WHERE id = ?", (run_id,))
    conn.commit()
    cur.execute("SELECT salle_index FROM roguelike_runs WHERE id = ?", (run_id,))
    nouvel_index = cur.fetchone()["salle_index"]
    conn.close()
    return nouvel_index


def ajouter_relique_roguelike(run_id: int, relique_id: str):
    run = obtenir_run_roguelike(run_id)
    reliques = json.loads(run["reliques"])
    reliques.append(relique_id)
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE roguelike_runs SET reliques = ? WHERE id = ?", (json.dumps(reliques), run_id))
    conn.commit()
    conn.close()


def terminer_run_roguelike(run_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE roguelike_runs SET actif = 0 WHERE id = ?", (run_id,))
    cur.execute("DELETE FROM roguelike_combat WHERE run_id = ?", (run_id,))
    conn.commit()
    conn.close()


def creer_equipe_roguelike(run_id: int, equipe: list):
    """equipe = [{'pokemon_nom':.., 'niveau':.., 'pv_max':..}, ...] — insère à pleine vie."""
    conn = get_connexion()
    cur = conn.cursor()
    for position, mon in enumerate(equipe):
        cur.execute(
            """
            INSERT INTO roguelike_equipe (run_id, position, pokemon_nom, niveau, pv_max, pv_actuels)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, position, mon["pokemon_nom"], mon["niveau"], mon["pv_max"], mon["pv_max"]),
        )
    conn.commit()
    conn.close()


def ajouter_membre_equipe_roguelike(run_id: int, pokemon_nom: str, niveau: int, pv_max: int) -> int:
    """Recrute UN nouveau membre en cours de run (salle recrutement) — prend la 1ère
    position libre. Retourne la position attribuée."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 AS prochaine_position FROM roguelike_equipe WHERE run_id = ?", (run_id,))
    position = cur.fetchone()["prochaine_position"]
    cur.execute(
        """
        INSERT INTO roguelike_equipe (run_id, position, pokemon_nom, niveau, pv_max, pv_actuels)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (run_id, position, pokemon_nom, niveau, pv_max, pv_max),
    )
    conn.commit()
    conn.close()
    return position


def obtenir_equipe_roguelike(run_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM roguelike_equipe WHERE run_id = ? ORDER BY position", (run_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def definir_pv_roguelike(run_id: int, position: int, pv_actuels: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE roguelike_equipe SET pv_actuels = ? WHERE run_id = ? AND position = ?",
        (max(0, pv_actuels), run_id, position),
    )
    conn.commit()
    conn.close()


def soigner_equipe_roguelike(run_id: int, pourcentage: float):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT position, pv_max, pv_actuels FROM roguelike_equipe WHERE run_id = ?", (run_id,))
    for row in cur.fetchall():
        if row["pv_actuels"] <= 0:
            continue  # un Pokémon K.O. ne se réveille pas tout seul au repos, il faut le relique/l'objet adapté
        nouveau_pv = min(row["pv_max"], row["pv_actuels"] + round(row["pv_max"] * pourcentage))
        cur.execute(
            "UPDATE roguelike_equipe SET pv_actuels = ? WHERE run_id = ? AND position = ?",
            (nouveau_pv, run_id, row["position"]),
        )
    conn.commit()
    conn.close()


def creer_combat_roguelike(run_id: int, ennemi_nom: str, ennemi_niveau: int, ennemi_pv_max: int, actif_position: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO roguelike_combat (run_id, ennemi_nom, ennemi_niveau, ennemi_pv_max, ennemi_pv_actuels, actif_position)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            ennemi_nom = excluded.ennemi_nom, ennemi_niveau = excluded.ennemi_niveau,
            ennemi_pv_max = excluded.ennemi_pv_max, ennemi_pv_actuels = excluded.ennemi_pv_max,
            actif_position = excluded.actif_position
        """,
        (run_id, ennemi_nom, ennemi_niveau, ennemi_pv_max, ennemi_pv_max, actif_position),
    )
    conn.commit()
    conn.close()


def obtenir_combat_roguelike(run_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM roguelike_combat WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    conn.close()
    return row


def definir_pv_ennemi_roguelike(run_id: int, pv_actuels: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE roguelike_combat SET ennemi_pv_actuels = ? WHERE run_id = ?", (max(0, pv_actuels), run_id))
    conn.commit()
    conn.close()


def definir_actif_position_roguelike(run_id: int, position: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE roguelike_combat SET actif_position = ? WHERE run_id = ?", (position, run_id))
    conn.commit()
    conn.close()


def terminer_combat_roguelike(run_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM roguelike_combat WHERE run_id = ?", (run_id,))
    conn.commit()
    conn.close()


def enregistrer_record_roguelike(joueur_id: int, etage_atteint: int) -> bool:
    """Met à jour le record du joueur SI cet étage dépasse son ancien record. Retourne
    True si c'est un nouveau record."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT meilleur_etage FROM roguelike_records WHERE joueur_id = ?", (joueur_id,))
    row = cur.fetchone()
    if row is None or etage_atteint > row["meilleur_etage"]:
        cur.execute(
            """
            INSERT INTO roguelike_records (joueur_id, meilleur_etage, date_record) VALUES (?, ?, ?)
            ON CONFLICT(joueur_id) DO UPDATE SET meilleur_etage = excluded.meilleur_etage, date_record = excluded.date_record
            """,
            (joueur_id, etage_atteint, int(time.time())),
        )
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def classement_roguelike(limite: int = 10):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT joueur_id, meilleur_etage FROM roguelike_records ORDER BY meilleur_etage DESC LIMIT ?", (limite,))
    rows = cur.fetchall()
    conn.close()
    return rows


def creer_annonce_marketplace(vendeur_id: int, capture_id: int, prix: int, duree_secondes: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    maintenant = int(time.time())
    cur.execute(
        """
        INSERT INTO marketplace_annonces (vendeur_id, capture_id, prix, date_creation, date_expiration, statut)
        VALUES (?, ?, ?, ?, ?, 'active')
        """,
        (vendeur_id, capture_id, prix, maintenant, maintenant + duree_secondes),
    )
    annonce_id = cur.lastrowid
    conn.commit()
    conn.close()
    return annonce_id


def definir_message_annonce_marketplace(annonce_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE marketplace_annonces SET message_id = ? WHERE id = ?", (str(message_id), annonce_id))
    conn.commit()
    conn.close()


def obtenir_annonce_marketplace(annonce_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marketplace_annonces WHERE id = ?", (annonce_id,))
    row = cur.fetchone()
    conn.close()
    return row


def capture_deja_en_vente(capture_id: int) -> bool:
    """Empêche de mettre en vente un Pokémon déjà listé activement ailleurs."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM marketplace_annonces WHERE capture_id = ? AND statut = 'active' LIMIT 1",
        (capture_id,),
    )
    trouve = cur.fetchone() is not None
    conn.close()
    return trouve


def obtenir_annonces_marketplace_joueur(vendeur_id: int, actives_seulement: bool = True):
    conn = get_connexion()
    cur = conn.cursor()
    if actives_seulement:
        cur.execute(
            "SELECT * FROM marketplace_annonces WHERE vendeur_id = ? AND statut = 'active' ORDER BY date_creation DESC",
            (vendeur_id,),
        )
    else:
        cur.execute(
            "SELECT * FROM marketplace_annonces WHERE vendeur_id = ? ORDER BY date_creation DESC",
            (vendeur_id,),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def obtenir_annonces_marketplace_expirees(maintenant: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM marketplace_annonces WHERE statut = 'active' AND date_expiration <= ?",
        (maintenant,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def marquer_annonce_marketplace(annonce_id: int, statut: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE marketplace_annonces SET statut = ? WHERE id = ?", (statut, annonce_id))
    conn.commit()
    conn.close()


def executer_achat_marketplace(annonce_id: int, acheteur_id: int) -> tuple:
    """Exécute l'achat de façon atomique : re-vérifie que l'annonce est toujours active,
    que le vendeur possède toujours le Pokémon, et que l'acheteur a les fonds — puis
    transfère le Pokémon et les Poké Dollars. Retourne (succes, message_erreur)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marketplace_annonces WHERE id = ?", (annonce_id,))
    annonce = cur.fetchone()
    if annonce is None or annonce["statut"] != "active":
        conn.close()
        return False, "Cette annonce n'est plus disponible (déjà vendue, retirée ou expirée)."
    if annonce["vendeur_id"] == acheteur_id:
        conn.close()
        return False, "Tu ne peux pas acheter ton propre Pokémon !"

    cur.execute("SELECT user_id FROM captures WHERE id = ?", (annonce["capture_id"],))
    capture = cur.fetchone()
    if capture is None or capture["user_id"] != annonce["vendeur_id"]:
        cur.execute("UPDATE marketplace_annonces SET statut = 'annulee' WHERE id = ?", (annonce_id,))
        conn.commit()
        conn.close()
        return False, "Le vendeur ne possède plus ce Pokémon (déjà échangé, relâché...) — annonce annulée."
    conn.close()

    # Solde vérifié via une connexion séparée (même convention que executer_echange).
    solde_acheteur = obtenir_poke_dollars(acheteur_id)
    if solde_acheteur < annonce["prix"]:
        return False, f"Il te manque des Poké Dollars pour cet achat ({solde_acheteur}/{annonce['prix']})."

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE captures SET user_id = ? WHERE id = ?", (acheteur_id, annonce["capture_id"]))
    cur.execute(
        "UPDATE marketplace_annonces SET statut = 'vendue', acheteur_id = ? WHERE id = ?",
        (acheteur_id, annonce_id),
    )
    conn.commit()
    conn.close()

    ajouter_poke_dollars(acheteur_id, -annonce["prix"])
    ajouter_poke_dollars(annonce["vendeur_id"], annonce["prix"])
    return True, None


def rechercher_annonces_marketplace_actives(terme: str, limite: int = 15):
    """Recherche par nom d'espèce parmi les annonces ACTIVES uniquement — insensible à la
    casse ET aux accents (filtrage en Python : peu d'annonces actives à la fois, pas
    besoin d'une recherche SQL, et ça évite les faux "aucun résultat" quand l'accent
    n'est pas tapé — ex: chercher "ecremeuh" doit trouver "Écrémeuh")."""
    import pokemon_data

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.*, c.pokemon_nom, c.pc, c.shiny
        FROM marketplace_annonces m
        JOIN captures c ON c.id = m.capture_id
        WHERE m.statut = 'active'
        ORDER BY m.date_creation DESC
        """,
    )
    toutes = cur.fetchall()
    conn.close()

    terme_normalise = pokemon_data.cle_tri_alphabetique_fr(terme)
    resultats = [row for row in toutes if terme_normalise in pokemon_data.cle_tri_alphabetique_fr(row["pokemon_nom"])]
    return resultats[:limite]


def obtenir_historique_marketplace_joueur(user_id: int, limite: int = 15):
    """Toutes les annonces où le joueur est vendeur OU acheteur (tous statuts confondus),
    les plus récentes d'abord. LEFT JOIN : reste correct même si la capture a depuis été
    relâchée/re-échangée (pokemon_nom devient None dans ce cas plutôt qu'une ligne perdue)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.*, c.pokemon_nom
        FROM marketplace_annonces m
        LEFT JOIN captures c ON c.id = m.capture_id
        WHERE m.vendeur_id = ? OR m.acheteur_id = ?
        ORDER BY m.date_creation DESC
        LIMIT ?
        """,
        (user_id, user_id, limite),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def incrementer_explorations_terminees(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO stats_lifetime (user_id, explorations_terminees) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET explorations_terminees = explorations_terminees + 1
        """,
        (user_id,),
    )
    conn.commit()
    conn.close()


# --- Classements enrichis ---

def classement_victoires_pvp(limite: int = 10):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, victoires_pvp FROM stats_lifetime WHERE victoires_pvp > 0 AND user_id > 0 "
        "ORDER BY victoires_pvp DESC LIMIT ?",
        (limite,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def classement_explorations(limite: int = 10):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, explorations_terminees FROM stats_lifetime WHERE explorations_terminees > 0 "
        "ORDER BY explorations_terminees DESC LIMIT ?",
        (limite,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def obtenir_captures_totales(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT captures_totales FROM stats_lifetime WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["captures_totales"] if row else 0


def obtenir_relation_gladio(user_id: int) -> int:
    """Compteur de familiarité effectif — décroît lentement si le joueur n'a pas
    interagi avec Gladio depuis longtemps (config.GLADIO_JOURS_PAR_PALIER_DECAY)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT compteur, derniere_interaction FROM gladio_relation WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0

    compteur = row["compteur"]
    derniere = row["derniere_interaction"] or 0
    if derniere:
        jours_inactif = (time.time() - derniere) / 86400
        paliers_perdus = int(jours_inactif // config.GLADIO_JOURS_PAR_PALIER_DECAY)
        compteur = max(0, compteur - paliers_perdus)
    return compteur


def incrementer_relation_gladio(user_id: int):
    effectif = obtenir_relation_gladio(user_id)  # applique la décroissance avant d'incrémenter
    maintenant = int(time.time())
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gladio_relation (user_id, compteur, derniere_interaction) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET compteur = ?, derniere_interaction = ?
        """,
        (user_id, effectif + 1, maintenant, effectif + 1, maintenant),
    )
    conn.commit()
    conn.close()


def temps_restant_defi_gladio(user_id: int) -> int:
    """Secondes restantes avant de pouvoir redéfier Gladio (0 = disponible tout de suite)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT dernier_defi FROM gladio_defis WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0
    ecoule = time.time() - row["dernier_defi"]
    restant = config.GLADIO_COOLDOWN_DEFI - ecoule
    return max(0, round(restant))


def marquer_defi_gladio(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gladio_defis (user_id, dernier_defi) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET dernier_defi = excluded.dernier_defi
        """,
        (user_id, int(time.time())),
    )
    conn.commit()
    conn.close()


def reinitialiser_defi_gladio(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM gladio_defis WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def obtenir_serie_victoires_pvp(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT serie FROM pvp_serie_victoires WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["serie"] if row else 0


def incrementer_serie_victoires_pvp(user_id: int) -> int:
    """Incrémente la série de victoires PvP consécutives et retourne la nouvelle valeur."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pvp_serie_victoires (user_id, serie) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET serie = serie + 1
        """,
        (user_id,),
    )
    cur.execute("SELECT serie FROM pvp_serie_victoires WHERE user_id = ?", (user_id,))
    nouvelle_serie = cur.fetchone()["serie"]
    conn.commit()
    conn.close()
    return nouvelle_serie


def reinitialiser_serie_victoires_pvp(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pvp_serie_victoires (user_id, serie) VALUES (?, 0) "
        "ON CONFLICT(user_id) DO UPDATE SET serie = 0",
        (user_id,),
    )
    conn.commit()
    conn.close()


def classement_shiny(limite: int = 10):
    """Top joueurs par nombre de Pokémon shiny capturés À VIE (jamais réduit par un
    relâcher, contrairement à un simple COUNT sur les captures encore en base)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, shiny_totaux AS total_shiny
        FROM stats_lifetime
        WHERE shiny_totaux > 0
        ORDER BY total_shiny DESC
        LIMIT ?
        """,
        (limite,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def obtenir_toutes_races_joueurs():
    """Retourne [(user_id, race_nom), ...] pour tous les joueurs ayant une race —
    le tri par palier se fait côté Python (classement.py) via le catalogue races.py."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT user_id, race_nom FROM joueur_race")
    resultats = [(row["user_id"], row["race_nom"]) for row in cur.fetchall()]
    conn.close()
    return resultats


# --- Suivi économique (snapshots périodiques pour repérer un déséquilibre à temps) ---

def enregistrer_snapshot_economie():
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(poke_dollars), 0) AS total FROM users")
    row = cur.fetchone()
    cur.execute(
        "INSERT OR REPLACE INTO snapshots_economie (date, nb_joueurs, total_pd) VALUES (?, ?, ?)",
        (int(time.time()), row["n"], row["total"]),
    )
    conn.commit()
    conn.close()


def obtenir_historique_economie(limite: int = 14):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM snapshots_economie ORDER BY date DESC LIMIT ?", (limite,))
    resultats = cur.fetchall()
    conn.close()
    return resultats


def obtenir_stats_economie_actuelles():
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(poke_dollars), 0) AS total, COALESCE(AVG(poke_dollars), 0) AS moyenne FROM users")
    row = cur.fetchone()
    conn.close()
    return row["n"], row["total"], row["moyenne"]


# --- Dresseurs PvE ---

def creer_dresseur_actif(archetype_nom: str, channel_id: int, date_expiration: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO dresseurs_actifs (archetype_nom, channel_id, date_expiration) VALUES (?, ?, ?)",
        (archetype_nom, str(channel_id), date_expiration),
    )
    dresseur_id = cur.lastrowid
    conn.commit()
    conn.close()
    return dresseur_id


def obtenir_dresseur_actif(dresseur_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM dresseurs_actifs WHERE id = ?", (dresseur_id,))
    row = cur.fetchone()
    conn.close()
    return row


def dresseur_actif_dans_channel(channel_id: int):
    """Vrai s'il y a un dresseur actif ET non expiré dans ce channel. Nettoie au passage
    tout dresseur resté actif=1 en base alors que sa fenêtre est dépassée (arrive si le
    bot a redémarré entre-temps et a perdu la tâche asyncio qui gère l'expiration) —
    sans ce nettoyage, un dresseur fantôme bloquerait indéfiniment le channel."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE dresseurs_actifs SET actif = 0 WHERE channel_id = ? AND actif = 1 AND date_expiration < ?",
        (str(channel_id), int(time.time())),
    )
    conn.commit()
    cur.execute(
        "SELECT * FROM dresseurs_actifs WHERE channel_id = ? AND actif = 1 LIMIT 1",
        (str(channel_id),),
    )
    row = cur.fetchone()
    conn.close()
    return row


def marquer_dresseur_message(dresseur_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE dresseurs_actifs SET message_id = ? WHERE id = ?", (str(message_id), dresseur_id))
    conn.commit()
    conn.close()


def a_deja_defie_dresseur(dresseur_id: int, user_id: int) -> bool:
    """Indique si ce joueur a déjà affronté ce spawn de dresseur précis (peu importe
    l'issue), pour éviter qu'il le re-défie en boucle tant qu'il est actif."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM dresseur_defis WHERE dresseur_id = ? AND user_id = ?",
        (dresseur_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def enregistrer_defi_dresseur(dresseur_id: int, user_id: int):
    """Marque ce joueur comme ayant défié ce spawn — n'empêche PAS les autres joueurs
    de le défier aussi, contrairement à l'ancien verrou premier-arrivé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO dresseur_defis (dresseur_id, user_id) VALUES (?, ?)",
        (dresseur_id, user_id),
    )
    conn.commit()
    conn.close()


def terminer_dresseur(dresseur_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE dresseurs_actifs SET actif = 0 WHERE id = ?", (dresseur_id,))
    conn.commit()
    conn.close()


def obtenir_dresseurs_actifs_toutes() -> list:
    """Retourne tous les dresseurs marqués actifs, tous channels confondus — utilisé
    uniquement par le nettoyage des messages orphelins au démarrage du bot."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM dresseurs_actifs WHERE actif = 1")
    resultats = cur.fetchall()
    conn.close()
    return resultats


def incrementer_victoires_pve(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO stats_lifetime (user_id, victoires_pve) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET victoires_pve = victoires_pve + 1
        """,
        (user_id,),
    )
    conn.commit()
    conn.close()


def synchroniser_pv_persistant_depuis_combat(combat_id: int, user_id: int):
    """Recopie les PV de fin de combat (table combat_equipe, propre à ce match) vers le
    pool PERSISTANT (etat_combat_pokemon), partagé avec les raids — les dégâts subis en
    PvE restent donc jusqu'au prochain soin, au lieu de se réinitialiser à chaque combat."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pokemon_nom, pv_actuels FROM combat_equipe WHERE combat_id = ? AND user_id = ?",
        (combat_id, user_id),
    )
    for row in cur.fetchall():
        cur.execute(
            """
            INSERT INTO etat_combat_pokemon (user_id, pokemon_nom, pv_actuels) VALUES (?, ?, ?)
            ON CONFLICT(user_id, pokemon_nom) DO UPDATE SET pv_actuels = excluded.pv_actuels
            """,
            (user_id, row["pokemon_nom"], row["pv_actuels"]),
        )
    conn.commit()
    conn.close()


# --- Diagnostic (/status-bot) ---

def obtenir_compteurs_activite() -> dict:
    """Compte les objets actifs actuellement en base — combats PvP/PvE en cours, dresseurs
    et raids actifs. Utilisé par /status-bot pour un diagnostic rapide sans avoir à deviner
    si un souci vient du bot lui-même ou d'un état simplement inhabituel mais normal."""
    conn = get_connexion()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS n FROM combat_pvp WHERE actif = 1")
    combats_actifs = cur.fetchone()["n"]

    cur.execute("SELECT COUNT(*) AS n FROM dresseurs_actifs WHERE actif = 1")
    dresseurs_actifs = cur.fetchone()["n"]

    cur.execute("SELECT COUNT(*) AS n FROM raid_actuel WHERE actif = 1")
    raids_actifs = cur.fetchone()["n"]

    conn.close()
    return {
        "combats_actifs": combats_actifs,
        "dresseurs_actifs": dresseurs_actifs,
        "raids_actifs": raids_actifs,
    }
