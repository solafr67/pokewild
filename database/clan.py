"""Sous-module database — domaine clan (3 équipes fixes : affectation joueur,
contribution, objectifs hebdomadaires, historique de saison).

Dépendances (vérifiées exhaustivement avant extraction) :
- get_connexion, _assurer_joueur_existe, ajouter_poke_dollars : cœur, restent dans
  database/__init__.py.
- ajouter_contribution_clan (définie ICI) est appelée par incrementer_progression_quete
  (domaine quêtes, pas encore extrait, reste dans __init__.py) — les quêtes alimentent
  la contribution clan. Fonctionne par late binding, comme pour especes_en_exploration."""

import time

import config

from . import _assurer_joueur_existe, ajouter_poke_dollars, get_connexion


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

