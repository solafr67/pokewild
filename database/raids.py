"""Sous-module database — domaine raids (session de raid, participants, dégâts,
tentatives de capture, synchronisation du pool de PV pendant un raid).

Domaine isolé (vérifié par analyse exhaustive des appels avant extraction) :
aucune fonction ailleurs dans database/ n'appelle une fonction de ce fichier, et
ce fichier ne dépend que de get_connexion — même si reinitialiser_pool_raid_joueur
et joueur_dans_raid_actif touchent en SQL brut la table etat_combat_pokemon (domaine
combat) et n'étaient PAS physiquement contiguës au reste du bloc raid dans le
fichier original ; les tables restent définies de façon centrale dans __init__.py,
donc ce n'est pas un couplage de fonctions, juste un accès direct à une table."""

import time

from . import get_connexion


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


