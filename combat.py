import random
import time

import discord

import capacites as capacites_module
import formes_objets as formes_objets_module
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
DEGATS_BRULURE_POURCENT = 0.06   # 6% des PV max par tour
DEGATS_POISON_POURCENT = 0.10    # 10% des PV max par tour
CHANCE_PARALYSIE_SKIP = 0.25     # 25% de ne pas pouvoir agir
CHANCE_DEGEL = 0.20              # 20% de dégeler chaque tour
CHANCE_MUE = 0.30                # Mue : 30% de guérir son propre statut chaque tour
CHANCE_CRITIQUE = 1 / 24         # Taux de critique officiel de base (pas de ratio par attaque pour l'instant)
CHANCE_CONFUSION_SKIP = 0.33     # 33% de se blesser au lieu d'agir
DOLLARS_VICTOIRE = 150
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
    """À appeler juste après tout database.definir_statut(...) réussi : si le Pokémon qui
    vient de recevoir ce statut tient une baie qui le guérit (Pêcha/Chéri/Kika...), elle se
    déclenche immédiatement et se consomme — comme dans les vrais jeux."""
    objet = database.obtenir_objet_combat(combat_id, user_id, pokemon_nom)
    info_baie = capacites_module.guerison_statut_objet(objet, code_statut)
    if info_baie:
        database.retirer_statut(combat_id, user_id, pokemon_nom)
        database.definir_objet_combat(combat_id, user_id, pokemon_nom, None)
        log.append(f"  {info_baie['emoji']} **{pokemon_nom}** guérit aussitôt grâce à sa **{info_baie['nom']}** !")


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


def construire_embeds_combat(combat_id: int, log_tour: list = None, noms: dict = None) -> list:
    """Construit les embeds du combat : un par joueur (sprite animé du Pokémon actif,
    barre de PV, réserve), plus un embed de log si un tour vient d'être résolu."""
    combat = database.obtenir_combat(combat_id)
    if combat is None:
        return [discord.Embed(description="Combat introuvable.", color=discord.Color.red())]

    embeds = []
    couleurs = [discord.Color.blue(), discord.Color.red()]
    cotes = [
        (combat["joueur1_id"], combat["actif1_nom"], combat["action1"]),
        (combat["joueur2_id"], combat["actif2_nom"], combat["action2"]),
    ]

    for (user_id, actif_nom, action), couleur in zip(cotes, couleurs):
        equipe = database.obtenir_equipe_pvp(combat_id, user_id)
        actif_row = next((r for r in equipe if r["pokemon_nom"] == actif_nom), None)
        objet_actif = database.obtenir_objet_combat(combat_id, user_id, actif_nom)
        pokemon = formes_objets_module.pokemon_effectif(obtenir_pokemon_par_nom(actif_nom), objet_actif)
        nom_affiche = formes_objets_module.nom_affichage(actif_nom, objet_actif)

        nom_joueur = noms.get(user_id) if noms else None
        nom_joueur = nom_joueur or f"Joueur {str(user_id)[-4:]}"
        statut = "✅ prêt" if action else "⏳ choisit..."

        embed = discord.Embed(color=couleur)
        embed.set_author(name=f"{nom_joueur} — {statut}")
        if actif_row:
            # Émoji de statut à côté du nom (🔥 brûlé, 💤 endormi...)
            statut_actif = database.obtenir_statut(combat_id, user_id, actif_nom)
            emoji_statut = f" {STATUTS_INFO[statut_actif[0]]['emoji']}" if statut_actif and statut_actif[0] in STATUTS_INFO else ""
            embed.title = f"{nom_affiche}{emoji_statut}"

            description = (
                f"{_barre_pv(actif_row['pv_actuels'], actif_row['pv_max'])}\n"
                f"❤️ **{actif_row['pv_actuels']} / {actif_row['pv_max']} PV**"
            )
            # Boosts de stats affichés s'ils sont non nuls (📊 Atq +1 • Déf Spé -2)
            boosts = database.obtenir_boosts(combat_id, user_id, actif_nom)
            morceaux_boosts = [
                f"{label} {boosts[stat]:+d}"
                for stat, label in (
                    ("atk", "Atq"), ("def", "Déf"), ("atk_spe", "Atq Spé"), ("def_spe", "Déf Spé"), ("vit", "Vit")
                )
                if boosts[stat] != 0
            ]
            if morceaux_boosts:
                description += f"\n📊 {' • '.join(morceaux_boosts)}"
            embed.description = description
        url_sprite = sprite_anime(pokemon)
        if url_sprite:
            embed.set_thumbnail(url=url_sprite)
        embed.add_field(name="Réserve", value=_bloc_reserve(equipe, actif_nom), inline=False)
        embeds.append(embed)

    dernier = discord.Embed(color=discord.Color.dark_grey())
    dernier.set_author(name=f"⚔️ Tour {combat['tour']}")
    if log_tour:
        # Limite Discord : 4096 caractères par description d'embed — un tour très bavard
        # (multi-K.O., pièges, statuts...) pouvait dépasser et faire échouer l'édition du
        # message (erreur 400), ce qui tuait la boucle de résolution. On tronque proprement.
        texte_log = "\n".join(log_tour)
        if len(texte_log) > 4000:
            texte_log = texte_log[:4000] + "\n… *(log du tour tronqué)*"
        dernier.description = texte_log
    temps_restant = max(0, combat["date_limite_tour"] - int(time.time()))
    dernier.set_footer(text=f"Tour résolu quand les deux joueurs ont joué, ou dans ~{temps_restant}s")
    embeds.append(dernier)

    return embeds


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

    noms = {joueur1.id: joueur1.display_name, joueur2.id: joueur2.display_name}
    embeds = construire_embeds_combat(combat_id, noms=noms)
    vue = VueActionCombat(combat_id, 1)

    msg = await thread.send(
        content=f"{joueur1.mention} {joueur2.mention} ⚔️ Le combat commence ! Choisissez votre action ci-dessous.",
        embeds=embeds,
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

    j1, j2 = combat["joueur1_id"], combat["joueur2_id"]
    a1 = combat["action1"] or f"attaque:{ATTAQUE_DEFAUT_NOM}"
    a2 = combat["action2"] or f"attaque:{ATTAQUE_DEFAUT_NOM}"

    log = []

    def infos_actif(user_id):
        cbt = database.obtenir_combat(combat_id)
        nom = cbt["actif1_nom"] if user_id == j1 else cbt["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        row = next((r for r in eq if r["pokemon_nom"] == nom), None)
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
            database.changer_pokemon_actif_pvp(combat_id, user_id, nouveau)
            log.append(f"<@{user_id}> rappelle **{ancien_nom}** et envoie **{nouveau}** !")
            _appliquer_hazards_entree(combat_id, user_id, nouveau, log)
            _declencher_talent_entree(combat_id, user_id, nouveau, j1 if user_id == j2 else j2, log)
            _declencher_meteo_entree(combat_id, user_id, nouveau, log)
            _declencher_fouille_entree(combat_id, user_id, nouveau, j1 if user_id == j2 else j2, log)

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
        vitesse = row["vit"] * mult_stage(boosts["vit"]) * capacites_module.multiplicateur_stat_objet(objet_vitesse, "vit")
        # Chlorophylle/Nage Rapide : Vitesse doublée sous la bonne météo.
        meteo_pour_vitesse = database.obtenir_meteo(combat_id)
        vitesse *= capacites_module.multiplicateur_vitesse_meteo(
            database.obtenir_capacite_combat(combat_id, user_id, nom),
            meteo_pour_vitesse["type"] if meteo_pour_vitesse else None,
        )
        statut_actuel = database.obtenir_statut(combat_id, user_id, nom)
        if statut_actuel and statut_actuel[0] == "paralysis":
            vitesse /= 2  # la paralysie ralentit

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

        # Priorité très basse (Mitra-Poing et consorts) : force ce Pokémon à agir en
        # dernier ce tour-ci, peu importe sa Vitesse réelle — comme la priorité -3 des
        # vrais jeux.
        vitesse_effective = vitesse - 1_000_000 if nom_attaque_demandee in ATTAQUES_PRIORITE_BASSE_ECHOUE_SI_TOUCHE else vitesse
        # Farceur : priorité +1 sur les attaques de statut (puissance absente/None).
        if nom_attaque_demandee and nom_attaque_demandee != NOM_LUTTE:
            attaque_pour_priorite = obtenir_attaque(nom_attaque_demandee)
            if (
                attaque_pour_priorite
                and not attaque_pour_priorite.get("puissance")
                and capacites_module.a_priorite_attaques_statut(database.obtenir_capacite_combat(combat_id, user_id, nom))
            ):
                vitesse_effective = vitesse + 1_000_000
        attaquants.append((vitesse_effective + random.random(), user_id, adversaire_id, nom_attaque_demandee))

    attaquants.sort(reverse=True)  # le plus rapide agit en premier
    switches_volontaires = {}  # user_id -> True si Relais (transfère les boosts), False sinon (Change Éclair/Demi-Tour)
    degats_subis_ce_tour = set()  # user_id ayant subi des dégâts d'une attaque adverse ce tour-ci
    flinch_ce_tour = set()  # user_id ayant flanché ce tour-ci — ne peut pas agir si son tour n'est pas encore passé

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
            log.append(f"😨 **{nom_atk}** a flanché et ne peut pas attaquer !")
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
            elif code_statut == "confusion":
                compteur = database.decrementer_compteur_statut(combat_id, user_id, nom_atk)
                if compteur <= 0:
                    database.retirer_statut(combat_id, user_id, nom_atk)
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
            statut_def_pour_esquive = database.obtenir_statut(combat_id, adversaire_id, nom_def)
            meteo_pour_esquive = database.obtenir_meteo(combat_id)
            bonus_esquive = capacites_module.bonus_esquive_defenseur(
                capacite_def_precision,
                meteo_pour_esquive["type"] if meteo_pour_esquive else None,
                bool(statut_def_pour_esquive and statut_def_pour_esquive[0] == "confusion"),
            )
            precision_effective *= (1 - bonus_esquive)
            if random.random() * 100 > precision_effective:
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

        if attaque.get("puissance"):
            # --- Attaque offensive ---
            pok_atk = formes_objets_module.pokemon_effectif(
                obtenir_pokemon_par_nom(nom_atk), database.obtenir_objet_combat(combat_id, user_id, nom_atk)
            )
            pok_def = formes_objets_module.pokemon_effectif(
                obtenir_pokemon_par_nom(nom_def), database.obtenir_objet_combat(combat_id, adversaire_id, nom_def)
            )
            types_atk_pokemon = pok_atk["types"] if pok_atk else ["normal"]
            types_def = pok_def["types"] if pok_def else ["normal"]

            if attaque["type"] is None:
                multi_type, stab = 1.0, 1.0  # Lutte : ni faiblesse/résistance, ni STAB
            else:
                multi_type = calculer_multiplicateur_type([attaque["type"]], types_def)
                stab = 1.5 if attaque["type"] in types_atk_pokemon else 1.0

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
            info_immunite = capacites_module.immunite_type(capacite_def, attaque["type"]) if attaque["type"] else None
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
            stat_off = row_atk["atq_spe"] if est_special else row_atk["atq"]
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
            cle_boost_def = "def_spe" if est_special else "def"
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
            stat_def_boostee = max(1, stat_def * mult_stage(stage_def_pour_degats))
            stat_off_boostee = max(1, stat_off * mult_stage(stage_off_pour_degats) * mult_stat_choix)
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

            capacite_def = database.obtenir_capacite_combat(combat_id, adversaire_id, nom_def)
            mult_talent_objet *= capacites_module.multiplicateur_degats_subis(capacite_def, multi_type)

            # Météo : Feu/Eau boostés ou affaiblis de 50% sous Soleil/Pluie (l'un renforce
            # son propre type et affaiblit l'opposé).
            mult_meteo = 1.0
            meteo_active = database.obtenir_meteo(combat_id)
            if meteo_active:
                if meteo_active["type"] == "soleil":
                    mult_meteo = 1.5 if attaque["type"] == "feu" else (0.5 if attaque["type"] == "eau" else 1.0)
                elif meteo_active["type"] == "pluie":
                    mult_meteo = 1.5 if attaque["type"] == "eau" else (0.5 if attaque["type"] == "feu" else 1.0)
            mult_meteo *= capacites_module.multiplicateur_types_meteo(
                capacite_atk, meteo_active["type"] if meteo_active else None, attaque["type"]
            )  # Force Sable

            mult_critique = capacites_module.multiplicateur_degats_critique(capacite_atk) if est_critique else 1.0
            degats = max(1, round(
                ((2 * row_atk["niveau"] / 5 + 2) * attaque["puissance"] * stat_off_boostee / stat_def_boostee / 50 + 2)
                * multi_type * stab * variance * bonus_badge * mult_talent_objet * mult_meteo * mult_critique
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
                        deja_confus = database.obtenir_statut(combat_id, user_id, nom_atk)
                        if not deja_confus:
                            database.definir_statut(combat_id, user_id, nom_atk, "confusion", random.randint(1, 4))
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
                    compteur = 0
                    if ailment == "sleep":
                        compteur = random.randint(1, 3)
                    elif ailment == "confusion":
                        compteur = random.randint(1, 4)
                    if database.definir_statut(combat_id, adversaire_id, nom_def, ailment, compteur):
                        info = STATUTS_INFO[ailment]
                        log.append(f"  {info['emoji']} **{nom_def}** est {info['nom']} !")
                        _verifier_baie_statut(combat_id, adversaire_id, nom_def, ailment, log)
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
                compteur = 0
                if ailment == "sleep":
                    compteur = random.randint(1, 3)
                elif ailment == "confusion":
                    compteur = random.randint(1, 4)
                if database.definir_statut(combat_id, cible_ailment_id, cible_ailment_nom, ailment, compteur):
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
            pourcent = DEGATS_BRULURE_POURCENT if code == "burn" else DEGATS_POISON_POURCENT
            degats_statut = max(1, round(actif_row["pv_max"] * pourcent))
            pv_apres = database.appliquer_degats_pvp(combat_id, user_id, nom_actif, degats_statut)
            info = STATUTS_INFO[code]
            log.append(f"{info['emoji']} **{nom_actif}** souffre de son statut ({info['nom']}) : -{degats_statut} PV")
            if pv_apres <= 0:
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

    journal.logger(f"🏳️ <@{perdant_id}> a abandonné son combat PvP contre <@{vainqueur_id}> (victoire par forfait).")

    embed = discord.Embed(
        title=f"🏳️ {nom_perdant} a abandonné !",
        description=(
            f"<@{vainqueur_id}> remporte le combat par forfait.\n\n"
            f"🎖️ +{dollars_reels} Poké Dollars & +{xp_reels} XP au vainqueur.{note_reduction}\n"
            f"+{xp_defaite_reelle} XP de consolation pour <@{perdant_id}>."
        ),
        color=discord.Color.orange(),
    )

    if combat["thread_id"]:
        try:
            thread = bot.get_channel(int(combat["thread_id"])) or await bot.fetch_channel(int(combat["thread_id"]))
            if thread:
                embeds_a_envoyer = [embed, embed_rival] if embed_rival else [embed]
                await thread.send(embeds=embeds_a_envoyer)
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
                    await msg.edit(embeds=embeds_a_envoyer, view=None)
                except discord.NotFound:
                    await thread.send(embed=embed)
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
        embeds = construire_embeds_combat(combat_id, log_tour=log, noms=noms)
        vue = VueActionCombat(combat_id, nouveau_tour, avec_choix_ko=bool(database.obtenir_choix_ko(combat_id)))
        try:
            msg = await thread.fetch_message(message_id)
            await msg.edit(embeds=embeds, view=vue)
        except discord.HTTPException:
            pass  # message disparu ou édition refusée : le prochain tick retentera
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
        await interaction.response.send_message("🏳️ Tu as abandonné. Défaite enregistrée.", ephemeral=True)
        await resoudre_abandon(interaction.client, self.combat_id, interaction.user.id)


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
