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
    # WAL : permet à des lectures et une écriture de se produire en même temps (au lieu du
    # mode par défaut "rollback journal" qui bloque tout lecteur pendant une écriture) —
    # réduit fortement les erreurs "database is locked" quand plusieurs boucles/commandes
    # tapent la DB en même temps (spawns, combats, quêtes...). busy_timeout : si un verrou
    # persiste malgré tout, SQLite réessaie pendant 5s au lieu d'échouer immédiatement.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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

    # Event "Capture Classée" : chaque capture (classique uniquement, VIP exclu, doublons
    # comptés comme les nouvelles) rapporte des points selon la rareté — voir
    # evenements.py pour le barème. Même structure que chasse_shiny_evenement ci-dessus.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS event_capture_rarete (
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

    # Migration : favoris — épingler ses exemplaires préférés pour les retrouver vite
    # dans les listes (Pokédex/PC), pur confort, aucun effet sur le jeu.
    try:
        cur.execute("ALTER TABLE captures ADD COLUMN favori INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Migration : surnom — personnalisation d'un exemplaire précis pour l'attachement,
    # indépendant de tout aspect économique. NULL = pas de surnom (nom d'espèce affiché
    # normalement partout ailleurs dans le bot, qui continue de fonctionner par nom
    # d'espèce — le surnom n'apparaît que dans les écrans dédiés Pokédex/PC).
    try:
        cur.execute("ALTER TABLE captures ADD COLUMN surnom TEXT")
    except sqlite3.OperationalError:
        pass

    # Migration : source de la capture ("classique"/"VIP" pour les spawns sauvages, None
    # pour tout le reste — dons admin, œufs/élevage, raids...). Sert notamment à l'event
    # "Capture Classée" (voir evenements.py) qui ne doit compter QUE le spawn classique.
    try:
        cur.execute("ALTER TABLE captures ADD COLUMN source TEXT")
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
        CREATE TABLE IF NOT EXISTS connexion_quotidienne (
            user_id INTEGER PRIMARY KEY,
            streak INTEGER NOT NULL DEFAULT 0,
            dernier_jour INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recap_hebdo_snapshot (
            user_id INTEGER PRIMARY KEY,
            date_snapshot INTEGER NOT NULL DEFAULT 0,
            victoires_pvp INTEGER NOT NULL DEFAULT 0,
            victoires_pve INTEGER NOT NULL DEFAULT 0,
            captures_totales INTEGER NOT NULL DEFAULT 0,
            explorations_terminees INTEGER NOT NULL DEFAULT 0,
            shiny_totaux INTEGER NOT NULL DEFAULT 0,
            poke_dollars INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS event_capture_rarete_points (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (event_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS caisson_croissance_slots (
            user_id INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            date_debut INTEGER NOT NULL,
            PRIMARY KEY (user_id, slot)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS contrats_actifs (
            user_id INTEGER NOT NULL,
            jour INTEGER NOT NULL,
            position INTEGER NOT NULL,
            contrat_id TEXT NOT NULL,
            compteur INTEGER NOT NULL DEFAULT 0,
            complete INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, jour, position)
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
            bonus_mutation REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (run_id, position)
        )
        """
    )

    # Migration pour les bases créées avant l'Autel de Mutation (roguelike)
    try:
        cur.execute("ALTER TABLE roguelike_equipe ADD COLUMN bonus_mutation REAL NOT NULL DEFAULT 1.0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS roguelike_combat (
            run_id INTEGER PRIMARY KEY,
            ennemi_nom TEXT NOT NULL,
            ennemi_niveau INTEGER NOT NULL,
            ennemi_pv_max INTEGER NOT NULL,
            ennemi_pv_actuels INTEGER NOT NULL,
            actif_position INTEGER NOT NULL DEFAULT 0,
            est_rencontre_speciale INTEGER NOT NULL DEFAULT 0,
            equipe_restante TEXT NOT NULL DEFAULT '[]',
            est_dresseur INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Migration pour les bases créées avant les combats de Dresseur (roguelike)
    try:
        cur.execute("ALTER TABLE roguelike_combat ADD COLUMN equipe_restante TEXT NOT NULL DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà
    try:
        cur.execute("ALTER TABLE roguelike_combat ADD COLUMN est_dresseur INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

    # Migration pour les bases créées avant la Rencontre scintillante (roguelike)
    try:
        cur.execute("ALTER TABLE roguelike_combat ADD COLUMN est_rencontre_speciale INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonne existe déjà

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
        CREATE TABLE IF NOT EXISTS echange_objets (
            echange_id INTEGER NOT NULL,
            proposant_id INTEGER NOT NULL,
            objet_cle TEXT NOT NULL,
            quantite INTEGER NOT NULL,
            PRIMARY KEY (echange_id, proposant_id, objet_cle)
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

    # Terrain de zone (Champ Électrifié/Herbu/Brumeux/Psychique) : effet actif sur tout
    # le terrain pendant plusieurs tours, distinct de la météo (peut coexister).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_terrain_zone (
            combat_id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            tours_restants INTEGER NOT NULL
        )
        """
    )

    # Écrans d'équipe (Reflet, Mur Lumière, Voile Aurore, Vent Arrière, Rune Protect,
    # Garde Large, Prévention, Tatamigaeshi) — clé d'équipe unifiée 1v1/2v2 : en 1v1
    # equipe_cle = str(user_id) du joueur protégé, en 2v2 "equipe1"/"equipe2".
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_ecrans (
            combat_id INTEGER NOT NULL,
            equipe_cle TEXT NOT NULL,
            type_effet TEXT NOT NULL,
            tours_restants INTEGER NOT NULL,
            PRIMARY KEY (combat_id, equipe_cle, type_effet)
        )
        """
    )

    # Effets globaux à durée (Lot C) : Distorsion (trick_room), Zone Étrange
    # (wonder_room), Zone Magique (magic_room), Gravité (gravite), Verrou Enchanté
    # (verrou_enchante), Lance-Boue (lance_boue) — plusieurs peuvent être actifs EN MÊME
    # TEMPS (comme dans les vrais jeux), d'où une table à part de combat_meteo/
    # combat_terrain_zone qui ne gèrent chacune qu'un seul état à la fois.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_effets_globaux (
            combat_id INTEGER NOT NULL,
            type_effet TEXT NOT NULL,
            tours_restants INTEGER NOT NULL,
            PRIMARY KEY (combat_id, type_effet)
        )
        """
    )

    # Requiem (Chant du Trépas) : compte à rebours PAR Pokémon touché (pas un état
    # global) — celui qui l'a lancé est affecté aussi, comme tout le monde sur le terrain.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_requiem (
            combat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pokemon_nom TEXT NOT NULL,
            tours_restants INTEGER NOT NULL,
            PRIMARY KEY (combat_id, user_id, pokemon_nom)
        )
        """
    )

    # Journal du tour PRÉCÉDENT — conservé pour l'affichage dans la scène visuelle (voir
    # combat_visuel.py) : le joueur peut ainsi comparer avec ce que l'adversaire a fait
    # au tour d'avant sans que ça disparaisse dès que le tour suivant se résout.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_log_precedent (
            combat_id INTEGER PRIMARY KEY,
            log_json TEXT NOT NULL
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

    # Réparation ponctuelle : des joueurs ayant fini la Partie 1 (7 chapitres, à l'époque
    # le seul contenu existant) se sont retrouvés avec termine=1 stocké en base — un flag
    # qui n'est JAMAIS réévalué dynamiquement contre la vraie longueur de
    # QUETE_PRINCIPALE_CHAPITRES, seulement positionné une fois au moment de la
    # complétion (voir avancer_quete_principale). Depuis l'ajout de la Partie 2 (10
    # chapitres de plus), ces joueurs restaient bloqués pour toujours, incapables de
    # progresser même si le nouveau contenu existe. On les débloque ici (idempotent, sans
    # danger de le relancer à chaque démarrage) : un joueur réellement bloqué a
    # chapitre < longueur actuelle (ex: 7 < 17, jamais incrémenté puisqu'il avait été
    # marqué "terminé" avant l'extension) ; un joueur ayant VRAIMENT fini tout le contenu
    # actuel a chapitre == longueur actuelle (ex: 17 == 17) — condition stricte "<" pour
    # ne débloquer QUE les premiers, jamais les seconds.
    import config as config_module
    cur.execute(
        "UPDATE quete_principale_progression SET termine = 0 WHERE termine = 1 AND chapitre < ?",
        (len(config_module.QUETE_PRINCIPALE_CHAPITRES),),
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


def avancer_quete_principale(user_id: int, evenement: str, contexte: dict = None, montant: int = 1) -> dict | None:
    """Fait progresser la quête principale si `evenement` correspond à l'objectif du
    chapitre EN COURS du joueur (les événements pour un chapitre déjà passé ou pas encore
    atteint sont ignorés silencieusement). Retourne un dict de notification de chapitre
    tout juste complété (titre/outro/récompense + éventuel nouveau chapitre à annoncer) si
    CET appel vient de faire franchir le seuil, sinon None. La récompense est créditée
    immédiatement (pas d'étape de réclamation séparée, contrairement aux quêtes jour/semaine).

    `contexte`/`filtre` optionnels (même mécanique que les quêtes jour/semaine) — un
    chapitre SANS "filtre" dans sa définition se comporte exactement comme avant
    (rétrocompatible avec tous les chapitres de la Partie 1), un chapitre AVEC "filtre"
    exige en plus une correspondance exacte (ou une valeur parmi une liste) sur le
    contexte transmis — ex: {"rarete": ["rare", "hyper_rare", "legendaire"]}."""
    import config

    contexte = contexte or {}
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

    filtre = chapitre_actuel.get("filtre")
    if filtre:
        for cle, attendu in filtre.items():
            valeur_reelle = contexte.get(cle)
            if isinstance(attendu, list):
                if valeur_reelle not in attendu:
                    return None
            elif isinstance(valeur_reelle, list):
                # ex: futur filtre {"type": "feu"} contre un Pokémon bi-type — voir la
                # même correction dans database/contrats.py pour le contexte complet.
                if attendu not in valeur_reelle:
                    return None
            elif valeur_reelle != attendu:
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


# reinitialiser_pool_raid_joueur, joueur_dans_raid_actif : déplacées dans
# database/raids.py (avec le reste du domaine raid, voir plus bas dans ce fichier).



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


# Domaine parrainage (enregistrer_parrainage, compter_parrainages, etc.) déplacé dans
# database/parrainage.py — voir le `from .parrainage import *` en fin de fichier.
# (est_booster_serveur/definir_booster_serveur restent ici, pas un vrai domaine à part.)



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


# Domaine Plus ou Moins (obtenir/definir_record_plus_ou_moins) déplacé dans
# database/plus_ou_moins.py — voir le `from .plus_ou_moins import *` en fin de fichier.



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

# Domaine clan (obtenir_statut_equipe, changer_equipe, obtenir_equipe,
# classement_equipes, contribution/objectifs/historique clan) déplacé dans
# database/clan.py — voir le `from .clan import *` en fin de fichier.


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


# Domaine arène + repaires (spawn, runs, badges, multiplicateur de dégression) déplacé
# dans database/arene_repaires.py — voir le `from .arene_repaires import *` en fin de
# fichier. (marquer_runs_arene_en_cours_defaite, multiplicateur_arene_du_jour,
# enregistrer_victoire_arene/dresseur_repetition, tout le domaine dresseurs/Gladio
# restent ici pour l'instant, prochain lot.)


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


def ajouter_capture(user_id: int, pokemon_nom: str, pc: int, shiny: bool = False, ivs: dict = None, source: str = None) -> str | None:
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
            capacite, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, pokemon_nom, pc, int(time.time()), int(shiny),
            ivs.get("pv"), ivs.get("attaque"), ivs.get("defense"),
            ivs.get("attaque_spe"), ivs.get("defense_spe"), ivs.get("vitesse"),
            capacites_module.capacite_pour_espece(pokemon_nom), source,
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


def obtenir_meilleure_capture_id(user_id: int, pokemon_nom: str) -> int | None:
    """L'id de l'exemplaire au PC le plus élevé pour cette espèce chez ce joueur —
    c'est cet exemplaire précis que représente un emplacement de l'équipe de combat
    (qui ne référence l'espèce que par son nom, pas par id individuel). Utilisé pour
    savoir QUEL exemplaire surnommer/consulter depuis l'équipe de combat."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC, id ASC LIMIT 1",
        (user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["id"] if row else None


def obtenir_favori_surnom_par_espece(user_id: int) -> dict:
    """Retourne {pokemon_nom: {"favori": bool, "surnom": str|None}} — favori=True si AU
    MOINS un exemplaire de l'espèce est favori, surnom=celui du meilleur PC (même
    exemplaire "représentatif" que obtenir_meilleure_capture_id). Utilisé par le Pokédex
    et l'équipe de combat pour afficher l'étoile/le surnom au niveau de l'espèce."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pokemon_nom, pc, favori, surnom FROM captures WHERE user_id = ? ORDER BY pokemon_nom, pc DESC, id ASC",
        (user_id,),
    )
    resultats = {}
    for row in cur.fetchall():
        entry = resultats.setdefault(row["pokemon_nom"], {"favori": False, "surnom": None, "_meilleur_pc_vu": -1})
        if row["favori"]:
            entry["favori"] = True
        if row["pc"] > entry["_meilleur_pc_vu"]:
            entry["_meilleur_pc_vu"] = row["pc"]
            entry["surnom"] = row["surnom"]
    conn.close()
    for entry in resultats.values():
        del entry["_meilleur_pc_vu"]
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
    verrouille, favori, surnom, rang) triés par nom puis par PC décroissant. Rang = 1
    signifie que c'est le seul/meilleur exemplaire de son espèce — utile pour afficher un
    avertissement si l'utilisateur tente de relâcher le dernier représentant d'une espèce
    (perte de l'entrée Pokédex)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, pokemon_nom, pc, shiny, verrouille, favori, surnom,
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


def definir_favori_capture(capture_id: int, favori: bool):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE captures SET favori = ? WHERE id = ?", (int(favori), capture_id))
    conn.commit()
    conn.close()


def obtenir_captures_favorites(user_id: int):
    """Tous les exemplaires épinglés en favori d'un joueur (id, pokemon_nom, pc, shiny,
    surnom) — pur confort d'affichage, aucun effet sur le jeu."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, pokemon_nom, pc, shiny, surnom FROM captures WHERE user_id = ? AND favori = 1 "
        "ORDER BY pokemon_nom COLLATE ALPHABET_FR ASC, pc DESC",
        (user_id,),
    )
    resultats = cur.fetchall()
    conn.close()
    return resultats


def definir_surnom_capture(capture_id: int, surnom: str | None):
    """surnom=None (ou chaîne vide) efface le surnom — l'exemplaire réaffiche alors son
    nom d'espèce normal partout."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE captures SET surnom = ? WHERE id = ?", (surnom or None, capture_id))
    conn.commit()
    conn.close()


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

# Domaine raids (obtenir_raid_actif_pour_channel, demarrer_raid, etc.) déplacé dans
# database/raids.py — voir le `from .raids import *` en fin de fichier.

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


# Seuil du 2e siège synthétique d'un joueur humain en double combat solo-vs-duo (voir
# combat_2v2.id_delegue/DELEGUE_OFFSET) — dupliqué ici en dur plutôt qu'importé, pour ne
# pas faire dépendre ce module générique de combat_2v2.py. Les fonctions ci-dessous qui
# touchent la RÉSERVE (combat_equipe) redirigent automatiquement un ID délégué vers l'ID
# réel du joueur : la réserve est UNIQUE et partagée entre ses 2 sièges, jamais dupliquée
# — sans ça, un même Pokémon aurait 2 PV différents selon le siège consulté.
DELEGUE_OFFSET = 2_000_000_000_000_000_000


def _id_equipe(user_id: int) -> int:
    """Résout un ID de siège délégué vers l'ID réel du joueur, pour toute fonction qui
    lit/écrit la réserve de combat (combat_equipe) — jamais pour les données propres au
    SIÈGE lui-même (actif courant, action du tour), qui restent bien séparées par siège."""
    return user_id - DELEGUE_OFFSET if user_id >= DELEGUE_OFFSET else user_id


def obtenir_capacite_combat(combat_id: int, user_id: int, pokemon_nom: str) -> str | None:
    """Talent SNAPSHOTÉ pour ce combat précis (voir initialiser_equipe_combat_pvp) — à
    utiliser dans le moteur de combat plutôt que obtenir_capacite_reelle, pour que ça
    fonctionne identiquement pour un vrai joueur ET un dresseur/boss IA."""
    user_id = _id_equipe(user_id)
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
    user_id = _id_equipe(user_id)
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
    user_id = _id_equipe(user_id)
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_equipe SET objet_tenu = ? WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (objet, combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def definir_capacite_combat(combat_id: int, user_id: int, pokemon_nom: str, capacite: str | None):
    """Écrase le talent SNAPSHOTÉ pour ce combat précis (voir obtenir_capacite_combat) —
    utilisé par le Draft PvP pour imposer un talent tiré au hasard après l'initialisation
    normale de l'équipe, qui aurait sinon copié le vrai talent de la capture du joueur.
    N'affecte jamais le talent réel hors combat."""
    user_id = _id_equipe(user_id)
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE combat_equipe SET capacite = ? WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (capacite, combat_id, user_id, pokemon_nom),
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
    user_id = _id_equipe(user_id)
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
    user_id = _id_equipe(user_id)
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
    user_id = _id_equipe(user_id)
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


# marquer_runs_arene_en_cours_defaite : déplacée dans database/dresseurs_gladio.py
# (avec le reste du domaine dresseurs/Gladio, voir plus bas dans ce fichier).

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


# --- Terrain de zone (Champ Électrifié/Herbu/Brumeux/Psychique) ------------------------

def obtenir_terrain_zone(combat_id: int) -> dict | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type, tours_restants FROM combat_terrain_zone WHERE combat_id = ?", (combat_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {"type": row["type"], "tours_restants": row["tours_restants"]}


def definir_terrain_zone(combat_id: int, type_terrain: str | None, tours: int = 5):
    conn = get_connexion()
    cur = conn.cursor()
    if type_terrain is None:
        cur.execute("DELETE FROM combat_terrain_zone WHERE combat_id = ?", (combat_id,))
    else:
        cur.execute(
            """
            INSERT INTO combat_terrain_zone (combat_id, type, tours_restants) VALUES (?, ?, ?)
            ON CONFLICT(combat_id) DO UPDATE SET type = excluded.type, tours_restants = excluded.tours_restants
            """,
            (combat_id, type_terrain, tours),
        )
    conn.commit()
    conn.close()


def decrementer_terrain_zone(combat_id: int) -> str | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type, tours_restants FROM combat_terrain_zone WHERE combat_id = ?", (combat_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    nouveau = row["tours_restants"] - 1
    if nouveau <= 0:
        cur.execute("DELETE FROM combat_terrain_zone WHERE combat_id = ?", (combat_id,))
        conn.commit()
        conn.close()
        return row["type"]
    cur.execute("UPDATE combat_terrain_zone SET tours_restants = ? WHERE combat_id = ?", (nouveau, combat_id))
    conn.commit()
    conn.close()
    return None


# --- Écrans d'équipe (Reflet, Mur Lumière, Voile Aurore, Vent Arrière, Rune Protect,
# --- Garde Large, Prévention, Tatamigaeshi) ---------------------------------------------

def equipe_cle_pour_joueur(combat_id: int, user_id: int) -> str:
    """Clé d'équipe unifiée 1v1/2v2 : en 1v1 chaque camp = 1 joueur, donc equipe_cle =
    str(user_id) directement. En 2v2, regarde dans combat_2v2_joueurs si présent."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT equipe FROM combat_2v2_joueurs WHERE combat_id = ? AND user_id = ?", (combat_id, user_id))
    row = cur.fetchone()
    conn.close()
    if row is not None:
        return f"equipe{row['equipe']}"
    return str(user_id)


def activer_ecran(combat_id: int, equipe_cle: str, type_effet: str, tours: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_ecrans (combat_id, equipe_cle, type_effet, tours_restants) VALUES (?, ?, ?, ?)
        ON CONFLICT(combat_id, equipe_cle, type_effet) DO UPDATE SET tours_restants = excluded.tours_restants
        """,
        (combat_id, equipe_cle, type_effet, tours),
    )
    conn.commit()
    conn.close()


def obtenir_ecran(combat_id: int, equipe_cle: str, type_effet: str) -> int | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT tours_restants FROM combat_ecrans WHERE combat_id = ? AND equipe_cle = ? AND type_effet = ?",
        (combat_id, equipe_cle, type_effet),
    )
    row = cur.fetchone()
    conn.close()
    return row["tours_restants"] if row else None


def obtenir_tous_ecrans_equipe(combat_id: int, equipe_cle: str) -> list:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT type_effet, tours_restants FROM combat_ecrans WHERE combat_id = ? AND equipe_cle = ?",
        (combat_id, equipe_cle),
    )
    resultats = [{"type_effet": row["type_effet"], "tours_restants": row["tours_restants"]} for row in cur.fetchall()]
    conn.close()
    return resultats


def decrementer_ecrans_equipe(combat_id: int, equipe_cle: str) -> list:
    """À appeler une fois par tour résolu, PAR ÉQUIPE (pas par joueur — en 2v2, appeler
    une seule fois par equipe_cle, sinon un camp à 2 joueurs verrait ses écrans décompter
    deux fois plus vite). Retourne la liste des type_effet qui viennent d'expirer."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT type_effet, tours_restants FROM combat_ecrans WHERE combat_id = ? AND equipe_cle = ?",
        (combat_id, equipe_cle),
    )
    rows = cur.fetchall()
    expires = []
    for row in rows:
        nouveau = row["tours_restants"] - 1
        if nouveau <= 0:
            cur.execute(
                "DELETE FROM combat_ecrans WHERE combat_id = ? AND equipe_cle = ? AND type_effet = ?",
                (combat_id, equipe_cle, row["type_effet"]),
            )
            expires.append(row["type_effet"])
        else:
            cur.execute(
                "UPDATE combat_ecrans SET tours_restants = ? WHERE combat_id = ? AND equipe_cle = ? AND type_effet = ?",
                (nouveau, combat_id, equipe_cle, row["type_effet"]),
            )
    conn.commit()
    conn.close()
    return expires


# --- Lot B : Brume / Aromathérapie ------------------------------------------------------

def retirer_tous_statuts_joueur(combat_id: int, user_id: int) -> int:
    """Guérit TOUTE l'équipe de ce joueur (pas juste le Pokémon actif) — Aromathérapie/
    Glas de Soin. Retourne le nombre de Pokémon effectivement guéris (pour le log)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM combat_statuts WHERE combat_id = ? AND user_id = ?", (combat_id, user_id))
    nb = cur.fetchone()["n"]
    cur.execute("DELETE FROM combat_statuts WHERE combat_id = ? AND user_id = ?", (combat_id, user_id))
    conn.commit()
    conn.close()
    return nb


def reinitialiser_boosts_combat(combat_id: int):
    """Brume : remet TOUS les stages de stats (des DEUX/QUATRE Pokémon actifs, tous
    camps confondus) à zéro d'un coup — supprime toutes les lignes combat_boosts de ce
    combat plutôt que de cibler un Pokémon précis."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM combat_boosts WHERE combat_id = ?", (combat_id,))
    conn.commit()
    conn.close()


# --- Effets globaux à durée (Distorsion/Zone Étrange/Zone Magique/Gravité/Verrou
# --- Enchanté/Lance-Boue) ----------------------------------------------------------------

def activer_effet_global(combat_id: int, type_effet: str, tours: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_effets_globaux (combat_id, type_effet, tours_restants) VALUES (?, ?, ?)
        ON CONFLICT(combat_id, type_effet) DO UPDATE SET tours_restants = excluded.tours_restants
        """,
        (combat_id, type_effet, tours),
    )
    conn.commit()
    conn.close()


def obtenir_effet_global(combat_id: int, type_effet: str) -> int | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT tours_restants FROM combat_effets_globaux WHERE combat_id = ? AND type_effet = ?",
        (combat_id, type_effet),
    )
    row = cur.fetchone()
    conn.close()
    return row["tours_restants"] if row else None


def decrementer_effets_globaux(combat_id: int) -> list:
    """À appeler une fois par tour résolu. Retourne la liste des type_effet qui viennent
    d'expirer à l'instant (pour un message de log)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type_effet, tours_restants FROM combat_effets_globaux WHERE combat_id = ?", (combat_id,))
    rows = cur.fetchall()
    expires = []
    for row in rows:
        nouveau = row["tours_restants"] - 1
        if nouveau <= 0:
            cur.execute(
                "DELETE FROM combat_effets_globaux WHERE combat_id = ? AND type_effet = ?",
                (combat_id, row["type_effet"]),
            )
            expires.append(row["type_effet"])
        else:
            cur.execute(
                "UPDATE combat_effets_globaux SET tours_restants = ? WHERE combat_id = ? AND type_effet = ?",
                (nouveau, combat_id, row["type_effet"]),
            )
    conn.commit()
    conn.close()
    return expires


# --- Requiem (Chant du Trépas) : compte à rebours par Pokémon --------------------------

def obtenir_requiem(combat_id: int, user_id: int, pokemon_nom: str) -> int | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT tours_restants FROM combat_requiem WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    return row["tours_restants"] if row else None


def definir_requiem(combat_id: int, user_id: int, pokemon_nom: str, tours: int = 3):
    """N'écrase JAMAIS un compte à rebours déjà en cours (comme dans les vrais jeux —
    relancer Requiem sur un Pokémon déjà affecté ne réinitialise pas son compteur)."""
    if obtenir_requiem(combat_id, user_id, pokemon_nom) is not None:
        return
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO combat_requiem (combat_id, user_id, pokemon_nom, tours_restants) VALUES (?, ?, ?, ?)",
        (combat_id, user_id, pokemon_nom, tours),
    )
    conn.commit()
    conn.close()


def retirer_requiem(combat_id: int, user_id: int, pokemon_nom: str):
    """À appeler quand ce Pokémon quitte le terrain (switch) — échappe au K.O., comme
    dans les vrais jeux."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM combat_requiem WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    conn.commit()
    conn.close()


def decrementer_requiem_actifs(combat_id: int, actifs: list) -> list:
    """À appeler une fois par tour résolu, avec la liste des (user_id, pokemon_nom)
    actuellement ACTIFS sur le terrain (le compte à rebours ne progresse que pour eux).
    Retourne [(user_id, pokemon_nom)] de ceux qui viennent d'atteindre 0 (K.O. à
    appliquer par l'appelant)."""
    conn = get_connexion()
    cur = conn.cursor()
    tombes = []
    for user_id, pokemon_nom in actifs:
        cur.execute(
            "SELECT tours_restants FROM combat_requiem WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
            (combat_id, user_id, pokemon_nom),
        )
        row = cur.fetchone()
        if row is None:
            continue
        nouveau = row["tours_restants"] - 1
        if nouveau <= 0:
            cur.execute(
                "DELETE FROM combat_requiem WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
                (combat_id, user_id, pokemon_nom),
            )
            tombes.append((user_id, pokemon_nom))
        else:
            cur.execute(
                "UPDATE combat_requiem SET tours_restants = ? WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
                (nouveau, combat_id, user_id, pokemon_nom),
            )
    conn.commit()
    conn.close()
    return tombes


# --- Journal du tour précédent (pour l'affichage visuel, voir combat_visuel.py) --------

def obtenir_log_precedent(combat_id: int) -> list | None:
    """Retourne le journal du tour précédent (liste de lignes), ou None si c'est le
    premier tour du combat (rien à afficher en "précédent" pour l'instant)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT log_json FROM combat_log_precedent WHERE combat_id = ?", (combat_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    import json
    return json.loads(row["log_json"])


def definir_log_precedent(combat_id: int, log: list):
    """À appeler après avoir affiché le journal d'un tour — le mémorise pour qu'il reste
    visible (en second plan) quand le tour suivant se résout."""
    import json
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_log_precedent (combat_id, log_json) VALUES (?, ?)
        ON CONFLICT(combat_id) DO UPDATE SET log_json = excluded.log_json
        """,
        (combat_id, json.dumps(log)),
    )
    conn.commit()
    conn.close()


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

# Événements serveur (défi collectif, chasse aux shiny, capture rareté) déplacés
# dans database/quetes_evenements.py — voir le `from .quetes_evenements import *`
# en fin de fichier.



# --- Codes promo ---

# Domaine codes promo (creer_code_promo, utiliser_code_promo, etc.) déplacé dans
# database/codes_promo.py — voir le `from .codes_promo import *` en fin de fichier.


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

# nb_slots_exploration ... especes_en_exploration : déplacées dans database/exploration.py
# (obtenir_equipe_combat_disponible juste après reste ici, domaine combat).

def obtenir_equipe_combat_disponible(user_id: int) -> list:
    """Équipe de combat, en excluant les espèces actuellement parties en exploration."""
    indisponibles = especes_en_exploration(user_id)
    return [nom for nom in obtenir_equipe_combat(user_id) if nom not in indisponibles]


# --- Incubateur (Laboratoire) ---
# 1 seul emplacement en V1, volontairement simple — pas d'extension achetable pour l'instant
# (contrairement à l'Exploration), à ajouter plus tard si le système plaît.

# obtenir_incubation_active ... forcer_fin_incubation : déplacées dans
# database/exploration.py — voir le `from .exploration import *` en fin de fichier.

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
# Quêtes journalières/hebdomadaires (_periode_id, incrementer_progression_quete,
# reclamer_quete) déplacées dans database/quetes_evenements.py.
# (obtenir_progression_quete_principale/avancer_quete_principale, tout en haut de ce
# fichier, restent ici — dépendance déjà établie par arene_repaires.py.)



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


# Famille dégression quotidienne arène/dresseur (multiplicateur_arene_du_jour,
# enregistrer_victoire_arene/dresseur_repetition) déplacée dans database/dresseurs_gladio.py.

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


def obtenir_explorations_terminees(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT explorations_terminees FROM stats_lifetime WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["explorations_terminees"] if row else 0


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


# Domaine Gladio (relation, cooldown de défi) déplacé dans database/dresseurs_gladio.py.

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


def obtenir_shiny_totaux(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT shiny_totaux FROM stats_lifetime WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["shiny_totaux"] if row else 0


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

# Domaine dresseurs PvE (spawn, défis, nettoyage) déplacé dans
# database/dresseurs_gladio.py — voir le `from .dresseurs_gladio import *` en fin de fichier.

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


def obtenir_victoires_pve(user_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT victoires_pve FROM stats_lifetime WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["victoires_pve"] if row else 0


def synchroniser_pv_persistant_depuis_combat(combat_id: int, user_id: int):
    """Recopie les PV de fin de combat (table combat_equipe, propre à ce match) vers le
    pool PERSISTANT (etat_combat_pokemon), partagé avec les raids — les dégâts subis en
    PvE restent donc jusqu'au prochain soin, au lieu de se réinitialiser à chaque combat."""
    user_id = _id_equipe(user_id)
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


# Domaines extraits en sous-modules (package database/) — voir chaque fichier pour le
# détail. Import fait ICI, tout en bas, après que get_connexion (et tout le reste du
# noyau) soit défini : nécessaire pour que `from . import get_connexion` fonctionne
# depuis roguelike.py sans import circulaire réel.
from .roguelike import *  # noqa: F401,F403
from .plus_ou_moins import *  # noqa: F401,F403
from .raids import *  # noqa: F401,F403
from .codes_promo import *  # noqa: F401,F403
from .parrainage import *  # noqa: F401,F403
from .echanges_marketplace import *  # noqa: F401,F403
from .exploration import *  # noqa: F401,F403
from .clan import *  # noqa: F401,F403
from .arene_repaires import *  # noqa: F401,F403
from .dresseurs_gladio import *  # noqa: F401,F403
from .quetes_evenements import *  # noqa: F401,F403
from .connexion_quotidienne import *  # noqa: F401,F403
from .recap_hebdomadaire import *  # noqa: F401,F403
from .caisson_croissance import *  # noqa: F401,F403
from .contrats import *  # noqa: F401,F403
