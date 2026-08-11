"""
Même bug que Perrserker/Sirfetch'd/Cursola/M. Rime : entrée Pokédex EN DOUBLE et VIDE
(sprite=null, 0 attaque) créée par erreur pour Hachécateur (Kleavor), qui existait déjà
correctement dans le Pokédex de base. L'entrée vide a été supprimée du
pokedex_complet.json livré à part. Ce script corrige les CAPTURES DÉJÀ FAITES par des
joueurs sous l'ancien nom fantôme :

  Kleavor -> Hachécateur   (#900)

Même logique que corriger_doublons_perrserker_sirfetchd.py (renommage à un seul saut,
fusion uniquement des vrais doublons — même joueur, même destination finale, garde le
niveau/XP le plus haut). Idempotent (verrou dans `settings`).
"""

import sqlite3
import os
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "pokebot.sqlite3")
CLE_PARAMETRE = "migration_noms_doublon_kleavor_appliquee"

CORRECTIONS = {
    "Kleavor": "Hachécateur",
}


def _corriger_captures(cur):
    for ancien_nom, nouveau_nom in CORRECTIONS.items():
        cur.execute(
            "UPDATE captures SET pokemon_nom = ? WHERE pokemon_nom = ?",
            (nouveau_nom, ancien_nom),
        )
        if cur.rowcount:
            print(f"  captures : {cur.rowcount} ligne(s) renommée(s)")


def _corriger_table_avec_cle_unique(cur, table, colonnes_extra):
    colonnes = ["user_id", "pokemon_nom"] + colonnes_extra
    cur.execute(f"SELECT {', '.join(colonnes)} FROM {table}")
    lignes = cur.fetchall()

    par_destination = defaultdict(list)
    for ligne in lignes:
        user_id, nom, *extra = ligne
        cle = CORRECTIONS.get(nom, nom)
        par_destination[(user_id, cle)].append(tuple(extra))

    total_fusionnees = 0
    cur.execute(f"DELETE FROM {table}")
    for (user_id, nom_final), groupe in par_destination.items():
        fusion = tuple(max(valeurs) for valeurs in zip(*groupe)) if colonnes_extra else ()
        placeholders = ", ".join("?" for _ in colonnes)
        cur.execute(
            f"INSERT INTO {table} ({', '.join(colonnes)}) VALUES ({placeholders})",
            (user_id, nom_final) + fusion,
        )
        if len(groupe) > 1:
            total_fusionnees += 1

    if total_fusionnees:
        print(f"  {table} : {total_fusionnees} doublon(s) réel(s) fusionné(s)")
    print(f"  {table} : {len(par_destination)} ligne(s) au total après passage")


def corriger():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT valeur FROM settings WHERE cle = ?", (CLE_PARAMETRE,))
    if cur.fetchone():
        print("⛔ Cette migration a déjà été appliquée sur cette base — abandon, rien à faire.")
        conn.close()
        return

    _corriger_captures(cur)
    _corriger_table_avec_cle_unique(cur, "equipe_combat", [])
    _corriger_table_avec_cle_unique(cur, "niveaux_pokemon", ["niveau", "xp"])

    conn.commit()
    print("\n✅ Terminé.")

    conn.execute(
        "INSERT OR REPLACE INTO settings (cle, valeur) VALUES (?, ?)",
        (CLE_PARAMETRE, "1"),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    corriger()
