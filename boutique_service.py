"""boutique_service.py — Boutique et Marché Noir sur le site (sans Discord).

Mêmes prix, mêmes limites de sac et mêmes plafonds quotidiens que boutique.py (qui n'est
utilisé ici que pour la rotation du jour du Marché Noir). Le rôle VIP Discord n'est pas
proposé : il n'a pas de sens hors du serveur Discord.
Le Marché Noir est ouvert/fermé par le bot (en mémoire) ; le site relit son créneau du
jour dans la base (marche_noir_event_debut).
"""

import time

import boutique
import capacites as capacites_module
import config
import database
import mega_evolutions as mega_evolutions_module
from combat_service import ErreurCombatWeb
from pokemon_data import NOM_BALL_AFFICHAGE, NOM_SOIN_AFFICHAGE, prix_ct

MAX_QUANTITE = 999


def _marche_noir_ouvert() -> tuple:
    try:
        debut = int(database.obtenir_parametre("marche_noir_event_debut") or 0)
    except ValueError:
        return False, 0
    fin = debut + config.DUREE_MARCHE_NOIR
    maintenant = time.time()
    if debut > 0 and debut <= maintenant < fin:
        return True, int(fin - maintenant)
    return False, 0


def _soin_texte(cle: str) -> str:
    if cle == "totalsoin":
        return "Soigne tous les statuts en combat"
    pct = round(config.SOIN_POURCENT.get(cle, 0) * 100)
    return "Soin complet" if pct >= 100 else f"+{pct}% des PV max"


def catalogue(user_id: int) -> dict:
    inv = database.obtenir_inventaire_balls(user_id)
    utilises = database.compter_objets_totaux(user_id)
    limite = database.limite_stockage_objets(user_id)
    ouvert, reste = _marche_noir_ouvert()

    marche = {"ouvert": ouvert, "secondes_restantes": reste, "objets": [], "cts": []}
    if ouvert:
        objets, cts = boutique._rotation_marche_noir_du_jour()
        possedees = database.obtenir_ct_possedees(user_id)
        for cle in objets:
            nom, _e, prix, plafond = boutique._nom_emoji_prix_objet_rare(cle)
            marche["objets"].append({
                "cle": cle, "nom": nom, "prix": prix, "plafond": plafond,
                "achete": database.compter_achats_marche_noir(user_id, cle),
            })
        for nom in cts:
            normal = prix_ct(nom)
            marche["cts"].append({
                "nom": nom, "prix_normal": normal, "prix": round(normal * (1 - config.REMISE_MARCHE_NOIR_CT)),
                "achete": database.compter_achats_marche_noir(user_id, f"ct_{nom}") >= config.CAP_MARCHE_NOIR_CT,
                "possedee": nom in possedees,
            })

    return {
        "poke_dollars": database.obtenir_poke_dollars(user_id),
        "sac": {"utilises": utilises, "limite": limite},
        "stockage_pokemon": {
            "utilises": database.compter_captures_totales(user_id), "limite": database.limite_stockage_pokemon(user_id),
        },
        "balls": [
            {"cle": c, "nom": NOM_BALL_AFFICHAGE[c], "prix": p, "possede": inv.get(c, 0)}
            for c, p in config.PRIX_BALLS.items()
        ],
        "soins": [
            {"cle": c, "nom": NOM_SOIN_AFFICHAGE[c], "prix": p, "description": _soin_texte(c), "possede": inv.get(c, 0)}
            for c, p in config.PRIX_SOINS.items()
        ],
        "ameliorations": {
            "pokemon": {"gain": config.EXTENSION_STOCKAGE_POKEMON, "prix": config.PRIX_EXTENSION_STOCKAGE_POKEMON},
            "objets": {"gain": config.EXTENSION_STOCKAGE_OBJETS, "prix": config.PRIX_EXTENSION_STOCKAGE_OBJETS},
            "slot_exploration": {
                "achetable": database.nb_slots_exploration(user_id) < 2, "prix": config.EXTENSION_SLOT_EXPLORATION_PRIX,
            },
        },
        "objets_tenus": [
            {"cle": c, "nom": i["nom"], "description": i["description"], "prix": config.PRIX_OBJETS_TENUS[c], "possede": inv.get(c, 0)}
            for c, i in capacites_module.OBJETS_TENUS.items() if c in config.PRIX_OBJETS_TENUS
        ],
        "gemmes_mega": [
            {"cle": c, "nom": i["objet_nom"], "espece": i["espece"], "prix": config.PRIX_GEMME_MEGA, "possede": inv.get(c, 0)}
            for c, i in sorted(mega_evolutions_module.MEGA_EVOLUTIONS.items(), key=lambda kv: kv[1]["espece"])
        ],
        "marche_noir": marche,
    }


def _prix_et_nom(categorie: str, cle: str) -> tuple:
    if categorie == "balls" and cle in config.PRIX_BALLS:
        return config.PRIX_BALLS[cle], NOM_BALL_AFFICHAGE[cle]
    if categorie == "soins" and cle in config.PRIX_SOINS:
        return config.PRIX_SOINS[cle], NOM_SOIN_AFFICHAGE[cle]
    if categorie == "objets_tenus" and cle in config.PRIX_OBJETS_TENUS and cle in capacites_module.OBJETS_TENUS:
        return config.PRIX_OBJETS_TENUS[cle], capacites_module.OBJETS_TENUS[cle]["nom"]
    if categorie == "gemmes_mega" and cle in mega_evolutions_module.MEGA_EVOLUTIONS:
        return config.PRIX_GEMME_MEGA, mega_evolutions_module.MEGA_EVOLUTIONS[cle]["objet_nom"]
    raise ErreurCombatWeb("Article inconnu.")


def _verifier_quantite(quantite: int) -> int:
    if not isinstance(quantite, int) or quantite < 1 or quantite > MAX_QUANTITE:
        raise ErreurCombatWeb("Merci d'entrer un nombre entier positif.")
    return quantite


def _debiter(user_id: int, cout: int):
    solde = database.obtenir_poke_dollars(user_id)
    if solde < cout:
        raise ErreurCombatWeb(f"Solde insuffisant : il te faut {cout} Poké Dollars, tu en as {solde}.")
    database.ajouter_poke_dollars(user_id, -cout)


def acheter(user_id: int, categorie: str, cle: str, quantite: int = 1) -> dict:
    """Achat d'un article de la boutique (balls, soins, objets tenus, gemmes Méga)."""
    quantite = _verifier_quantite(quantite)
    prix, nom = _prix_et_nom(categorie, cle)
    utilises = database.compter_objets_totaux(user_id)
    limite = database.limite_stockage_objets(user_id)
    if utilises + quantite > limite:
        raise ErreurCombatWeb(
            f"Pas assez de place dans ton sac ({utilises}/{limite}) : il te reste {max(0, limite - utilises)} place(s)."
        )
    cout = prix * quantite
    _debiter(user_id, cout)
    database.ajouter_balls(user_id, cle, quantite)
    return {"message": f"Achat réussi : {quantite}× {nom} pour {cout} Poké Dollars.", "poke_dollars": database.obtenir_poke_dollars(user_id)}


def acheter_extension(user_id: int, type_extension: str, paliers: int = 1) -> dict:
    paliers = _verifier_quantite(paliers)
    if type_extension == "pokemon":
        prix, gain = config.PRIX_EXTENSION_STOCKAGE_POKEMON, config.EXTENSION_STOCKAGE_POKEMON
    elif type_extension == "objets":
        prix, gain = config.PRIX_EXTENSION_STOCKAGE_OBJETS, config.EXTENSION_STOCKAGE_OBJETS
    else:
        raise ErreurCombatWeb("Extension inconnue.")
    cout = prix * paliers
    _debiter(user_id, cout)
    if type_extension == "pokemon":
        database.acheter_extension_stockage_pokemon(user_id, paliers)
        nouvelle = database.limite_stockage_pokemon(user_id)
    else:
        database.acheter_extension_stockage_objets(user_id, paliers)
        nouvelle = database.limite_stockage_objets(user_id)
    return {"message": f"Stockage étendu de {gain * paliers} places pour {cout} Poké Dollars (nouvelle limite : {nouvelle}).",
            "poke_dollars": database.obtenir_poke_dollars(user_id)}


def acheter_marche_noir(user_id: int, type_article: str, cle: str, quantite: int = 1) -> dict:
    ouvert, _ = _marche_noir_ouvert()
    if not ouvert:
        raise ErreurCombatWeb("Le Marché Noir est fermé pour le moment.")
    objets, cts = boutique._rotation_marche_noir_du_jour()

    if type_article == "objet":
        if cle not in objets:
            raise ErreurCombatWeb("Cet objet n'est pas au Marché Noir aujourd'hui.")
        quantite = _verifier_quantite(quantite)
        nom, _e, prix, plafond = boutique._nom_emoji_prix_objet_rare(cle)
        deja = database.compter_achats_marche_noir(user_id, cle)
        if deja >= plafond:
            raise ErreurCombatWeb(f"Tu as déjà atteint ta limite de {plafond} pour {nom} aujourd'hui !")
        if quantite > plafond - deja:
            raise ErreurCombatWeb(f"Il ne te reste que {plafond - deja} exemplaire(s) possible(s) pour {nom} aujourd'hui.")
        cout = prix * quantite
        _debiter(user_id, cout)
        database.ajouter_balls(user_id, cle, quantite)
        database.incrementer_achat_marche_noir(user_id, cle, quantite)
        return {"message": f"Acheté : {quantite}× {nom} pour {cout} Poké Dollars.", "poke_dollars": database.obtenir_poke_dollars(user_id)}

    if type_article == "ct":
        if cle not in cts:
            raise ErreurCombatWeb("Cette CT n'est pas au Marché Noir aujourd'hui.")
        suivi = f"ct_{cle}"
        if database.compter_achats_marche_noir(user_id, suivi) >= config.CAP_MARCHE_NOIR_CT:
            raise ErreurCombatWeb(f"Tu as déjà acheté la CT {cle} aujourd'hui !")
        if cle in database.obtenir_ct_possedees(user_id):
            raise ErreurCombatWeb("Tu possèdes déjà cette CT !")
        normal = prix_ct(cle)
        reduit = round(normal * (1 - config.REMISE_MARCHE_NOIR_CT))
        _debiter(user_id, reduit)
        database.acheter_ct(user_id, cle)
        database.incrementer_achat_marche_noir(user_id, suivi)
        return {"message": f"CT achetée : {cle} pour {reduit} Poké Dollars (au lieu de {normal}).",
                "poke_dollars": database.obtenir_poke_dollars(user_id)}

    raise ErreurCombatWeb("Type d'article inconnu.")
