"""
Formes alternatives déclenchées par un objet tenu — PAS le même mécanisme que les formes
régionales (Alola/Galar/Hisui/Paldea, voir ajouter_formes_regionales.py). Ici, c'est le
MÊME Pokémon capturé (mêmes IV, même niveau, même capture_id) qui change d'apparence et de
stats tant qu'il tient un objet précis, et reprend sa forme normale dès qu'on le lui
retire — exactement comme une Méga-Évolution, pas une nouvelle capture.

Portée actuelle (9 formes, toutes déclenchées par un seul objet, aucune mécanique de
fusion) :
- Shaymin + Fleur Gracidea → Shaymin (Forme Céleste)
- Giratina + Orbe Griséous → Giratina (Origine)
- Dialga + Orbe Adamant → Dialga (Origine)
- Palkia + Perle Lustrée → Palkia (Origine)
- Kyogre + Orbe Bleue → Primo-Kyogre
- Groudon + Orbe Rouge → Primo-Groudon
- Hoopa + Vase de l'Entrave → Hoopa Déchaîné
- Zacian + Épée Rouillée → Zacian (Épée Suprême)
- Zamazenta + Bouclier Rouillé → Zamazenta (Bouclier Suprême)

Volontairement HORS PÉRIMÈTRE pour l'instant (mécaniques plus complexes, à concevoir à
part) : Kyurem Noir/Blanc (fusion avec un Zekrom/Reshiram capturé dans les vrais jeux,
pas un simple objet tenu) et Keldeo Résolu (débloqué par une capacité apprise, pas un
objet). À reprendre dans un lot séparé une fois qu'on aura décidé comment les adapter.

⚠️ Suppose que Kyogre, Groudon, Hoopa, Zacian et Zamazenta sont déjà des espèces
capturables normalement dans le Pokédex (confirmé par l'utilisateur le 08/08/2026) — ce
module ne les ajoute pas, il se contente de leur donner une forme alternative.

Ces objets ne sont PAS achetables en boutique (décision du 01/08/2026) — uniquement
obtenables via l'exploration (petite chance, voir config.EXPLORATION_CHANCE_OBJET_FORME)
ou déjà tenus par le Pokémon sauvage correspondant au moment de sa capture (voir
views.py/raid.py — chance_objet_forme_a_la_capture).

Les stats sont RÉELLES (vérifiées contre PokéAPI/Poképédia), mais le PC affiché au joueur
NE CHANGE PAS avec la forme (décision du 01/08/2026, pour rester simple et lisible) —
seules les stats de COMBAT (calcul des dégâts, PV réels) et les types changent.
"""

FORMES_OBJETS = {
    "fleur_gracidea": {
        "objet_nom": "Fleur Gracidea",
        "objet_emoji": "🌸",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/fleur_gracidea.png",
        "espece": "Shaymin",
        "forme_nom": "Shaymin (Forme Céleste)",
        "numero_sprite": 10006,
        "sprite_gif_disponible": False,  # forme trop rare pour un GIF Showdown fiable — repli sur l'artwork officiel statique, garanti disponible
        "types": ["plante", "vol"],
        "stats_detaillees": {"pv": 100, "attaque": 103, "defense": 75, "attaque_spe": 120, "defense_spe": 75, "vitesse": 127},
    },
    "orbe_griseous": {
        "objet_nom": "Orbe Griséous",
        "objet_emoji": "🔮",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_griseous.png",
        "espece": "Giratina",
        "forme_nom": "Giratina (Origine)",
        "numero_sprite": 10007,
        "sprite_gif_disponible": False,
        "types": ["spectre", "dragon"],
        "stats_detaillees": {"pv": 150, "attaque": 120, "defense": 100, "attaque_spe": 120, "defense_spe": 100, "vitesse": 90},
    },
    "orbe_adamant": {
        "objet_nom": "Orbe Adamant",
        "objet_emoji": "💎",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_adamant.png",
        "espece": "Dialga",
        "forme_nom": "Dialga (Origine)",
        "numero_sprite": 10245,
        "sprite_gif_disponible": False,
        "types": ["acier", "dragon"],
        "stats_detaillees": {"pv": 100, "attaque": 100, "defense": 100, "attaque_spe": 150, "defense_spe": 120, "vitesse": 110},
    },
    "perle_lustree": {
        "objet_nom": "Perle Lustrée",
        "objet_emoji": "💠",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/perle_lustree.png",
        "espece": "Palkia",
        "forme_nom": "Palkia (Origine)",
        "numero_sprite": 10246,
        "sprite_gif_disponible": False,
        "types": ["eau", "dragon"],
        "stats_detaillees": {"pv": 90, "attaque": 100, "defense": 100, "attaque_spe": 150, "defense_spe": 120, "vitesse": 120},
    },
    "orbe_bleue": {
        "objet_nom": "Orbe Bleue",
        "objet_emoji": "🔵",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_bleue.png",
        "espece": "Kyogre",
        "forme_nom": "Primo-Kyogre",
        "numero_sprite": 10077,
        "sprite_gif_disponible": False,
        "types": ["eau"],
        "stats_detaillees": {"pv": 100, "attaque": 150, "defense": 90, "attaque_spe": 180, "defense_spe": 160, "vitesse": 90},
    },
    "orbe_rouge": {
        "objet_nom": "Orbe Rouge",
        "objet_emoji": "🔴",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_rouge.png",
        "espece": "Groudon",
        "forme_nom": "Primo-Groudon",
        "numero_sprite": 10078,
        "sprite_gif_disponible": False,
        "types": ["sol", "feu"],
        "stats_detaillees": {"pv": 100, "attaque": 180, "defense": 160, "attaque_spe": 150, "defense_spe": 90, "vitesse": 90},
    },
    "vase_entrave": {
        "objet_nom": "Vase de l'Entrave",
        "objet_emoji": "🏺",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/vase_entrave.png",
        "espece": "Hoopa",
        "forme_nom": "Hoopa Déchaîné",
        "numero_sprite": 10086,
        "sprite_gif_disponible": False,
        "types": ["psy", "tenebres"],
        "stats_detaillees": {"pv": 80, "attaque": 160, "defense": 60, "attaque_spe": 170, "defense_spe": 130, "vitesse": 80},
    },
    "epee_rouillee": {
        "objet_nom": "Épée Rouillée",
        "objet_emoji": "⚔️",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/epee_rouillee.png",
        "espece": "Zacian",
        "forme_nom": "Zacian (Épée Suprême)",
        "numero_sprite": 10188,
        "sprite_gif_disponible": False,
        "types": ["fee", "acier"],
        "stats_detaillees": {"pv": 92, "attaque": 150, "defense": 115, "attaque_spe": 80, "defense_spe": 115, "vitesse": 148},
    },
    "bouclier_rouille": {
        "objet_nom": "Bouclier Rouillé",
        "objet_emoji": "🛡️",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/bouclier_rouille.png",
        "espece": "Zamazenta",
        "forme_nom": "Zamazenta (Bouclier Suprême)",
        "numero_sprite": 10189,
        "sprite_gif_disponible": False,
        "types": ["combat", "acier"],
        "stats_detaillees": {"pv": 92, "attaque": 130, "defense": 145, "attaque_spe": 80, "defense_spe": 145, "vitesse": 128},
    },
}

# Vue inverse : espèce -> objet qui la transforme, pour vérifier rapidement si un
# Pokémon donné a une forme alternative disponible du tout (avant même de regarder ce
# qu'il tient réellement).
ESPECE_VERS_OBJET_FORME = {info["espece"]: cle for cle, info in FORMES_OBJETS.items()}


def forme_objet_pour(pokemon_nom: str, objet_tenu: str | None) -> dict | None:
    """Retourne les infos de la forme alternative SI ce Pokémon tient l'objet qui la
    déclenche, sinon None (forme normale)."""
    if not objet_tenu:
        return None
    info = FORMES_OBJETS.get(objet_tenu)
    if info and info["espece"] == pokemon_nom:
        return info
    return None


def pokemon_effectif(pokemon: dict, objet_tenu: str | None) -> dict:
    """Retourne le dict Pokédex à utiliser pour les CALCULS (types + stats de base) —
    celui de la forme alternative si l'objet correspondant est tenu, sinon `pokemon`
    inchangé. Ne modifie jamais le PC affiché (voir docstring du module) : seuls les
    types et les stats_detaillees sont substitués."""
    if not pokemon:
        return pokemon
    forme = forme_objet_pour(pokemon["nom"], objet_tenu)
    if not forme:
        return pokemon
    return {
        **pokemon,
        "types": forme["types"],
        "stats_detaillees": forme["stats_detaillees"],
        "numero_sprite": forme["numero_sprite"],
        "sprite_gif_disponible": forme["sprite_gif_disponible"],
    }


def nom_affichage(pokemon_nom: str, objet_tenu: str | None) -> str:
    """Nom à afficher au joueur (embeds, fiches...) — le nom de la forme alternative si
    elle est active, sinon le nom normal du Pokémon."""
    forme = forme_objet_pour(pokemon_nom, objet_tenu)
    return forme["forme_nom"] if forme else pokemon_nom
