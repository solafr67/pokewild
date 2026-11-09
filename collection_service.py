"""collection_service.py — Collection (verrous, favoris, surnoms, relâcher) et Classements
sur le site (sans Discord). Mêmes règles et mêmes fonctions de base que profil.py /
classement.py.
"""

import config
import database
from combat_service import ErreurCombatWeb
from pokemon_data import POKEDEX, cle_tri_alphabetique_fr, obtenir_pokemon_par_nom

PAR_PAGE = 40
RARETES = {"commun": "Commun", "peu_commun": "Peu commun", "rare": "Rare", "hyper_rare": "Hyper rare", "legendaire": "Légendaire"}


# ----------------------------------------------------------------------------
# Collection
# ----------------------------------------------------------------------------

def _possede(user_id: int, capture_id: int):
    conn = database.get_connexion()
    row = conn.execute("SELECT id, pokemon_nom FROM captures WHERE id = ? AND user_id = ?", (capture_id, user_id)).fetchone()
    conn.close()
    if row is None:
        raise ErreurCombatWeb("Pokémon introuvable dans ta collection.")
    return row


def collection(user_id: int, tri: str = "alphabetique", recherche: str = "", filtre: str = "tous", page: int = 0) -> dict:
    lignes = [dict(r) for r in database.obtenir_toutes_captures_detaillees(user_id)]
    total = len(lignes)
    nb_verrous = sum(1 for r in lignes if r["verrouille"])
    nb_favoris = sum(1 for r in lignes if r["favori"])
    if recherche:
        t = cle_tri_alphabetique_fr(recherche)
        lignes = [r for r in lignes if t in cle_tri_alphabetique_fr(r["pokemon_nom"]) or (r["surnom"] and t in cle_tri_alphabetique_fr(r["surnom"]))]
    if filtre == "doublons":
        lignes = [r for r in lignes if r["rang"] > 1]
    elif filtre == "verrouilles":
        lignes = [r for r in lignes if r["verrouille"]]
    elif filtre == "favoris":
        lignes = [r for r in lignes if r["favori"]]
    elif filtre == "shiny":
        lignes = [r for r in lignes if r["shiny"]]
    if tri == "pc_desc":
        lignes.sort(key=lambda r: -r["pc"])
    elif tri == "favoris_dabord":
        lignes.sort(key=lambda r: (not r["favori"], cle_tri_alphabetique_fr(r["pokemon_nom"]), -r["pc"]))
    elif tri == "verrouilles_dabord":
        lignes.sort(key=lambda r: (not r["verrouille"], cle_tri_alphabetique_fr(r["pokemon_nom"]), -r["pc"]))
    # défaut : l'ordre alphabétique de la base
    nb_pages = max(1, (len(lignes) + PAR_PAGE - 1) // PAR_PAGE)
    page = max(0, min(page, nb_pages - 1))
    sel = lignes[page * PAR_PAGE:(page + 1) * PAR_PAGE]
    return {
        "page": page, "nb_pages": nb_pages, "nb": len(lignes), "total": total, "verrous": nb_verrous, "favoris": nb_favoris,
        "captures": [
            {"id": r["id"], "nom": r["pokemon_nom"], "pc": r["pc"], "shiny": bool(r["shiny"]), "verrouille": bool(r["verrouille"]),
             "favori": bool(r["favori"]), "surnom": r["surnom"], "dernier": r["total_espece"] == 1,
             "doublon": r["rang"] > 1}
            for r in sel
        ],
    }


def basculer(user_id: int, capture_id: int, champ: str, valeur: bool) -> dict:
    _possede(user_id, capture_id)
    if champ == "verrouille":
        database.definir_verrouillage_capture(capture_id, bool(valeur))
    elif champ == "favori":
        database.definir_favori_capture(capture_id, bool(valeur))
    else:
        raise ErreurCombatWeb("Champ inconnu.")
    return {"ok": True}


def surnommer(user_id: int, capture_id: int, surnom: str) -> dict:
    _possede(user_id, capture_id)
    surnom = (surnom or "").strip()
    if len(surnom) > 32:
        raise ErreurCombatWeb("Le surnom ne peut pas dépasser 32 caractères.")
    database.definir_surnom_capture(capture_id, surnom or None)
    return {"ok": True}


def _verifier_pas_en_combat(user_id: int):
    if database.combat_en_cours_pour_joueur(user_id):
        raise ErreurCombatWeb("Impossible pendant un combat.")


def _lignes_recompense(user_id: int, resultats: dict) -> dict:
    mult = database.multiplicateur_boost(user_id, "argent")
    lignes = [{"nom": n, "quantite": q, "dollars": round(config.RECOMPENSE_RELACHER * q * mult)}
              for n, q in sorted(resultats.items(), key=lambda kv: cle_tri_alphabetique_fr(kv[0]))]
    return {"lignes": lignes, "total": sum(l["dollars"] for l in lignes), "nb": sum(l["quantite"] for l in lignes)}


def _raretes(raretes) -> set | None:
    if not raretes:
        return None
    r = set(raretes)
    if not r <= set(RARETES):
        raise ErreurCombatWeb("Rareté inconnue.")
    return r


def apercu_relacher(user_id: int, raretes=None) -> dict:
    r = _raretes(raretes)
    res = database.previsualiser_doublons_par_rarete(user_id, r) if r else database.previsualiser_doublons(user_id)
    return _lignes_recompense(user_id, res)


def relacher_doublons(user_id: int, raretes=None) -> dict:
    _verifier_pas_en_combat(user_id)
    r = _raretes(raretes)
    res = database.relacher_doublons_par_rarete(user_id, r) if r else database.relacher_tous_doublons(user_id)
    if not res:
        raise ErreurCombatWeb("Tu n'as aucun doublon à relâcher.")
    out = _lignes_recompense(user_id, res)
    database.ajouter_poke_dollars(user_id, out["total"])
    return out


def supprimer(user_id: int, ids: list) -> dict:
    _verifier_pas_en_combat(user_id)
    ids = [int(i) for i in ids]
    if not ids or len(ids) > 500:
        raise ErreurCombatWeb("Sélection invalide.")
    detail = {r["id"]: r for r in database.obtenir_toutes_captures_detaillees(user_id)}
    perdus = list(dict.fromkeys(detail[i]["pokemon_nom"] for i in ids if i in detail and detail[i]["total_espece"] == 1))
    nb = database.relacher_captures_par_id(user_id, ids)
    if nb == 0:
        raise ErreurCombatWeb("Rien n'a été supprimé.")
    dollars = round(config.RECOMPENSE_RELACHER * nb * database.multiplicateur_boost(user_id, "argent"))
    database.ajouter_poke_dollars(user_id, dollars)
    return {"nb": nb, "dollars": dollars, "perdus_pokedex": perdus}


# ----------------------------------------------------------------------------
# Classements
# ----------------------------------------------------------------------------

def _pseudos() -> dict:
    conn = database.get_connexion()
    try:
        return {r["user_id"]: r["pseudo"] for r in conn.execute("SELECT user_id, pseudo FROM web_joueurs")}
    except Exception:
        return {}
    finally:
        conn.close()


def classements(user_id: int, limite: int = 10) -> dict:
    pseudos = _pseudos()

    def nom(uid):
        return pseudos.get(uid) or f"Dresseur #{str(uid)[-4:]}"

    def liste(rows, cle_id, cle_val, fmt):
        return [{"rang": i + 1, "pseudo": nom(r[cle_id]), "moi": r[cle_id] == user_id, "valeur": fmt(r[cle_val])} for i, r in enumerate(rows)]

    total = len(POKEDEX)
    cats = [
        ("captures", "🎯", "Plus de captures", liste(database.classement_captures_individuelles(limite), "user_id", "total_captures", lambda v: f"{v} captures")),
        ("dollars", "💰", "Plus de Poké Dollars", liste([r for r in database.classement_poke_dollars(limite) if r["poke_dollars"] > 0], "user_id", "poke_dollars", lambda v: f"{v} PD")),
        ("pokedex", "📖", "Complétion du Pokédex", liste(database.classement_completion_pokedex(limite), "user_id", "especes_distinctes", lambda v: f"{v}/{total} ({v / total:.0%})")),
        ("pvp", "🥊", "Victoires PvP", liste(database.classement_victoires_pvp(limite), "user_id", "victoires_pvp", lambda v: f"{v} victoires")),
        ("shiny", "🌟", "Pokémon shiny capturés", liste(database.classement_shiny(limite), "user_id", "total_shiny", lambda v: f"{v} ✨")),
        ("exploration", "🗺️", "Expéditions terminées", liste(database.classement_explorations(limite), "user_id", "explorations_terminees", lambda v: f"{v} expéditions")),
        ("roguelike", "🏰", "Meilleur étage Roguelike", liste(database.classement_roguelike(limite), "joueur_id", "meilleur_etage", lambda v: f"étage {v}")),
    ]
    tops = {r["equipe"]: r for r in database.classement_equipes()}
    clans = []
    for nom_equipe in config.COULEURS_EQUIPES:
        r = tops.get(nom_equipe)
        clans.append({"nom": nom_equipe, "emoji": config.EMOJI_EQUIPES.get(nom_equipe, ""),
                      "captures": r["total_captures"] if r else 0, "pc": r["total_pc"] if r else 0})
    clans.sort(key=lambda c: -c["pc"])
    return {"categories": [{"cle": c, "emoji": e, "titre": t, "lignes": l} for c, e, t, l in cats], "clans": clans}
