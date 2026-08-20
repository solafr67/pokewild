"""
Scène de combat façon jeux Pokémon 2D/3D classiques — génère une image composite (fond +
sprite du joueur vu de dos + sprite adverse vu de face + HUD complet : PV, statut, boosts,
équipe en Poké Balls, log du tour) à chaque tour de combat PvP 1v1.

Nécessite Pillow et numpy (pip install Pillow numpy --break-system-packages sur le VPS
si pas déjà fait).
"""

import io

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

import pokemon_data

CHEMIN_HAUTEURS = "hauteurs_pokemon.json"

# --- Un fond différent selon le type de combat, chacun avec son propre calibrage
# (coordonnées + tailles déterminées visuellement sur SON fond précis, à la grille —
# elles ne sont pas interchangeables d'un fond à l'autre). "dresseur" sert de valeur par
# défaut pour tout combat qui n'est ni une arène ni un repaire (dresseurs sauvages, PvP).
CONFIGS_FOND = {
    "dresseur": {
        "chemin": "assets/fond_terrain.png",
        "ancre_joueur": (380, 920),
        "ancre_adversaire": (1220, 440),
        "taille_max_joueur": 340,
        "taille_max_adversaire": 220,
        "ancres_joueur_2v2": [(750, 870), (1080, 910)],
        "ancres_adversaire_2v2": [(880, 445), (1130, 470)],
        "taille_max_joueur_2v2": 260,
        "taille_max_adversaire_2v2": 170,
    },
    "arene": {
        "chemin": "assets/fond_arene.png",
        "ancre_joueur": (400, 800),
        "ancre_adversaire": (950, 590),
        "taille_max_joueur": 340,
        "taille_max_adversaire": 220,
        "ancres_joueur_2v2": [(280, 800), (600, 830)],
        "ancres_adversaire_2v2": [(650, 470), (880, 480)],
        "taille_max_joueur_2v2": 260,
        "taille_max_adversaire_2v2": 170,
    },
    "repaire": {
        "chemin": "assets/fond_repaire.png",
        "ancre_joueur": (400, 820),
        "ancre_adversaire": (950, 545),
        "taille_max_joueur": 340,
        "taille_max_adversaire": 220,
        "ancres_joueur_2v2": [(280, 820), (600, 850)],
        "ancres_adversaire_2v2": [(650, 430), (880, 440)],
        "taille_max_joueur_2v2": 260,
        "taille_max_adversaire_2v2": 170,
    },
}

# Mise à l'échelle selon la VRAIE taille de l'espèce (comme dans les jeux) — un Rayquaza
# ou un Wailord doit paraître nettement plus imposant qu'un Pikachu, pas juste rempli
# dans la même boîte. Hauteurs officielles (décimètres) via PokéAPI, indexées par le même
# ID que numero_sprite/numero. Formule volontairement compressée (racine plutôt que
# linéaire) et bornée — sinon un Wailord déborderait complètement de sa plateforme, et un
# Pokémon minuscule deviendrait illisible.
HAUTEUR_REFERENCE_DM = 10  # ~1m, hauteur "moyenne" servant de repère neutre (facteur=1)
FACTEUR_TAILLE_MIN = 0.55
FACTEUR_TAILLE_MAX = 1.4
try:
    import json as _json
    with open(CHEMIN_HAUTEURS, encoding="utf-8") as _f:
        _HAUTEURS_POKEMON = {int(k): v for k, v in _json.load(_f).items()}
except (FileNotFoundError, OSError):
    _HAUTEURS_POKEMON = {}


def _facteur_taille_reelle(pokemon: dict) -> float:
    numero = pokemon.get("numero_sprite") or pokemon.get("numero")
    hauteur_dm = _HAUTEURS_POKEMON.get(numero)
    if not hauteur_dm:
        return 1.0
    facteur = (hauteur_dm / HAUTEUR_REFERENCE_DM) ** 0.4
    return max(FACTEUR_TAILLE_MIN, min(FACTEUR_TAILLE_MAX, facteur))


_CACHE_SPRITES: dict = {}


def _telecharger_sprite(url: str, silencieux: bool = False) -> Image.Image | None:
    """`silencieux=True` pour un essai qui peut échouer normalement (ex: sprite Gen 5
    inexistant pour une espèce plus récente) — évite de spammer la console d'avertissements
    attendus à chaque repli automatique vers le pack suivant."""
    if url in _CACHE_SPRITES:
        return _CACHE_SPRITES[url]
    try:
        reponse = requests.get(url, timeout=6)
        reponse.raise_for_status()
        img = Image.open(io.BytesIO(reponse.content))
        img.seek(0)
        img = img.convert("RGBA")
    except Exception as e:
        if not silencieux:
            print(f"⚠️ [combat_visuel] Sprite introuvable ({url}) : {e}")
        img = None
    _CACHE_SPRITES[url] = img
    return img


def _url_sprite_dos(numero: int, shiny: bool = False) -> str:
    sous_dossier = "shiny/" if shiny else ""
    return f"https://raw.githubusercontent.com/solafr67/pokewild/main/sprites_dos/{sous_dossier}{numero}.gif"


def _sprite_joueur(pokemon: dict, shiny: bool = False) -> Image.Image | None:
    """Sprite vu de dos si disponible (pack Showdown), sinon repli sur le sprite de face
    habituel (~1.3% des espèces n'ont pas de version dos)."""
    numero = pokemon.get("numero_sprite") or pokemon.get("numero")
    if not numero:
        return None
    img = _telecharger_sprite(_url_sprite_dos(numero, shiny), silencieux=True)
    if img is not None:
        return img
    return _telecharger_sprite(pokemon_data.sprite_pokemon(pokemon, shiny))


def _sprite_adversaire(pokemon: dict, shiny: bool = False) -> Image.Image | None:
    return _telecharger_sprite(pokemon_data.sprite_pokemon(pokemon, shiny))


def _boite_contenu_visible(img: Image.Image) -> tuple:
    alpha = img.split()[-1]
    boite = alpha.getbbox()
    return boite if boite else (0, 0, img.width, img.height)


def _centre_de_masse_horizontal(img: Image.Image) -> int:
    alpha = np.array(img.split()[-1])
    colonnes_poids = alpha.sum(axis=0)
    if colonnes_poids.sum() == 0:
        return img.width // 2
    indices = np.arange(img.width)
    return int(round((indices * colonnes_poids).sum() / colonnes_poids.sum()))


def _redimensionner_propre(img: Image.Image, taille_max: int) -> Image.Image:
    """Redimensionne en lissé (LANCZOS, net à cette échelle plus grande — le mode "brut"
    NEAREST utilisé pour l'ancien petit fond deviendrait très blocky ici) tout en évitant
    le liseré coloré causé par les pixels transparents d'un GIF qui contiennent souvent
    une couleur RVB parasite — neutralisée via un alpha prémultiplié avant lissage."""
    ratio = min(taille_max / img.width, taille_max / img.height)
    nouvelle_taille = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))

    a = img.split()[-1]
    arr_rgb = np.array(img.convert("RGB"), dtype=np.float32)
    arr_a = np.array(a, dtype=np.float32) / 255.0
    arr_premult = arr_rgb * arr_a[:, :, None]
    img_premult = Image.fromarray(arr_premult.astype("uint8"), "RGB")

    img_premult_resized = img_premult.resize(nouvelle_taille, Image.LANCZOS)
    a_resized = a.resize(nouvelle_taille, Image.LANCZOS)

    arr_premult_r = np.array(img_premult_resized, dtype=np.float32)
    arr_a_r = np.array(a_resized, dtype=np.float32) / 255.0
    with np.errstate(divide="ignore", invalid="ignore"):
        arr_final_rgb = np.where(arr_a_r[:, :, None] > 0.01, arr_premult_r / arr_a_r[:, :, None], 0)
    arr_final_rgb = np.clip(arr_final_rgb, 0, 255).astype("uint8")

    resultat = Image.fromarray(arr_final_rgb, "RGB").convert("RGBA")
    resultat.putalpha(Image.fromarray((arr_a_r * 255).astype("uint8")))
    return resultat


def _coller_centre_sur_ancre(scene: Image.Image, sprite: Image.Image, ancre_xy: tuple):
    _, _, _, bas = _boite_contenu_visible(sprite)
    centre_x_masse = _centre_de_masse_horizontal(sprite)
    x = ancre_xy[0] - centre_x_masse
    y = ancre_xy[1] - bas
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


# Badges de statut en texte (pas d'emoji couleur — pas garanti disponible sur toutes les
# polices système du VPS, un badge texte coloré est fiable partout). Clés alignées sur
# combat.STATUTS_INFO (burn/poison/paralysis/sleep/freeze/confusion).
# Tables d'affichage LOCALES météo/terrain (juste emoji + nom court) — combat_visuel.py
# reste volontairement indépendant de combat.py (pas d'import croisé), donc pas de
# réutilisation directe de METEO_INFO/TERRAIN_INFO qui y vivent (avec toute la logique de
# jeu en plus, inutile ici). Clés alignées sur les types réels (soleil/pluie/sable/grele,
# electrique/herbu/brumeux/psychique).
METEO_INFO_LOCAL = {
    "soleil": {"emoji": "☀️", "nom_affiche": "Zénith"},
    "pluie": {"emoji": "🌧️", "nom_affiche": "Danse Pluie"},
    "sable": {"emoji": "🌪️", "nom_affiche": "Tempête de Sable"},
    "grele": {"emoji": "🌨️", "nom_affiche": "Grêle"},
}
TERRAIN_INFO_LOCAL = {
    "electrique": {"emoji": "⚡", "nom_affiche": "Champ Électrifié"},
    "herbu": {"emoji": "🌿", "nom_affiche": "Champ Herbu"},
    "brumeux": {"emoji": "🌫️", "nom_affiche": "Champ Brumeux"},
    "psychique": {"emoji": "🔮", "nom_affiche": "Champ Psychique"},
}

# Couleurs par type (mêmes teintes que les jeux/sites compétitifs), pour les badges de
# type sous le nom dans le HUD — clés alignées sur les valeurs françaises du Pokédex.
COULEURS_TYPES = {
    "normal": (168, 168, 120), "feu": (240, 128, 48), "eau": (104, 144, 240),
    "plante": (120, 200, 80), "electrik": (248, 208, 48), "glace": (152, 216, 216),
    "combat": (192, 48, 40), "poison": (160, 64, 160), "sol": (224, 192, 104),
    "vol": (168, 144, 240), "psy": (248, 88, 136), "insecte": (168, 184, 32),
    "roche": (184, 160, 56), "spectre": (112, 88, 152), "dragon": (112, 56, 248),
    "tenebres": (112, 88, 72), "acier": (184, 184, 208), "fee": (238, 153, 172),
}

BADGES_STATUT = {
    "burn": ("BRL", (230, 90, 40)),
    "poison": ("PSN", (150, 60, 190)),
    "paralysis": ("PAR", (230, 190, 30)),
    "sleep": ("SOM", (100, 100, 200)),
    "freeze": ("GEL", (100, 190, 230)),
    "confusion": ("CNF", (220, 100, 160)),
}


def _dessiner_badges_types(draw: ImageDraw.ImageDraw, x: int, y: int, types: list) -> int:
    """Dessine les badges de type (pastilles colorées, ex: Eau/Vol) l'un à côté de
    l'autre. Retourne la largeur totale utilisée."""
    police = _police(7)
    curseur_x = x
    for t in types or []:
        couleur = COULEURS_TYPES.get(t, (120, 120, 120))
        texte = t.capitalize()
        largeur_texte = draw.textlength(texte, font=police)
        largeur_badge = round(largeur_texte) + 8
        draw.rounded_rectangle([curseur_x, y, curseur_x + largeur_badge, y + 12], radius=3, fill=couleur)
        draw.text((curseur_x + 4, y + 1), texte, font=police, fill=(255, 255, 255))
        curseur_x += largeur_badge + 3
    return curseur_x - x


def _dessiner_badge_statut(draw: ImageDraw.ImageDraw, x: int, y: int, code_statut: str | None) -> int:
    """Dessine un petit badge coloré (ex: 'BRL' sur fond orange) à côté du nom si le
    Pokémon a un statut. Retourne la largeur utilisée (0 si aucun statut)."""
    if not code_statut or code_statut not in BADGES_STATUT:
        return 0
    texte, couleur = BADGES_STATUT[code_statut]
    police = _police(7)
    largeur_texte = draw.textlength(texte, font=police)
    largeur_badge = round(largeur_texte) + 6
    draw.rounded_rectangle([x, y, x + largeur_badge, y + 11], radius=3, fill=couleur)
    draw.text((x + 3, y + 1), texte, font=police, fill=(255, 255, 255))
    return largeur_badge + 6


def _dessiner_pokeball(draw: ImageDraw.ImageDraw, cx: int, cy: int, rayon: int, vivant: bool):
    """Une Poké Ball miniature — rouge/blanc si le Pokémon de l'équipe est encore vivant,
    grise/noircie s'il est K.O. (comme l'écran d'équipe des vrais jeux)."""
    if vivant:
        couleur_haut, couleur_bas = (220, 60, 60), (250, 250, 245)
    else:
        couleur_haut, couleur_bas = (70, 70, 70), (30, 30, 30)
    draw.pieslice([cx - rayon, cy - rayon, cx + rayon, cy + rayon], 180, 360, fill=couleur_haut, outline=(20, 20, 20))
    draw.pieslice([cx - rayon, cy - rayon, cx + rayon, cy + rayon], 0, 180, fill=couleur_bas, outline=(20, 20, 20))
    draw.line([(cx - rayon, cy), (cx + rayon, cy)], fill=(20, 20, 20), width=2)
    rayon_centre = max(2, rayon // 3)
    draw.ellipse([cx - rayon_centre, cy - rayon_centre, cx + rayon_centre, cy + rayon_centre], fill=(240, 240, 240), outline=(20, 20, 20))


def _dessiner_ligne_pokeballs(scene: Image.Image, x: int, y: int, equipe_vivante: list, ancre_droite: bool = False):
    rayon = 4
    espacement = 11
    largeur_totale = len(equipe_vivante) * espacement
    if ancre_droite:
        x = x - largeur_totale
    draw = ImageDraw.Draw(scene)
    for i, vivant in enumerate(equipe_vivante):
        _dessiner_pokeball(draw, x + i * espacement + rayon, y + rayon, rayon, vivant)


def _dessiner_bloc_hud(
    scene: Image.Image, x: int, y: int, nom: str, niveau: int, pv_actuels: int, pv_max: int,
    code_statut: str, boosts: dict, equipe_vivante: list, types: list = None, ancre_droite: bool = False, ancre_bas: bool = False,
    afficher_pokeballs: bool = True,
):
    """Bloc HUD complet : nom + niveau, badge de statut, boosts de stats, barre de PV +
    PV en chiffres, et la ligne de Poké Balls de l'équipe en dessous. Hauteur du cadre
    calculée en ADDITIONNANT chaque ligne réellement dessinée (jamais de valeur fixe qui
    pourrait ne plus suffire si une ligne change — plus de débordement du texte des PV
    en dehors du cadre). Si ancre_bas=True, `y` désigne le bord BAS du cadre (pour ancrer
    depuis le bas de l'écran) plutôt que le bord haut."""
    draw = ImageDraw.Draw(scene)
    police_nom = _police(11)
    police_detail = _police(8)

    texte_niveau = f"Nv.{niveau}"
    largeur_nom = draw.textlength(nom, font=police_nom)
    largeur_badge_estimee = 22 if code_statut in BADGES_STATUT else 0
    largeur_niveau_texte = draw.textlength(texte_niveau, font=police_detail)
    largeur = max(100, round(largeur_nom + largeur_niveau_texte) + largeur_badge_estimee + 20)
    if ancre_droite:
        x = x - largeur

    morceaux_boosts = [
        f"{label}{boosts.get(stat, 0):+d}"
        for stat, label in (("atk", "Atq"), ("def", "Déf"), ("atk_spe", "AtqS"), ("def_spe", "DéfS"), ("vit", "Vit"))
        if boosts.get(stat, 0) != 0
    ]
    texte_boosts = " ".join(morceaux_boosts)

    # Construction verticale additive, en coordonnées RELATIVES (0 = haut du cadre)
    # d'abord — la hauteur totale en découle, et seulement APRÈS on sait où placer le
    # bord haut réel du cadre (utile pour ancre_bas, où on part du bord BAS souhaité).
    PADDING_HAUT, PADDING_BAS = 4, 4
    H_LIGNE_NOM = 14
    H_LIGNE_TYPES = 15
    H_LIGNE_BOOSTS = 10
    H_BARRE = 5
    GAP_APRES_BARRE = 2
    H_LIGNE_PV = 11

    curseur = PADDING_HAUT
    rel_nom = curseur
    curseur += H_LIGNE_NOM
    rel_types = curseur if types else None
    if types:
        curseur += H_LIGNE_TYPES
    rel_boosts = curseur if texte_boosts else None
    if texte_boosts:
        curseur += H_LIGNE_BOOSTS
    rel_barre = curseur
    curseur += H_BARRE + GAP_APRES_BARRE
    rel_pv = curseur
    curseur += H_LIGNE_PV
    hauteur_bloc = curseur + PADDING_BAS

    if ancre_bas:
        y = y - hauteur_bloc

    # Fond clair opaque (comme dans les jeux classiques).
    draw.rounded_rectangle([x, y, x + largeur, y + hauteur_bloc], radius=5, fill=(250, 250, 240, 235), outline=(80, 80, 80, 255), width=1)

    draw.text((x + 5, y + rel_nom), nom, font=police_nom, fill=(40, 40, 40))
    _dessiner_badge_statut(draw, x + 6 + largeur_nom, y + rel_nom + 1, code_statut)
    draw.text((x + largeur - largeur_niveau_texte - 5, y + rel_nom + 1), texte_niveau, font=police_detail, fill=(40, 40, 40))

    if types:
        _dessiner_badges_types(draw, x + 5, y + rel_types, types)

    if texte_boosts:
        draw.text((x + 5, y + rel_boosts), texte_boosts, font=_police(7), fill=(30, 90, 160))

    police_pv_label = _police(7)
    draw.text((x + 5, y + rel_barre - 1), "PV", font=police_pv_label, fill=(60, 60, 60))
    largeur_label_pv = draw.textlength("PV", font=police_pv_label) + 4
    barre_x = x + 5 + round(largeur_label_pv)
    barre_largeur = largeur - 10 - round(largeur_label_pv)
    y_barre = y + rel_barre
    ratio = max(0, min(1, pv_actuels / pv_max)) if pv_max else 0
    draw.rectangle([barre_x, y_barre, barre_x + barre_largeur, y_barre + H_BARRE], fill=(60, 60, 60))
    if ratio > 0:
        draw.rectangle(
            [barre_x + 1, y_barre + 1, barre_x + 1 + max(1, round((barre_largeur - 2) * ratio)), y_barre + H_BARRE - 1],
            fill=_couleur_pv(ratio),
        )
    texte_pv = f"{pv_actuels} / {pv_max} PV"
    draw.text((x + largeur - 5 - draw.textlength(texte_pv, font=police_detail), y + rel_pv), texte_pv, font=police_detail, fill=(40, 40, 40))

    if afficher_pokeballs:
        _dessiner_ligne_pokeballs(scene, x + largeur if ancre_droite else x, y - 14, equipe_vivante, ancre_droite=ancre_droite)
    return hauteur_bloc

def _nettoyer_texte_log(ligne: str, noms: dict = None) -> str:
    """Nettoie une ligne de log pour l'affichage dans l'image : retire les codes d'emoji
    custom Discord (<:nom:id>) et les emoji Unicode (aucun des deux ne s'affiche
    correctement avec la police système, juste un rectangle "tofu" vide), et remplace
    les mentions <@id> par le vrai nom du joueur si connu (sinon les retire, mieux que
    d'afficher un ID brut illisible)."""
    import re
    ligne = re.sub(r"<a?:\w+:\d+>", "", ligne)

    def _remplacer_mention(m):
        if noms:
            try:
                return noms.get(int(m.group(1)), "")
            except ValueError:
                return ""
        return ""
    ligne = re.sub(r"<@!?(\d+)>", _remplacer_mention, ligne)

    # Retire tout emoji Unicode restant (plages courantes) — la police système ne les
    # affiche pas nativement, mieux vaut les enlever qu'un rectangle vide illisible.
    ligne = re.sub(
        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2B00-\u2BFF\uFE0F]+", "", ligne
    )
    ligne = ligne.replace("**", "")  # markdown Discord, ne s'affiche pas dans une image PIL
    return re.sub(r"\s+", " ", ligne).strip()


def _tronquer_texte(draw: ImageDraw.ImageDraw, texte: str, police, largeur_max: int) -> str:
    """Coupe le texte avec '…' si sa largeur dépasserait largeur_max — évite que le
    journal déborde sur le bloc PV de l'adversaire quand un pseudo + une description
    d'attaque sont longs."""
    if draw.textlength(texte, font=police) <= largeur_max:
        return texte
    while texte and draw.textlength(texte + "…", font=police) > largeur_max:
        texte = texte[:-1]
    return texte + "…"


def _dessiner_log_tour(
    scene: Image.Image, lignes: list, tour: int = None, noms: dict = None, x: int = 10, y: int = 10, max_lignes: int = 6,
    lignes_precedentes: list = None, tour_precedent: int = None,
) -> int:
    """Dessine le bloc de log (avec le numéro de tour en première ligne, en gras) en haut
    à gauche. Si lignes_precedentes est fourni, le tour d'avant reste visible juste
    au-dessus (grisé, limité à 3 lignes) — permet de comparer avec ce que l'adversaire a
    fait au tour précédent sans que ça disparaisse dès que le tour suivant se résout.
    Retourne la largeur totale du bloc dessiné (0 si rien dessiné) — sert à placer les
    badges météo/terrain juste à côté, sans les faire chevaucher. Largeur plafonnée
    (LARGEUR_MAX_LOG) pour ne jamais chevaucher le bloc PV de l'adversaire, même avec un
    pseudo + une description d'attaque longs sur la même ligne."""
    MAX_LIGNES_PRECEDENT = 3
    LARGEUR_MAX_LOG = round(scene.width * 0.58)
    police = _police(7)
    police_titre = _police(8)
    lignes_propres = [_nettoyer_texte_log(l, noms) for l in (lignes or []) if l.strip()]
    lignes_propres = [l for l in lignes_propres if l]
    lignes_propres = lignes_propres[:max_lignes]

    lignes_prec_propres = [_nettoyer_texte_log(l, noms) for l in (lignes_precedentes or []) if l.strip()]
    lignes_prec_propres = [l for l in lignes_prec_propres if l][:MAX_LIGNES_PRECEDENT]

    titre = f"Tour {tour}" if tour else None
    titre_precedent = f"Tour {tour_precedent}" if tour_precedent and lignes_prec_propres else None
    if not lignes_propres and not titre and not lignes_prec_propres:
        return 0

    draw = ImageDraw.Draw(scene)
    lignes_propres = [_tronquer_texte(draw, l, police, LARGEUR_MAX_LOG - 12) for l in lignes_propres]
    lignes_prec_propres = [_tronquer_texte(draw, l, police, LARGEUR_MAX_LOG - 12) for l in lignes_prec_propres]
    if titre:
        titre = _tronquer_texte(draw, titre, police_titre, LARGEUR_MAX_LOG - 12)
    if titre_precedent:
        titre_precedent = _tronquer_texte(draw, titre_precedent, police_titre, LARGEUR_MAX_LOG - 12)

    hauteur_ligne = 10
    largeurs = [draw.textlength(l, font=police) for l in lignes_propres + lignes_prec_propres]
    if titre:
        largeurs.append(draw.textlength(titre, font=police_titre))
    if titre_precedent:
        largeurs.append(draw.textlength(titre_precedent, font=police_titre))
    largeur_max = max(largeurs, default=100)

    nb_lignes_precedent = len(lignes_prec_propres) + (1 if titre_precedent else 0)
    hauteur_section_precedente = nb_lignes_precedent * hauteur_ligne + (6 if nb_lignes_precedent else 0)
    nb_lignes_actuel = len(lignes_propres) + (1 if titre else 0)
    hauteur_bloc = hauteur_section_precedente + nb_lignes_actuel * hauteur_ligne + 8
    largeur_bloc = min(largeur_max + 12, LARGEUR_MAX_LOG)
    draw.rounded_rectangle(
        [x, y, x + largeur_bloc, y + hauteur_bloc], radius=4, fill=(20, 20, 25, 200), outline=(200, 200, 200, 180), width=1
    )
    curseur_y = y + 4
    if nb_lignes_precedent:
        if titre_precedent:
            draw.text((x + 6, curseur_y), titre_precedent, font=police_titre, fill=(150, 150, 130))
            curseur_y += hauteur_ligne
        for ligne in lignes_prec_propres:
            draw.text((x + 6, curseur_y), ligne, font=police, fill=(150, 150, 150))
            curseur_y += hauteur_ligne
        draw.line([(x + 6, curseur_y + 1), (x + largeur_bloc - 6, curseur_y + 1)], fill=(90, 90, 90, 180), width=1)
        curseur_y += 5
    if titre:
        draw.text((x + 6, curseur_y), titre, font=police_titre, fill=(255, 220, 120))
        curseur_y += hauteur_ligne
    for ligne in lignes_propres:
        draw.text((x + 6, curseur_y), ligne, font=police, fill=(255, 255, 255))
        curseur_y += hauteur_ligne
    return largeur_bloc


def _dessiner_badge_info(scene: Image.Image, x: int, y: int, texte_principal: str, texte_secondaire: str, couleur_fond: tuple) -> int:
    """Petit badge compact (fond coloré, 2 lignes de texte) pour la météo ou le terrain
    actif. Retourne sa largeur (pour empiler plusieurs badges côte à côte)."""
    draw = ImageDraw.Draw(scene)
    police_principal = _police(8)
    police_secondaire = _police(6)
    largeur = max(
        round(draw.textlength(texte_principal, font=police_principal)),
        round(draw.textlength(texte_secondaire, font=police_secondaire)) if texte_secondaire else 0,
    ) + 10
    hauteur = 21
    draw.rounded_rectangle([x, y, x + largeur, y + hauteur], radius=4, fill=couleur_fond, outline=(255, 255, 255, 200), width=1)
    draw.text((x + 5, y + 2), texte_principal, font=police_principal, fill=(255, 255, 255))
    if texte_secondaire:
        draw.text((x + 5, y + 11), texte_secondaire, font=police_secondaire, fill=(235, 235, 235))
    return largeur


def _dessiner_indicateurs_meteo_terrain(scene: Image.Image, x: int, y: int, meteo_type: str, terrain_type: str):
    """Dessine côte à côte le badge météo (s'il y en a une) puis le badge terrain (s'il y
    en a un), juste à droite du bloc de log. Pas d'emoji dans le texte (même limite de
    police que pour les badges de statut) — la couleur du fond suffit à distinguer."""
    curseur_x = x
    if meteo_type:
        info = METEO_INFO_LOCAL.get(meteo_type)
        if info:
            largeur = _dessiner_badge_info(scene, curseur_x, y, "Météo", info["nom_affiche"], (50, 90, 140, 235))
            curseur_x += largeur + 8
    if terrain_type:
        info = TERRAIN_INFO_LOCAL.get(terrain_type)
        if info:
            _dessiner_badge_info(scene, curseur_x, y, "Terrain", info["nom_affiche"], (60, 120, 70, 235))


def generer_image_combat(
    pokemon_joueur: dict, nom_joueur_affiche: str, niveau_joueur: int, pv_joueur: int, pv_max_joueur: int, shiny_joueur: bool,
    code_statut_joueur: str, boosts_joueur: dict, equipe_joueur_vivante: list,
    pokemon_adversaire: dict, nom_adversaire_affiche: str, niveau_adversaire: int, pv_adversaire: int, pv_max_adversaire: int, shiny_adversaire: bool,
    code_statut_adversaire: str, boosts_adversaire: dict, equipe_adversaire_vivante: list,
    log_tour: list = None, noms: dict = None, tour: int = None, meteo_type: str = None, terrain_type: str = None,
    log_precedent: list = None, tour_precedent: int = None, type_combat: str = "dresseur",
) -> bytes | None:
    """Retourne les bytes PNG de la scène composée, ou None si le fond ou l'un des deux
    sprites n'a pas pu être chargé (appelant doit alors se contenter du texte, pas
    d'échec bruyant pour un souci purement visuel). type_combat sélectionne le fond et
    son calibrage propre (voir CONFIGS_FOND) — "dresseur" par défaut (dresseurs sauvages,
    PvP), "arene" ou "repaire" pour ces contextes précis."""
    config_fond = CONFIGS_FOND.get(type_combat, CONFIGS_FOND["dresseur"])
    try:
        scene = Image.open(config_fond["chemin"]).convert("RGBA")
    except (FileNotFoundError, OSError) as e:
        import os
        print(f"⚠️ [combat_visuel] Fond introuvable ({os.path.abspath(config_fond['chemin'])}) : {e}")
        return None

    sprite_j = _sprite_joueur(pokemon_joueur, shiny_joueur)
    sprite_a = _sprite_adversaire(pokemon_adversaire, shiny_adversaire)
    if sprite_j is None or sprite_a is None:
        print("⚠️ [combat_visuel] Au moins un des 2 sprites n'a pas pu être chargé (voir message ci-dessus)")
        return None

    sprite_j = _redimensionner_propre(sprite_j, round(config_fond["taille_max_joueur"] * _facteur_taille_reelle(pokemon_joueur)))
    sprite_a = _redimensionner_propre(sprite_a, round(config_fond["taille_max_adversaire"] * _facteur_taille_reelle(pokemon_adversaire)))

    _coller_centre_sur_ancre(scene, sprite_a, config_fond["ancre_adversaire"])
    _coller_centre_sur_ancre(scene, sprite_j, config_fond["ancre_joueur"])

    # Réduction/agrandissement UNIQUE vers une taille proche de l'affichage réel Discord
    # en conversation (recherché : ~400-520px de large selon la fenêtre) — le fond de
    # départ (800×440 ici) n'a pas besoin de correspondre exactement, du moment qu'on
    # ramène nous-mêmes le résultat final à cette taille AVANT l'envoi. Sans ça, Discord
    # réduirait lui-même l'image à l'affichage, et ce réechantillonnage fait par Discord
    # (hors de notre contrôle) adoucit visiblement les détails fins. Fait ICI, sprites
    # déjà collés mais AVANT le HUD/texte ci-dessous — dessiner le texte après ce
    # redimensionnement, pas avant, le garde net à n'importe quelle échelle (police
    # vectorielle) au lieu de le faire grossir/rétrécir avec le reste.
    LARGEUR_SORTIE_FINALE = 550
    ratio_sortie = LARGEUR_SORTIE_FINALE / scene.width
    scene = scene.resize((LARGEUR_SORTIE_FINALE, round(scene.height * ratio_sortie)), Image.LANCZOS)

    _dessiner_bloc_hud(
        scene, 10, scene.height - 10, nom_joueur_affiche, niveau_joueur, pv_joueur, pv_max_joueur,
        code_statut_joueur, boosts_joueur, equipe_joueur_vivante, ancre_bas=True,
    )
    _dessiner_bloc_hud(
        scene, scene.width - 10, 10 + 16, nom_adversaire_affiche, niveau_adversaire, pv_adversaire, pv_max_adversaire,
        code_statut_adversaire, boosts_adversaire, equipe_adversaire_vivante, ancre_droite=True,
    )

    largeur_log = 0
    if log_tour or tour:
        largeur_log = _dessiner_log_tour(scene, log_tour, tour=tour, noms=noms, lignes_precedentes=log_precedent, tour_precedent=tour_precedent)

    if meteo_type or terrain_type:
        x_badges = 10 + largeur_log + 6 if largeur_log else 10
        _dessiner_indicateurs_meteo_terrain(scene, x_badges, 10, meteo_type, terrain_type)

    # Rehaussement final (contraste + saturation + netteté légère) — sans ça, l'image
    # ressort visiblement plus terne/plate qu'une référence comparable (mesuré : écart
    # de contraste et de saturation réels, pas juste une impression). Fait en tout
    # dernier, HUD/texte compris, pour un rendu cohérent — vérifié que ça ne crée pas
    # de halo sur le texte déjà net (police vectorielle, contrairement aux sprites).
    scene_rgb = scene.convert("RGB")
    scene_rgb = ImageEnhance.Contrast(scene_rgb).enhance(1.18)
    scene_rgb = ImageEnhance.Color(scene_rgb).enhance(1.15)
    scene_rgb = ImageEnhance.Sharpness(scene_rgb).enhance(1.3)

    tampon = io.BytesIO()
    scene_rgb.save(tampon, format="PNG")
    return tampon.getvalue()


def generer_image_combat_2v2(
    equipe_joueur: list, equipe_adversaire: list,
    log_tour: list = None, noms: dict = None, tour: int = None, meteo_type: str = None, terrain_type: str = None,
    log_precedent: list = None, tour_precedent: int = None, type_combat: str = "dresseur",
) -> bytes | None:
    """Équivalent 2v2 de generer_image_combat — mêmes principes (fond + sprites + HUD +
    journal), mais 2 combattants par camp au lieu d'1 seul. `equipe_joueur` et
    `equipe_adversaire` sont chacune une liste de 2 dicts avec les clés :
    pokemon, nom_affiche, niveau, pv, pv_max, shiny, code_statut, boosts, equipe_vivante
    (une équipe déjà K.O. peut passer un dict à None pour ce membre — rien n'est dessiné
    pour lui, l'autre combattant du camp continue de s'afficher normalement). type_combat
    sélectionne le fond, voir generer_image_combat."""
    config_fond = CONFIGS_FOND.get(type_combat, CONFIGS_FOND["dresseur"])
    try:
        scene = Image.open(config_fond["chemin"]).convert("RGBA")
    except (FileNotFoundError, OSError) as e:
        import os
        print(f"⚠️ [combat_visuel] Fond introuvable ({os.path.abspath(config_fond['chemin'])}) : {e}")
        return None

    for i, combattant in enumerate(equipe_joueur[:2]):
        if not combattant:
            continue
        sprite = _sprite_joueur(combattant["pokemon"], combattant.get("shiny", False))
        if sprite is None:
            print(f"⚠️ [combat_visuel] Sprite joueur {i+1} introuvable, ce combattant sera absent de la scène")
            continue
        sprite = _redimensionner_propre(sprite, round(config_fond["taille_max_joueur_2v2"] * _facteur_taille_reelle(combattant["pokemon"])))
        _coller_centre_sur_ancre(scene, sprite, config_fond["ancres_joueur_2v2"][i])

    for i, combattant in enumerate(equipe_adversaire[:2]):
        if not combattant:
            continue
        sprite = _sprite_adversaire(combattant["pokemon"], combattant.get("shiny", False))
        if sprite is None:
            print(f"⚠️ [combat_visuel] Sprite adversaire {i+1} introuvable, ce combattant sera absent de la scène")
            continue
        sprite = _redimensionner_propre(sprite, round(config_fond["taille_max_adversaire_2v2"] * _facteur_taille_reelle(combattant["pokemon"])))
        _coller_centre_sur_ancre(scene, sprite, config_fond["ancres_adversaire_2v2"][i])

    LARGEUR_SORTIE_FINALE = 550
    ratio_sortie = LARGEUR_SORTIE_FINALE / scene.width
    scene = scene.resize((LARGEUR_SORTIE_FINALE, round(scene.height * ratio_sortie)), Image.LANCZOS)

    # HUD : 2 blocs empilés par coin (compacts, gap réduit par rapport au 1v1 qui n'en a
    # qu'un seul par coin) — joueur en bas-gauche, adversaire en haut-droite. Si les 2
    # combattants d'un même camp sont contrôlés par la MÊME personne (cas "solo double"
    # — voir cle_controleur, transmis par combat_2v2.py quand il est connu), les Poké
    # Balls ne sont dessinées qu'une seule fois plutôt que dupliquées. Repli sur une
    # comparaison de equipe_vivante si cle_controleur n'est pas fourni par l'appelant.
    def _meme_equipe(a: dict, b: dict) -> bool:
        if not a or not b:
            return False
        if a.get("cle_controleur") is not None or b.get("cle_controleur") is not None:
            return a.get("cle_controleur") == b.get("cle_controleur")
        return a.get("equipe_vivante") == b.get("equipe_vivante")

    equipe_partagee_joueur = _meme_equipe(equipe_joueur[0] if equipe_joueur else None, equipe_joueur[1] if len(equipe_joueur) > 1 else None)
    y_bloc_joueur = scene.height - 10
    for i, combattant in enumerate(reversed(equipe_joueur[:2])):
        if not combattant:
            continue
        afficher_balls = not (equipe_partagee_joueur and i == 0)
        hauteur_bloc = _dessiner_bloc_hud(
            scene, 10, y_bloc_joueur, combattant["nom_affiche"], combattant["niveau"], combattant["pv"], combattant["pv_max"],
            combattant.get("code_statut"), combattant.get("boosts", {}), combattant.get("equipe_vivante", []), ancre_bas=True,
            afficher_pokeballs=afficher_balls,
        )
        y_bloc_joueur -= (hauteur_bloc if hauteur_bloc else 0) + 32

    equipe_partagee_adversaire = _meme_equipe(equipe_adversaire[0] if equipe_adversaire else None, equipe_adversaire[1] if len(equipe_adversaire) > 1 else None)
    y_bloc_adversaire = 10 + 16
    for i, combattant in enumerate(equipe_adversaire[:2]):
        if not combattant:
            continue
        afficher_balls = not (equipe_partagee_adversaire and i == 0)
        hauteur_bloc = _dessiner_bloc_hud(
            scene, scene.width - 10, y_bloc_adversaire, combattant["nom_affiche"], combattant["niveau"], combattant["pv"], combattant["pv_max"],
            combattant.get("code_statut"), combattant.get("boosts", {}), combattant.get("equipe_vivante", []), ancre_droite=True,
            afficher_pokeballs=afficher_balls,
        )
        y_bloc_adversaire += (hauteur_bloc if hauteur_bloc else 0) + 32

    largeur_log = 0
    if log_tour or tour:
        largeur_log = _dessiner_log_tour(scene, log_tour, tour=tour, noms=noms, lignes_precedentes=log_precedent, tour_precedent=tour_precedent)

    if meteo_type or terrain_type:
        x_badges = 10 + largeur_log + 6 if largeur_log else 10
        _dessiner_indicateurs_meteo_terrain(scene, x_badges, 10, meteo_type, terrain_type)

    scene_rgb = scene.convert("RGB")
    scene_rgb = ImageEnhance.Contrast(scene_rgb).enhance(1.18)
    scene_rgb = ImageEnhance.Color(scene_rgb).enhance(1.15)
    scene_rgb = ImageEnhance.Sharpness(scene_rgb).enhance(1.3)

    tampon = io.BytesIO()
    scene_rgb.save(tampon, format="PNG")
    return tampon.getvalue()
