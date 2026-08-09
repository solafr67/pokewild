"""
Corrige les noms de 8 espèces dont l'entrée régionale/évolution exclusive Galar avait
gardé son ANCIEN nom (jamais mis à jour par les précédentes corrections).

  Grimace d'Alola      -> Tadmorv d'Alola
  Tadmorv d'Alola      -> Grotadmorv d'Alola
  Darumacho de Galar   -> Darumarond de Galar
  Ristourbo de Galar   -> Darumacho de Galar
  Ouaporo de Paldea    -> Axoloto de Paldea
  Dosinectar           -> Corayôme
  M. Glacial           -> M. Glaquette
  Blancoton d'Hisui     -> Fragilady d'Hisui

⚠️ 2 versions précédentes de ce script avaient chacune un bug de fond :
  v1 : simple UPDATE en cascade -> une ligne pouvait être renommée deux fois de suite
       (ex: Grimace -> Tadmorv -> Grotadmorv sur la MÊME ligne, alors que Grimace doit
       s'arrêter à Tadmorv).
  v2 : UPDATE atomique par CASE (corrige la cascade) + une "résolution de conflit"
       préalable qui fusionnait à tort deux ESPÈCES DIFFÉRENTES qui possédaient juste
       le même nom de passage dans la chaîne (Grimace d'Alola ET Tadmorv d'Alola sont
       deux Pokémon bien distincts qu'un joueur peut légitimement posséder tous les
       deux — les fusionner aurait fait perdre les niveaux/XP de l'un des deux).

Cette version (v3) fait tout le renommage en Python, en un seul passage par ligne
(chaque ligne n'est mappée qu'UNE fois vers sa destination directe), et ne fusionne
QUE les vrais doublons — c'est-à-dire quand, après ce mappage à un seul saut, DEUX
lignes du MÊME joueur finissent avec EXACTEMENT le même nom final (là on fusionne en
gardant le niveau/XP le plus haut, aucune perte de progression).

Idempotent (verrou dans `settings`) : impossible de le relancer par erreur.
"""

import sqlite3
import os
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "pokebot.sqlite3")
CLE_PARAMETRE = "migration_noms_formes_manquants_3_appliquee"

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


def _corriger_captures(cur):
    """captures.id est la clé primaire (pas pokemon_nom) -> pas de risque de collision
    d'unicité, mais toujours un risque de CASCADE (une ligne renommée une fois par une
    règle se ferait re-capter par la règle suivante, ex: Grimace->Tadmorv->Grotadmorv
    sur la même ligne). Un seul UPDATE atomique par CASE évalue toujours le nom
    D'ORIGINE de chaque ligne, jamais un nom déjà modifié dans la même exécution."""
    anciens_noms = list(CORRECTIONS.keys())
    case_sql = " ".join("WHEN ? THEN ?" for _ in CORRECTIONS)
    case_params = [v for paire in CORRECTIONS.items() for v in paire]
    placeholders = ", ".join("?" for _ in anciens_noms)
    cur.execute(
        f"""
        UPDATE captures
        SET pokemon_nom = CASE pokemon_nom {case_sql} ELSE pokemon_nom END
        WHERE pokemon_nom IN ({placeholders})
        """,
        case_params + anciens_noms,
    )
    total = cur.rowcount
    if total:
        print(f"  captures : {total} ligne(s) renommée(s)")
    return total


def _corriger_table_avec_cle_unique(cur, table, colonnes_extra):
    """Pour les tables où (user_id, pokemon_nom) doit rester unique (equipe_combat,
    niveaux_pokemon). Charge tout en mémoire, mappe chaque ligne à sa destination en UN
    seul saut, fusionne les vraies collisions (même joueur, même destination finale) en
    gardant le maximum de chaque colonne numérique, réécrit la table proprement."""
    colonnes = ["user_id", "pokemon_nom"] + colonnes_extra
    cur.execute(f"SELECT {', '.join(colonnes)} FROM {table}")
    lignes = cur.fetchall()

    par_destination = defaultdict(list)  # (user_id, nom_final) -> [tuple(extra), ...]
    inchangees = []
    for ligne in lignes:
        user_id, nom, *extra = ligne
        if nom in CORRECTIONS:
            par_destination[(user_id, CORRECTIONS[nom])].append(tuple(extra))
        else:
            # Toute ligne pas concernée par une correction (y compris une ligne déjà
            # nommée correctement, ex: un nom cible pré-existant chez ce joueur) doit
            # aussi participer à la fusion si elle porte déjà le nom final de quelqu'un
            # d'autre en cours de renommage : on l'ajoute sous sa propre destination
            # (= son nom actuel, puisqu'elle ne bouge pas) pour capter ce cas.
            par_destination[(user_id, nom)].append(tuple(extra))

    total_renommees = 0
    total_fusionnees = 0
    cur.execute(f"DELETE FROM {table}")
    for (user_id, nom_final), groupe in par_destination.items():
        if colonnes_extra:
            fusion = tuple(max(valeurs) for valeurs in zip(*groupe))
        else:
            fusion = ()
        placeholders = ", ".join("?" for _ in colonnes)
        cur.execute(
            f"INSERT INTO {table} ({', '.join(colonnes)}) VALUES ({placeholders})",
            (user_id, nom_final) + fusion,
        )
        if len(groupe) > 1:
            total_fusionnees += 1
        else:
            total_renommees += 1

    if total_fusionnees:
        print(f"  {table} : {total_fusionnees} doublon(s) réel(s) fusionné(s) (même joueur, même destination)")
    print(f"  {table} : {len(par_destination)} ligne(s) au total après passage (table réécrite proprement)")


def corriger():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT valeur FROM settings WHERE cle = ?", (CLE_PARAMETRE,))
    if cur.fetchone():
        print("⛔ Cette migration a déjà été appliquée sur cette base (marqueur trouvé dans `settings`) — abandon, rien à faire.")
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
