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


def mettre_a_jour_chemin_roguelike(run_id: int, chemin: list):
    """Étend (ou remplace) le chemin d'une run — utilisé quand un boss est vaincu et que
    la run continue au lieu de se terminer (voir roguelike.py::avancer_salle)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE roguelike_runs SET chemin = ? WHERE id = ?", (json.dumps(chemin), run_id))
    conn.commit()
    conn.close()


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


def definir_mutation_membre_roguelike(run_id: int, position: int, bonus_mutation: float):
    """Applique un multiplicateur de stats permanent (pour la run) à UN membre précis —
    voir roguelike.py::VueMutation (salle Autel de Mutation). Multiplicatif avec les
    stats de base, jamais cumulé plusieurs fois sur le même membre (la salle ne
    propose la mutation qu'aux membres n'en ayant pas déjà une, voir la vue)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE roguelike_equipe SET bonus_mutation = ? WHERE run_id = ? AND position = ?",
        (bonus_mutation, run_id, position),
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
    """Soigne toute l'équipe d'un pourcentage de ses PV max — ressuscite aussi un
    Pokémon K.O. (pv_actuels=0), qui remonte alors exactement à ce même pourcentage de
    vie (0 + pv_max×pourcentage = pv_max×pourcentage), cohérent avec ce qu'un Pokémon
    déjà vivant gagnerait de la même source. Utilisé par Repos, Marchand, les
    consolations de Trésor/Recrutement, et la relique Régénération."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT position, pv_max, pv_actuels FROM roguelike_equipe WHERE run_id = ?", (run_id,))
    for row in cur.fetchall():
        nouveau_pv = min(row["pv_max"], row["pv_actuels"] + round(row["pv_max"] * pourcentage))
        cur.execute(
            "UPDATE roguelike_equipe SET pv_actuels = ? WHERE run_id = ? AND position = ?",
            (nouveau_pv, run_id, row["position"]),
        )
    conn.commit()
    conn.close()


def creer_combat_roguelike(
    run_id: int, ennemi_nom: str, ennemi_niveau: int, ennemi_pv_max: int, actif_position: int,
    est_rencontre_speciale: bool = False, equipe_restante: list = None, est_dresseur: bool = False,
):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO roguelike_combat
            (run_id, ennemi_nom, ennemi_niveau, ennemi_pv_max, ennemi_pv_actuels, actif_position,
             est_rencontre_speciale, equipe_restante, est_dresseur)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            ennemi_nom = excluded.ennemi_nom, ennemi_niveau = excluded.ennemi_niveau,
            ennemi_pv_max = excluded.ennemi_pv_max, ennemi_pv_actuels = excluded.ennemi_pv_max,
            actif_position = excluded.actif_position, est_rencontre_speciale = excluded.est_rencontre_speciale,
            equipe_restante = excluded.equipe_restante, est_dresseur = excluded.est_dresseur
        """,
        (
            run_id, ennemi_nom, ennemi_niveau, ennemi_pv_max, ennemi_pv_max, actif_position,
            int(est_rencontre_speciale), json.dumps(equipe_restante or []), int(est_dresseur),
        ),
    )
    conn.commit()
    conn.close()


def avancer_ennemi_suivant_roguelike(run_id: int, ennemi_nom: str, ennemi_niveau: int, ennemi_pv_max: int, equipe_restante: list):
    """Fait passer un combat de Dresseur au Pokémon suivant de son équipe — SANS créer
    une nouvelle ligne (même combat, juste l'ennemi qui change), et sans toucher aux PV
    du joueur (contrairement à un nouveau combat classique, un dresseur enchaîne ses
    Pokémon sans laisser l'adversaire se soigner entre deux)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE roguelike_combat
        SET ennemi_nom = ?, ennemi_niveau = ?, ennemi_pv_max = ?, ennemi_pv_actuels = ?, equipe_restante = ?
        WHERE run_id = ?
        """,
        (ennemi_nom, ennemi_niveau, ennemi_pv_max, ennemi_pv_max, json.dumps(equipe_restante), run_id),
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


def reinitialiser_classement_roguelike() -> int:
    """Remet TOUT le classement Roguelike à zéro (vide roguelike_records entièrement) —
    utilisé par la commande admin /reset-classement-roguelike. Retourne le nombre de
    joueurs dont le record a été effacé. N'affecte JAMAIS la progression EN COURS d'une
    run active (table roguelike_runs, séparée) — seulement les records déjà enregistrés."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS nb FROM roguelike_records")
    nb_effaces = cur.fetchone()["nb"]
    cur.execute("DELETE FROM roguelike_records")
    conn.commit()
    conn.close()
    return nb_effaces

