"""
Regroupe TOUTES les corrections de noms français trouvées jusqu'ici sur les formes
régionales (Alola/Galar/Hisui/Paldea) en un seul script. Fusion de :
    corriger_nom_ouaporo.py
    corriger_noms_grimer_muk.py
    corriger_noms_ristourbo_glacial.py
    corriger_noms_darumacho_darumarond.py

Corrige, dans cet ordre (peu importe en fait, chaque correctif est indépendant des
autres) :
    1. "Ouaporo de Paldea" -> "Axoloto de Paldea"
    2. "Grimace d'Alola" / "Tadmorv d'Alola" (inversés) -> "Tadmorv d'Alola" / "Grotadmorv d'Alola"
    3. "Ristourbo de Galar" -> "Darumarond de Galar" (avant la découverte de l'inversion complète, voir 5)
       "M. Glacial" -> "M. Glaquette"
    4. "Darumacho de Galar" / "Darumarond de Galar" (inversés, repérés par NUMÉRO
       554/555 plutôt que par nom) -> bons noms

Met à jour pokedex_complet.json ET les captures de joueurs existantes à chaque étape
(rien n'est perdu). Chaque correctif est indépendant et vérifie lui-même s'il a déjà été
appliqué — relançable sans risque autant de fois que nécessaire, y compris partiellement
(si le script est interrompu en cours de route, relance-le simplement, il reprendra
uniquement ce qui n'a pas encore été fait).

Utilisation (sur le VPS, dans le dossier du bot) :
    py corriger_tous_les_noms.py
"""

import json
import sqlite3

FICHIER_POKEDEX = "pokedex_complet.json"
FICHIER_DB = "pokebot.sqlite3"


def _renommer_simple(pokedex, cur, ancien_nom, nouveau_nom):
    """Renomme une entrée par son nom actuel — utilisé pour les correctifs qui ne sont
    PAS des inversions (donc aucun risque de collision)."""
    entree_trouvee = False
    for p in pokedex:
        if p["nom"] == ancien_nom:
            p["nom"] = nouveau_nom
            entree_trouvee = True
    if not entree_trouvee:
        return False, 0
    cur.execute("UPDATE captures SET pokemon_nom = ? WHERE pokemon_nom = ?", (nouveau_nom, ancien_nom))
    return True, cur.rowcount


def _renommer_par_index(pokedex, cur, index, nouveau_nom):
    ancien_nom = pokedex[index]["nom"]
    pokedex[index]["nom"] = nouveau_nom
    cur.execute("UPDATE captures SET pokemon_nom = ? WHERE pokemon_nom = ?", (nouveau_nom, ancien_nom))
    return cur.rowcount


def corriger_ouaporo(pokedex, cur):
    print("--- 1. Ouaporo de Paldea -> Axoloto de Paldea ---")
    ok, n = _renommer_simple(pokedex, cur, "Ouaporo de Paldea", "Axoloto de Paldea")
    if ok:
        print(f"✅ Corrigé ({n} capture(s) mise(s) à jour)")
    else:
        print("⏭️  Déjà corrigé, ou jamais ajouté.")


def corriger_grimer_muk(pokedex, cur):
    print("--- 2. Grimer/Muk d'Alola (inversion) ---")
    # Marqueur fiable de "pas encore migré" : "Grimace d'Alola" n'existe QUE dans l'état
    # incorrect (avant ce correctif). S'il est absent, tout a déjà été fait.
    if not any(p["nom"] == "Grimace d'Alola" for p in pokedex):
        print("⏭️  Déjà corrigé, ou jamais ajouté.")
        return
    # Étape 1 : Muk (qui portait à tort "Tadmorv d'Alola") récupère son vrai nom en premier,
    # pour libérer "Tadmorv d'Alola" avant que Grimer ne le récupère.
    ok1, n1 = _renommer_simple(pokedex, cur, "Tadmorv d'Alola", "Grotadmorv d'Alola")
    # Étape 2 : Grimer (qui portait à tort "Grimace d'Alola") récupère son vrai nom.
    ok2, n2 = _renommer_simple(pokedex, cur, "Grimace d'Alola", "Tadmorv d'Alola")
    print(f"✅ Corrigé ({n1 + n2} capture(s) mise(s) à jour au total)")


def corriger_ristourbo_glacial(pokedex, cur):
    print("--- 3. Ristourbo de Galar -> Darumarond de Galar / M. Glacial -> M. Glaquette ---")
    renommages = [
        ("Ristourbo de Galar", "Darumarond de Galar"),
        ("M. Glacial", "M. Glaquette"),
    ]
    total = 0
    trouve = False
    for ancien, nouveau in renommages:
        ok, n = _renommer_simple(pokedex, cur, ancien, nouveau)
        if ok:
            trouve = True
            total += n
    if trouve:
        print(f"✅ Corrigé ({total} capture(s) mise(s) à jour au total)")
    else:
        print("⏭️  Déjà corrigé, ou jamais ajouté.")


def corriger_darumacho_darumarond(pokedex, cur):
    print("--- 4. Darumacho/Darumarond de Galar (inversion, repérée par numéro) ---")
    NUMERO_BASE, NUMERO_EVOLUTION = 554, 555
    NOM_BASE_CORRECT, NOM_EVOLUTION_CORRECT = "Darumarond de Galar", "Darumacho de Galar"
    NOM_TEMPORAIRE = "__temp_migration_darumaka__"

    idx_base = next((i for i, p in enumerate(pokedex) if p.get("numero") == NUMERO_BASE and "Galar" in p["nom"]), None)
    idx_evolution = next((i for i, p in enumerate(pokedex) if p.get("numero") == NUMERO_EVOLUTION and "Galar" in p["nom"]), None)

    if idx_base is None or idx_evolution is None:
        print("⏭️  Une des deux entrées est introuvable — rien à faire.")
        return
    if pokedex[idx_base]["nom"] == NOM_BASE_CORRECT and pokedex[idx_evolution]["nom"] == NOM_EVOLUTION_CORRECT:
        print("⏭️  Déjà corrigé.")
        return

    n1 = _renommer_par_index(pokedex, cur, idx_base, NOM_TEMPORAIRE)
    n2 = _renommer_par_index(pokedex, cur, idx_evolution, NOM_EVOLUTION_CORRECT)
    n3 = _renommer_par_index(pokedex, cur, idx_base, NOM_BASE_CORRECT)
    print(f"✅ Corrigé ({n1 + n2 + n3} capture(s) mise(s) à jour au total)")


def main():
    with open(FICHIER_POKEDEX, encoding="utf-8") as f:
        pokedex = json.load(f)

    conn = sqlite3.connect(FICHIER_DB)
    cur = conn.cursor()

    corriger_ouaporo(pokedex, cur)
    conn.commit()
    corriger_grimer_muk(pokedex, cur)
    conn.commit()
    corriger_ristourbo_glacial(pokedex, cur)
    conn.commit()
    corriger_darumacho_darumarond(pokedex, cur)
    conn.commit()
    conn.close()

    with open(FICHIER_POKEDEX, "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)

    print("\n🎉 Tous les correctifs de noms ont été appliqués (ou étaient déjà à jour).")
    print("N'oublie pas de redémarrer le bot pour que le changement soit pris en compte :")
    print("    sudo systemctl restart pokewild")


if __name__ == "__main__":
    main()
