"""rogue_service.py — Roguelike (mini-jeu indépendant) jouable sur le site.

Reprend le moteur de roguelike.py (génération de chemin, ennemis, dégâts, reliques,
salles) et les mêmes tables (roguelike_runs/equipe/combat/records) : une run lancée sur le
site compte pour le même classement et bloque le /roguelike Discord (une run active par
joueur). Comme sur Discord : aucune récompense liée au profil, permadeath, sans fin.
L'écran « en attente d'une décision » (que Discord garde dans un message) est stocké dans
la table rogue_web_etat.
"""

import json
import random

import config
import database
import roguelike as rl
from combat_service import ErreurCombatWeb
from pokemon_data import evoluer_si_possible, obtenir_pokemon_par_nom

NOMS_SALLES = {
    "combat": "⚔️ Combat", "tresor": "💰 Trésor", "repos": "🏕️ Repos", "evenement": "❓ Événement",
    "recrutement": "🧭 Recrutement", "marchand": "🛍️ Marchand", "mutation": "🔮 Autel de Mutation",
    "centre_pokemon": "🏥 Centre Pokémon",
}


def _init():
    conn = database.get_connexion()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS rogue_web_etat (joueur_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, ecran TEXT NOT NULL)")
        conn.commit()
    finally:
        conn.close()


def _pseudos():
    conn = database.get_connexion()
    try:
        return {r["user_id"]: r["pseudo"] for r in conn.execute("SELECT user_id, pseudo FROM web_joueurs")}
    except Exception:
        return {}
    finally:
        conn.close()


def _lire_ecran(uid):
    _init()
    conn = database.get_connexion()
    try:
        r = conn.execute("SELECT run_id, ecran FROM rogue_web_etat WHERE joueur_id = ?", (uid,)).fetchone()
    finally:
        conn.close()
    return (r["run_id"], json.loads(r["ecran"])) if r else (None, None)


def _ecrire(uid, run_id, ecran):
    _init()
    conn = database.get_connexion()
    try:
        conn.execute("INSERT OR REPLACE INTO rogue_web_etat (joueur_id, run_id, ecran) VALUES (?,?,?)", (uid, run_id, json.dumps(ecran, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def _continuer(uid, run_id, titre, texte):
    _ecrire(uid, run_id, {"type": "continuer", "titre": titre, "texte": texte})


def _reliques(run):
    return json.loads(run["reliques"])


def _run_actif(uid):
    run = database.obtenir_run_roguelike_actif(uid)
    if run is None:
        raise ErreurCombatWeb("Aucune run en cours.")
    rid, ecran = _lire_ecran(uid)
    if rid != run["id"] or ecran is None:
        raise ErreurCombatWeb("Cette run a été lancée sur Discord : continue-la là-bas ou abandonne-la ici.")
    return run, ecran


# ----------------------------------------------------------------------------
# Lecture
# ----------------------------------------------------------------------------
def _fiche_pokemon(nom, niveau=None, pv=None, pv_max=None):
    p = obtenir_pokemon_par_nom(nom) or {}
    return {"nom": nom, "niveau": niveau, "pv": pv, "pv_max": pv_max, "types": p.get("types", [])}


def etat(uid: int) -> dict:
    run = database.obtenir_run_roguelike_actif(uid)
    record = next((r["meilleur_etage"] for r in database.classement_roguelike(10000) if r["joueur_id"] == uid), None)
    out = {"record": record, "run": None, "ecran": None}
    rid, ecran = _lire_ecran(uid)
    if run is None:
        if ecran and ecran["type"] in ("fin", "abandon"):
            out["ecran"] = ecran
        return out
    if rid != run["id"] or ecran is None:
        out["discord"] = True
        out["run"] = {"salle": run["salle_index"] + 1}
        return out
    equipe = database.obtenir_equipe_roguelike(run["id"])
    out["run"] = {
        "salle": run["salle_index"] + 1,
        "equipe": [{"position": m["position"], "nom": m["pokemon_nom"], "niveau": m["niveau"], "pv": m["pv_actuels"], "pv_max": m["pv_max"],
                    "mute": m["bonus_mutation"] != 1.0, "types": (obtenir_pokemon_par_nom(m["pokemon_nom"]) or {}).get("types", [])} for m in equipe],
        "reliques": [{"id": r, **{k: rl.RELIQUES[r][k] for k in ("nom", "emoji", "description")}} for r in _reliques(run)],
    }
    ecran = dict(ecran)
    if ecran["type"] == "combat":
        c = database.obtenir_combat_roguelike(run["id"])
        if c:
            actif = next((m for m in equipe if m["position"] == c["actif_position"]), None)
            ecran["ennemi"] = _fiche_pokemon(c["ennemi_nom"], c["ennemi_niveau"], c["ennemi_pv_actuels"], c["ennemi_pv_max"])
            ecran["restants"] = len(json.loads(c["equipe_restante"]) if c["equipe_restante"] else [])
            ecran["actif"] = actif["position"] if actif else None
            ecran["attaques"] = [{"nom": a["nom"], "type": a["type"], "puissance": a["puissance"], "precision": a["precision"]}
                                 for a in rl._attaques_disponibles(actif["pokemon_nom"])] if actif else []
    elif ecran["type"] == "mutation":
        ecran["candidats"] = [m["position"] for m in equipe if m["bonus_mutation"] == 1.0 and m["pv_actuels"] > 0]
    elif ecran["type"] == "evolution":
        ecran["candidats"] = [m["position"] for m in equipe if m["pv_actuels"] > 0]
    elif ecran["type"] == "tresor":
        ecran["reliques"] = [{"id": r, **{k: rl.RELIQUES[r][k] for k in ("nom", "emoji", "description")}} for r in ecran["options"]]
    elif ecran["type"] == "carrefour":
        ecran["noms"] = {t: NOMS_SALLES.get(t, t) for t in ecran["options"]}
    out["ecran"] = ecran
    return out


# ----------------------------------------------------------------------------
# Démarrage / abandon
# ----------------------------------------------------------------------------
def demarrer(uid: int) -> dict:
    if database.obtenir_run_roguelike_actif(uid) is not None:
        raise ErreurCombatWeb("Tu as déjà une run en cours (abandonne-la pour en relancer une).")
    run_id = database.creer_run_roguelike(uid, rl._generer_chemin())
    cands = random.sample(rl.STARTERS_9_GENERATIONS, 6)
    _ecrire(uid, run_id, {"type": "starter", "titre": "🗺️ Choisis ton starter !", "texte": "Sélectionne le Pokémon avec lequel tu commences l'aventure.", "candidats": cands})
    return etat(uid)


def abandonner(uid: int) -> dict:
    run = database.obtenir_run_roguelike_actif(uid)
    if run is None:
        raise ErreurCombatWeb("Aucune run en cours.")
    database.terminer_run_roguelike(run["id"])
    _ecrire(uid, run["id"], {"type": "abandon", "titre": "Run abandonnée", "texte": "Tu peux en relancer une nouvelle."})
    return etat(uid)


def _conclure(uid, run_id, log=None):
    run = database.obtenir_run_roguelike(run_id)
    etage = run["salle_index"]
    database.terminer_run_roguelike(run_id)
    record = database.enregistrer_record_roguelike(uid, etage)
    _ecrire(uid, run_id, {"type": "fin", "titre": "💀 Fin de la run", "texte": f"Ton équipe est tombée à la salle {etage + 1}.", "etage": etage + 1,
                          "nouveau_record": record, "log": log or []})


# ----------------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------------
def agir(uid: int, action: str, valeur: str = "") -> dict:
    run, ecran = _run_actif(uid)
    rid = run["id"]
    t = ecran["type"]
    if action == "attaquer" and t == "combat":
        _attaquer(uid, run, valeur)
    elif action == "continuer" and t == "continuer":
        _entrer_salle(uid, rid)
    elif action == "starter" and t == "starter":
        if valeur not in ecran["candidats"]:
            raise ErreurCombatWeb("Starter invalide.")
        niveau = config.ROGUELIKE_NIVEAU_DEPART
        database.ajouter_membre_equipe_roguelike(rid, valeur, niveau, rl._generer_stats(valeur, niveau)["pv"])
        _continuer(uid, rid, "🗺️ L'aventure commence !", f"**{valeur}** rejoint l'aventure ! Le chemin s'étend sans fin, avec un boss à intervalles réguliers. Combien d'étages peux-tu atteindre ?")
    elif action == "evenement" and t == "evenement":
        ev = rl.EVENEMENTS[ecran["index"]]
        try:
            effet = ev["choix"][int(valeur)][1]
        except (ValueError, IndexError):
            raise ErreurCombatWeb("Choix invalide.")
        _continuer(uid, rid, ev["titre"], rl._resoudre_effet_evenement(rid, effet))
    elif action == "relique" and t == "tresor":
        if valeur not in ecran["options"]:
            raise ErreurCombatWeb("Relique invalide.")
        _continuer(uid, rid, *_accorder(rid, valeur))
    elif action == "recruter" and t == "recrutement":
        if valeur == "passer":
            _continuer(uid, rid, "🧭 Recrutement décliné", "Tu gardes ton équipe actuelle.")
        else:
            if valeur not in ecran["options"]:
                raise ErreurCombatWeb("Candidat invalide.")
            niveau = rl._niveau_pour_etage(run["salle_index"])
            database.ajouter_membre_equipe_roguelike(rid, valeur, niveau, rl._generer_stats(valeur, niveau)["pv"])
            _continuer(uid, rid, "🧭 Nouveau coéquipier !", f"**{valeur}** (Niv. {niveau}) rejoint ton équipe !")
    elif action == "marchand" and t == "marchand":
        if valeur == "soin":
            database.soigner_equipe_roguelike(rid, 0.40)
            _continuer(uid, rid, "🛍️ Marchand", "Ton équipe récupère 40 % de ses PV.")
        elif valeur == "relique":
            dispo = [r for r in rl.RELIQUES if r not in _reliques(run)]
            if not dispo:
                _continuer(uid, rid, "🛍️ Marchand", "Tu as déjà toutes les reliques ! Rien à t'offrir ici.")
            else:
                _continuer(uid, rid, *_accorder(rid, random.choice(dispo)))
        else:
            raise ErreurCombatWeb("Choix invalide.")
    elif action == "muter" and t == "mutation":
        pos = int(valeur or -1)
        eq = database.obtenir_equipe_roguelike(rid)
        m = next((x for x in eq if x["position"] == pos and x["bonus_mutation"] == 1.0 and x["pv_actuels"] > 0), None)
        if m is None:
            raise ErreurCombatWeb("Pokémon invalide.")
        database.definir_mutation_membre_roguelike(rid, pos, 1.20)
        st = rl._appliquer_bonus_mutation(rl._generer_stats(m["pokemon_nom"], m["niveau"]), 1.20)
        ratio = m["pv_actuels"] / m["pv_max"] if m["pv_max"] > 0 else 0
        database.mettre_a_jour_niveau_membre_roguelike(rid, pos, m["niveau"], st["pv"], max(1, round(st["pv"] * ratio)))
        _continuer(uid, rid, "🔮 Mutation accomplie !", f"**{m['pokemon_nom']}** reçoit +20 % à toutes ses statistiques pour le reste de la run !")
    elif action == "evoluer" and t == "evolution":
        pos = int(valeur or -1)
        m = next((x for x in database.obtenir_equipe_roguelike(rid) if x["position"] == pos and x["pv_actuels"] > 0), None)
        if m is None:
            raise ErreurCombatWeb("Pokémon invalide.")
        niv = min(100, m["niveau"] + 5)
        nom_final, chaine = evoluer_si_possible(m["pokemon_nom"], niv)
        st = rl._appliquer_bonus_mutation(rl._generer_stats(nom_final, niv), m["bonus_mutation"])
        ratio = m["pv_actuels"] / m["pv_max"] if m["pv_max"] > 0 else 0
        database.mettre_a_jour_niveau_membre_roguelike(rid, pos, niv, st["pv"], max(1, round(st["pv"] * ratio)), pokemon_nom=nom_final if chaine else None)
        texte = f"**{m['pokemon_nom']}** grimpe à Niv. {niv} !" + (f" ✨ Il évolue en **{nom_final}** !" if chaine else "")
        _continuer(uid, rid, "🧬 Chambre d'Évolution", texte)
    elif action == "carrefour" and t == "carrefour":
        if valeur not in ecran["options"]:
            raise ErreurCombatWeb("Chemin invalide.")
        chemin = json.loads(run["chemin"])
        suivant = run["salle_index"] + 1
        if suivant < len(chemin) - 1:
            chemin[suivant] = valeur
        else:
            chemin.insert(suivant, valeur)  # ne jamais écraser le boss final du segment
        database.mettre_a_jour_chemin_roguelike(rid, chemin)
        _continuer(uid, rid, "🧭 Chemin choisi !", f"Tu t'engages vers : **{NOMS_SALLES.get(valeur, valeur)}**")
    elif action == "combattre" and t == "scintillante":
        _lancer_combat(uid, run, elite=True, speciale=True)
    elif action == "fuir" and t == "scintillante":
        _continuer(uid, rid, "🏃 Tu t'éloignes prudemment...", "Aucun risque, aucune récompense — le Pokémon scintillant disparaît.")
    elif action == "parier" and t == "arene":
        if valeur not in (ecran["a"], ecran["b"]):
            raise ErreurCombatWeb("Pari invalide.")
        vainqueur = random.choice([ecran["a"], ecran["b"]])
        eq = database.obtenir_equipe_roguelike(rid)
        if valeur == vainqueur and len(eq) < config.ROGUELIKE_TAILLE_EQUIPE_MAX:
            niv = rl._niveau_pour_etage(run["salle_index"])
            database.ajouter_membre_equipe_roguelike(rid, vainqueur, niv, rl._generer_stats(vainqueur, niv)["pv"])
            texte = f"🎉 **{vainqueur}** l'emporte, comme parié ! Il rejoint ton équipe."
        elif valeur == vainqueur:
            texte = f"🎉 **{vainqueur}** l'emporte comme prévu, mais ton équipe est complète — il s'éloigne."
        else:
            texte = f"😬 **{vainqueur}** l'emporte, pas **{valeur}**. Ton pari ne paie pas."
        _continuer(uid, rid, "🎤 Arène clandestine — Résultat", texte)
    else:
        raise ErreurCombatWeb("Action impossible à ce stade.")
    return etat(uid)


def _accorder(run_id, relique_id):
    database.ajouter_relique_roguelike(run_id, relique_id)
    if relique_id == "carapace_solide":
        conn = database.get_connexion()
        try:
            for m in database.obtenir_equipe_roguelike(run_id):
                nv = round(m["pv_max"] * 1.2)
                conn.execute("UPDATE roguelike_equipe SET pv_max = ?, pv_actuels = pv_actuels + ? WHERE run_id = ? AND position = ?",
                             (nv, nv - m["pv_max"], run_id, m["position"]))
            conn.commit()
        finally:
            conn.close()
    i = rl.RELIQUES[relique_id]
    return f"{i['emoji']} Relique obtenue : {i['nom']}", i["description"]


# ----------------------------------------------------------------------------
# Salles
# ----------------------------------------------------------------------------
def _entrer_salle(uid, run_id):
    run = database.obtenir_run_roguelike(run_id)
    chemin = json.loads(run["chemin"])
    idx = database.avancer_salle_roguelike(run_id)
    if idx >= len(chemin):
        chemin = chemin + rl._generer_chemin()
        database.mettre_a_jour_chemin_roguelike(run_id, chemin)
    attendu = min(100, rl._niveau_pour_etage(idx) + chemin[:idx].count("boss"))
    annonces = []
    for m in database.obtenir_equipe_roguelike(run_id):
        if m["niveau"] >= attendu:
            continue
        nom_final, chaine = evoluer_si_possible(m["pokemon_nom"], attendu)
        if chaine:
            annonces.append(f"✨ {m['pokemon_nom']} a évolué en {nom_final} !")
        st = rl._appliquer_bonus_mutation(rl._generer_stats(nom_final, attendu), m["bonus_mutation"])
        ratio = m["pv_actuels"] / m["pv_max"] if m["pv_max"] > 0 else 0
        pv = max(1, round(st["pv"] * ratio)) if m["pv_actuels"] > 0 else 0
        database.mettre_a_jour_niveau_membre_roguelike(run_id, m["position"], attendu, st["pv"], pv, pokemon_nom=nom_final if chaine else None)
    run = database.obtenir_run_roguelike(run_id)
    n = idx + 1
    salle = chemin[idx]
    pre = "\n".join(annonces)

    def ec(**kw):
        kw.setdefault("annonces", annonces)
        _ecrire(uid, run_id, kw)

    if salle in ("combat", "elite", "boss"):
        _lancer_combat(uid, run, elite=salle == "elite", boss=salle == "boss", annonces=annonces)
    elif salle == "repos":
        database.soigner_equipe_roguelike(run_id, config.ROGUELIKE_SOIN_REPOS_POURCENT)
        ec(type="continuer", titre=f"🏕️ Salle {n} — Un lieu de repos", texte=f"Ton équipe récupère {round(config.ROGUELIKE_SOIN_REPOS_POURCENT * 100)} % de ses PV.")
    elif salle == "evenement":
        i = random.randrange(len(rl.EVENEMENTS))
        ev = rl.EVENEMENTS[i]
        ec(type="evenement", titre=f"{ev['titre']}", texte=ev["texte"], index=i, choix=[c[0] for c in ev["choix"]])
    elif salle == "tresor":
        dispo = [r for r in rl.RELIQUES if r not in _reliques(run)]
        if not dispo:
            database.soigner_equipe_roguelike(run_id, 0.25)
            ec(type="continuer", titre=f"💰 Salle {n} — Trésor", texte="Tu as déjà toutes les reliques ! +25 % PV à la place.")
        else:
            ec(type="tresor", titre=f"💰 Salle {n} — Trésor", texte="Choisis une relique :", options=random.sample(dispo, min(3, len(dispo))))
    elif salle == "recrutement":
        eq = database.obtenir_equipe_roguelike(run_id)
        if len(eq) >= config.ROGUELIKE_TAILLE_EQUIPE_MAX:
            database.soigner_equipe_roguelike(run_id, 0.20)
            ec(type="continuer", titre=f"🧭 Salle {n} — Recrutement", texte="Ton équipe est au complet ! +20 % PV à la place.")
        else:
            deja = {m["pokemon_nom"] for m in eq}
            cands = [x for x in rl.ENNEMIS_FAIBLE + rl.ENNEMIS_MOYEN if x not in deja]
            ec(type="recrutement", titre=f"🧭 Salle {n} — Recrutement", texte="Un Pokémon errant souhaite se joindre à toi.", options=random.sample(cands, min(3, len(cands))))
    elif salle == "marchand":
        ec(type="marchand", titre=f"🛍️ Salle {n} — Marchand", texte="Un marchand itinérant te propose un choix :")
    elif salle == "mutation":
        eq = database.obtenir_equipe_roguelike(run_id)
        if not [m for m in eq if m["bonus_mutation"] == 1.0 and m["pv_actuels"] > 0]:
            database.soigner_equipe_roguelike(run_id, 0.20)
            ec(type="continuer", titre=f"🔮 Salle {n} — Autel de Mutation", texte="Tous tes Pokémon vivants sont déjà mutés ! +20 % PV à la place.")
        else:
            ec(type="mutation", titre=f"🔮 Salle {n} — Autel de Mutation", texte="Choisis UN Pokémon pour +20 % à toutes ses stats (PV inclus) jusqu'à la fin de la run.")
    elif salle == "rencontre_scintillante":
        ec(type="scintillante", titre=f"✨ Salle {n} — Rencontre scintillante", texte="Un Pokémon aux couleurs éclatantes, bien plus fort que la normale. Une victoire garantit une relique bonus. Tu peux aussi fuir.")
    elif salle == "carrefour":
        ec(type="carrefour", titre=f"🧭 Salle {n} — Carrefour", texte="Trois chemins s'offrent à toi.", options=random.sample(rl.TYPES_CARREFOUR, 3))
    elif salle == "arene_clandestine":
        pool = rl._pool_ennemis_pour_etage(idx)
        a, b = random.sample(pool, 2)
        ec(type="arene", titre=f"🎤 Salle {n} — Arène clandestine", texte=f"**{a}** affronte **{b}**. Parie sur le vainqueur : il rejoindra ton équipe s'il y a de la place.", a=a, b=b)
    elif salle == "chambre_evolution":
        ec(type="evolution", titre=f"🧬 Salle {n} — Chambre d'Évolution", texte="Choisis UN Pokémon : +5 niveaux immédiats (évolution si le seuil est atteint).")
    elif salle == "centre_pokemon":
        database.soigner_equipe_roguelike(run_id, 1.0)
        ec(type="continuer", titre=f"🏥 Salle {n} — Centre Pokémon", texte="Équipe soignée intégralement, K.O. inclus !")
    elif salle == "dresseur":
        _lancer_dresseur(uid, run, annonces)


def _lancer_combat(uid, run, elite=False, boss=False, speciale=False, annonces=None):
    rid = run["id"]
    ennemi = rl._tirer_ennemi(run["salle_index"], elite=elite, boss=boss)
    premier = next((m for m in database.obtenir_equipe_roguelike(rid) if m["pv_actuels"] > 0), None)
    if premier is None:
        return _conclure(uid, rid)
    database.creer_combat_roguelike(rid, ennemi["nom"], ennemi["niveau"], ennemi["pv_max"], premier["position"], est_rencontre_speciale=speciale)
    pre = "👑 BOSS" if boss else "✨ Scintillant" if speciale else "⭐ Élite" if elite else "⚔️ Combat"
    _ecrire(uid, rid, {"type": "combat", "titre": f"{pre} — {ennemi['nom']} sauvage !", "texte": "", "log": [], "annonces": annonces or []})


def _lancer_dresseur(uid, run, annonces):
    rid, idx = run["id"], run["salle_index"]
    nom = random.choice(rl.NOMS_DRESSEURS)
    taille = 2 if idx <= 7 else 3 if idx <= config.ROGUELIKE_SALLE_DRESSEUR_4EME_POKEMON else 4
    pool = rl._pool_ennemis_pour_etage(idx)
    noms = random.sample(pool, min(taille, len(pool)))
    niv = rl._niveau_pour_etage(idx)
    mult = rl._multiplicateur_total_ennemi(idx, est_dresseur=True)
    premier = next((m for m in database.obtenir_equipe_roguelike(rid) if m["pv_actuels"] > 0), None)
    if premier is None:
        return _conclure(uid, rid)
    reste = [{"nom": n, "niveau": niv, "pv_max": round(rl._generer_stats(n, niv)["pv"] * mult)} for n in noms[1:]]
    database.creer_combat_roguelike(rid, noms[0], niv, round(rl._generer_stats(noms[0], niv)["pv"] * mult), premier["position"], equipe_restante=reste, est_dresseur=True)
    _ecrire(uid, rid, {"type": "combat", "titre": f"🥊 {nom} veut se battre ! ({len(noms)} Pokémon)", "texte": "", "log": [], "annonces": annonces})


# ----------------------------------------------------------------------------
# Combat
# ----------------------------------------------------------------------------
def _attaquer(uid, run, valeur):
    rid = run["id"]
    combat = database.obtenir_combat_roguelike(rid)
    if combat is None:
        raise ErreurCombatWeb("Aucun combat en cours.")
    equipe = database.obtenir_equipe_roguelike(rid)
    actif = next((m for m in equipe if m["position"] == combat["actif_position"]), None)
    if actif is None or actif["pv_actuels"] <= 0:
        raise ErreurCombatWeb("Ton Pokémon actif est K.O. !")
    attaques = rl._attaques_disponibles(actif["pokemon_nom"])
    try:
        attaque = attaques[int(valeur)]
    except (ValueError, IndexError):
        raise ErreurCombatWeb("Attaque invalide.")
    _, ecran = _lire_ecran(uid)
    reliques = _reliques(run)
    m_deg = 1.15 if "griffes_aiguisees" in reliques else 1.0
    m_red = 0.85 if "peau_de_fer" in reliques else 1.0
    malus = 10 if "amulette_trouble" in reliques else 0
    stats_j = rl._appliquer_bonus_mutation(rl._generer_stats(actif["pokemon_nom"], actif["niveau"]), actif["bonus_mutation"])
    mult = rl._multiplicateur_total_ennemi(run["salle_index"], est_dresseur=bool(combat["est_dresseur"]))
    stats_e = rl._appliquer_bonus_mutation(rl._generer_stats(combat["ennemi_nom"], combat["ennemi_niveau"]), mult)
    tj = (obtenir_pokemon_par_nom(actif["pokemon_nom"]) or {"types": ["normal"]})["types"]
    te = (obtenir_pokemon_par_nom(combat["ennemi_nom"]) or {"types": ["normal"]})["types"]
    log = []
    pv_e, pv_j = combat["ennemi_pv_actuels"], actif["pv_actuels"]

    def tour_joueur():
        nonlocal pv_e
        d, multi, ok = rl._appliquer_degats(stats_j, stats_e, attaque, tj, te, m_deg)
        if not ok:
            log.append(f"{actif['pokemon_nom']} utilise {attaque['nom']}... et rate !")
            return
        pv_e = max(0, pv_e - d)
        database.definir_pv_ennemi_roguelike(rid, pv_e)
        log.append(f"{actif['pokemon_nom']} utilise {attaque['nom']} → -{d} PV")
        if rl._texte_efficacite(multi):
            log.append("  " + rl._texte_efficacite(multi))
        if pv_e <= 0:
            log.append(f"  💀 {combat['ennemi_nom']} est vaincu !")

    def tour_ennemi():
        nonlocal pv_j
        a = random.choice(rl._attaques_disponibles(combat["ennemi_nom"]))
        a2 = dict(a, precision=max(10, a.get("precision", 100) - malus))
        d, multi, ok = rl._appliquer_degats(stats_e, stats_j, a2, te, tj, m_red)
        if not ok:
            log.append(f"{combat['ennemi_nom']} utilise {a['nom']}... et rate !")
            return
        pv_j = max(0, pv_j - d)
        database.definir_pv_roguelike(rid, actif["position"], pv_j)
        log.append(f"{combat['ennemi_nom']} utilise {a['nom']} → -{d} PV")
        if rl._texte_efficacite(multi):
            log.append("  " + rl._texte_efficacite(multi))
        if pv_j <= 0:
            log.append(f"  💀 {actif['pokemon_nom']} est K.O. !")

    if "instinct_predateur" in reliques or stats_j["vitesse"] >= stats_e["vitesse"]:
        tour_joueur()
        if pv_e > 0:
            tour_ennemi()
    else:
        tour_ennemi()
        if pv_j > 0:
            tour_joueur()

    base = {"type": "combat", "titre": ecran["titre"], "texte": "", "annonces": []}
    if pv_e <= 0:
        reste = json.loads(combat["equipe_restante"]) if combat["equipe_restante"] else []
        if reste:
            prochain = reste.pop(0)
            database.avancer_ennemi_suivant_roguelike(rid, prochain["nom"], prochain["niveau"], prochain["pv_max"], reste)
            log.append(f"🥊 Le dresseur envoie {prochain['nom']} ! (Niv. {prochain['niveau']})")
            _ecrire(uid, rid, {**base, "log": log})
            return
        database.terminer_combat_roguelike(rid)
        if "regeneration" in reliques:
            database.soigner_equipe_roguelike(rid, 0.08)
        if combat["est_dresseur"]:
            database.soigner_equipe_roguelike(rid, 0.15)
        texte = "\n".join(log)
        if combat["est_rencontre_speciale"]:
            dispo = [r for r in rl.RELIQUES if r not in reliques]
            if dispo:
                t, d = _accorder(rid, random.choice(dispo))
                texte += f"\n{t} — {d}"
        _ecrire(uid, rid, {"type": "continuer", "titre": "🏆 Victoire !", "texte": texte})
        return
    if pv_j <= 0:
        eq = database.obtenir_equipe_roguelike(rid)
        vivants = [m for m in eq if m["pv_actuels"] > 0]
        if not vivants and "sauvegarde_ultime" in reliques:
            surv = eq[0]
            database.definir_pv_roguelike(rid, surv["position"], 1)
            reliques.remove("sauvegarde_ultime")
            conn = database.get_connexion()
            try:
                conn.execute("UPDATE roguelike_runs SET reliques = ? WHERE id = ?", (json.dumps(reliques), rid))
                conn.commit()
            finally:
                conn.close()
            log.append(f"✨ Sauvegarde Ultime — {surv['pokemon_nom']} s'accroche avec 1 PV !")
            vivants = [surv]
        if not vivants:
            return _conclure(uid, rid, log)
        database.definir_actif_position_roguelike(rid, vivants[0]["position"])
        log.append(f"🔁 {vivants[0]['pokemon_nom']} entre au combat !")
    _ecrire(uid, rid, {**base, "log": log})


def classement(uid: int) -> dict:
    p = _pseudos()
    return {"classement": [{"rang": i + 1, "pseudo": p.get(r["joueur_id"]) or f"Dresseur #{str(r['joueur_id'])[-4:]}", "etage": r["meilleur_etage"], "moi": r["joueur_id"] == uid}
                           for i, r in enumerate(database.classement_roguelike(20))]}
