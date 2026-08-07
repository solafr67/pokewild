"""
Correctif ponctuel : "Kleavor" n'est pas le vrai nom français — c'est "Hachécateur"
(confirmé sur Poképédia, Pokébip, Pokekalos). Erreur de ma part : ma recherche précédente
s'était basée par erreur sur un site au nom trompeur ("PokéPédia" en portugais, pas la
vraie Poképédia française), qui n'affichait que le nom anglais faute de traduction sur
cette page précise.

Met à jour pokedex_complet.json ET les captures de joueurs existantes vers le bon nom.
Relançable sans risque (si "Kleavor" n'existe déjà plus, ne fait rien).

Utilisation (sur le VPS, dans le dossier du bot) :
    py corriger_nom_kleavor.py
"""

import json
import sqlite3

FICHIER_POKEDEX = "pokedex_complet.json"
FICHIER_DB = "pokebot.sqlite3"

ANCIEN_NOM = "Kleavor"
NOUVEAU_NOM = "Hachécateur"
NUMERO_ATTENDU = 900


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
            f"{NUMERO_ATTENDU} attendu — je m'arrête sans rien toucher par précaution. "
            f"Vérifie manuellement cette entrée."
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
