"""maitre_service.py — Le Maître des Types sur le site : boutique de CT, objets tenus,
sélection d'un Pokémon pour gérer ses attaques. Mêmes règles que maitre_types.py (Discord)."""

import capacites as capacites_module
import database
import equipe_combat
import formes_objets as formes_objets_module
import mega_evolutions as mega_evolutions_module
from combat_service import ErreurCombatWeb
from pokemon_data import ATTAQUES, obtenir_attaque, obtenir_pokemon_par_nom, prix_ct, toutes_attaques_utilisables

PAR_PAGE = 24


def _infos_objets() -> dict:
    return {
        **{c: {"nom": i["nom"], "description": i["description"]} for c, i in capacites_module.OBJETS_TENUS.items()},
        **{c: {"nom": i["objet_nom"], "description": f"Transforme {i['espece']} en {i['forme_nom']} tant qu'il le tient."}
           for c, i in formes_objets_module.FORMES_OBJETS.items()},
        **{c: {"nom": i["objet_nom"], "description": f"Permet de Méga-Évoluer {i['espece']} en combat (une fois par combat)."}
           for c, i in mega_evolutions_module.MEGA_EVOLUTIONS.items()},
    }


def pokemon(user_id: int, recherche: str = "") -> dict:
    """Espèces possédées (avec niveau et objet tenu) pour choisir à qui parler."""
    stats = equipe_combat._stats_par_espece(user_id)
    terme = recherche.strip().lower()
    infos = _infos_objets()
    res = []
    for nom in sorted(stats):
        if terme and terme not in nom.lower():
            continue
        p = obtenir_pokemon_par_nom(nom) or {}
        niveau, _ = database.obtenir_niveau_pokemon(user_id, nom)
        tenu = database.obtenir_objet_tenu_reel(user_id, nom)
        res.append({"nom": nom, "niveau": niveau, "types": p.get("types", []),
                    "tenu": {"cle": tenu, "nom": (infos.get(tenu) or {}).get("nom", tenu)} if tenu else None})
    return {"pokemon": res[:60], "total": len(res)}


def boutique_ct(user_id: int, type_: str = "tous", categorie: str = "tous", q: str = "", page: int = 0) -> dict:
    possedees = database.obtenir_ct_possedees(user_id)
    terme = q.strip().lower()
    liste = []
    for nom in toutes_attaques_utilisables():
        a = obtenir_attaque(nom)
        if type_ != "tous" and (a.get("type") or "").lower() != type_.lower():
            continue
        if categorie != "tous" and a.get("classe") != categorie:
            continue
        if terme and terme not in nom.lower():
            continue
        liste.append((nom, a))
    types = sorted({(ATTAQUES[n].get("type") or "").lower() for n in toutes_attaques_utilisables() if ATTAQUES[n].get("type")})
    pages = max(1, -(-len(liste) // PAR_PAGE))
    page = max(0, min(page, pages - 1))
    return {
        "types": types, "page": page, "pages": pages, "total": len(liste),
        "poke_dollars": database.obtenir_poke_dollars(user_id),
        "attaques": [{"nom": n, "type": a.get("type"), "puissance": a.get("puissance"), "precision": a.get("precision"),
                      "categorie": a.get("classe"), "prix": prix_ct(n), "possedee": n in possedees}
                     for n, a in liste[page * PAR_PAGE:(page + 1) * PAR_PAGE]],
    }


def _verifier(user_id: int, nom: str):
    if nom not in equipe_combat._stats_par_espece(user_id):
        raise ErreurCombatWeb("Tu ne possèdes pas ce Pokémon.")
    if database.combat_en_cours_pour_joueur(user_id):
        raise ErreurCombatWeb("Impossible de changer un objet pendant un combat.")


def objets_pokemon(user_id: int, nom: str) -> dict:
    if nom not in equipe_combat._stats_par_espece(user_id):
        raise ErreurCombatWeb("Tu ne possèdes pas ce Pokémon.")
    infos = _infos_objets()
    inv = database.obtenir_inventaire_balls(user_id)
    tenu = database.obtenir_objet_tenu_reel(user_id, nom)
    return {
        "nom": nom,
        "tenu": {"cle": tenu, **(infos.get(tenu) or {"nom": tenu, "description": ""})} if tenu else None,
        "sac": [{"cle": c, "nom": i["nom"], "description": i["description"], "quantite": inv[c]}
                for c, i in infos.items() if inv.get(c, 0) > 0],
    }


def equiper_objet(user_id: int, nom: str, cle: str) -> dict:
    _verifier(user_id, nom)
    if cle not in _infos_objets():
        raise ErreurCombatWeb("Objet inconnu.")
    ancien = database.obtenir_objet_tenu_reel(user_id, nom)
    if ancien == cle:
        raise ErreurCombatWeb(f"{nom} tient déjà cet objet.")
    if not database.retirer_ball(user_id, cle):
        raise ErreurCombatWeb("Tu n'as plus cet objet.")
    if ancien:
        database.ajouter_balls(user_id, ancien, 1)
    database.definir_objet_tenu_reel(user_id, nom, cle)
    return objets_pokemon(user_id, nom)


def retirer_objet(user_id: int, nom: str) -> dict:
    _verifier(user_id, nom)
    ancien = database.obtenir_objet_tenu_reel(user_id, nom)
    if ancien is None:
        raise ErreurCombatWeb(f"{nom} ne tient aucun objet.")
    database.definir_objet_tenu_reel(user_id, nom, None)
    database.ajouter_balls(user_id, ancien, 1)
    return objets_pokemon(user_id, nom)
