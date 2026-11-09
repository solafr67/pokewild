"""saison_service.py — Passe de saison et parrainage sur le site (lecture seule).

Les points de saison sont gagnés automatiquement avec l'XP (voir saison.gagner_points) ;
le parrainage dépend des invitations Discord, il est donc seulement affiché ici.
"""

import config
import database
import saison
from quetes_service import _nom_objet


def etat(user_id: int) -> dict:
    s = saison.obtenir_statut(user_id)
    paliers = []
    for n in range(1, config.SAISON_NB_PALIERS + 1):
        r = saison.RECOMPENSES_PAR_PALIER.get(n, {"dollars": 0, "objets": []})
        paliers.append({
            "palier": n,
            "atteint": n <= s["palier"],
            "dollars": r["dollars"],
            "objets": [{"cle": c, "nom": _nom_objet(c), "quantite": q} for c, q in r["objets"]],
        })
    total = database.compter_parrainages(user_id)
    p = config.PARRAINAGE_PALIER
    return {
        "saison": s,
        "paliers": paliers,
        "parrainage": {
            "confirmes": total,
            "palier": p,
            "avant_prochain": p - (total % p),
            "delai_jours": config.PARRAINAGE_DELAI_JOURS,
            "recompense_dollars": config.PARRAINAGE_RECOMPENSE_DOLLARS,
            "recompense_objets": [{"cle": c, "nom": _nom_objet(c), "quantite": q} for c, q in config.PARRAINAGE_RECOMPENSE_BALLS],
        },
    }
