"""echanges_service.py — Marketplace (ventes directes et enchères) et Échanges entre
joueurs sur le site (sans Discord).

Mêmes règles et mêmes fonctions de base que marketplace.py / echanges.py : annonces et
échanges sont dans les mêmes tables que le bot. Le bot continue de purger les annonces
expirées et de résoudre les enchères terminées ; le site n'affiche que ce qui est actif.
Les annonces créées sur le site n'ont pas de message dans le channel Discord.
"""

import time

import capacites as capacites_module
import config
import database
import formes_objets as formes_objets_module
from combat_service import ErreurCombatWeb
from pokemon_data import (
    NOM_BALL_AFFICHAGE, NOM_OBJETS_DIVERS, NOM_SOIN_AFFICHAGE, cle_tri_alphabetique_fr, obtenir_pokemon_par_nom,
)

PAR_PAGE = 20


def _pseudos() -> dict:
    conn = database.get_connexion()
    try:
        return {r["user_id"]: r["pseudo"] for r in conn.execute("SELECT user_id, pseudo FROM web_joueurs")}
    except Exception:
        return {}
    finally:
        conn.close()


def _nom(pseudos: dict, uid) -> str:
    return pseudos.get(uid) or f"Dresseur #{str(uid)[-4:]}"


def noms_objets() -> dict:
    return {
        **NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS,
        **{c: i["nom"] for c, i in capacites_module.OBJETS_TENUS.items()},
        **{c: i["objet_nom"] for c, i in formes_objets_module.FORMES_OBJETS.items()},
    }


# ----------------------------------------------------------------------------
# Marketplace
# ----------------------------------------------------------------------------

def _fiche_annonce(r, user_id: int, pseudos: dict) -> dict:
    enchere = r["type_annonce"] == "enchere"
    return {
        "id": r["id"], "nom": r["pokemon_nom"], "pc": r["pc"], "shiny": bool(r["shiny"]),
        "type": "enchere" if enchere else "directe", "vendeur": _nom(pseudos, r["vendeur_id"]), "mienne": r["vendeur_id"] == user_id,
        "prix": r["prix"], "prix_actuel": r["prix_actuel"] if enchere else None,
        "minimum": (r["prix_actuel"] + 1 if r["prix_actuel"] else r["prix"]) if enchere else r["prix"],
        "meilleur_offrant_moi": bool(enchere and r["enchereur_actuel_id"] == user_id),
        "a_des_offres": bool(enchere and r["enchereur_actuel_id"] is not None),
        "secondes_restantes": max(0, r["date_expiration"] - int(time.time())),
    }


def annonces(user_id: int, recherche: str = "", type_annonce: str = "toutes", page: int = 0, tri: str = "recentes") -> dict:
    conn = database.get_connexion()
    rows = conn.execute(
        """SELECT m.*, c.pokemon_nom, c.pc, c.shiny FROM marketplace_annonces m JOIN captures c ON c.id = m.capture_id
           WHERE m.statut = 'active' AND m.date_expiration > ? ORDER BY m.date_creation DESC""",
        (int(time.time()),),
    ).fetchall()
    conn.close()
    if recherche:
        t = cle_tri_alphabetique_fr(recherche)
        rows = [r for r in rows if t in cle_tri_alphabetique_fr(r["pokemon_nom"])]
    if type_annonce == "directe":
        rows = [r for r in rows if r["type_annonce"] != "enchere"]
    elif type_annonce == "enchere":
        rows = [r for r in rows if r["type_annonce"] == "enchere"]
    if tri == "prix_asc":
        rows.sort(key=lambda r: r["prix_actuel"] or r["prix"])
    elif tri == "prix_desc":
        rows.sort(key=lambda r: -(r["prix_actuel"] or r["prix"]))
    elif tri == "pc_desc":
        rows.sort(key=lambda r: -r["pc"])
    elif tri == "fin":
        rows.sort(key=lambda r: r["date_expiration"])
    nb_pages = max(1, (len(rows) + PAR_PAGE - 1) // PAR_PAGE)
    page = max(0, min(page, nb_pages - 1))
    ps = _pseudos()
    return {"page": page, "nb_pages": nb_pages, "nb": len(rows), "solde": database.obtenir_poke_dollars(user_id),
            "annonces": [_fiche_annonce(r, user_id, ps) for r in rows[page * PAR_PAGE:(page + 1) * PAR_PAGE]]}


def mes_annonces(user_id: int) -> dict:
    conn = database.get_connexion()
    rows = conn.execute(
        """SELECT m.*, c.pokemon_nom, c.pc, c.shiny FROM marketplace_annonces m LEFT JOIN captures c ON c.id = m.capture_id
           WHERE m.vendeur_id = ? OR m.acheteur_id = ? OR m.enchereur_actuel_id = ? ORDER BY m.date_creation DESC LIMIT 40""",
        (user_id, user_id, user_id),
    ).fetchall()
    conn.close()
    ps = _pseudos()
    maintenant = int(time.time())
    out = []
    for r in rows:
        d = {"id": r["id"], "nom": r["pokemon_nom"] or "?", "pc": r["pc"], "shiny": bool(r["shiny"]),
             "type": "enchere" if r["type_annonce"] == "enchere" else "directe", "statut": r["statut"],
             "prix": r["prix_actuel"] or r["prix"], "role": "vendeur" if r["vendeur_id"] == user_id else ("acheteur" if r["acheteur_id"] == user_id else "enchérisseur"),
             "actif": r["statut"] == "active" and r["date_expiration"] > maintenant,
             "a_des_offres": r["enchereur_actuel_id"] is not None, "secondes_restantes": max(0, r["date_expiration"] - maintenant)}
        out.append(d)
    return {"annonces": out}


def vendable(user_id: int, recherche: str = "") -> dict:
    lignes = [dict(r) for r in database.obtenir_toutes_captures_detaillees(user_id)]
    if recherche:
        t = cle_tri_alphabetique_fr(recherche)
        lignes = [r for r in lignes if t in cle_tri_alphabetique_fr(r["pokemon_nom"])]
    return {"nb": len(lignes), "captures": [
        {"id": r["id"], "nom": r["pokemon_nom"], "pc": r["pc"], "shiny": bool(r["shiny"]), "dernier": r["total_espece"] == 1 and r["rang"] == 1,
         "en_vente": database.capture_deja_en_vente(r["id"])}
        for r in lignes[:40]]}


def _verifier_prix(prix) -> int:
    if not isinstance(prix, int) or not config.MARKETPLACE_PRIX_MIN <= prix <= config.MARKETPLACE_PRIX_MAX:
        raise ErreurCombatWeb(f"Le prix doit être compris entre {config.MARKETPLACE_PRIX_MIN} et {config.MARKETPLACE_PRIX_MAX} Poké Dollars.")
    return prix


def vendre(user_id: int, capture_id: int, prix: int, type_annonce: str) -> dict:
    prix = _verifier_prix(prix)
    conn = database.get_connexion()
    row = conn.execute("SELECT pokemon_nom FROM captures WHERE id = ? AND user_id = ?", (capture_id, user_id)).fetchone()
    conn.close()
    if row is None:
        raise ErreurCombatWeb("Pokémon introuvable dans ta collection.")
    if database.capture_deja_en_vente(capture_id):
        raise ErreurCombatWeb("Ce Pokémon est déjà en vente.")
    if type_annonce == "enchere":
        database.creer_annonce_enchere(user_id, capture_id, prix, config.MARKETPLACE_DUREE_ANNONCE_SECONDES)
        return {"message": f"{row['pokemon_nom']} mis aux enchères (mise à prix {prix} PD, 7 jours)."}
    if type_annonce == "directe":
        database.creer_annonce_marketplace(user_id, capture_id, prix, config.MARKETPLACE_DUREE_ANNONCE_SECONDES)
        return {"message": f"{row['pokemon_nom']} mis en vente pour {prix} PD (7 jours)."}
    raise ErreurCombatWeb("Type d'annonce inconnu.")


def _annonce_active(annonce_id: int):
    a = database.obtenir_annonce_marketplace(annonce_id)
    if a is None or a["statut"] != "active" or a["date_expiration"] <= int(time.time()):
        raise ErreurCombatWeb("Cette annonce n'est plus disponible.")
    return a


def acheter(user_id: int, annonce_id: int) -> dict:
    a = _annonce_active(annonce_id)
    if a["type_annonce"] == "enchere":
        raise ErreurCombatWeb("C'est une enchère : place une offre.")
    ok, err = database.executer_achat_marketplace(annonce_id, user_id)
    if not ok:
        raise ErreurCombatWeb(err)
    return {"message": f"Achat réussi pour {a['prix']} Poké Dollars !", "solde": database.obtenir_poke_dollars(user_id)}


def encherir(user_id: int, annonce_id: int, montant: int) -> dict:
    a = _annonce_active(annonce_id)
    if a["type_annonce"] != "enchere":
        raise ErreurCombatWeb("Ce n'est pas une enchère.")
    if not isinstance(montant, int) or montant <= 0:
        raise ErreurCombatWeb("Montant invalide.")
    ok, err = database.placer_enchere(annonce_id, user_id, montant)
    if not ok:
        raise ErreurCombatWeb(err)
    return {"message": f"Enchère de {montant} PD placée (fonds retenus jusqu'à la fin ou jusqu'à ce qu'on te surenchérisse).",
            "solde": database.obtenir_poke_dollars(user_id)}


def retirer(user_id: int, annonce_id: int) -> dict:
    a = _annonce_active(annonce_id)
    if a["vendeur_id"] != user_id:
        raise ErreurCombatWeb("Seul le vendeur peut retirer cette annonce.")
    if a["type_annonce"] == "enchere" and a["enchereur_actuel_id"] is not None:
        raise ErreurCombatWeb("Impossible de retirer : une enchère a déjà été placée, elle doit aller à son terme.")
    database.marquer_annonce_marketplace(annonce_id, "annulee")
    return {"message": "Annonce retirée : ton Pokémon est resté chez toi."}


# ----------------------------------------------------------------------------
# Échanges
# ----------------------------------------------------------------------------

def _init():
    conn = database.get_connexion()
    conn.execute("CREATE TABLE IF NOT EXISTS echange_web_issue (echange_id INTEGER PRIMARY KEY, issue TEXT NOT NULL, detail TEXT, date INTEGER NOT NULL)")
    conn.commit()
    conn.close()


def _issue(echange_id: int, issue: str, detail: str = ""):
    _init()
    conn = database.get_connexion()
    conn.execute("INSERT OR REPLACE INTO echange_web_issue (echange_id, issue, detail, date) VALUES (?, ?, ?, ?)",
                 (echange_id, issue, detail, int(time.time())))
    conn.commit()
    conn.close()


def _cote(echange, uid: int, pseudos: dict) -> dict:
    est1 = echange["joueur1_id"] == uid
    return {
        "id": uid, "pseudo": _nom(pseudos, uid),
        "pokemon": [{"id": r["id"], "nom": r["pokemon_nom"], "pc": r["pc"], "shiny": bool(r["shiny"])} for r in database.obtenir_offre_echange(echange["id"], uid)],
        "pd": echange["joueur1_pd" if est1 else "joueur2_pd"],
        "objets": [{"cle": c, "nom": noms_objets().get(c, c), "quantite": q} for c, q in database.obtenir_objets_offre_echange(echange["id"], uid).items()],
        "valide": bool(echange["joueur1_valide" if est1 else "joueur2_valide"]),
    }


def etat_echange(user_id: int) -> dict:
    _init()
    e = database.echange_en_cours_pour_joueur(user_id)
    ps = _pseudos()
    out = {"echange": None, "dernier": None, "solde": database.obtenir_poke_dollars(user_id)}
    if e is not None:
        autre = e["joueur2_id"] if e["joueur1_id"] == user_id else e["joueur1_id"]
        out["echange"] = {"id": e["id"], "moi": _cote(e, user_id, ps), "autre": _cote(e, autre, ps), "discord": bool(e["thread_id"])}
    else:
        conn = database.get_connexion()
        r = conn.execute(
            """SELECT e.id, i.issue, i.detail FROM echanges e LEFT JOIN echange_web_issue i ON i.echange_id = e.id
               WHERE e.actif = 0 AND (e.joueur1_id = ? OR e.joueur2_id = ?) AND e.date_creation > ? ORDER BY e.id DESC LIMIT 1""",
            (user_id, user_id, int(time.time()) - 900),
        ).fetchone()
        conn.close()
        if r and r["issue"]:
            out["dernier"] = {"issue": r["issue"], "detail": r["detail"]}
    conn = database.get_connexion()
    out["joueurs"] = [{"id": j["user_id"], "pseudo": j["pseudo"]} for j in conn.execute(
        "SELECT user_id, pseudo FROM web_joueurs WHERE user_id != ? ORDER BY vu_a DESC LIMIT 40", (user_id,))]
    conn.close()
    return out


def proposer_echange(user_id: int, cible_id: int) -> dict:
    _init()
    if cible_id == user_id:
        raise ErreurCombatWeb("Cible invalide.")
    conn = database.get_connexion()
    ok = conn.execute("SELECT 1 FROM web_joueurs WHERE user_id = ?", (cible_id,)).fetchone()
    conn.close()
    if not ok:
        raise ErreurCombatWeb("Ce joueur ne s'est jamais connecté au site : impossible de lui proposer un échange ici.")
    if database.echange_en_cours_pour_joueur(user_id):
        raise ErreurCombatWeb("Tu as déjà un échange en cours.")
    if database.echange_en_cours_pour_joueur(cible_id):
        raise ErreurCombatWeb("Ce joueur a déjà un échange en cours.")
    return {"echange_id": database.creer_echange(user_id, cible_id)}


def _echange_participant(user_id: int, echange_id: int):
    e = database.obtenir_echange(echange_id)
    if not e or not e["actif"] or user_id not in (e["joueur1_id"], e["joueur2_id"]):
        raise ErreurCombatWeb("Cet échange n'est plus disponible.")
    return e


def definir_offre(user_id: int, echange_id: int, capture_ids: list, pd: int, objets: dict) -> dict:
    _echange_participant(user_id, echange_id)
    if not isinstance(pd, int) or pd < 0:
        raise ErreurCombatWeb("Montant de Poké Dollars invalide.")
    if pd > database.obtenir_poke_dollars(user_id):
        raise ErreurCombatWeb(f"Tu n'as que {database.obtenir_poke_dollars(user_id)} Poké Dollars.")
    ids = list(dict.fromkeys(int(i) for i in capture_ids))
    if len(ids) > 50:
        raise ErreurCombatWeb("50 Pokémon maximum par offre.")
    if ids:
        conn = database.get_connexion()
        marq = ",".join("?" for _ in ids)
        poss = {r["id"] for r in conn.execute(f"SELECT id FROM captures WHERE user_id = ? AND id IN ({marq})", (user_id, *ids))}
        conn.close()
        if poss != set(ids):
            raise ErreurCombatWeb("Un des Pokémon proposés n'est pas dans ta collection.")
        if any(database.capture_deja_en_vente(i) for i in ids):
            raise ErreurCombatWeb("Un des Pokémon proposés est en vente sur le marketplace.")
    inv = database.obtenir_inventaire_balls(user_id)
    catalogue = noms_objets()
    propres = {}
    for cle, q in (objets or {}).items():
        if cle not in catalogue:
            raise ErreurCombatWeb("Objet inconnu.")
        if not isinstance(q, int) or q < 0 or q > inv.get(cle, 0):
            raise ErreurCombatWeb(f"Quantité invalide pour {catalogue[cle]} (tu en as {inv.get(cle, 0)}).")
        if q > 0:
            propres[cle] = q
    database.definir_offre_echange(echange_id, user_id, ids, pd)
    database.definir_objets_offre_echange(echange_id, user_id, propres)
    return {"message": "Offre mise à jour (les validations sont remises à zéro)."}


def valider_echange(user_id: int, echange_id: int) -> dict:
    _init()
    _echange_participant(user_id, echange_id)
    if not database.valider_offre_echange(echange_id, user_id):
        return {"fini": False, "message": "Offre validée : en attente de l'autre joueur."}
    ok, err = database.executer_echange(echange_id)
    if ok:
        _issue(echange_id, "conclu")
        return {"fini": True, "succes": True, "message": "Échange conclu ! Les Pokémon, objets et Poké Dollars ont changé de propriétaire."}
    database.annuler_echange(echange_id)
    detail = (err or "").replace("<@", "").replace(">", "")
    _issue(echange_id, "annule", detail)
    return {"fini": True, "succes": False, "message": f"Échange annulé : {detail}"}


def annuler_echange(user_id: int, echange_id: int) -> dict:
    _init()
    _echange_participant(user_id, echange_id)
    database.annuler_echange(echange_id)
    _issue(echange_id, "annule", "annulé par un des joueurs")
    return {"message": "Échange annulé."}


def objets_proposables(user_id: int) -> dict:
    inv = database.obtenir_inventaire_balls(user_id)
    n = noms_objets()
    return {"objets": sorted(({"cle": c, "nom": n.get(c, c), "possede": q} for c, q in inv.items() if q > 0), key=lambda o: cle_tri_alphabetique_fr(o["nom"]))}
