import json
import os
import random
import unicodedata

import config

# Rareté : commun / peu_commun / rare / hyper_rare / legendaire

TAUX_CAPTURE = {
    "commun": {"pokeball": 0.60, "superball": 0.75, "hyperball": 0.90, "masterball": 1.0, "honorball": 0.70},
    "peu_commun": {"pokeball": 0.35, "superball": 0.55, "hyperball": 0.75, "masterball": 1.0, "honorball": 0.45},
    "rare": {"pokeball": 0.15, "superball": 0.30, "hyperball": 0.50, "masterball": 1.0, "honorball": 0.20},
    "hyper_rare": {"pokeball": 0.08, "superball": 0.18, "hyperball": 0.35, "masterball": 1.0, "honorball": 0.07},
    "legendaire": {"pokeball": 0.05, "superball": 0.12, "hyperball": 0.25, "masterball": 1.0, "honorball": 0.02},
}

EMOJI_RARETE = {
    "commun": "⚪",
    "peu_commun": "🟢",
    "rare": "🔵",
    "hyper_rare": "🟣",
    "legendaire": "🟡",
}

# Couleur d'embed Discord par rareté
COULEUR_RARETE = {
    "commun": 0x9E9E9E,       # gris
    "peu_commun": 0x2ECC71,   # vert
    "rare": 0x3498DB,         # bleu
    "hyper_rare": 0x9B59B6,   # violet
    "legendaire": 0xF1C40F,   # or
}

NOM_BALL_AFFICHAGE = {
    "pokeball": "Poké Ball",
    "superball": "Super Ball",
    "hyperball": "Hyper Ball",
    "masterball": "Master Ball",
    "honorball": "Honor Ball",
}

# Émojis personnalisés du serveur (Master Ball prête pour un usage futur, pas encore utilisée en jeu)
EMOJI_BALLS = {
    "pokeball": "<:6673_pokeball:1524807945550823455>",
    "superball": "<:4705_pokeball_great:1524807943931826226>",
    "hyperball": "<:4040_pokeball_ultra:1524807942615072768>",
    "masterball": "<:4713_pokeball_master:1524807947249651854>",
    "honorball": "<:200pxHonor_BallRS:1525245355623579939>",
}

EMOJI_POKEDEX = "<:Pkdex:1524812405433962537>"
EMOJI_POKEDOLLAR = "<:pokedollar:1524812915864244235>"

NOM_SOIN_AFFICHAGE = {
    "potion": "Potion",
    "superpotion": "Super Potion",
    "hyperpotion": "Hyper Potion",
    "totalsoin": "Total Soin",
}
EMOJI_SOINS = {
    "potion": "🧪",
    "superpotion": "💊",
    "hyperpotion": "⚕️",
    "totalsoin": "🌿",
}

NOM_OBJETS_DIVERS = {
    "cristal_mutation": "Cristal de Mutation",
    "oeuf_commun": "Œuf Commun",
    "oeuf_peu_commun": "Œuf Peu Commun",
    "oeuf_rare": "Œuf Rare",
    "oeuf_hyper_rare": "Œuf Hyper Rare",
    "oeuf_legendaire": "Œuf Légendaire",
}
EMOJI_OBJETS_DIVERS = {
    "cristal_mutation": "🔮",
    "oeuf_commun": "🥚",
    "oeuf_peu_commun": "🐣",
    "oeuf_rare": "🐥",
    "oeuf_hyper_rare": "🌟",
    "oeuf_legendaire": "✨",
}

# Correspondance palier d'œuf <-> rareté du Pokédex (mêmes valeurs, alias pour la lisibilité
# du code de l'incubateur).
PALIER_OEUF_VERS_RARETE = {
    "commun": "commun",
    "peu_commun": "peu_commun",
    "rare": "rare",
    "hyper_rare": "hyper_rare",
    "legendaire": "legendaire",
}

# Émojis de type (correspondent aux valeurs françaises utilisées dans "types" du pokédex).
# "electrik" manque encore l'émoji correspondant — fallback texte en attendant.
EMOJI_TYPES = {
    "normal":   "<:459566normaltype:1524813692443689021>",
    "feu":      "<:80339firetype:1524813681538502808>",
    "eau":      "<:66792watertype:1524813679189688431>",
    "electrik": "<:679891electrictype:1524819074436300932>",
    "plante":   "<:664253grasstype:1524813694473863428>",
    "glace":    "<:349774icetype:1524813687905320990>",
    "combat":   "<:899710fightingtype:1524813712953835640>",
    "poison":   "<:132170poisontype:1524813682989600818>",
    "sol":      "<:828944groundtype:1524813710621802527>",
    "vol":      "<:800738flyingtype:1524813706511253554>",
    "psy":      "<:734116psychictype:1524813791853019366>",
    "insecte":  "<:455882bugtype:1524813690837274735>",
    "roche":    "<:27314rocktype:1524813676371251332>",
    "spectre":  "<:848015ghosttype:1524813711771172874>",
    "dragon":   "<:234172dragontype:1524813685900447935>",
    "tenebres": "<:219234darktype:1524813684340424905>",
    "acier":    "<:5512steeltype:1524813675012292618>",
    "fee":      "<:701529fairytype:1524813695979356301>",
}

# Table d'efficacité des types (attaquant -> défenseur -> multiplicateur)
# 2.0 = super efficace, 0.5 = peu efficace, 0.0 = immunisé, 1.0 = normal (implicite)
EFFICACITE_TYPES = {
    "feu":      {"plante": 2.0, "glace": 2.0, "insecte": 2.0, "acier": 2.0, "eau": 0.5, "roche": 0.5, "dragon": 0.5, "feu": 0.5},
    "eau":      {"feu": 2.0, "roche": 2.0, "sol": 2.0, "plante": 0.5, "dragon": 0.5, "eau": 0.5},
    "plante":   {"eau": 2.0, "roche": 2.0, "sol": 2.0, "feu": 0.5, "plante": 0.5, "poison": 0.5, "vol": 0.5, "insecte": 0.5, "dragon": 0.5, "acier": 0.5},
    "electrik": {"eau": 2.0, "vol": 2.0, "plante": 0.5, "dragon": 0.5, "electrik": 0.5, "sol": 0.0},
    "glace":    {"plante": 2.0, "sol": 2.0, "vol": 2.0, "dragon": 2.0, "feu": 0.5, "eau": 0.5, "glace": 0.5, "acier": 0.5},
    "combat":   {"normal": 2.0, "glace": 2.0, "roche": 2.0, "tenebres": 2.0, "acier": 2.0, "poison": 0.5, "vol": 0.5, "psy": 0.5, "insecte": 0.5, "fee": 0.5, "spectre": 0.0},
    "poison":   {"plante": 2.0, "fee": 2.0, "poison": 0.5, "sol": 0.5, "roche": 0.5, "spectre": 0.5, "acier": 0.0},
    "sol":      {"feu": 2.0, "electrik": 2.0, "poison": 2.0, "roche": 2.0, "acier": 2.0, "plante": 0.5, "insecte": 0.5, "vol": 0.0},
    "vol":      {"plante": 2.0, "combat": 2.0, "insecte": 2.0, "electrik": 0.5, "roche": 0.5, "acier": 0.5},
    "psy":      {"combat": 2.0, "poison": 2.0, "psy": 0.5, "acier": 0.5, "tenebres": 0.0},
    "insecte":  {"plante": 2.0, "psy": 2.0, "tenebres": 2.0, "feu": 0.5, "combat": 0.5, "vol": 0.5, "spectre": 0.5, "acier": 0.5, "fee": 0.5},
    "roche":    {"feu": 2.0, "glace": 2.0, "vol": 2.0, "insecte": 2.0, "combat": 0.5, "sol": 0.5, "acier": 0.5},
    "spectre":  {"spectre": 2.0, "psy": 2.0, "normal": 0.0, "combat": 0.0, "tenebres": 0.5},
    "dragon":   {"dragon": 2.0, "acier": 0.5, "fee": 0.0},
    "tenebres": {"spectre": 2.0, "psy": 2.0, "combat": 0.5, "tenebres": 0.5, "fee": 0.5},
    "acier":    {"glace": 2.0, "roche": 2.0, "fee": 2.0, "feu": 0.5, "eau": 0.5, "electrik": 0.5, "acier": 0.5},
    "fee":      {"combat": 2.0, "dragon": 2.0, "tenebres": 2.0, "feu": 0.5, "poison": 0.5, "acier": 0.5},
    "normal":   {"roche": 0.5, "acier": 0.5, "spectre": 0.0},
}


def sprite_pokemon(pokemon: dict, shiny: bool = False) -> str | None:
    """URL de sprite ANIMÉ, hébergé sur notre propre dépôt GitHub — ce sont les sprites
    Showdown originaux, mais reencodés avec un disposal de frame correct (voir
    corriger_sprites.py) pour éliminer le bug de "ghosting" (traînée floue) que certains
    fichiers du pack communautaire original provoquaient sur le lecteur GIF de Discord.
    Repli sur le sprite statique stocké si jamais le numéro du Pokédex est indisponible."""
    if not pokemon:
        return None
    numero = pokemon.get("numero")
    if numero:
        sous_dossier = "shiny/" if shiny else ""
        return f"https://raw.githubusercontent.com/solafr67/pokewild/main/sprites_corriges/{sous_dossier}{numero}.gif"
    return pokemon.get("sprite_shiny") if shiny else pokemon.get("sprite")


def calculer_multiplicateur_type(types_attaquant: list, types_defenseur: list) -> float:
    """Calcule le multiplicateur de dégâts total en fonction des types de l'attaquant et du défenseur.
    Un Pokémon à deux types cumule les deux multiplicateurs (ex: eau vs feu/sol = 2.0 × 2.0 = 4.0)."""
    multiplicateur = 1.0
    for type_atk in types_attaquant:
        type_atk_norm = type_atk.lower()
        if type_atk_norm in EFFICACITE_TYPES:
            for type_def in types_defenseur:
                type_def_norm = type_def.lower()
                multi = EFFICACITE_TYPES[type_atk_norm].get(type_def_norm, 1.0)
                multiplicateur *= multi
    return multiplicateur
def cle_tri_alphabetique_fr(nom: str) -> str:
    """Clé de tri insensible aux accents — Python (et SQLite) trient par défaut par valeur
    de code Unicode, ce qui place "É"/"É" après "Z" au lieu de les mélanger avec "E"/"e"."""
    return "".join(c for c in unicodedata.normalize("NFKD", nom) if not unicodedata.combining(c)).lower()


def affichage_types(liste_types: list) -> str:
    """Formate une liste de types avec émoji si disponible, sinon retombe sur le nom texte."""
    morceaux = []
    for t in liste_types:
        emoji = EMOJI_TYPES.get(t)
        morceaux.append(f"{emoji} {t.capitalize()}" if emoji else t.capitalize())
    return " / ".join(morceaux)

# Astuce affichée selon la rareté, pour orienter le choix de ball du joueur
ASTUCE_RARETE = {
    "commun": "Une Poké Ball suffit largement.",
    "peu_commun": "Utilisez une Super Ball pour plus de chances.",
    "rare": "Une Hyper Ball est recommandée pour ce Pokémon.",
    "hyper_rare": "Une Hyper Ball est fortement recommandée, il est coriace !",
    "legendaire": "Une Hyper Ball est fortement recommandée !",
}

# Petite liste de secours (utilisée uniquement si pokedex_complet.json n'existe pas encore
# — voir generer_pokedex.py pour générer la base complète de tous les Pokémon existants)
POKEDEX_BASE = [
    {"nom": "Rattata", "types": ["normal"], "rarete": "commun", "base_pc": 40, "generation": 1},
    {"nom": "Roucool", "types": ["normal", "vol"], "rarete": "commun", "base_pc": 45, "generation": 1},
    {"nom": "Chenipan", "types": ["insecte"], "rarete": "commun", "base_pc": 35, "generation": 1},
    {"nom": "Aspicot", "types": ["insecte", "poison"], "rarete": "commun", "base_pc": 38, "generation": 1},
    {"nom": "Nidoran", "types": ["poison"], "rarete": "commun", "base_pc": 42, "generation": 1},
    {"nom": "Poissirene", "types": ["eau"], "rarete": "commun", "base_pc": 40, "generation": 1},
    {"nom": "Mimitoss", "types": ["insecte", "poison"], "rarete": "peu_commun", "base_pc": 90, "generation": 1},
    {"nom": "Ponyta", "types": ["feu"], "rarete": "peu_commun", "base_pc": 100, "generation": 1},
    {"nom": "Machoc", "types": ["combat"], "rarete": "peu_commun", "base_pc": 110, "generation": 1},
    {"nom": "Racaillou", "types": ["roche"], "rarete": "peu_commun", "base_pc": 85, "generation": 1},
    {"nom": "Psykokwak", "types": ["eau"], "rarete": "peu_commun", "base_pc": 95, "generation": 1},
    {"nom": "M. Mime", "types": ["psy", "fee"], "rarete": "peu_commun", "base_pc": 105, "generation": 1},
    {"nom": "Salameche", "types": ["feu"], "rarete": "rare", "base_pc": 180, "generation": 1},
    {"nom": "Carapuce", "types": ["eau"], "rarete": "rare", "base_pc": 175, "generation": 1},
    {"nom": "Bulbizarre", "types": ["plante", "poison"], "rarete": "rare", "base_pc": 178, "generation": 1},
    {"nom": "Evoli", "types": ["normal"], "rarete": "rare", "base_pc": 170, "generation": 1},
    {"nom": "Ronflex", "types": ["normal"], "rarete": "rare", "base_pc": 250, "generation": 1},
    {"nom": "Dracaufeu", "types": ["feu", "vol"], "rarete": "legendaire", "base_pc": 400, "generation": 1},
    {"nom": "Mewtwo", "types": ["psy"], "rarete": "legendaire", "base_pc": 500, "generation": 1},
    {"nom": "Artikodin", "types": ["glace", "vol"], "rarete": "legendaire", "base_pc": 450, "generation": 1},
    {"nom": "Sulfura", "types": ["electrik", "vol"], "rarete": "legendaire", "base_pc": 450, "generation": 1},
]

CHEMIN_JSON_COMPLET = os.path.join(os.path.dirname(__file__), "pokedex_complet.json")

if os.path.exists(CHEMIN_JSON_COMPLET):
    with open(CHEMIN_JSON_COMPLET, encoding="utf-8") as f:
        POKEDEX = json.load(f)
    print(f"📚 pokedex_complet.json chargé — {len(POKEDEX)} Pokémon disponibles.")
else:
    POKEDEX = POKEDEX_BASE
    print(
        f"📚 pokedex_complet.json introuvable — utilisation de la liste de base "
        f"({len(POKEDEX)} Pokémon). Lance generer_pokedex.py pour débloquer tous les Pokémon."
    )

# --- Attaques (générées par generer_pokedex.py dans attaques_complet.json) ---

CHEMIN_JSON_ATTAQUES = os.path.join(os.path.dirname(__file__), "attaques_complet.json")

# Attaque de secours utilisée quand un Pokémon n'a aucune attaque équipée
# (ou si attaques_complet.json n'a pas encore été généré)
ATTAQUE_DEFAUT_NOM = "Charge"
ATTAQUE_DEFAUT = {"type": "normal", "puissance": 40, "precision": 100, "classe": "physical", "stats": [], "cible": "adversaire"}

if os.path.exists(CHEMIN_JSON_ATTAQUES):
    with open(CHEMIN_JSON_ATTAQUES, encoding="utf-8") as f:
        ATTAQUES = json.load(f)
    print(f"⚔️ attaques_complet.json chargé — {len(ATTAQUES)} attaques disponibles.")
else:
    ATTAQUES = {ATTAQUE_DEFAUT_NOM: dict(ATTAQUE_DEFAUT)}
    print("⚔️ attaques_complet.json introuvable — relance generer_pokedex.py pour débloquer les attaques.")

if ATTAQUE_DEFAUT_NOM not in ATTAQUES:
    ATTAQUES[ATTAQUE_DEFAUT_NOM] = dict(ATTAQUE_DEFAUT)


def obtenir_attaque(nom: str) -> dict:
    """Détails d'une attaque par son nom FR, avec repli sur l'attaque par défaut."""
    return ATTAQUES.get(nom, ATTAQUE_DEFAUT)


def pp_max_attaque(attaque: dict) -> int:
    """PP maximum d'une attaque. Utilise la vraie valeur PokéAPI si disponible (relancer
    maj_attaques.py pour la récupérer), sinon un repli raisonnable basé sur la puissance
    (les attaques puissantes ont moins de PP dans les vrais jeux)."""
    pp = attaque.get("pp")
    if pp:
        return pp
    puissance = attaque.get("puissance")
    if not puissance:
        return 20  # attaque de statut par défaut
    if puissance >= 120:
        return 5
    if puissance >= 90:
        return 10
    if puissance >= 70:
        return 15
    if puissance >= 40:
        return 20
    return 25


# Attaques de terrain (entry hazards) gérées en combat : posées sur le terrain adverse,
# elles affectent chaque Pokémon ennemi qui ENTRE en combat (comme les vrais jeux).
ATTAQUES_TERRAIN = {
    "Piège de Roc": "stealth_rock",   # dégâts à l'entrée, multipliés par la faiblesse au type roche
    "Picots": "spikes",               # dégâts à l'entrée, cumulables jusqu'à 3 couches
    "Pics Toxik": "toxic_spikes",     # empoisonne le Pokémon qui entre
}

# Attaques à deux tours, gérées en combat. Liste tenue à la main (le nom français exact
# n'est pas exposé de façon fiable par la PokéAPI) — pas forcément exhaustive. Si une
# attaque à deux tours manque à l'appel, ajoute son nom français exact ici.
#
# CHARGE : tour 1 = charge sans dégâts, tour 2 = attaque à pleine puissance.
ATTAQUES_CHARGE = {
    "Lance-Soleil",
    "Lame-Vent",
    "Vrille Vigueur",
    "Attaque Céleste",
    "Choc Glace",
    "Éclat Glace",
    "Géocontrôle",
}
# RECHARGE : attaque immédiatement à pleine puissance, puis 1 tour de repos forcé.
ATTAQUES_RECHARGE = {
    "Ultimaton",
    "Ultralaser",
}


def attaques_apprenables(pokemon: dict) -> list:
    """Liste triée des attaques apprenables par ce Pokémon, en excluant celles sans
    aucun effet en jeu (ni dégâts, ni stats, ni statut, ni effet de terrain géré).
    Attaques offensives d'abord (par puissance décroissante), puis le reste (par nom)."""
    if not pokemon:
        return [ATTAQUE_DEFAUT_NOM]

    def est_utilisable(nom):
        attaque = ATTAQUES[nom]
        return bool(
            attaque.get("puissance")
            or attaque.get("stats")
            or attaque.get("ailment")
            or nom in ATTAQUES_TERRAIN
        )

    noms = [n for n in pokemon.get("attaques", []) if n in ATTAQUES and est_utilisable(n)]
    if not noms:
        return [ATTAQUE_DEFAUT_NOM]

    def cle_tri(nom):
        puissance = ATTAQUES[nom].get("puissance")
        return (0, -puissance) if puissance else (1, 0)

    return sorted(noms, key=lambda n: (cle_tri(n), n))

# Poids de tirage par rareté, pour le channel classique et le channel VIP
POIDS_RARETE_CLASSIQUE = {"commun": 60, "peu_commun": 26, "rare": 9, "hyper_rare": 3, "legendaire": 2}
POIDS_RARETE_VIP = {"commun": 45, "peu_commun": 30, "rare": 15, "hyper_rare": 6, "legendaire": 4}


def tirer_pokemon_aleatoire(poids_rarete: dict, multiplicateurs_meteo: dict | None = None):
    """Tire un Pokémon au hasard en pondérant par la rareté, avec un éventuel
    multiplicateur de météo appliqué sur des types précis (ex: {'eau': 2.0})."""
    multiplicateurs_meteo = multiplicateurs_meteo or {}

    pool_pondere = []
    for pokemon in POKEDEX:
        poids = poids_rarete[pokemon["rarete"]]
        for t in pokemon["types"]:
            if t in multiplicateurs_meteo:
                poids = int(poids * multiplicateurs_meteo[t])
                break
        pool_pondere.extend([pokemon] * max(poids, 1))

    return random.choice(pool_pondere)


def generer_pc(pokemon: dict) -> int:
    """Génère le PC d'un Pokémon sauvage à partir de ses stats de base, d'un multiplicateur
    lié à sa rareté, et d'une légère variance aléatoire (façon IV). Pas de notion de niveau."""
    variance = random.uniform(config.PC_VARIANCE_MIN, config.PC_VARIANCE_MAX)
    multiplicateur = config.MULTIPLICATEUR_PC_PAR_RARETE[pokemon["rarete"]]
    pc = round(pokemon["base_pc"] * multiplicateur * variance)
    return min(pc, config.PC_MAXIMUM)


def calculer_pv_max(pc: int) -> int:
    """Calcule les PV de combat max d'un Pokémon à partir de son PC."""
    return max(1, round(pc * config.FACTEUR_PV_PAR_PC))


def stat_effective(pokemon: dict, cle_stat: str, pc: int, niveau: int, niveau_max: int):
    """Valeur effective d'une stat de combat (attaque/defense/attaque_spe/defense_spe/
    vitesse) pour un INDIVIDU précis, à partir de :
    - la stat de base de l'espèce (PokéAPI, via stats_detaillees)
    - son ratio PC individuel / base_pc (même rareté+variance que celle qui détermine
      déjà le PC affiché — pas un second tirage séparé)
    - son niveau, en pourcentage de son propre plafond (0.7x au niveau 1, 1.3x au plafond
      quelle que soit la rareté — le niveau reflète l'entraînement, pas la rareté, qui est
      déjà pleinement portée par le PC)

    Retourne None si stats_detaillees n'est pas encore disponible (avant le premier
    passage de maj_stats.py) — à charge de l'appelant de retomber sur l'ancien calcul
    basé uniquement sur le PC dans ce cas."""
    stats_base = pokemon.get("stats_detaillees")
    if not stats_base or cle_stat not in stats_base:
        return None

    base_pc = pokemon.get("base_pc") or 1
    ratio_individuel = pc / base_pc
    ratio_niveau = 0.7 + 0.6 * (niveau - 1) / max(1, niveau_max - 1)

    return max(1, round(stats_base[cle_stat] * ratio_individuel * ratio_niveau))


def obtenir_pokemon_par_nom(nom: str):
    for p in POKEDEX:
        if p["nom"].lower() == nom.lower():
            return p
    return None


def tirer_boss_raid() -> dict:
    """Tire un boss de raid parmi les Pokémon hyper rares et légendaires."""
    candidats = [p for p in POKEDEX if p["rarete"] in ("hyper_rare", "legendaire")]
    if not candidats:
        candidats = POKEDEX  # filet de sécurité si la liste de secours n'a pas ces tiers
    return random.choice(candidats)


# Roster fixe des boss de raid par palier d'étoiles. Les 4★/5★ sont pensés pour
# être changés régulièrement (ex: tous les mois) afin d'apporter de la nouveauté.
ROSTER_RAID = {
    1: ["Rattata", "Roucool", "Chenipan", "Nidoran♂", "Poissirène"],
    2: ["Ponyta", "Mimitoss", "Nosferalto", "Rapasdepic", "Dodrio"],
    3: ["Ronflex", "Léviator", "Ectoplasma", "Alakazam", "Lokhlass"],
    4: ["Dracolosse", "Tyranocif", "Métalosse"],
    5: ["Mewtwo", "Rayquaza", "Lugia"],
}


def tirer_pokemon_par_rarete(rarete: str) -> dict:
    """Tire un Pokémon uniformément au hasard parmi ceux d'une rareté précise (pas pondéré
    par génération/type comme un spawn sauvage) — utilisé pour l'éclosion des œufs."""
    candidats = [p for p in POKEDEX if p["rarete"] == rarete]
    return random.choice(candidats) if candidats else random.choice(POKEDEX)


def tirer_boss_raid_par_etoile(etoiles: int) -> dict:
    """Tire un boss dans le roster fixe correspondant au palier d'étoiles donné.
    Si aucun nom du roster ne correspond exactement à la base actuelle (ex: régénération
    du pokédex avec une légère différence de nom), retombe sur un tirage aléatoire
    dans la bonne rareté pour ne jamais bloquer un raid."""
    import config

    noms_roster = ROSTER_RAID.get(etoiles, [])
    candidats = [obtenir_pokemon_par_nom(nom) for nom in noms_roster]
    candidats = [p for p in candidats if p is not None]

    if candidats:
        return random.choice(candidats)

    # Filet de sécurité : tirage aléatoire dans la rareté correspondante
    rarete = config.RARETE_PAR_ETOILES.get(etoiles, "commun")
    secours = [p for p in POKEDEX if p["rarete"] == rarete]
    return random.choice(secours) if secours else random.choice(POKEDEX)
