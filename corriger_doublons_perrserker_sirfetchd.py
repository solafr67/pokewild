"""
Complément à corriger_noms_formes_manquants.py — traite 2 espèces découvertes après coup
en creusant le signalement de l'utilisateur sur Sacré Griffe/Doigrind : ce ne sont pas de
simples mauvais noms, ce sont des entrées Pokédex EN DOUBLE et VIDES (sprite=null, 0
attaque, 0 movepool) créées par erreur par ajouter_formes_regionales.py pour des espèces
qui existaient déjà correctement dans le Pokédex de base (Perrserker/Sirfetch'd/Cursola/
M. Rime ne sont PAS des formes régionales à proprement parler — juste des Pokémon
exclusifs à Galar avec leur propre numéro, déjà présents une fois).

Les 4 entrées vides (numero_sprite == numero, sprite null) ont été supprimées du
pokedex_complet.json livré à part. Ce script corrige les CAPTURES DÉJÀ FAITES par des
joueurs sous l'ancien nom fantôme, en les fusionnant vers la vraie entrée :

  Sacré Griffe -> Berserkatt   (Perrserker, #863)
  Doigrind     -> Palarticho   (Sirfetch'd, #865)

(Dosinectar->Corayôme et M. Glacial->M. Glaquette avaient déjà le même souci de doublon,
mais leur RENOMMAGE de capture est déjà couvert par corriger_noms_formes_manquants.py —
à lancer aussi si ce n'est pas déjà fait, il n'y a que la suppression de l'entrée fantôme
dans le JSON qui était encore manquante pour ces deux-là, déjà faite dans le fichier livré.)

Idempotent (comme l'original) : verrou dans `settings` pour empêcher un relancement.
"""

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "pokebot.sqlite3")
CLE_PARAMETRE = "migration_noms_doublons_perrserker_sirfetchd_appliquee"

CORRECTIONS = {
    "Sacré Griffe": "Berserkatt",
    "Doigrind": "Palarticho",
}

TABLES = ["captures", "equipe_combat", "niveaux_pokemon"]


def corriger():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT valeur FROM settings WHERE cle = ?", (CLE_PARAMETRE,))
    if cur.fetchone():
        print("⛔ Cette migration a déjà été appliquée sur cette base — abandon, rien à faire.")
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
    print(f"\n✅ Terminé — {total} ligne(s) corrigée(s) au total.")

    conn.execute(
        "INSERT OR REPLACE INTO settings (cle, valeur) VALUES (?, ?)",
        (CLE_PARAMETRE, "1"),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    corriger()
