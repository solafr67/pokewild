"""Connexion quotidienne : série de jours consécutifs, récompense qui grandit de façon
exponentielle (plafonnée) au fil de la série. Voir /recompense-quotidienne
(cogs/connexion_quotidienne.py).
"""

import time

import database
import leveling
from pokemon_data import EMOJI_POKEDOLLAR

BASE_DOLLARS = 40
RATIO_DOLLARS = 1.13
BASE_XP = 15
RATIO_XP = 1.11
PLAFOND_SERIE = 30  # au-delà, la récompense n'augmente plus (celle du jour 30 pour toujours)

# Objets quotidiens de base (balls + potions), en plus des PD/XP — croissent doucement
# avec la série puis plafonnent, pour rester utiles sans devenir un raz-de-marée d'objets.
def _balls_du_jour(streak: int) -> int:
    return min(1 + streak // 3, 5)


def _potions_du_jour(streak: int) -> int:
    return min(streak // 5, 3)


# Bonus d'objet PONCTUEL à certains paliers de série — en plus des balls/potions
# quotidiennes ci-dessus, pour marquer les paliers importants d'un vrai petit "coup de
# pouce" (au-delà de PLAFOND_SERIE, un Cristal de Mutation tous les 7 jours, objectif
# à très long terme même une fois le plafond de PD/XP atteint).
PALIERS_OBJETS = {
    7: ("superball", 2),
    14: ("superball", 3),
    21: ("hyperball", 1),
    28: ("hyperball", 2),
}
NOM_OBJETS_PALIERS = {
    "pokeball": "Poké Ball", "potion": "Potion",
    "superball": "Super Ball", "hyperball": "Hyper Ball", "cristal_mutation": "Cristal de Mutation",
}


def jour_actuel() -> int:
    """Découpage en jours UTC, même logique que _periode_id pour les quêtes journalières
    — un jour change à 00h UTC pour tout le monde, pas de fenêtre glissante de 24h."""
    return int(time.time()) // 86400


def calculer_recompense(streak: int) -> dict:
    """Calcule la récompense pour CE palier de série — fonction pure, testable sans DB.
    Retourne {dollars, xp, objets: [(cle, quantite), ...]} — objets contient TOUJOURS les
    balls/potions quotidiennes (si > 0), plus l'objet de palier ponctuel s'il y a lieu."""
    palier = min(streak, PLAFOND_SERIE)
    dollars = round(BASE_DOLLARS * RATIO_DOLLARS ** (palier - 1))
    xp = round(BASE_XP * RATIO_XP ** (palier - 1))

    objets = []
    nb_balls = _balls_du_jour(streak)
    if nb_balls > 0:
        objets.append(("pokeball", nb_balls))
    nb_potions = _potions_du_jour(streak)
    if nb_potions > 0:
        objets.append(("potion", nb_potions))

    if streak in PALIERS_OBJETS:
        objets.append(PALIERS_OBJETS[streak])
    elif streak > PLAFOND_SERIE and streak % 7 == 0:
        objets.append(("cristal_mutation", 1))

    return {"dollars": dollars, "xp": xp, "objets": objets}


def reclamer(user_id: int) -> dict:
    """Réclame la récompense du jour pour ce joueur. Retourne :
    - {"deja_reclame": True, "streak": ..., "temps_avant_prochain": ...} si déjà fait aujourd'hui
    - {"deja_reclame": False, "streak": ..., "streak_precedente": ..., "recompense": {...}} sinon
    Applique réellement la récompense (PD/XP/objet) avant de retourner, dans les DEUX cas
    où deja_reclame=False — l'appelant n'a rien d'autre à faire que construire l'affichage."""
    statut = database.obtenir_statut_connexion(user_id)
    jour = jour_actuel()
    ancien_streak = statut["streak"]
    dernier_jour = statut["dernier_jour"]

    if dernier_jour == jour:
        secondes_avant_minuit_utc = (jour + 1) * 86400 - int(time.time())
        return {
            "deja_reclame": True,
            "streak": ancien_streak,
            "temps_avant_prochain": secondes_avant_minuit_utc,
        }

    if dernier_jour == jour - 1:
        nouveau_streak = ancien_streak + 1  # jour consécutif
    else:
        nouveau_streak = 1  # premier jour, ou un jour a été sauté (streak brisée)

    recompense = calculer_recompense(nouveau_streak)
    database.ajouter_poke_dollars(user_id, recompense["dollars"])
    leveling.gagner_xp(user_id, recompense["xp"])
    for cle, quantite in recompense["objets"]:
        database.ajouter_balls(user_id, cle, quantite)

    database.enregistrer_connexion(user_id, nouveau_streak, jour)

    return {
        "deja_reclame": False,
        "streak": nouveau_streak,
        "streak_precedente": ancien_streak,
        "recompense": recompense,
    }


def texte_recompense(recompense: dict) -> str:
    """Formatte {dollars, xp, objets} en une ligne lisible, pour l'embed."""
    morceaux = [f"{recompense['dollars']} {EMOJI_POKEDOLLAR} Poké Dollars", f"{recompense['xp']} XP"]
    for cle, quantite in recompense["objets"]:
        morceaux.append(f"{quantite}× {NOM_OBJETS_PALIERS.get(cle, cle)}")
    return ", ".join(morceaux)
