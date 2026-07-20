import sqlite3
import time

import config

DB_PATH = "pokebot.sqlite3"

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

    conn.commit()
    conn.close()


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
    avoir vérifié via obtenir_statut_equipe que c'est autorisé)."""
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    cur.execute(
        "UPDATE users SET team = ?, team_last_change = ? WHERE user_id = ?",
        (nouvelle_equipe, int(time.time()), user_id),
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


def ajouter_capture(user_id: int, pokemon_nom: str, pc: int, shiny: bool = False, ivs: dict = None):
    conn = get_connexion()
    cur = conn.cursor()
    _assurer_joueur_existe(cur, user_id)
    ivs = ivs or {}
    cur.execute(
        """
        INSERT INTO captures (
            user_id, pokemon_nom, pc, date_capture, shiny,
            iv_pv, iv_attaque, iv_defense, iv_attaque_spe, iv_defense_spe, iv_vitesse
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, pokemon_nom, pc, int(time.time()), int(shiny),
            ivs.get("pv"), ivs.get("attaque"), ivs.get("defense"),
            ivs.get("attaque_spe"), ivs.get("defense_spe"), ivs.get("vitesse"),
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

def obtenir_pv_actuels(user_id: int, pokemon_nom: str, pv_max: int) -> int:
    """Retourne les PV actuels d'une espèce en combat (initialisés au max si jamais vue).
    Si le max a augmenté depuis (meilleur PC capturé), les PV actuels sont juste plafonnés
    au nouveau max, sans soin gratuit."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT pv_actuels FROM etat_combat_pokemon WHERE user_id = ? AND pokemon_nom = ?",
        (user_id, pokemon_nom),
    )
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO etat_combat_pokemon (user_id, pokemon_nom, pv_actuels) VALUES (?, ?, ?)",
            (user_id, pokemon_nom, pv_max),
        )
        conn.commit()
        conn.close()
        return pv_max

    pv_actuels = min(row["pv_actuels"], pv_max)
    conn.close()
    return pv_actuels


def modifier_pv_pokemon(user_id: int, pokemon_nom: str, delta: int, pv_max: int) -> int:
    """Applique un delta (positif = soin, négatif = dégâts) aux PV actuels d'une espèce,
    borné entre 0 et pv_max. Retourne les PV après modification."""
    pv_actuels = obtenir_pv_actuels(user_id, pokemon_nom, pv_max)
    nouveau_pv = max(0, min(pv_max, pv_actuels + delta))

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO etat_combat_pokemon (user_id, pokemon_nom, pv_actuels) VALUES (?, ?, ?)
        ON CONFLICT(user_id, pokemon_nom) DO UPDATE SET pv_actuels = excluded.pv_actuels
        """,
        (user_id, pokemon_nom, nouveau_pv),
    )
    conn.commit()
    conn.close()
    return nouveau_pv


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
    Retourne {pokemon_nom: quantite_relachable}."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pokemon_nom,
               ROW_NUMBER() OVER (PARTITION BY pokemon_nom ORDER BY pc DESC, id ASC) AS rang
        FROM captures
        WHERE user_id = ?
        """,
        (user_id,),
    )
    resultats = {}
    for row in cur.fetchall():
        if row["rang"] > 1:
            resultats[row["pokemon_nom"]] = resultats.get(row["pokemon_nom"], 0) + 1
    conn.close()
    return resultats


def obtenir_doublons_detailles(user_id: int):
    """Comme previsualiser_doublons, mais retourne chaque exemplaire individuel
    (id, pokemon_nom, pc, shiny) plutôt qu'un simple total par espèce — utilisé pour la
    sélection manuelle (cocher précisément lesquels relâcher)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, pokemon_nom, pc, shiny,
               ROW_NUMBER() OVER (PARTITION BY pokemon_nom ORDER BY pc DESC, id ASC) AS rang
        FROM captures
        WHERE user_id = ?
        """,
        (user_id,),
    )
    resultats = [row for row in cur.fetchall() if row["rang"] > 1]
    conn.close()
    return resultats


def obtenir_toutes_captures_detaillees(user_id: int):
    """Retourne TOUS les exemplaires de la collection du joueur (id, pokemon_nom, pc, shiny,
    rang) triés par nom puis par PC décroissant. Rang = 1 signifie que c'est le seul/meilleur
    exemplaire de son espèce — utile pour afficher un avertissement si l'utilisateur
    tente de relâcher le dernier représentant d'une espèce (perte de l'entrée Pokédex)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, pokemon_nom, pc, shiny,
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


def relacher_tous_doublons(user_id: int) -> dict:
    """Relâche automatiquement TOUS les doublons de toutes les espèces d'un coup,
    en gardant systématiquement le meilleur PC de chaque espèce.
    Retourne {pokemon_nom: quantite_relachee} pour les espèces concernées."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, pokemon_nom,
               ROW_NUMBER() OVER (PARTITION BY pokemon_nom ORDER BY pc DESC, id ASC) AS rang
        FROM captures
        WHERE user_id = ?
        """,
        (user_id,),
    )
    a_supprimer = [row for row in cur.fetchall() if row["rang"] > 1]

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
    conn = get_connexion()
    cur = conn.cursor()
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


def initialiser_equipe_combat_pvp(combat_id: int, user_id: int, equipe: list):
    """Enregistre l'équipe d'un joueur pour ce combat. `equipe` est une liste de dicts
    {nom, pv, attaque, defense, attaque_spe, defense_spe, vitesse, niveau} — les stats
    complètes, déjà calculées une fois (IV + niveau) pour ne plus être re-dérivées à
    chaque tour."""
    conn = get_connexion()
    cur = conn.cursor()
    for i, mon in enumerate(equipe):
        cur.execute(
            """
            INSERT INTO combat_equipe
                (combat_id, user_id, pokemon_nom, pv_max, pv_actuels, position, atq, defe, atq_spe, def_spe, vit, niveau)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                combat_id, user_id, mon["nom"], mon["pv"], mon["pv"], i,
                mon["attaque"], mon["defense"], mon["attaque_spe"], mon["defense_spe"], mon["vitesse"],
                mon.get("niveau", 50),
            ),
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


def terminer_combat_pvp(combat_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET actif = 0 WHERE id = ?", (combat_id,))
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
    """Retourne {'atk': stage, 'def': stage, 'vit': stage} (0 partout si jamais boosté)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT stage_atk, stage_def, stage_vit FROM combat_boosts WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"atk": 0, "def": 0, "vit": 0}
    return {"atk": row["stage_atk"], "def": row["stage_def"], "vit": row["stage_vit"]}


def modifier_boost(combat_id: int, user_id: int, pokemon_nom: str, stat: str, delta: int) -> int:
    """Applique un delta de stage à une stat (atk/def/vit), borné entre -6 et +6.
    Retourne le nouveau stage."""
    boosts = obtenir_boosts(combat_id, user_id, pokemon_nom)
    nouveau = max(-6, min(6, boosts[stat] + delta))
    boosts[stat] = nouveau

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_boosts (combat_id, user_id, pokemon_nom, stage_atk, stage_def, stage_vit)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(combat_id, user_id, pokemon_nom) DO UPDATE SET
            stage_atk = excluded.stage_atk,
            stage_def = excluded.stage_def,
            stage_vit = excluded.stage_vit
        """,
        (combat_id, user_id, pokemon_nom, boosts["atk"], boosts["def"], boosts["vit"]),
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


# --- Charge / recharge (attaques à deux tours type Lance-Soleil, Ultimaton) ---

def obtenir_charge(combat_id: int, user_id: int, pokemon_nom: str) -> dict:
    """Retourne {'attaque_en_charge': str|None, 'doit_recharger': bool}."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT attaque_en_charge, doit_recharger FROM combat_charge "
        "WHERE combat_id = ? AND user_id = ? AND pokemon_nom = ?",
        (combat_id, user_id, pokemon_nom),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"attaque_en_charge": None, "doit_recharger": False}
    return {"attaque_en_charge": row["attaque_en_charge"], "doit_recharger": bool(row["doit_recharger"])}


def definir_charge(combat_id: int, user_id: int, pokemon_nom: str, attaque_en_charge: str | None, doit_recharger: bool):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_charge (combat_id, user_id, pokemon_nom, attaque_en_charge, doit_recharger)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(combat_id, user_id, pokemon_nom) DO UPDATE SET
            attaque_en_charge = excluded.attaque_en_charge, doit_recharger = excluded.doit_recharger
        """,
        (combat_id, user_id, pokemon_nom, attaque_en_charge, int(doit_recharger)),
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


# --- Statuts de combat (brûlure, poison, paralysie, sommeil, gel, confusion) ---

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


def definir_statut(combat_id: int, user_id: int, pokemon_nom: str, statut: str, compteur: int = 0) -> bool:
    """Applique une altération de statut, seulement si le Pokémon n'en a pas déjà une
    (un seul statut à la fois, comme dans les vrais jeux). Retourne True si appliqué."""
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
    base = row["date_expiration"] if row and row["date_expiration"] > maintenant else maintenant
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
    if row and row["date_expiration"] > int(time.time()):
        return row["date_expiration"]
    return None


def obtenir_tous_boosts_actifs(user_id: int) -> dict:
    """Retourne {type_boost: date_expiration} pour tous les boosts encore actifs de ce joueur."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT type_boost, date_expiration FROM boosts_actifs WHERE user_id = ?", (user_id,))
    maintenant = int(time.time())
    resultat = {row["type_boost"]: row["date_expiration"] for row in cur.fetchall() if row["date_expiration"] > maintenant}
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

    if obtenir_boost_actif(user_id, type_boost) is not None:
        multiplicateur *= config.MULTIPLICATEURS_BOOST.get(type_boost, 1.0)

    if type_boost in config.MULTIPLICATEUR_BOOSTER_SERVEUR and est_booster_serveur(user_id):
        multiplicateur *= config.MULTIPLICATEUR_BOOSTER_SERVEUR[type_boost]

    return multiplicateur


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


def consommer_pp(combat_id: int, user_id: int, pokemon_nom: str, attaque_nom: str, pp_max: int) -> int:
    """Consomme 1 PP (initialise d'abord si jamais utilisée). Retourne le PP restant
    après consommation (jamais négatif)."""
    pp_actuel = obtenir_pp(combat_id, user_id, pokemon_nom, attaque_nom, pp_max)
    nouveau_pp = max(0, pp_actuel - 1)
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
    sinon config.PVP_MULTIPLICATEUR_REPETITION (fortement réduit, contre la collusion)."""
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
    multiplicateur = 1.0 if compteur_avant == 0 else config.PVP_MULTIPLICATEUR_REPETITION

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
    return multiplicateur


def enregistrer_victoire_dresseur_repetition(user_id: int) -> float:
    """Enregistre une victoire PvE contre dresseur pour la journée en cours (TOUS
    archétypes confondus), et retourne le multiplicateur à appliquer sur la récompense
    ÉCONOMIQUE (PD + XP) de CETTE victoire — dégression progressive au fil des victoires
    du jour, voir config.DRESSEUR_MULTIPLICATEURS_REPETITION_JOUR."""
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

    paliers = config.DRESSEUR_MULTIPLICATEURS_REPETITION_JOUR
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
