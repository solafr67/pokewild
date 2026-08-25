"""Sous-module database — domaine Contrats (missions à la demande d'un PNJ, pool
personnel de 3 tirées au sort chaque jour). Voir contrats_catalogue.py (racine, pure
donnée) pour le catalogue complet.

Dépendances (vérifiées) : get_connexion, ajouter_poke_dollars, ajouter_balls (cœur,
restent dans __init__.py) — import du catalogue fait EN LOCAL dans chaque fonction (pas
en tête de fichier), même pattern déjà établi pour quetes.py dans
quetes_evenements.py::incrementer_progression_quete — sûr car ce sous-module n'est
chargé qu'après __init__.py entièrement exécuté.
"""

import random
import time

from . import ajouter_balls, ajouter_poke_dollars, get_connexion

NB_CONTRATS_ACTIFS = 3


def _jour_actuel() -> int:
    return int(time.time()) // 86400


def _tirer_contrats(catalogue: list, n: int) -> list:
    """Tirage pondéré SANS remise (n contrats distincts) — random.choices ne garantit
    pas l'absence de doublons, d'où cette implémentation manuelle."""
    restants = list(catalogue)
    tires = []
    for _ in range(min(n, len(restants))):
        poids = [c["poids"] for c in restants]
        choisi = random.choices(restants, weights=poids, k=1)[0]
        tires.append(choisi)
        restants.remove(choisi)
    return tires


def obtenir_contrats_du_jour(user_id: int) -> list:
    """Retourne les 3 contrats actifs du joueur pour AUJOURD'HUI — en tire un nouveau
    pool (et l'enregistre) si aucun n'existe encore pour ce jour précis. Chaque entrée :
    {contrat_id, position, compteur, complete, ...le reste du catalogue fusionné}."""
    from contrats_catalogue import CONTRATS_PAR_ID, CONTRATS_CATALOGUE

    jour = _jour_actuel()
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT position, contrat_id, compteur, complete FROM contrats_actifs WHERE user_id = ? AND jour = ? ORDER BY position",
        (user_id, jour),
    )
    lignes = cur.fetchall()

    if not lignes:
        tires = _tirer_contrats(CONTRATS_CATALOGUE, NB_CONTRATS_ACTIFS)
        for position, contrat in enumerate(tires):
            cur.execute(
                "INSERT INTO contrats_actifs (user_id, jour, position, contrat_id, compteur, complete) VALUES (?, ?, ?, ?, 0, 0)",
                (user_id, jour, position, contrat["id"]),
            )
        conn.commit()
        cur.execute(
            "SELECT position, contrat_id, compteur, complete FROM contrats_actifs WHERE user_id = ? AND jour = ? ORDER BY position",
            (user_id, jour),
        )
        lignes = cur.fetchall()

    conn.close()

    resultats = []
    for ligne in lignes:
        infos = dict(CONTRATS_PAR_ID[ligne["contrat_id"]])
        infos["position"] = ligne["position"]
        infos["compteur"] = ligne["compteur"]
        infos["complete"] = bool(ligne["complete"])
        resultats.append(infos)
    return resultats


def incrementer_progression_contrats(user_id: int, evenement: str, contexte: dict = None, montant: int = 1) -> list:
    """Fait progresser les contrats actifs du joueur correspondant à cet événement —
    même signature que incrementer_progression_quete, appelée juste après elle (voir
    quetes_evenements.py). Applique la récompense IMMÉDIATEMENT dès qu'un contrat est
    complété (pas de bouton "réclamer" séparé). Retourne la liste des contrats tout
    juste complétés par CET appel (pour notification immédiate).

    Écrit et FERME sa connexion avant d'appliquer la moindre récompense — les fonctions
    de récompense (ajouter_poke_dollars, ajouter_balls, leveling.gagner_xp) ouvrent
    chacune leur propre connexion, et SQLite refuse une deuxième écriture concurrente
    tant qu'une première n'est pas commit/fermée ('database is locked')."""
    from contrats_catalogue import CONTRATS_PAR_ID

    contexte = contexte or {}
    jour = _jour_actuel()
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT position, contrat_id, compteur, complete FROM contrats_actifs WHERE user_id = ? AND jour = ?",
        (user_id, jour),
    )
    lignes = cur.fetchall()

    tout_juste_completes = []
    for ligne in lignes:
        if ligne["complete"]:
            continue
        contrat = CONTRATS_PAR_ID[ligne["contrat_id"]]
        if contrat["evenement"] != evenement:
            continue

        filtre = contrat.get("filtre")
        if filtre:
            correspond = True
            for cle, attendu in filtre.items():
                valeur_reelle = contexte.get(cle)
                if isinstance(attendu, list):
                    if valeur_reelle not in attendu:
                        correspond = False
                        break
                elif valeur_reelle != attendu:
                    correspond = False
                    break
            if not correspond:
                continue

        nouveau_compteur = min(contrat["cible"], ligne["compteur"] + montant)
        cur.execute(
            "UPDATE contrats_actifs SET compteur = ? WHERE user_id = ? AND jour = ? AND position = ?",
            (nouveau_compteur, user_id, jour, ligne["position"]),
        )

        if ligne["compteur"] < contrat["cible"] <= nouveau_compteur:
            cur.execute(
                "UPDATE contrats_actifs SET complete = 1 WHERE user_id = ? AND jour = ? AND position = ?",
                (user_id, jour, ligne["position"]),
            )
            tout_juste_completes.append(contrat)

    conn.commit()
    conn.close()

    # Récompenses appliquées APRÈS avoir fermé notre connexion (voir docstring) —
    # chacune de ces fonctions ouvre et referme la sienne, aucun conflit possible ici.
    resultats = []
    for contrat in tout_juste_completes:
        recompense = contrat["recompense"]
        ajouter_poke_dollars(user_id, recompense["dollars"])
        if recompense.get("xp"):
            import leveling
            leveling.gagner_xp(user_id, recompense["xp"])
        if recompense.get("objet"):
            cle_objet, quantite = recompense["objet"]
            ajouter_balls(user_id, cle_objet, quantite)
        resultats.append({"id": contrat["id"], "nom": contrat["nom"], "emoji": contrat["emoji"], "recompense": recompense})

    return resultats
