"""casino_service.py — Casino (Blackjack, Roulette) et mini-jeu Plus ou Moins sur le site.

Réutilise la logique pure de casino.py (deck, mains, résolution, roulette) et de
plus_ou_moins.py. Les parties de Blackjack et de Plus ou Moins sont gardées CÔTÉ SERVEUR
(le client ne voit jamais le deck ni la carte cachée du croupier).
"""

import json
import re
import random

import casino
import database
import plus_ou_moins
from combat_service import ErreurCombatWeb
from pokemon_data import POKEDEX, obtenir_pokemon_par_nom


def _init():
    conn = database.get_connexion()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS casino_web_blackjack (
            user_id INTEGER PRIMARY KEY, mise INTEGER NOT NULL, deck TEXT NOT NULL,
            joueur TEXT NOT NULL, croupier TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pom_web (
            user_id INTEGER PRIMARY KEY, actuel TEXT NOT NULL, mystere TEXT NOT NULL, streak INTEGER NOT NULL)""")
        conn.commit()
    finally:
        conn.close()


def _exec(sql, params=()):
    _init()
    conn = database.get_connexion()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur
    finally:
        conn.close()


def _lire(sql, params=()):
    _init()
    conn = database.get_connexion()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _cartes(l):
    return [[c[0], c[1]] for c in l]


# ----------------------------------------------------------------------------
# Blackjack
# ----------------------------------------------------------------------------
def _etat_bj(row, fini=False, resultat=None, gain=0):
    joueur = [tuple(c) for c in json.loads(row["joueur"])]
    croupier = [tuple(c) for c in json.loads(row["croupier"])]
    revele = fini
    res = {
        "mise": row["mise"], "fini": fini,
        "joueur": [casino.carte_texte(c) for c in joueur], "valeur_joueur": casino.valeur_main(joueur),
        "croupier": [casino.carte_texte(c) for c in croupier] if revele else [casino.carte_texte(croupier[0]), "🂠"],
        "valeur_croupier": casino.valeur_main(croupier) if revele else casino.VALEURS_CARTES[croupier[0][0]],
    }
    if fini:
        res["resultat"] = resultat
        res["gain"] = gain
        res["message"] = re.sub(r"<:\w+:\d+>", "PD", casino._texte_resultat_blackjack(resultat, row["mise"], gain).replace("**", ""))
    return res


def _terminer_bj(uid, row):
    """Fait jouer le croupier, résout, crédite. Le DELETE conditionnel empêche tout double paiement."""
    deck = [tuple(c) for c in json.loads(row["deck"])]
    joueur = [tuple(c) for c in json.loads(row["joueur"])]
    croupier = [tuple(c) for c in json.loads(row["croupier"])]
    if casino.valeur_main(joueur) <= 21:
        casino.jouer_croupier(croupier, deck)
    resultat, mult = casino.resoudre_blackjack(joueur, croupier)
    gain = round(row["mise"] * mult)
    if _exec("DELETE FROM casino_web_blackjack WHERE user_id = ?", (uid,)).rowcount == 0:
        raise ErreurCombatWeb("Cette partie est déjà terminée.")
    if gain > 0:
        database.ajouter_poke_dollars(uid, gain)
    row = {"mise": row["mise"], "joueur": json.dumps(_cartes(joueur)), "croupier": json.dumps(_cartes(croupier))}
    return _etat_bj(row, True, resultat, gain)


def _partie_bj(uid):
    return _lire("SELECT * FROM casino_web_blackjack WHERE user_id = ?", (uid,))


def blackjack_etat(uid):
    row = _partie_bj(uid)
    return _etat_bj(row) if row else None


def blackjack_demarrer(uid, mise):
    if _partie_bj(uid):
        raise ErreurCombatWeb("Tu as déjà une partie de Blackjack en cours.")
    _verifier_mise(uid, mise)
    database.ajouter_poke_dollars(uid, -mise)
    deck = casino.nouveau_deck()
    joueur = [deck.pop()]
    croupier = [deck.pop()]
    joueur.append(deck.pop())
    croupier.append(deck.pop())
    try:
        _exec("INSERT INTO casino_web_blackjack (user_id, mise, deck, joueur, croupier) VALUES (?,?,?,?,?)",
              (uid, mise, json.dumps(_cartes(deck)), json.dumps(_cartes(joueur)), json.dumps(_cartes(croupier))))
    except Exception:
        database.ajouter_poke_dollars(uid, mise)
        raise ErreurCombatWeb("Tu as déjà une partie de Blackjack en cours.")
    row = _partie_bj(uid)
    if casino.est_blackjack(joueur):
        return _terminer_bj(uid, row)
    return _etat_bj(row)


def blackjack_tirer(uid):
    row = _partie_bj(uid)
    if not row:
        raise ErreurCombatWeb("Aucune partie de Blackjack en cours.")
    deck = [tuple(c) for c in json.loads(row["deck"])]
    joueur = [tuple(c) for c in json.loads(row["joueur"])]
    joueur.append(deck.pop())
    _exec("UPDATE casino_web_blackjack SET deck = ?, joueur = ? WHERE user_id = ?",
          (json.dumps(_cartes(deck)), json.dumps(_cartes(joueur)), uid))
    row = _partie_bj(uid)
    if casino.valeur_main(joueur) >= 21:
        return _terminer_bj(uid, row)
    return _etat_bj(row)


def blackjack_rester(uid):
    row = _partie_bj(uid)
    if not row:
        raise ErreurCombatWeb("Aucune partie de Blackjack en cours.")
    return _terminer_bj(uid, row)


def _verifier_mise(uid, mise):
    ok, res = casino._valider_mise(uid, str(int(mise)) if isinstance(mise, int) and mise > 0 else "x")
    if not ok:
        raise ErreurCombatWeb(re.sub(r"<:\w+:\d+>", "PD", res.replace("❌ ", "")))


# ----------------------------------------------------------------------------
# Roulette
# ----------------------------------------------------------------------------
def roulette(uid, type_mise, numero, mise):
    if type_mise != "plein" and type_mise not in casino.TYPES_MISE_ROULETTE:
        raise ErreurCombatWeb("Type de mise inconnu.")
    if type_mise == "plein" and (numero is None or not 0 <= numero <= 36):
        raise ErreurCombatWeb("Numéro invalide (0 à 36).")
    _verifier_mise(uid, mise)
    database.ajouter_poke_dollars(uid, -mise)
    tire = casino.tirer_roulette()
    gagne, mult = casino.resoudre_roulette(tire, type_mise, numero)
    gain = round(mise * mult)
    if gain > 0:
        database.ajouter_poke_dollars(uid, gain)
    return {"numero": tire, "couleur": casino.couleur_numero(tire), "gagne": gagne, "gain": gain, "mise": mise,
            "message": f"🎉 Tu gagnes ! Total récupéré : {gain} PD" if gagne else f"❌ Tu perds ta mise de {mise} PD."}


# ----------------------------------------------------------------------------
# Plus ou Moins
# ----------------------------------------------------------------------------
def _fiche_pokemon(nom, cache=False):
    p = obtenir_pokemon_par_nom(nom)
    return {"nom": nom, "pc": None if cache else p["base_pc"]}


def pom_etat(uid):
    row = _lire("SELECT * FROM pom_web WHERE user_id = ?", (uid,))
    res = {"record": database.obtenir_record_plus_ou_moins(uid), "partie": None}
    if row:
        res["partie"] = {"actuel": _fiche_pokemon(row["actuel"]), "mystere": _fiche_pokemon(row["mystere"], True),
                         "serie": row["streak"]}
    return res


def pom_demarrer(uid):
    a, m = plus_ou_moins.tirer_pokemon_pc(), plus_ou_moins.tirer_pokemon_pc()
    _exec("INSERT OR REPLACE INTO pom_web (user_id, actuel, mystere, streak) VALUES (?,?,?,0)", (uid, a["nom"], m["nom"]))
    return pom_etat(uid)


def pom_choisir(uid, plus):
    row = _lire("SELECT * FROM pom_web WHERE user_id = ?", (uid,))
    if not row:
        raise ErreurCombatWeb("Aucune partie en cours.")
    pa, pm = obtenir_pokemon_par_nom(row["actuel"])["base_pc"], obtenir_pokemon_par_nom(row["mystere"])["base_pc"]
    juste = (pm >= pa) if plus else (pm <= pa)
    info = {"revele": {"nom": row["mystere"], "pc": pm}, "contre": {"nom": row["actuel"], "pc": pa}, "juste": juste}
    if juste:
        nouveau = plus_ou_moins.tirer_pokemon_pc()["nom"]
        _exec("UPDATE pom_web SET actuel = ?, mystere = ?, streak = streak + 1 WHERE user_id = ?", (row["mystere"], nouveau, uid))
        return {**info, **pom_etat(uid), "fini": False}
    record = database.obtenir_record_plus_ou_moins(uid)
    nouveau_record = row["streak"] > record
    if nouveau_record:
        database.definir_record_plus_ou_moins(uid, row["streak"])
    _exec("DELETE FROM pom_web WHERE user_id = ?", (uid,))
    return {**info, "fini": True, "serie": row["streak"], "nouveau_record": nouveau_record,
            "record": max(record, row["streak"]), "partie": None}


def etat(uid):
    return {"solde": database.obtenir_poke_dollars(uid), "mise_min": casino.MISE_MINIMUM, "mise_max": casino.MISE_MAXIMUM,
            "blackjack": blackjack_etat(uid), "pom": pom_etat(uid)}
