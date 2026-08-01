"""
Diagnostic : repère les entrées du Pokédex qui SE RESSEMBLENT trop pour être un hasard
(même nom une fois qu'on ignore accents/casse/espaces) — symptôme typique : un joueur a
capturé un Pokémon, mais sa fiche affiche quand même "non capturé", parce que sa capture
est liée à une entrée du Pokédex légèrement différente (en toutes lettres) de celle
listée maintenant.

Ne modifie RIEN — affiche juste un rapport. Lance-le, regarde le résultat, et dis-moi ce
qu'il trouve : je te dirai ensuite laquelle des deux entrées garder (généralement celle
qui a le plus de capture liées) et comment fusionner proprement.

Utilisation :
    py verifier_doublons_pokedex.py
"""

import json
import unicodedata
from collections import defaultdict

FICHIER_POKEDEX = "pokedex_complet.json"


def cle_normalisee(nom: str) -> str:
    """Même nom, mais sans accents/casse/espaces superflus — deux entrées avec la même
    clé normalisée sont presque sûrement censées être LA MÊME espèce."""
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", nom) if not unicodedata.combining(c))
    return sans_accents.lower().strip()


def main():
    with open(FICHIER_POKEDEX, encoding="utf-8") as f:
        pokedex = json.load(f)

    groupes = defaultdict(list)
    for p in pokedex:
        groupes[cle_normalisee(p["nom"])].append(p["nom"])

    doublons = {cle: noms for cle, noms in groupes.items() if len(set(noms)) > 1}

    if not doublons:
        print(f"✅ Aucun doublon détecté sur {len(pokedex)} entrées — les noms sont tous uniques.")
        return

    print(f"⚠️ {len(doublons)} groupe(s) de doublons potentiels trouvés sur {len(pokedex)} entrées :\n")
    for cle, noms in doublons.items():
        print(f"  - {' / '.join(repr(n) for n in noms)}")

    print(
        "\nCopie-moi cette liste — je te dirai laquelle des deux entrées garder "
        "(généralement celle qui a déjà des captures liées) et comment merger proprement "
        "les captures existantes vers cette entrée."
    )


if __name__ == "__main__":
    main()
