"""
Ajoute le niveau d'apprentissage (level-up) de chaque attaque à chaque entrée de
pokedex_complet.json, sous la clé "movepool_niveaux" (nom d'attaque FR -> niveau minimum).

Les attaques qui n'apprennent JAMAIS par montée de niveau (CT/tuteur/œuf uniquement)
n'apparaissent pas dans ce dict — elles restent apprenables sans restriction de niveau
pour l'instant (la restriction "il faut la CT" arrive avec le Maître des Types payant).

Comme maj_stats.py : un seul appel /pokemon/{id} par Pokémon, garde ce qui existe déjà
en base sauf --forcer, reprise possible en cas d'échec partiel.

Utilisation :
    pip install requests
    py maj_movepool.py [--forcer]
"""

import json
import sys
import time

import requests

from generer_pokedex import recuperer_attaque

BASE_URL = "https://pokeapi.co/api/v2"
CHEMIN_JSON = "pokedex_complet.json"


def recuperer_movepool_anglais(numero: int):
    """Retourne {nom_anglais: niveau_minimum} pour les attaques apprises par montée de
    niveau (method 'level-up'), tous groupes de version confondus (le niveau le plus bas
    trouvé est gardé)."""
    reponse = requests.get(f"{BASE_URL}/pokemon/{numero}")
    if reponse.status_code != 200:
        return None

    movepool = {}
    for entree in reponse.json().get("moves", []):
        nom_anglais = entree["move"]["name"]
        for detail in entree.get("version_group_details", []):
            if detail["move_learn_method"]["name"] != "level-up":
                continue
            niveau = detail["level_learned_at"]
            if niveau <= 0:
                continue
            if nom_anglais not in movepool or niveau < movepool[nom_anglais]:
                movepool[nom_anglais] = niveau
    return movepool


def main():
    forcer = "--forcer" in sys.argv

    with open(CHEMIN_JSON, "r", encoding="utf-8") as f:
        pokedex = json.load(f)

    a_traiter = [p for p in pokedex if forcer or "movepool_niveaux" not in p]
    if not a_traiter:
        print("Tous les Pokémon ont déjà leur movepool par niveau. Utilise --forcer pour tout re-télécharger.")
        return

    print(f"Récupération des niveaux d'apprentissage pour {len(a_traiter)}/{len(pokedex)} Pokémon...")

    # --- Passe 1 : movepool en anglais par Pokémon ---
    echecs = []
    noms_anglais_uniques = set()
    for i, pokemon in enumerate(a_traiter, start=1):
        numero = pokemon.get("numero")
        if not numero:
            continue
        movepool = recuperer_movepool_anglais(numero)
        if movepool is None:
            echecs.append(numero)
        else:
            pokemon["_movepool_anglais"] = movepool
            noms_anglais_uniques.update(movepool.keys())
        if i % 50 == 0 or i == len(a_traiter):
            print(f"  ... {i}/{len(a_traiter)}")
        time.sleep(0.05)

    # --- Passe 2 : traduction des noms d'attaques anglais -> français (une fois chacun) ---
    print(f"\nTraduction de {len(noms_anglais_uniques)} attaques uniques...")
    traduction = {}
    for i, nom_anglais in enumerate(sorted(noms_anglais_uniques), start=1):
        resultat = recuperer_attaque(nom_anglais)
        if resultat:
            nom_fr, _details = resultat
            traduction[nom_anglais] = nom_fr
        if i % 100 == 0:
            print(f"  ... {i}/{len(noms_anglais_uniques)}")
        time.sleep(0.05)

    # --- Passe 3 : assemblage final en français ---
    for pokemon in a_traiter:
        movepool_anglais = pokemon.pop("_movepool_anglais", None)
        if movepool_anglais is None:
            continue
        pokemon["movepool_niveaux"] = {
            traduction[nom_en]: niveau
            for nom_en, niveau in movepool_anglais.items()
            if nom_en in traduction
        }

    with open(CHEMIN_JSON, "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Movepool par niveau ajouté à {len(a_traiter) - len(echecs)}/{len(a_traiter)} Pokémon traités.")
    if echecs:
        print(f"⚠️ Échecs (relance le script, il ne retentera que ceux-ci) : {echecs}")
    print("Relance le bot pour en tenir compte.")


if __name__ == "__main__":
    main()
