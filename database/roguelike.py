"""Sous-module database — domaine roguelike (mini-jeu indépendant : runs, équipe,
combat, records). Extrait de database.py monolithique (voir database/__init__.py
pour le contexte général du découpage en package).

Domaine parfaitement isolé : aucune fonction ici n'appelle une fonction d'un
autre domaine (à part get_connexion, le helper partagé), et aucune fonction
ailleurs dans database/ n'appelle une fonction de ce fichier — vérifié par grep
exhaustif avant extraction."""

import json
import time

from . import get_connexion


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


def mettre_a_jour_niveau_membre_roguelike(
    run_id: int, position: int, niveau: int, pv_max: int, pv_actuels: int, pokemon_nom: str = None
):
    """Fait monter un membre d'équipe à un nouveau niveau (avec ses nouveaux PV max) —
    utilisé pour que l'équipe du joueur suive la même courbe de niveau que les ennemis au
    fil des salles (voir roguelike.py::avancer_salle, correctif d'un déséquilibre où
    l'équipe restait figée au niveau de départ pendant que les ennemis montaient en
    niveau à chaque salle). pv_actuels doit être calculé par l'appelant pour préserver le
    même pourcentage de vie plutôt que de soigner gratuitement à chaque montée.
    pokemon_nom (optionnel) : si fourni, change aussi l'espèce — utilisé quand la montée
    de niveau déclenche une évolution (voir pokemon_data.evoluer_si_possible)."""
    conn = get_connexion()
    cur = conn.cursor()
    if pokemon_nom is not None:
        cur.execute(
            "UPDATE roguelike_equipe SET niveau = ?, pv_max = ?, pv_actuels = ?, pokemon_nom = ? WHERE run_id = ? AND position = ?",
            (niveau, pv_max, max(0, pv_actuels), pokemon_nom, run_id, position),
        )
    else:
        cur.execute(
            "UPDATE roguelike_equipe SET niveau = ?, pv_max = ?, pv_actuels = ? WHERE run_id = ? AND position = ?",
            (niveau, pv_max, max(0, pv_actuels), run_id, position),
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

