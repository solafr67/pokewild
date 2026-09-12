import io
import random
import time

import discord

import capacites as capacites_module
import combat_visuel
import formes_objets as formes_objets_module
import mega_evolutions as mega_evolutions_module
import config
import database
import journal
import leveling
import niveaux_pokemon
import quetes_ui
from pokemon_data import (
    ATTAQUE_DEFAUT_NOM,
    ATTAQUES_CHARGE,
    ATTAQUES_FURIE,
    ATTAQUES_PRIORITE_BASSE_ECHOUE_SI_TOUCHE,
    ATTAQUES_RECHARGE,
    ATTAQUES_TERRAIN,
    ATTAQUES_TERRAIN_ZONE,
    ATTAQUES_ECRANS,
    ATTAQUES_EFFETS_GLOBAUX,
    EMOJI_RARETE,
    EMOJI_TYPES,
    IV_DEFAUT,
    calculer_multiplicateur_type,
    calculer_toutes_stats,
    obtenir_attaque,
    obtenir_pokemon_par_nom,
    pp_max_attaque,
    sprite_pokemon,
)

DUREE_TOUR = 45  # secondes avant qu'un tour se résolve automatiquement
DELAI_SUPPRESSION_FIL = 120  # secondes après la fin du combat avant suppression auto du fil
# Dégâts = vraie formule officielle des jeux Pokémon :
#   ((2×niveau/5 + 2) × puissance × Atq/Déf / 50 + 2) × STAB × types × variance
# Les stats (Atq/Déf/etc.) viennent des IV réels de chaque individu + son niveau actuel —
# plus de PC dans ce calcul, le PC n'est plus qu'un score affiché dérivé de ces stats.

# Lutte : attaque de secours automatique quand toutes les attaques équipées sont à 0 PP
# (comme dans les vrais jeux). Ne consomme pas de PP (infinie), mais inflige un contrecoup.
NOM_LUTTE = "Lutte"
ATTAQUE_LUTTE = {"type": None, "puissance": 50, "precision": None, "classe": "physical", "stats": [], "cible": "adversaire"}
LUTTE_RECOIL_POURCENT = 0.25  # 25% des PV max de l'attaquant en contrecoup

# Altérations de statut : émoji, libellé, et effets
STATUTS_INFO = {
    "burn":      {"emoji": "🔥", "nom": "brûlé"},
    "poison":    {"emoji": "☠️", "nom": "empoisonné"},
    "paralysis": {"emoji": "⚡", "nom": "paralysé"},
    "sleep":     {"emoji": "💤", "nom": "endormi"},
    "freeze":    {"emoji": "❄️", "nom": "gelé"},
    "confusion": {"emoji": "🌀", "nom": "confus"},
}
# Météo de combat : soleil/pluie boostent+affaiblissent Feu/Eau de 50% chacun (le type
# opposé), sable/grêle infligent 1/16 des PV max en dégâts de fin de tour aux types non
# immunisés (Roche/Sol/Acier pour le sable, Glace pour la grêle).
METEO_INFO = {
    "soleil": {"emoji": "☀️", "texte_debut": "Le soleil brille de mille feux !", "texte_fin": "Le soleil retrouve son intensité normale."},
    "pluie":  {"emoji": "🌧️", "texte_debut": "Il commence à pleuvoir !", "texte_fin": "La pluie s'arrête."},
    "sable":  {"emoji": "🌪️", "texte_debut": "Une tempête de sable se lève !", "texte_fin": "La tempête de sable se calme."},
    "grele":  {"emoji": "🌨️", "texte_debut": "Il commence à grêler !", "texte_fin": "La grêle s'arrête."},
}
METEO_TYPES_IMMUNISES = {"sable": {"roche", "sol", "acier"}, "grele": {"glace"}}

# Terrain de zone (Électrique/Herbu/Brumeux/Psychique) — affecte uniquement les Pokémon
# AU SOL (pas Vol, pas Lévitation) : boost +30% sur le type assorti, effets spéciaux
# propres à chacun (voir _est_au_sol / _appliquer_effets_terrain plus bas).
TERRAIN_INFO = {
    "electrique": {"emoji": "⚡", "type_associe": "electrik", "texte_debut": "Un champ électrique recouvre la zone !", "texte_fin": "Le champ électrique se dissipe."},
    "herbu":      {"emoji": "🌿", "type_associe": "plante", "texte_debut": "Un champ herbu recouvre la zone !", "texte_fin": "Le champ herbu se dissipe."},
    "brumeux":    {"emoji": "🌫️", "type_associe": "fee", "texte_debut": "Un champ brumeux recouvre la zone !", "texte_fin": "Le champ brumeux se dissipe."},
    "psychique":  {"emoji": "🔮", "type_associe": "psy", "texte_debut": "Un champ psychique recouvre la zone !", "texte_fin": "Le champ psychique se dissipe."},
}
ATTAQUES_PRIORITE_POSITIVE = {"Vive-Attaque", "Ombre Portée", "Poing Éclair", "Direct Toxik"}
ATTAQUES_SEISME = {"Séisme", "Ampleur"}

# Attaques de zone (2v2 uniquement — en 1v1 elles se comportent normalement, un seul
# adversaire possible de toute façon) : touchent plusieurs cibles à la fois, avec -25%
# de dégâts par cible RÉELLEMENT touchée (comme dans les vrais jeux). Deux catégories
# selon que l'allié du lanceur est touché aussi ou non — voir
# https://www.pokepedia.fr/Capacité_de_zone (les capacités exclusives à Pokémon XD sont
# volontairement absentes, hors-scope).
ATTAQUES_ZONE_AVEC_ALLIE = {
    "Séisme", "Ampleur", "Bang Sonique", "Caboche-Kaboum", "Centrifugifle", "Cradovague",
    "Destruction", "Ébullilave", "Explosion", "Incendie", "Parabocharge", "Piétisol",
    "Surf", "Synchropeine", "Tempête Florale",
}
ATTAQUES_ZONE_ADVERSAIRES = {
    "Abattage", "Aboiement", "Acide", "Blizzard", "Calcination", "Canicule", "Carapiège",
    "Chant Antique", "Coupe-Vent", "Doux Parfum", "Draco-Énergie", "Éboulement",
    "Éclat Magique", "Éclat Spectral", "Écume", "Ère Glaciaire", "Éruption", "Feu Envieux",
    "Force Chtonienne", "Gaz Toxik", "Giclédo", "Lame Pangéenne", "Mégaphone", "Météores",
    "Mimi-Queue", "Mortier Matcha", "Myria-Flèches", "Myria-Vagues", "Ocroupi",
    "Onde Originelle", "Orage Adamantin", "Ouragan", "Overdrive", "Piège de Venin",
    "Pika-Splash", "Poudreuse", "Ruée d'Or", "Rugissement", "Sanction Suprême", "Sécrétion",
    "Séduction", "Spore Coton", "Survinsecte", "Toile Élek", "Toupie Éclat", "Trou Noir",
    "Typhon Fulgurant", "Typhon Hivernal", "Typhon Passionné", "Typhon Pyrosable",
    "Vent Glace", "Vibrécaille", "Voix Enjôleuse",
}
ATTAQUES_ZONE_TOUTES = ATTAQUES_ZONE_AVEC_ALLIE | ATTAQUES_ZONE_ADVERSAIRES

# Écrans/buffs d'équipe (Lot A) — protègent tout le CAMP du lanceur, pas juste lui.
ECRANS_INFO = {
    "reflet": {"emoji": "🛡️", "nom_affiche": "Reflet", "texte_debut": "protège l'équipe des attaques physiques !", "texte_fin": "Le Reflet de l'équipe de {equipe} disparaît."},
    "voile_lumiere": {"emoji": "✨", "nom_affiche": "Mur Lumière", "texte_debut": "protège l'équipe des attaques spéciales !", "texte_fin": "Le Mur Lumière de l'équipe de {equipe} disparaît."},
    "voile_aurore": {"emoji": "🌈", "nom_affiche": "Voile Aurore", "texte_debut": "protège l'équipe de toutes les attaques !", "texte_fin": "Le Voile Aurore de l'équipe de {equipe} disparaît."},
    "vent_arriere": {"emoji": "💨", "nom_affiche": "Vent Arrière", "texte_debut": "double la Vitesse de l'équipe !", "texte_fin": "Le Vent Arrière de l'équipe de {equipe} retombe."},
    "rune_protect": {"emoji": "🔰", "nom_affiche": "Rune Protect", "texte_debut": "protège l'équipe de tout problème de statut !", "texte_fin": "L'effet de Rune Protect de l'équipe de {equipe} se dissipe."},
    "garde_large": {"emoji": "🌐", "nom_affiche": "Garde Large", "texte_debut": "protège l'équipe des attaques de zone ce tour-ci !", "texte_fin": "La Garde Large de l'équipe de {equipe} disparaît."},
    "prevention": {"emoji": "🚧", "nom_affiche": "Prévention", "texte_debut": "protège l'équipe des attaques de statut ce tour-ci !", "texte_fin": "La Prévention de l'équipe de {equipe} disparaît."},
    "tatamigaeshi": {"emoji": "🥋", "nom_affiche": "Tatamigaeshi", "texte_debut": "protège l'équipe des attaques prioritaires ce tour-ci !", "texte_fin": "Le Tatamigaeshi de l'équipe de {equipe} disparaît."},
}

# Effets globaux à durée (Lot C) — plusieurs actifs en même temps possibles.
EFFETS_GLOBAUX_INFO = {
    "trick_room": {"emoji": "🌀", "texte_debut": "Les Pokémon les plus lents agiront en premier !", "texte_fin": "L'espace revient à la normale."},
    "wonder_room": {"emoji": "🔄", "texte_debut": "Défense et Défense Spéciale sont échangées pour tous !", "texte_fin": "Défense et Défense Spéciale reviennent à la normale."},
    "magic_room": {"emoji": "🚫", "texte_debut": "Les effets des objets tenus sont supprimés !", "texte_fin": "Les effets des objets tenus reviennent à la normale."},
    "gravite": {"emoji": "🌍", "texte_debut": "La gravité s'intensifie ! Tout le monde est plaqué au sol.", "texte_fin": "La gravité redevient normale."},
    "verrou_enchante": {"emoji": "🔒", "texte_debut": "Personne ne peut changer de Pokémon pour le prochain tour !", "texte_fin": "Le verrou se relâche, les changements sont de nouveau possibles."},
    "lance_boue": {"emoji": "💧", "texte_debut": "Les attaques Électrik sont affaiblies pour tout le monde !", "texte_fin": "L'effet de Lance-Boue se dissipe."},
}

DEGATS_BRULURE_POURCENT = 0.06   # 6% des PV max par tour
DEGATS_POISON_POURCENT = 0.10    # 10% des PV max par tour
CHANCE_PARALYSIE_SKIP = 0.25     # 25% de ne pas pouvoir agir
CHANCE_DEGEL = 0.20              # 20% de dégeler chaque tour
CHANCE_MUE = 0.30                # Mue : 30% de guérir son propre statut chaque tour
CHANCE_CRITIQUE = 1 / 24         # Taux de critique officiel de base (pas de ratio par attaque pour l'instant)
CHANCE_CONFUSION_SKIP = 0.33     # 33% de se blesser au lieu d'agir
DOLLARS_VICTOIRE = 150
PLAFOND_MISE_DUEL_RATIO = 0.20   # Duels par mise : jamais plus de 20% du solde du plus pauvre des 2


def _est_au_sol(pokemon: dict, capacite: str | None, combat_id: int = None) -> bool:
    """Un Pokémon Vol ou avec Lévitation n'est jamais affecté par le Terrain de zone
    (ni les effets bénéfiques/malus, ni le boost de dégâts assorti) — SAUF sous Gravité,
    qui plaque tout le monde au sol sans exception (si combat_id est fourni)."""
    if combat_id is not None and database.obtenir_effet_global(combat_id, "gravite"):
        return True
    if pokemon and "vol" in pokemon.get("types", []):
        return False
    if capacite == "levitation":
        return False
    return True


def calculer_degats_zone(
    combat_id: int, user_id: int, nom_atk: str, row_atk: dict, attaque: dict, capacite_atk: str,
    adversaire_id: int, nom_def: str, row_def: dict, nb_cibles_reelles: int,
) -> tuple:
    """Calcul de dégâts DÉDIÉ aux attaques de zone en 2v2 (Séisme/Explosion/Surf/etc.,
    voir ATTAQUES_ZONE_TOUTES) — couvre le cœur de la formule (niveau, ATQ/DÉF avec
    boosts, STAB, efficacité de type, coup critique, météo, terrain, brûlure, et le
    -25% par cible réellement touchée) mais PAS les interactions plus exotiques du
    combat normal (objets tenus consommables, Rustique/survie, ripostes au contact) —
    scope volontairement réduit pour ce système, à étendre plus tard si besoin.
    Retourne (degats: int, multi_type: float, est_critique: bool)."""
    pok_atk = formes_objets_module.pokemon_effectif(
        obtenir_pokemon_par_nom(nom_atk), database.obtenir_objet_combat(combat_id, user_id, nom_atk)
    )
    pok_def = formes_objets_module.pokemon_effectif(
        obtenir_pokemon_par_nom(nom_def), database.obtenir_objet_combat(combat_id, adversaire_id, nom_def)
    )
    types_atk = pok_atk["types"] if pok_atk else ["normal"]
    types_def = pok_def["types"] if pok_def else ["normal"]
    capacite_def = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)

    multi_type = calculer_multiplicateur_type([attaque["type"]], types_def)
    if multi_type == 0.0:
        return 0, 0.0, False

    est_special = attaque.get("classe") == "special"
    boosts_atk = database.obtenir_boosts(combat_id, user_id, nom_atk)
    boosts_def = database.obtenir_boosts(combat_id, adversaire_id, nom_def)
    stat_off = row_atk["atq_spe"] if est_special else row_atk["atq"]
    stat_def = row_def["def_spe"] if est_special else row_def["defe"]
    cle_boost_off = "atk_spe" if est_special else "atk"
    cle_boost_def = "def_spe" if est_special else "def"

    est_critique = random.random() < CHANCE_CRITIQUE
    stage_off = max(0, boosts_atk[cle_boost_off]) if est_critique else boosts_atk[cle_boost_off]
    stage_def = min(0, boosts_def[cle_boost_def]) if est_critique else boosts_def[cle_boost_def]
    stat_off_boostee = max(1, stat_off * mult_stage(stage_off))
    stat_def_boostee = max(1, stat_def * mult_stage(stage_def))

    statut_atk = database.obtenir_statut(combat_id, user_id, nom_atk)
    if statut_atk and statut_atk[0] == "burn" and not est_special and capacite_atk != "tenacite":
        stat_off_boostee *= 0.5

    stab = 1.5 if attaque["type"] in types_atk else 1.0
    variance = random.uniform(0.85, 1.0)
    bonus_badge = 1.0

    meteo_active = database.obtenir_meteo(combat_id)
    mult_meteo = 1.0
    if meteo_active:
        if meteo_active["type"] == "soleil":
            mult_meteo = 1.5 if attaque["type"] == "feu" else (0.5 if attaque["type"] == "eau" else 1.0)
        elif meteo_active["type"] == "pluie":
            mult_meteo = 1.5 if attaque["type"] == "eau" else (0.5 if attaque["type"] == "feu" else 1.0)

    mult_terrain = 1.0
    terrain_actif = database.obtenir_terrain_zone(combat_id)
    if terrain_actif and _est_au_sol(pok_atk, capacite_atk, combat_id):
        info_terrain = TERRAIN_INFO[terrain_actif["type"]]
        if attaque["type"] == info_terrain["type_associe"]:
            mult_terrain = 1.3
    if terrain_actif and terrain_actif["type"] == "herbu" and nom_atk in ATTAQUES_SEISME:
        if _est_au_sol(pok_def, capacite_def, combat_id):
            mult_terrain *= 0.5

    mult_zone = 0.75 if nb_cibles_reelles > 1 else 1.0
    mult_critique = 1.5 if est_critique else 1.0
    mult_lance_boue = 0.5 if attaque["type"] == "electrik" and database.obtenir_effet_global(combat_id, "lance_boue") else 1.0

    degats = max(1, round(
        ((2 * row_atk["niveau"] / 5 + 2) * attaque["puissance"] * stat_off_boostee / stat_def_boostee / 50 + 2)
        * multi_type * stab * variance * bonus_badge * mult_meteo * mult_terrain * mult_zone * mult_lance_boue * mult_critique
    ))
    return degats, multi_type, est_critique


def mult_stage(stage: int) -> float:
    """Multiplicateur officiel Pokémon pour un stage de stat (-6..+6)."""
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


XP_VICTOIRE = 80
XP_DEFAITE = 30


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------

def _barre_pv(pv_actuel: int, pv_max: int, longueur: int = 12) -> str:
    """Barre de PV colorée selon l'état : vert > 50%, jaune > 20%, rouge en dessous."""
    ratio = max(0, min(1, pv_actuel / pv_max)) if pv_max else 0
    rempli = round(longueur * ratio)
    if ratio > 0.5:
        bloc = "🟩"
    elif ratio > 0.2:
        bloc = "🟨"
    else:
        bloc = "🟥"
    return bloc * rempli + "⬛" * (longueur - rempli)


def sprite_anime(pokemon: dict) -> str | None:
    """Alias local vers pokemon_data.sprite_pokemon (couvre toutes les générations)."""
    return sprite_pokemon(pokemon)


def _verifier_baie_statut(combat_id: int, user_id: int, pokemon_nom: str, code_statut: str, log: list):
    """À appeler juste après toute application réussie d'un statut (principal via
    database.definir_statut, OU confusion via database.definir_confusion) : si le
    Pokémon qui vient de le recevoir tient une baie qui le guérit (Pêcha/Chéri/Kika...),
    elle se déclenche immédiatement et se consomme — comme dans les vrais jeux."""
    objet = database.obtenir_objet_combat(combat_id, user_id, pokemon_nom)
    info_baie = capacites_module.guerison_statut_objet(objet, code_statut)
    if info_baie:
        if code_statut == "confusion":
            database.retirer_confusion(combat_id, user_id, pokemon_nom)
        else:
            database.retirer_statut(combat_id, user_id, pokemon_nom)
        database.definir_objet_combat(combat_id, user_id, pokemon_nom, None)
        log.append(f"  {info_baie['emoji']} **{pokemon_nom}** guérit aussitôt grâce à sa **{info_baie['nom']}** !")
        # Bajoues (Cheek Pouch, Dedenne) : soigne 33% des PV max EN PLUS, après l'effet
        # de la Baie — v1 : ne couvre que les baies de statut consommées ici, pas
        # d'éventuelles baies de PV consommées à un autre point du code.
        capacite_pour_bajoues = database.obtenir_capacite_combat(combat_id, user_id, pokemon_nom)
        if capacites_module.a_bajoues(capacite_pour_bajoues):
            eq_bajoues = database.obtenir_equipe_pvp(combat_id, user_id)
            row_bajoues = next((r for r in eq_bajoues if r["pokemon_nom"] == pokemon_nom), None)
            if row_bajoues:
                soin_bajoues = max(1, round(row_bajoues["pv_max"] * 0.33))
                database.soigner_pvp(combat_id, user_id, pokemon_nom, soin_bajoues)
                log.append(f"  😋 **{pokemon_nom}** récupère {soin_bajoues} PV en plus grâce à **Bajoues** !")
        # Délestage (Unburden, Goupilou/Roublenard) : +2 Vitesse (approxime le vrai
        # doublement hors-stage des vrais jeux, v1 simplifiée) en consommant son objet.
        if capacites_module.a_delestage(capacite_pour_bajoues):
            nouveau_stage_delestage = database.modifier_boost(combat_id, user_id, pokemon_nom, "vit", 2)
            log.append(f"  🏃 **{pokemon_nom}** s'allège et accélère grâce à **Délestage** ! (stage Vitesse {nouveau_stage_delestage:+d})")


def _bloc_reserve(equipe, actif_nom: str) -> str:
    """Ligne compacte listant la réserve : nom + PV, 💀 pour les K.O."""
    morceaux = []
    for row in equipe:
        if row["pokemon_nom"] == actif_nom:
            continue
        if row["pv_actuels"] <= 0:
            morceaux.append(f"💀 ~~{row['pokemon_nom']}~~")
        else:
            morceaux.append(f"{row['pokemon_nom']} ({row['pv_actuels']})")
    return " • ".join(morceaux) if morceaux else "*Aucune réserve*"


def _texte_efficacite(multi: float) -> str:
    if multi >= 4.0:
        return "🔥🔥 C'est hyper efficace !!"
    if multi >= 2.0:
        return "🔥 C'est super efficace !"
    if multi == 0.0:
        return "🚫 Ça n'a aucun effet..."
    if multi <= 0.25:
        return "❄️❄️ C'est vraiment peu efficace..."
    if multi < 1.0:
        return "❄️ Ce n'est pas très efficace..."
    return ""


# ----------------------------------------------------------------------------
# Initialisation du combat
# ----------------------------------------------------------------------------

def stats_combattant_reel(user_id: int, nom: str) -> dict:
    """Stats de combat complètes {nom, pv, attaque, defense, attaque_spe, defense_spe,
    vitesse} pour UN Pokémon possédé par un vrai joueur — IV de sa meilleure capture de
    cette espèce (si disponibles) + son niveau actuel (croît avec l'XP d'équipe). Repli
    sur un profil neutre (IV 15, niveau 50) si les IV ou les vraies stats de l'espèce ne
    sont pas encore disponibles (avant maj_stats.py / avant cette refonte).

    Si ce Pokémon tient un objet de transformation (Fleur Gracidea, Orbe Griséous...),
    les stats de SA FORME ALTERNATIVE sont utilisées à la place — voir formes_objets.py.
    Le PC affiché au joueur, lui, ne change jamais (uniquement les stats de combat)."""
    pokemon = obtenir_pokemon_par_nom(nom)
    objet_tenu = database.obtenir_objet_tenu_reel(user_id, nom)
    pokemon_pour_calcul = formes_objets_module.pokemon_effectif(pokemon, objet_tenu)
    ivs = database.obtenir_meilleures_ivs(user_id, nom) or IV_DEFAUT
    niveau, _xp = database.obtenir_niveau_pokemon(user_id, nom)
    stats = calculer_toutes_stats(pokemon_pour_calcul, ivs, niveau) if pokemon_pour_calcul else None
    if not stats:
        stats = {"pv": 120, "attaque": 60, "defense": 60, "attaque_spe": 60, "defense_spe": 60, "vitesse": 60}
    return {"nom": nom, "niveau": niveau, **stats}


def preparer_equipe_pour_combat(user_id: int) -> list:
    """Construit la liste de stats complètes pour chaque Pokémon de l'équipe de combat
    d'un joueur, prêtes à être stockées via database.initialiser_equipe_combat_pvp."""
    noms = database.obtenir_equipe_combat_disponible(user_id)
    captures = database.obtenir_pokedex_joueur(user_id)
    especes_possedees = {row["pokemon_nom"] for row in captures}
    return [stats_combattant_reel(user_id, nom) for nom in noms if nom in especes_possedees]


async def demarrer_combat(bot, joueur1: discord.Member, joueur2: discord.Member, channel: discord.TextChannel):
    """Crée le thread privé et envoie UN message unique contenant les embeds du combat
    ET les boutons d'action partagés (chaque joueur ne peut enregistrer que sa propre
    action, vérifié en base au moment du clic)."""
    equipe1 = preparer_equipe_pour_combat(joueur1.id)
    equipe2 = preparer_equipe_pour_combat(joueur2.id)

    if not equipe1 or not equipe2:
        await channel.send("❌ L'un des joueurs n'a pas d'équipe de combat configurée (`/equipe-combat`).")
        return

    await lancer_combat_avec_equipes(bot, joueur1, joueur2, channel, equipe1, equipe2)


class VueRegarderCombat(discord.ui.View):
    """Bouton public permettant à n'importe qui (pas seulement les 2 combattants) de
    rejoindre le fil de combat en spectateur. Le fil est déjà un thread PUBLIC (donc
    techniquement déjà visible/rejoignable manuellement par n'importe qui) — ce bouton
    résout le vrai problème pratique : le retrouver facilement parmi tous les autres
    fils du channel, sans avoir à fouiller la liste des fils actifs. Pas de custom_id
    (pas persistant après un redémarrage) : le combat est de toute façon éphémère, une
    annonce de spectateur qui redevient un bouton mort après un redémarrage n'est pas
    un problème pratique (le fil reste consultable manuellement)."""

    def __init__(self, thread: discord.Thread):
        super().__init__(timeout=None)  # le combat peut durer un moment, pas de timeout
        self.thread = thread

    @discord.ui.button(label="Regarder", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def regarder(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.thread.add_user(interaction.user)
            await interaction.response.send_message(
                f"👁️ Tu as rejoint {self.thread.mention} en spectateur !", ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Impossible de te rejoindre au fil : {e}", ephemeral=True)


class VueRevancheCombat(discord.ui.View):
    """Bouton affiché sur l'annonce de victoire — relance un défi identique entre les
    2 mêmes joueurs. Réutilise demarrer_combat() (pas les anciennes équipes en mémoire)
    pour repartir sur les équipes ACTUELLES des joueurs, au cas où l'un des deux l'aurait
    changée entre-temps. Les 2 joueurs doivent valider avant que le combat ne reparte
    réellement — un seul clic ne suffit pas."""

    def __init__(self, joueur1_id: int, joueur2_id: int):
        super().__init__(timeout=300)  # 5 min pour se décider, le fil du combat précédent va bientôt disparaître
        self.joueur1_id = joueur1_id
        self.joueur2_id = joueur2_id
        self.confirmations = set()
        self.deja_lancee = False

    @discord.ui.button(label="Revanche", emoji="🔄", style=discord.ButtonStyle.primary)
    async def revanche(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.joueur1_id, self.joueur2_id):
            await interaction.response.send_message("Cette revanche ne te concerne pas !", ephemeral=True)
            return
        if self.deja_lancee:
            await interaction.response.send_message("La revanche a déjà été lancée !", ephemeral=True)
            return
        if interaction.user.id in self.confirmations:
            await interaction.response.send_message(
                "Tu as déjà validé — en attente de l'autre joueur.", ephemeral=True
            )
            return

        self.confirmations.add(interaction.user.id)

        if len(self.confirmations) < 2:
            autre_id = self.joueur2_id if interaction.user.id == self.joueur1_id else self.joueur1_id
            await interaction.response.edit_message(
                content=f"✅ {interaction.user.mention} valide la revanche ! En attente de <@{autre_id}>..."
            )
            return

        # Les 2 joueurs ont validé — re-vérifie qu'aucun des deux n'a lancé un autre
        # combat entre-temps (le temps que le 2e valide) avant de réellement relancer.
        if database.combat_en_cours_pour_joueur(self.joueur1_id) or database.combat_en_cours_pour_joueur(self.joueur2_id):
            self.confirmations.discard(interaction.user.id)
            await interaction.response.send_message(
                "❌ L'un des deux joueurs a déjà un combat en cours.", ephemeral=True
            )
            return

        joueur1 = interaction.guild.get_member(self.joueur1_id)
        joueur2 = interaction.guild.get_member(self.joueur2_id)
        if joueur1 is None or joueur2 is None:
            self.confirmations.discard(interaction.user.id)
            await interaction.response.send_message("❌ Un des deux joueurs est introuvable sur le serveur.", ephemeral=True)
            return

        self.deja_lancee = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="⚔️ Les deux joueurs ont validé — la revanche commence !", view=self
        )

        # Le fil du combat précédent va être supprimé sous peu — le nouveau combat part
        # du channel PARENT (celui où /defier avait été utilisé à l'origine), pas du fil.
        channel_parent = interaction.channel.parent if isinstance(interaction.channel, discord.Thread) else interaction.channel
        await demarrer_combat(interaction.client, joueur1, joueur2, channel_parent)

    async def on_timeout(self):
        if self.deja_lancee:
            return
        for item in self.children:
            item.disabled = True
        # Pas de message.edit ici : cette vue n'a pas de référence directe au message
        # (elle est reconstruite/attachée par le code appelant), les boutons désactivés
        # localement suffisent à empêcher tout clic après expiration côté Discord.


async def lancer_combat_avec_equipes(
    bot,
    joueur1: discord.Member,
    joueur2: discord.Member,
    channel: discord.TextChannel,
    equipe1: list,
    equipe2: list,
    avant_lancement=None,
) -> int:
    """Crée le combat (thread + message + boucle de résolution) à partir de deux équipes
    déjà construites (liste de dicts stats complètes) — factorisé pour être réutilisé
    aussi bien par le PvP classique (preparer_equipe_pour_combat) que par le Draft PvP
    (draft_pvp.py, équipes tirées au hasard). `avant_lancement(combat_id)`, si fourni,
    est attendu juste après la création du combat_id mais AVANT que le thread ne soit
    visible aux joueurs — utilisé par le Draft pour équiper les attaques tirées au sort
    avant que quiconque ne puisse cliquer sur Attaquer. Retourne l'ID du combat créé."""
    date_limite = int(time.time()) + DUREE_TOUR
    actif1 = equipe1[0]["nom"]
    actif2 = equipe2[0]["nom"]

    combat_id = database.creer_combat(joueur1.id, joueur2.id, actif1, actif2, date_limite)
    database.initialiser_equipe_combat_pvp(combat_id, joueur1.id, equipe1)
    database.initialiser_equipe_combat_pvp(combat_id, joueur2.id, equipe2)

    if avant_lancement is not None:
        await avant_lancement(combat_id)

    try:
        thread = await channel.create_thread(
            name=f"⚔️ {joueur1.display_name} vs {joueur2.display_name}",
            type=discord.ChannelType.public_thread,  # public : visible et rejoignable par tous pour visionner
        )
        await thread.add_user(joueur1)
        await thread.add_user(joueur2)
    except discord.HTTPException as e:
        await channel.send(f"❌ Impossible de créer le thread : {e}")
        database.terminer_combat_pvp(combat_id)
        return combat_id

    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET thread_id = ? WHERE id = ?", (str(thread.id), combat_id))
    conn.commit()
    conn.close()

    try:
        await channel.send(
            f"⚔️ Un combat vient de commencer entre **{joueur1.display_name}** et "
            f"**{joueur2.display_name}** dans {thread.mention} !",
            view=VueRegarderCombat(thread),
        )
    except discord.HTTPException:
        pass  # purement informatif, ne doit jamais faire échouer le lancement du combat

    noms = {joueur1.id: joueur1.display_name, joueur2.id: joueur2.display_name}
    vue = VueActionCombat(combat_id, 1)

    fichier_scene = _generer_fichier_scene_combat(combat_id, noms)
    try:
        msg = await thread.send(
            content=f"{joueur1.mention} {joueur2.mention} ⚔️ Le combat commence ! Choisissez votre action ci-dessous.",
            view=vue,
            file=fichier_scene if fichier_scene else discord.utils.MISSING,
        )
    except discord.HTTPException as e:
        # Ne doit JAMAIS laisser le fil silencieux — si l'envoi avec image échoue pour une
        # raison quelconque, on retente sans image plutôt que de planter tout le lancement
        # du combat sans aucun message visible (même filet de sécurité que dresseurs.py).
        print(f"⚠️ Échec de l'envoi du message initial du combat {combat_id} avec image ({e}), nouvelle tentative sans image.")
        msg = await thread.send(
            content=f"{joueur1.mention} {joueur2.mention} ⚔️ Le combat commence ! Choisissez votre action ci-dessous.",
            view=vue,
        )

    bot.loop.create_task(boucle_resolution_tour(bot, combat_id, thread.id, msg.id, DUREE_TOUR))
    return combat_id


# ----------------------------------------------------------------------------
# Résolution d'un tour
# ----------------------------------------------------------------------------

def _appliquer_hazards_entree(combat_id: int, user_id: int, pokemon_nom: str, log: list):
    """Applique les pièges de terrain (posés contre le camp de user_id) au Pokémon qui
    vient d'entrer en combat. Comme dans les vrais jeux : Piège de Roc inflige des dégâts
    multipliés par la faiblesse au type roche, Picots cumulent, Pics Toxik empoisonnent."""
    hazards = database.obtenir_hazards(combat_id, user_id)
    if not hazards:
        return

    eq = database.obtenir_equipe_pvp(combat_id, user_id)
    row = next((r for r in eq if r["pokemon_nom"] == pokemon_nom), None)
    if row is None or row["pv_actuels"] <= 0:
        return

    pokemon = formes_objets_module.pokemon_effectif(
        obtenir_pokemon_par_nom(pokemon_nom), database.obtenir_objet_combat(combat_id, user_id, pokemon_nom)
    )
    types_pokemon = pokemon["types"] if pokemon else ["normal"]

    if "stealth_rock" in hazards:
        multi = calculer_multiplicateur_type(["roche"], types_pokemon)
        degats = max(1, round(row["pv_max"] * 0.125 * multi))
        pv = database.appliquer_degats_pvp(combat_id, user_id, pokemon_nom, degats)
        log.append(f"  🪨 **{pokemon_nom}** est blessé par le Piège de Roc ! (-{degats} PV)")
        if pv <= 0:
            log.append(f"  💀 **{pokemon_nom}** est K.O. !")
            return

    if "spikes" in hazards:
        part = {1: 0.08, 2: 0.12, 3: 0.17}.get(hazards["spikes"], 0.08)
        degats = max(1, round(row["pv_max"] * part))
        pv = database.appliquer_degats_pvp(combat_id, user_id, pokemon_nom, degats)
        log.append(f"  📌 **{pokemon_nom}** est blessé par les Picots ! (-{degats} PV)")
        if pv <= 0:
            log.append(f"  💀 **{pokemon_nom}** est K.O. !")
            return

    if "toxic_spikes" in hazards:
        if database.definir_statut(combat_id, user_id, pokemon_nom, "poison"):
            log.append(f"  ☠️ **{pokemon_nom}** est empoisonné par les Pics Toxik !")
            _verifier_baie_statut(combat_id, user_id, pokemon_nom, "poison", log)


def _declencher_talent_entree(combat_id: int, user_id: int, pokemon_nom: str, adversaire_id: int, log: list):
    """Déclenche l'effet d'entrée en jeu du talent (ex: Intimidation) — v1, uniquement sur
    un CHANGEMENT explicite en cours de combat (pas encore sur l'envoi initial du tout
    premier tour, limite connue de cette v1)."""
    eq = database.obtenir_equipe_pvp(combat_id, user_id)
    row = next((r for r in eq if r["pokemon_nom"] == pokemon_nom), None)
    if row is None or row["pv_actuels"] <= 0:
        return
    capacite = database.obtenir_capacite_combat(combat_id, user_id, pokemon_nom)

    # Téléchargement (Download) : cas à part, la stat boostée dépend DYNAMIQUEMENT de la
    # Défense/Défense Spé. de l'ADVERSAIRE au moment de l'envoi — impossible à exprimer
    # avec le simple stat_entree=(stat, delta) fixe utilisé par les autres talents d'entrée.
    if capacite == "telechargement":
        eq_adv = database.obtenir_equipe_pvp(combat_id, adversaire_id)
        combat_actuel = database.obtenir_combat(combat_id)
        nom_actif_adv = combat_actuel["actif1_nom"] if adversaire_id == combat_actuel["joueur1_id"] else combat_actuel["actif2_nom"]
        row_adv = next((r for r in eq_adv if r["pokemon_nom"] == nom_actif_adv), None)
        if row_adv is None or row_adv["pv_actuels"] <= 0:
            return
        stat_choisie = "atk" if row_adv["defe"] < row_adv["def_spe"] else "atk_spe"
        nouveau_stage_dl = database.modifier_boost(combat_id, user_id, pokemon_nom, stat_choisie, 1)
        log.append(
            f"  💾 **{pokemon_nom}** (Téléchargement) : +1 {NOMS_STATS[stat_choisie]} (stage {nouveau_stage_dl:+d})"
        )
        return

    info = capacites_module.infos_capacite(capacite) if capacite else None
    if not info or not info.get("sur_entree"):
        return

    cible_entree = info.get("cible_entree", "soi")
    stat, delta = info.get("stat_entree", (None, 0))
    if not stat:
        return

    if cible_entree == "adversaire":
        eq_adv = database.obtenir_equipe_pvp(combat_id, adversaire_id)
        combat_actuel = database.obtenir_combat(combat_id)
        nom_actif_adv = combat_actuel["actif1_nom"] if adversaire_id == combat_actuel["joueur1_id"] else combat_actuel["actif2_nom"]
        row_adv = next((r for r in eq_adv if r["pokemon_nom"] == nom_actif_adv), None)
        if row_adv is None or row_adv["pv_actuels"] <= 0:
            return
        # Querelleur : immunisé à Intimidation (et effets similaires ciblant l'adversaire).
        capacite_adv = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_actif_adv)
        if capacite == "intimidation" and capacites_module.immunise_contre_intimidation(capacite_adv):
            log.append(f"  🚫 **{nom_actif_adv}** est immunisé grâce à **Querelleur** !")
            return
        nouveau_stage = database.modifier_boost(combat_id, adversaire_id, nom_actif_adv, stat, delta)
        signe = "+" if delta > 0 else ""
        log.append(
            f"  {info['emoji']} **{pokemon_nom}** ({info['nom']}) fait baisser la garde de "
            f"**{nom_actif_adv}** ! ({signe}{delta} {stat.upper()}, stage {nouveau_stage:+d})"
        )
    else:
        nouveau_stage = database.modifier_boost(combat_id, user_id, pokemon_nom, stat, delta)
        signe = "+" if delta > 0 else ""
        log.append(f"  {info['emoji']} **{pokemon_nom}** ({info['nom']}) : {signe}{delta} {stat.upper()} (stage {nouveau_stage:+d})")


def _declencher_meteo_entree(combat_id: int, user_id: int, pokemon_nom: str, log: list):
    """Sécheresse/Averse/Sable Volant/Alerte Neige — même limitation v1 que
    _declencher_talent_entree (uniquement sur un changement explicite en cours de combat)."""
    capacite = database.obtenir_capacite_combat(combat_id, user_id, pokemon_nom)
    meteo = capacites_module.meteo_declenchee_a_entree(capacite) if capacite else None
    if not meteo:
        return
    meteo_actuelle = database.obtenir_meteo(combat_id)
    if meteo_actuelle and meteo_actuelle["type"] == meteo:
        return  # déjà active, rien à refaire
    database.definir_meteo(combat_id, meteo, 5)
    info_capacite = capacites_module.infos_capacite(capacite)
    log.append(f"  {METEO_INFO[meteo]['emoji']} **{pokemon_nom}** ({info_capacite['nom']}) — {METEO_INFO[meteo]['texte_debut']}")


def _declencher_terrain_entree(combat_id: int, user_id: int, pokemon_nom: str, log: list):
    """Électro/Chloro/Aura/Psycho Surge (les 4 Tapu) — même principe que
    _declencher_meteo_entree, pour le terrain de zone plutôt que la météo."""
    capacite = database.obtenir_capacite_combat(combat_id, user_id, pokemon_nom)
    terrain = capacites_module.terrain_declenche_a_entree(capacite) if capacite else None
    if not terrain:
        return
    terrain_actuel = database.obtenir_terrain_zone(combat_id)
    if terrain_actuel and terrain_actuel["type"] == terrain:
        return  # déjà actif, rien à refaire
    database.definir_terrain_zone(combat_id, terrain, 5)
    info_capacite = capacites_module.infos_capacite(capacite)
    log.append(f"  {TERRAIN_INFO[terrain]['emoji']} **{pokemon_nom}** ({info_capacite['nom']}) — {TERRAIN_INFO[terrain]['texte_debut']}")


def _declencher_illusion_entree(combat_id: int, user_id: int, pokemon_nom: str):
    """Illusion (Zoroark) — se déguise en le dernier Pokémon conscient de l'équipe.
    JAMAIS de message de log ici (contrairement aux autres effets d'entrée) : annoncer
    le déguisement dans le journal casserait tout le mystère qu'il est censé créer.
    v1 : même limitation que _declencher_talent_entree — ne se déclenche que sur un
    CHANGEMENT explicite en cours de combat, pas sur l'envoi initial du tout premier
    tour (l'appel initial de mise en place d'équipe ne passe pas par ce même chemin)."""
    capacite = database.obtenir_capacite_combat(combat_id, user_id, pokemon_nom)
    if not capacite or not capacites_module.a_illusion(capacite):
        return
    deguisement = database.dernier_conscient_pour_illusion(combat_id, user_id, pokemon_nom)
    database.definir_illusion(combat_id, user_id, pokemon_nom, deguisement)


def _declencher_supermutation_entree(combat_id: int, user_id: int, pokemon_nom: str, log: list):
    """Supermutation (Zero to Hero, Superdofin) — passe en forme Super, définitivement
    pour le reste du combat. Se déclenche TOUJOURS ici (jamais à l'envoi initial) car
    ce point d'entrée ne se déclenche QUE sur un changement explicite en cours de
    combat (même limitation v1 documentée pour Illusion ci-dessus) — ce qui correspond
    PILE au vrai mécanisme ("change de forme en quittant puis en revenant sur le
    terrain"), sans logique supplémentaire nécessaire."""
    capacite = database.obtenir_capacite_combat(combat_id, user_id, pokemon_nom)
    if not capacite or not capacites_module.a_supermutation(capacite):
        return
    if not database.a_forme_super(combat_id, user_id, pokemon_nom):
        database.activer_forme_super(combat_id, user_id, pokemon_nom)
        log.append(f"  🦸 **{pokemon_nom}** prend sa **Forme Super** grâce à **Supermutation** !")


def _declencher_fouille_entree(combat_id: int, user_id: int, pokemon_nom: str, adversaire_id: int, log: list):
    """Fouille — révèle l'objet tenu de l'adversaire à l'entrée en jeu (même limitation v1)."""
    capacite = database.obtenir_capacite_combat(combat_id, user_id, pokemon_nom)
    if not capacite or not capacites_module.revele_objet_a_entree(capacite):
        return
    combat_actuel = database.obtenir_combat(combat_id)
    nom_actif_adv = combat_actuel["actif1_nom"] if adversaire_id == combat_actuel["joueur1_id"] else combat_actuel["actif2_nom"]
    if not nom_actif_adv:
        return
    objet_adv = database.obtenir_objet_combat(combat_id, adversaire_id, nom_actif_adv)
    info_objet_adv = capacites_module.infos_objet(objet_adv)
    texte_objet = f"**{info_objet_adv['nom']}**" if info_objet_adv else "aucun objet"
    log.append(f"  🔍 **{pokemon_nom}** (Fouille) — **{nom_actif_adv}** tient : {texte_objet}")


def _generer_fichier_scene_combat(combat_id: int, noms: dict, log_tour: list = None, type_combat: str = "dresseur") -> discord.File | None:
    """Génère l'image de la scène de combat (fond + sprites + HUD complet : PV, statut,
    boosts, équipe en Poké Balls, log du tour) pour le tour en cours. Retourne None si un
    souci purement visuel survient (sprite/fond introuvable) — ne doit JAMAIS empêcher
    l'affichage du texte du combat, qui reste la source de vérité en cas d'échec.
    type_combat sélectionne le fond ("dresseur" par défaut, "arene" ou "repaire")."""
    try:
        combat = database.obtenir_combat(combat_id)
        if combat is None:
            return None
        j1, j2 = combat["joueur1_id"], combat["joueur2_id"]
        nom_actif_j1, nom_actif_j2 = combat["actif1_nom"], combat["actif2_nom"]

        def _infos_cote(user_id: int, nom_actif: str):
            equipe = database.obtenir_equipe_pvp(combat_id, user_id)
            row = next((r for r in equipe if r["pokemon_nom"] == nom_actif), None)
            if row is None:
                return None
            objet = database.obtenir_objet_combat(combat_id, user_id, nom_actif)
            pokemon = formes_objets_module.pokemon_effectif(obtenir_pokemon_par_nom(nom_actif), objet)
            pokemon = mega_evolutions_module.pokemon_effectif_mega(pokemon, database.obtenir_mega_actif(combat_id, user_id))
            nom_affiche = formes_objets_module.nom_affichage(nom_actif, objet)
            # Illusion (Zoroark) : substitue le sprite ET le nom affichés par ceux du
            # Pokémon dont il se déguise — TOUJOURS APRÈS les formes à objet ci-dessus
            # (le vrai Zoroark ne porte jamais lui-même de forme alternative), jamais
            # touché la logique de combat elle-même (row/statut/boosts restent ceux du
            # VRAI Zoroark, seuls le sprite et le nom changent).
            deguisement = database.obtenir_illusion(combat_id, user_id, nom_actif)
            if deguisement:
                pokemon_deguise = obtenir_pokemon_par_nom(deguisement)
                if pokemon_deguise:
                    pokemon = pokemon_deguise
                    nom_affiche = deguisement
            statut = database.obtenir_statut(combat_id, user_id, nom_actif)
            code_statut = statut[0] if statut else None
            boosts = database.obtenir_boosts(combat_id, user_id, nom_actif)
            equipe_vivante = [r["pv_actuels"] > 0 for r in equipe]
            return pokemon, nom_affiche, row["niveau"], row["pv_actuels"], row["pv_max"], code_statut, boosts, equipe_vivante

        infos_j1 = _infos_cote(j1, nom_actif_j1)
        infos_j2 = _infos_cote(j2, nom_actif_j2)
        if infos_j1 is None or infos_j2 is None:
            return None

        meteo_active = database.obtenir_meteo(combat_id)
        terrain_actif = database.obtenir_terrain_zone(combat_id)

        log_precedent = database.obtenir_log_precedent(combat_id)
        png_bytes = combat_visuel.generer_image_combat(
            infos_j1[0], infos_j1[1], infos_j1[2], infos_j1[3], infos_j1[4], False, infos_j1[5], infos_j1[6], infos_j1[7],
            infos_j2[0], infos_j2[1], infos_j2[2], infos_j2[3], infos_j2[4], False, infos_j2[5], infos_j2[6], infos_j2[7],
            log_tour=log_tour, noms=noms, tour=combat["tour"],
            meteo_type=meteo_active["type"] if meteo_active else None,
            terrain_type=terrain_actif["type"] if terrain_actif else None,
            log_precedent=log_precedent, tour_precedent=combat["tour"] - 1 if log_precedent else None,
            type_combat=type_combat,
            nom_dresseur_joueur=noms.get(j1) if noms else None,
            nom_dresseur_adversaire=noms.get(j2) if noms else None,
        )
        if log_tour:
            database.definir_log_precedent(combat_id, log_tour)
        if png_bytes is None:
            return None
        return discord.File(io.BytesIO(png_bytes), filename="scene_combat.png")
    except Exception as e:
        print(f"⚠️ Erreur en générant la scène visuelle du combat {combat_id} (le texte s'affiche quand même) : {e}")
        return None


async def resoudre_tour(combat_id: int) -> list:
    """Exécute les actions des deux joueurs et retourne le log du tour.

    Ordre de résolution (comme les vrais jeux) :
    1. Changements de Pokémon (toujours prioritaires)
    2. Potions
    3. Attaques, dans l'ordre de VITESSE (PC modifié par les stages de vitesse) —
       si le premier attaquant met K.O. l'adversaire, la riposte est annulée.
    """
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return []

    # Abri/Protection ne dure qu'UN SEUL tour déclaré — jamais reportée sur le suivant,
    # remise à zéro ici avant que quiconque n'ait encore agi ce tour-ci.
    database.reinitialiser_protections(combat_id)

    j1, j2 = combat["joueur1_id"], combat["joueur2_id"]
    a1 = combat["action1"] or f"attaque:{ATTAQUE_DEFAUT_NOM}"
    a2 = combat["action2"] or f"attaque:{ATTAQUE_DEFAUT_NOM}"

    log = []

    def infos_actif(user_id):
        cbt = database.obtenir_combat(combat_id)
        nom = cbt["actif1_nom"] if user_id == j1 else cbt["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        row = next((r for r in eq if r["pokemon_nom"] == nom), None)
        if row is not None:
            # Stance Change (Exagide) : swap Attaque<->Défense / Attaque Spé<->Défense
            # Spé si en forme Lame — centralisé ICI pour propager automatiquement à
            # TOUS les points qui lisent row_atk/row_def (dégâts, vitesse...), sans
            # avoir à toucher chaque site d'utilisation individuellement.
            capacite_pour_stance = database.obtenir_capacite_combat(combat_id, user_id, nom)
            if capacites_module.a_stance_change(capacite_pour_stance):
                row = capacites_module.stats_echangees_si_lame(row, bool(row["forme_lame"]))
            # Supermutation (Superdofin) : x1.9 uniforme sur toutes les stats de combat
            # en Forme Super — centralisé ici pour la même raison que Stance Change
            # ci-dessus. Copie sûre (jamais de mutation de l'original).
            if capacites_module.a_supermutation(capacite_pour_stance) and database.a_forme_super(combat_id, user_id, nom):
                row = {
                    **row,
                    "atq": round(row["atq"] * 1.9), "defe": round(row["defe"] * 1.9),
                    "atq_spe": round(row["atq_spe"] * 1.9), "def_spe": round(row["def_spe"] * 1.9),
                    "vit": round(row["vit"] * 1.9),
                }
            # Bancosphère (Schooling, Froussardine) : recalculé EN DIRECT (pas
            # persistant, comme Forme Météo) selon le niveau et le % PV actuels.
            if capacites_module.en_forme_ecole(capacite_pour_stance, row["niveau"], row["pv_actuels"], row["pv_max"]):
                row = {
                    **row,
                    "atq": round(row["atq"] * 6), "defe": round(row["defe"] * 6),
                    "atq_spe": round(row["atq_spe"] * 6), "def_spe": round(row["def_spe"] * 6),
                    "vit": round(row["vit"] * 0.75),
                }
        return nom, row

    def mult_stage(stage: int) -> float:
        """Multiplicateur officiel Pokémon pour un stage de stat (-6..+6)."""
        return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)

    def mult_stage_precision(stage: int) -> float:
        """Table de ratio DIFFÉRENTE pour Précision/Esquive (-6..+6) — pas la même
        progression que les 5 stats offensives/défensives."""
        return (3 + stage) / 3 if stage >= 0 else 3 / (3 - stage)

    NOMS_STATS = {"atk": "Attaque", "def": "Défense", "atk_spe": "Attaque Spé", "def_spe": "Défense Spé", "vit": "Vitesse", "precision": "Précision", "esquive": "Esquive"}

    # --- Phase 1 : changements de Pokémon (réinitialisent les boosts du sortant) ---
    for user_id, action in ((j1, a1), (j2, a2)):
        if action.startswith("changer:"):
            ancien_nom, ancien_row = infos_actif(user_id)
            nouveau = action.split(":", 1)[1]
            # Ombre Portée (Shadow Tag, Qulbutoké/Okéoké) : empêche l'ADVERSAIRE de
            # changer volontairement de Pokémon tant qu'il est en vie (un Pokémon K.O.
            # doit quand même être remplacé — passe par un chemin différent, pas ce
            # changement volontaire ici). v1 : bloqué au moment de la résolution plutôt
            # que dans l'interface de choix elle-même (le joueur peut toujours CLIQUER
            # sur changer, mais l'action échoue avec un message explicite).
            adversaire_pour_piege = j2 if user_id == j1 else j1
            nom_adversaire_piege, row_adversaire_piege = infos_actif(adversaire_pour_piege)
            capacite_adversaire_piege = (
                database.obtenir_capacite_combat(combat_id, adversaire_pour_piege, nom_adversaire_piege)
                if row_adversaire_piege else None
            )
            if (
                ancien_row and ancien_row["pv_actuels"] > 0
                and row_adversaire_piege and row_adversaire_piege["pv_actuels"] > 0
                and capacites_module.piege_adversaire(capacite_adversaire_piege)
            ):
                log.append(f"<@{user_id}> ne peut pas changer de Pokémon — **{nom_adversaire_piege}** a **Ombre Portée** !")
                continue
            capacite_sortant = database.obtenir_capacite_combat(combat_id, user_id, ancien_nom)
            if ancien_row and ancien_row["pv_actuels"] > 0:
                # Régénération : soigne un % des PV max en quittant volontairement le combat.
                pourcent_regen = capacites_module.soin_sortie_terrain(capacite_sortant)
                if pourcent_regen:
                    soin_regen = max(1, round(ancien_row["pv_max"] * pourcent_regen))
                    database.soigner_pvp(combat_id, user_id, ancien_nom, soin_regen)
                    log.append(f"  💚 **{ancien_nom}** récupère {soin_regen} PV grâce à **Régénération** en quittant le combat !")
                # Vigilance : guérit son propre statut en quittant volontairement le combat.
                if capacites_module.soigne_statut_a_la_sortie(capacite_sortant) and database.obtenir_statut(combat_id, user_id, ancien_nom):
                    database.retirer_statut(combat_id, user_id, ancien_nom)
                    log.append(f"  🌿 **{ancien_nom}** guérit de son statut grâce à **Vigilance** en quittant le combat !")
            database.reinitialiser_boosts(combat_id, user_id, ancien_nom)
            database.reinitialiser_charge(combat_id, user_id, ancien_nom)
            database.reinitialiser_verrouillage_choix(combat_id, user_id, ancien_nom)
            database.definir_furie(combat_id, user_id, ancien_nom, None)
            database.retirer_requiem(combat_id, user_id, ancien_nom)  # Requiem : échappe au K.O. en changeant
            database.changer_pokemon_actif_pvp(combat_id, user_id, nouveau)
            log.append(f"<@{user_id}> rappelle **{ancien_nom}** et envoie **{nouveau}** !")
            _appliquer_hazards_entree(combat_id, user_id, nouveau, log)
            _declencher_talent_entree(combat_id, user_id, nouveau, j1 if user_id == j2 else j2, log)
            _declencher_meteo_entree(combat_id, user_id, nouveau, log)
            _declencher_terrain_entree(combat_id, user_id, nouveau, log)
            _declencher_fouille_entree(combat_id, user_id, nouveau, j1 if user_id == j2 else j2, log)
            _declencher_illusion_entree(combat_id, user_id, nouveau)
            _declencher_supermutation_entree(combat_id, user_id, nouveau, log)
            # Absentéisme (Truant, Parecool) : prêt à agir dès son premier tour après un
            # envoi (comme dans les vrais jeux).
            database.reinitialiser_absenteisme(combat_id, user_id, nouveau)

    # --- Phase 2 : potions ---
    for user_id, action in ((j1, a1), (j2, a2)):
        if action.startswith("potion:"):
            type_potion = action.split(":", 1)[1]
            nom, row = infos_actif(user_id)
            if row is None:
                continue

            if type_potion == "totalsoin":
                statut_actuel = database.obtenir_statut(combat_id, user_id, nom)
                if statut_actuel:
                    database.retirer_statut(combat_id, user_id, nom)
                    info = STATUTS_INFO.get(statut_actuel[0], {"emoji": "✨", "nom": statut_actuel[0]})
                    log.append(f"<@{user_id}> : **{nom}** utilise 🌿 Total Soin → {info['emoji']} {info['nom']} soigné !")
                else:
                    log.append(f"<@{user_id}> : **{nom}** utilise 🌿 Total Soin, mais n'avait aucun problème de statut.")
                continue

            delta = max(1, round(row["pv_max"] * config.SOIN_POURCENT.get(type_potion, 0.3)))
            pv_apres = database.soigner_pvp(combat_id, user_id, nom, delta)
            log.append(f"<@{user_id}> : **{nom}** est soigné → {pv_apres}/{row['pv_max']} PV")

    # --- Phase 3 : attaques, ordonnées par vitesse ---
    attaquants = []
    for user_id, adversaire_id, action in ((j1, j2, a1), (j2, j1, a2)):
        if not action.startswith("attaque:"):
            continue
        nom, row = infos_actif(user_id)
        if row is None or row["pv_actuels"] <= 0:
            continue
        boosts = database.obtenir_boosts(combat_id, user_id, nom)
        objet_vitesse = database.obtenir_objet_combat(combat_id, user_id, nom)
        capacite_pour_vitesse = database.obtenir_capacite_combat(combat_id, user_id, nom)
        vitesse = row["vit"] * mult_stage(boosts["vit"]) * capacites_module.multiplicateur_stat_objet(objet_vitesse, "vit")
        # Chlorophylle/Nage Rapide : Vitesse doublée sous la bonne météo.
        meteo_pour_vitesse = database.obtenir_meteo(combat_id)
        vitesse *= capacites_module.multiplicateur_vitesse_meteo(
            capacite_pour_vitesse,
            meteo_pour_vitesse["type"] if meteo_pour_vitesse else None,
        )
        # Lenteur (Slow Start) : Vitesse divisée par 2 pendant les 5 premiers tours après l'envoi.
        vitesse *= capacites_module.multiplicateur_debut_lent(capacite_pour_vitesse, row["tours_en_jeu"])["vit"]
        # Vigueur Ancestrale/Turbo Circuit (Paradoxes) : +50% sur la Vitesse si c'est sa
        # stat de base la plus élevée, sous la bonne météo/le bon terrain.
        terrain_pour_vitesse = database.obtenir_terrain_zone(combat_id)
        vitesse *= capacites_module.multiplicateur_stat_dominante(
            capacite_pour_vitesse,
            meteo_pour_vitesse["type"] if meteo_pour_vitesse else None,
            terrain_pour_vitesse["type"] if terrain_pour_vitesse else None,
            row,
            "vit",
        )
        # Vagues Électriques (Surge Surfer, Raichu d'Alola) : double sa Vitesse sous le
        # Terrain Électrique — même fonction que Moteur Hadron (Miraidon), jamais
        # appelée jusqu'ici au calcul de VITESSE (seulement aux dégâts), donc ajoutée
        # ici spécifiquement pour cette capacité.
        vitesse *= capacites_module.multiplicateur_stat_terrain_signature(
            capacite_pour_vitesse, terrain_pour_vitesse["type"] if terrain_pour_vitesse else None, "vit"
        )
        statut_actuel = database.obtenir_statut(combat_id, user_id, nom)
        # Pied Véloce (Quick Feet, Teddiursa) : +50% Vitesse tant qu'il a un problème
        # de statut — réutilise statut_actuel déjà calculé ci-dessus.
        vitesse *= capacites_module.multiplicateur_vitesse_si_statut(capacite_pour_vitesse, statut_actuel is not None)
        if statut_actuel and statut_actuel[0] == "paralysis":
            vitesse /= 2  # la paralysie ralentit

        # Vent Arrière (écran d'équipe) : double la Vitesse de toute l'équipe protégée.
        if database.obtenir_ecran(combat_id, database.equipe_cle_pour_joueur(combat_id, user_id), "vent_arriere"):
            vitesse *= 2

        # Objet Choix : force à répéter la même attaque tant que ce Pokémon reste sur le
        # terrain — remplace silencieusement le choix du joueur par l'attaque déjà
        # verrouillée s'il y en a une (comme les vrais jeux, où le menu ne propose même
        # plus les autres attaques une fois verrouillé).
        nom_attaque_demandee = action.split(":", 1)[1]
        if capacites_module.verrouille_attaque(objet_vitesse):
            attaque_verrouillee = database.obtenir_attaque_verrouillee(combat_id, user_id, nom)
            if attaque_verrouillee and attaque_verrouillee != nom_attaque_demandee:
                nom_attaque_demandee = attaque_verrouillee
            else:
                database.definir_attaque_verrouillee(combat_id, user_id, nom, nom_attaque_demandee)

        # Furie (Colère/Dracocolère) : verrouille sur la MÊME attaque tant que le
        # verrouillage n'est pas expiré, peu importe ce que le joueur a choisi ce tour-ci
        # — le vrai relâchement/la confusion se règlent plus loin, une fois l'attaque
        # effectivement résolue (voir plus bas, après le test de précision).
        etat_furie = database.obtenir_furie(combat_id, user_id, nom)
        if etat_furie:
            nom_attaque_demandee = etat_furie["attaque"]

        # Distorsion (Trick Room) : inverse l'ordre normal des Vitesses (le plus lent
        # agit en premier) — mais ne touche PAS les priorités spéciales ci-dessous
        # (Mitra-Poing, Farceur...), qui dominent toujours grâce à leurs gros décalages.
        if database.obtenir_effet_global(combat_id, "trick_room"):
            vitesse = -vitesse

        # Priorité très basse (Mitra-Poing et consorts) : force ce Pokémon à agir en
        # dernier ce tour-ci, peu importe sa Vitesse réelle — comme la priorité -3 des
        # vrais jeux.
        vitesse_effective = vitesse - 1_000_000 if nom_attaque_demandee in ATTAQUES_PRIORITE_BASSE_ECHOUE_SI_TOUCHE else vitesse
        # Priorité +1 "classique" (Vive-Attaque, Poing Éclair, Ombre Portée, Direct
        # Toxik) — même palier que Farceur juste en dessous, agit systématiquement avant
        # les attaques normales peu importe la Vitesse relative.
        if nom_attaque_demandee in ATTAQUES_PRIORITE_POSITIVE:
            vitesse_effective = vitesse + 1_000_000
        # Farceur : priorité +1 sur les attaques de statut (puissance absente/None).
        if nom_attaque_demandee and nom_attaque_demandee != NOM_LUTTE:
            attaque_pour_priorite = obtenir_attaque(nom_attaque_demandee)
            capacite_pour_priorite = database.obtenir_capacite_combat(combat_id, user_id, nom)
            if (
                attaque_pour_priorite
                and not attaque_pour_priorite.get("puissance")
                and capacites_module.a_priorite_attaques_statut(capacite_pour_priorite)
            ):
                vitesse_effective = vitesse + 1_000_000
            # Mycelium Might (Terracruel) : symétrique de Farceur — SES PROPRES attaques
            # de statut agissent toujours en DERNIER (pénalité modérée, très inférieure
            # à la priorité -3 réelle des attaques comme Mitra-Poing, pour rester "en
            # dernier dans sa tranche de priorité" plutôt que dernier absolu du tour).
            if (
                attaque_pour_priorite
                and not attaque_pour_priorite.get("puissance")
                and capacites_module.a_mycelium_might(capacite_pour_priorite)
            ):
                vitesse_effective = vitesse - 500
        attaquants.append((vitesse_effective + random.random(), user_id, adversaire_id, nom_attaque_demandee))

    attaquants.sort(reverse=True)  # le plus rapide agit en premier
    switches_volontaires = {}  # user_id -> True si Relais (transfère les boosts), False sinon (Change Éclair/Demi-Tour)
    degats_subis_ce_tour = set()  # user_id ayant subi des dégâts d'une attaque adverse ce tour-ci
    flinch_ce_tour = set()  # user_id ayant eu peur (flinch) ce tour-ci — ne peut pas agir si son tour n'est pas encore passé

    for _, user_id, adversaire_id, nom_attaque in attaquants:
        nom_atk, row_atk = infos_actif(user_id)
        nom_def, row_def = infos_actif(adversaire_id)
        if row_atk is None or row_atk["pv_actuels"] <= 0:
            log.append(f"💫 **{nom_atk}** est K.O. et ne peut pas attaquer !")
            continue
        if row_def is None:
            continue

        # Flinch : empêche d'agir CE tour-ci si déclenché par l'adversaire avant que ce
        # Pokémon n'ait eu la chance de jouer (immunisé par Détermination).
        if user_id in flinch_ce_tour:
            log.append(f"😨 **{nom_atk}** a eu peur et n'a pas pu attaquer !")
            continue

        # Absentéisme (Truant, Parecool) : n'agit qu'un tour sur deux — vérifié TRÈS
        # tôt (avant même le statut), puisqu'un tour où il glande ne consomme rien
        # (ni PP, ni déclencheurs d'aucune sorte).
        capacite_atk_pour_absenteisme = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
        if capacites_module.a_absenteisme(capacite_atk_pour_absenteisme):
            if database.bascule_absenteisme(combat_id, user_id, nom_atk):
                log.append(f"😴 **{nom_atk}** glande et ne fait rien à cause de son **Absentéisme** !")
                continue

        # Charme (infatuation) : 50% de chance d'échouer à attaquer tant qu'infatué —
        # statut volatil séparé (voir combat_confusion pour le même principe), jamais
        # levé automatiquement ici (seulement en quittant le terrain, voir plus bas).
        if database.est_infatue(combat_id, user_id, nom_atk):
            if random.random() < 0.5:
                log.append(f"💕 **{nom_atk}** est trop amoureux pour attaquer !")
                continue

        # --- Le statut de l'attaquant peut l'empêcher d'agir ---
        statut_atk = database.obtenir_statut(combat_id, user_id, nom_atk)

        # Mue : 30% de chance de guérir tout seul son statut au début de son tour,
        # avant même de vérifier si ce statut l'empêche d'agir.
        if statut_atk and capacites_module.a_mue(database.obtenir_capacite_combat(combat_id, user_id, nom_atk)):
            if random.random() < CHANCE_MUE:
                info_statut_gueri = STATUTS_INFO[statut_atk[0]]
                database.retirer_statut(combat_id, user_id, nom_atk)
                log.append(f"  🐍 **{nom_atk}** guérit de son statut ({info_statut_gueri['nom']}) grâce à **Mue** !")
                statut_atk = None

        if statut_atk:
            code_statut = statut_atk[0]
            if code_statut == "sleep":
                compteur = database.decrementer_compteur_statut(combat_id, user_id, nom_atk)
                if compteur <= 0:
                    database.retirer_statut(combat_id, user_id, nom_atk)
                    log.append(f"☀️ **{nom_atk}** se réveille !")
                else:
                    log.append(f"💤 **{nom_atk}** dort profondément...")
                    continue
            elif code_statut == "freeze":
                if random.random() < CHANCE_DEGEL:
                    database.retirer_statut(combat_id, user_id, nom_atk)
                    log.append(f"☀️ **{nom_atk}** dégèle !")
                else:
                    log.append(f"❄️ **{nom_atk}** est gelé et ne peut pas bouger !")
                    continue
            elif code_statut == "paralysis" and random.random() < CHANCE_PARALYSIE_SKIP:
                log.append(f"⚡ **{nom_atk}** est paralysé ! Il ne peut pas attaquer !")
                continue

        # Confusion : statut VOLATIL séparé du statut principal ci-dessus (peut coexister
        # avec poison/brûlure/etc. — voir Marionnettiste Toxique, Pêchaminus). Vérifiée
        # indépendamment, que statut_atk soit vide ou non.
        if database.obtenir_confusion(combat_id, user_id, nom_atk) is not None:
            compteur_confusion = database.decrementer_confusion(combat_id, user_id, nom_atk)
            if compteur_confusion <= 0:
                database.retirer_confusion(combat_id, user_id, nom_atk)
                log.append(f"✨ **{nom_atk}** n'est plus confus !")
            elif random.random() < CHANCE_CONFUSION_SKIP:
                degats_confusion = max(1, round(row_atk["pv_max"] * 0.05))
                database.appliquer_degats_pvp(combat_id, user_id, nom_atk, degats_confusion)
                log.append(f"🌀 **{nom_atk}** est confus et se blesse lui-même ! (-{degats_confusion} PV)")
                continue

        # --- Charge / recharge (attaques à deux tours type Lance-Soleil, Ultimaton) ---
        charge_info = database.obtenir_charge(combat_id, user_id, nom_atk)
        if charge_info["doit_recharger"]:
            database.definir_charge(combat_id, user_id, nom_atk, None, False)
            log.append(f"<@{user_id}> : **{nom_atk}** doit récupérer et ne peut pas attaquer ce tour-ci !")
            continue

        liberation_charge = False
        if charge_info["attaque_en_charge"]:
            # Le joueur ne choisit plus rien tant que la charge n'est pas relâchée — comme
            # dans les vrais jeux, l'attaque enregistrée ce tour-ci est ignorée.
            nom_attaque = charge_info["attaque_en_charge"]
            liberation_charge = True
            database.definir_charge(combat_id, user_id, nom_atk, None, False)

        if nom_attaque == NOM_LUTTE:
            attaque = ATTAQUE_LUTTE
        else:
            attaque = obtenir_attaque(nom_attaque)
            # Pixilate (Nymphali) : transforme SES PROPRES attaques Normal en Fée, +30%
            # de puissance — copie locale du dict, JAMAIS de mutation directe (obtenir_
            # attaque renvoie une référence partagée au catalogue ATTAQUES, une écriture
            # directe corromprait cette attaque pour tout le monde, définitivement).
            if attaque.get("type") == "normal" and attaque.get("puissance"):
                capacite_atk_pour_pixilate = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
                if capacites_module.transforme_type_normal(capacite_atk_pour_pixilate):
                    attaque = {**attaque, "type": "fee", "puissance": round(attaque["puissance"] * 1.3)}
            # Force Brute (Sheer Force, Pachyradjah) : +30% de puissance sur une attaque
            # ayant un effet secondaire (ailment ou changement de stat), en échange de
            # SUPPRIMER cet effet secondaire — même principe de copie sûre que Pixilate
            # ci-dessus. En vidant ailment/stats dans la copie, les blocs qui les
            # traitent plus loin ne trouvent naturellement plus rien à appliquer, sans
            # avoir à les toucher un par un.
            if attaque.get("puissance") and (attaque.get("ailment") or attaque.get("stats")):
                capacite_atk_pour_force_brute = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
                if capacites_module.a_force_brute(capacite_atk_pour_force_brute):
                    attaque = {
                        **attaque,
                        "puissance": round(attaque["puissance"] * 1.3),
                        "ailment": None, "ailment_chance": 0, "stats": [],
                    }
            # Attaques basées sur le poids (Nœud Herbe/Balayage/Tacle Lourd/Tacle Feu) :
            # puissance calculée dynamiquement plutôt que fixe dans le catalogue —
            # même principe de copie sûre. Poids toujours lu depuis l'espèce RÉELLE
            # (obtenir_pokemon_par_nom), pas depuis pok_atk/pok_def transformés par une
            # forme à objet/Méga-Évolution (limite v1 : une forme alternative garde le
            # poids de son espèce de base).
            if nom_attaque in capacites_module.ATTAQUES_POIDS_CIBLE or nom_attaque in capacites_module.ATTAQUES_POIDS_RATIO:
                pokemon_reel_atk = obtenir_pokemon_par_nom(nom_atk)
                pokemon_reel_def = obtenir_pokemon_par_nom(nom_def)
                capacite_atk_pour_poids = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
                capacite_def_pour_poids = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
                if nom_attaque in capacites_module.ATTAQUES_POIDS_CIBLE:
                    poids_def_effectif = pokemon_reel_def.get("poids_kg", 0) * capacites_module.multiplicateur_poids_effectif(capacite_def_pour_poids)
                    nouvelle_puissance = capacites_module.puissance_selon_poids_cible(poids_def_effectif)
                else:
                    poids_atk_effectif = pokemon_reel_atk.get("poids_kg", 0) * capacites_module.multiplicateur_poids_effectif(capacite_atk_pour_poids)
                    poids_def_effectif = pokemon_reel_def.get("poids_kg", 0) * capacites_module.multiplicateur_poids_effectif(capacite_def_pour_poids)
                    nouvelle_puissance = capacites_module.puissance_selon_ratio_poids(poids_atk_effectif, poids_def_effectif)
                attaque = {**attaque, "puissance": nouvelle_puissance}
            # Attaques à coups multiples (Furie/Dard-Nuée/Double Pied) : puissance
            # totale multipliée par le nombre de coups tirés — approxime l'effet sans
            # résoudre chaque coup séparément (voir docstring de tire_nombre_coups).
            nombre_coups_multiples = None
            if attaque.get("puissance") and nom_attaque in capacites_module.ATTAQUES_COUPS_MULTIPLES:
                capacite_atk_pour_coups = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
                nombre_coups_multiples = capacites_module.tire_nombre_coups(nom_attaque, capacite_atk_pour_coups)
                if nombre_coups_multiples:
                    attaque = {**attaque, "puissance": attaque["puissance"] * nombre_coups_multiples}
            pp_max = pp_max_attaque(attaque)
            # Pression : le défenseur fait consommer 2 PP au lieu d'1 pour toute attaque
            # utilisée contre lui (y compris les attaques de statut qui ne le ciblent
            # pas forcément, comme dans les vrais jeux — Pression s'applique dès que ce
            # Pokémon est présent face à l'attaquant, pas seulement s'il est visé).
            cout_pp = 2 if capacites_module.defenseur_double_cout_pp(database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)) else 1
            if liberation_charge:
                # Le PP a déjà été consommé au tour de charge — on ne fait que le lire ici.
                pp_restant = database.obtenir_pp(combat_id, user_id, nom_atk, nom_attaque, pp_max)
            else:
                pp_restant = database.consommer_pp(combat_id, user_id, nom_atk, nom_attaque, pp_max, cout_pp)
        emoji_type = EMOJI_TYPES.get(attaque["type"], "⚔️")

        # Stance Change (Exagide) : passe en forme Lame AVANT de résoudre une attaque
        # offensive (pour que CETTE attaque bénéficie déjà des stats échangées, fidèle
        # aux vrais jeux), repasse en forme Bouclier sur Bouclier Royal précisément.
        # Aucune autre attaque de statut ne change la forme.
        capacite_atk_pour_stance = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
        if capacites_module.a_stance_change(capacite_atk_pour_stance):
            changement_forme = False
            if attaque.get("puissance"):
                database.definir_forme_lame(combat_id, user_id, nom_atk, True)
                changement_forme = True
            elif nom_attaque == "Bouclier Royal":
                database.definir_forme_lame(combat_id, user_id, nom_atk, False)
                changement_forme = True
            if changement_forme:
                # row_atk a été fixé AVANT ce changement (ligne ~929, bien plus haut) et
                # reste utilisé pour tout le calcul de dégâts qui suit — sans ce
                # rafraîchissement, CETTE attaque utiliserait encore les stats de
                # l'ANCIENNE forme, ratant la nuance la plus importante de Stance Change.
                _, row_atk = infos_actif(user_id)

        # Corps Maudit (Ectoplasma) : cette attaque précise a été désactivée par
        # l'adversaire il y a peu — échoue immédiatement, comme dans les vrais jeux
        # (où elle serait de toute façon grisée dans le menu de sélection). Le compteur
        # décompte à CHAQUE tour joué par ce Pokémon, peu importe l'attaque choisie —
        # vérifié AVANT décrémentation pour que le dernier tour de blocage compte bien.
        attaque_bloquee = database.obtenir_attaque_desactivee(combat_id, user_id, nom_atk)
        if attaque_bloquee:
            database.decrementer_desactivation(combat_id, user_id, nom_atk)
        if attaque_bloquee == nom_attaque:
            log.append(f"<@{user_id}> : **{nom_atk}** ne peut pas utiliser **{nom_attaque}** — désactivée par **Corps Maudit** !")
            continue

        if nom_attaque in ("Abri", "Protection"):
            database.definir_protection(combat_id, user_id, nom_atk, True)
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** — se protège !")
            continue

        # Or Pur (Good as Gold, Gromago) : immunisé à toute attaque de STATUT adverse —
        # jamais aux attaques offensives (même avec un effet secondaire de statut), et
        # jamais si le lanceur cible SA PROPRE équipe (Dopant/Danse Fleur...).
        if attaque.get("cible") != "soi" and capacites_module.bloque_attaque_statut_adverse(
            database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def), attaque.get("classe")
        ):
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                f"mais **{nom_def}** est immunisé grâce à **Or Pur** !"
            )
            continue

        # Ordre Royal (Queenly Majesty, Sucreine) : bloque toute attaque adverse à
        # priorité positive (liste limitée, voir ATTAQUES_PRIORITE_POSITIVE_CAPACITES).
        if capacites_module.bloque_attaque_prioritaire(
            database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def), nom_attaque
        ):
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                f"mais **{nom_def}** bloque l'attaque grâce à **Ordre Royal** !"
            )
            continue

        # Miroir Magik (Magic Bounce, Sorcilence) : renvoie une attaque de STATUT
        # adverse vers son lanceur au lieu de la subir — applique directement les
        # données de l'attaque (ailment/stats) sur L'ATTAQUANT, plutôt que de tenter un
        # "swap" complet des rôles (plus sûr, évite tout effet de bord sur le reste du
        # tour déjà engagé pour le vrai attaquant, comme le PP déjà consommé).
        if attaque.get("cible") != "soi" and capacites_module.a_miroir_magik(
            database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def), attaque.get("classe")
        ):
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                f"mais **{nom_def}** renvoie l'effet grâce à **Miroir Magik** !"
            )
            ailment_renvoye = attaque.get("ailment")
            if ailment_renvoye and ailment_renvoye in STATUTS_INFO:
                if ailment_renvoye == "confusion":
                    if database.definir_confusion(combat_id, user_id, nom_atk, random.randint(1, 4)):
                        info_conf = STATUTS_INFO["confusion"]
                        log.append(f"  {info_conf['emoji']} **{nom_atk}** est {info_conf['nom']} !")
                else:
                    compteur_renvoye = random.randint(1, 3) if ailment_renvoye == "sleep" else 0
                    if database.definir_statut(combat_id, user_id, nom_atk, ailment_renvoye, compteur_renvoye):
                        info_ail = STATUTS_INFO[ailment_renvoye]
                        log.append(f"  {info_ail['emoji']} **{nom_atk}** est {info_ail['nom']} !")
            for stat_renvoyee, delta_renvoye in attaque.get("stats", []):
                nouveau_stage_renvoye = database.modifier_boost(combat_id, user_id, nom_atk, stat_renvoyee, delta_renvoye)
                signe_renvoye = "+" if delta_renvoye > 0 else ""
                log.append(f"  {signe_renvoye}{delta_renvoye} {NOMS_STATS[stat_renvoyee]} pour **{nom_atk}** (stage {nouveau_stage_renvoye:+d}) !")
            continue

        # Ronfleur (Soundproof, Chuchmur) : immunisé aux attaques sonores reconnues (voir
        # ATTAQUES_SONORES) — vérifié ici, AVANT la séparation offensive/statut plus bas,
        # car les attaques sonores de ce jeu sont un mélange des deux classes.
        if attaque.get("cible") != "soi" and capacites_module.immunise_attaque_sonore(
            database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def), nom_attaque
        ):
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                f"mais **{nom_def}** est immunisé grâce à **Ronfleur** !"
            )
            continue

        if not liberation_charge and nom_attaque in ATTAQUES_CHARGE:
            database.definir_charge(combat_id, user_id, nom_atk, nom_attaque, False)
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** "
                f"— commence à charger son énergie !"
            )
            continue

        if liberation_charge:
            log.append(f"<@{user_id}> : **{nom_atk}** relâche toute son énergie chargée !")

        # Mitra-Poing et consorts (priorité très basse, agit en dernier) : échoue
        # automatiquement si l'utilisateur a subi des dégâts d'une attaque adverse CE
        # TOUR-CI, avant d'avoir eu la chance d'agir — exactement comme dans les vrais jeux.
        if nom_attaque in ATTAQUES_PRIORITE_BASSE_ECHOUE_SI_TOUCHE and user_id in degats_subis_ce_tour:
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                f"mais sa concentration a été brisée par les dégâts subis !"
            )
            continue

        # Champ Psychique : bloque toute attaque à priorité positive ciblant un Pokémon
        # au sol (Vol/Lévitation restent affectables normalement).
        if nom_attaque in ATTAQUES_PRIORITE_POSITIVE:
            terrain_pour_priorite = database.obtenir_terrain_zone(combat_id)
            if terrain_pour_priorite and terrain_pour_priorite["type"] == "psychique":
                pok_def_priorite = formes_objets_module.pokemon_effectif(
                    obtenir_pokemon_par_nom(nom_def), database.obtenir_objet_combat(combat_id, adversaire_id, nom_def)
                )
                capacite_def_priorite = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
                if _est_au_sol(pok_def_priorite, capacite_def_priorite, combat_id):
                    log.append(
                        f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                        f"mais le Champ Psychique protège **{nom_def}** !"
                    )
                    continue
            # Tatamigaeshi (bouclier d'équipe, 1 tour) : bloque toute attaque prioritaire.
            cle_def_tatami = database.equipe_cle_pour_joueur(combat_id, adversaire_id)
            if database.obtenir_ecran(combat_id, cle_def_tatami, "tatamigaeshi"):
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                    f"mais le Tatamigaeshi protège **{nom_def}** !"
                )
                continue

        # Test de précision — combine le stage de Précision de l'attaquant et le stage
        # d'Esquive du défenseur (table de ratio propre à Précision/Esquive, différente
        # des 5 autres stats). Regard Vif ignore l'Esquive du défenseur.
        boosts_atk = database.obtenir_boosts(combat_id, user_id, nom_atk)
        boosts_def = database.obtenir_boosts(combat_id, adversaire_id, nom_def)
        precision = attaque.get("precision")
        if precision is not None:
            capacite_atk_precision = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
            capacite_def_precision = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
            stage_esquive_def = 0 if capacites_module.ignore_esquive_adverse(capacite_atk_precision) else boosts_def["esquive"]
            stage_combine = max(-6, min(6, boosts_atk["precision"] - stage_esquive_def))
            precision_effective = precision * mult_stage_precision(stage_combine)
            precision_effective *= capacites_module.multiplicateur_precision_attaque(capacite_atk_precision)  # Œil Composé
            if attaque.get("classe") == "physical":
                precision_effective *= capacites_module.multiplicateur_precision_physique(capacite_atk_precision)  # Agitation
            # Voile Sable (sous tempête de sable) / Pieds Confus (si confus) — bonus
            # d'esquive additif directement en points de précision, appliqué APRÈS le
            # calcul de stage pour rester simple à lire.
            meteo_pour_esquive = database.obtenir_meteo(combat_id)
            bonus_esquive = capacites_module.bonus_esquive_defenseur(
                capacite_def_precision,
                meteo_pour_esquive["type"] if meteo_pour_esquive else None,
                database.obtenir_confusion(combat_id, adversaire_id, nom_def) is not None,
            )
            precision_effective *= (1 - bonus_esquive)
            # Gravité : x5/3 sur la précision de TOUTES les attaques (offensives comme
            # les autres, tant qu'elles ont un champ "precision" défini).
            if database.obtenir_effet_global(combat_id, "gravite"):
                precision_effective *= 5 / 3
            # Anti-Air (No Guard, Monorpale/Dimoclès) : touche TOUJOURS, que ce soit le
            # porteur qui attaque ou qui soit visé (concerne les deux camps).
            a_anti_air = capacites_module.a_anti_air(capacite_atk_precision) or capacites_module.a_anti_air(capacite_def_precision)
            if not a_anti_air and random.random() * 100 > precision_effective:
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... mais rate !")
                continue

        # Météo (Zénith/Danse Pluie/Tempête de Sable/Grêle) : remplace toujours l'ancienne
        # météo, sauf si c'est déjà exactement la même (échec, comme dans les vrais jeux).
        meteo_declenchee = attaque.get("meteo")
        if meteo_declenchee:
            meteo_actuelle = database.obtenir_meteo(combat_id)
            if meteo_actuelle and meteo_actuelle["type"] == meteo_declenchee:
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... mais ça n'a aucun effet !")
            else:
                database.definir_meteo(combat_id, meteo_declenchee, 5)
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
                log.append(f"  {METEO_INFO[meteo_declenchee]['emoji']} {METEO_INFO[meteo_declenchee]['texte_debut']}")
            continue

        # Terrain de zone (Champ Électrifié/Herbu/Brumeux/Psychique) : même principe que
        # la météo ci-dessus, mais table indépendante (les deux peuvent être actifs
        # simultanément, comme dans les vrais jeux).
        terrain_declenche = ATTAQUES_TERRAIN_ZONE.get(nom_attaque)
        if terrain_declenche:
            terrain_actuel = database.obtenir_terrain_zone(combat_id)
            if terrain_actuel and terrain_actuel["type"] == terrain_declenche:
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... mais ça n'a aucun effet !")
            else:
                database.definir_terrain_zone(combat_id, terrain_declenche, 5)
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
                log.append(f"  {TERRAIN_INFO[terrain_declenche]['emoji']} {TERRAIN_INFO[terrain_declenche]['texte_debut']}")
            continue

        # Écrans d'équipe (Reflet/Mur Lumière/Voile Aurore/Vent Arrière/Rune Protect) —
        # Voile Aurore exige la Grêle active (comme dans les vrais jeux), sinon échoue.
        info_ecran = ATTAQUES_ECRANS.get(nom_attaque)
        if info_ecran:
            type_ecran, duree_ecran = info_ecran
            meteo_pour_voile = database.obtenir_meteo(combat_id)
            if type_ecran == "voile_aurore" and not (meteo_pour_voile and meteo_pour_voile["type"] == "grele"):
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... mais ça n'a aucun effet !")
                continue
            equipe_cle = database.equipe_cle_pour_joueur(combat_id, user_id)
            database.activer_ecran(combat_id, equipe_cle, type_ecran, duree_ecran)
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
            log.append(f"  {ECRANS_INFO[type_ecran]['emoji']} L'équipe de <@{user_id}> {ECRANS_INFO[type_ecran]['texte_debut']}")
            continue

        # Brume : réinitialise tous les stages de stats de tout le combat (soi, allié,
        # adversaires), effet instantané sans durée à suivre.
        if nom_attaque == "Brume":
            database.reinitialiser_boosts_combat(combat_id)
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
            log.append("  🌫️ Tous les changements de stats sont annulés !")
            continue

        # Aromathérapie / Glas de Soin : guérit TOUTE l'équipe du lanceur (pas juste
        # l'actif) — effet instantané, identique pour les deux attaques.
        if nom_attaque in ("Aromathérapie", "Glas de Soin"):
            nb_gueris = database.retirer_tous_statuts_joueur(combat_id, user_id)
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
            if nb_gueris:
                log.append(f"  💚 Toute l'équipe de <@{user_id}> est guérie de ses problèmes de statut !")
            else:
                log.append("  💚 Personne dans l'équipe n'avait de problème de statut.")
            continue

        # Fontaine de Vie : soigne 25% des PV max du lanceur ET de son allié (1v1 : juste
        # le lanceur, il n'y a pas d'allié).
        if nom_attaque == "Fontaine de Vie":
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
            soin_fontaine = max(1, round(row_atk["pv_max"] * 0.25))
            database.soigner_pvp(combat_id, user_id, nom_atk, soin_fontaine)
            log.append(f"  💧 **{nom_atk}** récupère {soin_fontaine} PV !")
            continue

        # Effets globaux à durée (Distorsion/Zone Étrange/Zone Magique/Gravité) — voir
        # EFFETS_GLOBAUX_INFO. Plusieurs peuvent être actifs en même temps.
        info_effet_global = ATTAQUES_EFFETS_GLOBAUX.get(nom_attaque)
        if info_effet_global:
            type_effet, duree_effet = info_effet_global
            if database.obtenir_effet_global(combat_id, type_effet):
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... mais ça n'a aucun effet !")
            else:
                database.activer_effet_global(combat_id, type_effet, duree_effet)
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
                log.append(f"  {EFFETS_GLOBAUX_INFO[type_effet]['emoji']} {EFFETS_GLOBAUX_INFO[type_effet]['texte_debut']}")
            continue

        # Requiem (Chant du Trépas) : affecte TOUS les Pokémon actifs sur le terrain
        # (soi compris), compte à rebours de 3 tours avant K.O. — sauf switch entre-temps.
        if nom_attaque == "Requiem":
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
            log.append("  🎵 Tous les Pokémon sur le terrain ayant entendu la chanson s'affaibliront dans 3 tours !")
            database.definir_requiem(combat_id, user_id, nom_atk, 3)
            combat_pour_requiem = database.obtenir_combat(combat_id)
            autre_id = combat_pour_requiem["joueur2_id"] if user_id == combat_pour_requiem["joueur1_id"] else combat_pour_requiem["joueur1_id"]
            autre_nom = combat_pour_requiem["actif2_nom"] if user_id == combat_pour_requiem["joueur1_id"] else combat_pour_requiem["actif1_nom"]
            if autre_nom:
                database.definir_requiem(combat_id, autre_id, autre_nom, 3)
            continue

        # Garde Florale : +1 Défense pour TOUS les Pokémon Plante actifs sur le terrain
        # (les deux camps), effet instantané sans durée à suivre.
        if nom_attaque == "Garde Florale":
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
            combat_pour_florale = database.obtenir_combat(combat_id)
            nb_boostes = 0
            for uid_florale, nom_florale in ((j1, combat_pour_florale["actif1_nom"]), (j2, combat_pour_florale["actif2_nom"])):
                if not nom_florale:
                    continue
                pok_florale = obtenir_pokemon_par_nom(nom_florale)
                if pok_florale and "plante" in pok_florale.get("types", []):
                    database.modifier_boost(combat_id, uid_florale, nom_florale, "def", 1)
                    nb_boostes += 1
            if nb_boostes:
                log.append(f"  🌸 {nb_boostes} Pokémon Plante sur le terrain voient leur Défense augmenter !")
            else:
                log.append("  🌸 Aucun Pokémon Plante sur le terrain pour en profiter.")
            continue

        if attaque.get("puissance"):
            # Abri/Protection : bloque TOUTE attaque offensive ciblant ce Pokémon ce
            # tour-ci, sauf si l'attaquant a Poing Fantôme (Unseen Fist).
            if database.est_protege(combat_id, adversaire_id, nom_def):
                capacite_atk_protection = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
                if not capacites_module.ignore_protection(capacite_atk_protection):
                    log.append(
                        f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                        f"mais **{nom_def}** se protège avec **Abri** !"
                    )
                    continue
            # --- Attaque offensive ---
            pok_atk = formes_objets_module.pokemon_effectif(
                obtenir_pokemon_par_nom(nom_atk), database.obtenir_objet_combat(combat_id, user_id, nom_atk)
            )
            pok_def = formes_objets_module.pokemon_effectif(
                obtenir_pokemon_par_nom(nom_def), database.obtenir_objet_combat(combat_id, adversaire_id, nom_def)
            )
            types_atk_pokemon = pok_atk["types"] if pok_atk else ["normal"]
            types_def = pok_def["types"] if pok_def else ["normal"]
            # Camouflage (Color Change, Kecleon) : remplace le(s) type(s) normaux par le
            # type camouflé actif, des deux côtés (attaquant ET défenseur) — utile pour
            # le STAB de son côté comme pour l'efficacité de type subie de l'autre.
            camouflage_atk = database.obtenir_camouflage(combat_id, user_id, nom_atk)
            if camouflage_atk:
                types_atk_pokemon = [camouflage_atk]
            camouflage_def = database.obtenir_camouflage(combat_id, adversaire_id, nom_def)
            if camouflage_def:
                types_def = [camouflage_def]
            # Forme Météo (Forecast, Morphéo) : recalculé en DIRECT selon la météo
            # active (jamais persistant, contrairement à Camouflage) — des deux côtés.
            meteo_pour_forme = database.obtenir_meteo(combat_id)
            meteo_type_pour_forme = meteo_pour_forme["type"] if meteo_pour_forme else None
            capacite_atk_pour_forme = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
            type_forme_atk = capacites_module.type_forme_meteo(capacite_atk_pour_forme, meteo_type_pour_forme)
            if type_forme_atk:
                types_atk_pokemon = [type_forme_atk]
            capacite_def_pour_forme = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
            type_forme_def = capacites_module.type_forme_meteo(capacite_def_pour_forme, meteo_type_pour_forme)
            if type_forme_def:
                types_def = [type_forme_def]

            if attaque["type"] is None:
                multi_type, stab = 1.0, 1.0  # Lutte : ni faiblesse/résistance, ni STAB
            else:
                multi_type = calculer_multiplicateur_type([attaque["type"]], types_def)
                stab = 1.5 if attaque["type"] in types_atk_pokemon else 1.0
                # Adaptabilité (Évoli) : le STAB passe de x1.5 à x2.0.
                if stab == 1.5:
                    capacite_atk_pour_adapt = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
                    if capacites_module.a_adaptabilite(capacite_atk_pour_adapt):
                        stab = 2.0

            # Querelleur : les attaques Normal/Combat de l'attaquant touchent les Spectre
            # comme si l'immunité de type n'existait pas (recalcule sans le type Spectre).
            capacite_atk_querelleur = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
            if (
                multi_type == 0.0
                and attaque["type"] in ("normal", "combat")
                and "spectre" in types_def
                and capacites_module.touche_spectre_normal_combat(capacite_atk_querelleur)
            ):
                multi_type = calculer_multiplicateur_type([attaque["type"]], [t for t in types_def if t != "spectre"]) or 1.0

            # Immunité de TALENT (ex: Lévitation contre Sol, Absorb Volt contre Électrik)
            # — prioritaire sur l'immunité de type-chart classique, et peut soigner au
            # lieu de bloquer sèchement (Absorb Volt/Eau).
            capacite_def = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
            # Turboblaze (Reshiram) / Teravolt (Zekrom) : ignore la capacité DÉFENSIVE de
            # l'adversaire pour les 4 vérifications ci-dessous (immunité de type par
            # capacité, Filtre/Prisme Armure, Bouclier de l'Ombre/Carapace Téra) — jamais
            # pour les capacités réactives/de riposte (Justicier...), qui utilisent
            # capacite_def normalement plus loin, pas cette version neutralisée.
            capacite_def_pour_defense = (
                "" if capacites_module.ignore_capacite_defensive(capacite_atk_querelleur) else capacite_def
            )
            # Carapace Téra (Terapagos) : plafonne l'efficacité à "pas très efficace" tant
            # que le défenseur est à pleine vie — remplace multi_type, ne le multiplie pas.
            multi_type = capacites_module.plafonne_efficacite_pleine_vie(
                capacite_def_pour_defense, row_def["pv_actuels"], row_def["pv_max"], multi_type
            )
            info_immunite = capacites_module.immunite_type(capacite_def_pour_defense, attaque["type"]) if attaque["type"] else None
            if info_immunite:
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}**..."
                )
                soin_pourcent = info_immunite.get("immunite_type_soin")
                boost_stat = info_immunite.get("immunite_type_boost_stat")
                if soin_pourcent:
                    soin = max(1, round(row_def["pv_max"] * soin_pourcent))
                    pv_apres_absorb = database.soigner_pvp(combat_id, adversaire_id, nom_def, soin)
                    log.append(
                        f"  {info_immunite['emoji']} **{nom_def}** absorbe l'attaque grâce à "
                        f"**{info_immunite['nom']}** et récupère {soin} PV ! ({pv_apres_absorb}/{row_def['pv_max']} PV)"
                    )
                elif boost_stat:
                    stat, delta = boost_stat
                    nouveau_stage = database.modifier_boost(combat_id, adversaire_id, nom_def, stat, delta)
                    log.append(
                        f"  {info_immunite['emoji']} **{nom_def}** absorbe l'attaque grâce à "
                        f"**{info_immunite['nom']}** — {NOMS_STATS[stat]} {'+' if delta > 0 else ''}{delta} (stage {nouveau_stage:+d}) !"
                    )
                else:
                    log.append(f"  {info_immunite['emoji']} **{nom_def}** est immunisé grâce à **{info_immunite['nom']}** !")
                continue

            # Turbine Éolienne (Wind Rider, Théffroyable) : même principe que l'immunité
            # de type ci-dessus, mais basé sur le NOM de l'attaque plutôt que son type
            # (les attaques "vent" reconnues n'ont pas un type unique commun) — voir
            # ATTAQUES_VENT dans capacites.py pour la liste exacte.
            if capacites_module.immunise_et_boost_si_vent(capacite_def_pour_defense, nom_attaque):
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}**..."
                )
                nouveau_stage_vent = database.modifier_boost(combat_id, adversaire_id, nom_def, "atk", 1)
                log.append(
                    f"  🌬️ **{nom_def}** absorbe l'attaque grâce à **Turbine Éolienne** — "
                    f"Attaque +1 (stage {nouveau_stage_vent:+d}) !"
                )
                continue

            # Fac-similé (Disguise, Mimiqui) : bloque intégralement UN SEUL coup sur
            # toute la durée du combat (1/8 PV max perdu à la place) — vérifié sur
            # capacite_def_pour_defense (Turboblaze/Teravolt le contournent aussi dans
            # les vrais jeux). Jamais si déjà immunisé par le type (rien à "bloquer").
            if (
                attaque["type"] is not None
                and multi_type != 0.0
                and capacites_module.a_facsimile(capacite_def_pour_defense)
                and database.consommer_facsimile(combat_id, adversaire_id, nom_def)
            ):
                degats_facsimile = max(1, row_def["pv_max"] // 8)
                database.appliquer_degats_pvp(combat_id, adversaire_id, nom_def, degats_facsimile)
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}**...\n"
                    f"  🎎 **Fac-similé** absorbe le coup pour **{nom_def}** ! (-{degats_facsimile} PV au lieu des dégâts complets)"
                )
                continue

            # Wonder Guard (Munja) : immunisé à toute attaque qui n'est pas super
            # efficace (multi_type < 2.0) — sauf Lutte, qui touche toujours dans les
            # vrais jeux peu importe le type. Vérifié sur capacite_def_pour_defense
            # (Turboblaze/Teravolt peuvent bien le contourner, comme dans les vrais jeux).
            if attaque["type"] is not None and multi_type < 2.0 and capacites_module.a_wonder_guard(capacite_def_pour_defense):
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}**..."
                )
                log.append(f"  🌟 **{nom_def}** est protégé par **Wonder Guard** — seule une attaque super efficace peut le toucher !")
                continue

            # Immunité totale : aucun dégât (plus jamais de "-1 PV / aucun effet")
            if multi_type == 0.0:
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}**..."
                )
                log.append("  🚫 Ça n'affecte pas " + nom_def + " !")
                continue

            # Stat offensive de l'attaquant / stat défensive du défenseur (physique ou
            # spécial selon la classe de l'attaque), déjà calculées via IV + niveau réels
            # et stockées dans combat_equipe au début du combat.
            est_special = attaque.get("classe") == "special"
            # Zone Étrange (Wonder Room) : la DÉFENSE utilisée est inversée pour tout le
            # monde — une attaque physique tape la Défense Spéciale, et inversement.
            wonder_room_actif = bool(database.obtenir_effet_global(combat_id, "wonder_room"))
            stat_off = row_atk["atq_spe"] if est_special else row_atk["atq"]
            if wonder_room_actif:
                stat_def = row_def["defe"] if est_special else row_def["def_spe"]
            else:
                stat_def = row_def["def_spe"] if est_special else row_def["defe"]

            # La Brûlure divise par deux l'Attaque physique (pas l'Attaque Spéciale) — sauf
            # pour un Pokémon avec Ténacité, qui en est justement immunisé dans les vrais jeux.
            capacite_atk_burn = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
            if not est_special and statut_atk and statut_atk[0] == "burn" and capacite_atk_burn != "tenacite":
                stat_off = max(1, stat_off // 2)

            # Vraie formule officielle des jeux (avec STAB/types/variance en plus, gérés
            # séparément ci-dessous) : ((2×niveau/5 + 2) × puissance × Atq/Déf / 50) + 2.
            variance = random.uniform(0.85, 1.15)
            cle_boost_off = "atk_spe" if est_special else "atk"
            cle_boost_def = ("def" if est_special else "def_spe") if wonder_room_actif else ("def_spe" if est_special else "def")
            objet_atk = database.obtenir_objet_combat(combat_id, user_id, nom_atk)
            mult_stat_choix = capacites_module.multiplicateur_stat_objet(objet_atk, cle_boost_off)

            # Coup critique : ~1/24 de chance (taux officiel de base), immunisé par
            # Carapace/Battle Armor côté défenseur. Un critique ignore les stages
            # DÉFAVORABLES des DEUX côtés — le stage de l'attaquant n'est jamais compté
            # négatif, celui du défenseur jamais compté positif — comme dans les vrais jeux.
            capacite_def_crit = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
            est_critique = (
                not capacites_module.immunise_contre_critiques(capacite_def_crit)
                and random.random() < CHANCE_CRITIQUE
            )
            stage_off_pour_degats = max(0, boosts_atk[cle_boost_off]) if est_critique else boosts_atk[cle_boost_off]
            stage_def_pour_degats = min(0, boosts_def[cle_boost_def]) if est_critique else boosts_def[cle_boost_def]
            # Téméraire (Unaware, Cosmog) : ignore les changements de stats DE L'AUTRE —
            # le défenseur Téméraire ignore les boosts d'Attaque adverse (stage_off remis
            # à 0), l'attaquant Téméraire ignore les boosts de Défense adverse (stage_def
            # remis à 0). Jamais ses propres stages, qui restent inchangés. Récupéré
            # localement ici (capacite_atk n'est définie que PLUS LOIN dans cette
            # fonction à ce stade de l'exécution).
            capacite_atk_pour_temeraire = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
            if capacites_module.ignore_stage_adverse(capacite_def_crit):
                stage_off_pour_degats = 0
            if capacites_module.ignore_stage_adverse(capacite_atk_pour_temeraire):
                stage_def_pour_degats = 0
            stat_def_boostee = max(1, stat_def * mult_stage(stage_def_pour_degats))
            stat_off_boostee = max(1, stat_off * mult_stage(stage_off_pour_degats) * mult_stat_choix)
            # Fléau (Chongjian/Baojian/Dinglu/Yuyu) : -25% sur UNE stat précise de tout le
            # monde SAUF son propre porteur — vérifié depuis la capacité DE L'AUTRE camp,
            # jamais la sienne propre (fidèle à "jamais chez lui-même" dans les vrais jeux).
            capacite_atk_pour_fleau = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
            stat_off_boostee *= capacites_module.multiplicateur_fleau(capacite_def_crit, cle_boost_off)
            stat_def_boostee *= capacites_module.multiplicateur_fleau(capacite_atk_pour_fleau, cle_boost_def)
            # Chochotte (Defeatist, Arkéapti) : Attaque ET Attaque Spéciale divisées par
            # 2 dès 50% PV ou moins — s'applique ici puisque stat_off_boostee EST déjà
            # l'une des deux (physique ou spéciale) selon le type de l'attaque utilisée.
            stat_off_boostee *= capacites_module.multiplicateur_chochotte(capacite_atk_pour_fleau, row_atk["pv_actuels"], row_atk["pv_max"])
            # Pure Puissance (Huge Power, Excavarenne) : double SA PROPRE Attaque
            # physique — jamais l'Attaque Spéciale, vérifié via cle_boost_off.
            if cle_boost_off == "atk" and capacites_module.a_pure_puissance(capacite_atk_pour_fleau):
                stat_off_boostee *= 2.0
            # Tactiques Simiesques (Gorilla Tactics, Darumacho de Galar) : +50%
            # Attaque physique (v1 simplifiée, voir docstring).
            if cle_boost_off == "atk" and capacites_module.a_tactiques_simiesques(capacite_atk_pour_fleau):
                stat_off_boostee *= 1.5
            # Fourrure Renforcée (Fur Coat, Couafarel) : dégâts physiques subis divisés
            # par 2 — vérifié sur la capacité du DÉFENSEUR, jamais les dégâts spéciaux.
            stat_def_boostee /= capacites_module.multiplicateur_fourrure_renforcee(capacite_def_crit, attaque["classe"])
            # Vigueur Ancestrale/Turbo Circuit (Paradoxes) : +30-50% sur SA PROPRE stat de
            # base la plus élevée, sous la bonne météo/le bon terrain — récupérés
            # localement pour éviter tout risque d'utiliser une valeur périmée d'un point
            # antérieur de cette fonction.
            meteo_pour_paradoxe = database.obtenir_meteo(combat_id)
            terrain_pour_paradoxe = database.obtenir_terrain_zone(combat_id)
            meteo_type_paradoxe = meteo_pour_paradoxe["type"] if meteo_pour_paradoxe else None
            terrain_type_paradoxe = terrain_pour_paradoxe["type"] if terrain_pour_paradoxe else None
            stat_off_boostee *= capacites_module.multiplicateur_stat_dominante(
                capacite_atk_pour_fleau, meteo_type_paradoxe, terrain_type_paradoxe, row_atk, cle_boost_off
            )
            stat_def_boostee *= capacites_module.multiplicateur_stat_dominante(
                capacite_def_crit, meteo_type_paradoxe, terrain_type_paradoxe, row_def, cle_boost_def
            )
            # Écailles Magiques (Milobellus) : +50% Défense tant que le DÉFENSEUR a un
            # problème de statut (poison/brûlure/paralysie/sommeil/gel).
            statut_def_pour_ecailles = database.obtenir_statut(combat_id, adversaire_id, nom_def)
            stat_def_boostee *= capacites_module.multiplicateur_defense_si_statut(
                capacite_def_crit, statut_def_pour_ecailles is not None
            )
            # Bonus permanent d'Arène : +X% si l'attaquant a débloqué le badge du type de
            # cette attaque (voir arene.py / config.ARENE_BONUS_DEGATS_PAR_BADGE). Les
            # badges de Repaire de méchants donnent un bonus différent (multiplicateur_boost
            # par catégorie capture/shiny/argent/xp, pas de bonus de dégâts) — voir repaires.py.
            bonus_badge = 1.0
            if user_id > 0 and database.possede_badge_arene(user_id, attaque["type"]):
                bonus_badge += config.ARENE_BONUS_DEGATS_PAR_BADGE

            # Multiplicateurs de talent/objet — attaquant (Cran, Torrent/Brasier..., Orbe
            # Vie) et défenseur (Solide Roc/Filtre, -25% sur un coup super efficace).
            capacite_atk = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
            mult_talent_objet = capacites_module.multiplicateur_degats_infliges(
                capacite_atk, objet_atk, row_atk["pv_actuels"], row_atk["pv_max"], attaque["type"], attaque.get("classe")
            )
            if capacite_atk == "tenacite" and attaque.get("classe") == "physical" and statut_atk:
                mult_talent_objet *= 1.5  # Cran : +50% physique si l'attaquant a un statut
            if capacites_module.boost_attaques_faible_puissance(capacite_atk) and (attaque.get("puissance") or 0) <= 60:
                mult_talent_objet *= 1.5  # Technicien
            if capacites_module.double_pas_tres_efficace(capacite_atk) and multi_type < 1.0:
                mult_talent_objet *= 2.0  # Lentiteintée
            if attaque.get("classe") == "physical":
                # Lenteur (Slow Start) : ne touche QUE l'Attaque physique, jamais l'Attaque
                # Spéciale — fidèle aux vrais jeux.
                mult_talent_objet *= capacites_module.multiplicateur_debut_lent(capacite_atk, row_atk["tours_en_jeu"])["atk"]

            mult_talent_objet *= capacites_module.multiplicateur_degats_subis(capacite_def_pour_defense, multi_type)
            # Bouclier de l'Ombre (Lunala) : -50% dégâts subis tant qu'à pleine vie.
            mult_talent_objet *= capacites_module.multiplicateur_degats_pleine_vie(
                capacite_def_pour_defense, row_def["pv_actuels"], row_def["pv_max"]
            )

            # Météo : Feu/Eau boostés ou affaiblis de 50% sous Soleil/Pluie (l'un renforce
            # son propre type et affaiblit l'opposé).
            mult_meteo = 1.0
            meteo_active = database.obtenir_meteo(combat_id)
            # Air Lock (Rayquaza) — annule l'effet de la météo sur les dégâts, peu importe
            # quel camp le possède (v1 : voir capacites_module.annule_meteo pour la portée
            # exacte, ne couvre pas encore la Vitesse ni les dégâts de fin de tour).
            if capacites_module.annule_meteo(capacite_atk) or capacites_module.annule_meteo(capacite_def):
                meteo_active = None
            if meteo_active:
                if meteo_active["type"] == "soleil":
                    mult_meteo = 1.5 if attaque["type"] == "feu" else (0.5 if attaque["type"] == "eau" else 1.0)
                elif meteo_active["type"] == "pluie":
                    mult_meteo = 1.5 if attaque["type"] == "eau" else (0.5 if attaque["type"] == "feu" else 1.0)
            mult_meteo *= capacites_module.multiplicateur_types_meteo(
                capacite_atk, meteo_active["type"] if meteo_active else None, attaque["type"]
            )  # Force Sable

            # Aura Fée/Aura Sombre : +33% sur les attaques Fée/Ténèbres de N'IMPORTE QUI
            # (les deux capacités sont vérifiées côté attaquant ET défenseur).
            mult_aura = capacites_module.multiplicateur_aura(capacite_atk, capacite_def, attaque["type"])
            mult_aura *= capacites_module.multiplicateur_type_signature(capacite_atk, attaque["type"])  # Transistor/Gueule Draconique
            mult_aura *= capacites_module.boost_attaque_poing(capacite_atk, nom_attaque)  # Poing de Fer
            mult_aura *= capacites_module.boost_attaque_pulse(capacite_atk, nom_attaque)  # Méga Blaster
            # Moelleux (Fluffy, Nounourson/Moumouton/Moumouflon) : dégâts physiques
            # divisés par 2, dégâts Feu doublés — capacité du DÉFENSEUR.
            mult_aura *= capacites_module.multiplicateur_moelleux(capacite_def, attaque["classe"], attaque["type"])
            # Poigne de Fer (Tough Claws, Berserkatt) : +30% sur ses propres attaques
            # au contact.
            mult_aura *= capacites_module.boost_attaque_contact(capacite_atk, attaque["classe"])
            # Mâchoire Brute (Strong Jaw, Voltoutou/Fulgudog) : +50% sur ses propres
            # attaques de morsure reconnues.
            mult_aura *= capacites_module.boost_attaque_morsure(capacite_atk, nom_attaque)

            # Terrain de zone : +30% sur le type assorti, mais UNIQUEMENT si l'attaquant
            # est au sol (Vol/Lévitation ignorent totalement le Terrain).
            mult_terrain = 1.0
            terrain_actif = database.obtenir_terrain_zone(combat_id)
            if terrain_actif and _est_au_sol(pok_atk, capacite_atk, combat_id):
                info_terrain = TERRAIN_INFO[terrain_actif["type"]]
                if attaque["type"] == info_terrain["type_associe"]:
                    mult_terrain = 1.3
            # Champ Herbu : Séisme/Ampleur infligent moitié moins de dégâts à une cible au sol.
            if terrain_actif and terrain_actif["type"] == "herbu" and nom_attaque in ATTAQUES_SEISME:
                if _est_au_sol(pok_def, capacite_def, combat_id):
                    mult_terrain *= 0.5
            # Pulsion Orichalque (Koraidon) / Moteur Hadron (Miraidon) : +33% sur SA
            # propre Attaque (ou Attaque Spéciale) sous la météo/le terrain qu'il a
            # lui-même déclenché à son entrée — s'applique même si un autre effet a
            # entre-temps changé la météo/le terrain, tant que ça correspond encore.
            mult_aura *= capacites_module.multiplicateur_stat_meteo_signature(
                capacite_atk, meteo_active["type"] if meteo_active else None, cle_boost_off
            )
            mult_aura *= capacites_module.multiplicateur_stat_terrain_signature(
                capacite_atk, terrain_actif["type"] if terrain_actif else None, cle_boost_off
            )

            # Écrans d'équipe (Reflet/Mur Lumière/Voile Aurore) : -50% de dégâts subis
            # par l'équipe protégée, mais ignorés en cas de coup critique (comme dans
            # les vrais jeux — un critique perce toujours les écrans).
            mult_ecran = 1.0
            if not est_critique:
                equipe_cle_def = database.equipe_cle_pour_joueur(combat_id, adversaire_id)
                ecrans_def = database.obtenir_tous_ecrans_equipe(combat_id, equipe_cle_def)
                if "voile_aurore" in ecrans_def:
                    mult_ecran = 0.5
                elif not est_special and "reflet" in ecrans_def:
                    mult_ecran = 0.5
                elif est_special and "voile_lumiere" in ecrans_def:
                    mult_ecran = 0.5

            mult_critique = capacites_module.multiplicateur_degats_critique(capacite_atk) if est_critique else 1.0
            # Lance-Boue : -50% sur les attaques Électrik, pour tout le monde (pas
            # spécifique à une équipe, contrairement aux écrans ci-dessus).
            mult_lance_boue = 0.5 if attaque["type"] == "electrik" and database.obtenir_effet_global(combat_id, "lance_boue") else 1.0
            degats = max(1, round(
                ((2 * row_atk["niveau"] / 5 + 2) * attaque["puissance"] * stat_off_boostee / stat_def_boostee / 50 + 2)
                * multi_type * stab * variance * bonus_badge * mult_talent_objet * mult_meteo * mult_aura * mult_terrain * mult_ecran * mult_lance_boue * mult_critique
            ))

            # Ceinture Force (objet à usage unique, se consomme) OU Rustique (aptitude
            # permanente, ne se consomme jamais) : si le défenseur est encore à pleine vie
            # et que ce coup l'aurait achevé, il survit avec 1 PV.
            objet_def = database.obtenir_objet_combat(combat_id, adversaire_id, nom_def)
            info_objet_def = capacites_module.infos_objet(objet_def)
            sturdy_par_objet = bool(info_objet_def and info_objet_def.get("sturdy_like"))
            sturdy_par_talent = capacites_module.talent_declenche_sturdy(capacite_def)
            sturdy_declenche = (
                (sturdy_par_objet or sturdy_par_talent)
                and row_def["pv_actuels"] == row_def["pv_max"]
                and degats >= row_def["pv_actuels"]
            )
            if sturdy_declenche:
                degats = row_def["pv_actuels"] - 1

            pv_restants = database.appliquer_degats_pvp(combat_id, adversaire_id, nom_def, degats)
            degats_subis_ce_tour.add(adversaire_id)
            # Attaques à coups multiples (Furie/Dard-Nuée/Double Pied) : précise le
            # nombre de coups tirés, quelle que soit la variante de message ci-dessus
            # qui vient de s'afficher (critique/type/normal...).
            if nombre_coups_multiples:
                log.append(f"  🔢 Touché **{nombre_coups_multiples}** fois !")

            # Illusion (Zoroark) : révélée dès le premier coup subi, peu importe le
            # dégât ou le K.O. — fidèle aux vrais jeux, où c'est justement en encaissant
            # une attaque que le subterfuge s'effondre.
            deguisement_actif = database.obtenir_illusion(combat_id, adversaire_id, nom_def)
            if deguisement_actif:
                database.definir_illusion(combat_id, adversaire_id, nom_def, None)
                log.append(f"  🎭 Ce n'était qu'une **Illusion** ! **{nom_def}** est en fait révélé !")

            # Peau Dure/Piquant : riposte au contact, inflige un % des PV max de
            # L'ATTAQUANT en retour — même si celui-ci vient de mettre K.O. le
            # défenseur (l'attaque a bien fait contact, peu importe l'issue pour lui).
            pourcent_riposte = capacites_module.riposte_contact(capacite_def, attaque["classe"])
            if pourcent_riposte:
                degats_riposte = max(1, round(row_atk["pv_max"] * pourcent_riposte))
                database.appliquer_degats_pvp(combat_id, user_id, nom_atk, degats_riposte)
                log.append(f"  🦔 **{nom_atk}** est blessé au contact de **{nom_def}** ! (-{degats_riposte} PV)")

            # Momie (Tutafeh/Tutankafer) : au contact, transforme la capacité de
            # L'ATTAQUANT en Momie, qui se propage à son tour à qui la touche ensuite —
            # jamais si l'attaquant a DÉJÀ Momie (rien à changer).
            nouvelle_capacite_momie = capacites_module.change_capacite_au_contact(capacite_def, attaque["classe"])
            if nouvelle_capacite_momie and capacite_atk != nouvelle_capacite_momie:
                database.definir_capacite_combat(combat_id, user_id, nom_atk, nouvelle_capacite_momie)
                log.append(f"  🧟 **{nom_atk}** attrape **Momie** au contact de **{nom_def}** !")

            # Esprit Vagabond (Tutétékri) : au contact, ÉCHANGE sa propre capacité avec
            # celle de l'attaquant (contrairement à Momie, à sens unique).
            if capacites_module.a_esprit_vagabond(capacite_def, attaque["classe"]):
                database.definir_capacite_combat(combat_id, user_id, nom_atk, capacite_def)
                database.definir_capacite_combat(combat_id, adversaire_id, nom_def, capacite_atk)
                log.append(f"  👻 **{nom_def}** échange sa capacité avec **{nom_atk}** grâce à **Esprit Vagabond** !")

            # Charme Ensorceleur (Cute Charm, Rondoudou/Toudoudou/Skitty/Delcatty) : 30%
            # de chance d'infatuer L'ATTAQUANT au contact, si les genres sont opposés —
            # genres SNAPSHOTÉS par combat (voir tire_genre_pour_espece), jamais si K.O.
            if pv_restants > 0:
                genre_def_charme = database.obtenir_genre_combat(combat_id, adversaire_id, nom_def)
                genre_atk_charme = database.obtenir_genre_combat(combat_id, user_id, nom_atk)
                if capacites_module.declenche_charme_ensorceleur(capacite_def, genre_def_charme, genre_atk_charme, attaque["classe"]):
                    database.definir_infatuation(combat_id, user_id, nom_atk, True)
                    log.append(f"  💕 **{nom_atk}** tombe amoureux de **{nom_def}** grâce à **Charme Ensorceleur** !")

                # Pose Spore (Effect Spore, Balignon/Spododo/Lampignon) : au contact,
                # 30% de chance totale d'infliger poison/paralysie/sommeil à
                # L'ATTAQUANT — taux exacts officiels (9%/10%/11%).
                statut_pose_spore = capacites_module.tire_statut_pose_spore(capacite_def, attaque["classe"])
                if statut_pose_spore:
                    compteur_spore = random.randint(1, 3) if statut_pose_spore == "sleep" else 0
                    if database.definir_statut(combat_id, user_id, nom_atk, statut_pose_spore, compteur_spore):
                        info_spore = STATUTS_INFO[statut_pose_spore]
                        log.append(f"  {info_spore['emoji']} **{nom_atk}** est {info_spore['nom']} par **Pose Spore** !")

                # Coloforce (Pickpocket, Sapereau) : au contact, vole l'objet tenu de
                # L'ATTAQUANT (sens inverse de Magicien) — jamais si le défenseur tient
                # déjà quelque chose, jamais si l'attaquant n'a rien à voler, jamais un
                # objet lié à une transformation.
                if (
                    capacites_module.vole_objet_au_contact(capacite_def, attaque["classe"])
                    and not objet_def
                    and objet_atk
                    and objet_atk not in formes_objets_module.FORMES_OBJETS
                ):
                    database.definir_objet_combat(combat_id, adversaire_id, nom_def, objet_atk)
                    database.definir_objet_combat(combat_id, user_id, nom_atk, None)
                    nom_objet_vole_cf = capacites_module.infos_objet(objet_atk)
                    nom_affiche_cf = nom_objet_vole_cf["nom"] if nom_objet_vole_cf else objet_atk
                    log.append(f"  🖐️ **{nom_def}** vole **{nom_affiche_cf}** à **{nom_atk}** grâce à **Coloforce** !")

            # Camouflage (Color Change, Kecleon) : change son propre type pour
            # correspondre à l'attaque qui vient de le toucher — jamais si K.O., jamais
            # sur Lutte (type None), jamais si déjà de ce type précis (rien à changer).
            if pv_restants > 0 and attaque["type"] is not None:
                capacite_def_pour_camouflage = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
                if capacites_module.a_camouflage(capacite_def_pour_camouflage) and attaque["type"] not in types_def:
                    database.definir_camouflage(combat_id, adversaire_id, nom_def, attaque["type"])
                    log.append(f"  🦎 **{nom_def}** devient de type **{attaque['type'].capitalize()}** grâce à **Camouflage** !")

            # Magicien (Hoopa) : vole l'objet tenu de la cible sur TOUT coup réussi (pas
            # seulement un K.O., contrairement à Justicier/Ossature/Hennissement plus bas)
            # — jamais s'il tient déjà quelque chose lui-même, jamais si la cible n'a
            # rien à voler, et jamais un objet lié à une transformation (Plaque, ROM,
            # Orbe...), pour éviter le cas bizarre de rendre normal un Pokémon
            # transformé juste en le touchant.
            if (
                capacites_module.vole_objet_sur_coup(capacite_atk)
                and not objet_atk
                and objet_def
                and objet_def not in formes_objets_module.FORMES_OBJETS
            ):
                database.definir_objet_combat(combat_id, user_id, nom_atk, objet_def)
                database.definir_objet_combat(combat_id, adversaire_id, nom_def, None)
                nom_objet_vole = capacites_module.infos_objet(objet_def)
                nom_affiche_objet = nom_objet_vole["nom"] if nom_objet_vole else objet_def
                log.append(f"  🎩 **{nom_atk}** vole **{nom_affiche_objet}** à **{nom_def}** grâce à **Magicien** !")

            # Dommage Sec (Aftermath, Baudrive/Grodrive) : en étant mis K.O. par une
            # attaque physique, inflige 25% des PV max de L'ATTAQUANT en retour —
            # vérification INDÉPENDANTE du bloc "pv_restants > 0" suivant (ce
            # déclencheur est justement l'exact opposé : seulement SI K.O.).
            if pv_restants <= 0 and capacites_module.declenche_dommage_sec(capacite_def, attaque["classe"]):
                degats_dommage_sec = max(1, round(row_atk["pv_max"] * 0.25))
                database.appliquer_degats_pvp(combat_id, user_id, nom_atk, degats_dommage_sec)
                log.append(f"  💢 **{nom_atk}** subit le contrecoup de **Dommage Sec** ! (-{degats_dommage_sec} PV)")

            # Expuls'Organes (Innards Out, Concombaffe) : en étant mis K.O. (n'importe
            # quelle classe d'attaque, contrairement à Dommage Sec/Peau Dure), inflige à
            # L'ATTAQUANT des dégâts égaux à SES PROPRES PV restants AVANT ce coup fatal
            # (row_def["pv_actuels"] est la valeur PRÉ-dégâts, fixée plus haut par
            # infos_actif avant que ce tour ne soit résolu).
            if pv_restants <= 0 and capacites_module.a_expuls_organes(capacite_def):
                degats_expuls = max(1, row_def["pv_actuels"])
                database.appliquer_degats_pvp(combat_id, user_id, nom_atk, degats_expuls)
                log.append(f"  🫀 **{nom_atk}** subit le contrecoup d'**Expuls'Organes** ! (-{degats_expuls} PV)")

            # Justicier (Cobalium/Terrakium/Viridium) : +1 Attaque quand touché par une
            # attaque Ténèbres — vérifié sur la capacité du DÉFENSEUR, se déclenche même
            # si l'attaque était super efficace/pas très efficace, mais pas si K.O.
            if pv_restants > 0:
                boost_justicier = capacites_module.boost_attaque_si_touche_par_type(capacite_def, attaque["type"])
                if boost_justicier:
                    stat_j, delta_j = boost_justicier
                    nouveau_stage_j = database.modifier_boost(combat_id, adversaire_id, nom_def, stat_j, delta_j)
                    log.append(f"  ⚖️ **{nom_def}** active **Justicier** ! (+{delta_j} {NOMS_STATS[stat_j]}, stage {nouveau_stage_j:+d})")

                # Phobique (Rattled, Mordudor) : +1 Vitesse quand touché par une attaque
                # Ténèbres/Spectre/Insecte.
                if capacites_module.boost_vitesse_phobique(capacite_def, attaque["type"]):
                    nouveau_stage_phobique = database.modifier_boost(combat_id, adversaire_id, nom_def, "vit", 1)
                    log.append(f"  😱 **{nom_def}** active **Phobique** ! (+1 Vitesse, stage {nouveau_stage_phobique:+d})")

                # Armure Fragile (Polthégeist/Corayôme) : -1 Défense, +2 Vitesse quand
                # touché par une attaque PHYSIQUE, peu importe son type.
                if attaque.get("classe") == "physical":
                    boost_armure = capacites_module.boost_si_touche_physique(capacite_def)
                    if boost_armure:
                        (stat_baisse, delta_baisse), (stat_hausse, delta_hausse) = boost_armure
                        database.modifier_boost(combat_id, adversaire_id, nom_def, stat_baisse, delta_baisse)
                        nouveau_stage_v = database.modifier_boost(combat_id, adversaire_id, nom_def, stat_hausse, delta_hausse)
                        log.append(
                            f"  🔨 **{nom_def}** active **Armure Fragile** ! ({delta_baisse} {NOMS_STATS[stat_baisse]}, "
                            f"+{delta_hausse} {NOMS_STATS[stat_hausse]}, stage Vitesse {nouveau_stage_v:+d})"
                        )

                # Ossature (Berserk, Sulfura de Galar) : +1 Attaque Spéciale la première
                # fois que les PV passent sous 50% suite à CE coup précis.
                boost_ossature = capacites_module.declenche_ossature(
                    capacite_def, row_def["pv_actuels"], pv_restants, row_def["pv_max"]
                )
                if boost_ossature:
                    stat_o, delta_o = boost_ossature
                    nouveau_stage_o = database.modifier_boost(combat_id, adversaire_id, nom_def, stat_o, delta_o)
                    log.append(f"  💢 **{nom_def}** active **Ossature** ! (+{delta_o} {NOMS_STATS[stat_o]}, stage {nouveau_stage_o:+d})")

                # Porte de Secours (Sarmuraï) : se retire automatiquement du combat la
                # première fois que ses PV passent sous 50% — réutilise EXACTEMENT le
                # même mécanisme "switches_volontaires" que Change Éclair/Demi-Tour pour
                # que la boucle de fin de tour gère l'envoi du remplaçant. relais=False
                # (comme Change Éclair, pas Relais/Baton Pass) : aucun transfert de boosts.
                if capacites_module.declenche_porte_secours(capacite_def, row_def["pv_actuels"], pv_restants, row_def["pv_max"]):
                    switches_volontaires[adversaire_id] = (False, nom_def)
                    log.append(f"  🚪 **{nom_def}** se retire du combat grâce à **Porte de Secours** !")

                # Corps Maudit (Ectoplasma) : 30% de chance de désactiver l'attaque de
                # L'ATTAQUANT qui vient de toucher — vérifié sur la capacité du
                # DÉFENSEUR, jamais si K.O. (désactiver l'attaque d'un Pokémon qui
                # vient d'en mettre K.O. un autre n'a pas de sens).
                if pv_restants > 0:
                    chance_maudit = capacites_module.chance_corps_maudit(capacite_def)
                    if chance_maudit and random.random() < chance_maudit:
                        database.definir_attaque_desactivee(combat_id, user_id, nom_atk, nom_attaque, 4)
                        log.append(f"  👻 **{nom_attaque}** de **{nom_atk}** est désactivée par **Corps Maudit** !")

                    # Chloro Semence (Seed Sower, Arboliva) : déclenche le Terrain Herbu
                    # quand touché par une attaque offensive — réutilise TELLE QUELLE la
                    # même fonction que les 4 Tapu, juste appelée ici (réactif) plutôt
                    # qu'à l'entrée en jeu.
                    _declencher_terrain_entree(combat_id, adversaire_id, nom_def, log)

                # Chaîne Toxique (Félicanis/Fortusimia/Favianos) : chance d'empoisonner la
                # cible sur une attaque OFFENSIVE (jamais une attaque de statut, jamais si
                # déjà sous un autre statut). Vérifié sur la capacité de L'ATTAQUANT.
                if attaque.get("classe") in ("physical", "special"):
                    chance_toxique = capacites_module.chance_poison_chaine_toxique(capacite_atk)
                    if chance_toxique and random.random() < chance_toxique:
                        if database.definir_statut(combat_id, adversaire_id, nom_def, "poison"):
                            log.append(f"  ⛓️ **{nom_def}** est empoisonné par **Chaîne Toxique** !")
            else:
                # Hennissement Glacé (Blizzeval) / Hennissement Sépulcral (Spectreval) :
                # +1 sur une stat propre quand CE Pokémon inflige lui-même le K.O. —
                # vérifié sur la capacité de L'ATTAQUANT cette fois (pas du défenseur),
                # jamais s'il ne s'agit que d'un statut (poison/brûlure) qui achève plus
                # tard, seulement sur le coup direct qui inflige le K.O.
                boost_hennissement = capacites_module.boost_si_ko_inflige(capacite_atk)
                if boost_hennissement:
                    stat_h, delta_h = boost_hennissement
                    nouveau_stage_h = database.modifier_boost(combat_id, user_id, nom_atk, stat_h, delta_h)
                    log.append(f"  🐴 **{nom_atk}** active son Hennissement ! (+{delta_h} {NOMS_STATS[stat_h]}, stage {nouveau_stage_h:+d})")

                # Cœur d'Âme (Magearna) : +1 sur une stat propre à CHAQUE K.O., peu importe
                # qui l'inflige — contrairement à Hennissement Glacé/Sépulcral ci-dessus qui
                # exige que ce soit CE Pokémon l'auteur du coup. En 1v1, le seul témoin
                # possible est justement l'attaquant (le seul autre Pokémon présent).
                boost_coeur_ame = capacites_module.boost_si_ko_temoin(capacite_atk)
                if boost_coeur_ame:
                    stat_c, delta_c = boost_coeur_ame
                    nouveau_stage_c = database.modifier_boost(combat_id, user_id, nom_atk, stat_c, delta_c)
                    log.append(f"  💗 **{nom_atk}** active **Cœur d'Âme** ! (+{delta_c} {NOMS_STATS[stat_c]}, stage {nouveau_stage_c:+d})")

            # Une attaque de type Feu dégèle instantanément la cible, en plus du jet de
            # 20%/tour classique — comme dans les vrais jeux.
            if attaque["type"] == "feu" and pv_restants > 0:
                statut_def_avant = database.obtenir_statut(combat_id, adversaire_id, nom_def)
                if statut_def_avant and statut_def_avant[0] == "freeze":
                    database.retirer_statut(combat_id, adversaire_id, nom_def)
                    log.append(f"  🔥 **{nom_def}** dégèle sous l'effet de la chaleur !")

            pp_txt = "" if nom_attaque == NOM_LUTTE else f" ({pp_restant}/{pp_max} PP)"
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}** → -{degats} PV{pp_txt}"
            )
            if sturdy_declenche and sturdy_par_objet:
                database.definir_objet_combat(combat_id, adversaire_id, nom_def, None)
                log.append(f"  🥊 **{nom_def}** s'accroche grâce à sa **{info_objet_def['nom']}** et survit avec 1 PV !")
            elif sturdy_declenche:
                log.append(f"  🥊 **{nom_def}** s'accroche grâce à **Rustique** et survit avec 1 PV !")
            if est_critique:
                log.append("  💥 Coup critique !")
            efficacite = _texte_efficacite(multi_type)
            if efficacite:
                log.append(f"  {efficacite}")
            if pv_restants <= 0:
                log.append(f"  💀 **{nom_def}** est K.O. !")
                # Boost Chimère : +1 à la stat la plus élevée de l'attaquant après un K.O.
                if capacites_module.boost_apres_ko(capacite_atk):
                    cles_stats = {"atk": row_atk["atq"], "def": row_atk["defe"], "atk_spe": row_atk["atq_spe"], "def_spe": row_atk["def_spe"], "vit": row_atk["vit"]}
                    meilleure_stat = max(cles_stats, key=cles_stats.get)
                    nouveau_stage_bc = database.modifier_boost(combat_id, user_id, nom_atk, meilleure_stat, 1)
                    log.append(f"  👽 **{nom_atk}** gagne en puissance grâce à **Boost Chimère** ! (+1 {NOMS_STATS[meilleure_stat]}, stage {nouveau_stage_bc:+d})")

            # Flinch : ne se déclenche que si la cible n'a pas encore joué ce tour-ci —
            # inutile si elle est plus rapide et a déjà agi, ou si elle est déjà K.O.
            flinch_chance_attaque = attaque.get("flinch_chance")
            if flinch_chance_attaque and pv_restants > 0 and adversaire_id not in flinch_ce_tour:
                capacite_def_flinch = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
                if not capacites_module.immunise_contre_flinch(capacite_def_flinch) and random.random() * 100 < flinch_chance_attaque:
                    flinch_ce_tour.add(adversaire_id)

            # Riposte au contact (Peau Dure, Statik, Corps Ardent...) — approximation :
            # toute attaque de classe "physical" est considérée comme un contact.
            if pv_restants > 0 and attaque.get("classe") == "physical":
                info_capacite_def = capacites_module.infos_capacite(capacite_def)
                if info_capacite_def and info_capacite_def.get("contact_riposte"):
                    if "riposte_pourcent" in info_capacite_def:
                        recul_contact = max(1, round(row_atk["pv_max"] * info_capacite_def["riposte_pourcent"]))
                        pv_apres_contact = database.appliquer_degats_pvp(combat_id, user_id, nom_atk, recul_contact)
                        log.append(
                            f"  {info_capacite_def['emoji']} **{nom_atk}** est blessé au contact par "
                            f"**{info_capacite_def['nom']}** de **{nom_def}** ! (-{recul_contact} PV)"
                        )
                        if pv_apres_contact <= 0:
                            log.append(f"  💀 **{nom_atk}** est K.O. !")
                    elif "riposte_statut" in info_capacite_def:
                        if random.random() < info_capacite_def.get("riposte_chance", 0.3):
                            statut_riposte = info_capacite_def["riposte_statut"]
                            if not capacites_module.bloque_statut(capacite_atk, statut_riposte):
                                if database.definir_statut(combat_id, user_id, nom_atk, statut_riposte):
                                    info_statut = STATUTS_INFO[statut_riposte]
                                    log.append(
                                        f"  {info_capacite_def['emoji']} **{nom_atk}** est {info_statut['nom']} au "
                                        f"contact de **{info_capacite_def['nom']}** !"
                                    )
                                    _verifier_baie_statut(combat_id, user_id, nom_atk, statut_riposte, log)

            # Recul/absorption propre à l'ATTAQUE elle-même (Explosion, Cogne-Griffe,
            # Wild Charge... = recul négatif ; Giga Sangsue, Draco-Souffle-vamp... =
            # absorption positive) — distinct du recul de l'Orbe Vie ci-dessus (qui est un
            # effet d'OBJET, toujours 10% des PV MAX). Ici c'est un pourcentage des DÉGÂTS
            # INFLIGÉS à la cible, comme dans les vrais jeux — ex: Explosion inflige 100%
            # des dégâts causés en recul à soi-même, donc s'auto-inflige un coup fatal la
            # plupart du temps sans que ce soit un KO totalement garanti à 1 PV près.
            recul_attaque = attaque.get("recul") or 0
            if recul_attaque > 0:  # absorption : l'attaquant se soigne d'un % des dégâts infligés
                soin_absorption = max(1, round(degats * recul_attaque / 100))
                database.soigner_pvp(combat_id, user_id, nom_atk, soin_absorption)
                log.append(f"  🩸 **{nom_atk}** récupère {soin_absorption} PV en absorbant les dégâts infligés !")
            elif recul_attaque < 0:  # recul : l'attaquant se blesse d'un % des dégâts infligés
                if capacites_module.immunise_contre_recul(capacite_atk):
                    log.append(f"  🗿 **{nom_atk}** est protégé du contrecoup grâce à **Tête de Roc** !")
                else:
                    recul_montant = max(1, round(degats * abs(recul_attaque) / 100))
                    pv_apres_recul_attaque = database.appliquer_degats_pvp(combat_id, user_id, nom_atk, recul_montant)
                    log.append(f"  💥 **{nom_atk}** subit le contrecoup de son attaque ! (-{recul_montant} PV)")
                    if pv_apres_recul_attaque <= 0:
                        log.append(f"  💀 **{nom_atk}** est K.O. !")

            # Orbe Vie : recul de 10% des PV max de l'attaquant après chaque attaque
            # offensive réussie (indépendant de l'issue du coup).
            info_objet_atk = capacites_module.infos_objet(objet_atk)
            if info_objet_atk and "recul_pourcent" in info_objet_atk:
                recul_objet = max(1, round(row_atk["pv_max"] * info_objet_atk["recul_pourcent"]))
                pv_apres_recul = database.appliquer_degats_pvp(combat_id, user_id, nom_atk, recul_objet)
                log.append(f"  🔮 **{nom_atk}** est affaibli par son **{info_objet_atk['nom']}** ! (-{recul_objet} PV)")
                if pv_apres_recul <= 0:
                    log.append(f"  💀 **{nom_atk}** est K.O. !")

            # Baie du défenseur : soin/guérison de statut à usage unique, déclenchée sous
            # un certain seuil de PV — se consomme une fois utilisée. Tension (côté
            # attaquant) l'en empêche totalement.
            if pv_restants > 0 and not capacites_module.empeche_baie_adverse(capacite_atk):
                objet_def_actuel = database.obtenir_objet_combat(combat_id, adversaire_id, nom_def)
                info_baie = capacites_module.infos_objet(objet_def_actuel)
                # Gourmandise : le seuil de déclenchement est doublé (25% -> 50% par ex.)
                seuil_baie = (info_baie or {}).get("guerison_pv_seuil", 0) * capacites_module.multiplicateur_seuil_baie(
                    database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
                )
                if info_baie and "guerison_pv_seuil" in info_baie and pv_restants / row_def["pv_max"] <= seuil_baie:
                    soin_baie = max(1, round(row_def["pv_max"] * info_baie["guerison_pv_pourcent"]))
                    pv_apres_baie = database.soigner_pvp(combat_id, adversaire_id, nom_def, soin_baie)
                    database.definir_objet_combat(combat_id, adversaire_id, nom_def, None)
                    log.append(f"  {info_baie['emoji']} **{nom_def}** grignote sa **{info_baie['nom']}** et récupère {soin_baie} PV !")

            # Tour de récupération pour les attaques à RECHARGE (ex: Ultimaton, Ultralaser)
            # — distinct des attaques à CHARGE gérées plus haut (qui chargent AVANT de
            # frapper). S'applique TOUJOURS après usage, même si le coup met K.O. la
            # cible (contrairement à ce qu'un correctif précédent supposait à tort).
            if nom_attaque in ATTAQUES_RECHARGE:
                database.definir_charge(combat_id, user_id, nom_atk, None, True)
                log.append(f"  😵‍💫 **{nom_atk}** doit maintenant récupérer !")

            # Furie (Colère/Dracocolère) : verrouille sur cette attaque 2-3 tours au
            # premier usage, puis confusion automatique une fois le verrouillage épuisé.
            if nom_attaque in ATTAQUES_FURIE:
                etat_furie = database.obtenir_furie(combat_id, user_id, nom_atk)
                if etat_furie is None:
                    database.definir_furie(combat_id, user_id, nom_atk, nom_attaque, random.randint(2, 3))
                else:
                    tours_restants = etat_furie["tours_restants"] - 1
                    if tours_restants <= 0:
                        database.definir_furie(combat_id, user_id, nom_atk, None)
                        deja_confus = database.obtenir_confusion(combat_id, user_id, nom_atk)
                        if deja_confus is None:
                            if database.definir_confusion(combat_id, user_id, nom_atk, random.randint(1, 4)):
                                log.append(f"  😵 **{nom_atk}** se laisse emporter par sa furie et devient confus !")
                            else:
                                log.append(f"  😵 **{nom_atk}** se laisse emporter par sa furie, mais reste immunisé à la confusion !")
                        else:
                            log.append(f"  😵 **{nom_atk}** se laisse emporter par sa furie et devient confus !")
                    else:
                        database.definir_furie(combat_id, user_id, nom_atk, nom_attaque, tours_restants)

            if nom_attaque == NOM_LUTTE:
                recoil = max(1, round(row_atk["pv_max"] * LUTTE_RECOIL_POURCENT))
                pv_apres_recoil = database.appliquer_degats_pvp(combat_id, user_id, nom_atk, recoil)
                log.append(f"  💥 **{nom_atk}** subit le contrecoup de Lutte ! (-{recoil} PV)")
                if pv_apres_recoil <= 0:
                    log.append(f"  💀 **{nom_atk}** est K.O. par le contrecoup !")

            # Altération de statut éventuelle (ex: Flammèche 10% de brûler) — Écran Poudre
            # (côté défenseur) bloque tous les effets secondaires subis, pas les dégâts.
            ailment = attaque.get("ailment")
            if ailment in STATUTS_INFO and pv_restants > 0 and not capacites_module.bloque_effets_secondaires_subis(capacite_def):
                chance = attaque.get("ailment_chance", 0) or 100  # 0 = garanti (attaques de statut pur)
                chance *= capacites_module.multiplicateur_chance_secondaire(capacite_atk)  # Grâce Sereine
                if random.random() * 100 < chance:
                    if ailment == "confusion":
                        # Statut VOLATIL séparé (voir combat_confusion) — jamais bloqué par
                        # un statut principal déjà actif, contrairement aux autres ailments
                        # ci-dessous qui échouent si un statut est déjà en place.
                        if database.definir_confusion(combat_id, adversaire_id, nom_def, random.randint(1, 4)):
                            info_confusion = STATUTS_INFO["confusion"]
                            log.append(f"  {info_confusion['emoji']} **{nom_def}** est {info_confusion['nom']} !")
                            _verifier_baie_statut(combat_id, adversaire_id, nom_def, "confusion", log)
                        else:
                            log.append(f"  ❌ **{nom_def}** n'est pas affecté(e) (immunisé à la confusion) !")
                        # Marionnettiste Toxique (Pêchaminus) : si CETTE MÊME attaque a
                        # aussi empoisonné la cible (voir plus bas, ailment principal
                        # "poison" séparé), les deux se cumulent naturellement puisque la
                        # confusion ne bloque jamais rien — rien de plus à faire ici.
                    else:
                        compteur = random.randint(1, 3) if ailment == "sleep" else 0
                        # Corrosion (Floréclat) : peut empoisonner un Poison/Acier malgré
                        # leur immunité de type naturelle.
                        ignore_immunite_poison = ailment == "poison" and capacites_module.a_corrosion(capacite_atk)
                        if database.definir_statut(combat_id, adversaire_id, nom_def, ailment, compteur, ignore_immunite_poison):
                            info = STATUTS_INFO[ailment]
                            log.append(f"  {info['emoji']} **{nom_def}** est {info['nom']} !")
                            _verifier_baie_statut(combat_id, adversaire_id, nom_def, ailment, log)
                            # Marionnettiste Toxique (Pêchaminus) : si CE poison vient d'une
                            # de SES attaques, la cible devient AUSSI confuse — possible
                            # maintenant que la confusion ne partage plus le même
                            # emplacement que le statut principal.
                            if ailment == "poison" and capacites_module.confond_aussi_si_poison(capacite_atk):
                                if database.definir_confusion(combat_id, adversaire_id, nom_def, random.randint(1, 4)):
                                    log.append(f"  🎭 **{nom_def}** est aussi confus à cause de **Marionnettiste Toxique** !")
                                    _verifier_baie_statut(combat_id, adversaire_id, nom_def, "confusion", log)
                            # Synchro : renvoie le même statut à l'attaquant (Poison/Brûlure/
                            # Paralysie uniquement — pas Sommeil/Gel/Confusion dans les vrais jeux)
                            if ailment in ("poison", "burn", "paralysis") and capacites_module.a_synchro(capacite_def):
                                if not database.obtenir_statut(combat_id, user_id, nom_atk):
                                    if database.definir_statut(combat_id, user_id, nom_atk, ailment, 0):
                                        log.append(f"  🔗 **{nom_atk}** est aussi {info['nom']} à cause de la **Synchro** de **{nom_def}** !")

            # Effet secondaire de stat éventuel (ex: Nitrocharge +1 Vitesse sur soi
            # garanti, Griffe Acier +1 Attaque sur soi à 10%, Étreinte -1 Défense sur la
            # cible à 20%...) — jusqu'ici totalement ignoré sur les attaques qui infligent
            # aussi des dégâts (seules les attaques de statut PURES géraient "stats").
            changements_secondaires = attaque.get("stats", [])
            if changements_secondaires and (attaque.get("stats_cible") == "soi" or attaque.get("cible") == "soi" or pv_restants > 0):
                chance_stat = attaque.get("stat_chance", 0) or 100  # 0 = garanti (donnée absente/ancienne = garanti aussi)
                if random.random() * 100 < chance_stat:
                    # "stats_cible" (nouveau champ optionnel) prime sur "cible" pour décider
                    # qui reçoit CE malus/bonus de stat secondaire — nécessaire car "cible"
                    # ne concerne que le ciblage des DÉGÂTS : une attaque offensive comme
                    # Close Combat ou Surchauffe vise bien l'adversaire pour les dégâts, mais
                    # son malus de stat s'applique à SOI, pas à la cible. Sans ce champ
                    # distinct, ces malus étaient infligés à tort à l'adversaire au lieu de
                    # l'attaquant. Absent (grande majorité des attaques) -> comportement
                    # identique à avant, basé sur "cible".
                    cible_effective = attaque.get("stats_cible") or attaque.get("cible")
                    bloque_ecran_poudre = cible_effective != "soi" and capacites_module.bloque_effets_secondaires_subis(capacite_def)
                    if cible_effective == "soi":
                        cible_stat_id, cible_stat_nom = user_id, nom_atk
                    else:
                        cible_stat_id, cible_stat_nom = adversaire_id, nom_def

                    if bloque_ecran_poudre:
                        pass  # Écran Poudre : effet secondaire totalement bloqué, silencieux
                    else:
                        morceaux = []
                        capacite_cible_stat = database.obtenir_capacite_combat(combat_id, cible_stat_id, cible_stat_nom)
                        double_stat = capacites_module.double_les_boosts(capacite_cible_stat)
                        # Corps Sain : immunisé aux baisses de stats infligées par l'ADVERSAIRE
                        # uniquement — un Pokémon qui se baisse lui-même (Damoclès, Close
                        # Combat...) n'est jamais concerné, cible_effective vaut alors "soi".
                        protege_corps_sain = (
                            cible_effective != "soi"
                            and capacites_module.immunise_contre_baisse_stat_adverse(capacite_cible_stat)
                        )
                        # Cœur de Coq (et similaires) : protège UNE seule stat précise des
                        # baisses infligées par l'adversaire.
                        stat_protegee_specifique = (
                            capacites_module.stat_protegee_contre_adversaire(capacite_cible_stat)
                            if cible_effective != "soi" else None
                        )
                        if protege_corps_sain and all(delta < 0 for _, delta in changements_secondaires):
                            log.append(f"  🛡️ **{cible_stat_nom}** est protégé grâce à **Corps Sain** !")
                        else:
                            stat_specifique_bloquee = False
                            for stat, delta in changements_secondaires:
                                if protege_corps_sain and delta < 0:
                                    continue  # cette baisse précise est bloquée, un éventuel bonus dans le même lot passe
                                if stat_protegee_specifique and stat == stat_protegee_specifique and delta < 0:
                                    stat_specifique_bloquee = True
                                    continue
                                delta_reel = delta * 2 if double_stat else delta
                                nouveau_stage = database.modifier_boost(combat_id, cible_stat_id, cible_stat_nom, stat, delta_reel)
                                signe = "+" if delta_reel > 0 else ""
                                morceaux.append(f"{signe}{delta_reel} {NOMS_STATS[stat]} (stage {nouveau_stage:+d})")
                                # Compétiteur/Défiant : se déclenche dès qu'une stat est
                                # abaissée PAR L'ADVERSAIRE (peu importe laquelle) — jamais
                                # sur une baisse auto-infligée (cible_stat_id == soi).
                                if cible_stat_id == adversaire_id and delta_reel < 0:
                                    boost_cd = capacites_module.boost_si_stat_baissee_par_adversaire(capacite_cible_stat)
                                    if boost_cd:
                                        stat_cd, delta_cd = boost_cd
                                        nouveau_stage_cd = database.modifier_boost(combat_id, adversaire_id, cible_stat_nom, stat_cd, delta_cd)
                                        log.append(f"  📈 **{cible_stat_nom}** riposte ! (+{delta_cd} {NOMS_STATS[stat_cd]}, stage {nouveau_stage_cd:+d})")

                            if stat_specifique_bloquee:
                                info_cs = capacites_module.infos_capacite(capacite_cible_stat)
                                log.append(f"  🛡️ **{cible_stat_nom}** protège sa {NOMS_STATS[stat_protegee_specifique]} grâce à **{info_cs['nom']}** !")
                            if morceaux:
                                log.append(f"  📊 **{cible_stat_nom}** : {', '.join(morceaux)}")


            # Changement Éclair / Demi-Tour et consorts : l'attaquant quitte le combat
            # juste après avoir frappé, à condition d'avoir survécu (recul éventuel
            # compris) et d'avoir un autre Pokémon vivant vers qui basculer — sinon
            # l'attaque reste sans effet de retrait, comme dans les vrais jeux. Réutilise
            # TEL QUEL le mécanisme de remplacement après K.O. (bouton "Envoyer un
            # Pokémon", envoi auto anti-AFK) : la sélection y exclut déjà l'actif en
            # cours par son nom, donc rien d'autre à adapter pour ce cas non-fatal.
            if attaque.get("changement_apres"):
                _, actif_apres_attaque = infos_actif(user_id)
                if actif_apres_attaque and actif_apres_attaque["pv_actuels"] > 0:
                    switches_volontaires[user_id] = (False, nom_atk)

            # Draco-Queue / Projection et consorts : inflige des dégâts PUIS éjecte la
            # CIBLE (pas l'attaquant) vers un remplaçant tiré au hasard, à condition
            # qu'elle ait survécu au coup — sinon c'est un K.O. normal, pas d'éjection en
            # plus. Immédiat et sans choix pour la victime (contrairement à Change
            # Éclair), donc traité directement ici plutôt que via le mécanisme différé.
            if attaque.get("ejecte_adversaire") and pv_restants > 0:
                eq_adverse = database.obtenir_equipe_pvp(combat_id, adversaire_id)
                candidats = [r["pokemon_nom"] for r in eq_adverse if r["pv_actuels"] > 0 and r["pokemon_nom"] != nom_def]
                if candidats:
                    suivant = random.choice(candidats)
                    database.reinitialiser_boosts(combat_id, adversaire_id, nom_def)
                    database.reinitialiser_charge(combat_id, adversaire_id, nom_def)
                    database.reinitialiser_verrouillage_choix(combat_id, adversaire_id, nom_def)
                    database.definir_furie(combat_id, adversaire_id, nom_def, None)
                    database.changer_pokemon_actif_pvp(combat_id, adversaire_id, suivant)
                    log.append(
                        f"  🌀 **{nom_def}** est repoussé hors du combat — "
                        f"{'<@' + str(adversaire_id) + '>' if adversaire_id > 0 else 'son dresseur'} "
                        f"envoie **{suivant}** !"
                    )
                    _appliquer_hazards_entree(combat_id, adversaire_id, suivant, log)
        else:
            # --- Attaque de terrain (Piège de Roc, Picots, Pics Toxik) ---
            if nom_attaque in ATTAQUES_TERRAIN:
                effet = ATTAQUES_TERRAIN[nom_attaque]
                stacks_max = 3 if effet == "spikes" else 1
                stacks = database.poser_hazard(combat_id, adversaire_id, effet, stacks_max)
                couches_txt = f" (couche {stacks}/{stacks_max})" if stacks_max > 1 else ""
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** — "
                    f"le piège est posé du côté adverse !{couches_txt}"
                )
                continue

            # --- Attaque de statut (boosts / malus / altérations) ---
            changements = attaque.get("stats", [])
            ailment = attaque.get("ailment")

            # Prévention (bouclier d'équipe, 1 tour) : bloque toute attaque de statut
            # visant l'adversaire — pas les attaques de statut sur soi-même.
            if attaque.get("cible") == "adversaire":
                cle_def_prevention = database.equipe_cle_pour_joueur(combat_id, adversaire_id)
                if database.obtenir_ecran(combat_id, cle_def_prevention, "prevention"):
                    log.append(
                        f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... "
                        f"mais la Prévention protège **{nom_def}** !"
                    )
                    continue

            # Éjection forcée de l'adversaire (Cyclone) : contrairement à Change Éclair/
            # Demi-Tour (l'ATTAQUANT choisit de partir), ici c'est la CIBLE qui est éjectée
            # sans son consentement, vers un remplaçant tiré AU HASARD parmi ses Pokémon
            # vivants restants — pas de bouton de choix, comme dans les vrais jeux.
            if attaque.get("ejecte_adversaire"):
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
                eq_adverse = database.obtenir_equipe_pvp(combat_id, adversaire_id)
                candidats = [r["pokemon_nom"] for r in eq_adverse if r["pv_actuels"] > 0 and r["pokemon_nom"] != nom_def]
                if not candidats:
                    log.append(f"  ...mais **{nom_def}** n'a personne d'autre à envoyer, ça n'a aucun effet !")
                else:
                    suivant = random.choice(candidats)
                    database.reinitialiser_boosts(combat_id, adversaire_id, nom_def)
                    database.reinitialiser_charge(combat_id, adversaire_id, nom_def)
                    database.reinitialiser_verrouillage_choix(combat_id, adversaire_id, nom_def)
                    database.definir_furie(combat_id, adversaire_id, nom_def, None)
                    database.changer_pokemon_actif_pvp(combat_id, adversaire_id, suivant)
                    log.append(
                        f"  🌀 **{nom_def}** est repoussé hors du combat — "
                        f"{'<@' + str(adversaire_id) + '>' if adversaire_id > 0 else 'son dresseur'} "
                        f"envoie **{suivant}** !"
                    )
                    _appliquer_hazards_entree(combat_id, adversaire_id, suivant, log)
                continue

            # Relais (Baton Pass) : quitte le combat comme Change Éclair, MAIS transmet
            # les boosts de stats actuels au remplaçant au lieu de les perdre — voir la
            # gestion du transfert dans le bloc de remplacement post-tour plus bas et dans
            # les callbacks de choix (_on_envoyer_remplacant / traiter_choix_ko).
            if attaque.get("relais"):
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")
                switches_volontaires[user_id] = (True, nom_atk)
                continue

            if not changements and ailment not in STATUTS_INFO:
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** (sans effet notable)")
                continue

            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")

            # Changements de stats éventuels
            if changements:
                if attaque.get("cible") == "soi":
                    cible_id, cible_nom = user_id, nom_atk
                else:
                    cible_id, cible_nom = adversaire_id, nom_def

                morceaux = []
                capacite_cible = database.obtenir_capacite_combat(combat_id, cible_id, cible_nom)
                double_stat = capacites_module.double_les_boosts(capacite_cible)
                protege_corps_sain_pur = (
                    cible_id == adversaire_id
                    and capacites_module.immunise_contre_baisse_stat_adverse(capacite_cible)
                )
                stat_protegee_pure = (
                    capacites_module.stat_protegee_contre_adversaire(capacite_cible)
                    if cible_id == adversaire_id else None
                )
                if protege_corps_sain_pur and all(delta < 0 for _, delta in changements):
                    log.append(f"  🛡️ **{cible_nom}** est protégé grâce à **Corps Sain** !")
                else:
                    stat_specifique_bloquee_pure = False
                    for stat, delta in changements:
                        if protege_corps_sain_pur and delta < 0:
                            continue
                        if stat_protegee_pure and stat == stat_protegee_pure and delta < 0:
                            stat_specifique_bloquee_pure = True
                            continue
                        delta_reel = delta * 2 if double_stat else delta
                        nouveau_stage = database.modifier_boost(combat_id, cible_id, cible_nom, stat, delta_reel)
                        signe = "+" if delta_reel > 0 else ""
                        morceaux.append(f"{signe}{delta_reel} {NOMS_STATS[stat]} (stage {nouveau_stage:+d})")
                        if cible_id == adversaire_id and delta_reel < 0:
                            boost_cd2 = capacites_module.boost_si_stat_baissee_par_adversaire(capacite_cible)
                            if boost_cd2:
                                stat_cd2, delta_cd2 = boost_cd2
                                nouveau_stage_cd2 = database.modifier_boost(combat_id, adversaire_id, cible_nom, stat_cd2, delta_cd2)
                                log.append(f"  📈 **{cible_nom}** riposte ! (+{delta_cd2} {NOMS_STATS[stat_cd2]}, stage {nouveau_stage_cd2:+d})")

                    if stat_specifique_bloquee_pure:
                        info_cs2 = capacites_module.infos_capacite(capacite_cible)
                        log.append(f"  🛡️ **{cible_nom}** protège sa {NOMS_STATS[stat_protegee_pure]} grâce à **{info_cs2['nom']}** !")
                    if morceaux:
                        log.append(f"  📊 **{cible_nom}** : {', '.join(morceaux)}")

            # Altération de statut pure (Hypnose → sommeil, Para-Spore → paralysie...)
            # ⚠️ CORRECTIF : ciblait toujours l'adversaire, même pour une attaque dont la
            # cible réelle est "soi" (ex: Ventardise — augmente sa propre Attaque, et ne
            # doit PAS confondre l'adversaire au passage). Suit maintenant la même cible
            # que les changements de stats ci-dessus.
            if ailment in STATUTS_INFO:
                cible_ailment_id, cible_ailment_nom = (
                    (user_id, nom_atk) if attaque.get("cible") == "soi" else (adversaire_id, nom_def)
                )
                if ailment == "confusion":
                    # Statut VOLATIL séparé (voir combat_confusion) — ne partage jamais
                    # l'emplacement du statut principal, jamais bloqué par lui.
                    if database.definir_confusion(combat_id, cible_ailment_id, cible_ailment_nom, random.randint(1, 4)):
                        info_confusion = STATUTS_INFO["confusion"]
                        log.append(f"  {info_confusion['emoji']} **{cible_ailment_nom}** est {info_confusion['nom']} !")
                        _verifier_baie_statut(combat_id, cible_ailment_id, cible_ailment_nom, "confusion", log)
                    else:
                        log.append(f"  ❌ **{cible_ailment_nom}** n'est pas affecté(e) (immunisé à la confusion) !")
                else:
                    compteur = random.randint(1, 3) if ailment == "sleep" else 0
                    # capacite_atk n'est PAS forcément déjà en scope ici : ce bloc
                    # "altération de statut pure" est aussi atteint par des attaques
                    # 100% statut (Toxik, Hypnose, Poudre Dodo...) qui n'ont jamais
                    # traversé le calcul de dégâts offensif plus haut (seul endroit où
                    # capacite_atk était fixée jusqu'ici) — d'où le crash "cannot access
                    # local variable" sur CES attaques précises, jamais sur une attaque
                    # offensive avec effet secondaire. Récupérée ici pour couvrir les
                    # deux cas uniformément.
                    capacite_atk = database.obtenir_capacite_combat(combat_id, user_id, nom_atk)
                    ignore_immunite_poison2 = (
                        ailment == "poison" and cible_ailment_id == adversaire_id and capacites_module.a_corrosion(capacite_atk)
                    )
                    # Mycelium Might (Terracruel) : sur SA PROPRE attaque de statut,
                    # ignore l'immunité de CAPACITÉ de la cible (jamais l'immunité de
                    # type, gérée séparément juste au-dessus).
                    ignore_capacite_mycelium = (
                        cible_ailment_id == adversaire_id and capacites_module.a_mycelium_might(capacite_atk)
                    )
                    if database.definir_statut(
                        combat_id, cible_ailment_id, cible_ailment_nom, ailment, compteur,
                        ignore_immunite_poison2, ignore_capacite_mycelium,
                    ):
                        info = STATUTS_INFO[ailment]
                        log.append(f"  {info['emoji']} **{cible_ailment_nom}** est {info['nom']} !")
                        _verifier_baie_statut(combat_id, cible_ailment_id, cible_ailment_nom, ailment, log)
                        if (
                            cible_ailment_id == adversaire_id
                            and ailment in ("poison", "burn", "paralysis")
                            and capacites_module.a_synchro(database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def))
                            and not database.obtenir_statut(combat_id, user_id, nom_atk)
                        ):
                            if database.definir_statut(combat_id, user_id, nom_atk, ailment, 0):
                                log.append(f"  🔗 **{nom_atk}** est aussi {info['nom']} à cause de la **Synchro** de **{nom_def}** !")
                    else:
                        log.append(f"  ❌ **{cible_ailment_nom}** n'est pas affecté(e) (déjà un statut, ou immunisé par son type) !")

    # --- Météo : dégâts de fin de tour (Tempête de Sable/Grêle) + décompte de durée ---
    meteo_active = database.obtenir_meteo(combat_id)
    if meteo_active and meteo_active["type"] in METEO_TYPES_IMMUNISES:
        combat_meteo_snapshot = database.obtenir_combat(combat_id)
        for user_id in (j1, j2):
            nom_actif_m = combat_meteo_snapshot["actif1_nom"] if user_id == j1 else combat_meteo_snapshot["actif2_nom"]
            eq_m = database.obtenir_equipe_pvp(combat_id, user_id)
            actif_row_m = next((r for r in eq_m if r["pokemon_nom"] == nom_actif_m), None)
            if actif_row_m is None or actif_row_m["pv_actuels"] <= 0:
                continue
            pok_m = obtenir_pokemon_par_nom(nom_actif_m)
            types_m = set(pok_m["types"]) if pok_m else {"normal"}
            if types_m & METEO_TYPES_IMMUNISES[meteo_active["type"]]:
                continue
            if capacites_module.immunise_contre_degats_meteo(database.obtenir_capacite_combat(combat_id, user_id, nom_actif_m)):
                continue  # Envelocape
            if capacites_module.immunise_contre_degats_meteo_specifique(database.obtenir_capacite_combat(combat_id, user_id, nom_actif_m), meteo_active["type"]):
                continue  # Voile Sable (sable uniquement)
            if capacites_module.a_garde_magique(database.obtenir_capacite_combat(combat_id, user_id, nom_actif_m)):
                continue  # Garde Magique — aucun dégât indirect, peu importe la source
            degats_meteo = max(1, round(actif_row_m["pv_max"] / 16))
            pv_apres_meteo = database.appliquer_degats_pvp(combat_id, user_id, nom_actif_m, degats_meteo)
            log.append(f"{METEO_INFO[meteo_active['type']]['emoji']} **{nom_actif_m}** souffre de la météo : -{degats_meteo} PV")
            if pv_apres_meteo <= 0:
                log.append(f"  💀 **{nom_actif_m}** est K.O. !")

    # Hydratation : guérit le statut en fin de tour sous la bonne météo (indépendant de
    # METEO_TYPES_IMMUNISES ci-dessus, qui ne concerne que les dégâts sable/grêle).
    if meteo_active:
        combat_hydra_snapshot = database.obtenir_combat(combat_id)
        for user_id in (j1, j2):
            nom_actif_h = combat_hydra_snapshot["actif1_nom"] if user_id == j1 else combat_hydra_snapshot["actif2_nom"]
            eq_h = database.obtenir_equipe_pvp(combat_id, user_id)
            actif_row_h = next((r for r in eq_h if r["pokemon_nom"] == nom_actif_h), None)
            if actif_row_h is None or actif_row_h["pv_actuels"] <= 0:
                continue
            statut_h = database.obtenir_statut(combat_id, user_id, nom_actif_h)
            if not statut_h:
                continue
            if capacites_module.meteo_guerissant_statut(database.obtenir_capacite_combat(combat_id, user_id, nom_actif_h)) == meteo_active["type"]:
                database.retirer_statut(combat_id, user_id, nom_actif_h)
                log.append(f"  💧 **{nom_actif_h}** guérit de son statut grâce à **Hydratation** !")

    meteo_qui_sexpire = database.decrementer_meteo(combat_id)
    if meteo_qui_sexpire:
        log.append(f"{METEO_INFO[meteo_qui_sexpire]['emoji']} {METEO_INFO[meteo_qui_sexpire]['texte_fin']}")

    # --- Champ Herbu : soin de fin de tour (1/16 PV max) pour les Pokémon au sol ---
    terrain_actif_fin_tour = database.obtenir_terrain_zone(combat_id)
    if terrain_actif_fin_tour and terrain_actif_fin_tour["type"] == "herbu":
        combat_herbu_snapshot = database.obtenir_combat(combat_id)
        for user_id in (j1, j2):
            nom_actif_h2 = combat_herbu_snapshot["actif1_nom"] if user_id == j1 else combat_herbu_snapshot["actif2_nom"]
            eq_h2 = database.obtenir_equipe_pvp(combat_id, user_id)
            actif_row_h2 = next((r for r in eq_h2 if r["pokemon_nom"] == nom_actif_h2), None)
            if actif_row_h2 is None or actif_row_h2["pv_actuels"] <= 0 or actif_row_h2["pv_actuels"] >= actif_row_h2["pv_max"]:
                continue
            pok_h2 = formes_objets_module.pokemon_effectif(
                obtenir_pokemon_par_nom(nom_actif_h2), database.obtenir_objet_combat(combat_id, user_id, nom_actif_h2)
            )
            if not _est_au_sol(pok_h2, database.obtenir_capacite_combat(combat_id, user_id, nom_actif_h2), combat_id):
                continue
            soin_herbu = max(1, round(actif_row_h2["pv_max"] / 16))
            database.soigner_pvp(combat_id, user_id, nom_actif_h2, soin_herbu)
            log.append(f"{TERRAIN_INFO['herbu']['emoji']} **{nom_actif_h2}** est soigné par le Champ Herbu : +{soin_herbu} PV")

    terrain_qui_sexpire = database.decrementer_terrain_zone(combat_id)
    if terrain_qui_sexpire:
        log.append(f"{TERRAIN_INFO[terrain_qui_sexpire]['emoji']} {TERRAIN_INFO[terrain_qui_sexpire]['texte_fin']}")

    # --- Écrans d'équipe : décompte de durée pour les DEUX camps (1v1 : chaque camp
    # = 1 joueur, donc equipe_cle = str(j1) et str(j2) directement) ---
    for user_id_ecran in (j1, j2):
        for type_ecran_expire in database.decrementer_ecrans_equipe(combat_id, database.equipe_cle_pour_joueur(combat_id, user_id_ecran)):
            log.append(f"{ECRANS_INFO[type_ecran_expire]['emoji']} {ECRANS_INFO[type_ecran_expire]['texte_fin'].format(equipe=f'<@{user_id_ecran}>')}")

    # --- Effets globaux (Distorsion/Zone Étrange/Zone Magique/Gravité) : décompte ---
    for type_effet_expire in database.decrementer_effets_globaux(combat_id):
        log.append(f"{EFFETS_GLOBAUX_INFO[type_effet_expire]['emoji']} {EFFETS_GLOBAUX_INFO[type_effet_expire]['texte_fin']}")

    # --- Requiem : compte à rebours pour les DEUX actifs (pas les Pokémon en réserve),
    # K.O. direct de ceux qui atteignent 0 ---
    combat_pour_requiem_fin = database.obtenir_combat(combat_id)
    actifs_requiem = []
    if combat_pour_requiem_fin["actif1_nom"]:
        actifs_requiem.append((j1, combat_pour_requiem_fin["actif1_nom"]))
    if combat_pour_requiem_fin["actif2_nom"]:
        actifs_requiem.append((j2, combat_pour_requiem_fin["actif2_nom"]))
    for user_id_requiem, nom_requiem in database.decrementer_requiem_actifs(combat_id, actifs_requiem):
        database.appliquer_degats_pvp(combat_id, user_id_requiem, nom_requiem, 999999)
        log.append(f"🎵 **{nom_requiem}** s'effondre, à bout de souffle... 💀 K.O. !")

    # --- Compteur "tours en jeu" (Lenteur/Slow Start) : incrémenté pour qui est resté
    # actif tout le tour (un Pokémon qui vient d'être envoyé a déjà été remis à 0 par
    # changer_pokemon_actif_pvp, donc l'incrémenter ici aussi ferait démarrer son compte
    # à 1 au lieu de 0 dès son premier tour réellement joué).
    combat = database.obtenir_combat(combat_id)
    for user_id in (j1, j2):
        nom_actif = combat["actif1_nom"] if user_id == j1 else combat["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        actif_row = next((r for r in eq if r["pokemon_nom"] == nom_actif), None)
        if actif_row and actif_row["pv_actuels"] > 0 and user_id not in switches_volontaires:
            database.incrementer_tours_en_jeu(combat_id, user_id, nom_actif)
            # Cran Vital (Speed Boost, Ninjask) : +1 Vitesse à la fin de chaque tour où
            # ce Pokémon est resté actif — même condition que le compteur ci-dessus (pas
            # sur le tour où il vient d'être envoyé).
            capacite_pour_cran_vital = database.obtenir_capacite_combat(combat_id, user_id, nom_actif)
            if capacites_module.a_cran_vital(capacite_pour_cran_vital):
                nouveau_stage_cran_vital = database.modifier_boost(combat_id, user_id, nom_actif, "vit", 1)
                log.append(f"  💨 **{nom_actif}** gagne en Vitesse grâce à **Cran Vital** ! (stage {nouveau_stage_cran_vital:+d})")

    # --- Dégâts de fin de tour : brûlure et poison ---
    combat = database.obtenir_combat(combat_id)
    for user_id in (j1, j2):
        nom_actif = combat["actif1_nom"] if user_id == j1 else combat["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        actif_row = next((r for r in eq if r["pokemon_nom"] == nom_actif), None)
        if actif_row is None or actif_row["pv_actuels"] <= 0:
            continue
        statut_actif = database.obtenir_statut(combat_id, user_id, nom_actif)
        if not statut_actif:
            continue
        code = statut_actif[0]
        if code in ("burn", "poison"):
            capacite_pour_garde_magique = database.obtenir_capacite_combat(combat_id, user_id, nom_actif)
            if capacites_module.a_garde_magique(capacite_pour_garde_magique):
                log.append(f"  🛡️ **{nom_actif}** ignore les dégâts de son statut grâce à **Garde Magique** !")
                continue
            pourcent = DEGATS_BRULURE_POURCENT if code == "burn" else DEGATS_POISON_POURCENT
            degats_statut = max(1, round(actif_row["pv_max"] * pourcent))
            pv_apres = database.appliquer_degats_pvp(combat_id, user_id, nom_actif, degats_statut)
            info = STATUTS_INFO[code]
            log.append(f"{info['emoji']} **{nom_actif}** souffre de son statut ({info['nom']}) : -{degats_statut} PV")
            if pv_apres <= 0:
                log.append(f"  💀 **{nom_actif}** est K.O. !")

        # Cauchemar (Bad Dreams) : dépend de la capacité de L'ADVERSAIRE (pas de celui qui
        # subit le sommeil), vérifié donc séparément de brûlure/poison ci-dessus. Relit les
        # PV à jour de ce Pokémon (actif_row peut être périmé si brûlure/poison l'a déjà
        # blessé juste au-dessus, dans cette même itération).
        statut_actuel_apres = database.obtenir_statut(combat_id, user_id, nom_actif)
        if statut_actuel_apres and statut_actuel_apres[0] == "sleep":
            eq_a_jour = database.obtenir_equipe_pvp(combat_id, user_id)
            actif_row_a_jour = next((r for r in eq_a_jour if r["pokemon_nom"] == nom_actif), None)
            if actif_row_a_jour and actif_row_a_jour["pv_actuels"] > 0:
                adversaire_id = j2 if user_id == j1 else j1
                nom_actif_adv = combat["actif2_nom"] if user_id == j1 else combat["actif1_nom"]
                eq_adv = database.obtenir_equipe_pvp(combat_id, adversaire_id)
                actif_row_adv = next((r for r in eq_adv if r["pokemon_nom"] == nom_actif_adv), None)
                if actif_row_adv and actif_row_adv["pv_actuels"] > 0:
                    capacite_adv = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_actif_adv)
                    fraction_cauchemar = capacites_module.inflige_degats_sommeil_adverse(capacite_adv)
                    if fraction_cauchemar:
                        degats_cauchemar = max(1, round(actif_row_a_jour["pv_max"] * fraction_cauchemar))
                        pv_apres_cauchemar = database.appliquer_degats_pvp(combat_id, user_id, nom_actif, degats_cauchemar)
                        log.append(f"😴 **{nom_actif}** souffre de Cauchemar (**{nom_actif_adv}**) : -{degats_cauchemar} PV")
                        if pv_apres_cauchemar <= 0:
                            log.append(f"  💀 **{nom_actif}** est K.O. !")

    # --- Vérifier les K.O. et gérer le remplacement (+ changements volontaires post-attaque) ---
    combat = database.obtenir_combat(combat_id)
    for user_id in (j1, j2):
        nom_actif = combat["actif1_nom"] if user_id == j1 else combat["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        actif_row = next((r for r in eq if r["pokemon_nom"] == nom_actif), None)
        est_ko = actif_row and actif_row["pv_actuels"] <= 0
        est_switch_volontaire = (
            user_id in switches_volontaires
            and actif_row and actif_row["pv_actuels"] > 0
            and switches_volontaires[user_id][1] == nom_actif  # pas déjà déplacé entre-temps (ex: éjecté par Cyclone adverse avant sa propre résolution)
        )
        if est_ko or est_switch_volontaire:
            est_relais = est_switch_volontaire and switches_volontaires[user_id][0]

            if est_switch_volontaire:
                capacite_sortant = database.obtenir_capacite_combat(combat_id, user_id, nom_actif)
                pourcent_regen = capacites_module.soin_sortie_terrain(capacite_sortant)
                if pourcent_regen:
                    soin_regen = max(1, round(actif_row["pv_max"] * pourcent_regen))
                    database.soigner_pvp(combat_id, user_id, nom_actif, soin_regen)
                    log.append(f"  💚 **{nom_actif}** récupère {soin_regen} PV grâce à **Régénération** en quittant le combat !")
                if capacites_module.soigne_statut_a_la_sortie(capacite_sortant) and database.obtenir_statut(combat_id, user_id, nom_actif):
                    database.retirer_statut(combat_id, user_id, nom_actif)
                    log.append(f"  🌿 **{nom_actif}** guérit de son statut grâce à **Vigilance** en quittant le combat !")

            # Relais (Baton Pass) : ne PAS réinitialiser tout de suite — les boosts de
            # nom_actif doivent survivre jusqu'au transfert vers le remplaçant (choisi
            # immédiatement ci-dessous si envoi auto, ou plus tard via le bouton/le
            # timeout anti-AFK — voir _on_envoyer_remplacant et traiter_choix_ko).
            if not est_relais:
                database.reinitialiser_boosts(combat_id, user_id, nom_actif)
            # Stance Change (Exagide) : revient TOUJOURS en forme Bouclier en quittant le
            # terrain (K.O. ou changement, Relais compris — contrairement aux boosts,
            # ce n'est pas quelque chose que Relais transfère dans les vrais jeux).
            capacite_sortant_stance = database.obtenir_capacite_combat(combat_id, user_id, nom_actif)
            if capacites_module.a_stance_change(capacite_sortant_stance):
                database.definir_forme_lame(combat_id, user_id, nom_actif, False)
            # Illusion (Zoroark) : efface le déguisement en quittant le terrain — sera
            # réévalué frais (contre le NOUVEAU dernier conscient) à son prochain envoi.
            if capacites_module.a_illusion(capacite_sortant_stance):
                database.definir_illusion(combat_id, user_id, nom_actif, None)
            # Camouflage (Kecleon) : redevient son type normal en quittant le terrain.
            if capacites_module.a_camouflage(capacite_sortant_stance):
                database.definir_camouflage(combat_id, user_id, nom_actif, None)
            # Charme (infatuation) : levée en quittant le terrain — v1 : ne couvre que
            # le cas où c'est le Pokémon INFATUÉ lui-même qui part (fidèle aux vrais
            # jeux). Le cas où c'est plutôt SON BÉGUIN qui change de Pokémon en face
            # n'est pas couvert (nécessiterait de tracer PRÉCISÉMENT qui a causé
            # l'infatuation, pas juste un flag booléen) — l'infatuation persisterait
            # alors un peu plus longtemps que dans les vrais jeux.
            database.definir_infatuation(combat_id, user_id, nom_actif, False)
            if est_ko:
                vivants = [r["pokemon_nom"] for r in eq if r["pv_actuels"] > 0]
            else:
                # Changement volontaire : l'actif reste vivant, on l'exclut juste lui-même
                # des choix (il ne peut pas "se remplacer par lui-même").
                vivants = [r["pokemon_nom"] for r in eq if r["pv_actuels"] > 0 and r["pokemon_nom"] != nom_actif]
            if not vivants:
                if est_relais:
                    database.reinitialiser_boosts(combat_id, user_id, nom_actif)  # personne à qui transférer
                continue  # équipe entière K.O. (ou plus personne d'autre à envoyer) : rien à faire de plus
            if user_id > 0 and len(vivants) >= 2:
                # Joueur humain avec un vrai choix : comme dans les jeux, c'est LUI qui
                # décide qui entre — la résolution du tour suivant attend son choix
                # (bouton "Envoyer un Pokémon"), avec envoi auto au bout du délai anti-AFK.
                database.creer_choix_ko(combat_id, user_id, int(time.time()) + config.CHOIX_KO_DUREE_SECONDES, relais=est_relais)
                log.append(
                    f"  🔁 <@{user_id}> — choisis ton prochain Pokémon avec le bouton "
                    f"**Envoyer un Pokémon** ({config.CHOIX_KO_DUREE_SECONDES}s, sinon envoi automatique) !"
                )
            else:
                # IA (dresseur/Arène/Gladio) ou un seul survivant : envoi automatique
                suivant = vivants[0]
                if est_relais:
                    database.copier_boosts(combat_id, user_id, nom_actif, suivant)
                    database.reinitialiser_boosts(combat_id, user_id, nom_actif)
                database.changer_pokemon_actif_pvp(combat_id, user_id, suivant)
                note_relais = " (avec ses boosts de stats hérités de Relais !)" if est_relais else ""
                log.append(f"  → <@{user_id}> envoie **{suivant}**{note_relais} !" if user_id > 0 else f"  → **{suivant}** entre en jeu !")
                _appliquer_hazards_entree(combat_id, user_id, suivant, log)

    return log


async def traiter_choix_ko(bot, combat_id: int, thread) -> bool:
    """Gère les choix de remplaçant en attente pour ce combat. Envoie automatiquement le
    premier vivant pour chaque choix expiré (anti-AFK), en le signalant dans le fil.
    Retourne True s'il reste au moins un choix EN ATTENTE (la résolution doit patienter)."""
    rows = database.obtenir_choix_ko(combat_id)
    if not rows:
        return False

    maintenant = int(time.time())
    reste = False
    for row in rows:
        if maintenant < row["date_limite"]:
            reste = True
            continue
        # Délai écoulé : envoi automatique (supprimer_choix_ko protège contre le double
        # traitement si le joueur clique exactement au même moment)
        if not database.supprimer_choix_ko(combat_id, row["user_id"]):
            continue
        eq = database.obtenir_equipe_pvp(combat_id, row["user_id"])
        suivant = next((r["pokemon_nom"] for r in eq if r["pv_actuels"] > 0), None)
        if suivant is None:
            continue
        if row["relais"]:
            combat_actuel = database.obtenir_combat(combat_id)
            nom_sortant = combat_actuel["actif1_nom"] if row["user_id"] == combat_actuel["joueur1_id"] else combat_actuel["actif2_nom"]
            database.copier_boosts(combat_id, row["user_id"], nom_sortant, suivant)
            database.reinitialiser_boosts(combat_id, row["user_id"], nom_sortant)
        database.changer_pokemon_actif_pvp(combat_id, row["user_id"], suivant)
        mini_log = [f"⏳ <@{row['user_id']}> n'a pas choisi à temps — **{suivant}** est envoyé automatiquement !"]
        _appliquer_hazards_entree(combat_id, row["user_id"], suivant, mini_log)
        if thread is not None:
            try:
                await thread.send("\n".join(mini_log))
            except discord.HTTPException:
                pass
    return reste


def verifier_fin_combat(combat_id: int) -> int | None:
    """Vérifie si une équipe est entièrement K.O. Retourne l'ID du vainqueur, ou None."""
    combat = database.obtenir_combat(combat_id)
    if not combat:
        return None

    for user_id, adversaire_id in [(combat["joueur1_id"], combat["joueur2_id"]), (combat["joueur2_id"], combat["joueur1_id"])]:
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        if all(r["pv_actuels"] <= 0 for r in eq):
            return adversaire_id  # l'adversaire a gagné

    return None


async def supprimer_fil_apres_delai(thread, delai_secondes: int):
    """Supprime le fil de combat après un délai, sans planter s'il a déjà disparu."""
    import asyncio

    await asyncio.sleep(delai_secondes)
    try:
        await thread.delete()
    except Exception:
        pass  # fil déjà supprimé, permissions manquantes, etc.


async def resoudre_abandon(bot, combat_id: int, perdant_id: int):
    """Résout un abandon : le joueur qui quitte perd, l'adversaire gagne par forfait."""
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return

    vainqueur_id = combat["joueur2_id"] if perdant_id == combat["joueur1_id"] else combat["joueur1_id"]
    database.terminer_combat_pvp(combat_id)

    # Duels par mise (voir VueDefiMise) : le pot déjà prélevé aux DEUX joueurs à
    # l'acceptation du défi revient intégralement au vainqueur, abandon compris — se
    # défiler d'un duel avec mise ne protège pas la mise du perdant.
    montant_mise = database.obtenir_mise_combat(combat_id)
    if montant_mise:
        database.ajouter_poke_dollars(vainqueur_id, montant_mise)
        database.retirer_mise_combat(combat_id)

    mult_repetition = database.enregistrer_victoire_pvp_repetition(vainqueur_id, perdant_id)
    database.ajouter_poke_dollars(vainqueur_id, round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent")))
    # La quête "gagner un combat PvP" ne compte QUE les victoires jouées jusqu'au bout —
    # une victoire par abandon (forfait) ne progresse plus la quête. Sans ça, deux joueurs
    # pouvaient s'échanger des abandons pour la compléter à volonté sans jamais vraiment
    # se battre. Les Poké Dollars, l'XP et les stats de victoire restent inchangés (le
    # perdant y perd déjà de son côté : XP de consolation réduite, série remise à zéro).
    database.incrementer_victoires_pvp(vainqueur_id)
    leveling.gagner_xp(vainqueur_id, round(XP_VICTOIRE * mult_repetition))
    leveling.gagner_xp(perdant_id, XP_DEFAITE)

    serie = database.incrementer_serie_victoires_pvp(vainqueur_id)
    database.reinitialiser_serie_victoires_pvp(perdant_id)
    embed_rival = None
    if serie >= 3 and serie % 3 == 0:  # tous les 3 (3, 6, 9...) pour ne pas spammer à chaque victoire
        embed_rival = pnj.construire_embed_reaction(
            "serie_victoires_pvp", user_id=vainqueur_id, joueur=f"<@{vainqueur_id}>"
        )

    vainqueur = bot.get_user(vainqueur_id)
    perdant = bot.get_user(perdant_id)
    # Les titres d'embed ne peuvent pas afficher de mention Discord cliquable (<@id>), donc on
    # y met le pseudo si connu en cache, sinon un repli court — mais la description, elle,
    # utilise toujours la mention native, fiable même si le joueur n'est pas en cache.
    nom_vainqueur = vainqueur.display_name if vainqueur else f"Joueur…{str(vainqueur_id)[-4:]}"
    nom_perdant = perdant.display_name if perdant else f"Joueur…{str(perdant_id)[-4:]}"

    dollars_reels = round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent"))
    # xp_reels = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp() applique
    # son propre multiplicateur en interne, on le reproduit ici seulement pour le texte affiché.
    xp_reels = round(round(XP_VICTOIRE * mult_repetition) * database.multiplicateur_boost(vainqueur_id, "xp"))
    xp_defaite_reelle = round(XP_DEFAITE * database.multiplicateur_boost(perdant_id, "xp"))
    note_reduction = "\n*(récompense réduite : déjà battu cet adversaire aujourd'hui)*" if mult_repetition < 1.0 else ""
    note_mise = f"\n💰 **+{montant_mise} Poké Dollars de mise remportée !**" if montant_mise else ""

    journal.logger(f"🏳️ <@{perdant_id}> a abandonné son combat PvP contre <@{vainqueur_id}> (victoire par forfait).")

    embed = discord.Embed(
        title=f"🏳️ {nom_perdant} a abandonné !",
        description=(
            f"<@{vainqueur_id}> remporte le combat par forfait.\n\n"
            f"🎖️ +{dollars_reels} Poké Dollars & +{xp_reels} XP au vainqueur.{note_reduction}{note_mise}\n"
            f"+{xp_defaite_reelle} XP de consolation pour <@{perdant_id}>."
        ),
        color=discord.Color.orange(),
    )

    if combat["thread_id"]:
        try:
            thread = bot.get_channel(int(combat["thread_id"])) or await bot.fetch_channel(int(combat["thread_id"]))
            if thread:
                embeds_a_envoyer = [embed, embed_rival] if embed_rival else [embed]
                await thread.send(embeds=embeds_a_envoyer, view=VueRevancheCombat(vainqueur_id, perdant_id))
                await thread.send(f"🗑️ Ce fil sera supprimé automatiquement dans {DELAI_SUPPRESSION_FIL // 60} minutes.")
                bot.loop.create_task(supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))
        except Exception:
            pass


async def boucle_resolution_tour(bot, combat_id: int, thread_id: int, message_id: int, duree: int):
    """Attend la fin du timer ou que les deux joueurs aient joué, puis résout le tour.

    Toute exception imprévue dans un tick tuait la tâche asyncio EN SILENCE et laissait
    le combat figé pour toujours (même famille de bug que les combats dresseur bloqués).
    Chaque tick est donc protégé : erreur → journalisée + retentée au tick suivant, et si
    l'erreur persiste 3 ticks d'affilée, le combat est clôturé proprement plutôt que de
    bloquer les deux joueurs indéfiniment."""
    import asyncio

    echecs_consecutifs = 0

    while True:
        await asyncio.sleep(5)

        try:
            fini = await _tick_resolution_pvp(bot, combat_id, thread_id, message_id, duree)
            if fini:
                return
            echecs_consecutifs = 0
            continue
        except Exception:
            import traceback

            echecs_consecutifs += 1
            print(f"⚠️ Erreur au tick de résolution du combat PvP {combat_id} (tentative {echecs_consecutifs}/3) :")
            traceback.print_exc()
            if echecs_consecutifs == 1:
                journal.logger(
                    f"🔴 Erreur dans la résolution du combat PvP {combat_id} — nouvelle tentative "
                    f"au prochain tick, voir logs serveur."
                )
            if echecs_consecutifs >= 3:
                database.terminer_combat_pvp(combat_id)
                journal.logger(
                    f"🔴 Combat PvP {combat_id} clôturé de force après 3 erreurs consécutives — "
                    f"les joueurs ne sont plus bloqués (aucune récompense distribuée)."
                )
                try:
                    thread = bot.get_channel(int(thread_id)) or await bot.fetch_channel(int(thread_id))
                    if thread is not None:
                        await thread.send(
                            "⚠️ Une erreur répétée a interrompu ce combat. Il a été annulé "
                            "(ni victoire ni défaite), vous pouvez en relancer un."
                        )
                        bot.loop.create_task(supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))
                except Exception:
                    pass
                return


async def _tick_resolution_pvp(bot, combat_id: int, thread_id: int, message_id: int, duree: int) -> bool:
    """Un tick de résolution. Retourne True si le combat est terminé (la boucle s'arrête)."""
    if True:
        combat = database.obtenir_combat(combat_id)
        if not combat or not combat["actif"]:
            return True

        # Un joueur doit choisir son remplaçant après un K.O. : la résolution attend
        # (envoi automatique géré par traiter_choix_ko une fois le délai anti-AFK écoulé).
        thread_choix = bot.get_channel(int(thread_id))
        if await traiter_choix_ko(bot, combat_id, thread_choix):
            return False

        # Un joueur en pleine charge/recharge (attaque à deux tours) n'a rien à choisir ce
        # tour-ci — son action reste NULL à raison, mais ça ne doit pas forcer à attendre le
        # timer complet si l'adversaire, lui, a déjà joué.
        charge1 = database.obtenir_charge(combat_id, combat["joueur1_id"], combat["actif1_nom"])
        charge2 = database.obtenir_charge(combat_id, combat["joueur2_id"], combat["actif2_nom"])
        j1_verrouille = bool(charge1["attaque_en_charge"]) or charge1["doit_recharger"]
        j2_verrouille = bool(charge2["attaque_en_charge"]) or charge2["doit_recharger"]

        action1_prete = combat["action1"] is not None or j1_verrouille
        action2_prete = combat["action2"] is not None or j2_verrouille
        deux_joueurs_prets = action1_prete and action2_prete
        timer_expire = int(time.time()) >= combat["date_limite_tour"]

        if not deux_joueurs_prets and not timer_expire:
            return False  # rien à résoudre ce tick-ci

        # Résoudre le tour
        log = await resoudre_tour(combat_id)
        vainqueur_id = verifier_fin_combat(combat_id)

        thread = bot.get_channel(int(thread_id))
        if thread is None:
            # get_channel ne regarde que le cache local — un fil peut en être absent
            # (redémarrage, inactivité...) sans avoir réellement disparu. On vérifie pour
            # de vrai auprès de Discord avant de conclure que le combat doit se terminer.
            try:
                thread = await bot.fetch_channel(int(thread_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                thread = None

        if thread is None:
            database.terminer_combat_pvp(combat_id)
            return True

        if vainqueur_id is not None:
            database.terminer_combat_pvp(combat_id)
            perdant_id = combat["joueur2_id"] if vainqueur_id == combat["joueur1_id"] else combat["joueur1_id"]

            # Duels par mise (voir VueDefiMise) : même principe que dans resoudre_abandon
            # ci-dessus — le pot revient intégralement au vainqueur.
            montant_mise = database.obtenir_mise_combat(combat_id)
            if montant_mise:
                database.ajouter_poke_dollars(vainqueur_id, montant_mise)
                database.retirer_mise_combat(combat_id)

            annonce_envoyee = False
            try:
                journal.logger(f"🥊 <@{vainqueur_id}> a battu <@{perdant_id}> en combat PvP.")
                mult_repetition = database.enregistrer_victoire_pvp_repetition(vainqueur_id, perdant_id)
                database.ajouter_poke_dollars(vainqueur_id, round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent")))
                quetes_completees = database.incrementer_progression_quete(vainqueur_id, "pvp_victoire")
                database.incrementer_victoires_pvp(vainqueur_id)
                leveling.gagner_xp(vainqueur_id, round(XP_VICTOIRE * mult_repetition))
                leveling.gagner_xp(perdant_id, XP_DEFAITE)

                serie = database.incrementer_serie_victoires_pvp(vainqueur_id)
                database.reinitialiser_serie_victoires_pvp(perdant_id)
                embed_rival = None
                if serie >= 3 and serie % 3 == 0:
                    embed_rival = pnj.construire_embed_reaction(
                        "serie_victoires_pvp", user_id=vainqueur_id, joueur=f"<@{vainqueur_id}>"
                    )
                elif random.random() < 0.2:
                    embed_rival = pnj.construire_embed_reaction(
                        "defaite_pvp", user_id=perdant_id, joueur=f"<@{perdant_id}>"
                    )

                vainqueur = bot.get_user(vainqueur_id)
                nom_vainqueur = vainqueur.display_name if vainqueur else f"Joueur…{str(vainqueur_id)[-4:]}"
                dollars_reels = round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent"))
                # XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp() applique
                # son propre multiplicateur en interne, on le reproduit ici pour le texte affiché.
                xp_reels = round(round(XP_VICTOIRE * mult_repetition) * database.multiplicateur_boost(vainqueur_id, "xp"))
                texte_recompense = f"\n\n🎖️ +{dollars_reels} Poké Dollars & +{xp_reels} XP au vainqueur !"
                if mult_repetition < 1.0:
                    texte_recompense += "\n*(récompense réduite : déjà battu cet adversaire aujourd'hui)*"
                if montant_mise:
                    texte_recompense += f"\n💰 **+{montant_mise} Poké Dollars de mise remportée !**"
                embed = discord.Embed(
                    title=f"🏆 {nom_vainqueur} remporte le combat !",
                    description=(
                        "\n".join(log)
                        + texte_recompense
                        + quetes_ui.texte_notifications_completion(quetes_completees)
                    ),
                    color=discord.Color.gold(),
                )
                try:
                    msg = await thread.fetch_message(message_id)
                    embeds_a_envoyer = [embed, embed_rival] if embed_rival else [embed]
                    await msg.edit(embeds=embeds_a_envoyer, view=VueRevancheCombat(vainqueur_id, perdant_id))
                except discord.NotFound:
                    await thread.send(embed=embed, view=VueRevancheCombat(vainqueur_id, perdant_id))
                annonce_envoyee = True
            except Exception:
                # Le combat est déjà marqué terminé en base à ce stade (ligne ci-dessus) —
                # une erreur ici ne doit JAMAIS laisser les joueurs sans savoir qui a gagné,
                # ni empêcher le nettoyage du fil. On journalise pour diagnostiquer la vraie
                # cause, et on retombe sur une annonce minimale.
                import traceback

                print(f"⚠️ Erreur en clôturant le combat PvP {combat_id} (déjà marqué terminé en base) :")
                traceback.print_exc()
                journal.logger(
                    f"🔴 Erreur en clôturant le combat PvP {combat_id} (vainqueur : <@{vainqueur_id}>) — "
                    f"voir les logs serveur pour le détail complet."
                )

            if not annonce_envoyee:
                try:
                    await thread.send(
                        f"🏆 <@{vainqueur_id}> remporte le combat ! (un souci est survenu pour afficher le "
                        f"détail complet du dernier tour — les récompenses ont quand même été attribuées)"
                    )
                except Exception:
                    pass

            try:
                await thread.send(f"🗑️ Ce fil sera supprimé automatiquement dans {DELAI_SUPPRESSION_FIL // 60} minutes.")
            except Exception:
                pass
            bot.loop.create_task(supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))
            return True

        # Passer au tour suivant
        nouvelle_limite = int(time.time()) + duree
        database.passer_tour_pvp(combat_id, nouvelle_limite)
        combat = database.obtenir_combat(combat_id)
        nouveau_tour = combat["tour"]
        j1 = combat["joueur1_id"]
        j2 = combat["joueur2_id"]

        noms = {
            j1: (bot.get_user(j1).display_name if bot.get_user(j1) else f"Joueur {str(j1)[-4:]}"),
            j2: (bot.get_user(j2).display_name if bot.get_user(j2) else f"Joueur {str(j2)[-4:]}"),
        }
        vue = VueActionCombat(combat_id, nouveau_tour, avec_choix_ko=bool(database.obtenir_choix_ko(combat_id)))
        fichier_scene = _generer_fichier_scene_combat(combat_id, noms, log_tour=log)
        try:
            msg = await thread.fetch_message(message_id)
            if fichier_scene:
                await msg.edit(embeds=[], view=vue, attachments=[fichier_scene])
            else:
                await msg.edit(embeds=[], view=vue)
        except discord.HTTPException as e:
            # ⚠️ Même piste que dresseurs.py : erreur avant totalement silencieuse.
            print(f"⚠️ Échec de la mise à jour de l'image de combat PvP {combat_id} (tour suivant, le prochain tick retentera) : {e}")
        return False


# ----------------------------------------------------------------------------
# Vue d'action (boutons de chaque joueur)
# ----------------------------------------------------------------------------

class VueActionCombat(discord.ui.View):
    """Panneau d'action PARTAGÉ, affiché dans le fil sous les embeds du combat.
    Chaque joueur clique sur le même panneau ; les vérifications se font en base :
    seul un des deux combattants peut agir, une seule fois par tour."""

    def __init__(self, combat_id: int, tour: int, avec_choix_ko: bool = False):
        super().__init__(timeout=None)  # le message est édité à chaque tour, pas de timeout
        self.combat_id = combat_id
        self.tour = tour
        if avec_choix_ko:
            bouton = discord.ui.Button(label="Envoyer un Pokémon", emoji="🔁", style=discord.ButtonStyle.primary, row=1)
            bouton.callback = self._on_envoyer_remplacant
            self.add_item(bouton)

    async def _on_envoyer_remplacant(self, interaction: discord.Interaction):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est terminé.", ephemeral=True)
            return
        if not any(r["user_id"] == interaction.user.id for r in database.obtenir_choix_ko(self.combat_id)):
            await interaction.response.send_message(
                "Tu n'as pas de Pokémon K.O. à remplacer (ou l'envoi automatique a déjà eu lieu).",
                ephemeral=True,
            )
            return
        nom_actif = combat["actif1_nom"] if combat["joueur1_id"] == interaction.user.id else combat["actif2_nom"]
        equipe = database.obtenir_equipe_pvp(self.combat_id, interaction.user.id)
        vivants = [r for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != nom_actif]
        if not vivants:
            await interaction.response.send_message("Tu n'as plus d'autres Pokémon vivants !", ephemeral=True)
            return
        vue = VueChoixRemplacantKO(self.combat_id, interaction.user.id, vivants)
        await interaction.response.send_message("Quel Pokémon envoyer au combat ?", view=vue, ephemeral=True)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est terminé.", ephemeral=True)
            return False
        if combat["tour"] != self.tour:
            await interaction.response.send_message("⌛ Ce tour est déjà résolu.", ephemeral=True)
            return False
        if interaction.user.id not in (combat["joueur1_id"], combat["joueur2_id"]):
            await interaction.response.send_message("Tu n'es pas un des combattants !", ephemeral=True)
            return False
        deja_joue = (
            combat["action1"] is not None
            if interaction.user.id == combat["joueur1_id"]
            else combat["action2"] is not None
        )
        if deja_joue:
            await interaction.response.send_message("Tu as déjà choisi ton action pour ce tour !", ephemeral=True)
            return False
        if any(r["user_id"] == interaction.user.id for r in database.obtenir_choix_ko(self.combat_id)):
            await interaction.response.send_message(
                "🔁 Ton Pokémon est K.O. — choisis d'abord ton remplaçant avec le bouton "
                "**Envoyer un Pokémon** !",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Méga-Évoluer", style=discord.ButtonStyle.primary, emoji="🔷", row=1)
    async def mega_evoluer(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est terminé.", ephemeral=True)
            return
        if interaction.user.id not in (combat["joueur1_id"], combat["joueur2_id"]):
            await interaction.response.send_message("Tu n'es pas un des combattants !", ephemeral=True)
            return
        if database.a_deja_mega_evolue(self.combat_id, interaction.user.id):
            await interaction.response.send_message("Tu as déjà utilisé ta Méga-Évolution pour ce combat !", ephemeral=True)
            return

        actif_nom = combat["actif1_nom"] if combat["joueur1_id"] == interaction.user.id else combat["actif2_nom"]
        equipe = database.obtenir_equipe_pvp(self.combat_id, interaction.user.id)
        row = next((r for r in equipe if r["pokemon_nom"] == actif_nom), None)
        if row is None or row["pv_actuels"] <= 0:
            await interaction.response.send_message("Ton Pokémon actif est K.O. !", ephemeral=True)
            return

        # Cas spécial : Rayquaza n'a besoin d'AUCUNE Pierre Méga — juste de connaître
        # Draco-Ascension, contrairement à toutes les autres Méga-Évolutions.
        if actif_nom == "Rayquaza":
            attaques_equipees = database.obtenir_attaques_equipees(interaction.user.id, "Rayquaza", combat_id=self.combat_id)
            if mega_evolutions_module.MEGA_RAYQUAZA["attaque_requise"] not in attaques_equipees.values():
                await interaction.response.send_message(
                    "❌ **Rayquaza** doit connaître **Draco-Ascension** pour Méga-Évoluer — "
                    "aucune Pierre Méga n'est nécessaire pour lui, juste cette attaque équipée.",
                    ephemeral=True,
                )
                return
            stone_info = mega_evolutions_module.MEGA_RAYQUAZA
            cle_stone = None  # pas de pierre, aucune ambiguïté de variante (une seule Méga-Rayquaza)
        else:
            objet_tenu = row["objet_tenu"]
            stone_info = mega_evolutions_module.MEGA_EVOLUTIONS.get(objet_tenu) if objet_tenu else None
            if not stone_info or stone_info["espece"] != actif_nom:
                await interaction.response.send_message(
                    f"❌ **{actif_nom}** ne tient pas de Pierre Méga compatible — équipe-la d'abord avec `/equiper-objet`.",
                    ephemeral=True,
                )
                return
            cle_stone = objet_tenu  # distingue les variantes X/Y (Dracaufeu, Mewtwo) pour le bon sprite

        ivs = database.obtenir_meilleures_ivs(interaction.user.id, actif_nom) or IV_DEFAUT
        pokemon_mega = {
            "nom": stone_info["forme_nom"], "types": stone_info["types"],
            "stats_detaillees": stone_info["stats_detaillees"],
        }
        nouvelles_stats = calculer_toutes_stats(pokemon_mega, ivs, row["niveau"])
        database.activer_mega_evolution_combat(
            self.combat_id, interaction.user.id, row["position"], actif_nom, nouvelles_stats, cle_stone=cle_stone
        )

        await interaction.response.send_message(
            f"🔷 **{actif_nom}** Méga-Évolue en **{stone_info['forme_nom']}** ! Ses statistiques de combat sont "
            f"boostées pour le reste du combat (les PV ne changent jamais). N'oublie pas de choisir ton attaque !",
            ephemeral=False,
        )

    @discord.ui.button(label="Attaquer", style=discord.ButtonStyle.danger, emoji="⚔️", row=0)
    async def attaquer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        combat = database.obtenir_combat(self.combat_id)
        actif_nom = combat["actif1_nom"] if combat["joueur1_id"] == interaction.user.id else combat["actif2_nom"]
        equipees = database.obtenir_attaques_equipees(interaction.user.id, actif_nom, combat_id=self.combat_id)

        if not equipees:
            # Aucune attaque équipée : Charge par défaut, directement (illimitée, hors système de PP)
            database.enregistrer_action_pvp(self.combat_id, interaction.user.id, f"attaque:{ATTAQUE_DEFAUT_NOM}")
            await interaction.response.send_message(
                f"⚔️ **{actif_nom}** utilisera **{ATTAQUE_DEFAUT_NOM}** (aucune attaque équipée — "
                f"va voir le Maître des Types !)",
                ephemeral=True,
            )
            return

        # Ne proposer que les attaques ayant encore des PP
        equipees_avec_pp = {}
        for slot, nom in equipees.items():
            pp_max = pp_max_attaque(obtenir_attaque(nom))
            pp_restant = database.obtenir_pp(self.combat_id, interaction.user.id, actif_nom, nom, pp_max)
            if pp_restant > 0:
                equipees_avec_pp[slot] = nom

        if not equipees_avec_pp:
            # Toutes les attaques équipées sont à 0 PP : Lutte automatique, comme dans les vrais jeux
            database.enregistrer_action_pvp(self.combat_id, interaction.user.id, f"attaque:{NOM_LUTTE}")
            await interaction.response.send_message(
                f"💥 **{actif_nom}** n'a plus de PP pour aucune de ses attaques — il utilisera **Lutte** "
                f"(contrecoup de {round(LUTTE_RECOIL_POURCENT * 100)}% de ses PV max) !",
                ephemeral=True,
            )
            return

        vue = VueChoixAttaque(self.combat_id, interaction.user.id, actif_nom, equipees_avec_pp)
        await interaction.response.send_message("Quelle attaque utiliser ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Potion", style=discord.ButtonStyle.success, emoji="💊", row=0)
    async def potion(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        from pokemon_data import NOM_SOIN_AFFICHAGE
        inventaire = database.obtenir_inventaire_balls(interaction.user.id)
        potions_dispo = {k: v for k, v in inventaire.items() if k in NOM_SOIN_AFFICHAGE and v > 0}

        # Limite de potions de SOIN (PV) par combat — Total Soin n'est jamais concerné.
        limite_atteinte = (
            database.compter_potions_soin_utilisees(self.combat_id, interaction.user.id)
            >= config.LIMITE_POTIONS_SOIN_COMBAT
        )
        if limite_atteinte:
            potions_dispo = {k: v for k, v in potions_dispo.items() if k == "totalsoin"}

        if not potions_dispo:
            message = (
                f"Tu as déjà utilisé tes {config.LIMITE_POTIONS_SOIN_COMBAT} potions de soin "
                "pour ce combat !" if limite_atteinte else "Tu n'as plus aucune potion !"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        vue = VueChoixPotion(self.combat_id, interaction.user.id, potions_dispo)
        await interaction.response.send_message("Quel objet de soin utiliser ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Changer", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def changer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        combat = database.obtenir_combat(self.combat_id)
        actif_nom = combat["actif1_nom"] if combat["joueur1_id"] == interaction.user.id else combat["actif2_nom"]
        equipe = database.obtenir_equipe_pvp(self.combat_id, interaction.user.id)
        vivants = [r for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != actif_nom]
        if not vivants:
            await interaction.response.send_message("Tu n'as plus d'autres Pokémon vivants !", ephemeral=True)
            return
        vue = VueChoixChangement(self.combat_id, interaction.user.id, vivants)
        await interaction.response.send_message("Quel Pokémon envoyer ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Abandonner", style=discord.ButtonStyle.secondary, emoji="🏳️", row=1)
    async def abandonner(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est déjà terminé.", ephemeral=True)
            return
        if interaction.user.id not in (combat["joueur1_id"], combat["joueur2_id"]):
            await interaction.response.send_message("Tu n'es pas un des combattants !", ephemeral=True)
            return
        await interaction.response.send_message(
            "🏳️ Es-tu sûr de vouloir abandonner ? La défaite sera enregistrée immédiatement.",
            view=VueConfirmationAbandon(self.combat_id, interaction.user.id),
            ephemeral=True,
        )


class VueConfirmationAbandon(discord.ui.View):
    """Confirmation avant un abandon — irréversible dès validé, donc un simple clic
    accidentel sur le bouton principal ne doit jamais suffire à perdre le combat.

    IMPORTANT : "Annuler" est déclaré EN PREMIER (donc affiché en premier/à gauche) —
    un joueur ayant rapporté un abandon "sans confirmation" malgré un seul clic, le
    bouton "Oui, abandonner" occupait vraisemblablement à peu près la même position à
    l'écran que le bouton "Abandonner" initial, rendant un double-tap accidentel au
    même endroit (fréquent sur mobile) indiscernable d'un vrai clic volontaire sur la
    confirmation. Mettre l'option sûre en premier réduit ce risque, sans certitude
    absolue que c'était la cause exacte (aucun bug de code trouvé par ailleurs)."""

    def __init__(self, combat_id: int, user_id: int):
        super().__init__(timeout=60)
        self.combat_id = combat_id
        self.user_id = user_id

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Abandon annulé — le combat continue.", view=None)

    @discord.ui.button(label="Oui, abandonner", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.edit_message(content="Ce combat est déjà terminé.", view=None)
            return
        await interaction.response.edit_message(content="🏳️ Tu as abandonné. Défaite enregistrée.", view=None)
        await resoudre_abandon(interaction.client, self.combat_id, self.user_id)


class VueChoixRemplacantKO(discord.ui.View):
    """Sous-menu éphémère : choisir le Pokémon envoyé après un K.O. — changement GRATUIT
    (ne consomme pas le tour), comme dans les jeux officiels."""

    def __init__(self, combat_id: int, user_id: int, vivants: list):
        super().__init__(timeout=config.CHOIX_KO_DUREE_SECONDES)
        self.combat_id = combat_id
        self.user_id = user_id
        options = [
            discord.SelectOption(label=r["pokemon_nom"], description=f"{r['pv_actuels']}/{r['pv_max']} PV")
            for r in vivants[:25]
        ]
        select = discord.ui.Select(placeholder="Choisis ton prochain Pokémon…", options=options)
        select.callback = self._on_choix
        self.add_item(select)
        self._select = select

    async def _on_choix(self, interaction: discord.Interaction):
        # Récupère le flag "relais" AVANT de supprimer la ligne (verrou anti-double-envoi).
        ligne_choix = next(
            (r for r in database.obtenir_choix_ko(self.combat_id) if r["user_id"] == self.user_id), None
        )
        if not database.supprimer_choix_ko(self.combat_id, self.user_id):
            await interaction.response.edit_message(
                content="⏳ Trop tard — l'envoi automatique a déjà eu lieu !", view=None
            )
            return
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.edit_message(content="Ce combat est terminé.", view=None)
            return
        nouveau_nom = self._select.values[0]
        if ligne_choix and ligne_choix["relais"]:
            nom_sortant = combat["actif1_nom"] if self.user_id == combat["joueur1_id"] else combat["actif2_nom"]
            database.copier_boosts(self.combat_id, self.user_id, nom_sortant, nouveau_nom)
            database.reinitialiser_boosts(self.combat_id, self.user_id, nom_sortant)
        database.changer_pokemon_actif_pvp(self.combat_id, self.user_id, nouveau_nom)
        mini_log = [f"🔁 <@{self.user_id}> envoie **{nouveau_nom}** !"]
        _appliquer_hazards_entree(self.combat_id, self.user_id, nouveau_nom, mini_log)
        await interaction.response.edit_message(content=f"✅ **{nouveau_nom}** entre en jeu !", view=None)
        try:
            await interaction.channel.send("\n".join(mini_log))
        except discord.HTTPException:
            pass


class VueChoixPotion(discord.ui.View):
    """Sous-menu éphémère : choisir quelle potion utiliser ce tour."""

    def __init__(self, combat_id: int, user_id: int, potions: dict):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id
        from pokemon_data import EMOJI_SOINS, NOM_SOIN_AFFICHAGE
        for type_potion, quantite in potions.items():
            bouton = discord.ui.Button(
                label=f"{NOM_SOIN_AFFICHAGE[type_potion]} (x{quantite})",
                emoji=EMOJI_SOINS.get(type_potion),
                style=discord.ButtonStyle.success,
            )
            bouton.callback = self._creer_callback(type_potion)
            self.add_item(bouton)

    def _creer_callback(self, type_potion: str):
        async def callback(interaction: discord.Interaction):
            combat = database.obtenir_combat(self.combat_id)
            deja_joue = (
                combat["action1"] is not None
                if interaction.user.id == combat["joueur1_id"]
                else combat["action2"] is not None
            )
            if deja_joue:
                await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
                return
            if type_potion != "totalsoin" and (
                database.compter_potions_soin_utilisees(self.combat_id, self.user_id)
                >= config.LIMITE_POTIONS_SOIN_COMBAT
            ):
                await interaction.response.edit_message(
                    content=f"Tu as déjà utilisé tes {config.LIMITE_POTIONS_SOIN_COMBAT} potions de soin pour ce combat !",
                    view=None,
                )
                return
            if not database.retirer_ball(self.user_id, type_potion):
                await interaction.response.edit_message(content="Tu n'as plus cette potion !", view=None)
                return
            database.enregistrer_action_pvp(self.combat_id, self.user_id, f"potion:{type_potion}")
            if type_potion != "totalsoin":
                database.incrementer_potions_soin_utilisees(self.combat_id, self.user_id)
            await interaction.response.edit_message(content="💊 Action enregistrée : potion !", view=None)
        return callback


class VueChoixChangement(discord.ui.View):
    """Sous-menu éphémère : choisir quel Pokémon envoyer ce tour."""

    def __init__(self, combat_id: int, user_id: int, vivants: list):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id
        options = [
            discord.SelectOption(
                label=f"{r['pokemon_nom']} ({r['pv_actuels']}/{r['pv_max']} PV)",
                value=r["pokemon_nom"],
            )
            for r in vivants[:25]
        ]
        select = discord.ui.Select(placeholder="Choisir un Pokémon...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        combat = database.obtenir_combat(self.combat_id)
        deja_joue = (
            combat["action1"] is not None
            if interaction.user.id == combat["joueur1_id"]
            else combat["action2"] is not None
        )
        if deja_joue:
            await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
            return
        nom = interaction.data["values"][0]
        database.enregistrer_action_pvp(self.combat_id, self.user_id, f"changer:{nom}")
        await interaction.response.edit_message(content=f"🔄 Action enregistrée : envoi de **{nom}** !", view=None)


class VueChoixAttaque(discord.ui.View):
    """Sous-menu éphémère : choisir laquelle des attaques équipées (avec PP restant) utiliser ce tour."""

    def __init__(self, combat_id: int, user_id: int, pokemon_nom: str, equipees: dict):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id

        options = []
        for slot in sorted(equipees):
            nom = equipees[slot]
            attaque = obtenir_attaque(nom)
            emoji = EMOJI_TYPES.get(attaque["type"], "⚔️")
            pp_max = pp_max_attaque(attaque)
            pp_restant = database.obtenir_pp(combat_id, user_id, pokemon_nom, nom, pp_max)
            if attaque.get("puissance"):
                desc = f"{attaque['puissance']} pcs — préc. {attaque.get('precision') or '∞'}% — {pp_restant}/{pp_max} PP"
            else:
                morceaux = [f"{'+' if d > 0 else ''}{d} {s.upper()}" for s, d in attaque.get("stats", [])]
                base = ", ".join(morceaux) if morceaux else "Attaque de statut"
                desc = f"{base} — {pp_restant}/{pp_max} PP"
            options.append(
                discord.SelectOption(label=nom[:100], description=desc[:100], value=nom, emoji=emoji)
            )

        select = discord.ui.Select(placeholder="Choisis ton attaque...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.edit_message(content="Ce combat est terminé.", view=None)
            return
        deja_joue = (
            combat["action1"] is not None
            if interaction.user.id == combat["joueur1_id"]
            else combat["action2"] is not None
        )
        if deja_joue:
            await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
            return
        nom = interaction.data["values"][0]
        database.enregistrer_action_pvp(self.combat_id, self.user_id, f"attaque:{nom}")
        await interaction.response.edit_message(content=f"⚔️ Action enregistrée : **{nom}** !", view=None)
