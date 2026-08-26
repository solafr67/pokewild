"""Sous-module database — domaine quêtes + événements serveur (défi collectif,
chasse aux shiny, capture rareté, quêtes journalières/hebdomadaires).

Dépendances (vérifiées exhaustivement avant extraction) :
- get_connexion : cœur, reste dans database/__init__.py.
- avancer_quete_principale : cœur, reste dans __init__.py (déjà une dépendance
  établie d'arene_repaires.py, ne pas déplacer pour ne pas casser ce fichier déjà
  livré).
- ajouter_contribution_clan : PAS dans le cœur, définie dans database/clan.py
  (domaine déjà extrait) — import explicite depuis .clan, pas depuis le cœur.
  incrementer_progression_quete alimente donc la contribution clan directement.

obtenir_progression_quete_principale/avancer_quete_principale (quête PRINCIPALE,
différente des quêtes journalières/hebdo ci-dessous) restent volontairement dans
__init__.py pour la même raison de dépendance déjà établie."""

import time

from . import avancer_quete_principale, get_connexion
from .clan import ajouter_contribution_clan
from .contrats import incrementer_progression_contrats


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


# --- Events serveur : Capture Classée (/event) — points selon la rareté, spawn
# classique uniquement (VIP exclu), doublons comptés comme les nouvelles captures ---

BAREME_POINTS_CAPTURE_RARETE = {
    "commun": 1,
    "peu_commun": 3,
    "rare": 6,
    "hyper_rare": 10,
    "legendaire": 15,
}
BONUS_POINTS_SHINY_CAPTURE_RARETE = 25


def calculer_points_event_capture_rarete(rarete: str, shiny: bool) -> int:
    """Barème pour UNE capture — factorisé ici pour que views.py (au moment même de la
    capture) et le classement utilisent exactement le même calcul, sans dupliquer le
    barème à deux endroits."""
    points = BAREME_POINTS_CAPTURE_RARETE.get(rarete, 0)
    if shiny:
        points += BONUS_POINTS_SHINY_CAPTURE_RARETE
    return points


def demarrer_event_capture_rarete(duree_secondes: int, channel_annonce_id: int | None = None) -> int:
    """Démarre un nouvel event Capture Classée, désactivant silencieusement tout event du
    même type encore actif (un seul à la fois). Retourne l'id du nouvel event."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE event_capture_rarete SET actif = 0 WHERE actif = 1")
    maintenant = int(time.time())
    cur.execute(
        """
        INSERT INTO event_capture_rarete (date_debut, date_fin, actif, channel_annonce_id, annoncee)
        VALUES (?, ?, 1, ?, 0)
        """,
        (maintenant, maintenant + duree_secondes, channel_annonce_id),
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()
    return event_id


def obtenir_event_capture_rarete_actif() -> dict | None:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM event_capture_rarete WHERE actif = 1 LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def definir_message_event_capture_rarete(event_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE event_capture_rarete SET message_id = ? WHERE id = ?", (message_id, event_id))
    conn.commit()
    conn.close()


def obtenir_events_capture_rarete_a_terminer() -> list:
    """Events actifs dont la date de fin est dépassée — pour la boucle de vérification."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM event_capture_rarete WHERE actif = 1 AND date_fin <= ?", (int(time.time()),))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ajouter_points_event_capture_rarete(event_id: int, user_id: int, points: int):
    """Crédite des points de façon PERMANENTE et ADDITIVE au moment de la capture — voir
    views.py, appelé juste après database.ajouter_capture() pour une capture 'classique'
    pendant un event actif. Contrairement à l'ancien calcul en direct (recompté depuis la
    table captures à chaque affichage), ces points ne peuvent plus jamais être perdus ni
    transférés après coup : relâcher un doublon, l'échanger ou le vendre au marketplace
    n'affecte plus le score déjà acquis — c'était le bug d'origine (des joueurs voyaient
    leurs points BAISSER après avoir relâché des doublons capturés pendant l'event,
    puisque le score recalculé ne comptait plus que les captures encore présentes dans
    la table)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO event_capture_rarete_points (event_id, user_id, points) VALUES (?, ?, ?)
        ON CONFLICT(event_id, user_id) DO UPDATE SET points = points + excluded.points
        """,
        (event_id, user_id, points),
    )
    conn.commit()
    conn.close()


def _classement_capture_rarete_stocke(event_id: int) -> list:
    """Lit le classement depuis la table persistante (event_capture_rarete_points) —
    remplace l'ancien calcul en direct depuis la table captures, voir
    ajouter_points_event_capture_rarete pour le contexte complet du bug corrigé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, points FROM event_capture_rarete_points WHERE event_id = ? ORDER BY points DESC",
        (event_id,),
    )
    resultats = [(row["user_id"], row["points"]) for row in cur.fetchall()]
    conn.close()
    return resultats


def classement_event_capture_rarete_en_cours(event_id: int) -> list:
    """Classement LIVE d'un event encore actif — pour les mises à jour périodiques
    (toutes les 30 min) affichées dans le channel d'annonce, sans clôturer l'event."""
    return _classement_capture_rarete_stocke(event_id)


def terminer_event_capture_rarete(event_id: int) -> list:
    """Clôture l'event et retourne le classement final [(user_id, points)] trié
    décroissant."""
    classement = _classement_capture_rarete_stocke(event_id)
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE event_capture_rarete SET actif = 0, annoncee = 1 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return classement


def arreter_event_capture_rarete():
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE event_capture_rarete SET actif = 0 WHERE actif = 1")
    conn.commit()
    conn.close()

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


def _valeur_correspond_filtre(valeur_reelle, valeur_attendue) -> bool:
    """Compare une valeur de contexte à ce qu'exige un filtre — gère les deux sens :
    valeur_attendue peut être une liste de valeurs ACCEPTABLES (ex: rareté "rare ou
    mieux"), ou valeur_reelle peut elle-même être une liste (ex: "type" transmet TOUS
    les types d'un Pokémon bi-type, pas seulement le premier — sans ce 2e cas, un
    Pokémon dont le Feu est le 2e type ne comptait jamais pour un filtre {"type": "feu"})."""
    if isinstance(valeur_attendue, list):
        return valeur_reelle in valeur_attendue
    if isinstance(valeur_reelle, list):
        return valeur_attendue in valeur_reelle
    return valeur_reelle == valeur_attendue


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
    avancer_quete_principale(user_id, evenement, contexte, montant)

    # Contrats (mission du jour, pool personnel de 3, voir database/contrats.py) —
    # branchés ici pour réutiliser exactement le même événement/contexte déjà propagé
    # par tous les appelants existants (capture, combat, exploration...), sans avoir à
    # semer un nouveau point d'accroche dans chaque fichier du jeu. Le retour n'est pas
    # propagé aux appelants ici (même choix que pour la quête principale juste au-dessus)
    # — le joueur découvre la complétion via /contrats.
    incrementer_progression_contrats(user_id, evenement, contexte, montant)

    contexte = contexte or {}
    conn = get_connexion()
    cur = conn.cursor()
    tout_juste_completees = []

    for type_quete, catalogue in (("jour", quetes_module.QUETES_JOUR), ("semaine", quetes_module.QUETES_SEMAINE)):
        for quete in catalogue:
            if quete["evenement"] != evenement:
                continue
            filtre = quete.get("filtre")
            if filtre and any(not _valeur_correspond_filtre(contexte.get(cle), valeur) for cle, valeur in filtre.items()):
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
