"""
Ajoute les VRAIES stats de base (attaque, défense, attaque spé, défense spé, vitesse, PV)
à chaque entrée de pokedex_complet.json, sous la clé "stats_detaillees".

Jusqu'ici, seul le TOTAL des stats était gardé (utilisé pour le PC) — le détail par stat
était calculé par la PokéAPI mais jeté. Ce script comble ce manque sans tout re-générer :
un seul appel /pokemon/{id} par Pokémon (pas de sprites, pas de traduction d'attaques),
donc beaucoup plus rapide que generer_pokedex.py.

Utilisation :
    pip install requests
    py maj_stats.py
"""

import json
import sys
import time

import requests

BASE_URL = "https://pokeapi.co/api/v2"
CHEMIN_JSON = "pokedex_complet.json"

# PokéAPI -> clés utilisées côté bot (distinctes des clés "atk"/"def"/"vit" déjà utilisées
# pour les stages de boost en combat, pour ne pas les confondre)
TRADUCTION_STATS_DETAILLEES = {
    "hp": "pv",
    "attack": "attaque",
    "defense": "defense",
    "special-attack": "attaque_spe",
    "special-defense": "defense_spe",
    "speed": "vitesse",
}


def recuperer_stats(numero: int):
    reponse = requests.get(f"{BASE_URL}/pokemon/{numero}")
    if reponse.status_code != 200:
        return None
    data = reponse.json()
    return {
        TRADUCTION_STATS_DETAILLEES[s["stat"]["name"]]: s["base_stat"]
        for s in data["stats"]
        if s["stat"]["name"] in TRADUCTION_STATS_DETAILLEES
    }


def main():
    forcer = "--forcer" in sys.argv

    with open(CHEMIN_JSON, "r", encoding="utf-8") as f:
        pokedex = json.load(f)

    a_traiter = [p for p in pokedex if forcer or not p.get("stats_detaillees")]
    if not a_traiter:
        print("Tous les Pokémon ont déjà leurs stats détaillées. Utilise --forcer pour tout re-télécharger.")
        return

    print(f"Récupération des stats détaillées pour {len(a_traiter)}/{len(pokedex)} Pokémon...")
    echecs = []

    for i, pokemon in enumerate(a_traiter, start=1):
        numero = pokemon.get("numero")
        if not numero:
            continue

        stats = recuperer_stats(numero)
        if stats is None:
            echecs.append(numero)
        else:
            pokemon["stats_detaillees"] = stats

        if i % 50 == 0 or i == len(a_traiter):
            print(f"  ... {i}/{len(a_traiter)}")

        time.sleep(0.05)

    with open(CHEMIN_JSON, "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Stats détaillées ajoutées à {len(a_traiter) - len(echecs)}/{len(a_traiter)} Pokémon traités.")
    if echecs:
        print(f"⚠️ Échecs (relance le script, il ne retentera que ceux-ci) : {echecs}")
    print("Relance le bot pour en tenir compte.")


if __name__ == "__main__":
    main()
