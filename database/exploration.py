"""Sous-module database — domaine exploration + incubation (Laboratoire).

Dépendances (vérifiées exhaustivement avant extraction) :
- get_connexion, _assurer_joueur_existe : définies dans database/__init__.py (cœur),
  importées ici via le pattern relatif standard.
- especes_en_exploration (définie ICI) est appelée par obtenir_equipe_combat_disponible,
  qui reste dans __init__.py (domaine combat/équipe, pas encore extrait) — ça fonctionne
  grâce au late binding Python : le nom est résolu au moment de l'APPEL, pas de la
  définition, et le `from .exploration import *` en fin de __init__.py aura déjà
  rendu especes_en_exploration disponible dans son espace de noms à ce moment-là.

Volontairement laissées dans __init__.py (pas dans ce fichier) malgré leur lien avec
l'exploration : enregistrer_completion_exploration_repetition (mêlée à des fonctions
de dégression quotidienne arène/dresseur similaires, famille transversale) et
incrementer_explorations_terminees/classement_explorations (touchent stats_lifetime,
table du domaine cœur, aux côtés d'autres classements enrichis)."""

import time

from . import _assurer_joueur_existe, get_connexion


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


