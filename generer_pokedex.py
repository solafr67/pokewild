"""
Script à lancer UNE SEULE FOIS pour générer la base de données complète
des Pokémon (toutes générations) à partir de la PokéAPI (https://pokeapi.co).

Utilisation :
    pip install requests
    py generer_pokedex.py

Ça crée un fichier `pokedex_complet.json` que le bot chargera automatiquement.
Ça prend quelques minutes (environ 1300 Pokémon, 2 requêtes chacun).
"""

import json
import time

import requests

BASE_URL = "https://pokeapi.co/api/v2"
NOMBRE_MAX_POKEMON = 1025  # couvre toutes les générations parues à ce jour

# Traduction des types anglais (renvoyés par l'API) vers le français utilisé dans le bot
TRADUCTION_TYPES = {
    "normal": "normal",
    "fire": "feu",
    "water": "eau",
    "electric": "electrik",
    "grass": "plante",
    "ice": "glace",
    "fighting": "combat",
    "poison": "poison",
    "ground": "sol",
    "flying": "vol",
    "psychic": "psy",
    "bug": "insecte",
    "rock": "roche",
    "ghost": "spectre",
    "dragon": "dragon",
    "dark": "tenebres",
    "steel": "acier",
    "fairy": "fee",
}


# Traduction des noms de génération renvoyés par l'API vers un simple numéro
GENERATION_MAP = {
    "generation-i": 1,
    "generation-ii": 2,
    "generation-iii": 3,
    "generation-iv": 4,
    "generation-v": 5,
    "generation-vi": 6,
    "generation-vii": 7,
    "generation-viii": 8,
    "generation-ix": 9,
}

# Ultra-Chimères (Gen 7) et Pokémon Paradoxe (Gen 9) : classés Hyper Rare quelle que
# soit leur statut légendaire officiel dans la PokéAPI, pour rester cohérents avec les
# vrais pseudo-légendaires du jeu plutôt que la catégorie Légendaire pure.
ID_ULTRA_CHIMERES_ET_PARADOXE = {
    # Ultra-Chimères
    793, 794, 795, 796, 797, 798, 799, 803, 804, 805, 806,
    # Pokémon Paradoxe (hors Koraidon/Miraidon, qui restent de vrais légendaires)
    984, 985, 986, 987, 988, 989, 990, 991, 992, 993, 994, 995,
    1005, 1006, 1009, 1010, 1020, 1021, 1022, 1023,
}


def determiner_rarete(pokedex_id: int, est_legendaire: bool, est_mythique: bool, total_stats: int) -> str:
    if pokedex_id in ID_ULTRA_CHIMERES_ET_PARADOXE:
        return "hyper_rare"
    if est_legendaire or est_mythique:
        return "legendaire"
    if total_stats >= 580:  # pseudo-légendaires (Dracolosse, Tyranocif, Carchacrok...)
        return "hyper_rare"
    if total_stats >= 500:
        return "rare"
    if total_stats >= 400:
        return "peu_commun"
    return "commun"


SHOWDOWN_SPRITE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/showdown/{numero}.gif"


def verifier_sprite_showdown_existe(pokedex_id: int) -> bool:
    """Vérifie que le sprite animé style Showdown existe vraiment pour ce numéro, plutôt
    que de supposer que oui — ce pack n'a jamais été dessiné pour une bonne partie des
    Pokémon Gen 9 récents (base + DLC), et une URL construite dans le vide ne s'affiche
    simplement pas côté Discord, sans erreur visible."""
    try:
        reponse = requests.head(SHOWDOWN_SPRITE_URL.format(numero=pokedex_id), timeout=5, allow_redirects=True)
        return reponse.status_code == 200
    except requests.RequestException:
        return False  # en cas de doute (timeout, etc.), on retombe sur le sprite statique


def recuperer_pokemon(pokedex_id: int):
    """Récupère types + stats depuis /pokemon/{id}, et le statut légendaire depuis /pokemon-species/{id}."""
    reponse_pokemon = requests.get(f"{BASE_URL}/pokemon/{pokedex_id}")
    if reponse_pokemon.status_code != 200:
        return None
    data_pokemon = reponse_pokemon.json()

    reponse_espece = requests.get(f"{BASE_URL}/pokemon-species/{pokedex_id}")
    if reponse_espece.status_code != 200:
        return None
    data_espece = reponse_espece.json()

    # Noms anglais de toutes les attaques apprenables (traduits plus tard en une passe)
    noms_moves_anglais = [m["move"]["name"] for m in data_pokemon.get("moves", [])]

    types = [TRADUCTION_TYPES.get(t["type"]["name"], t["type"]["name"]) for t in data_pokemon["types"]]
    total_stats = sum(s["base_stat"] for s in data_pokemon["stats"])
    rarete = determiner_rarete(
        pokedex_id, data_espece["is_legendary"], data_espece["is_mythical"], total_stats
    )

    # Sprite animé (disponible jusqu'à la génération 5) avec repli sur le sprite fixe
    sprite_url = data_pokemon["sprites"]["front_default"]
    try:
        sprite_anime = (
            data_pokemon["sprites"]["versions"]["generation-v"]["black-white"]["animated"]["front_default"]
        )
        if sprite_anime:
            sprite_url = sprite_anime
    except (KeyError, TypeError):
        pass

    sprite_shiny_url = data_pokemon["sprites"].get("front_shiny")
    try:
        sprite_shiny_anime = (
            data_pokemon["sprites"]["versions"]["generation-v"]["black-white"]["animated"]["front_shiny"]
        )
        if sprite_shiny_anime:
            sprite_shiny_url = sprite_shiny_anime
    except (KeyError, TypeError):
        pass

    # Le bot préfère le sprite ANIMÉ style Showdown (toutes générations) à celui-ci, mais ce
    # pack communautaire n'a jamais été dessiné pour une bonne partie des Pokémon Gen 9
    # récents (base + DLC) — sans vérification, l'URL construite à partir du numéro pointe
    # dans le vide et l'image ne s'affiche tout simplement pas. On vérifie une fois ici, à la
    # génération, pour ne pas avoir à le refaire à chaque affichage en jeu.
    sprite_anime_disponible = verifier_sprite_showdown_existe(pokedex_id)

    generation = GENERATION_MAP.get(data_espece["generation"]["name"], 0)

    # Nom en français si disponible, sinon nom anglais par défaut
    nom_francais = data_pokemon["name"].capitalize()
    for entree in data_espece.get("names", []):
        if entree["language"]["name"] == "fr":
            nom_francais = entree["name"]
            break

    return {
        "nom": nom_francais,
        "numero": pokedex_id,
        "types": types,
        "rarete": rarete,
        "base_pc": total_stats,  # utilisé directement comme base pour le calcul de PC en jeu
        "sprite": sprite_url,
        "sprite_shiny": sprite_shiny_url,
        "sprite_anime_disponible": sprite_anime_disponible,
        "generation": generation,
        "_moves_anglais": noms_moves_anglais,  # temporaire, remplacé par "attaques" (noms FR) en fin de script
    }


# Mapping des stats PokéAPI vers les 3 stats simplifiées du bot
TRADUCTION_STATS = {
    "attack": "atk",
    "special-attack": "atk",
    "defense": "def",
    "special-defense": "def",
    "speed": "vit",
}


def recuperer_attaque(nom_anglais: str):
    """Récupère les détails d'une attaque : nom FR, type, puissance, précision, classe,
    et changements de stats (pour les attaques de statut/boosts)."""
    reponse = requests.get(f"{BASE_URL}/move/{nom_anglais}")
    if reponse.status_code != 200:
        return None
    data = reponse.json()

    nom_francais = data["name"].replace("-", " ").title()
    for entree in data.get("names", []):
        if entree["language"]["name"] == "fr":
            nom_francais = entree["name"]
            break

    type_attaque = TRADUCTION_TYPES.get(data["type"]["name"], data["type"]["name"])
    classe = data["damage_class"]["name"] if data.get("damage_class") else "status"

    # Changements de stats (ex: Danse-Lames +2 Atq, Groz'Yeux -1 Déf adverse)
    changements = []
    for sc in data.get("stat_changes", []):
        stat_simplifiee = TRADUCTION_STATS.get(sc["stat"]["name"])
        if stat_simplifiee:
            changements.append([stat_simplifiee, sc["change"]])

    # Cible simplifiée : boosts sur soi, malus sur l'adversaire
    cible = "soi" if changements and all(delta > 0 for _, delta in changements) else "adversaire"

    # Altération de statut infligée (brûlure, sommeil, paralysie, poison, gel, confusion)
    STATUTS_GERES = {"burn", "poison", "paralysis", "sleep", "freeze", "confusion"}
    ailment = None
    ailment_chance = 0
    meta = data.get("meta") or {}
    if meta.get("ailment") and meta["ailment"]["name"] in STATUTS_GERES:
        ailment = meta["ailment"]["name"]
        ailment_chance = meta.get("ailment_chance", 0)  # 0 = toujours (attaques de statut pur)

    return nom_francais, {
        "type": type_attaque,
        "puissance": data.get("power"),  # None pour les attaques de statut
        "precision": data.get("accuracy"),  # None = ne rate jamais
        "classe": classe,  # physical / special / status
        "stats": changements,
        "cible": cible,
        "ailment": ailment,
        "ailment_chance": ailment_chance,
        "pp": data.get("pp"),  # Points de Pouvoir — nombre d'utilisations avant épuisement en combat
    }


def main():
    pokedex = []
    print(f"Récupération de {NOMBRE_MAX_POKEMON} Pokémon depuis la PokéAPI...")

    for pokedex_id in range(1, NOMBRE_MAX_POKEMON + 1):
        pokemon = recuperer_pokemon(pokedex_id)
        if pokemon:
            pokedex.append(pokemon)
            if pokedex_id % 50 == 0:
                print(f"  ... {pokedex_id}/{NOMBRE_MAX_POKEMON}")
        time.sleep(0.05)  # petite pause pour rester correct envers l'API publique

    # --- Téléchargement de toutes les attaques uniques (une seule requête par attaque) ---
    moves_uniques = set()
    for pokemon in pokedex:
        moves_uniques.update(pokemon["_moves_anglais"])

    print(f"\nRécupération des détails de {len(moves_uniques)} attaques uniques...")
    attaques = {}  # nom_fr -> détails
    traduction_moves = {}  # nom_anglais -> nom_fr
    for i, nom_anglais in enumerate(sorted(moves_uniques), start=1):
        resultat = recuperer_attaque(nom_anglais)
        if resultat:
            nom_fr, details = resultat
            attaques[nom_fr] = details
            traduction_moves[nom_anglais] = nom_fr
        if i % 100 == 0:
            print(f"  ... {i}/{len(moves_uniques)}")
        time.sleep(0.05)

    # Remplacer les noms anglais par les noms français dans chaque Pokémon
    for pokemon in pokedex:
        pokemon["attaques"] = sorted(
            {traduction_moves[m] for m in pokemon.pop("_moves_anglais") if m in traduction_moves}
        )

    with open("pokedex_complet.json", "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)

    with open("attaques_complet.json", "w", encoding="utf-8") as f:
        json.dump(attaques, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Terminé ! {len(pokedex)} Pokémon dans pokedex_complet.json")
    print(f"✅ {len(attaques)} attaques dans attaques_complet.json")
    print("Tu peux maintenant relancer le bot, il chargera automatiquement ces fichiers.")


if __name__ == "__main__":
    main()
