"""
Formes alternatives déclenchées par un objet tenu — PAS le même mécanisme que les formes
régionales (Alola/Galar/Hisui/Paldea, voir ajouter_formes_regionales.py). Ici, c'est le
MÊME Pokémon capturé (mêmes IV, même niveau, même capture_id) qui change d'apparence et de
stats tant qu'il tient un objet précis, et reprend sa forme normale dès qu'on le lui
retire — exactement comme une Méga-Évolution, pas une nouvelle capture.

Portée actuelle (4 formes, les plus simples à modéliser — un seul objet, aucune
mécanique de fusion) :
- Shaymin + Fleur Gracidea → Shaymin (Forme Céleste)
- Giratina + Orbe Griséous → Giratina (Origine)
- Dialga + Orbe Adamant → Dialga (Origine)
- Palkia + Perle Lustrée → Palkia (Origine)

Volontairement HORS PÉRIPHÉRIE pour l'instant (mécaniques plus complexes, à concevoir à
part) : Kyurem Noir/Blanc (fusion avec un Zekrom/Reshiram capturé dans les vrais jeux,
pas un simple objet tenu) et Keldeo Résolu (débloqué par une capacité apprise, pas un
objet). À reprendre dans un lot séparé une fois qu'on aura décidé comment les adapter.

Ces objets ne sont PAS achetables en boutique (décision du 01/08/2026) — uniquement
obtenables via l'exploration (petite chance, voir config.EXPLORATION_CHANCE_OBJET_FORME)
ou déjà tenus par le Pokémon sauvage correspondant au moment de sa capture (voir
views.py/raid.py — chance_objet_forme_a_la_capture).

Les stats sont RÉELLES (vérifiées contre PokéAPI), mais le PC affiché au joueur NE
CHANGE PAS avec la forme (décision du 01/08/2026, pour rester simple et lisible) — seules
les stats de COMBAT (calcul des dégâts, PV réels) et les types changent.
"""

FORMES_OBJETS = {
    "fleur_gracidea": {
        "objet_nom": "Fleur Gracidea",
        "objet_emoji": "🌸",
        "espece": "Shaymin",
        "forme_nom": "Shaymin (Forme Céleste)",
        "numero_sprite": 10006,
        "types": ["plante", "vol"],
        "stats_detaillees": {"pv": 100, "attaque": 103, "defense": 75, "attaque_spe": 120, "defense_spe": 75, "vitesse": 127},
    },
    "orbe_griseous": {
        "objet_nom": "Orbe Griséous",
        "objet_emoji": "🔮",
        "espece": "Giratina",
        "forme_nom": "Giratina (Origine)",
        "numero_sprite": 10007,
        "types": ["spectre", "dragon"],
        "stats_detaillees": {"pv": 150, "attaque": 120, "defense": 100, "attaque_spe": 120, "defense_spe": 100, "vitesse": 90},
    },
    "orbe_adamant": {
        "objet_nom": "Orbe Adamant",
        "objet_emoji": "💎",
        "espece": "Dialga",
        "forme_nom": "Dialga (Origine)",
        "numero_sprite": 10245,
        "types": ["acier", "dragon"],
        "stats_detaillees": {"pv": 100, "attaque": 100, "defense": 100, "attaque_spe": 150, "defense_spe": 120, "vitesse": 110},
    },
    "perle_lustree": {
        "objet_nom": "Perle Lustrée",
        "objet_emoji": "💠",
        "espece": "Palkia",
        "forme_nom": "Palkia (Origine)",
        "numero_sprite": 10246,
        "types": ["eau", "dragon"],
        "stats_detaillees": {"pv": 90, "attaque": 100, "defense": 100, "attaque_spe": 150, "defense_spe": 120, "vitesse": 120},
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
    }


def nom_affichage(pokemon_nom: str, objet_tenu: str | None) -> str:
    """Nom à afficher au joueur (embeds, fiches...) — le nom de la forme alternative si
    elle est active, sinon le nom normal du Pokémon."""
    forme = forme_objet_pour(pokemon_nom, objet_tenu)
    return forme["forme_nom"] if forme else pokemon_nom
