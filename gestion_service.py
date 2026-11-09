"""gestion_service.py — gestion du compte depuis le site (sans Discord).

Reprend les règles des écrans Discord (/equipe-combat, /inventaire, Maître des Types,
Pokédex) en s'appuyant sur les MÊMES fonctions de base de données : un changement fait
sur le site est immédiatement visible sur Discord, et inversement.
Les erreurs de règle lèvent ErreurCombatWeb (→ HTTP 400 avec un message lisible).
"""

import random

import combat as combat_module
import config
import database
import equipe_combat
import inventaire
from combat_service import ErreurCombatWeb
from pokedex import ORDRE_RARETE
from pokemon_data import (
    ATTAQUES,
    attaque_necessite_ct,
    attaques_apprenables,
    attaques_verrouillees_par_niveau,
    cle_tri_alphabetique_fr,
    obtenir_attaque,
    obtenir_pokemon_par_nom,
    prix_ct,
    toutes_attaques_utilisables,
)

TAILLE_MAX_EQUIPE = database.TAILLE_MAX_EQUIPE_COMBAT
TAILLE_MAX_PRESETS = database.TAILLE_MAX_PRESETS_EQUIPE


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------

def _contexte_pv(user_id: int) -> str:
    """Pool de PV ciblé : celui du raid si le joueur y est engagé (comme sur Discord)."""
    return "raid" if database.joueur_dans_raid_actif(user_id) else "normal"


def _verifier_possede(user_id: int, nom: str) -> dict:
    stats = equipe_combat._stats_par_espece(user_id)
    if nom not in stats:
        raise ErreurCombatWeb("Tu ne possèdes pas ce Pokémon.")
    return stats[nom]


def _verifier_pas_en_combat(user_id: int):
    if database.combat_en_cours_pour_joueur(user_id):
        raise ErreurCombatWeb(
            "Impossible de faire ça pendant un combat — utilise le bouton Potion dans le combat."
        )


def _indisponibles(user_id: int) -> set:
    return database.especes_en_exploration(user_id) | database.especes_en_caisson(user_id)


def _fiche_equipe(user_id: int, nom: str, contexte: str, indispos: set, favoris: dict) -> dict:
    stats = combat_module.stats_combattant_reel(user_id, nom)
    pokemon = obtenir_pokemon_par_nom(nom) or {}
    attaques = database.obtenir_attaques_equipees(user_id, nom)
    return {
        "nom": nom, "niveau": stats["niveau"], "pv_max": stats["pv"],
        "pv": database.obtenir_pv_actuels(user_id, nom, stats["pv"], contexte=contexte),
        "types": pokemon.get("types", []),
        "indisponible": nom in indispos,
        "surnom": (favoris.get(nom) or {}).get("surnom"),
        "nb_attaques": len(attaques),
    }


# ----------------------------------------------------------------------------
# Équipe de combat
# ----------------------------------------------------------------------------

def etat_equipe(user_id: int) -> dict:
    contexte = _contexte_pv(user_id)
    indispos = _indisponibles(user_id)
    favoris = database.obtenir_favori_surnom_par_espece(user_id)
    possedes = equipe_combat._stats_par_espece(user_id)
    equipe = [
        _fiche_equipe(user_id, nom, contexte, indispos, favoris)
        for nom in database.obtenir_equipe_combat(user_id) if nom in possedes
    ]
    return {
        "equipe": equipe, "taille_max": TAILLE_MAX_EQUIPE,
        "en_combat": database.combat_en_cours_pour_joueur(user_id) is not None,
        "presets": database.obtenir_noms_presets_equipe(user_id),
        "taille_max_presets": TAILLE_MAX_PRESETS,
    }


def especes_possedees(user_id: int, tri: str = "alphabetique", recherche: str = "") -> list:
    """Espèces possédées hors équipe (menu d'ajout), avec tri/recherche comme sur Discord."""
    stats = equipe_combat._stats_par_espece(user_id)
    dans_equipe = set(database.obtenir_equipe_combat(user_id))
    indispos = _indisponibles(user_id)
    noms = [n for n in stats if n not in dans_equipe]
    if recherche:
        terme = recherche.strip().lower()
        noms = [n for n in noms if terme in n.lower()]
    if tri == "rarete":
        noms.sort(key=lambda n: (ORDRE_RARETE.get((obtenir_pokemon_par_nom(n) or {}).get("rarete"), 99), n))
    elif tri == "pc_desc":
        noms.sort(key=lambda n: -stats[n]["pc"])
    elif tri == "pc_asc":
        noms.sort(key=lambda n: stats[n]["pc"])
    else:
        noms.sort(key=cle_tri_alphabetique_fr)
    return [
        {
            "nom": n, "pc": stats[n]["pc"], "shiny": stats[n]["shiny"],
            "rarete": (obtenir_pokemon_par_nom(n) or {}).get("rarete"),
            "types": (obtenir_pokemon_par_nom(n) or {}).get("types", []),
            "indisponible": n in indispos,
        }
        for n in noms
    ]


def ajouter_equipe(user_id: int, nom: str):
    _verifier_possede(user_id, nom)
    if nom in database.obtenir_equipe_combat(user_id):
        raise ErreurCombatWeb(f"{nom} est déjà dans ton équipe.")
    if not database.ajouter_a_equipe_combat(user_id, nom):
        raise ErreurCombatWeb(f"Ton équipe est pleine ({TAILLE_MAX_EQUIPE} Pokémon maximum).")


def retirer_equipe(user_id: int, nom: str):
    if not database.retirer_de_equipe_combat(user_id, nom):
        raise ErreurCombatWeb(f"{nom} n'est pas dans ton équipe.")


def deplacer_equipe(user_id: int, nom: str, direction: int):
    if direction not in (-1, 1):
        raise ErreurCombatWeb("Direction invalide.")
    if nom not in database.obtenir_equipe_combat(user_id):
        raise ErreurCombatWeb(f"{nom} n'est pas dans ton équipe.")
    database.deplacer_pokemon_equipe(user_id, nom, direction)


def equipe_auto(user_id: int) -> list:
    return equipe_combat.equiper_meilleure_equipe(user_id)


def sauvegarder_preset(user_id: int, nom_preset: str):
    nom_preset = (nom_preset or "").strip()[:30]
    if not nom_preset:
        raise ErreurCombatWeb("Donne un nom à l'équipe.")
    equipe = database.obtenir_equipe_combat(user_id)
    if not equipe:
        raise ErreurCombatWeb("Ton équipe est vide, rien à sauvegarder.")
    if not database.sauvegarder_preset_equipe(user_id, nom_preset, equipe):
        raise ErreurCombatWeb(f"Tu as déjà {TAILLE_MAX_PRESETS} équipes sauvegardées — supprime-en une.")


def charger_preset(user_id: int, nom_preset: str) -> dict:
    if nom_preset not in database.obtenir_noms_presets_equipe(user_id):
        raise ErreurCombatWeb("Équipe sauvegardée introuvable.")
    charges, manquants = equipe_combat.charger_preset_combat(user_id, nom_preset)
    return {"charges": charges, "manquants": manquants}


def supprimer_preset(user_id: int, nom_preset: str):
    if nom_preset not in database.obtenir_noms_presets_equipe(user_id):
        raise ErreurCombatWeb("Équipe sauvegardée introuvable.")
    database.supprimer_preset_equipe(user_id, nom_preset)


def apercu_presets(user_id: int) -> list:
    return [
        {"nom": n, "pokemon": database.obtenir_preset_equipe(user_id, n)}
        for n in database.obtenir_noms_presets_equipe(user_id)
    ]


# ----------------------------------------------------------------------------
# Soins
# ----------------------------------------------------------------------------

def soigner(user_id: int, nom: str, potion: str) -> dict:
    _verifier_pas_en_combat(user_id)
    if potion not in inventaire.TYPES_POTIONS:
        raise ErreurCombatWeb("Ce n'est pas une potion de soin.")
    if nom not in database.obtenir_equipe_combat(user_id):
        raise ErreurCombatWeb(f"{nom} n'est pas dans ton équipe.")
    _verifier_possede(user_id, nom)
    contexte = _contexte_pv(user_id)
    pv_max = combat_module.stats_combattant_reel(user_id, nom)["pv"]
    if database.obtenir_pv_actuels(user_id, nom, pv_max, contexte=contexte) >= pv_max:
        raise ErreurCombatWeb(f"{nom} est déjà en pleine forme.")
    if not database.retirer_ball(user_id, potion):
        raise ErreurCombatWeb("Tu n'as plus cette potion.")
    delta = max(1, round(pv_max * config.SOIN_POURCENT[potion]))
    pv = database.modifier_pv_pokemon(user_id, nom, delta, pv_max, contexte=contexte)
    return {"nom": nom, "pv": pv, "pv_max": pv_max}


def soin_auto(user_id: int) -> dict:
    _verifier_pas_en_combat(user_id)
    contexte = _contexte_pv(user_id)
    blesses = []
    for nom in database.obtenir_equipe_combat(user_id):
        if nom not in equipe_combat._stats_par_espece(user_id):
            continue
        pv_max = combat_module.stats_combattant_reel(user_id, nom)["pv"]
        pv = database.obtenir_pv_actuels(user_id, nom, pv_max, contexte=contexte)
        if pv < pv_max:
            blesses.append((nom, pv, pv_max))
    if not blesses:
        raise ErreurCombatWeb("Aucun de tes Pokémon d'équipe n'est blessé.")
    lignes, nb = equipe_combat.soigner_toute_equipe_auto(user_id, blesses, contexte=contexte)
    return {"lignes": lignes, "potions_utilisees": nb}


# ----------------------------------------------------------------------------
# Attaques équipées
# ----------------------------------------------------------------------------

def _info_attaque(nom: str, pokemon: dict, niveau: int, possedees: set) -> dict:
    a = obtenir_attaque(nom)
    ct = attaque_necessite_ct(pokemon, nom, niveau)
    return {
        "nom": nom, "type": a.get("type"), "puissance": a.get("puissance"),
        "precision": a.get("precision"), "categorie": a.get("categorie"),
        "necessite_ct": ct, "ct_possedee": nom in possedees,
        "equipable": (not ct) or nom in possedees,
        "prix": prix_ct(nom) if ct else None,
    }


def attaques_pokemon(user_id: int, nom: str) -> dict:
    _verifier_possede(user_id, nom)
    pokemon = obtenir_pokemon_par_nom(nom)
    if not pokemon:
        raise ErreurCombatWeb("Pokémon inconnu.")
    niveau, _ = database.obtenir_niveau_pokemon(user_id, nom)
    possedees = database.obtenir_ct_possedees(user_id)
    equipees = database.obtenir_attaques_equipees(user_id, nom)
    return {
        "nom": nom, "niveau": niveau, "types": pokemon.get("types", []),
        "equipees": {str(s): _info_attaque(a, pokemon, niveau, possedees) for s, a in equipees.items()},
        "disponibles": [_info_attaque(a, pokemon, niveau, possedees) for a in attaques_apprenables(pokemon)],
        "a_venir": [{"nom": n, "niveau": p} for n, p in attaques_verrouillees_par_niveau(pokemon, niveau)],
        "poke_dollars": database.obtenir_poke_dollars(user_id),
    }


def _verifier_attaque_equipable(user_id: int, nom: str, attaque: str):
    pokemon = obtenir_pokemon_par_nom(nom)
    if attaque not in attaques_apprenables(pokemon):
        raise ErreurCombatWeb(f"{nom} ne peut pas apprendre {attaque}.")
    niveau, _ = database.obtenir_niveau_pokemon(user_id, nom)
    if attaque_necessite_ct(pokemon, attaque, niveau) and attaque not in database.obtenir_ct_possedees(user_id):
        raise ErreurCombatWeb(
            f"Tu ne possèdes pas encore la CT de {attaque} — achète-la ({prix_ct(attaque)} PD)."
        )


def equiper_attaque(user_id: int, nom: str, slot: int, attaque: str):
    _verifier_possede(user_id, nom)
    if slot not in (1, 2, 3, 4):
        raise ErreurCombatWeb("Emplacement invalide (1 à 4).")
    for s, a in database.obtenir_attaques_equipees(user_id, nom).items():
        if a == attaque and s != slot:
            raise ErreurCombatWeb(f"{attaque} est déjà équipée dans l'emplacement {s}.")
    _verifier_attaque_equipable(user_id, nom, attaque)
    database.equiper_attaque(user_id, nom, slot, attaque)


def vider_attaque(user_id: int, nom: str, slot: int):
    _verifier_possede(user_id, nom)
    if slot not in (1, 2, 3, 4):
        raise ErreurCombatWeb("Emplacement invalide (1 à 4).")
    database.retirer_attaque(user_id, nom, slot)


def attaques_aleatoires(user_id: int, nom: str):
    _verifier_possede(user_id, nom)
    pokemon = obtenir_pokemon_par_nom(nom)
    niveau, _ = database.obtenir_niveau_pokemon(user_id, nom)
    possedees = database.obtenir_ct_possedees(user_id)
    gratuites = [
        n for n in attaques_apprenables(pokemon)
        if not attaque_necessite_ct(pokemon, n, niveau) or n in possedees
    ]
    off = [n for n in gratuites if ATTAQUES[n].get("puissance")]
    stat = [n for n in gratuites if not ATTAQUES[n].get("puissance")]
    random.shuffle(off)
    random.shuffle(stat)
    tirage = (off[:3] + stat)[:4] if len(off) >= 3 else (off + stat)[:4]
    random.shuffle(tirage)
    for slot, a in enumerate(tirage, start=1):
        database.equiper_attaque(user_id, nom, slot, a)
    for slot in range(len(tirage) + 1, 5):
        database.retirer_attaque(user_id, nom, slot)


def acheter_ct(user_id: int, attaque: str) -> dict:
    if attaque not in toutes_attaques_utilisables():
        raise ErreurCombatWeb("Attaque inconnue.")
    if database.possede_ct(user_id, attaque):
        raise ErreurCombatWeb("Tu possèdes déjà cette CT.")
    cout = prix_ct(attaque)
    if database.obtenir_poke_dollars(user_id) < cout:
        raise ErreurCombatWeb(f"Il te faut {cout} PD pour cette CT.")
    database.ajouter_poke_dollars(user_id, -cout)
    database.acheter_ct(user_id, attaque)
    return {"attaque": attaque, "cout": cout, "poke_dollars": database.obtenir_poke_dollars(user_id)}


# ----------------------------------------------------------------------------
# Inventaire
# ----------------------------------------------------------------------------

def _categorie_objet(cle: str) -> str:
    if cle in config.PRIX_SOINS:
        return "soin"
    if cle.endswith("ball"):
        return "ball"
    return "objet"


def inventaire_joueur(user_id: int) -> dict:
    inv = database.obtenir_inventaire_balls(user_id)
    objets = [
        {
            "cle": cle, "nom": inventaire.NOMS_OBJETS.get(cle, cle), "quantite": q,
            "categorie": _categorie_objet(cle), "potion": cle in inventaire.TYPES_POTIONS,
        }
        for cle, q in sorted(inv.items()) if q > 0
    ]
    return {"objets": objets, "poke_dollars": database.obtenir_poke_dollars(user_id)}


def supprimer_objet(user_id: int, cle: str, quantite: int):
    if quantite < 1:
        raise ErreurCombatWeb("Quantité invalide.")
    if not database.retirer_plusieurs_balls(user_id, cle, quantite):
        raise ErreurCombatWeb("Tu n'en as pas assez.")


# ----------------------------------------------------------------------------
# Pokédex
# ----------------------------------------------------------------------------

def pokedex_joueur(user_id: int) -> dict:
    """Espèces possédées (quantité, meilleur PC, shiny) — vue de collection."""
    par_espece: dict = {}
    for row in database.obtenir_pokedex_joueur(user_id):
        e = par_espece.setdefault(row["pokemon_nom"], {"quantite": 0, "meilleur_pc": 0, "shiny": False})
        e["quantite"] += row["quantite"]
        e["meilleur_pc"] = max(e["meilleur_pc"], row["meilleur_pc"])
        if row["shiny"]:
            e["shiny"] = True
    favoris = database.obtenir_favori_surnom_par_espece(user_id)
    entrees = []
    for nom, e in par_espece.items():
        p = obtenir_pokemon_par_nom(nom) or {}
        niveau, _ = database.obtenir_niveau_pokemon(user_id, nom)
        entrees.append({
            "nom": nom, **e, "niveau": niveau, "rarete": p.get("rarete"), "types": p.get("types", []),
            "numero": p.get("numero"), "favori": bool((favoris.get(nom) or {}).get("favori")),
            "surnom": (favoris.get(nom) or {}).get("surnom"),
        })
    entrees.sort(key=lambda x: (x["numero"] is None, x["numero"] or 0, x["nom"]))
    from pokemon_data import POKEDEX
    return {"entrees": entrees, "total_especes": len(POKEDEX), "possedees": len(entrees)}
