"""
Vérifie, pour chaque Pokémon, si son sprite animé existe vraiment dans sprites_corriges/
sur GitHub (celui que corriger_sprites.py est censé avoir généré). Si le téléchargement
avait échoué à l'époque (typiquement : espèces très récentes/DLC sans sprite Showdown
disponible du tout), aucun fichier n'a été créé pour ce numéro — ce script le détecte et
pose `sprite_gif_disponible: false` sur l'entrée correspondante dans pokedex_complet.json,
pour que le bot bascule automatiquement sur l'artwork officiel statique à la place.

Utilisation :
    pip install requests
    py verifier_sprites_disponibles.py [--forcer]

Sans --forcer, ne revérifie que les Pokémon pas encore marqués (première fois, ou ajoutés
depuis le dernier passage). Avec --forcer, revérifie tout le monde (utile après avoir
relancé corriger_sprites.py pour de nouveaux numéros).
"""

import json
import sys

import requests

CHEMIN_JSON = "pokedex_complet.json"
URL_SPRITE = "https://raw.githubusercontent.com/solafr67/pokewild/main/sprites_corriges/{numero}.gif"


def sprite_existe(numero: int) -> bool:
    try:
        reponse = requests.head(URL_SPRITE.format(numero=numero), timeout=8, allow_redirects=True)
        return reponse.status_code == 200
    except requests.RequestException:
        return True  # panne réseau ponctuelle : on ne marque pas absent à tort, on retentera plus tard


def main():
    forcer = "--forcer" in sys.argv

    with open(CHEMIN_JSON, "r", encoding="utf-8") as f:
        pokedex = json.load(f)

    a_verifier = [p for p in pokedex if forcer or "sprite_gif_disponible" not in p]
    if not a_verifier:
        print("Tous les Pokémon ont déjà été vérifiés. Utilise --forcer pour tout revérifier.")
        return

    print(f"Vérification de {len(a_verifier)}/{len(pokedex)} Pokémon...")
    manquants = []

    for i, pokemon in enumerate(a_verifier, start=1):
        numero = pokemon.get("numero")
        if not numero:
            continue
        disponible = sprite_existe(numero)
        pokemon["sprite_gif_disponible"] = disponible
        if not disponible:
            manquants.append(numero)

        if i % 50 == 0 or i == len(a_verifier):
            print(f"  ... {i}/{len(a_verifier)}")

    with open(CHEMIN_JSON, "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Vérification terminée : {len(manquants)} Pokémon sans sprite animé (basculeront sur l'artwork statique).")
    if manquants:
        print(f"Numéros concernés : {manquants}")
    print("Relance le bot pour en tenir compte.")


if __name__ == "__main__":
    main()
