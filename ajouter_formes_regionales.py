"""
Script à lancer UNE SEULE FOIS (relançable sans risque, idempotent — voir plus bas)
pour ajouter les FORMES RÉGIONALES au Pokédex : Alola (Sun/Moon), Galar (Épée/Bouclier),
Hisui (Légendes Arceus) et Paldea (Écarlate/Violet).

Principe retenu (validé avec l'utilisateur) :
- Chaque forme régionale devient une ENTRÉE DE POKÉDEX À PART ENTIÈRE (nom distinct),
  capturable et suivie séparément de sa forme de base — capturer Ramoloss ET Ramoloss de
  Galar compte pour 2 entrées différentes dans le Pokédex du joueur.
- Elle garde le même "numero" (numéro de Pokédex NATIONAL) que sa forme de base — ex:
  Ramoloss ET Ramoloss de Galar sont tous les deux "numero": 79, exactement comme dans un
  vrai Pokédex (Bulbapedia/Serebii). Ça les regroupe automatiquement l'une à côté de
  l'autre partout où le Pokédex trie par numéro.
- Elle a un "numero_sprite" DISTINCT (le vrai identifiant PokéAPI propre à cette forme,
  ex: 10164 pour Ramoloss de Galar) — sans ça, sprite_pokemon() afficherait le sprite de
  la forme de base pour les deux, puisque "numero" est partagé. Voir pokemon_data.py.
- Rareté calculée avec EXACTEMENT la même règle que generer_pokedex.py pour rester
  cohérent avec le reste du jeu (légendaire/mythique -> legendaire ; total de stats >=580
  -> hyper_rare ; >=500 -> rare ; >=400 -> peu_commun ; sinon commun).

⚠️ IMPORTANT — sprites : ce script ajoute les DONNÉES (types, stats, rareté...), mais les
sprites animés eux-mêmes ne sont pas encore dans sprites_corriges/ tant que
corriger_sprites.py n'a pas été relancé (il a été mis à jour pour aussi traiter
numero_sprite). Étapes complètes :
    1. py ajouter_formes_regionales.py     (ce script — ajoute les données)
    2. py corriger_sprites.py              (télécharge + corrige les nouveaux sprites)
    3. py verifier_sprites_disponibles.py  (marque ceux qui n'existent pas côté Showdown)
    4. Committer sprites_corriges/ sur GitHub, puis déployer normalement.

Portée : les 18 formes d'Alola + les 17 formes de Galar (dont les 3 oiseaux légendaires) +
les 6 espèces qui évoluent EXCLUSIVEMENT depuis une forme de Galar (Ixon, Sacré Griffe,
Dosinectar, Doigrind, M. Glacial, Trépassable) + les 16 formes d'Hisui (Légendes Arceus) +
les 6 espèces qui évoluent exclusivement depuis une forme d'Hisui (Wyrdeer, Kleavor,
Ursaluna, Bargantua, Sneasler, Overqwil) + les 4 formes de Paldea (Ouaporo de Paldea, et
les 3 races de Tauros de Paldea : Combat/Flamme/Aqua). 87 espèces au total.

Relançable sans risque : un Pokémon dont le NOM existe déjà dans pokedex_complet.json
n'est jamais ni dupliqué ni écrasé.
"""

import json

FICHIER_POKEDEX = "pokedex_complet.json"

# (nom, numero_national_partage, numero_sprite_pokeapi, types, stats, generation, legendaire)
FORMES_ALOLA = [
    ("Rattata d'Alola", 19, 10091, ['tenebres', 'normal'], (30, 56, 35, 25, 35, 72), 7, False),
    ("Rattatac d'Alola", 20, 10092, ['tenebres', 'normal'], (75, 71, 70, 40, 80, 77), 7, False),
    ("Raichu d'Alola", 26, 10100, ['electrik', 'psy'], (60, 85, 50, 95, 85, 110), 7, False),
    ("Sabelette d'Alola", 27, 10101, ['glace', 'acier'], (50, 75, 90, 10, 35, 40), 7, False),
    ("Sablaireau d'Alola", 28, 10102, ['glace', 'acier'], (75, 100, 120, 25, 65, 65), 7, False),
    ("Goupix d'Alola", 37, 10103, ['glace'], (38, 41, 40, 50, 65, 65), 7, False),
    ("Feunard d'Alola", 38, 10104, ['glace', 'fee'], (73, 67, 75, 81, 100, 109), 7, False),
    ("Taupiqueur d'Alola", 50, 10105, ['sol', 'acier'], (10, 55, 30, 35, 45, 90), 7, False),
    ("Triopikeur d'Alola", 51, 10106, ['sol', 'acier'], (35, 100, 60, 50, 70, 110), 7, False),
    ("Miaouss d'Alola", 52, 10107, ['tenebres'], (40, 35, 35, 50, 40, 90), 7, False),
    ("Persian d'Alola", 53, 10108, ['tenebres'], (65, 60, 60, 75, 65, 115), 7, False),
    ("Racaillou d'Alola", 74, 10109, ['roche', 'electrik'], (40, 60, 90, 55, 65, 45), 7, False),
    ("Gravalanch d'Alola", 75, 10110, ['roche', 'electrik'], (55, 75, 110, 65, 85, 45), 7, False),
    ("Grolem d'Alola", 76, 10111, ['roche', 'electrik'], (80, 95, 130, 55, 65, 45), 7, False),
    ("Grimace d'Alola", 88, 10112, ['poison', 'tenebres'], (80, 80, 50, 40, 50, 25), 7, False),
    ("Tadmorv d'Alola", 89, 10113, ['poison', 'tenebres'], (105, 105, 75, 65, 100, 50), 7, False),
    ("Noadkoko d'Alola", 103, 10114, ['plante', 'dragon'], (95, 105, 85, 125, 75, 45), 7, False),
    ("Ossatueur d'Alola", 105, 10115, ['feu', 'spectre'], (60, 80, 110, 50, 80, 45), 7, False),
]

FORMES_GALAR = [
    ("Miaouss de Galar", 52, 10161, ['acier'], (50, 65, 55, 40, 40, 40), 8, False),
    ("Ponyta de Galar", 77, 10162, ['fee'], (50, 65, 55, 65, 65, 90), 8, False),
    ("Galopa de Galar", 78, 10163, ['fee'], (65, 100, 70, 80, 80, 105), 8, False),
    ("Ramoloss de Galar", 79, 10164, ['poison', 'psy'], (90, 65, 65, 40, 40, 15), 8, False),
    ("Flagadoss de Galar", 80, 10165, ['poison', 'psy'], (95, 100, 95, 100, 70, 30), 8, False),
    ("Canarticho de Galar", 83, 10166, ['normal'], (52, 90, 55, 58, 62, 60), 8, False),
    ("Smogogo de Galar", 110, 10167, ['poison', 'fee'], (65, 90, 120, 85, 70, 60), 8, False),
    ("M. Mime de Galar", 122, 10168, ['glace', 'psy'], (50, 65, 65, 90, 90, 100), 8, False),
    ("Artikodin de Galar", 144, 10169, ['psy', 'vol'], (90, 85, 85, 125, 100, 95), 8, True),
    ("Électhor de Galar", 145, 10170, ['combat', 'vol'], (90, 125, 90, 85, 90, 100), 8, True),
    ("Sulfura de Galar", 146, 10171, ['tenebres', 'vol'], (90, 85, 90, 125, 90, 100), 8, True),
    ("Roigada de Galar", 199, 10172, ['poison', 'psy'], (95, 65, 80, 110, 110, 30), 8, False),
    ("Corayon de Galar", 222, 10173, ['fantome'], (60, 55, 100, 65, 100, 30), 8, False),
    ("Zigzaton de Galar", 263, 10174, ['tenebres', 'normal'], (38, 30, 41, 30, 41, 60), 8, False),
    ("Linéon de Galar", 264, 10175, ['tenebres', 'normal'], (78, 70, 61, 50, 61, 100), 8, False),
    ("Darumacho de Galar", 554, 10176, ['glace'], (70, 90, 45, 15, 45, 50), 8, False),
    ("Ristourbo de Galar", 555, 10177, ['glace'], (105, 140, 55, 30, 55, 55), 8, False),
]

# Espèces à part entière qui n'évoluent QUE depuis une forme de Galar — ont déjà leur
# propre numéro national (pas de partage avec une forme de base, contrairement aux 2
# listes ci-dessus).
FORMES_GALAR_EVOLUTIONS = [
    ("Ixon", 862, 862, ['tenebres', 'normal'], (93, 90, 101, 60, 81, 95), 8, False),
    ("Sacré Griffe", 863, 863, ['acier'], (70, 110, 100, 50, 60, 50), 8, False),
    ("Dosinectar", 864, 864, ['fantome'], (60, 95, 50, 145, 130, 30), 8, False),
    ("Doigrind", 865, 865, ['combat'], (62, 135, 95, 68, 82, 65), 8, False),
    ("M. Glacial", 866, 866, ['glace', 'psy'], (80, 85, 75, 110, 100, 70), 8, False),
    ("Trépassable", 867, 867, ['sol', 'fantome'], (58, 95, 145, 50, 105, 30), 8, False),
]

# --- Vague 2 : Hisui (Légendes Arceus) et Paldea (Écarlate/Violet) ---
FORMES_HISUI = [
    ("Caninos d'Hisui", 58, 10229, ['feu', 'roche'], (60, 75, 45, 65, 50, 55), 8, False),
    ("Arcanin d'Hisui", 59, 10230, ['feu', 'roche'], (90, 115, 80, 95, 80, 95), 8, False),
    ("Voltorbe d'Hisui", 100, 10231, ['plante', 'electrik'], (40, 30, 50, 55, 55, 100), 8, False),
    ("Électrode d'Hisui", 101, 10232, ['plante', 'electrik'], (60, 50, 70, 80, 80, 150), 8, False),
    ("Typhlosion d'Hisui", 157, 10233, ['feu', 'fantome'], (73, 84, 78, 109, 85, 100), 8, False),
    ("Qwilfish d'Hisui", 211, 10234, ['tenebres', 'poison'], (65, 95, 75, 55, 55, 85), 8, False),
    ("Farfuret d'Hisui", 215, 10235, ['combat', 'poison'], (55, 95, 55, 35, 75, 115), 8, False),
    ("Clamiral d'Hisui", 503, 10236, ['tenebres', 'eau'], (90, 108, 80, 100, 65, 85), 8, False),
    ("Blancoton d'Hisui", 549, 10237, ['plante', 'combat'], (70, 105, 75, 50, 75, 105), 8, False),
    ("Zorua d'Hisui", 570, 10238, ['normal', 'fantome'], (35, 60, 40, 40, 40, 65), 8, False),
    ("Zoroark d'Hisui", 571, 10239, ['normal', 'fantome'], (55, 100, 60, 85, 60, 105), 8, False),
    ("Gueriaigle d'Hisui", 628, 10240, ['psy', 'vol'], (110, 83, 70, 112, 70, 90), 8, False),
    ("Mucuscule d'Hisui", 705, 10241, ['acier', 'dragon'], (58, 75, 83, 83, 113, 60), 8, False),
    ("Muplodocus d'Hisui", 706, 10242, ['acier', 'dragon'], (80, 100, 100, 100, 150, 80), 8, False),
    ("Séracrawl d'Hisui", 713, 10243, ['glace', 'roche'], (95, 127, 184, 44, 46, 28), 8, False),
    ("Archéduc d'Hisui", 724, 10244, ['plante', 'combat'], (78, 107, 75, 100, 100, 70), 8, False),
]

# Espèces à part entière qui n'évoluent QUE depuis une forme d'Hisui — numéro national
# propre. ⚠️ Noms français gardés en anglais par prudence : ce sont des Pokémon très
# récents (Légendes Arceus, 2022) pour lesquels je n'ai pas une confiance suffisante sur
# la traduction française officielle exacte — à corriger toi-même si besoin, plutôt que
# risquer un nom inventé.
FORMES_HISUI_EVOLUTIONS = [
    ("Wyrdeer", 899, 899, ['normal', 'psy'], (103, 105, 72, 105, 75, 65), 8, False),
    ("Kleavor", 900, 900, ['insecte', 'roche'], (70, 135, 95, 45, 70, 85), 8, False),
    ("Ursaluna", 901, 901, ['sol', 'normal'], (130, 140, 105, 45, 80, 50), 8, False),
    ("Bargantua", 902, 902, ['eau', 'fantome'], (120, 112, 65, 80, 75, 78), 8, False),
    ("Sneasler", 903, 903, ['combat', 'poison'], (80, 130, 60, 40, 80, 120), 8, False),
    ("Overqwil", 904, 904, ['tenebres', 'poison'], (85, 115, 95, 65, 65, 85), 8, False),
]

FORMES_PALDEA = [
    ("Ouaporo de Paldea", 194, 10253, ['poison', 'sol'], (55, 45, 45, 25, 25, 15), 9, False),
    ("Tauros de Paldea (Combat)", 128, 10250, ['combat'], (75, 110, 105, 30, 70, 100), 9, False),
    ("Tauros de Paldea (Flamme)", 128, 10251, ['combat', 'feu'], (75, 110, 105, 30, 70, 100), 9, False),
    ("Tauros de Paldea (Aqua)", 128, 10252, ['combat', 'eau'], (75, 110, 105, 30, 70, 100), 9, False),
]


def determiner_rarete(total_stats: int, legendaire: bool) -> str:
    """Exactement la même règle que generer_pokedex.py — voir sa docstring."""
    if legendaire:
        return "legendaire"
    if total_stats >= 580:
        return "hyper_rare"
    if total_stats >= 500:
        return "rare"
    if total_stats >= 400:
        return "peu_commun"
    return "commun"


def construire_entree(nom, numero, numero_sprite, types, stats, generation, legendaire):
    pv, atk, defe, patk, pdef, vit = stats
    total = sum(stats)
    return {
        "nom": nom,
        "numero": numero,
        "numero_sprite": numero_sprite,
        "types": types,
        "rarete": determiner_rarete(total, legendaire),
        "generation": generation,
        "base_pc": total,
        "sprite": None,
        "attaques": [],
        "movepool_niveaux": {},
        "stats_detaillees": {
            "pv": pv, "attaque": atk, "defense": defe,
            "attaque_spe": patk, "defense_spe": pdef, "vitesse": vit,
        },
    }


def main():
    with open(FICHIER_POKEDEX, encoding="utf-8") as f:
        pokedex = json.load(f)

    noms_existants = {p["nom"] for p in pokedex}
    toutes_formes = (
        FORMES_ALOLA + FORMES_GALAR + FORMES_GALAR_EVOLUTIONS
        + FORMES_HISUI + FORMES_HISUI_EVOLUTIONS + FORMES_PALDEA
    )

    ajoutees = []
    deja_presentes = []
    for nom, numero, numero_sprite, types, stats, generation, legendaire in toutes_formes:
        if nom in noms_existants:
            deja_presentes.append(nom)
            continue
        pokedex.append(construire_entree(nom, numero, numero_sprite, types, stats, generation, legendaire))
        ajoutees.append(nom)

    with open(FICHIER_POKEDEX, "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(ajoutees)} forme(s) régionale(s) ajoutée(s) au Pokédex.")
    if deja_presentes:
        print(f"⏭️  {len(deja_presentes)} déjà présente(s), ignorée(s) : {', '.join(deja_presentes)}")
    print(f"\nTotal du Pokédex maintenant : {len(pokedex)} espèces.")
    print(
        "\n⚠️ Prochaines étapes pour que les sprites s'affichent correctement :\n"
        "   1. py corriger_sprites.py\n"
        "   2. py verifier_sprites_disponibles.py\n"
        "   3. Committer sprites_corriges/ sur GitHub, puis déployer normalement.\n"
        "\nCes attaques équipables sont vides par défaut (['attaques': []) — pense à\n"
        "relancer maj_movepool.py / maj_attaques.py si tu veux qu'elles apprennent des\n"
        "attaques par niveau comme les autres espèces."
    )


if __name__ == "__main__":
    main()
