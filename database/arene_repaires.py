"""Sous-module database — domaine arène + repaires de méchants (spawn, runs des
joueurs, badges, multiplicateur de dégression quotidienne).

Dépendances (vérifiées exhaustivement avant extraction) :
- get_connexion, avancer_quete_principale, multiplicateur_boost : cœur, restent
  dans database/__init__.py.
- obtenir_badges_repaire (définie ICI) est appelée par multiplicateur_boost
  (cœur, pas encore extrait) — fonctionne par late binding, comme especes_en_exploration
  et ajouter_contribution_clan dans les lots précédents."""

import time

import config

from . import avancer_quete_principale, get_connexion, multiplicateur_boost


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
    """Retourne True si c'est un NOUVEAU badge (première fois), False s'il l'avait déjà.
    avancer_quete_principale est appelée dans TOUS les cas (badge nouveau ou déjà
    possédé) — sinon un joueur qui a déjà tous les badges d'arène avant d'atteindre
    l'étape de quête correspondante reste bloqué indéfiniment, l'événement "badge_arene"
    ne se déclenchant plus jamais pour lui."""
    deja_possede = possede_badge_arene(user_id, type_pokemon)
    if not deja_possede:
        conn = get_connexion()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO arene_badges (user_id, type_pokemon, date_obtenu) VALUES (?, ?, ?)",
            (user_id, type_pokemon, int(time.time())),
        )
        conn.commit()
        conn.close()
    avancer_quete_principale(user_id, "badge_arene")
    return not deja_possede


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
    """Retourne True si c'est un NOUVEAU badge (première fois), False s'il l'avait déjà.
    avancer_quete_principale est appelée dans TOUS les cas — même raison que
    accorder_badge_arene ci-dessus."""
    deja_possede = possede_badge_repaire(user_id, equipe_mechante)
    if not deja_possede:
        conn = get_connexion()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO repaire_badges (user_id, equipe_mechante, date_obtenu) VALUES (?, ?, ?)",
            (user_id, equipe_mechante, int(time.time())),
        )
        conn.commit()
        conn.close()
    avancer_quete_principale(user_id, "badge_repaire")
    return not deja_possede


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

