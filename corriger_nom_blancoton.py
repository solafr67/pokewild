"""
Correctif ponctuel : "Blancoton d'Hisui" utilisait le nom d'un AUTRE Pokémon existant
(Blancoton = Eldegoss, un Pokémon différent, sans rapport) au lieu du vrai nom de
Lilligant, qui est "Fragilady" en français. Corrigé en "Fragilady d'Hisui".

⚠️ Contrairement aux précédents correctifs, ce n'est pas une simple faute de frappe ou
une inversion : "Blancoton" est un VRAI Pokémon différent (déjà présent ailleurs dans ton
Pokédex) — donc ce script ne touche QUE l'entrée numéro 549 (Lilligant), jamais le
Blancoton/Eldegoss légitime (numéro 830), même s'ils portent temporairement des noms
similaires.

Met à jour pokedex_complet.json ET les captures de joueurs existantes vers le bon nom.
Relançable sans risque (si "Blancoton d'Hisui" n'existe déjà plus, ne fait rien).

Utilisation (sur le VPS, dans le dossier du bot) :
    py corriger_nom_blancoton.py
"""

import json
import sqlite3

FICHIER_POKEDEX = "pokedex_complet.json"
FICHIER_DB = "pokebot.sqlite3"

ANCIEN_NOM = "Blancoton d'Hisui"
NOUVEAU_NOM = "Fragilady d'Hisui"
NUMERO_ATTENDU = 549  # sécurité : ne renomme que si c'est bien l'entrée Lilligant (549), jamais le vrai Blancoton (830)


def main():
    with open(FICHIER_POKEDEX, encoding="utf-8") as f:
        pokedex = json.load(f)

    entree = next((p for p in pokedex if p["nom"] == ANCIEN_NOM), None)
    if not entree:
        print(f"'{ANCIEN_NOM}' introuvable — déjà corrigé, ou jamais ajouté. Rien à faire.")
        return

    if entree.get("numero") != NUMERO_ATTENDU:
        print(
            f"⚠️ Trouvé '{ANCIEN_NOM}' mais avec le numéro {entree.get('numero')} au lieu de "
            f"{NUMERO_ATTENDU} attendu — pour éviter toute erreur, je m'arrête sans rien "
            f"toucher. Vérifie manuellement cette entrée."
        )
        return

    entree["nom"] = NOUVEAU_NOM

    with open(FICHIER_POKEDEX, "w", encoding="utf-8") as f:
        json.dump(pokedex, f, ensure_ascii=False, indent=2)
    print(f"✅ Entrée du Pokédex renommée : '{ANCIEN_NOM}' -> '{NOUVEAU_NOM}'")

    conn = sqlite3.connect(FICHIER_DB)
    cur = conn.cursor()
    cur.execute("UPDATE captures SET pokemon_nom = ? WHERE pokemon_nom = ?", (NOUVEAU_NOM, ANCIEN_NOM))
    nb_captures = cur.rowcount
    conn.commit()
    conn.close()
    print(f"✅ {nb_captures} capture(s) de joueur(s) mise(s) à jour vers le nouveau nom.")

    print("\nN'oublie pas de redémarrer le bot pour que le changement soit pris en compte :")
    print("    sudo systemctl restart pokewild")


if __name__ == "__main__":
    main()
