"""combat_service.py — combats de dresseurs (PvE) SANS Discord.

Étape 1 du portage navigateur de PokéWild. Ce module est un fichier NEUF : il ne modifie
rien dans combat.py / dresseurs.py (le bot Discord de prod reste strictement identique).
Il réutilise tel quel le moteur de combat existant :

  * combat.resoudre_tour(combat_id)       -> résolution d'un tour (2000 lignes, sans Discord)
  * combat.verifier_fin_combat(...)       -> détection de la fin du combat
  * combat.traiter_choix_ko(None, id, None) -> envoi auto du remplaçant après un K.O.
  * dresseurs._jouer_tour_ia(...)         -> choix d'action de l'IA
  * database.*                            -> TOUT l'état du combat vit en base

et ne remplace que la couche d'interface (fils, boutons, embeds) par des fonctions
qui renvoient / acceptent des dicts JSON, prêtes à être exposées par une API web.

Les règles de validation (tour déjà joué, PP, limite de potions, conditions de la
Méga-Évolution, choix du remplaçant...) reproduisent celles des vues Discord de
combat.py (VueActionCombat & sous-menus). Les récompenses de victoire reproduisent la
branche « dresseur classique » de dresseurs._tick_resolution_dresseur.

Tables ajoutées (créées à la demande, sans toucher aux tables existantes) :
  * combat_web_meta    : un combat lancé par le web (archétype, PC cible, nom du joueur)
  * combat_web_journal : journal de chaque tour (le moteur le renvoie, il n'est pas stocké)
  * combat_web_resultat: issue du combat (victoire/défaite/abandon + récompenses), lue par l'écran

⚠️ main.py (nettoyer_etats_orphelins_au_demarrage) clôture TOUS les combats actifs à
chaque redémarrage du bot Discord. Pour que les combats web y survivent, ajouter dans
cette boucle, juste après `for row in database.obtenir_combats_pvp_actifs():` :
    if combat_service.est_combat_web(row["id"]):
        continue
(et `import combat_service` en haut de main.py).
"""

import asyncio
import json
import random
import re
import time
import traceback

import combat as combat_module
import config
import database
import dresseurs as dresseurs_module
import leveling
import mega_evolutions as mega_evolutions_module
from pokemon_data import (
    ATTAQUE_DEFAUT_NOM,
    IV_DEFAUT,
    NOM_SOIN_AFFICHAGE,
    calculer_toutes_stats,
    obtenir_attaque,
    pp_max_attaque,
)


class ErreurCombatWeb(Exception):
    """Erreur « métier » lisible par le joueur (à renvoyer en HTTP 400 côté API)."""


# ----------------------------------------------------------------------------
# Tables propres au web
# ----------------------------------------------------------------------------

_tables_pretes = False


def _init_tables():
    global _tables_pretes
    if _tables_pretes:
        return
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_web_meta (
            combat_id INTEGER PRIMARY KEY,
            joueur_id INTEGER NOT NULL,
            id_adversaire INTEGER NOT NULL,
            archetype_nom TEXT NOT NULL,
            pc_cible INTEGER NOT NULL,
            nom_joueur TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_web_journal (
            combat_id INTEGER NOT NULL,
            tour INTEGER NOT NULL,
            lignes TEXT NOT NULL,
            PRIMARY KEY (combat_id, tour)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_web_resultat (
            combat_id INTEGER PRIMARY KEY,
            resultat TEXT NOT NULL
        )
        """
    )
    for colonne in ("mode TEXT DEFAULT 'dresseur'", "contexte TEXT"):
        try:
            cur.execute(f"ALTER TABLE combat_web_meta ADD COLUMN {colonne}")
        except Exception:
            pass  # colonne déjà présente
    conn.commit()
    conn.close()
    _tables_pretes = True


def _meta(combat_id: int):
    _init_tables()
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM combat_web_meta WHERE combat_id = ?", (combat_id,))
    row = cur.fetchone()
    conn.close()
    return row


def est_combat_web(combat_id: int) -> bool:
    return _meta(combat_id) is not None


def combats_web_actifs() -> list:
    """IDs des combats web encore actifs — à relancer (boucle_combat) au démarrage du
    serveur web : tout l'état est en base, un combat survit donc à un redémarrage."""
    _init_tables()
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT m.combat_id FROM combat_web_meta m JOIN combat_pvp c ON c.id = m.combat_id WHERE c.actif = 1"
    )
    ids = [r["combat_id"] for r in cur.fetchall()]
    conn.close()
    return ids


_RE_EMOJI_DISCORD = re.compile(r"<a?:(\w+):\d+>")


def _nettoyer_log(lignes: list, meta) -> list:
    """Remplace les mentions Discord (<@id>) par des noms, et les emojis personnalisés
    Discord (<:nom:id>), illisibles hors Discord, par leur nom."""
    mention_joueur = f"<@{meta['joueur_id']}>"
    mention_adversaire = f"<@{meta['id_adversaire']}>"
    propre = []
    for ligne in lignes:
        ligne = ligne.replace(mention_joueur, f"**{meta['nom_joueur']}**")
        ligne = ligne.replace(mention_adversaire, f"**{meta['archetype_nom']}**")
        # Le nom d'un emoji custom commence souvent par un identifiant numérique
        # (ex: 66792watertype) : on le retire pour garder un jeton lisible (:watertype:).
        ligne = _RE_EMOJI_DISCORD.sub(lambda m: f":{re.sub(r'^\d+', '', m.group(1))}:", ligne)
        propre.append(ligne)
    return propre


# ----------------------------------------------------------------------------
# Démarrage d'un combat
# ----------------------------------------------------------------------------

def _archetype_par_nom(nom: str | None) -> dict:
    if nom is None:
        return random.choice(dresseurs_module.ARCHETYPES)
    for a in dresseurs_module.ARCHETYPES:
        if a["nom"] == nom:
            return a
    raise ErreurCombatWeb(f"Dresseur inconnu : {nom}.")


def archetypes_disponibles() -> list:
    return [
        {"nom": a["nom"], "emoji": a["emoji"], "tier": a["tier"], "sprite": a.get("sprite"), "types": a["types_theme"]}
        for a in dresseurs_module.ARCHETYPES
    ]


async def demarrer_combat_dresseur(
    user_id: int, nom_joueur: str = "Dresseur", archetype_nom: str | None = None, multiplicateur_pc: float = 1.0,
    archetype_direct: dict | None = None, mode: str = "dresseur", contexte: dict | None = None,
) -> dict:
    """Lance un combat contre un dresseur (solo) pour un joueur du web. Même mise en
    place que dresseurs.demarrer_combat_dresseur, sans fil ni message Discord."""
    _init_tables()
    if database.combat_en_cours_pour_joueur(user_id):
        raise ErreurCombatWeb("Tu es déjà en combat !")

    archetype = archetype_direct or _archetype_par_nom(archetype_nom)

    pc_cible = round(dresseurs_module._pc_cumule_equipe(user_id) * multiplicateur_pc)
    if pc_cible <= 0:
        pc_cible = 500
    niveau_reference = dresseurs_module._niveau_moyen_equipe(user_id)
    niveau_max_equipe = dresseurs_module._niveau_max_equipe(user_id)
    equipe_dresseur = dresseurs_module.generer_equipe_dresseur(
        archetype, pc_cible, niveau_reference, niveau_max_equipe
    )

    noms_joueur = database.obtenir_equipe_combat_disponible(user_id)
    especes_possedees = {row["pokemon_nom"] for row in database.obtenir_pokedex_joueur(user_id)}
    equipe_joueur = []
    for nom in noms_joueur:
        if nom not in especes_possedees:
            continue
        stats = combat_module.stats_combattant_reel(user_id, nom)
        pv_actuels = database.obtenir_pv_actuels(user_id, nom, stats["pv"])
        equipe_joueur.append((stats, pv_actuels))
    vivants = [(s, pv) for s, pv in equipe_joueur if pv > 0]
    if not vivants:
        raise ErreurCombatWeb(
            "Toute ton équipe est K.O. (PV persistants à 0) ! Soigne-la avant de défier un dresseur."
        )

    date_limite = int(time.time()) + combat_module.DUREE_TOUR
    combat_id = database.creer_combat(user_id, 0, vivants[0][0]["nom"], equipe_dresseur[0]["nom"], date_limite)
    id_adversaire = dresseurs_module.ID_DRESSEUR_BASE - combat_id
    database.definir_adversaire_combat(combat_id, id_adversaire)

    # Équipe du joueur : mêmes colonnes que dresseurs.demarrer_combat_dresseur
    # (capacité + objet tenu repris de la meilleure capture).
    conn = database.get_connexion()
    cur = conn.cursor()
    for i, (stats, pv_actuels) in enumerate(equipe_joueur):
        if pv_actuels <= 0:
            continue
        cur.execute(
            "SELECT capacite, objet_tenu FROM captures WHERE user_id = ? AND pokemon_nom = ? ORDER BY pc DESC LIMIT 1",
            (user_id, stats["nom"]),
        )
        src = cur.fetchone()
        cur.execute(
            """
            INSERT INTO combat_equipe
                (combat_id, user_id, pokemon_nom, pv_max, pv_actuels, position, atq, defe, atq_spe, def_spe, vit, niveau, capacite, objet_tenu)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                combat_id, user_id, stats["nom"], stats["pv"], pv_actuels, i,
                stats["attaque"], stats["defense"], stats["attaque_spe"], stats["defense_spe"], stats["vitesse"],
                stats["niveau"], src["capacite"] if src else None, src["objet_tenu"] if src else None,
            ),
        )
    cur.execute(
        "INSERT INTO combat_web_meta (combat_id, joueur_id, id_adversaire, archetype_nom, pc_cible, nom_joueur, mode, contexte) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (combat_id, user_id, id_adversaire, archetype["nom"], pc_cible, nom_joueur, mode,
         json.dumps(contexte or {}, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    database.initialiser_equipe_combat_pvp(combat_id, id_adversaire, equipe_dresseur)
    for mon in equipe_dresseur:
        dresseurs_module._equiper_attaques_aleatoires(id_adversaire, mon["nom"])

    # L'IA joue immédiatement son 1er tour (même filet de secours que sur Discord).
    try:
        await dresseurs_module._jouer_tour_ia(combat_id, id_adversaire)
    except Exception:
        traceback.print_exc()
        database.enregistrer_action_pvp(combat_id, id_adversaire, f"attaque:{combat_module.NOM_LUTTE}")

    return {
        "combat_id": combat_id,
        "adversaire": {"nom": archetype["nom"], "emoji": archetype.get("emoji", "⚔️"), "sprite": archetype.get("sprite")},
    }


# ----------------------------------------------------------------------------
# État du combat (lecture seule, JSON)
# ----------------------------------------------------------------------------

def _ctx(combat_id: int, user_id: int):
    combat = database.obtenir_combat(combat_id)
    if not combat:
        raise ErreurCombatWeb("Combat introuvable.")
    if user_id not in (combat["joueur1_id"], combat["joueur2_id"]):
        raise ErreurCombatWeb("Tu n'es pas un des combattants !")
    adversaire_id = combat["joueur2_id"] if user_id == combat["joueur1_id"] else combat["joueur1_id"]
    actif_moi = combat["actif1_nom"] if user_id == combat["joueur1_id"] else combat["actif2_nom"]
    actif_adv = combat["actif2_nom"] if user_id == combat["joueur1_id"] else combat["actif1_nom"]
    action_moi = combat["action1"] if user_id == combat["joueur1_id"] else combat["action2"]
    return combat, adversaire_id, actif_moi, actif_adv, action_moi


def _pokemon_json(combat_id: int, user_id: int, row, actif_nom: str, detail: bool) -> dict:
    out = {
        "nom": row["pokemon_nom"],
        "niveau": row["niveau"],
        "pv": row["pv_actuels"],
        "pv_max": row["pv_max"],
        "ko": row["pv_actuels"] <= 0,
        "actif": row["pokemon_nom"] == actif_nom,
    }
    if out["actif"]:
        statut = database.obtenir_statut(combat_id, user_id, row["pokemon_nom"])
        out["statut"] = statut[0] if statut else None
        out["shiny"] = any(r["shiny"] for r in database.obtenir_pokedex_joueur(user_id) if r["pokemon_nom"] == actif_nom)
        boosts = database.obtenir_boosts(combat_id, user_id, row["pokemon_nom"])
        out["boosts"] = {k: v for k, v in boosts.items() if v}
    if detail:
        out["objet_tenu"] = row["objet_tenu"]
    return out


def _attaques_json(combat_id: int, user_id: int, actif_nom: str) -> dict:
    """Attaques proposables ce tour (mêmes règles que le bouton Attaquer de Discord)."""
    equipees = database.obtenir_attaques_equipees(user_id, actif_nom, combat_id=combat_id)
    if not equipees:
        return {"mode": "defaut", "attaques": [
            {"nom": ATTAQUE_DEFAUT_NOM, "type": None, "puissance": None, "precision": None, "pp": None, "pp_max": None, "jouable": True}
        ]}
    liste = []
    for slot in sorted(equipees):
        nom = equipees[slot]
        a = obtenir_attaque(nom)
        pp_max = pp_max_attaque(a)
        pp = database.obtenir_pp(combat_id, user_id, actif_nom, nom, pp_max)
        liste.append({
            "slot": slot, "nom": nom, "type": a.get("type"), "classe": a.get("classe"),
            "puissance": a.get("puissance"), "precision": a.get("precision"),
            "pp": pp, "pp_max": pp_max, "jouable": pp > 0,
        })
    if not any(x["jouable"] for x in liste):
        return {"mode": "lutte", "attaques": [], "lutte": combat_module.NOM_LUTTE}
    return {"mode": "normal", "attaques": liste}


def _potions_json(combat_id: int, user_id: int) -> dict:
    inv = database.obtenir_inventaire_balls(user_id)
    dispo = {k: v for k, v in inv.items() if k in NOM_SOIN_AFFICHAGE and v > 0}
    utilisees = database.compter_potions_soin_utilisees(combat_id, user_id)
    limite_atteinte = utilisees >= config.LIMITE_POTIONS_SOIN_COMBAT
    if limite_atteinte:
        dispo = {k: v for k, v in dispo.items() if k == "totalsoin"}
    return {
        "disponibles": [{"type": k, "nom": NOM_SOIN_AFFICHAGE[k], "quantite": v} for k, v in dispo.items()],
        "utilisees": utilisees,
        "limite": config.LIMITE_POTIONS_SOIN_COMBAT,
    }


def _mega_possible(combat_id: int, user_id: int, actif_nom: str, row) -> dict | None:
    """Infos sur la Méga-Évolution proposable maintenant, ou None."""
    if database.a_deja_mega_evolue(combat_id, user_id) or row is None or row["pv_actuels"] <= 0:
        return None
    if actif_nom == "Rayquaza":
        req = mega_evolutions_module.MEGA_RAYQUAZA["attaque_requise"]
        if req in database.obtenir_attaques_equipees(user_id, "Rayquaza", combat_id=combat_id).values():
            return {"forme": mega_evolutions_module.MEGA_RAYQUAZA["forme_nom"]}
        return None
    info = mega_evolutions_module.MEGA_EVOLUTIONS.get(row["objet_tenu"]) if row["objet_tenu"] else None
    if info and info["espece"] == actif_nom:
        return {"forme": info["forme_nom"]}
    return None


def etat_combat(combat_id: int, user_id: int) -> dict:
    """État complet du combat du point de vue d'un joueur (tout est JSON-sérialisable)."""
    combat, adv_id, actif_moi, actif_adv, action_moi = _ctx(combat_id, user_id)
    meta = _meta(combat_id)

    eq_moi = database.obtenir_equipe_pvp(combat_id, user_id)
    eq_adv = database.obtenir_equipe_pvp(combat_id, adv_id)
    row_actif = next((r for r in eq_moi if r["pokemon_nom"] == actif_moi), None)

    choix_ko = any(r["user_id"] == user_id for r in database.obtenir_choix_ko(combat_id))
    charge = database.obtenir_charge(combat_id, user_id, actif_moi)
    verrouille = bool(charge["attaque_en_charge"]) or bool(charge["doit_recharger"])

    etat = {
        "combat_id": combat_id,
        "mode": (meta["mode"] if meta else None) or "dresseur",
        "actif": bool(combat["actif"]),
        "tour": combat["tour"],
        "secondes_restantes": max(0, combat["date_limite_tour"] - int(time.time())),
        "duree_tour": combat_module.DUREE_TOUR,
        "action_choisie": action_moi is not None,
        "verrouille": verrouille,  # attaque en charge/recharge : rien à choisir ce tour
        "remplacant_requis": choix_ko,
        "moi": {
            "equipe": [_pokemon_json(combat_id, user_id, r, actif_moi, True) for r in eq_moi],
        },
        "adversaire": {
            "nom": ((meta["nom_joueur"] if user_id == meta["id_adversaire"] else meta["archetype_nom"]) if meta else None),
            "equipe": [_pokemon_json(combat_id, adv_id, r, actif_adv, False) for r in eq_adv],
        },
    }
    if combat["actif"]:
        etat["actions"] = {
            "attaques": _attaques_json(combat_id, user_id, actif_moi),
            "potions": _potions_json(combat_id, user_id),
            "changements": [r["pokemon_nom"] for r in eq_moi if r["pv_actuels"] > 0 and r["pokemon_nom"] != actif_moi],
            "mega": _mega_possible(combat_id, user_id, actif_moi, row_actif),
        }
    etat["journal"] = journal_combat(combat_id)
    etat["resultat"] = resultat_combat(combat_id)
    if etat["resultat"] and etat["resultat"].get("pvp"):
        import pvp_service
        etat["resultat"] = pvp_service.resultat_pour(etat["resultat"], user_id)
    return etat


def _enregistrer_resultat(combat_id: int, resultat: dict):
    _init_tables()
    conn = database.get_connexion()
    conn.execute(
        "INSERT OR REPLACE INTO combat_web_resultat (combat_id, resultat) VALUES (?, ?)",
        (combat_id, json.dumps(resultat, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def resultat_combat(combat_id: int) -> dict | None:
    """Issue d'un combat terminé : {"issue": "victoire"|"defaite"|"abandon"|"annule", "recompenses": ...}."""
    _init_tables()
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT resultat FROM combat_web_resultat WHERE combat_id = ?", (combat_id,))
    row = cur.fetchone()
    conn.close()
    return json.loads(row["resultat"]) if row else None


def journal_combat(combat_id: int, dernier_seulement: bool = True) -> list:
    """Journal des tours déjà résolus : [{tour, lignes}], le plus récent en dernier."""
    _init_tables()
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT tour, lignes FROM combat_web_journal WHERE combat_id = ? ORDER BY tour", (combat_id,))
    rows = cur.fetchall()
    conn.close()
    if dernier_seulement:
        rows = rows[-1:]
    return [{"tour": r["tour"], "lignes": json.loads(r["lignes"])} for r in rows]


# ----------------------------------------------------------------------------
# Actions du joueur
# ----------------------------------------------------------------------------

def _verifier_peut_agir(combat_id: int, user_id: int, tour: int | None):
    combat, _, _, _, action_moi = _ctx(combat_id, user_id)
    if not combat["actif"]:
        raise ErreurCombatWeb("Ce combat est terminé.")
    if tour is not None and combat["tour"] != tour:
        raise ErreurCombatWeb("⌛ Ce tour est déjà résolu.")
    if action_moi is not None:
        raise ErreurCombatWeb("Tu as déjà choisi ton action pour ce tour !")
    if any(r["user_id"] == user_id for r in database.obtenir_choix_ko(combat_id)):
        raise ErreurCombatWeb("🔁 Ton Pokémon est K.O. — choisis d'abord ton remplaçant.")
    return combat


def soumettre_action(combat_id: int, user_id: int, type_action: str, valeur: str | None = None, tour: int | None = None) -> dict:
    """Enregistre l'action du tour. type_action : 'attaque' | 'potion' | 'changer'.
    Lève ErreurCombatWeb si une règle du combat l'interdit."""
    combat = _verifier_peut_agir(combat_id, user_id, tour)
    _, _, actif_moi, _, _ = _ctx(combat_id, user_id)

    if type_action == "attaque":
        etat = _attaques_json(combat_id, user_id, actif_moi)
        if etat["mode"] == "defaut":
            action, msg = f"attaque:{ATTAQUE_DEFAUT_NOM}", f"{actif_moi} utilisera {ATTAQUE_DEFAUT_NOM} (aucune attaque équipée)."
        elif etat["mode"] == "lutte":
            action, msg = f"attaque:{combat_module.NOM_LUTTE}", f"{actif_moi} n'a plus de PP : il utilisera Lutte."
        else:
            jouables = {a["nom"] for a in etat["attaques"] if a["jouable"]}
            if valeur not in jouables:
                raise ErreurCombatWeb("Attaque indisponible (non équipée ou plus de PP).")
            action, msg = f"attaque:{valeur}", f"Action enregistrée : {valeur}."
        database.enregistrer_action_pvp(combat_id, user_id, action)
        return {"ok": True, "message": msg}

    if type_action == "potion":
        if valeur not in NOM_SOIN_AFFICHAGE:
            raise ErreurCombatWeb("Objet de soin inconnu.")
        if valeur != "totalsoin" and (
            database.compter_potions_soin_utilisees(combat_id, user_id) >= config.LIMITE_POTIONS_SOIN_COMBAT
        ):
            raise ErreurCombatWeb(f"Tu as déjà utilisé tes {config.LIMITE_POTIONS_SOIN_COMBAT} potions de soin pour ce combat !")
        if not database.retirer_ball(user_id, valeur):
            raise ErreurCombatWeb("Tu n'as plus cette potion !")
        database.enregistrer_action_pvp(combat_id, user_id, f"potion:{valeur}")
        if valeur != "totalsoin":
            database.incrementer_potions_soin_utilisees(combat_id, user_id)
        return {"ok": True, "message": f"Action enregistrée : {NOM_SOIN_AFFICHAGE[valeur]}."}

    if type_action == "changer":
        equipe = database.obtenir_equipe_pvp(combat_id, user_id)
        if valeur not in {r["pokemon_nom"] for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != actif_moi}:
            raise ErreurCombatWeb("Ce Pokémon ne peut pas être envoyé.")
        database.enregistrer_action_pvp(combat_id, user_id, f"changer:{valeur}")
        return {"ok": True, "message": f"Action enregistrée : envoi de {valeur}."}

    raise ErreurCombatWeb("Type d'action inconnu.")


def mega_evoluer(combat_id: int, user_id: int) -> dict:
    """Active la Méga-Évolution du Pokémon actif (ne consomme PAS le tour : il faut
    ensuite choisir une action). Mêmes règles que le bouton Discord."""
    combat, _, actif_moi, _, _ = _ctx(combat_id, user_id)
    if not combat["actif"]:
        raise ErreurCombatWeb("Ce combat est terminé.")
    if database.a_deja_mega_evolue(combat_id, user_id):
        raise ErreurCombatWeb("Tu as déjà utilisé ta Méga-Évolution pour ce combat !")
    equipe = database.obtenir_equipe_pvp(combat_id, user_id)
    row = next((r for r in equipe if r["pokemon_nom"] == actif_moi), None)
    if row is None or row["pv_actuels"] <= 0:
        raise ErreurCombatWeb("Ton Pokémon actif est K.O. !")

    if actif_moi == "Rayquaza":
        req = mega_evolutions_module.MEGA_RAYQUAZA["attaque_requise"]
        if req not in database.obtenir_attaques_equipees(user_id, "Rayquaza", combat_id=combat_id).values():
            raise ErreurCombatWeb(f"Rayquaza doit connaître {req} pour Méga-Évoluer.")
        info, cle_stone = mega_evolutions_module.MEGA_RAYQUAZA, None
    else:
        objet = row["objet_tenu"]
        info = mega_evolutions_module.MEGA_EVOLUTIONS.get(objet) if objet else None
        if not info or info["espece"] != actif_moi:
            raise ErreurCombatWeb(f"{actif_moi} ne tient pas de Pierre Méga compatible.")
        cle_stone = objet

    ivs = database.obtenir_meilleures_ivs(user_id, actif_moi) or IV_DEFAUT
    pokemon_mega = {"nom": info["forme_nom"], "types": info["types"], "stats_detaillees": info["stats_detaillees"]}
    stats = calculer_toutes_stats(pokemon_mega, ivs, row["niveau"])
    database.activer_mega_evolution_combat(combat_id, user_id, row["position"], actif_moi, stats, cle_stone=cle_stone)
    return {"ok": True, "message": f"{actif_moi} Méga-Évolue en {info['forme_nom']} ! Choisis maintenant ton action."}


def choisir_remplacant_ko(combat_id: int, user_id: int, nom: str) -> dict:
    """Envoie le remplaçant après un K.O. (changement gratuit, ne consomme pas le tour)."""
    combat, _, actif_moi, _, _ = _ctx(combat_id, user_id)
    if not combat["actif"]:
        raise ErreurCombatWeb("Ce combat est terminé.")
    ligne = next((r for r in database.obtenir_choix_ko(combat_id) if r["user_id"] == user_id), None)
    if ligne is None:
        raise ErreurCombatWeb("Tu n'as pas de Pokémon K.O. à remplacer (ou l'envoi automatique a déjà eu lieu).")
    equipe = database.obtenir_equipe_pvp(combat_id, user_id)
    if nom not in {r["pokemon_nom"] for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != actif_moi}:
        raise ErreurCombatWeb("Ce Pokémon ne peut pas être envoyé.")
    if not database.supprimer_choix_ko(combat_id, user_id):  # verrou anti-double-envoi
        raise ErreurCombatWeb("Trop tard — l'envoi automatique a déjà eu lieu !")
    if ligne["relais"]:
        database.copier_boosts(combat_id, user_id, actif_moi, nom)
        database.reinitialiser_boosts(combat_id, user_id, actif_moi)
    database.changer_pokemon_actif_pvp(combat_id, user_id, nom)
    mini_log = [f"🔁 **{_meta(combat_id)['nom_joueur']}** envoie **{nom}** !"]
    combat_module._appliquer_hazards_entree(combat_id, user_id, nom, mini_log)
    return {"ok": True, "message": f"{nom} entre en jeu !", "log": mini_log}


def abandonner(combat_id: int, user_id: int) -> dict:
    """Abandon d'un combat PvE : défaite sans récompense. Les PV restants sont conservés
    (pool persistant), comme à la fin d'un combat normal."""
    combat, _, _, _, _ = _ctx(combat_id, user_id)
    if not combat["actif"]:
        raise ErreurCombatWeb("Ce combat est déjà terminé.")
    meta_abandon = _meta(combat_id)
    if meta_abandon is not None and meta_abandon["mode"] == "pvp":
        import pvp_service
        return pvp_service.abandonner(combat_id, user_id)
    database.terminer_combat_pvp(combat_id)
    database.synchroniser_pv_persistant_depuis_combat(combat_id, user_id)
    suite = _suite_mode(_meta(combat_id), False)
    _enregistrer_resultat(combat_id, {"issue": "abandon", "recompenses": None, "suite": suite})
    return {"ok": True, "message": "Tu as abandonné. Défaite enregistrée."}


# ----------------------------------------------------------------------------
# Résolution (équivalent de _tick_resolution_dresseur, sans Discord)
# ----------------------------------------------------------------------------

def _quetes_json(quetes) -> list:
    sortie = []
    for q in quetes or []:
        try:
            sortie.append(dict(q))
        except (TypeError, ValueError):
            sortie.append({"quete": str(q)})
    return sortie


def _suite_mode(meta, victoire: bool) -> dict | None:
    """Étape suivante d'un run (Arène, Repaire) : gérée par modes_service (import tardif)."""
    if meta is None or (meta["mode"] or "dresseur") in ("dresseur", "gladio", "pvp"):
        return None
    import modes_service
    return modes_service.resoudre_etape(meta, victoire)


def _appliquer_victoire(meta) -> dict:
    joueur_id = meta["joueur_id"]
    pc_cible = meta["pc_cible"]
    mode = meta["mode"] or "dresseur"
    # Gladio / Arène / Repaire : récompense indépendante, sans dégression anti-farm.
    independant = mode != "dresseur"
    mult = 1.0 if independant else database.enregistrer_victoire_dresseur_repetition(joueur_id)
    if mode == "gladio":
        dollars = round(
            random.randint(config.GLADIO_RECOMPENSE_MIN, config.GLADIO_RECOMPENSE_MAX)
            * database.multiplicateur_boost(joueur_id, "argent")
        )
    elif mode in ("arene", "repaire"):
        dollars = 0  # les Poké Dollars sont crédités par le run lui-même (modes_service)
    else:
        dollars = round(pc_cible * config.DRESSEUR_FACTEUR_DOLLARS * mult * database.multiplicateur_boost(joueur_id, "argent"))
    xp = round(pc_cible * config.DRESSEUR_FACTEUR_XP * mult)
    xp_affichee = round(xp * database.multiplicateur_boost(joueur_id, "xp"))
    if dollars > 0:
        database.ajouter_poke_dollars(joueur_id, dollars)
    niveau_avant, niveau_apres, paliers = leveling.gagner_xp(joueur_id, xp)
    database.incrementer_victoires_pve(joueur_id)
    quetes = database.incrementer_progression_quete(joueur_id, "pve_victoire")
    if mode == "gladio":
        database.avancer_quete_principale(joueur_id, "gladio_victoire")
    return {
        "dollars": dollars,
        "xp": xp_affichee,
        "reduite": mult < 1.0,
        "niveau_dresseur": {"avant": niveau_avant, "apres": niveau_apres},
        "paliers": [{"palier": p, "dollars": d, "ball": b} for p, d, b in paliers],
        "quetes_completees": _quetes_json(quetes),
    }


async def tick(combat_id: int) -> dict:
    """Un tick de résolution. Renvoie {"statut": ...} :
       'inactif' (combat déjà fini), 'attente_remplacant', 'attente_joueur',
       'tour_resolu' (+ journal), ou 'termine' (+ vainqueur, récompenses, journal)."""
    meta = _meta(combat_id)
    if meta is None:
        raise ErreurCombatWeb("Ce combat n'a pas été lancé par le web.")
    if meta["mode"] == "pvp":
        import pvp_service
        return await pvp_service.tick(combat_id, meta)
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return {"statut": "inactif"}

    # Remplaçant après K.O. : la résolution attend (envoi auto une fois le délai écoulé).
    if await combat_module.traiter_choix_ko(None, combat_id, None):
        return {"statut": "attente_remplacant"}

    deux_prets = combat["action1"] is not None and combat["action2"] is not None
    timer_expire = int(time.time()) >= combat["date_limite_tour"]
    if not deux_prets and not timer_expire:
        return {"statut": "attente_joueur"}

    tour_resolu = combat["tour"]
    log = _nettoyer_log(await combat_module.resoudre_tour(combat_id), meta)
    conn = database.get_connexion()
    conn.execute(
        "INSERT OR REPLACE INTO combat_web_journal (combat_id, tour, lignes) VALUES (?, ?, ?)",
        (combat_id, tour_resolu, json.dumps(log, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    vainqueur_id = combat_module.verifier_fin_combat(combat_id)
    if vainqueur_id is not None:
        joueur_id = meta["joueur_id"]
        database.terminer_combat_pvp(combat_id)
        database.synchroniser_pv_persistant_depuis_combat(combat_id, joueur_id)
        victoire = vainqueur_id == joueur_id
        recompenses = _appliquer_victoire(meta) if victoire else None
        suite = _suite_mode(meta, victoire)
        _enregistrer_resultat(
            combat_id, {"issue": "victoire" if victoire else "defaite", "recompenses": recompenses, "suite": suite}
        )
        return {
            "statut": "termine",
            "victoire": victoire,
            "tour": tour_resolu,
            "journal": log,
            "recompenses": recompenses,
        }

    database.passer_tour_pvp(combat_id, int(time.time()) + combat_module.DUREE_TOUR)
    await dresseurs_module._jouer_tour_ia(combat_id, meta["id_adversaire"])
    return {"statut": "tour_resolu", "tour": tour_resolu, "journal": log}


async def boucle_combat(combat_id: int, intervalle: float = 2.0) -> dict | None:
    """Boucle de résolution d'un combat web (à lancer avec asyncio.create_task).
    Même protection que sur Discord : une erreur est retentée au tick suivant, et après
    3 échecs d'affilée le combat est clôturé proprement (annulé, sans récompense)."""
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
            print(f"⚠️ Erreur au tick du combat web {combat_id} (tentative {echecs}/3) :")
            traceback.print_exc()
            if echecs >= 3:
                meta = _meta(combat_id)
                database.terminer_combat_pvp(combat_id)
                if meta and meta["mode"] == "pvp":
                    mise = database.obtenir_mise_combat(combat_id)  # remboursement des deux joueurs
                    if mise:
                        database.ajouter_poke_dollars(meta["joueur_id"], mise // 2)
                        database.ajouter_poke_dollars(meta["id_adversaire"], mise // 2)
                        database.retirer_mise_combat(combat_id)
                elif meta:
                    database.synchroniser_pv_persistant_depuis_combat(combat_id, meta["joueur_id"])
                _enregistrer_resultat(combat_id, {"issue": "annule", "recompenses": None, "suite": _suite_mode(meta, False)})
                return {"statut": "annule"}
