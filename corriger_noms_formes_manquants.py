"""
Corrige les noms de 8 espèces dont l'entrée régionale/évolution exclusive Galar avait
gardé son ANCIEN nom (jamais mis à jour par les précédentes corrections, qui n'avaient
visiblement touché que les entrées de base) :

  Grimace d'Alola      -> Tadmorv d'Alola
  Tadmorv d'Alola      -> Grotadmorv d'Alola
  Darumacho de Galar   -> Darumarond de Galar
  Ristourbo de Galar   -> Darumacho de Galar
  Ouaporo de Paldea    -> Axoloto de Paldea
  Dosinectar           -> Corayôme
  M. Glacial           -> M. Glaquette
  Blancoton d'Hisui     -> Fragilady d'Hisui

pokedex_complet.json a déjà été corrigé séparément (fichier livré à part) — ce script
ne touche QUE les Pokémon déjà capturés par des joueurs sous l'ancien nom, dans les 3
tables où l'identité d'un Pokémon possédé est stockée durablement par son nom.

⚠️ Attention à l'ordre : "Darumacho de Galar" est à la fois un ANCIEN nom (pour l'entrée
554, à corriger vers Darumarond) et un NOUVEAU nom cible (pour l'entrée 555, venant de
Ristourbo). Un simple enchaînement de UPDATE un par un ferait donc une double conversion
en cascade sur la même ligne. Pour éviter ça, chaque table est corrigée en UN SEUL
UPDATE (via CASE), qui évalue toujours la valeur D'ORIGINE de la ligne, jamais une
valeur déjà modifiée dans la même exécution.

Idempotent PAR PROTECTION EXPLICITE (pas par nature) : ⚠️ "Darumacho de Galar" est à la
fois une cible de renommage ET une source d'un autre renommage dans ce lot — un second
lancement ne pourrait plus distinguer les lignes déjà corrigées de celles à corriger, et
re-corrompre les données. Ce script enregistre donc un marqueur dans la table
`settings` après son unique exécution réussie et refuse de tourner une seconde fois.
"""

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "pokebot.sqlite3")
CLE_PARAMETRE = "migration_noms_formes_manquants_2_appliquee"

CORRECTIONS = {
    "Grimace d'Alola": "Tadmorv d'Alola",
    "Tadmorv d'Alola": "Grotadmorv d'Alola",
    "Darumacho de Galar": "Darumarond de Galar",
    "Ristourbo de Galar": "Darumacho de Galar",
    "Ouaporo de Paldea": "Axoloto de Paldea",
    "Dosinectar": "Corayôme",
    "M. Glacial": "M. Glaquette",
    "Blancoton d'Hisui": "Fragilady d'Hisui",
}

# Les 3 tables où le nom d'un Pokémon possédé persiste durablement (hors état de combat
# éphémère, qui n'a pas besoin d'être corrigé). marketplace_annonces référence les
# Pokémon par capture_id, pas par nom -> hérite automatiquement de la correction.
TABLES = ["captures", "equipe_combat", "niveaux_pokemon"]


def corriger():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT valeur FROM settings WHERE cle = ?", (CLE_PARAMETRE,))
    if cur.fetchone():
        print("⛔ Cette migration a déjà été appliquée sur cette base (marqueur trouvé dans `settings`) — abandon, rien à faire.")
        conn.close()
        return

    anciens_noms = list(CORRECTIONS.keys())
    case_sql = " ".join("WHEN ? THEN ?" for _ in CORRECTIONS)
    case_params = [v for paire in CORRECTIONS.items() for v in paire]

    total = 0
    for table in TABLES:
        placeholders = ", ".join("?" for _ in anciens_noms)
        try:
            cur.execute(
                f"""
                UPDATE {table}
                SET pokemon_nom = CASE pokemon_nom {case_sql} ELSE pokemon_nom END
                WHERE pokemon_nom IN ({placeholders})
                """,
                case_params + anciens_noms,
            )
            if cur.rowcount:
                print(f"  {table} : {cur.rowcount} ligne(s) corrigée(s)")
                total += cur.rowcount
        except sqlite3.OperationalError as e:
            print(f"  ⚠️ {table}: {e}")

    conn.commit()
    conn.close()
    print(f"\n✅ Terminé — {total} ligne(s) corrigée(s) au total.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO settings (cle, valeur) VALUES (?, ?)",
        (CLE_PARAMETRE, "1"),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    corriger()
