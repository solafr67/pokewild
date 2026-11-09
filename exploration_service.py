"""exploration_service.py — apparitions, capture et PokéStop sur le site (sans Discord).

Reprend à l'identique les règles de views.py (capture) et main.py (PokéStop) en s'appuyant
sur les MÊMES fonctions de base de données : récompenses, XP, quêtes, boosts, stockage.

Apparitions : flux partagé propre au site (table spawn_web), une tentative par joueur et par
apparition, durée de vie = config.DUREE_AVANT_DISPARITION. Elles s'ajoutent à celles de
Discord (le bot n'enregistre pas les siennes en base).
Limite connue : la météo et l'heure de pointe sont gardées en mémoire par le bot ; le site
n'a donc pas de météo (tirage neutre), et l'heure de pointe est relue depuis la base.
"""

import asyncio
import json
import random
import sqlite3
import time

import config
import database
import inventaire
import leveling
import niveaux_pokemon
from combat_service import ErreurCombatWeb, _quetes_json
from pokemon_data import (
    POIDS_RARETE_CLASSIQUE,
    TAUX_CAPTURE,
    appliquer_deguisement_si_applicable,
    calculer_pc_derive,
    obtenir_pokemon_par_nom,
    tirer_ivs,
    tirer_niveau_spawn,
    tirer_pokemon_aleatoire,
)

BALLS_CAPTURE = ("pokeball", "superball", "hyperball", "masterball")
MAX_SPAWNS_ACTIFS = 4


# ----------------------------------------------------------------------------
# Tables
# ----------------------------------------------------------------------------

def _init_tables():
    conn = database.get_connexion()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS spawn_web (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_affiche TEXT NOT NULL,
            nom_reel TEXT NOT NULL,
            pc INTEGER NOT NULL,
            niveau INTEGER NOT NULL,
            ivs TEXT NOT NULL,
            cree_a REAL NOT NULL,
            expire_a REAL NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS spawn_web_tentatives (
            spawn_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (spawn_id, user_id)
        )"""
    )
    conn.commit()
    conn.close()


# ----------------------------------------------------------------------------
# Apparitions
# ----------------------------------------------------------------------------

def creer_spawn() -> int | None:
    """Fait apparaître un Pokémon (même tirage que le salon classique de Discord)."""
    conn = database.get_connexion()
    n = conn.execute("SELECT COUNT(*) FROM spawn_web WHERE expire_a > ?", (time.time(),)).fetchone()[0]
    conn.close()
    if n >= MAX_SPAWNS_ACTIFS:
        return None
    pokemon = appliquer_deguisement_si_applicable(tirer_pokemon_aleatoire(POIDS_RARETE_CLASSIQUE))
    reel = pokemon.get("__espece_reelle__") or pokemon
    niveau = tirer_niveau_spawn(pokemon["rarete"])
    ivs = tirer_ivs()
    pc = calculer_pc_derive(pokemon, ivs, niveau)
    maintenant = time.time()
    conn = database.get_connexion()
    cur = conn.execute(
        "INSERT INTO spawn_web (nom_affiche, nom_reel, pc, niveau, ivs, cree_a, expire_a) VALUES (?,?,?,?,?,?,?)",
        (pokemon["nom"], reel["nom"], pc, niveau, json.dumps(ivs), maintenant, maintenant + config.DUREE_AVANT_DISPARITION),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def nettoyer_spawns():
    conn = database.get_connexion()
    limite = time.time() - 3600
    conn.execute("DELETE FROM spawn_web_tentatives WHERE spawn_id IN (SELECT id FROM spawn_web WHERE expire_a < ?)", (limite,))
    conn.execute("DELETE FROM spawn_web WHERE expire_a < ?", (limite,))
    conn.commit()
    conn.close()


async def boucle_spawns(intervalle: float = None):
    """Boucle unique (un seul process web) : une apparition toutes les INTERVALLE_SPAWN_CLASSIQUE s."""
    intervalle = intervalle or config.INTERVALLE_SPAWN_CLASSIQUE
    while True:
        try:
            creer_spawn()
            nettoyer_spawns()
        except Exception as e:  # une erreur ne doit jamais arrêter la boucle
            print(f"⚠️ boucle_spawns : {e}")
        await asyncio.sleep(intervalle)


def spawns_actifs(user_id: int) -> list:
    conn = database.get_connexion()
    maintenant = time.time()
    lignes = conn.execute(
        "SELECT * FROM spawn_web WHERE expire_a > ? ORDER BY id DESC", (maintenant,)
    ).fetchall()
    tentes = {r[0] for r in conn.execute("SELECT spawn_id FROM spawn_web_tentatives WHERE user_id = ?", (user_id,))}
    conn.close()
    res = []
    for r in lignes:
        p = obtenir_pokemon_par_nom(r["nom_affiche"]) or {}
        res.append({
            "id": r["id"], "nom": r["nom_affiche"], "pc": r["pc"], "niveau": r["niveau"],
            "rarete": p.get("rarete"), "types": p.get("types", []),
            "secondes_restantes": max(0, int(r["expire_a"] - maintenant)),
            "deja_tente": r["id"] in tentes,
            "possedes": database.compter_captures_espece(user_id, r["nom_affiche"]),
        })
    return res


# ----------------------------------------------------------------------------
# Capture
# ----------------------------------------------------------------------------

def capturer(user_id: int, spawn_id: int, ball: str) -> dict:
    if ball not in BALLS_CAPTURE:
        raise ErreurCombatWeb("Ball inconnue.")
    conn = database.get_connexion()
    row = conn.execute("SELECT * FROM spawn_web WHERE id = ?", (spawn_id,)).fetchone()
    conn.close()
    if row is None or row["expire_a"] <= time.time():
        raise ErreurCombatWeb("💨 Trop tard, ce Pokémon s'est déjà enfui !")

    inv = database.obtenir_inventaire_balls(user_id)
    if inv.get(ball, 0) <= 0:
        raise ErreurCombatWeb("Tu n'as plus cette ball.")
    limite = database.limite_stockage_pokemon(user_id)
    if database.compter_captures_totales(user_id) >= limite:
        raise ErreurCombatWeb(f"📦 Ton stockage est plein ({limite}/{limite}) : relâche des Pokémon ou achète une extension.")

    # Verrou « une tentative par apparition » : atomique grâce à la clé primaire.
    conn = database.get_connexion()
    try:
        conn.execute("INSERT INTO spawn_web_tentatives (spawn_id, user_id) VALUES (?,?)", (spawn_id, user_id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ErreurCombatWeb("Tu as déjà tenté ta chance sur ce Pokémon !")
    conn.close()

    def annuler_verrou():
        c = database.get_connexion()
        c.execute("DELETE FROM spawn_web_tentatives WHERE spawn_id = ? AND user_id = ?", (spawn_id, user_id))
        c.commit()
        c.close()

    if not database.retirer_ball(user_id, ball):
        annuler_verrou()
        raise ErreurCombatWeb("Tu n'as plus cette ball.")

    pokemon = obtenir_pokemon_par_nom(row["nom_reel"])
    affiche = row["nom_affiche"]
    pc_affiche = row["pc"]
    ivs = json.loads(row["ivs"])
    niveau = row["niveau"]
    rarete_affichee = (obtenir_pokemon_par_nom(affiche) or pokemon)["rarete"]

    taux = min(1.0, TAUX_CAPTURE[rarete_affichee][ball] * database.multiplicateur_boost(user_id, "capture"))
    if random.random() >= taux:
        return {"reussite": False, "nom": affiche, "ball": ball,
                "message": f"💨 {affiche} a fui malgré ta {inventaire.NOMS_OBJETS.get(ball, ball)}."}

    # Révélation Zorua/Zoroark/Métamorph : la vraie espèce remplace le déguisement.
    pc = calculer_pc_derive(pokemon, ivs, niveau) if pokemon["nom"] != affiche else pc_affiche
    nouvelle_entree = database.compter_captures_espece(user_id, pokemon["nom"]) == 0
    chance_shiny = config.CHANCE_SHINY_BASE * database.multiplicateur_boost(user_id, "shiny")
    est_shiny = random.random() < chance_shiny

    objet_forme = database.ajouter_capture(user_id, pokemon["nom"], pc, shiny=est_shiny, ivs=ivs, source="web")

    niv_actuel, _ = database.obtenir_niveau_pokemon(user_id, pokemon["nom"])
    if niveau > niv_actuel:
        database.definir_niveau_xp_pokemon(user_id, pokemon["nom"], niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau))

    dollars = round(10 * database.multiplicateur_boost(user_id, "argent"))
    database.ajouter_poke_dollars(user_id, dollars)
    quetes = database.incrementer_progression_quete(
        user_id, "capture", {"rarete": pokemon["rarete"], "shiny": est_shiny, "type": pokemon.get("types", [])}
    )

    # Trouvaille : petite chance de Cristal de Mutation ou d'Œuf (mêmes tirages que Discord).
    trouvaille = None
    if random.random() < config.CHANCE_CRISTAL_CAPTURE:
        trouvaille = "cristal_mutation"
    else:
        tirage, seuil = random.random(), 0.0
        for palier, poids in config.OEUF_POIDS_CAPTURE.items():
            seuil += poids
            if tirage < seuil:
                trouvaille = f"oeuf_{palier}"
                break
    if trouvaille:
        database.ajouter_balls(user_id, trouvaille, 1)

    xp = config.XP_PAR_RARETE[pokemon["rarete"]] + (config.XP_BONUS_SHINY if est_shiny else 0)
    xp_affichee = round(xp * database.multiplicateur_boost(user_id, "xp"))
    _avant, _apres, paliers = leveling.gagner_xp(user_id, xp)
    montees = niveaux_pokemon.gagner_xp_equipe(user_id, config.XP_POKEMON_PAR_RARETE[pokemon["rarete"]])

    return {
        "reussite": True, "nom": pokemon["nom"], "ball": ball, "pc": pc, "shiny": est_shiny,
        "deguise_en": affiche if affiche != pokemon["nom"] else None,
        "nouvelle_entree": nouvelle_entree, "dollars": dollars, "xp": xp_affichee,
        "trouvaille": inventaire.NOMS_OBJETS.get(trouvaille, trouvaille) if trouvaille else None,
        "objet_forme": objet_forme,
        "paliers": [{"palier": p, "dollars": d, "ball": inventaire.NOMS_OBJETS.get(b, b)} for p, d, b in paliers],
        "montees_niveau": niveaux_pokemon.texte_montees_niveau(montees) if montees else None,
        "quetes_completees": _quetes_json(quetes),
    }


# ----------------------------------------------------------------------------
# PokéStop
# ----------------------------------------------------------------------------

def _seuils_ball_avec_chance(mult_chance: float) -> tuple:
    """Copie de main._seuils_ball_avec_chance (main.py ne peut pas être importé sans lancer le bot)."""
    bonus = max(0.0, mult_chance - 1.0)
    POKEBALL, SUPERBALL, HYPERBALL, MASTERBALL, RIEN = 0.55, 0.30, 0.10, 0.001, 0.049
    nouveau_rien = RIEN / (1 + bonus)
    liberee_rien = RIEN - nouveau_rien
    nouveau_pokeball = POKEBALL / (1 + bonus * 0.5)
    liberee_pokeball = POKEBALL - nouveau_pokeball
    hyper = HYPERBALL + liberee_rien * 0.7
    master = MASTERBALL + liberee_rien * 0.3
    sup = SUPERBALL + liberee_pokeball
    s1 = nouveau_pokeball
    s2 = s1 + sup
    s3 = s2 + hyper
    return s1, s2, s3, s3 + master


def heure_de_pointe_active() -> bool:
    """L'état du bot est en mémoire ; on relit le créneau du jour dans la base."""
    try:
        debut = int(database.obtenir_parametre("pokestop_event_debut") or 0)
    except ValueError:
        return False
    return debut > 0 and debut <= time.time() < debut + config.DUREE_HEURE_DE_POINTE_POKESTOP


def pokestop_etat(user_id: int) -> dict:
    ok, reste = database.peut_utiliser_pokestop(user_id, config.COOLDOWN_POKESTOP)
    return {"disponible": ok, "secondes_restantes": reste, "heure_de_pointe": heure_de_pointe_active(),
            "cooldown": config.COOLDOWN_POKESTOP}


def pokestop_tourner(user_id: int) -> dict:
    ok, reste = database.peut_utiliser_pokestop(user_id, config.COOLDOWN_POKESTOP)
    if not ok:
        raise ErreurCombatWeb(f"⏳ Disque pas encore rechargé : reviens dans {reste // 60} min {reste % 60} s.")
    database.marquer_pokestop_utilise(user_id)

    pointe = heure_de_pointe_active()
    mult_pointe = config.MULTIPLICATEUR_HEURE_DE_POINTE if pointe else 1.0
    nom = inventaire.NOMS_OBJETS.get

    dollars = round(random.randint(20, 45) * database.multiplicateur_boost(user_id, "argent") * mult_pointe)
    database.ajouter_poke_dollars(user_id, dollars)
    quetes = database.incrementer_progression_quete(user_id, "pokestop")

    objets = []
    sac_plein = False
    limite = database.limite_stockage_objets(user_id)

    def place():
        return limite - database.compter_objets_totaux(user_id)

    if place() <= 0:
        sac_plein = True
    else:
        mult_chance = database.multiplicateur_boost(user_id, "chance")
        s1, s2, s3, s4 = _seuils_ball_avec_chance(mult_chance)
        t = random.random()
        ball = None
        if t < s1:
            ball, q = "pokeball", random.randint(2, 5)
        elif t < s2:
            ball, q = "superball", random.randint(1, 3)
        elif t < s3:
            ball, q = "hyperball", random.randint(1, 3)
        elif t < s4:
            ball, q = "masterball", 1
        if ball:
            q = 1 if ball == "masterball" else min(round(q * mult_pointe), place())
            database.ajouter_balls(user_id, ball, q)
            objets.append({"cle": ball, "nom": nom(ball, ball), "quantite": q})

        if place() > 0:
            w = config.POTIONS_POIDS_POKESTOP
            t, seuil = random.random(), 0.0
            for cle, bornes in (("potion", (2, 5)), ("superpotion", (1, 3)), ("hyperpotion", (1, 1)), ("totalsoin", (1, 1))):
                seuil += w[cle]
                if t < seuil:
                    q = min(round(random.randint(*bornes) * mult_pointe), place())
                    database.ajouter_balls(user_id, cle, q)
                    objets.append({"cle": cle, "nom": nom(cle, cle), "quantite": q})
                    break

        if place() > 0 and random.random() < min(1.0, config.CHANCE_CRISTAL_POKESTOP * mult_pointe * mult_chance):
            database.ajouter_balls(user_id, "cristal_mutation", 1)
            objets.append({"cle": "cristal_mutation", "nom": nom("cristal_mutation", "Cristal de Mutation"), "quantite": 1})

        if place() > 0:
            t, seuil = random.random() / (mult_pointe * mult_chance), 0.0
            for palier, poids in config.OEUF_POIDS_POKESTOP.items():
                seuil += poids
                if t < seuil:
                    database.ajouter_balls(user_id, f"oeuf_{palier}", 1)
                    objets.append({"cle": f"oeuf_{palier}", "nom": nom(f"oeuf_{palier}", f"Œuf {palier}"), "quantite": 1})
                    break

    _avant, _apres, paliers = leveling.gagner_xp(user_id, config.XP_POKESTOP)
    montees = niveaux_pokemon.gagner_xp_equipe(user_id, config.XP_POKEMON_POKESTOP)
    return {
        "dollars": dollars, "objets": objets, "sac_plein": sac_plein, "heure_de_pointe": pointe,
        "xp": config.XP_POKESTOP,
        "paliers": [{"palier": p, "dollars": d, "ball": nom(b, b)} for p, d, b in paliers],
        "montees_niveau": niveaux_pokemon.texte_montees_niveau(montees) if montees else None,
        "quetes_completees": _quetes_json(quetes),
        "secondes_restantes": config.COOLDOWN_POKESTOP,
    }
