"""web_app.py — serveur web de PokéWild (étape 2 du portage navigateur).

FastAPI + connexion « Se connecter avec Discord » (OAuth2, scope `identify`). Il partage la
MÊME base SQLite que le bot Discord : un joueur retrouve son profil, son équipe et ses PV.
Rien du bot existant n'est modifié ; la logique de combat vient de combat_service.py.

Lancement (depuis le dossier du projet) :
    uvicorn web_app:app --host 127.0.0.1 --port 8000

Variables d'environnement :
    DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET  application Discord (onglet OAuth2)
    WEB_BASE_URL     URL publique du site, ex. https://pokewild.exemple.fr (sans « / » final) ;
                     l'URL de redirection à déclarer chez Discord est <WEB_BASE_URL>/auth/callback
    WEB_SECRET       clé secrète des cookies de session (longue, aléatoire, à garder privée)
    DB_PATH          même base que le bot (déjà géré par database/__init__.py)
    WEB_DEV_LOGIN=1  (TESTS UNIQUEMENT) active /auth/dev?user_id=... — ne JAMAIS l'activer en prod
    WEB_COOKIE_SECURE=1  recommandé derrière HTTPS
"""

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

# config.py exige DISCORD_TOKEN même si on ne se connecte jamais à Discord : valeur factice.
os.environ.setdefault("DISCORD_TOKEN", "web-only-no-discord-connection")

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

import combat as combat_module  # noqa: E402
import combat_service  # noqa: E402
import combat_visuel  # noqa: E402
import database  # noqa: E402
import exploration_service  # noqa: E402
import expedition_service  # noqa: E402
import boutique_service  # noqa: E402
import laboratoire_service  # noqa: E402
import gestion_service  # noqa: E402
import leveling  # noqa: E402
from combat_service import ErreurCombatWeb  # noqa: E402
from pokemon_data import obtenir_pokemon_par_nom, sprite_pokemon  # noqa: E402

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
WEB_SECRET = os.environ.get("WEB_SECRET") or secrets.token_hex(32)  # éphémère si non défini
WEB_DEV_LOGIN = os.environ.get("WEB_DEV_LOGIN") == "1"
DOSSIER_STATIC = Path(__file__).parent / "web"

_boucles: dict[int, asyncio.Task] = {}


def _lancer_boucle(combat_id: int):
    """Une boucle de résolution par combat web (relancée au démarrage pour les combats actifs)."""
    tache = _boucles.get(combat_id)
    if tache and not tache.done():
        return
    _boucles[combat_id] = asyncio.create_task(combat_service.boucle_combat(combat_id))


@asynccontextmanager
async def lifespan(app: FastAPI):
    combat_service._init_tables()
    exploration_service._init_tables()
    for combat_id in combat_service.combats_web_actifs():
        _lancer_boucle(combat_id)
    boucle_spawns = asyncio.create_task(exploration_service.boucle_spawns())
    yield
    boucle_spawns.cancel()
    for tache in _boucles.values():
        tache.cancel()


app = FastAPI(title="PokéWild", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=WEB_SECRET,
    session_cookie="pokewild_session",
    max_age=60 * 60 * 24 * 14,
    same_site="lax",
    https_only=os.environ.get("WEB_COOKIE_SECURE") == "1",
)


@app.exception_handler(ErreurCombatWeb)
async def _erreur_combat(_: Request, exc: ErreurCombatWeb):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def joueur_connecte(request: Request) -> dict:
    joueur = request.session.get("joueur")
    if not joueur:
        raise HTTPException(status_code=401, detail="Non connecté.")
    return joueur


# ----------------------------------------------------------------------------
# Connexion Discord
# ----------------------------------------------------------------------------

@app.get("/auth/login")
async def auth_login(request: Request):
    if not DISCORD_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Connexion Discord non configurée (DISCORD_CLIENT_ID).")
    etat = secrets.token_urlsafe(24)
    request.session["oauth_state"] = etat
    params = {
        "client_id": DISCORD_CLIENT_ID, "response_type": "code", "scope": "identify",
        "redirect_uri": f"{WEB_BASE_URL}/auth/callback", "state": etat, "prompt": "none",
    }
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{urlencode(params)}")


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = ""):
    attendu = request.session.pop("oauth_state", None)
    if not code or not attendu or not secrets.compare_digest(attendu, state):
        raise HTTPException(status_code=400, detail="Connexion Discord invalide ou expirée, réessaie.")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": f"{WEB_BASE_URL}/auth/callback",
            },
        )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Discord a refusé la connexion.")
        r = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {r.json()['access_token']}"},
        )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Impossible de lire le profil Discord.")
    u = r.json()
    request.session["joueur"] = {
        "id": int(u["id"]),
        "pseudo": u.get("global_name") or u["username"],
        "avatar": (
            f"https://cdn.discordapp.com/avatars/{u['id']}/{u['avatar']}.png?size=64" if u.get("avatar") else None
        ),
    }
    return RedirectResponse("/")


@app.get("/auth/dev")
async def auth_dev(request: Request, user_id: int, pseudo: str = "Testeur"):
    """Connexion factice pour tester en local — désactivée sauf WEB_DEV_LOGIN=1."""
    if not WEB_DEV_LOGIN:
        raise HTTPException(status_code=404)
    request.session["joueur"] = {"id": user_id, "pseudo": pseudo, "avatar": None}
    return RedirectResponse("/")


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


# ----------------------------------------------------------------------------
# Profil & équipe
# ----------------------------------------------------------------------------

def _sprites(nom: str) -> dict:
    """URLs des sprites (face + dos) d'une espèce — mêmes sources que le bot Discord."""
    pokemon = obtenir_pokemon_par_nom(nom)
    if not pokemon:
        return {"sprite": None, "sprite_dos": None}
    numero = pokemon.get("numero_sprite") or pokemon["numero"]
    return {"sprite": sprite_pokemon(pokemon), "sprite_dos": combat_visuel._url_sprite_dos(numero)}


def _combat_courant(user_id: int) -> dict:
    row = database.combat_en_cours_pour_joueur(user_id)
    if row is None:
        return {"combat_id": None, "source": None}
    return {"combat_id": row["id"], "source": "web" if combat_service.est_combat_web(row["id"]) else "discord"}


@app.get("/api/moi")
async def api_moi(request: Request):
    joueur = joueur_connecte(request)
    xp = database.obtenir_xp(joueur["id"])
    niveau, xp_dans_niveau, xp_requise = leveling.progression_niveau(xp)
    return {
        **joueur,
        "poke_dollars": database.obtenir_poke_dollars(joueur["id"]),
        "niveau": niveau, "xp": xp_dans_niveau, "xp_requise": xp_requise,
        "combat": _combat_courant(joueur["id"]),
    }


@app.get("/api/equipe")
async def api_equipe(request: Request):
    joueur = joueur_connecte(request)
    uid = joueur["id"]
    possedes = {row["pokemon_nom"] for row in database.obtenir_pokedex_joueur(uid)}
    equipe = []
    for nom in database.obtenir_equipe_combat_disponible(uid):
        if nom not in possedes:
            continue
        stats = combat_module.stats_combattant_reel(uid, nom)
        equipe.append({
            "nom": nom, "niveau": stats["niveau"], "pv_max": stats["pv"],
            "pv": database.obtenir_pv_actuels(uid, nom, stats["pv"]), **_sprites(nom),
        })
    return {"equipe": equipe}


# ----------------------------------------------------------------------------
# Combats de dresseurs
# ----------------------------------------------------------------------------

class DemandeCombat(BaseModel):
    archetype: str | None = None


class DemandeAction(BaseModel):
    type: str
    valeur: str | None = None
    tour: int | None = None


class DemandeRemplacant(BaseModel):
    nom: str


@app.get("/api/dresseurs")
async def api_dresseurs(request: Request):
    joueur_connecte(request)
    return {"dresseurs": combat_service.archetypes_disponibles()}


@app.post("/api/combats/dresseur")
async def api_lancer_combat(demande: DemandeCombat, request: Request):
    joueur = joueur_connecte(request)
    resultat = await combat_service.demarrer_combat_dresseur(
        joueur["id"], joueur["pseudo"], demande.archetype
    )
    _lancer_boucle(resultat["combat_id"])
    return resultat


def _enrichir(etat: dict) -> dict:
    for cote in ("moi", "adversaire"):
        for p in etat[cote]["equipe"]:
            p.update(_sprites(p["nom"]))
    return etat


@app.get("/api/combats/{combat_id}")
async def api_etat_combat(combat_id: int, request: Request):
    joueur = joueur_connecte(request)
    return _enrichir(combat_service.etat_combat(combat_id, joueur["id"]))


@app.post("/api/combats/{combat_id}/action")
async def api_action(combat_id: int, demande: DemandeAction, request: Request):
    joueur = joueur_connecte(request)
    return combat_service.soumettre_action(combat_id, joueur["id"], demande.type, demande.valeur, demande.tour)


@app.post("/api/combats/{combat_id}/mega")
async def api_mega(combat_id: int, request: Request):
    joueur = joueur_connecte(request)
    return combat_service.mega_evoluer(combat_id, joueur["id"])


@app.post("/api/combats/{combat_id}/remplacant")
async def api_remplacant(combat_id: int, demande: DemandeRemplacant, request: Request):
    joueur = joueur_connecte(request)
    return combat_service.choisir_remplacant_ko(combat_id, joueur["id"], demande.nom)


@app.post("/api/combats/{combat_id}/abandon")
async def api_abandon(combat_id: int, request: Request):
    joueur = joueur_connecte(request)
    return combat_service.abandonner(combat_id, joueur["id"])



# ----------------------------------------------------------------------------
# Gestion du compte : équipe, soins, attaques, inventaire, Pokédex
# ----------------------------------------------------------------------------

class DemandeNom(BaseModel):
    nom: str


class DemandeDeplacer(BaseModel):
    nom: str
    direction: int


class DemandeSoin(BaseModel):
    nom: str
    potion: str


class DemandeAttaque(BaseModel):
    nom: str
    slot: int
    attaque: str | None = None


class DemandeCT(BaseModel):
    attaque: str


class DemandeSuppression(BaseModel):
    cle: str
    quantite: int


def _equipe_enrichie(uid: int) -> dict:
    etat = gestion_service.etat_equipe(uid)
    for p in etat["equipe"]:
        p.update(_sprites(p["nom"]))
    return etat


@app.get("/api/gestion/equipe")
async def api_gestion_equipe(request: Request):
    return _equipe_enrichie(joueur_connecte(request)["id"])


@app.get("/api/gestion/especes")
async def api_gestion_especes(request: Request, tri: str = "alphabetique", q: str = ""):
    uid = joueur_connecte(request)["id"]
    especes = gestion_service.especes_possedees(uid, tri, q)
    for e in especes:
        e.update(_sprites(e["nom"]))
    return {"especes": especes}


@app.post("/api/gestion/equipe/ajouter")
async def api_equipe_ajouter(d: DemandeNom, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.ajouter_equipe(uid, d.nom)
    return _equipe_enrichie(uid)


@app.post("/api/gestion/equipe/retirer")
async def api_equipe_retirer(d: DemandeNom, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.retirer_equipe(uid, d.nom)
    return _equipe_enrichie(uid)


@app.post("/api/gestion/equipe/deplacer")
async def api_equipe_deplacer(d: DemandeDeplacer, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.deplacer_equipe(uid, d.nom, d.direction)
    return _equipe_enrichie(uid)


@app.post("/api/gestion/equipe/auto")
async def api_equipe_auto(request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.equipe_auto(uid)
    return _equipe_enrichie(uid)


@app.get("/api/gestion/presets")
async def api_presets(request: Request):
    return {"presets": gestion_service.apercu_presets(joueur_connecte(request)["id"])}


@app.post("/api/gestion/presets/sauvegarder")
async def api_preset_sauver(d: DemandeNom, request: Request):
    gestion_service.sauvegarder_preset(joueur_connecte(request)["id"], d.nom)
    return {"presets": gestion_service.apercu_presets(joueur_connecte(request)["id"])}


@app.post("/api/gestion/presets/charger")
async def api_preset_charger(d: DemandeNom, request: Request):
    uid = joueur_connecte(request)["id"]
    res = gestion_service.charger_preset(uid, d.nom)
    return {**_equipe_enrichie(uid), **res}


@app.post("/api/gestion/presets/supprimer")
async def api_preset_supprimer(d: DemandeNom, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.supprimer_preset(uid, d.nom)
    return {"presets": gestion_service.apercu_presets(uid)}


@app.post("/api/gestion/soigner")
async def api_soigner(d: DemandeSoin, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.soigner(uid, d.nom, d.potion)
    return _equipe_enrichie(uid)


@app.post("/api/gestion/soin-auto")
async def api_soin_auto(request: Request):
    uid = joueur_connecte(request)["id"]
    res = gestion_service.soin_auto(uid)
    return {**_equipe_enrichie(uid), **res}


@app.get("/api/gestion/attaques/{nom}")
async def api_attaques(nom: str, request: Request):
    return gestion_service.attaques_pokemon(joueur_connecte(request)["id"], nom)


@app.post("/api/gestion/attaques/equiper")
async def api_attaque_equiper(d: DemandeAttaque, request: Request):
    uid = joueur_connecte(request)["id"]
    if not d.attaque:
        raise ErreurCombatWeb("Choisis une attaque.")
    gestion_service.equiper_attaque(uid, d.nom, d.slot, d.attaque)
    return gestion_service.attaques_pokemon(uid, d.nom)


@app.post("/api/gestion/attaques/vider")
async def api_attaque_vider(d: DemandeAttaque, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.vider_attaque(uid, d.nom, d.slot)
    return gestion_service.attaques_pokemon(uid, d.nom)


@app.post("/api/gestion/attaques/aleatoires")
async def api_attaque_alea(d: DemandeNom, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.attaques_aleatoires(uid, d.nom)
    return gestion_service.attaques_pokemon(uid, d.nom)


@app.post("/api/gestion/ct/acheter")
async def api_ct_acheter(d: DemandeCT, request: Request):
    return gestion_service.acheter_ct(joueur_connecte(request)["id"], d.attaque)


@app.get("/api/gestion/inventaire")
async def api_inventaire(request: Request):
    return gestion_service.inventaire_joueur(joueur_connecte(request)["id"])


@app.post("/api/gestion/inventaire/supprimer")
async def api_inventaire_suppr(d: DemandeSuppression, request: Request):
    uid = joueur_connecte(request)["id"]
    gestion_service.supprimer_objet(uid, d.cle, d.quantite)
    return gestion_service.inventaire_joueur(uid)


@app.get("/api/gestion/pokedex")
async def api_pokedex(request: Request):
    uid = joueur_connecte(request)["id"]
    res = gestion_service.pokedex_joueur(uid)
    for e in res["entrees"]:
        e.update(_sprites(e["nom"]))
    return res



# ----------------------------------------------------------------------------
# Explorer : apparitions, capture, PokéStop
# ----------------------------------------------------------------------------

class DemandeCapture(BaseModel):
    spawn_id: int
    ball: str


@app.get("/api/explorer/spawns")
async def api_spawns(request: Request):
    uid = joueur_connecte(request)["id"]
    spawns = exploration_service.spawns_actifs(uid)
    for s in spawns:
        s.update(_sprites(s["nom"]))
    inv = database.obtenir_inventaire_balls(uid)
    balls = [
        {"cle": b, "nom": gestion_service.inventaire.NOMS_OBJETS.get(b, b), "quantite": inv.get(b, 0)}
        for b in exploration_service.BALLS_CAPTURE
    ]
    return {"spawns": spawns, "balls": balls}


@app.post("/api/explorer/capturer")
async def api_capturer(d: DemandeCapture, request: Request):
    uid = joueur_connecte(request)["id"]
    res = exploration_service.capturer(uid, d.spawn_id, d.ball)
    res.update(_sprites(res["nom"]))
    return res


@app.get("/api/explorer/pokestop")
async def api_pokestop_etat(request: Request):
    return exploration_service.pokestop_etat(joueur_connecte(request)["id"])


@app.post("/api/explorer/pokestop")
async def api_pokestop(request: Request):
    return exploration_service.pokestop_tourner(joueur_connecte(request)["id"])



# ----------------------------------------------------------------------------
# Centre des Explorations
# ----------------------------------------------------------------------------

class DemandeExpedition(BaseModel):
    slot: int
    destination: str
    pokemon: list[str]
    duree: str


class DemandeRecuperation(BaseModel):
    slot: int | None = None


@app.get("/api/expeditions")
async def api_expeditions(request: Request):
    etat = expedition_service.etat(joueur_connecte(request)["id"])
    for e in etat["especes"]:
        e.update(_sprites(e["nom"]))
    return etat


@app.post("/api/expeditions/demarrer")
async def api_expedition_demarrer(d: DemandeExpedition, request: Request):
    return expedition_service.demarrer(joueur_connecte(request)["id"], d.slot, d.destination, d.pokemon, d.duree)


@app.post("/api/expeditions/recuperer")
async def api_expedition_recuperer(d: DemandeRecuperation, request: Request):
    return expedition_service.recuperer(joueur_connecte(request)["id"], d.slot)


@app.post("/api/expeditions/acheter-slot")
async def api_expedition_slot(request: Request):
    return expedition_service.acheter_slot(joueur_connecte(request)["id"])



# ----------------------------------------------------------------------------
# Boutique & Marché Noir
# ----------------------------------------------------------------------------

class DemandeAchat(BaseModel):
    categorie: str
    cle: str
    quantite: int = 1


class DemandeExtension(BaseModel):
    type: str
    paliers: int = 1


class DemandeMarcheNoir(BaseModel):
    type: str
    cle: str
    quantite: int = 1


@app.get("/api/boutique")
async def api_boutique(request: Request):
    return boutique_service.catalogue(joueur_connecte(request)["id"])


@app.post("/api/boutique/acheter")
async def api_boutique_acheter(d: DemandeAchat, request: Request):
    return boutique_service.acheter(joueur_connecte(request)["id"], d.categorie, d.cle, d.quantite)


@app.post("/api/boutique/extension")
async def api_boutique_extension(d: DemandeExtension, request: Request):
    return boutique_service.acheter_extension(joueur_connecte(request)["id"], d.type, d.paliers)


@app.post("/api/boutique/slot-exploration")
async def api_boutique_slot(request: Request):
    return expedition_service.acheter_slot(joueur_connecte(request)["id"])


@app.post("/api/boutique/marche-noir")
async def api_boutique_marche_noir(d: DemandeMarcheNoir, request: Request):
    return boutique_service.acheter_marche_noir(joueur_connecte(request)["id"], d.type, d.cle, d.quantite)



# ----------------------------------------------------------------------------
# Laboratoire : incubateur, transformateur, caisson, mutation
# ----------------------------------------------------------------------------

class DemandePalier(BaseModel):
    palier: str


class DemandeTransformation(BaseModel):
    source: str
    lots: int


class DemandeSlot(BaseModel):
    slot: int


@app.get("/api/labo/incubateur")
async def api_labo_incubateur(request: Request):
    return laboratoire_service.etat_incubateur(joueur_connecte(request)["id"])


@app.post("/api/labo/incubateur/incuber")
async def api_labo_incuber(d: DemandePalier, request: Request):
    return laboratoire_service.incuber(joueur_connecte(request)["id"], d.palier)


@app.post("/api/labo/incubateur/eclore")
async def api_labo_eclore(request: Request):
    res = laboratoire_service.eclore(joueur_connecte(request)["id"])
    res.update(_sprites(res["nom"]))
    return res


@app.get("/api/labo/transformateur")
async def api_labo_transformateur(request: Request):
    return laboratoire_service.etat_transformateur(joueur_connecte(request)["id"])


@app.post("/api/labo/transformateur")
async def api_labo_transformer(d: DemandeTransformation, request: Request):
    return laboratoire_service.transformer(joueur_connecte(request)["id"], d.source, d.lots)


@app.get("/api/labo/caisson")
async def api_labo_caisson(request: Request, tri: str = "alphabetique", q: str = ""):
    return laboratoire_service.etat_caisson(joueur_connecte(request)["id"], tri, q)


@app.post("/api/labo/caisson/deposer")
async def api_labo_deposer(d: DemandeNom, request: Request):
    return laboratoire_service.deposer_caisson(joueur_connecte(request)["id"], d.nom)


@app.post("/api/labo/caisson/retirer")
async def api_labo_retirer(d: DemandeSlot, request: Request):
    return laboratoire_service.retirer_caisson(joueur_connecte(request)["id"], d.slot)


@app.get("/api/labo/mutation")
async def api_labo_mutation(request: Request):
    return laboratoire_service.etat_mutation(joueur_connecte(request)["id"])


@app.post("/api/labo/mutation")
async def api_labo_muter(request: Request):
    return laboratoire_service.muter(joueur_connecte(request)["id"])


# ----------------------------------------------------------------------------
# Site (page unique)
# ----------------------------------------------------------------------------

@app.get("/")
async def accueil():
    return FileResponse(DOSSIER_STATIC / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)  # pas d'icône pour l'instant : évite un 404 dans la console
