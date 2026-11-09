"""quetes_service.py — Quêtes, contrats, quête principale, accomplissements et récompense
quotidienne sur le site (sans Discord). Mêmes règles et mêmes données que quetes_ui.py /
connexion_quotidienne.py : la progression est partagée avec le bot.
"""

import random
import time

import config
import connexion_quotidienne as cq
import database
import leveling
import quetes as quetes_module
from combat_service import ErreurCombatWeb
from pokemon_data import NOM_OBJETS_DIVERS, NOM_SOIN_AFFICHAGE, obtenir_pokemon_par_nom

OBJETS_BONUS_JOUR = ["hyperball", "totalsoin"]


def _nom_objet(cle: str) -> str:
    return NOM_SOIN_AFFICHAGE.get(cle) or NOM_OBJETS_DIVERS.get(cle) or cq.NOM_OBJETS_PALIERS.get(cle) or cle.replace("_", " ").title()


def _fiche_quete(user_id: int, quete: dict, type_quete: str) -> dict:
    compteur, reclamee = database.obtenir_progression_quete(user_id, quete["id"], type_quete)
    return {
        "id": quete["id"], "nom": quete["nom"], "emoji": quete["emoji"], "type": type_quete,
        "compteur": compteur, "cible": quete["cible"], "complete": compteur >= quete["cible"], "reclamee": bool(reclamee),
    }


def _valeurs_accomplissements(user_id: int) -> dict:
    captures = database.obtenir_pokedex_joueur(user_id)
    niveau, _, _ = leveling.progression_niveau(database.obtenir_xp(user_id))
    return {
        "shiny": sum(r["quantite"] for r in captures if r["shiny"]),
        "legendaire": sum(1 for r in captures if (obtenir_pokemon_par_nom(r["pokemon_nom"]) or {}).get("rarete") == "legendaire"),
        "pvp": database.obtenir_victoires_pvp(user_id),
        "niveau": niveau,
        "pokedex": len({r["pokemon_nom"] for r in captures}),
    }


def _accomplissements(user_id: int) -> dict:
    valeurs = _valeurs_accomplissements(user_id)
    actif = database.obtenir_titre_actif(user_id)
    cats = []
    for cat, info in quetes_module.ACCOMPLISSEMENTS.items():
        palier = quetes_module.palier_atteint(cat, valeurs[cat])
        paliers = info["paliers"]
        cats.append({
            "cle": cat, "nom": info["nom_categorie"], "emoji": info["emoji"], "valeur": valeurs[cat],
            "palier": palier, "titre": quetes_module.titre_complet(cat, palier),
            "prochain": paliers[palier] if palier < len(paliers) else None, "maximum": paliers[-1],
            "actif": cat == actif and palier > 0,
        })
    return {"categories": cats,
            "titre_actif": quetes_module.titre_complet(actif, quetes_module.palier_atteint(actif, valeurs[actif])) if actif in valeurs else None}


def _contrats(user_id: int) -> list:
    out = []
    for c in database.obtenir_contrats_du_jour(user_id):
        rec = c["recompense"]
        objet = None
        if rec.get("objet"):
            cle, q = rec["objet"]
            objet = f"{q}× {_nom_objet(cle)}"
        out.append({"nom": c["nom"], "emoji": c["emoji"], "compteur": c["compteur"], "cible": c["cible"],
                    "complete": c["complete"], "dollars": rec["dollars"], "xp": rec["xp"], "objet": objet})
    return out


def _principale(user_id: int) -> dict:
    prog = database.obtenir_progression_quete_principale(user_id)
    chapitres = config.QUETE_PRINCIPALE_CHAPITRES
    if prog["termine"]:
        return {"termine": True, "total": len(chapitres)}
    ch = chapitres[prog["chapitre"] - 1]
    rec = ch["recompense"]
    return {
        "termine": False, "chapitre": prog["chapitre"], "total": len(chapitres), "titre": ch["titre"], "intro": ch["intro"],
        "compteur": prog["compteur"], "cible": ch["cible"],
        "recompense": {"dollars": rec["dollars"], "xp": rec["xp"], "objet": _nom_objet(rec["objet"]) if rec.get("objet") else None},
    }


def etat_connexion(user_id: int) -> dict:
    st = database.obtenir_statut_connexion(user_id)
    jour = cq.jour_actuel()
    deja = st["dernier_jour"] == jour
    streak_en_cours = st["streak"] if st["dernier_jour"] in (jour, jour - 1) else 0
    prochain = streak_en_cours + (0 if deja else 1)
    return {
        "deja_reclame": deja, "streak": streak_en_cours,
        "secondes_avant_prochain": (jour + 1) * 86400 - int(time.time()) if deja else 0,
        "recompense": _rec_json(cq.calculer_recompense(max(1, prochain))), "jour_recompense": max(1, prochain),
    }


def _rec_json(rec: dict) -> dict:
    return {"dollars": rec["dollars"], "xp": rec["xp"], "objets": [f"{q}× {_nom_objet(c)}" for c, q in rec["objets"]]}


def etat(user_id: int) -> dict:
    jour = [_fiche_quete(user_id, q, "jour") for q in quetes_module.QUETES_JOUR]
    semaine = [_fiche_quete(user_id, q, "semaine") for q in quetes_module.QUETES_SEMAINE]
    return {
        "jour": jour, "semaine": semaine,
        "pretes": sum(1 for q in jour + semaine if q["complete"] and not q["reclamee"]),
        "contrats": _contrats(user_id), "principale": _principale(user_id),
        "accomplissements": _accomplissements(user_id), "connexion": etat_connexion(user_id),
    }


def reclamer_tout(user_id: int) -> dict:
    dollars_tot = xp_tot = cristaux = 0
    bonus, noms = {}, []
    for type_quete, catalogue, base, chance in (
        ("jour", quetes_module.QUETES_JOUR, config.QUETE_RECOMPENSE_JOUR, config.QUETE_CHANCE_OBJET_BONUS_JOUR),
        ("semaine", quetes_module.QUETES_SEMAINE, config.QUETE_RECOMPENSE_SEMAINE, config.QUETE_CHANCE_CRISTAL_SEMAINE),
    ):
        for q in catalogue:
            if not database.reclamer_quete(user_id, q["id"], type_quete):
                continue
            dollars = round(base["dollars"] * database.multiplicateur_boost(user_id, "argent"))
            xp = base["xp"]
            database.ajouter_poke_dollars(user_id, dollars)
            leveling.gagner_xp(user_id, xp)
            dollars_tot += dollars
            xp_tot += round(xp * database.multiplicateur_boost(user_id, "xp"))
            if type_quete == "jour" and random.random() < chance:
                o = random.choice(OBJETS_BONUS_JOUR)
                database.ajouter_balls(user_id, o, 1)
                bonus[o] = bonus.get(o, 0) + 1
            elif type_quete == "semaine" and random.random() < chance:
                database.ajouter_balls(user_id, "cristal_mutation", 1)
                cristaux += 1
            noms.append(f"{q['emoji']} {q['nom']}")
    if not noms:
        raise ErreurCombatWeb("Aucune quête prête à être réclamée pour le moment.")
    return {"quetes": noms, "dollars": dollars_tot, "xp": xp_tot, "cristaux": cristaux,
            "objets": [f"{n}× {_nom_objet(o)}" for o, n in bonus.items()]}


def choisir_titre(user_id: int, categorie: str) -> dict:
    if categorie not in quetes_module.ACCOMPLISSEMENTS:
        raise ErreurCombatWeb("Titre inconnu.")
    if quetes_module.palier_atteint(categorie, _valeurs_accomplissements(user_id)[categorie]) == 0:
        raise ErreurCombatWeb("Tu n'as pas encore débloqué ce titre.")
    database.definir_titre_actif(user_id, categorie)
    return _accomplissements(user_id)


def reclamer_connexion(user_id: int) -> dict:
    res = cq.reclamer(user_id)
    if res["deja_reclame"]:
        raise ErreurCombatWeb("Tu as déjà récupéré ta récompense du jour.")
    return {
        "streak": res["streak"], "serie_cassee": res["streak_precedente"] > 0 and res["streak_precedente"] != res["streak"] - 1,
        "streak_precedente": res["streak_precedente"], "recompense": _rec_json(res["recompense"]),
    }
