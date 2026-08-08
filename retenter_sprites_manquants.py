"""
Script CIBLÉ — ne retraite QUE les espèces déjà marquées sprite_gif_disponible=False
(coincées sur l'artwork statique), pour vérifier si un sprite animé est devenu
disponible depuis (le pack communautaire Showdown/PokéAPI est mis à jour au fil du
temps, notamment pour les espèces récentes qui n'y étaient pas encore lors du premier
passage). Beaucoup plus rapide que de relancer corriger_sprites.py --forcer sur tout le
Pokédex : ne retente que les cas connus comme problématiques.

Réutilise directement la logique de téléchargement/correction de corriger_sprites.py
(aucune duplication) — un Pokémon qui obtient enfin son sprite animé voit son
sprite_gif_disponible repassé à True dans pokedex_complet.json.

Utilisation :
    pip install requests Pillow
    py retenter_sprites_manquants.py
"""

import json

from corriger_sprites import corriger_pokemon

CHEMIN_JSON = "pokedex_complet.json"


def main():
    with open(CHEMIN_JSON, encoding="utf-8") as f:
        dex = json.load(f)

    a_retenter = [p for p in dex if p.get("sprite_gif_disponible") is False]
    if not a_retenter:
        print("Aucune espèce actuellement marquée sans sprite animé — rien à retenter.")
        return

    print(f"{len(a_retenter)} espèce(s) actuellement sur l'artwork statique — nouvelle tentative...")
    recuperees = []

    for i, pokemon in enumerate(a_retenter, start=1):
        numero = pokemon.get("numero_sprite") or pokemon.get("numero")
        if not numero:
            continue

        resultat_normal = corriger_pokemon(numero, shiny=False, forcer=True)
        resultat_shiny = corriger_pokemon(numero, shiny=True, forcer=True)

        if resultat_normal in ("ok", "deja_fait"):
            pokemon["sprite_gif_disponible"] = True
            recuperees.append(pokemon["nom"])

        if i % 20 == 0 or i == len(a_retenter):
            print(f"  ... {i}/{len(a_retenter)}")

    with open(CHEMIN_JSON, "w", encoding="utf-8") as f:
        json.dump(dex, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(recuperees)} espèce(s) ont récupéré leur sprite animé :")
    for nom in recuperees:
        print(f"   {nom}")

    toujours_absentes = len(a_retenter) - len(recuperees)
    print(f"\n{toujours_absentes} espèce(s) toujours sans sprite animé (rien à faire, artwork statique conservé).")
    print("N'oublie pas de committer sprites_corriges/ sur GitHub, puis relancer le bot.")


if __name__ == "__main__":
    main()
