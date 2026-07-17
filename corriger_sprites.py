"""
Script à lancer UNE SEULE FOIS (ou pour retenter certains Pokémon en cas d'échec réseau)
pour corriger le bug de "ghosting" des sprites animés Showdown.

Le symptôme : sur certaines espèces, Discord affiche l'animation comme une traînée floue
où chaque étape reste visible au lieu de s'effacer avant la suivante. C'est un problème
d'encodage GIF — le "disposal" de frame (l'instruction qui dit "efface l'image précédente
avant de dessiner la suivante") est mal réglé ou absent sur certains fichiers de ce pack
communautaire, et le lecteur GIF de Discord ne compense pas cette erreur.

Ce script :
1. Télécharge chaque sprite Showdown (normal + shiny)
2. Recompose ses frames CORRECTEMENT (Pillow sait reconstruire l'image réelle de chaque
   frame même sur un GIF mal réglé, en tenant compte de la transparence)
3. Le réenregistre avec un disposal fiable (2 = "efface vers l'arrière-plan" avant chaque
   frame), la méthode la plus largement compatible
4. Sauvegarde le résultat dans sprites_corriges/ — à committer sur GitHub ensuite, pour
   que le bot serve CES fichiers au lieu des originaux (voir pokemon_data.py)

Utilisation :
    pip install requests Pillow
    py corriger_sprites.py

Ça prend un moment (jusqu'à ~2050 téléchargements, un par Pokémon en normal + shiny).
Peut être relancé sans risque : les fichiers déjà corrigés ne sont pas re-téléchargés
sauf si tu passes --forcer.
"""

import io
import json
import os
import sys
import time

import requests
from PIL import Image

SHOWDOWN_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/showdown/{sous_dossier}{numero}.gif"
DOSSIER_SORTIE = "sprites_corriges"


def corriger_gif(donnees: bytes):
    """Recompose les frames d'un GIF correctement et le réencode avec un disposal fiable.
    Retourne les octets du GIF corrigé, ou None si le fichier n'est pas exploitable."""
    try:
        gif = Image.open(io.BytesIO(donnees))
        frames = []
        durees = []
        try:
            while True:
                # .convert("RGBA") force Pillow à recomposer l'image RÉELLE de cette frame
                # (en tenant compte de la transparence et de ce qui précède), pas juste le
                # patch brut stocké dans le fichier — c'est ça qui corrige le bug.
                frames.append(gif.convert("RGBA").copy())
                durees.append(gif.info.get("duration", 100) or 100)
                gif.seek(gif.tell() + 1)
        except EOFError:
            pass

        if not frames:
            return None

        if len(frames) == 1:
            tampon = io.BytesIO()
            frames[0].save(tampon, format="GIF")
            return tampon.getvalue()

        tampon = io.BytesIO()
        frames[0].save(
            tampon,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durees,
            loop=0,
            disposal=2,  # efface vers l'arrière-plan avant chaque frame — élimine le ghosting
            transparency=0,
            optimize=False,
        )
        return tampon.getvalue()
    except Exception as e:
        print(f"    ⚠️ Erreur de traitement d'image : {e}")
        return None


def corriger_pokemon(numero: int, shiny: bool, forcer: bool) -> str:
    """Retourne 'ok', 'deja_fait', ou 'absent'."""
    sous_dossier_local = os.path.join(DOSSIER_SORTIE, "shiny") if shiny else DOSSIER_SORTIE
    chemin = os.path.join(sous_dossier_local, f"{numero}.gif")

    if os.path.exists(chemin) and not forcer:
        return "deja_fait"

    sous_dossier_url = "shiny/" if shiny else ""
    url = SHOWDOWN_URL.format(sous_dossier=sous_dossier_url, numero=numero)
    try:
        reponse = requests.get(url, timeout=8)
        if reponse.status_code != 200:
            return "absent"
    except requests.RequestException:
        return "absent"

    corrige = corriger_gif(reponse.content)
    if corrige is None:
        return "absent"

    os.makedirs(sous_dossier_local, exist_ok=True)
    with open(chemin, "wb") as f:
        f.write(corrige)
    return "ok"


def main():
    forcer = "--forcer" in sys.argv

    with open("pokedex_complet.json", encoding="utf-8") as f:
        dex = json.load(f)

    numeros = sorted({p["numero"] for p in dex if p.get("numero")})
    total = len(numeros)
    compteurs = {"ok": 0, "deja_fait": 0, "absent": 0}

    for i, numero in enumerate(numeros, 1):
        resultat_normal = corriger_pokemon(numero, shiny=False, forcer=forcer)
        resultat_shiny = corriger_pokemon(numero, shiny=True, forcer=forcer)
        compteurs[resultat_normal] = compteurs.get(resultat_normal, 0) + 1

        if i % 25 == 0 or i == total:
            print(f"[{i}/{total}] traités... (dernier : #{numero} — normal={resultat_normal}, shiny={resultat_shiny})")

        time.sleep(0.05)  # petite pause pour ne pas marteler le serveur GitHub

    print()
    print(f"✅ Corrigés avec succès : {compteurs['ok']}")
    print(f"⏭️  Déjà faits (relance) : {compteurs['deja_fait']}")
    print(f"❌ Introuvables/absents : {compteurs['absent']}")
    print(f"\nFichiers dans {DOSSIER_SORTIE}/ — reste à les committer sur GitHub (git add, commit, push).")


if __name__ == "__main__":
    main()
