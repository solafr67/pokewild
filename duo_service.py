"""duo_service.py — Double combat 2v2 (un joueur contrôle 2 Pokémon face à un duo de
dresseurs IA) sur le site, sans Discord.

Réutilise le moteur de combat_2v2.py (résolution de tour, ciblage, IA) et ses tables
(combat_2v2_joueurs…). Comme sur Discord, le joueur occupe 2 sièges : le sien (« a ») et
un siège délégué (« b »), avec UNE réserve d'équipe partagée (PV persistants réels).
Mêmes récompenses que le 2v2 Discord. Pour éviter le farm (sur Discord un duo n'apparaît
que par spawn), un délai est imposé entre deux duos lancés depuis le site.
"""

import asyncio
import json
import re
import time
import traceback

import combat_2v2 as c2
import combat as combat_module
import config
import database
import dresseurs as dresseurs_module
import leveling
import mega_evolutions as mega_evolutions_module
from combat_service import IV_DEFAUT, calculer_toutes_stats
from combat_service import ErreurCombatWeb, _RE_EMOJI_DISCORD
from pokemon_data import NOM_SOIN_AFFICHAGE, obtenir_attaque, obtenir_pokemon_par_nom, pp_max_attaque

DELAI_ENTRE_DUOS = 600  # secondes


def _init():
    conn = database.get_connexion()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS duo_web_meta (combat_id INTEGER PRIMARY KEY, joueur_id INTEGER NOT NULL, archetype TEXT NOT NULL, noms TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS duo_web_journal (combat_id INTEGER NOT NULL, tour INTEGER NOT NULL, lignes TEXT NOT NULL, PRIMARY KEY (combat_id, tour))")
        conn.execute("CREATE TABLE IF NOT EXISTS duo_web_pvp (combat_id INTEGER PRIMARY KEY, j2_id INTEGER NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS duo_web_resultat (combat_id INTEGER PRIMARY KEY, resultat TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS duo_web_cooldown (user_id INTEGER PRIMARY KEY, date INTEGER NOT NULL)")
        conn.commit()
    finally:
        conn.close()


def _q(sql, params=(), un=True, ecrire=False):
    _init()
    conn = database.get_connexion()
    try:
        cur = conn.execute(sql, params)
        if ecrire:
            conn.commit()
            return cur
        return cur.fetchone() if un else cur.fetchall()
    finally:
        conn.close()


def est_duo(combat_id: int) -> bool:
    return _q("SELECT 1 FROM duo_web_meta WHERE combat_id = ?", (combat_id,)) is not None


def duos_web_actifs() -> list:
    rows = _q("SELECT m.combat_id FROM duo_web_meta m JOIN combat_pvp c ON c.id = m.combat_id WHERE c.actif = 1", un=False)
    return [r["combat_id"] for r in rows]


def _j2(combat_id):
    r = _q("SELECT j2_id FROM duo_web_pvp WHERE combat_id = ?", (combat_id,))
    return r["j2_id"] if r else None


def _reels(m):
    """Joueurs humains du combat (1 en solo contre l'IA, 2 en PvP)."""
    j2 = _j2(m["combat_id"])
    return [m["joueur_id"]] + ([j2] if j2 else [])


def _verifier_participant(m, uid):
    if uid not in _reels(m):
        raise ErreurCombatWeb("Ce n'est pas ton combat.")


def _mon_equipe(combat_id, uid):
    """Numéro d'équipe (1 ou 2) du joueur, et de l'équipe adverse."""
    mes = _sieges_joueur(combat_id, uid)
    e = mes[0]["equipe"] if mes else 1
    return e, (2 if e == 1 else 1)


def _meta(combat_id):
    m = _q("SELECT * FROM duo_web_meta WHERE combat_id = ?", (combat_id,))
    if m is None:
        raise ErreurCombatWeb("Ce combat n'a pas été lancé par le web.")
    return m


def _sieges_joueur(combat_id, uid):
    return [j for j in database.obtenir_joueurs_2v2(combat_id) if c2.controleur_reel(j["user_id"]) == uid]


def _siege(combat_id, uid, cle):
    sieges = _sieges_joueur(combat_id, uid)
    if cle not in ("a", "b") or len(sieges) < 2:
        raise ErreurCombatWeb("Siège invalide.")
    return next(j for j in sieges if c2.est_delegue(j["user_id"]) == (cle == "b"))


# ----------------------------------------------------------------------------
# Démarrage
# ----------------------------------------------------------------------------
def liste(uid) -> dict:
    reste = 0
    row = _q("SELECT date FROM duo_web_cooldown WHERE user_id = ?", (uid,))
    if row:
        reste = max(0, row["date"] + DELAI_ENTRE_DUOS - int(time.time()))
    return {"duos": [{"nom": a["nom"], "sous_noms": list(a["sous_noms"]), "emoji": a["emoji"], "types": a["types_theme"], "sprite": a.get("sprite")}
                     for a in dresseurs_module.ARCHETYPES_DUO],
            "attente": reste, "gain": {"pd": c2.DOLLARS_VICTOIRE, "xp": c2.XP_VICTOIRE}}


def _equipe_reelle(uid: int) -> list:
    """[(stats, pv)] des Pokémon vivants de l'équipe de combat ; au moins 2 requis."""
    noms = database.obtenir_equipe_combat_disponible(uid)
    possedees = {r["pokemon_nom"] for r in database.obtenir_pokedex_joueur(uid)}
    equipe = []
    for nom in noms:
        if nom not in possedees:
            continue
        stats = c2.stats_combattant_reel(uid, nom)
        pv = database.obtenir_pv_actuels(uid, nom, stats["pv"])
        if pv > 0:
            equipe.append((stats, pv))
    if len(equipe) < 2:
        raise ErreurCombatWeb("Il te faut au moins 2 Pokémon vivants dans ton équipe de combat (soigne-la ou change-la).")
    return equipe


def _inserer_equipe(combat_id: int, uid: int, equipe: list):
    conn = database.get_connexion()
    try:
        for i, (stats, pv) in enumerate(equipe):
            src = conn.execute("SELECT capacite, objet_tenu FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC LIMIT 1", (uid, stats["nom"])).fetchone()
            conn.execute(
                """INSERT INTO combat_equipe (combat_id, user_id, pokemon_nom, pv_max, pv_actuels, position, atq, defe, atq_spe, def_spe, vit, niveau, capacite, objet_tenu)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (combat_id, uid, stats["nom"], stats["pv"], pv, i, stats["attaque"], stats["defense"], stats["attaque_spe"],
                 stats["defense_spe"], stats["vitesse"], stats["niveau"], src["capacite"] if src else None, src["objet_tenu"] if src else None))
        conn.commit()
    finally:
        conn.close()


def creer_pvp(j1: int, pseudo1: str, j2: int, pseudo2: str) -> dict:
    """Double combat entre deux joueurs : chacun contrôle 2 Pokémon (équipe partagée)."""
    for u in (j1, j2):
        if database.combat_en_cours_pour_joueur(u) is not None:
            raise ErreurCombatWeb("L'un des deux joueurs a déjà un combat en cours.")
    e1, e2 = _equipe_reelle(j1), _equipe_reelle(j2)
    d1, d2 = c2.id_delegue(j1), c2.id_delegue(j2)
    limite = int(time.time()) + c2.DUREE_TOUR_2V2
    combat_id = database.creer_combat(j1, j2, e1[0][0]["nom"], e2[0][0]["nom"], limite)
    database.creer_joueurs_2v2(combat_id, [
        (j1, 1, e1[0][0]["nom"]), (d1, 1, e1[1][0]["nom"]),
        (j2, 2, e2[0][0]["nom"]), (d2, 2, e2[1][0]["nom"]),
    ])
    _inserer_equipe(combat_id, j1, e1)
    _inserer_equipe(combat_id, j2, e2)
    noms = {str(j1): pseudo1, str(d1): f"{pseudo1} (2)", str(j2): pseudo2, str(d2): f"{pseudo2} (2)"}
    _q("INSERT INTO duo_web_meta (combat_id, joueur_id, archetype, noms) VALUES (?,?,?,?)",
       (combat_id, j1, "Duel 2v2", json.dumps(noms, ensure_ascii=False)), ecrire=True)
    _q("INSERT INTO duo_web_pvp (combat_id, j2_id) VALUES (?,?)", (combat_id, j2), ecrire=True)
    return {"combat_id": combat_id}


async def demarrer(uid: int, pseudo: str, nom_archetype: str) -> dict:
    archetype = next((a for a in dresseurs_module.ARCHETYPES_DUO if a["nom"] == nom_archetype), None)
    if archetype is None:
        raise ErreurCombatWeb("Duo inconnu.")
    if database.combat_en_cours_pour_joueur(uid) is not None:
        raise ErreurCombatWeb("Tu as déjà un combat en cours !")
    attente = liste(uid)["attente"]
    if attente:
        raise ErreurCombatWeb(f"Prochain double combat possible dans {attente // 60 + 1} min.")

    equipe = _equipe_reelle(uid)
    pc_cible = round(dresseurs_module._pc_cumule_equipe(uid)) or 500
    niveau_ref = dresseurs_module._niveau_moyen_equipe(uid)
    ia1 = dresseurs_module.generer_equipe_dresseur(archetype, pc_cible, niveau_ref)
    ia2 = dresseurs_module.generer_equipe_dresseur(archetype, pc_cible, niveau_ref)
    if not ia1 or not ia2:
        raise ErreurCombatWeb("Impossible de générer l'équipe adverse.")

    dele = c2.id_delegue(uid)
    limite = int(time.time()) + c2.DUREE_TOUR_2V2
    combat_id = database.creer_combat(uid, dresseurs_module.ID_DRESSEUR_BASE - uid, equipe[0][0]["nom"], ia1[0]["nom"], limite)
    id1 = dresseurs_module.ID_DRESSEUR_BASE - combat_id * 2
    id2 = id1 - 1
    database.creer_joueurs_2v2(combat_id, [
        (uid, 1, equipe[0][0]["nom"]), (dele, 1, equipe[1][0]["nom"]),
        (id1, 2, ia1[0]["nom"]), (id2, 2, ia2[0]["nom"]),
    ])
    _inserer_equipe(combat_id, uid, equipe)
    database.initialiser_equipe_combat_pvp(combat_id, id1, ia1)
    database.initialiser_equipe_combat_pvp(combat_id, id2, ia2)
    for m in ia1:
        dresseurs_module._equiper_attaques_aleatoires(id1, m["nom"])
    for m in ia2:
        dresseurs_module._equiper_attaques_aleatoires(id2, m["nom"])

    sous = archetype.get("sous_noms", (archetype["nom"], archetype["nom"]))
    noms_sieges = {str(uid): pseudo, str(dele): f"{pseudo} (2)", str(id1): sous[0], str(id2): sous[1]}
    _q("INSERT INTO duo_web_meta (combat_id, joueur_id, archetype, noms) VALUES (?,?,?,?)",
       (combat_id, uid, archetype["nom"], json.dumps(noms_sieges, ensure_ascii=False)), ecrire=True)
    _q("INSERT OR REPLACE INTO duo_web_cooldown (user_id, date) VALUES (?, ?)", (uid, int(time.time())), ecrire=True)
    try:
        js = database.obtenir_joueurs_2v2(combat_id)
        await c2._jouer_tour_ia_2v2(combat_id, id1, js)
        await c2._jouer_tour_ia_2v2(combat_id, id2, js)
    except Exception:
        traceback.print_exc()
    return {"combat_id": combat_id}


# ----------------------------------------------------------------------------
# État
# ----------------------------------------------------------------------------
def _fiche(combat_id, siege_id, row, actif_nom, detail=True):
    out = {"nom": row["pokemon_nom"], "niveau": row["niveau"], "pv": row["pv_actuels"], "pv_max": row["pv_max"],
           "ko": row["pv_actuels"] <= 0, "actif": row["pokemon_nom"] == actif_nom}
    if out["actif"]:
        st = database.obtenir_statut(combat_id, siege_id, row["pokemon_nom"])
        out["statut"] = st[0] if st else None
        out["boosts"] = {k: v for k, v in database.obtenir_boosts(combat_id, siege_id, row["pokemon_nom"]).items() if v}
    return out


def _attaques(combat_id, j):
    charge = database.obtenir_charge(combat_id, j["user_id"], j["actif_nom"])
    if charge["attaque_en_charge"] or charge["doit_recharger"]:
        return {"verrouille": True, "attaques": []}
    equipees = database.obtenir_attaques_equipees(c2.controleur_reel(j["user_id"]), j["actif_nom"], combat_id=combat_id)
    res = []
    for slot in sorted(equipees):
        nom = equipees[slot]
        a = obtenir_attaque(nom)
        if not a:
            continue
        pm = pp_max_attaque(a)
        pp = database.obtenir_pp(combat_id, j["user_id"], j["actif_nom"], nom, pm)
        if pp > 0:
            res.append({"nom": nom, "type": a.get("type"), "puissance": a.get("puissance"), "precision": a.get("precision"), "pp": pp, "pp_max": pm})
    if not res:
        res = [{"nom": c2.NOM_LUTTE, "type": None, "puissance": None, "precision": None, "pp": None, "pp_max": None}]
    return {"verrouille": False, "attaques": res}


def _resultat_pour(res, uid):
    if not res:
        return None
    r = json.loads(res["resultat"])
    if isinstance(r, dict) and "par_joueur" in r:
        return r["par_joueur"].get(str(uid))
    return r


def _info_mega(combat_id, j, row):
    """(infos de la forme Méga, clé de pierre) si ce siège peut Méga-Évoluer, sinon None."""
    if database.a_deja_mega_evolue(combat_id, j["user_id"]) or row is None or row["pv_actuels"] <= 0:
        return None
    if j["actif_nom"] == "Rayquaza":
        req = mega_evolutions_module.MEGA_RAYQUAZA["attaque_requise"]
        equipees = database.obtenir_attaques_equipees(c2.controleur_reel(j["user_id"]), "Rayquaza", combat_id=combat_id)
        return (mega_evolutions_module.MEGA_RAYQUAZA, None) if req in equipees.values() else None
    objet = row["objet_tenu"]
    info = mega_evolutions_module.MEGA_EVOLUTIONS.get(objet) if objet else None
    return (info, objet) if info and info["espece"] == j["actif_nom"] else None


def _mega_possible(combat_id, j, row):
    r = _info_mega(combat_id, j, row)
    return {"forme": r[0]["forme_nom"]} if r else None


def _nettoyer(lignes, joueurs, noms):
    noms_ia = {j["user_id"]: noms.get(str(j["user_id"]), "Adversaire") for j in joueurs if j["user_id"] < 0}
    propre = c2._nettoyer_log_2v2(lignes, joueurs, noms_ia)
    reels = [k for k in noms if int(k) > 0]
    out = []
    for l in propre:
        for k in reels:
            l = l.replace(f"<@{k}>", f"**{noms[k]}**")
        out.append(_RE_EMOJI_DISCORD.sub(lambda m: f":{re.sub(r'^\d+', '', m.group(1))}:", l))
    return out


def journal(combat_id, depuis=0):
    rows = _q("SELECT tour, lignes FROM duo_web_journal WHERE combat_id = ? AND tour >= ? ORDER BY tour", (combat_id, depuis), un=False)
    return [{"tour": r["tour"], "lignes": json.loads(r["lignes"])} for r in rows]


def etat(combat_id: int, uid: int) -> dict:
    m = _meta(combat_id)
    _verifier_participant(m, uid)
    combat = database.obtenir_combat(combat_id)
    res = _q("SELECT resultat FROM duo_web_resultat WHERE combat_id = ?", (combat_id,))
    j2 = _j2(combat_id)
    nm0 = json.loads(m["noms"])
    adv_id = next((x for x in _reels(m) if x != uid), None)
    titre = f"Duel 2v2 contre {nm0.get(str(adv_id), 'un dresseur')}" if adv_id else m["archetype"]
    out = {"combat_id": combat_id, "pvp": bool(j2), "archetype": titre, "actif": bool(combat and combat["actif"]),
           "journal": journal(combat_id), "resultat": _resultat_pour(res, uid)}
    equipe = database.obtenir_equipe_pvp(combat_id, uid)
    if not out["actif"]:
        out["equipe"] = [{"nom": r["pokemon_nom"], "niveau": r["niveau"], "pv": r["pv_actuels"], "pv_max": r["pv_max"], "ko": r["pv_actuels"] <= 0} for r in equipe]
        return out
    noms = json.loads(m["noms"])
    joueurs = database.obtenir_joueurs_2v2(combat_id)
    choix_ko = {r["user_id"] for r in database.obtenir_choix_ko(combat_id)}
    out["tour"] = combat["tour"]
    out["secondes"] = max(0, combat["date_limite_tour"] - int(time.time()))
    out["equipe"] = [{"nom": r["pokemon_nom"], "niveau": r["niveau"], "pv": r["pv_actuels"], "pv_max": r["pv_max"], "ko": r["pv_actuels"] <= 0} for r in equipe]
    inv = database.obtenir_inventaire_balls(uid)
    util = max((j["potions_soin"] for j in joueurs if j["user_id"] == uid), default=0)
    sieges = []
    for cle in ("a", "b"):
        j = _siege(combat_id, uid, cle)
        row = c2._row_actif(combat_id, j["user_id"], j["actif_nom"])
        hors = c2._joueur_hors_combat(combat_id, j)
        dispo = {x["actif_nom"] for x in joueurs if x["equipe"] == j["equipe"] and x["user_id"] != j["user_id"]}
        s = {"cle": cle, "actif": _fiche(combat_id, j["user_id"], row, j["actif_nom"]) if row else None,
             "action_choisie": j["action"] is not None, "hors_combat": hors, "abandonne": bool(j["abandonne"]),
             "remplacant_requis": j["user_id"] in choix_ko,
             "changements": [r["pokemon_nom"] for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != j["actif_nom"] and r["pokemon_nom"] not in dispo]}
        if not hors and j["actif_nom"] and row and row["pv_actuels"] > 0:
            s.update(_attaques(combat_id, j))
            s["mega"] = _mega_possible(combat_id, j, row)
        sieges.append(s)
    out["sieges"] = sieges
    out["potions"] = {"disponibles": [{"type": k, "nom": NOM_SOIN_AFFICHAGE[k], "quantite": v} for k, v in inv.items()
                                      if k in NOM_SOIN_AFFICHAGE and v > 0 and (k == "totalsoin" or util < config.LIMITE_POTIONS_SOIN_COMBAT)],
                      "utilisees": util, "limite": config.LIMITE_POTIONS_SOIN_COMBAT}
    adv = []
    _, equipe_adv = _mon_equipe(combat_id, uid)
    for j in joueurs:
        if j["equipe"] != equipe_adv:
            continue
        eq = database.obtenir_equipe_pvp(combat_id, j["user_id"])
        row = c2._row_actif(combat_id, j["user_id"], j["actif_nom"])
        adv.append({"id": str(j["user_id"]), "nom": noms.get(str(j["user_id"])), "actif": _fiche(combat_id, j["user_id"], row, j["actif_nom"]) if row else None,
                    "restants": sum(1 for r in eq if r["pv_actuels"] > 0), "total": len(eq)})
    out["adverses"] = adv
    return out


# ----------------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------------
def _verifier_siege(combat_id, uid, cle):
    m = _meta(combat_id)
    _verifier_participant(m, uid)
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        raise ErreurCombatWeb("Ce combat est terminé.")
    j = _siege(combat_id, uid, cle)
    if j["abandonne"]:
        raise ErreurCombatWeb("Tu as abandonné ce combat.")
    if c2._joueur_hors_combat(combat_id, j):
        raise ErreurCombatWeb("Ce siège est hors combat.")
    if j["action"] is not None:
        raise ErreurCombatWeb("Ce Pokémon a déjà son action pour ce tour.")
    if any(r["user_id"] == j["user_id"] for r in database.obtenir_choix_ko(combat_id)):
        raise ErreurCombatWeb("Ce Pokémon est K.O. : choisis d'abord son remplaçant.")
    return j


def agir(combat_id: int, uid: int, cle: str, type_action: str, valeur: str = "", cible: str = "") -> dict:
    j = _verifier_siege(combat_id, uid, cle)
    sid = j["user_id"]
    if type_action == "attaque":
        att = _attaques(combat_id, j)
        if att["verrouille"]:
            raise ErreurCombatWeb("Ce Pokémon charge ou récupère : rien à choisir, l'attaque est automatique.")
        if valeur not in {a["nom"] for a in att["attaques"]}:
            raise ErreurCombatWeb("Attaque indisponible.")
        cibles = c2._cibles_vivantes(combat_id, database.obtenir_joueurs_2v2(combat_id), _mon_equipe(combat_id, uid)[1])
        if not cibles:
            raise ErreurCombatWeb("Plus aucune cible.")
        if len(cibles) == 1:
            cid = cibles[0][0]
        else:
            ids = {str(c[0]): c[0] for c in cibles}
            if cible not in ids:
                raise ErreurCombatWeb("Choisis une cible.")
            cid = ids[cible]
        action = f"attaque:{valeur}@{cid}"
    elif type_action == "potion":
        if valeur not in NOM_SOIN_AFFICHAGE:
            raise ErreurCombatWeb("Potion inconnue.")
        if valeur != "totalsoin" and j["potions_soin"] >= config.LIMITE_POTIONS_SOIN_COMBAT:
            raise ErreurCombatWeb(f"Limite de {config.LIMITE_POTIONS_SOIN_COMBAT} potions de soin atteinte.")
        if not database.retirer_ball(uid, valeur):
            raise ErreurCombatWeb("Tu n'as plus cette potion.")
        if not database.definir_action_2v2(combat_id, sid, f"potion:{valeur}"):
            database.ajouter_balls(uid, valeur, 1)
            raise ErreurCombatWeb("Action déjà posée.")
        if valeur != "totalsoin":
            database.incrementer_potions_2v2(combat_id, sid)
        return {"ok": True}
    elif type_action == "changer":
        if valeur not in {x for x in _siege_etat(combat_id, uid, cle)["changements"]}:
            raise ErreurCombatWeb("Changement impossible.")
        action = f"changer:{valeur}"
    else:
        raise ErreurCombatWeb("Action inconnue.")
    if not database.definir_action_2v2(combat_id, sid, action):
        raise ErreurCombatWeb("Action déjà posée.")
    return {"ok": True}


def mega_evoluer(combat_id: int, uid: int, cle: str) -> dict:
    """Méga-Évolution du Pokémon actif d'un siège (ne consomme pas l'action du tour).
    Une seule par combat et par joueur, comme sur Discord."""
    j = _verifier_siege(combat_id, uid, cle)
    row = c2._row_actif(combat_id, j["user_id"], j["actif_nom"])
    if row is None or row["pv_actuels"] <= 0:
        raise ErreurCombatWeb("Ce Pokémon est K.O. !")
    if database.a_deja_mega_evolue(combat_id, j["user_id"]):
        raise ErreurCombatWeb("Tu as déjà utilisé ta Méga-Évolution pour ce combat !")
    r = _info_mega(combat_id, j, row)
    if not r:
        raise ErreurCombatWeb(f"{j['actif_nom']} ne peut pas Méga-Évoluer (Pierre Méga compatible requise).")
    info, cle_stone = r
    ivs = database.obtenir_meilleures_ivs(uid, j["actif_nom"]) or IV_DEFAUT
    pokemon_mega = {"nom": info["forme_nom"], "types": info["types"], "stats_detaillees": info["stats_detaillees"]}
    stats = calculer_toutes_stats(pokemon_mega, ivs, row["niveau"])
    database.activer_mega_evolution_combat(combat_id, j["user_id"], row["position"], j["actif_nom"], stats, cle_stone=cle_stone)
    return {"ok": True, "message": f"{j['actif_nom']} Méga-Évolue en {info['forme_nom']} !"}


def _siege_etat(combat_id, uid, cle):
    return next(s for s in etat(combat_id, uid)["sieges"] if s["cle"] == cle)


def remplacant(combat_id: int, uid: int, cle: str, nom: str) -> dict:
    m = _meta(combat_id)
    _verifier_participant(m, uid)
    j = _siege(combat_id, uid, cle)
    s = _siege_etat(combat_id, uid, cle)
    if nom not in s["changements"]:
        raise ErreurCombatWeb("Remplaçant invalide.")
    ligne = next((r for r in database.obtenir_choix_ko(combat_id) if r["user_id"] == j["user_id"]), None)
    if ligne is None or not database.supprimer_choix_ko(combat_id, j["user_id"]):
        raise ErreurCombatWeb("Aucun remplaçant à choisir (ou envoi automatique déjà fait).")
    if ligne["relais"] and j["actif_nom"]:
        database.copier_boosts(combat_id, j["user_id"], j["actif_nom"], nom)
        database.reinitialiser_boosts(combat_id, j["user_id"], j["actif_nom"])
    database.definir_actif_2v2(combat_id, j["user_id"], nom)
    mini = [f"🔁 Tu envoies **{nom}** !"]
    c2._appliquer_hazards_entree(combat_id, j["user_id"], nom, mini)
    _ajouter_journal(combat_id, mini)
    return {"ok": True}


def _ajouter_journal(combat_id, lignes):
    c = database.obtenir_combat(combat_id)
    tour = c["tour"] if c else 0
    ex = _q("SELECT lignes FROM duo_web_journal WHERE combat_id = ? AND tour = ?", (combat_id, tour))
    base = json.loads(ex["lignes"]) if ex else []
    _q("INSERT OR REPLACE INTO duo_web_journal (combat_id, tour, lignes) VALUES (?,?,?)",
       (combat_id, tour, json.dumps(base + lignes, ensure_ascii=False)), ecrire=True)


def abandonner(combat_id: int, uid: int) -> dict:
    m = _meta(combat_id)
    _verifier_participant(m, uid)
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        raise ErreurCombatWeb("Ce combat est déjà terminé.")
    for j in _sieges_joueur(combat_id, uid):
        database.marquer_abandon_2v2(combat_id, j["user_id"])
        database.supprimer_choix_ko(combat_id, j["user_id"])
    return {"ok": True, "message": "🏳️ Tu as abandonné."}


# ----------------------------------------------------------------------------
# Résolution
# ----------------------------------------------------------------------------
def _recompense_joueur(uid, perdants, gagne, par_abandon):
    if gagne:
        mult = min([database.enregistrer_victoire_pvp_repetition(uid, p) for p in perdants] or [1.0])
        dollars = round(c2.DOLLARS_VICTOIRE * mult * database.multiplicateur_boost(uid, "argent"))
        database.ajouter_poke_dollars(uid, dollars)
        database.incrementer_victoires_pvp(uid)
        xp = round(c2.XP_VICTOIRE * mult)
        leveling.gagner_xp(uid, xp)
        if not par_abandon:
            database.incrementer_progression_quete(uid, "pvp_victoire")
        return {"dollars": dollars, "xp": round(xp * database.multiplicateur_boost(uid, "xp"))}
    leveling.gagner_xp(uid, c2.XP_DEFAITE)
    return {"dollars": 0, "xp": c2.XP_DEFAITE}


def _cloturer(combat_id, m, joueurs, gagnante, par_abandon, tour_log):
    database.terminer_combat_pvp(combat_id)
    reels = _reels(m)
    for u in reels:
        database.synchroniser_pv_persistant_depuis_combat(combat_id, u)
    par = {}
    for u in reels:
        mon_eq = next(j["equipe"] for j in joueurs if c2.controleur_reel(j["user_id"]) == u)
        gagne = mon_eq == gagnante
        perdants = [x for x in reels if x != u] or [j["user_id"] for j in joueurs if j["equipe"] != mon_eq]
        rec = _recompense_joueur(u, perdants, gagne, par_abandon)
        abandon = any(j["abandonne"] for j in joueurs if j["equipe"] == mon_eq) and not gagne
        par[str(u)] = {"issue": "abandon" if abandon else "victoire" if gagne else "defaite", "recompenses": rec}
    resultat = par[str(reels[0])] if len(reels) == 1 else {"par_joueur": par}
    _q("INSERT OR REPLACE INTO duo_web_resultat (combat_id, resultat) VALUES (?,?)", (combat_id, json.dumps(resultat)), ecrire=True)


async def tick(combat_id: int) -> dict:
    m = _meta(combat_id)
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return {"statut": "inactif"}
    noms = json.loads(m["noms"])
    if await c2.traiter_choix_ko_2v2(combat_id, None):
        return {"statut": "attente_remplacant"}
    joueurs = database.obtenir_joueurs_2v2(combat_id)

    def fin(js, log=None):
        for g, p in ((1, 2), (2, 1)):
            if c2._equipe_vaincue(combat_id, js, p):
                par_abandon = not c2._equipe_entierement_ko(combat_id, js, p)
                _cloturer(combat_id, m, js, g, par_abandon, log)
                return True
        return False

    if fin(joueurs):
        return {"statut": "termine"}
    for j in joueurs:
        if j["user_id"] < 0 and not j["abandonne"] and not c2._joueur_hors_combat(combat_id, j):
            await c2._jouer_tour_ia_2v2(combat_id, j["user_id"], joueurs)
    joueurs = database.obtenir_joueurs_2v2(combat_id)
    en_attente = []
    for j in joueurs:
        if j["abandonne"] or c2._joueur_hors_combat(combat_id, j) or j["action"] is not None:
            continue
        if j["actif_nom"]:
            ch = database.obtenir_charge(combat_id, j["user_id"], j["actif_nom"])
            if ch["attaque_en_charge"] or ch["doit_recharger"]:
                continue
        en_attente.append(j["user_id"])
    if en_attente and int(time.time()) < combat["date_limite_tour"]:
        return {"statut": "attente_joueur"}
    tour = combat["tour"]
    log = await c2.resoudre_tour_2v2(combat_id)
    joueurs = database.obtenir_joueurs_2v2(combat_id)
    propre = _nettoyer(log, joueurs, noms)
    _ajouter_journal_tour(combat_id, tour, propre)
    if fin(joueurs, propre):
        return {"statut": "termine", "tour": tour}
    database.vider_actions_2v2(combat_id)
    database.passer_tour_pvp(combat_id, int(time.time()) + c2.DUREE_TOUR_2V2)
    return {"statut": "tour_resolu", "tour": tour}


def _ajouter_journal_tour(combat_id, tour, lignes):
    ex = _q("SELECT lignes FROM duo_web_journal WHERE combat_id = ? AND tour = ?", (combat_id, tour))
    base = json.loads(ex["lignes"]) if ex else []
    _q("INSERT OR REPLACE INTO duo_web_journal (combat_id, tour, lignes) VALUES (?,?,?)",
       (combat_id, tour, json.dumps(base + lignes, ensure_ascii=False)), ecrire=True)


async def boucle(combat_id: int, intervalle: float = 2.0):
    echecs = 0
    while True:
        await asyncio.sleep(intervalle)
        try:
            res = await tick(combat_id)
            echecs = 0
            if res["statut"] in ("termine", "inactif"):
                return res
        except Exception:
            echecs += 1
            traceback.print_exc()
            if echecs >= 3:
                database.terminer_combat_pvp(combat_id)
                _q("INSERT OR REPLACE INTO duo_web_resultat (combat_id, resultat) VALUES (?,?)",
                   (combat_id, json.dumps({"issue": "annule", "recompenses": None})), ecrire=True)
                return {"statut": "annule"}
