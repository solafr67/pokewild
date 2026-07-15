"""
Met à jour UNIQUEMENT attaques_complet.json (ajoute les altérations de statut),
sans re-télécharger les 1025 Pokémon. Beaucoup plus rapide que generer_pokedex.py.

Utilisation :
    py maj_attaques.py
"""

import json
import time

import requests

from generer_pokedex import recuperer_attaque

BASE_URL = "https://pokeapi.co/api/v2"


def main():
    print("Récupération de la liste complète des attaques...")
    reponse = requests.get(f"{BASE_URL}/move?limit=2000")
    noms_anglais = [m["name"] for m in reponse.json()["results"]]

    print(f"Téléchargement des détails de {len(noms_anglais)} attaques...")
    attaques = {}
    for i, nom_anglais in enumerate(noms_anglais, start=1):
        resultat = recuperer_attaque(nom_anglais)
        if resultat:
            nom_fr, details = resultat
            attaques[nom_fr] = details
        if i % 100 == 0:
            print(f"  ... {i}/{len(noms_anglais)}")
        time.sleep(0.05)

    with open("attaques_complet.json", "w", encoding="utf-8") as f:
        json.dump(attaques, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(attaques)} attaques mises à jour dans attaques_complet.json")
    print("Relance le bot pour prendre en compte les altérations de statut.")


if __name__ == "__main__":
    main()
