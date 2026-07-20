"""
Corrige la rareté des Ultra-Chimères (Gen 7) et Pokémon Paradoxe (Gen 9) directement dans
pokedex_complet.json, sans tout régénérer. generer_pokedex.py les classe déjà correctement
en Hyper Rare (voir ID_ULTRA_CHIMERES_ET_PARADOXE), mais cette règle a été ajoutée après la
dernière génération complète du fichier — ce script rattrape juste ces entrées-là.

Utilisation :
    py corriger_raretes_chimeres.py
"""

import json

CHEMIN_JSON = "pokedex_complet.json"

# Doit rester identique à ID_ULTRA_CHIMERES_ET_PARADOXE dans generer_pokedex.py
ID_ULTRA_CHIMERES_ET_PARADOXE = {
    # Ultra-Chimères
    793, 794, 795, 796, 797, 798, 799, 803, 804, 805, 806,
    # Pokémon Paradoxe (hors Koraidon/Miraidon, qui restent de vrais légendaires)
    984, 985, 986, 987, 988, 989, 990, 991, 992, 993, 994, 995,
    1005, 1006, 1009, 1010, 1020, 1021, 1022, 1023,
}


def main():
    with open(CHEMIN_JSON, "r", encoding="utf-8") as f:
        pokedex = json.load(f)

    corriges = []
    for pokemon in pokedex:
        if pokemon.get("numero") in ID_ULTRA_CHIMERES_ET_PARADOXE and pokemon.get("rarete") != "hyper_rare":
            ancienne = pokemon.get("rarete")
            pokemon["rarete"] = "hyper_rare"
            corriges.append(f"{pokemon['nom']} (#{pokemon['numero']}) : {ancienne} → hyper_rare")

    with open(CHEMIN_JSON, "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)

    if corriges:
        print(f"✅ {len(corriges)} Pokémon corrigés :")
        for ligne in corriges:
            print(f"   {ligne}")
    else:
        print("Rien à corriger — toutes les Ultra-Chimères/Paradoxe sont déjà en Hyper Rare.")
    print("\nRelance le bot pour en tenir compte.")


if __name__ == "__main__":
    main()
