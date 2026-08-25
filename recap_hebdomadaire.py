"""Récap personnel : progression depuis la dernière consultation de /recap. Réutilise
uniquement des stats déjà trackées à vie (stats_lifetime) — aucun nouveau hook de suivi
ajouté ailleurs dans le code, juste une différence entre deux instantanés.

Modèle volontairement "depuis ta dernière consultation" plutôt que calé sur le lundi
calendaire — évite d'avoir besoin d'une boucle de fond pour poster automatiquement,
cohérent avec le reste des commandes d'info du jeu (/passe-saison, /parrainage...),
toutes consultées à la demande plutôt que poussées par MP.
"""

import time

import database


def obtenir_recap(user_id: int) -> dict:
    """Calcule la progression depuis le dernier /recap, puis enregistre un nouveau
    snapshot pour la prochaine fois. Retourne :
    - {"premiere_fois": True} si jamais consulté avant (pas de delta à calculer)
    - {"premiere_fois": False, "jours_ecoules": ..., "victoires_pvp": ..., ...} sinon
    Le solde de Poké Dollars est une VARIATION NETTE (gains moins dépenses), pas
    seulement les gains — suivre les gains bruts demanderait d'ajouter un hook à chaque
    point de gain du jeu (raids, PvP, quêtes, exploration...), hors de portée ici."""
    ancien = database.obtenir_snapshot_recap(user_id)

    actuel = {
        "date_snapshot": int(time.time()),
        "victoires_pvp": database.obtenir_victoires_pvp(user_id),
        "victoires_pve": database.obtenir_victoires_pve(user_id),
        "captures_totales": database.obtenir_captures_totales(user_id),
        "explorations_terminees": database.obtenir_explorations_terminees(user_id),
        "shiny_totaux": database.obtenir_shiny_totaux(user_id),
        "poke_dollars": database.obtenir_poke_dollars(user_id),
    }

    database.enregistrer_snapshot_recap(user_id, actuel)

    if ancien is None:
        return {"premiere_fois": True}

    secondes_ecoulees = actuel["date_snapshot"] - ancien["date_snapshot"]
    return {
        "premiere_fois": False,
        "jours_ecoules": max(1, secondes_ecoulees // 86400),
        "victoires_pvp": actuel["victoires_pvp"] - ancien["victoires_pvp"],
        "victoires_pve": actuel["victoires_pve"] - ancien["victoires_pve"],
        "captures_totales": actuel["captures_totales"] - ancien["captures_totales"],
        "explorations_terminees": actuel["explorations_terminees"] - ancien["explorations_terminees"],
        "shiny_totaux": actuel["shiny_totaux"] - ancien["shiny_totaux"],
        "variation_poke_dollars": actuel["poke_dollars"] - ancien["poke_dollars"],
    }
