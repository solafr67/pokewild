"""
Scène de combat façon jeux Pokémon 2D/3D classiques — génère une image composite (fond +
sprite du joueur vu de dos + sprite adverse vu de face + HUD PV) à chaque tour de combat
PvP 1v1, en complément du texte existant (ne le remplace pas).

Nécessite Pillow (pip install Pillow --break-system-packages sur le VPS si pas déjà fait).
"""

import io

import requests
from PIL import Image, ImageDraw, ImageFont

import pokemon_data

CHEMIN_FOND = "assets/fond_terrain.png"  # à committer dans le dépôt, voir livraison

ANCRE_JOUEUR = (90, 125)
ANCRE_ADVERSAIRE = (205, 82)
TAILLE_MAX_JOUEUR = 90
TAILLE_MAX_ADVERSAIRE = 58

_CACHE_SPRITES: dict = {}  # évite de re-télécharger le même sprite plusieurs fois par tour


def _telecharger_sprite(url: str) -> Image.Image | None:
    if url in _CACHE_SPRITES:
        return _CACHE_SPRITES[url]
    try:
        reponse = requests.get(url, timeout=6)
        reponse.raise_for_status()
        img = Image.open(io.BytesIO(reponse.content))
        img.seek(0)  # 1ère frame seulement (image statique, pas besoin de l'animation ici)
        img = img.convert("RGBA")
    except Exception as e:
        print(f"⚠️ [combat_visuel] Sprite introuvable ({url}) : {e}")
        img = None
    _CACHE_SPRITES[url] = img
    return img


def _url_sprite_dos(numero: int, shiny: bool = False) -> str:
    sous_dossier = "shiny/" if shiny else ""
    return f"https://raw.githubusercontent.com/solafr67/pokewild/main/sprites_dos/{sous_dossier}{numero}.gif"


def _sprite_joueur(pokemon: dict, shiny: bool = False) -> Image.Image | None:
    """Sprite vu de dos si disponible, sinon repli sur le sprite de face habituel (~1.3%
    des espèces n'ont pas de version dos chez la source utilisée)."""
    numero = pokemon.get("numero_sprite") or pokemon.get("numero")
    if not numero:
        return None
    img = _telecharger_sprite(_url_sprite_dos(numero, shiny))
    if img is not None:
        return img
    return _telecharger_sprite(pokemon_data.sprite_pokemon(pokemon, shiny))


def _sprite_adversaire(pokemon: dict, shiny: bool = False) -> Image.Image | None:
    return _telecharger_sprite(pokemon_data.sprite_pokemon(pokemon, shiny))


def _redimensionner_max(img: Image.Image, taille_max: int) -> Image.Image:
    ratio = min(taille_max / img.width, taille_max / img.height)
    nouvelle_taille = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(nouvelle_taille, Image.LANCZOS)


def _coller_ancre_bas(scene: Image.Image, sprite: Image.Image, ancre_xy: tuple):
    x = ancre_xy[0] - sprite.width // 2
    y = ancre_xy[1] - sprite.height
    scene.paste(sprite, (x, y), sprite)


def _police(taille: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", taille)
    except OSError:
        return ImageFont.load_default()


def _couleur_pv(ratio: float) -> tuple:
    if ratio > 0.5:
        return (64, 200, 88)
    if ratio > 0.2:
        return (240, 190, 40)
    return (220, 60, 60)


def _dessiner_bloc_pv(scene: Image.Image, x: int, y: int, nom: str, niveau: int, pv_actuels: int, pv_max: int, largeur: int = 90):
    draw = ImageDraw.Draw(scene)
    police_nom = _police(9)
    police_pv = _police(7)

    hauteur_bloc = 26
    draw.rounded_rectangle([x, y, x + largeur, y + hauteur_bloc], radius=4, fill=(250, 250, 240, 235), outline=(80, 80, 80, 255))
    draw.text((x + 5, y + 2), nom, font=police_nom, fill=(40, 40, 40))
    texte_niveau = f"Nv.{niveau}"
    largeur_niveau = draw.textlength(texte_niveau, font=police_pv)
    draw.text((x + largeur - largeur_niveau - 5, y + 3), texte_niveau, font=police_pv, fill=(40, 40, 40))

    barre_x, barre_y = x + 6, y + 15
    barre_largeur, barre_hauteur = largeur - 12, 6
    ratio = max(0, min(1, pv_actuels / pv_max)) if pv_max else 0
    draw.rectangle([barre_x, barre_y, barre_x + barre_largeur, barre_y + barre_hauteur], fill=(60, 60, 60))
    if ratio > 0:
        draw.rectangle(
            [barre_x + 1, barre_y + 1, barre_x + 1 + max(1, round((barre_largeur - 2) * ratio)), barre_y + barre_hauteur - 1],
            fill=_couleur_pv(ratio),
        )


def generer_image_combat(
    pokemon_joueur: dict, nom_joueur_affiche: str, niveau_joueur: int, pv_joueur: int, pv_max_joueur: int, shiny_joueur: bool,
    pokemon_adversaire: dict, nom_adversaire_affiche: str, niveau_adversaire: int, pv_adversaire: int, pv_max_adversaire: int, shiny_adversaire: bool,
) -> bytes | None:
    """Retourne les bytes PNG de la scène composée, ou None si le fond ou l'un des deux
    sprites n'a pas pu être chargé (appelant doit alors se contenter du texte, pas
    d'échec bruyant pour un souci purement visuel)."""
    try:
        scene = Image.open(CHEMIN_FOND).convert("RGBA")
    except (FileNotFoundError, OSError) as e:
        import os
        print(f"⚠️ [combat_visuel] Fond introuvable ({os.path.abspath(CHEMIN_FOND)}) : {e}")
        return None

    sprite_j = _sprite_joueur(pokemon_joueur, shiny_joueur)
    sprite_a = _sprite_adversaire(pokemon_adversaire, shiny_adversaire)
    if sprite_j is None or sprite_a is None:
        print("⚠️ [combat_visuel] Au moins un des 2 sprites n'a pas pu être chargé (voir message ci-dessus)")
        return None

    sprite_j = _redimensionner_max(sprite_j, TAILLE_MAX_JOUEUR)
    sprite_a = _redimensionner_max(sprite_a, TAILLE_MAX_ADVERSAIRE)

    _coller_ancre_bas(scene, sprite_a, ANCRE_ADVERSAIRE)
    _coller_ancre_bas(scene, sprite_j, ANCRE_JOUEUR)

    _dessiner_bloc_pv(scene, 4, scene.height - 30, nom_joueur_affiche, niveau_joueur, pv_joueur, pv_max_joueur)
    _dessiner_bloc_pv(scene, scene.width - 94, 4, nom_adversaire_affiche, niveau_adversaire, pv_adversaire, pv_max_adversaire)

    # Agrandi x3 avec lissage (LANCZOS) — l'image source est minuscule (256×192) et le
    # premier essai en NEAREST (préserve les pixels bruts) rendait des bords en escalier
    # peu lisibles une fois affiché dans Discord. LANCZOS lisse sans devenir flou.
    scene = scene.resize((scene.width * 3, scene.height * 3), Image.LANCZOS)

    tampon = io.BytesIO()
    scene.save(tampon, format="PNG")
    return tampon.getvalue()
