"""profil_service.py — Profil public d'un joueur : titre, devise, Pokémon en vitrine,
statistiques et badges. Chaque joueur modifie le sien ; tout joueur connecté peut consulter
celui des autres (aucune donnée privée : ni solde, ni sac)."""

import config
import database
import leveling
import quetes as quetes_module
import quetes_service
from combat_service import ErreurCombatWeb
from pokemon_data import POKEDEX, obtenir_pokemon_par_nom

TAILLE_VITRINE = 6
MAX_DEVISE = 80


def _init():
    conn = database.get_connexion()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS profil_infos (user_id INTEGER PRIMARY KEY, devise TEXT NOT NULL DEFAULT '', avatar TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS profil_vitrine (user_id INTEGER NOT NULL, position INTEGER NOT NULL, capture_id INTEGER NOT NULL, PRIMARY KEY (user_id, position))")
        conn.commit()
    finally:
        conn.close()


def noter_avatar(user_id: int, avatar):
    """Mémorise l'avatar Discord à chaque connexion, pour l'afficher sur le profil public."""
    if not avatar:
        return
    _init()
    conn = database.get_connexion()
    try:
        conn.execute("INSERT INTO profil_infos (user_id, avatar) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET avatar = excluded.avatar", (user_id, avatar))
        conn.commit()
    finally:
        conn.close()


def _pseudo(uid: int):
    conn = database.get_connexion()
    try:
        r = conn.execute("SELECT pseudo FROM web_joueurs WHERE user_id = ?", (uid,)).fetchone()
        return r["pseudo"] if r else None
    finally:
        conn.close()


def _vitrine(uid: int) -> list:
    conn = database.get_connexion()
    try:
        rows = conn.execute(
            """SELECT v.position, c.id, c.pokemon_nom, c.pc, c.shiny, c.surnom FROM profil_vitrine v
               JOIN captures c ON c.id = v.capture_id WHERE v.user_id = ? AND c.user_id = ? ORDER BY v.position""", (uid, uid)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        p = obtenir_pokemon_par_nom(r["pokemon_nom"]) or {}
        out.append({"position": r["position"], "capture_id": r["id"], "nom": r["pokemon_nom"], "surnom": r["surnom"],
                    "pc": r["pc"], "shiny": bool(r["shiny"]), "types": p.get("types", []), "rarete": p.get("rarete")})
    return out


def _titre(uid: int):
    actif = database.obtenir_titre_actif(uid)
    if not actif or actif not in quetes_module.ACCOMPLISSEMENTS:
        return None
    valeur = quetes_service._valeurs_accomplissements(uid)[actif]
    palier = quetes_module.palier_atteint(actif, valeur)
    return quetes_module.titre_complet(actif, palier) if palier else None


def profil(uid: int, viewer_id: int) -> dict:
    _init()
    pseudo = _pseudo(uid)
    especes, total = database.obtenir_stats_joueur(uid)
    if pseudo is None and total == 0:
        raise ErreurCombatWeb("Ce joueur est introuvable.")
    captures = database.obtenir_pokedex_joueur(uid)
    shiny = sum(r["quantite"] for r in captures if r["shiny"])
    legendaires = sum(1 for r in captures if (obtenir_pokemon_par_nom(r["pokemon_nom"]) or {}).get("rarete") == "legendaire")
    niveau, xp, requis = leveling.progression_niveau(database.obtenir_xp(uid))
    clan, _, _ = database.obtenir_statut_equipe(uid)
    race_nom, _ = database.obtenir_race(uid)
    conn = database.get_connexion()
    try:
        info = conn.execute("SELECT devise, avatar FROM profil_infos WHERE user_id = ?", (uid,)).fetchone()
        rogue = conn.execute("SELECT meilleur_etage FROM roguelike_records WHERE joueur_id = ?", (uid,)).fetchone()
    except Exception:
        rogue = None
    finally:
        conn.close()
    cx = database.obtenir_statut_connexion(uid)
    try:
        arenes = len(database.obtenir_badges_arene(uid))
        repaires = len(database.obtenir_badges_repaire(uid))
    except Exception:
        arenes = repaires = 0
    achv = quetes_service._accomplissements(uid)
    return {
        "id": str(uid), "moi": uid == viewer_id,
        "pseudo": pseudo or f"Dresseur #{str(uid)[-4:]}",
        "avatar": info["avatar"] if info else None,
        "devise": (info["devise"] if info else "") or "",
        "titre": _titre(uid),
        "niveau": niveau, "xp": xp, "xp_requise": requis,
        "clan": {"nom": clan, "emoji": config.EMOJI_EQUIPES.get(clan, "")} if clan else None,
        "race": race_nom,
        "vitrine": _vitrine(uid),
        "stats": [
            {"cle": "pokedex", "nom": "Pokédex", "valeur": f"{especes} / {len(POKEDEX)}"},
            {"cle": "captures", "nom": "Pokémon capturés", "valeur": total},
            {"cle": "shiny", "nom": "Shiny", "valeur": shiny},
            {"cle": "legendaires", "nom": "Légendaires", "valeur": legendaires},
            {"cle": "pvp", "nom": "Victoires PvP", "valeur": database.obtenir_victoires_pvp(uid)},
            {"cle": "pve", "nom": "Victoires contre dresseurs", "valeur": database.obtenir_victoires_pve(uid)},
            {"cle": "badges", "nom": "Badges d'arène", "valeur": f"{arenes + repaires}"},
            {"cle": "serie", "nom": "Série de connexion", "valeur": f"{cx['streak']} jour(s)"},
            {"cle": "rogue", "nom": "Record roguelike", "valeur": f"étage {rogue['meilleur_etage']}" if rogue else "—"},
        ],
        "titres": [{"cle": c["cle"], "titre": c["titre"], "actif": c["actif"]} for c in achv["categories"] if c["palier"] > 0] if uid == viewer_id else [],
    }


def definir_devise(uid: int, texte: str) -> dict:
    _init()
    texte = " ".join((texte or "").split())[:MAX_DEVISE]
    conn = database.get_connexion()
    try:
        conn.execute("INSERT INTO profil_infos (user_id, devise) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET devise = excluded.devise", (uid, texte))
        conn.commit()
    finally:
        conn.close()
    return profil(uid, uid)


def definir_vitrine(uid: int, capture_ids: list) -> dict:
    _init()
    ids = []
    for c in capture_ids:
        if isinstance(c, int) and c not in ids:
            ids.append(c)
    if len(ids) > TAILLE_VITRINE:
        raise ErreurCombatWeb(f"Ta vitrine contient {TAILLE_VITRINE} Pokémon au maximum.")
    conn = database.get_connexion()
    try:
        for c in ids:
            r = conn.execute("SELECT 1 FROM captures WHERE id = ? AND user_id = ?", (c, uid)).fetchone()
            if r is None:
                raise ErreurCombatWeb("Tu ne possèdes pas l'un de ces Pokémon.")
        conn.execute("DELETE FROM profil_vitrine WHERE user_id = ?", (uid,))
        for pos, c in enumerate(ids):
            conn.execute("INSERT INTO profil_vitrine (user_id, position, capture_id) VALUES (?,?,?)", (uid, pos, c))
        conn.commit()
    finally:
        conn.close()
    return profil(uid, uid)


def candidats(uid: int, recherche: str = "") -> dict:
    """Exemplaires que le joueur peut mettre en vitrine : favoris et plus forts d'abord."""
    terme = recherche.strip().lower()
    conn = database.get_connexion()
    try:
        rows = conn.execute(
            "SELECT id, pokemon_nom, pc, shiny, surnom, favori FROM captures WHERE user_id = ? ORDER BY favori DESC, shiny DESC, pc DESC LIMIT 400", (uid,)).fetchall()
    finally:
        conn.close()
    res = [{"capture_id": r["id"], "nom": r["pokemon_nom"], "surnom": r["surnom"], "pc": r["pc"], "shiny": bool(r["shiny"]), "favori": bool(r["favori"])}
           for r in rows if not terme or terme in r["pokemon_nom"].lower() or terme in (r["surnom"] or "").lower()]
    return {"candidats": res[:60]}
