import asyncio
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import classement as classement_module
import raid as raid_module
import combat as combat_module
import echanges as echanges_module
import maitre_types as maitre_types_module
import exploration as exploration_module
import race_ui as race_ui_module
import races
import quetes as quetes_module
import quetes_ui as quetes_ui_module
import dresseurs as dresseurs_module
import elevage as elevage_module
import journal
import pnj
import database
import etat_jeu
import leveling
import meteo
import niveaux_pokemon
from pokemon_data import (
    ATTAQUES,
    EMOJI_BALLS,
    EMOJI_OBJETS_DIVERS,
    EMOJI_POKEDOLLAR,
    EMOJI_RARETE,
    EMOJI_SOINS,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
    POIDS_RARETE_CLASSIQUE,
    POIDS_RARETE_VIP,
    POKEDEX,
    generer_pc,
    obtenir_pokemon_par_nom,
    tirer_boss_raid_par_etoile,
    tirer_niveau_spawn,
    tirer_pokemon_aleatoire,
)
from boutique import construire_embed_boutique, VueBoutique
from profil import (
    construire_embed_fixe as construire_embed_profil_fixe,
    construire_embed_profil,
    construire_apercu_relacher,
    effectuer_relacher_tous,
    VueConfirmationRelacher,
    VueOuvrirPokedex,
    VueProfil,
)
import pokedex as pokedex_module
import equipe_combat as equipe_combat_module
from views import VueSpawn, construire_embed_spawn

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Diagnostic (/status-bot) : chaque boucle de fond met à jour son horodatage ici à
# chaque passage. Une boucle @tasks.loop qui a planté silencieusement (piège classique de
# discord.py) ou une boucle manuelle bloquée quelque part le montrera clairement — bien
# plus fiable que de se fier à is_running(), qui reste True même si le corps de la
# fonction plante en boucle sans jamais progresser.
DERNIERE_ACTIVITE_BOUCLES: dict[str, float] = {}


# ----------------------------------------------------------------------------
# PokéStop
# ----------------------------------------------------------------------------

def construire_embed_pokestop() -> discord.Embed:
    """Embed du message fixe du PokéStop, avec cooldown et récompenses possibles.
    Pendant l'Heure de pointe, les quantités/chances affichées reflètent le vrai
    multiplicateur en cours, pas les valeurs de base."""
    minutes_cooldown = config.COOLDOWN_POKESTOP // 60
    actif = etat_jeu.heure_de_pointe_pokestop_active
    mult = config.MULTIPLICATEUR_HEURE_DE_POINTE if actif else 1.0

    def plage(mini, maxi):
        return f"{round(mini * mult)}-{round(maxi * mult)}" if maxi > mini else f"{round(mini * mult)}"

    def pourcent(p):
        return f"{min(100, p * 100 * mult):g}%"

    embed = discord.Embed(
        title="🔵 PokéStop",
        description="Clique sur le bouton ci-dessous pour tourner le disque et obtenir une récompense !",
        color=discord.Color.gold() if actif else discord.Color.blue(),
    )
    if actif:
        debut_str = database.obtenir_parametre("pokestop_event_debut")
        tz = ZoneInfo("Europe/Paris")
        texte_horaire = ""
        if debut_str:
            debut_dt = datetime.fromtimestamp(int(debut_str), tz)
            fin_dt = debut_dt + timedelta(seconds=config.DUREE_HEURE_DE_POINTE_POKESTOP)
            texte_horaire = f"\nDémarrée à **{debut_dt.strftime('%Hh%M')}**, se termine à **{fin_dt.strftime('%Hh%M')}** (heure de Paris)."
        embed.add_field(
            name="🔥 Heure de pointe en cours !",
            value=f"Récompenses ×{mult:g} pendant 30 minutes.{texte_horaire}",
            inline=False,
        )
    embed.add_field(name="⏱️ Recharge", value=f"Toutes les {minutes_cooldown} minutes (par joueur)", inline=False)
    embed.add_field(
        name="🎁 Récompenses garanties",
        value=f"{EMOJI_POKEDOLLAR} {plage(20, 45)} Poké Dollars à chaque tirage",
        inline=False,
    )
    embed.add_field(
        name="✨ Bonus possible en plus (3 tirages indépendants)",
        value=(
            f"**Balls** — {EMOJI_BALLS['pokeball']} ×{plage(2, 5)} (55%) / "
            f"{EMOJI_BALLS['superball']} ×{plage(1, 3)} (30%) / "
            f"{EMOJI_BALLS['hyperball']} ×{plage(1, 3)} (10%) / "
            f"{EMOJI_BALLS['masterball']} ×1 (0,1%, rarissime !) / Rien (4,9%)\n"
            f"**Potions** — {EMOJI_SOINS['potion']} ×{plage(2, 5)} (50%) / "
            f"{EMOJI_SOINS['superpotion']} ×{plage(1, 3)} (28%) / "
            f"{EMOJI_SOINS['hyperpotion']} ×{plage(1, 1)} (10%) / "
            f"{EMOJI_SOINS['totalsoin']} ×{plage(1, 1)} (7%) / Rien (5%)\n"
            f"**Objet rare** — {EMOJI_OBJETS_DIVERS['cristal_mutation']} {NOM_OBJETS_DIVERS['cristal_mutation']} ×1 "
            f"({pourcent(config.CHANCE_CRISTAL_POKESTOP)})\n"
            f"**Œuf** — "
            + " / ".join(
                f"{EMOJI_OBJETS_DIVERS[f'oeuf_{p}']} {NOM_OBJETS_DIVERS[f'oeuf_{p}']} ({pourcent(poids)})"
                for p, poids in config.OEUF_POIDS_POKESTOP.items()
            )
        ),
        inline=False,
    )
    embed.set_footer(text="Reviens régulièrement pour ne jamais manquer de balls !")
    return embed


class VuePokestop(discord.ui.View):
    """Vue persistante attachée au message fixe du channel PokéStop."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Faire tourner le disque",
        style=discord.ButtonStyle.primary,
        emoji="🔵",
        custom_id="pokestop_bouton",  # nécessaire pour qu'un bouton persistant survive au redémarrage
    )
    async def tourner(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        peut_jouer, temps_restant = database.peut_utiliser_pokestop(user_id, config.COOLDOWN_POKESTOP)

        if not peut_jouer:
            minutes = temps_restant // 60
            secondes = temps_restant % 60
            embed_attente = discord.Embed(
                title="⏳ Disque pas encore rechargé",
                description=f"Reviens dans **{minutes}m {secondes}s** pour le retourner à nouveau.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed_attente, ephemeral=True)
            return

        database.marquer_pokestop_utilise(user_id)

        mult_pointe = config.MULTIPLICATEUR_HEURE_DE_POINTE if etat_jeu.heure_de_pointe_pokestop_active else 1.0

        # Poké Dollars garantis à chaque tirage
        montant_dollars = round(
            random.randint(20, 45) * database.multiplicateur_boost(user_id, "argent") * mult_pointe
        )
        database.ajouter_poke_dollars(user_id, montant_dollars)
        quetes_completees_pokestop = database.incrementer_progression_quete(user_id, "pokestop")

        # Deux tirages INDÉPENDANTS : un pour les balls, un pour les potions.
        # Chacun peut individuellement ne rien donner, peu importe l'autre.
        objets_actuels = database.compter_objets_totaux(user_id)
        limite_objets = database.limite_stockage_objets(user_id)
        place_disponible = limite_objets - objets_actuels

        texte_bonus_ball = None
        texte_bonus_potion = None
        texte_bonus_rare = None

        if place_disponible <= 0:
            texte_bonus_ball = "🎒 Ton sac est plein, pas de bonus objets cette fois !"
        else:
            # --- Tirage ball ---
            tirage_ball = random.random()
            if tirage_ball < 0.55:
                quantite = min(round(random.randint(2, 5) * mult_pointe), place_disponible)
                database.ajouter_balls(user_id, "pokeball", quantite)
                texte_bonus_ball = f"{EMOJI_BALLS['pokeball']} {quantite}× Poké Ball"
            elif tirage_ball < 0.85:
                quantite = min(round(random.randint(1, 3) * mult_pointe), place_disponible)
                database.ajouter_balls(user_id, "superball", quantite)
                texte_bonus_ball = f"{EMOJI_BALLS['superball']} {quantite}× Super Ball"
            elif tirage_ball < 0.95:
                quantite = min(round(random.randint(1, 3) * mult_pointe), place_disponible)
                database.ajouter_balls(user_id, "hyperball", quantite)
                texte_bonus_ball = f"{EMOJI_BALLS['hyperball']} {quantite}× Hyper Ball"
            elif tirage_ball < 0.951:  # 0,1% de chance, inchangé
                database.ajouter_balls(user_id, "masterball", 1)
                texte_bonus_ball = f"{EMOJI_BALLS['masterball']} 1× Master Ball ! Incroyable !"
            # sinon (4,9%) : pas de ball ce tirage-ci

            # --- Tirage potion (indépendant du tirage ball) — inclut désormais Total Soin ---
            objets_actuels_apres_ball = database.compter_objets_totaux(user_id)
            place_disponible_potion = limite_objets - objets_actuels_apres_ball

            if place_disponible_potion > 0:
                tirage_potion = random.random()
                seuil_potion = config.POTIONS_POIDS_POKESTOP["potion"]
                seuil_superpotion = seuil_potion + config.POTIONS_POIDS_POKESTOP["superpotion"]
                seuil_hyperpotion = seuil_superpotion + config.POTIONS_POIDS_POKESTOP["hyperpotion"]
                seuil_totalsoin = seuil_hyperpotion + config.POTIONS_POIDS_POKESTOP["totalsoin"]

                if tirage_potion < seuil_potion:
                    quantite = min(round(random.randint(2, 5) * mult_pointe), place_disponible_potion)
                    database.ajouter_balls(user_id, "potion", quantite)
                    texte_bonus_potion = f"{EMOJI_SOINS['potion']} {quantite}× Potion"
                elif tirage_potion < seuil_superpotion:
                    quantite = min(round(random.randint(1, 3) * mult_pointe), place_disponible_potion)
                    database.ajouter_balls(user_id, "superpotion", quantite)
                    texte_bonus_potion = f"{EMOJI_SOINS['superpotion']} {quantite}× Super Potion"
                elif tirage_potion < seuil_hyperpotion:
                    quantite = min(round(1 * mult_pointe), place_disponible_potion)
                    database.ajouter_balls(user_id, "hyperpotion", quantite)
                    texte_bonus_potion = f"{EMOJI_SOINS['hyperpotion']} {quantite}× Hyper Potion"
                elif tirage_potion < seuil_totalsoin:
                    quantite = min(round(1 * mult_pointe), place_disponible_potion)
                    database.ajouter_balls(user_id, "totalsoin", quantite)
                    texte_bonus_potion = f"{EMOJI_SOINS['totalsoin']} {quantite}× Total Soin"
                # sinon (5%) : pas de potion ce tirage-ci

            # --- Tirage Objet rare (indépendant) : Cristal de Mutation, petite chance ---
            objets_actuels_apres_potion = database.compter_objets_totaux(user_id)
            if objets_actuels_apres_potion < limite_objets and random.random() < min(1.0, config.CHANCE_CRISTAL_POKESTOP * mult_pointe):
                database.ajouter_balls(user_id, "cristal_mutation", 1)
                texte_bonus_rare = f"{EMOJI_OBJETS_DIVERS['cristal_mutation']} 1× {NOM_OBJETS_DIVERS['cristal_mutation']}"
            else:
                texte_bonus_rare = None

            # --- Tirage Œuf (indépendant) : palier tiré parmi OEUF_POIDS_POKESTOP,
            # Légendaire volontairement écrasé de rareté ---
            objets_actuels_apres_rare = database.compter_objets_totaux(user_id)
            texte_bonus_oeuf = None
            if objets_actuels_apres_rare < limite_objets:
                # Diviser le tirage par le multiplicateur resserre la plage vers le bas,
                # ce qui augmente la chance de tomber sous un des seuils — sans changer
                # la répartition relative entre paliers d'œuf.
                tirage_oeuf = random.random() / mult_pointe
                seuil = 0.0
                for palier, poids in config.OEUF_POIDS_POKESTOP.items():
                    seuil += poids
                    if tirage_oeuf < seuil:
                        database.ajouter_balls(user_id, f"oeuf_{palier}", 1)
                        texte_bonus_oeuf = f"{EMOJI_OBJETS_DIVERS[f'oeuf_{palier}']} 1× {NOM_OBJETS_DIVERS[f'oeuf_{palier}']}"
                        break
                # si tirage_oeuf >= somme des poids (91.5%) : pas d'œuf ce tirage-ci

        embed_resultat = discord.Embed(
            title="🎁 Résultat du disque",
            color=discord.Color.gold(),
        )
        if mult_pointe > 1.0:
            embed_resultat.add_field(
                name="🔥 Heure de pointe !", value=f"Récompenses ×{mult_pointe:g}", inline=False
            )
        embed_resultat.add_field(name="Poké Dollars", value=f"{EMOJI_POKEDOLLAR} +{montant_dollars}", inline=False)
        if texte_bonus_ball:
            embed_resultat.add_field(name="Bonus ball", value=texte_bonus_ball, inline=False)
        if texte_bonus_potion:
            embed_resultat.add_field(name="Bonus potion", value=texte_bonus_potion, inline=False)
        if texte_bonus_rare:
            embed_resultat.add_field(name="Bonus rare", value=texte_bonus_rare, inline=False)
        if texte_bonus_oeuf:
            embed_resultat.add_field(name="Bonus œuf", value=texte_bonus_oeuf, inline=False)

        niveau_avant, niveau_apres, recompenses_paliers = leveling.gagner_xp(user_id, config.XP_POKESTOP)
        embed_resultat.add_field(name="XP", value=f"✨ +{config.XP_POKESTOP}", inline=False)
        for palier, dollars, ball_type in recompenses_paliers:
            embed_resultat.add_field(
                name=f"🆙 Palier {palier} atteint (niveau {palier * 5}) !",
                value=(
                    f"+{dollars} {EMOJI_POKEDOLLAR} Poké Dollars, "
                    f"+1× {EMOJI_BALLS[ball_type]} {NOM_BALL_AFFICHAGE[ball_type]}"
                ),
                inline=False,
            )

        # XP du niveau PAR Pokémon : uniquement l'équipe de combat active (équipe vide =
        # perdue), indépendamment de l'XP de dresseur ci-dessus.
        montees_niveau_pokemon = niveaux_pokemon.gagner_xp_equipe(user_id, config.XP_POKEMON_POKESTOP)
        if montees_niveau_pokemon:
            embed_resultat.add_field(
                name="📈 Montée(s) de niveau (équipe)",
                value=niveaux_pokemon.texte_montees_niveau(montees_niveau_pokemon),
                inline=False,
            )

        minutes_cooldown = config.COOLDOWN_POKESTOP // 60
        embed_resultat.set_footer(text=f"Prochain tirage possible dans {minutes_cooldown} minutes")

        if quetes_completees_pokestop:
            embed_resultat.add_field(
                name="📜 Quête complétée !",
                value=quetes_ui_module.texte_notifications_completion(quetes_completees_pokestop).strip(),
                inline=False,
            )

        await interaction.response.send_message(embed=embed_resultat, ephemeral=True)


# ----------------------------------------------------------------------------
# Tâches de spawn
# ----------------------------------------------------------------------------

async def faire_disparaitre_apres_delai(message: discord.Message, vue: VueSpawn, delai: int, spawn_id: int):
    """Attend `delai` secondes, puis supprime le message du spawn s'il n'a pas déjà disparu."""
    await asyncio.sleep(delai)

    if vue.is_finished():
        database.retirer_spawn_actif(spawn_id)
        return  # la vue a déjà été arrêtée pour une autre raison

    vue.stop()

    try:
        await message.delete()
    except discord.NotFound:
        pass  # le message a déjà été supprimé entre-temps
    except discord.Forbidden:
        print("⚠️ Le bot n'a pas la permission de supprimer des messages dans ce channel.")
    finally:
        database.retirer_spawn_actif(spawn_id)


async def envoyer_spawn(
    channel_id: int,
    poids_rarete: dict,
    nom_channel: str = "",
    pokemon_force: dict = None,
    force_shiny: bool = False,
):
    channel = bot.get_channel(channel_id)
    if channel is None:
        print(
            f"⚠️ Channel de spawn '{nom_channel}' introuvable (ID={channel_id}). "
            f"Vérifie CHANNEL_SPAWN_{'VIP' if nom_channel == 'VIP' else 'CLASSIQUE'}_ID dans config.py."
        )
        return

    if pokemon_force is not None:
        pokemon = pokemon_force
    else:
        multiplicateurs_types = etat_jeu.obtenir_multiplicateurs_types()
        pokemon = tirer_pokemon_aleatoire(poids_rarete, multiplicateurs_types)

    pc = generer_pc(pokemon)
    niveau = tirer_niveau_spawn(pokemon["rarete"])

    embed = construire_embed_spawn(pokemon, pc, niveau, force_shiny=force_shiny)
    vue = VueSpawn(pokemon, pc, niveau, force_shiny=force_shiny)
    message = await channel.send(embed=embed, view=vue)

    # Suivi en base le temps que le spawn est affiché : sa vue n'étant pas persistante
    # d'un process à l'autre, un redémarrage du bot pendant qu'il est affiché le laisserait
    # sinon en place indéfiniment, avec un bouton Capturer mort — voir
    # nettoyer_etats_orphelins_au_demarrage().
    spawn_id = database.enregistrer_spawn_actif(channel_id, message.id)

    # Planifie la disparition automatique sans bloquer la boucle de spawn
    bot.loop.create_task(
        faire_disparaitre_apres_delai(message, vue, config.DUREE_AVANT_DISPARITION, spawn_id)
    )


@tasks.loop(seconds=config.INTERVALLE_SPAWN_CLASSIQUE)
async def boucle_spawn_classique():
    DERNIERE_ACTIVITE_BOUCLES["spawn_classique"] = time.time()
    try:
        await envoyer_spawn(config.CHANNEL_SPAWN_CLASSIQUE_ID, POIDS_RARETE_CLASSIQUE, "classique")
    except Exception as e:
        # Une exception non gérée ici arrêterait la boucle @tasks.loop DÉFINITIVEMENT
        # (piège classique de discord.py) — on log et on continue plutôt que de perdre
        # le spawn classique en silence jusqu'au prochain redémarrage du bot.
        print(f"⚠️ Erreur dans boucle_spawn_classique (spawn ignoré, la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_spawn_classique` : {e}")


@tasks.loop(seconds=config.INTERVALLE_SPAWN_VIP)
async def boucle_spawn_vip():
    DERNIERE_ACTIVITE_BOUCLES["spawn_vip"] = time.time()
    try:
        await envoyer_spawn(config.CHANNEL_SPAWN_VIP_ID, POIDS_RARETE_VIP, "VIP")
    except Exception as e:
        print(f"⚠️ Erreur dans boucle_spawn_vip (spawn ignoré, la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_spawn_vip` : {e}")


# ----------------------------------------------------------------------------
# Météo
# ----------------------------------------------------------------------------

async def annoncer_meteo(channel_id: int, texte: str, couleur: discord.Color):
    channel = bot.get_channel(channel_id)
    if channel is None:
        return None
    embed = discord.Embed(description=texte, color=couleur)
    return await channel.send(embed=embed)


async def _supprimer_message_apres_delai(message, delai: int):
    await asyncio.sleep(delai)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


# ----------------------------------------------------------------------------
# Classement
# ----------------------------------------------------------------------------

async def rafraichir_classement():
    """Poste le message de classement s'il n'existe pas, sinon le met à jour sur place."""
    channel = bot.get_channel(config.CHANNEL_CLASSEMENT_ID)
    if channel is None:
        print(
            "⚠️ CHANNEL_CLASSEMENT_ID introuvable — vérifie l'ID dans config.py. "
            "Le classement n'a pas pu être posté/mis à jour."
        )
        return

    await _verifier_changement_leader()

    embed = classement_module.construire_embed_apercu()
    vue = classement_module.VueClassements()
    message_id = database.obtenir_parametre("classement_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=vue)
            return
        except discord.NotFound:
            pass  # le message a été supprimé manuellement, on va en recréer un ci-dessous

    message = await channel.send(embed=embed, view=vue)
    database.definir_parametre("classement_message_id", str(message.id))


async def _verifier_changement_leader():
    """Compare le meneur actuel du classement des captures avec le dernier connu — si ça a
    changé, Gladio commente dans le channel de classement. Best-effort : n'importe quel
    souci ici ne doit jamais empêcher le classement lui-même de se rafraîchir."""
    try:
        top = database.classement_captures_individuelles(limite=1)
        if not top:
            return
        nouveau_leader_id = top[0]["user_id"]

        ancien_leader_id_str = database.obtenir_parametre("classement_leader_captures")
        database.definir_parametre("classement_leader_captures", str(nouveau_leader_id))

        if ancien_leader_id_str is None or int(ancien_leader_id_str) == nouveau_leader_id:
            return  # premier suivi, ou pas de changement — rien à commenter

        channel = bot.get_channel(config.CHANNEL_CLASSEMENT_ID)
        if channel is None:
            return
        embed_rival = pnj.construire_embed_reaction(
            "changement_leader_classement", user_id=nouveau_leader_id, joueur=f"<@{nouveau_leader_id}>"
        )
        if embed_rival:
            await channel.send(embed=embed_rival)
    except Exception as e:
        journal.logger(f"🔴 Erreur dans _verifier_changement_leader (non bloquant) : {e}")


@tasks.loop(seconds=config.INTERVALLE_CLASSEMENT)
async def boucle_classement():
    DERNIERE_ACTIVITE_BOUCLES["classement"] = time.time()
    try:
        await rafraichir_classement()
    except Exception as e:
        print(f"⚠️ Erreur dans boucle_classement (la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_classement` : {e}")


@tasks.loop(hours=24)
async def boucle_snapshot_economie():
    """Enregistre un instantané quotidien de la masse de Poké Dollars en circulation,
    pour repérer un futur déséquilibre économique tôt plutôt que par analyse manuelle."""
    DERNIERE_ACTIVITE_BOUCLES["snapshot_economie"] = time.time()
    try:
        database.enregistrer_snapshot_economie()
    except Exception as e:
        print(f"⚠️ Erreur dans boucle_snapshot_economie (la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_snapshot_economie` : {e}")


async def declencher_meteo(meteo_tiree: dict, duree_minutes: int = None):
    """Active une météo, l'annonce, puis programme son extinction. Utilisé aussi bien
    par le cycle automatique que par la commande admin /meteo-forcer."""
    etat_jeu.meteo_actuelle = meteo_tiree
    if duree_minutes is None:
        duree_minutes = random.randint(meteo_tiree["duree_min_minutes"], meteo_tiree["duree_max_minutes"])

    texte_debut = f"{meteo_tiree['emoji']} **{meteo_tiree['nom']}** ! "
    if meteo_tiree["multiplicateur_shiny"] > 1.0:
        texte_debut += "Chance de Pokémon shiny fortement augmentée "
    if meteo_tiree["types_boostes"]:
        types_str = ", ".join(meteo_tiree["types_boostes"].keys())
        texte_debut += f"— Pokémon de type {types_str} plus fréquents "
    texte_debut += f"pendant {duree_minutes} minutes !"

    messages_debut = []
    for channel_id in (config.CHANNEL_SPAWN_CLASSIQUE_ID, config.CHANNEL_SPAWN_VIP_ID):
        message = await annoncer_meteo(channel_id, texte_debut, discord.Color.blue())
        if message is not None:
            messages_debut.append(message)

    await asyncio.sleep(duree_minutes * 60)

    etat_jeu.meteo_actuelle = None
    for channel_id in (config.CHANNEL_SPAWN_CLASSIQUE_ID, config.CHANNEL_SPAWN_VIP_ID):
        message = await annoncer_meteo(
            channel_id, "☀️ Le temps redevient calme.", discord.Color.light_grey()
        )
        if message is not None:
            bot.loop.create_task(_supprimer_message_apres_delai(message, 5 * 60))
    # Les messages d'annonce du DÉBUT de la météo sont nettoyés en même temps que celui de
    # fin — sinon ils resteraient indéfiniment dans le channel, comme signalé.
    for message in messages_debut:
        bot.loop.create_task(_supprimer_message_apres_delai(message, 5 * 60))


async def boucle_meteo():
    """Alterne entre périodes neutres et événements météo, en continu."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        # Attente entre 30 et 60 minutes avant de vérifier si un événement se déclenche
        await asyncio.sleep(random.randint(30 * 60, 60 * 60))
        DERNIERE_ACTIVITE_BOUCLES["meteo"] = time.time()

        try:
            if random.random() >= meteo.PROBABILITE_DECLENCHEMENT:
                continue  # pas d'événement cette fois-ci, on continue d'attendre

            meteo_tiree = meteo.choisir_meteo_aleatoire()
            await declencher_meteo(meteo_tiree)
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_meteo (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_meteo` — voir les logs serveur pour le détail complet.")


async def boucle_evenement_pokestop():
    """Tire un créneau aléatoire de 30 min par jour (9h-23h, heure de Paris) pendant
    lequel le PokéStop donne de meilleures récompenses. Le créneau du jour est stocké en
    base (table parametres) pour survivre à un redémarrage du bot en plein milieu."""
    await bot.wait_until_ready()
    tz = ZoneInfo("Europe/Paris")

    while not bot.is_closed():
        await asyncio.sleep(60)
        DERNIERE_ACTIVITE_BOUCLES["evenement_pokestop"] = time.time()

        try:
            maintenant_dt = datetime.now(tz)
            aujourdhui = maintenant_dt.date().isoformat()

            date_programmee = database.obtenir_parametre("pokestop_event_date")
            debut_str = database.obtenir_parametre("pokestop_event_debut")

            if date_programmee != aujourdhui:
                # Nouveau jour : tirer un nouvel horaire aléatoire de départ, en
                # s'assurant que les 30 minutes tiennent avant la fin de la fenêtre.
                fin_fenetre_dt = maintenant_dt.replace(
                    hour=config.HEURE_FIN_FENETRE_POINTE, minute=0, second=0, microsecond=0
                )
                dernier_depart_possible = fin_fenetre_dt - timedelta(seconds=config.DUREE_HEURE_DE_POINTE_POKESTOP)
                minutes_fenetre = int((dernier_depart_possible.hour * 60 + dernier_depart_possible.minute) - config.HEURE_DEBUT_FENETRE_POINTE * 60)
                offset_minutes = random.randint(0, max(0, minutes_fenetre))
                debut_dt = maintenant_dt.replace(
                    hour=config.HEURE_DEBUT_FENETRE_POINTE, minute=0, second=0, microsecond=0
                ) + timedelta(minutes=offset_minutes)

                database.definir_parametre("pokestop_event_date", aujourdhui)
                database.definir_parametre("pokestop_event_debut", str(int(debut_dt.timestamp())))
                debut_str = str(int(debut_dt.timestamp()))
                print(f"🔥 Heure de pointe PokéStop programmée aujourd'hui à {debut_dt.strftime('%H:%M')} (heure de Paris).")

            debut_epoch = int(debut_str)
            fin_epoch = debut_epoch + config.DUREE_HEURE_DE_POINTE_POKESTOP
            maintenant_epoch = time.time()
            en_cours = debut_epoch <= maintenant_epoch < fin_epoch

            if en_cours and not etat_jeu.heure_de_pointe_pokestop_active:
                etat_jeu.heure_de_pointe_pokestop_active = True
                await poster_message_pokestop_si_absent()
                channel = bot.get_channel(config.CHANNEL_POKESTOP_ID) if getattr(config, "CHANNEL_POKESTOP_ID", None) else None
                if channel:
                    try:
                        await channel.send(
                            "🔥 **Heure de pointe au PokéStop !** Récompenses doublées pendant 30 minutes !"
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                journal.logger("🔥 Heure de pointe PokéStop activée pour 30 minutes.")
            elif not en_cours and etat_jeu.heure_de_pointe_pokestop_active:
                etat_jeu.heure_de_pointe_pokestop_active = False
                await poster_message_pokestop_si_absent()
                journal.logger("🔥 Heure de pointe PokéStop terminée.")
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_evenement_pokestop (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_evenement_pokestop` — voir les logs serveur pour le détail complet.")


async def boucle_gladio_spontane():
    """Petite chance, toutes les quelques heures, que Gladio balance une réflexion sur
    l'état général du serveur — pas liée à un événement précis, juste pour donner
    l'impression qu'il traîne dans le coin de temps en temps."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        await asyncio.sleep(random.randint(3 * 3600, 6 * 3600))
        DERNIERE_ACTIVITE_BOUCLES["gladio"] = time.time()

        try:
            if random.random() >= 0.25:
                continue  # rien cette fois-ci, on continue d'attendre

            channel_id = getattr(config, "CHANNEL_LOGS_ID", None) or config.CHANNEL_CLASSEMENT_ID
            channel = bot.get_channel(channel_id)
            if channel is None:
                continue
            embed_rival = pnj.construire_embed_reaction("spontane")
            if embed_rival:
                await channel.send(embed=embed_rival)
        except Exception as e:
            journal.logger(f"🔴 Erreur dans `boucle_gladio_spontane` (le cycle suivant sera quand même tenté) : {e}")


async def boucle_notifications_completion():
    """Prévient un joueur par MP dès que son Exploration ou son incubation d'Œuf est prête
    à récupérer — sans ça, il fallait rouvrir le menu concerné pour s'en rendre compte."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        await asyncio.sleep(30)
        DERNIERE_ACTIVITE_BOUCLES["notifications"] = time.time()

        try:
            for row in database.obtenir_explorations_a_notifier():
                utilisateur = bot.get_user(row["user_id"]) or await bot.fetch_user(row["user_id"])
                pokemons = ", ".join(p for p in (row["pokemon1"], row["pokemon2"], row["pokemon3"]) if p)
                try:
                    await utilisateur.send(
                        f"🎁 Ton exploration ({pokemons}) est terminée — reviens la récupérer "
                        f"quand tu veux, elle t'attend !"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass  # MP fermés ou joueur injoignable — on marque quand même comme notifié
                database.marquer_exploration_notifiee(row["user_id"], row["slot"])

            for row in database.obtenir_incubations_a_notifier():
                utilisateur = bot.get_user(row["user_id"]) or await bot.fetch_user(row["user_id"])
                nom_oeuf = NOM_OBJETS_DIVERS.get(f"oeuf_{row['palier']}", "Œuf")
                try:
                    await utilisateur.send(
                        f"🐣 Ton {nom_oeuf} est prêt à éclore — direction le "
                        f"Laboratoire quand tu veux !"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                database.marquer_incubation_notifiee(row["user_id"], row["slot"])
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_notifications_completion (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_notifications_completion` — voir les logs serveur pour le détail complet.")


# ----------------------------------------------------------------------------
# Raids
# ----------------------------------------------------------------------------

def _tirer_etoiles() -> int:
    paliers = list(config.POIDS_ETOILES_RAID.keys())
    poids = list(config.POIDS_ETOILES_RAID.values())
    return random.choices(paliers, weights=poids, k=1)[0]


async def demarrer_nouveau_raid(channel_id: int, etoiles: int = None, boss_force: dict = None):
    """Démarre un raid dans le channel donné, s'il n'y en a pas déjà un actif dedans.
    Passe d'abord par une salle d'attente avant que le combat ne démarre vraiment.
    Retourne True si démarré."""
    if database.obtenir_raid_actif_pour_channel(channel_id) is not None:
        return False  # un raid est déjà en cours dans ce channel

    channel = bot.get_channel(channel_id)
    if channel is None:
        print(f"⚠️ Channel introuvable (ID={channel_id}). Raid non démarré.")
        return False

    if boss_force is not None:
        boss = boss_force
        etoiles = config.ETOILES_PAR_RARETE.get(boss["rarete"], 1)
    else:
        etoiles = etoiles or _tirer_etoiles()
        boss = tirer_boss_raid_par_etoile(etoiles)

    try:
        pv_max_provisoire = config.PV_BASE_PAR_ETOILE.get(etoiles, 2000)  # recalculé selon le nombre de joueurs au démarrage du combat
        date_debut_combat = int(time.time()) + config.DUREE_SALLE_ATTENTE_RAID
        date_fin_provisoire = date_debut_combat + config.DUREE_RAID_MINUTES * 60

        raid_id = database.demarrer_raid(boss["nom"], etoiles, pv_max_provisoire, date_fin_provisoire, channel_id)

        embed = raid_module.construire_embed_salle_attente(boss, etoiles, date_debut_combat, 0)
        vue = raid_module.VueSalleAttente(raid_id, boss, etoiles, date_debut_combat)
        contenu_ping = "Un raid approche !"
        role_ping_id = getattr(config, "ROLE_PING_RAID_ID", None)
        if role_ping_id:
            contenu_ping = f"<@&{role_ping_id}> Un raid approche !"
        message = await channel.send(
            content=contenu_ping,
            embed=embed,
            view=vue,
            allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False),
        )
        database.definir_message_raid(raid_id, str(message.id))
    except Exception:
        import traceback

        print(f"⚠️ Erreur dans demarrer_nouveau_raid (channel_id={channel_id}) :")
        traceback.print_exc()
        journal.logger(f"🔴 Erreur dans `demarrer_nouveau_raid` (channel {channel_id}) — voir les logs serveur.")
        return False

    bot.loop.create_task(
        activer_combat_raid(raid_id, channel_id, message.id, boss, etoiles, config.DUREE_SALLE_ATTENTE_RAID)
    )
    return True


async def activer_combat_raid(raid_id: int, channel_id: int, message_id: int, boss: dict, etoiles: int, delai_secondes: int):
    """Bascule la salle d'attente vers le vrai combat une fois le délai écoulé. Les PV
    réels du boss sont calculés ICI, en fonction du nombre de joueurs présents dans le
    lobby — un raid avec 1 seul joueur reste soloable sur les petits paliers, mais
    devient un vrai défi collectif si beaucoup de monde s'est présenté."""
    await asyncio.sleep(delai_secondes)

    try:
        raid_row = database.obtenir_raid_par_id(raid_id)
        if raid_row is None or not raid_row["actif"]:
            return  # le raid a été annulé/terminé entre-temps

        nb_joueurs = len(database.obtenir_participants_raid(raid_id))

        if nb_joueurs == 0:
            # Personne n'a rejoint pendant la salle d'attente : le Pokémon s'enfuit
            # immédiatement, sans attendre inutilement la durée complète du raid.
            database.terminer_raid(raid_id)
            channel = bot.get_channel(channel_id)
            if channel is not None:
                try:
                    message = await channel.fetch_message(message_id)
                    embed = discord.Embed(
                        title=f"💨 {boss['nom']} s'est échappé...",
                        description="Personne n'a rejoint le raid à temps.",
                        color=discord.Color.dark_grey(),
                    )
                    await message.edit(embed=embed, view=None)
                    bot.loop.create_task(supprimer_message_apres_delai(message, 120))
                except discord.NotFound:
                    pass
            return

        pv_base = config.PV_BASE_PAR_ETOILE.get(etoiles, 2000)
        pv_max_reel = round(pv_base * (1 + (nb_joueurs - 1) * config.FACTEUR_PV_PAR_JOUEUR_SUPPLEMENTAIRE))
        database.redefinir_pv_max_raid(raid_id, pv_max_reel)

        date_fin_combat = int(time.time()) + config.DUREE_RAID_MINUTES * 60
        database.definir_date_fin_raid(raid_id, date_fin_combat)

        bot.loop.create_task(boucle_combat_raid(raid_id, channel_id, message_id, boss, etoiles))
        bot.loop.create_task(gerer_fin_de_raid(raid_id, channel_id, config.DUREE_RAID_MINUTES * 60))
    except Exception:
        import traceback

        print(f"⚠️ Erreur dans activer_combat_raid (raid_id={raid_id}) — le combat n'a pas pu démarrer :")
        traceback.print_exc()
        journal.logger(f"🔴 Erreur dans `activer_combat_raid` (raid {raid_id}) — le combat n'a pas démarré, voir les logs serveur.")


async def boucle_combat_raid(raid_id: int, channel_id: int, message_id: int, boss: dict, etoiles: int):
    """Toutes les quelques secondes, applique automatiquement les dégâts de TOUS les
    participants inscrits d'un coup — plus besoin de cliquer pour attaquer, et personne
    n'est exclu si le boss tombe pendant un tick puisque tout le monde est traité ensemble."""
    channel = bot.get_channel(channel_id)
    if channel is None:
        return

    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        return

    while True:
        await asyncio.sleep(config.INTERVALLE_TICK_COMBAT_RAID)

        try:
            raid_row = database.obtenir_raid_par_id(raid_id)
            if raid_row is None or not raid_row["actif"]:
                return  # terminé entre-temps (victoire ou timeout géré ailleurs)

            participants_inscrits = database.obtenir_participants_raid(raid_id)
            if not participants_inscrits:
                continue  # personne n'a encore rejoint, on attend le prochain tick

            degats_par_joueur = {
                row["user_id"]: raid_module.calculer_degats(row["user_id"]) for row in participants_inscrits
            }
            pv_restants = database.appliquer_degats_multiples(raid_id, degats_par_joueur)

            # Le boss riposte sur l'équipe de chaque participant engagé
            for row in participants_inscrits:
                raid_module.appliquer_riposte_boss(row["user_id"], etoiles)

            if pv_restants <= 0:
                participants = database.obtenir_participants_raid(raid_id)
                completions_par_joueur = raid_module.distribuer_recompenses_victoire(raid_id, etoiles)
                database.terminer_raid(raid_id)

                embeds_victoire = raid_module.construire_embed_victoire(boss, etoiles, participants, completions_par_joueur)
                vue_capture = raid_module.VueCaptureRaid(raid_id, boss, etoiles)
                try:
                    await message.edit(embeds=embeds_victoire, view=vue_capture)
                    bot.loop.create_task(
                        supprimer_message_apres_delai(message, config.DUREE_AFFICHAGE_VICTOIRE_RAID)
                    )
                except discord.NotFound:
                    pass
                return

            raid_row_maj = database.obtenir_raid_par_id(raid_id)
            embed = raid_module.construire_embed_raid(raid_row_maj, boss, len(participants_inscrits))
            vue = raid_module.VueRaidEnCombat(raid_id)
            try:
                await message.edit(embed=embed, view=vue)
            except discord.NotFound:
                return
        except Exception:
            import traceback

            print(f"⚠️ Erreur dans boucle_combat_raid (raid_id={raid_id}), tick suivant quand même tenté :")
            traceback.print_exc()
            journal.logger(f"🔴 Erreur dans `boucle_combat_raid` (raid {raid_id}) — voir les logs serveur.")
            continue


async def supprimer_message_apres_delai(message: discord.Message, delai_secondes: int):
    """Supprime un message après un délai, sans planter si déjà supprimé/manquant."""
    await asyncio.sleep(delai_secondes)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden):
        pass


async def gerer_fin_de_raid(raid_id: int, channel_id: int, delai_secondes: int):
    """Fait s'échapper le boss si le raid n'a pas été vaincu avant la fin du timer."""
    await asyncio.sleep(delai_secondes)

    raid_row = database.obtenir_raid_par_id(raid_id)
    if raid_row is None or not raid_row["actif"]:
        return  # déjà terminé (vaincu entre-temps)

    channel = bot.get_channel(channel_id)
    database.terminer_raid(raid_id)

    if channel is not None and raid_row["message_id"]:
        try:
            message = await channel.fetch_message(int(raid_row["message_id"]))
            embed = discord.Embed(
                title=f"💨 {raid_row['boss_nom']} s'est échappé...",
                description="Le temps est écoulé, personne n'a réussi à le vaincre à temps.",
                color=discord.Color.dark_grey(),
            )
            await message.edit(embed=embed, view=None)
            bot.loop.create_task(supprimer_message_apres_delai(message, 120))
        except discord.NotFound:
            pass


async def boucle_raid():
    """Vérifie chaque minute si un raid doit démarrer dans chaque channel de spawn.
    Un raid spawn dès que INTERVALLE_RAID s'est écoulé depuis le dernier spawn du channel
    ET qu'aucun raid n'y est actif — ainsi, un raid encore en cours ne décale plus le
    cycle de 15 minutes complètes, mais de quelques minutes au maximum."""
    await bot.wait_until_ready()

    # On initialise "dans le passé" plutôt qu'à l'instant présent : sinon, chaque redémarrage
    # du bot forçait une attente complète de INTERVALLE_RAID avant le premier raid possible,
    # même si le tout dernier spawn réel remontait à bien plus longtemps.
    maintenant = time.time()
    dernier_spawn = {
        config.CHANNEL_SPAWN_CLASSIQUE_ID: maintenant - config.INTERVALLE_RAID,
        config.CHANNEL_SPAWN_VIP_ID: maintenant - config.INTERVALLE_RAID,
    }

    while not bot.is_closed():
        await asyncio.sleep(60)
        DERNIERE_ACTIVITE_BOUCLES["raid"] = time.time()

        try:
            for channel_id in (config.CHANNEL_SPAWN_CLASSIQUE_ID, config.CHANNEL_SPAWN_VIP_ID):
                if time.time() - dernier_spawn.get(channel_id, 0) < config.INTERVALLE_RAID:
                    continue
                if await demarrer_nouveau_raid(channel_id):
                    dernier_spawn[channel_id] = time.time()
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_raid (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_raid` — voir les logs serveur pour le détail complet.")


async def demarrer_nouveau_dresseur(channel_id: int, ignorer_verification: bool = False, archetype_force: str | None = None) -> bool:
    """Fait apparaître un dresseur dans le channel donné, s'il n'y en a pas déjà un
    actif — sauf si ignorer_verification=True (utilisé par /force-dresseur pour pouvoir
    en empiler plusieurs en test, sans affecter le rythme du spawn automatique normal).
    archetype_force impose un archétype précis au lieu d'un tirage aléatoire.
    Retourne True si un dresseur a bien été posté."""
    if not channel_id:
        return False
    if not ignorer_verification and database.dresseur_actif_dans_channel(channel_id):
        return False  # déjà un dresseur en attente dans ce channel

    channel = bot.get_channel(channel_id)
    if channel is None:
        print("⚠️ CHANNEL_AVENTURE_ID introuvable — vérifie l'ID dans config.py.")
        return False

    archetype = dresseurs_module.choisir_archetype(archetype_force)
    date_expiration = int(time.time()) + config.DUREE_DISPONIBILITE_DRESSEUR
    dresseur_id = database.creer_dresseur_actif(archetype["nom"], channel_id, date_expiration)

    embed = dresseurs_module.construire_embed_spawn(archetype)
    vue = dresseurs_module.VueDefiDresseur(dresseur_id)
    message = await channel.send(embed=embed, view=vue)
    database.marquer_dresseur_message(dresseur_id, message.id)

    bot.loop.create_task(
        dresseurs_module.faire_partir_dresseur_si_non_defie(bot, dresseur_id, channel_id, config.DUREE_DISPONIBILITE_DRESSEUR)
    )
    return True


async def boucle_dresseurs():
    """Même principe que boucle_raid, mais pour le channel Aventure (un seul channel,
    dresseur plus rare pour limiter le farming solo)."""
    await bot.wait_until_ready()

    # Idem que boucle_raid : initialisé "dans le passé" pour ne pas forcer une attente
    # complète de INTERVALLE_DRESSEUR après chaque redémarrage du bot.
    dernier_spawn = time.time() - config.INTERVALLE_DRESSEUR

    while not bot.is_closed():
        await asyncio.sleep(60)
        DERNIERE_ACTIVITE_BOUCLES["dresseurs"] = time.time()

        channel_id = getattr(config, "CHANNEL_AVENTURE_ID", None)
        if not channel_id:
            continue

        try:
            if time.time() - dernier_spawn < config.INTERVALLE_DRESSEUR:
                continue
            if await demarrer_nouveau_dresseur(channel_id):
                dernier_spawn = time.time()
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_dresseurs (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_dresseurs` — voir les logs serveur pour le détail complet.")


# ----------------------------------------------------------------------------
# Événements
# ----------------------------------------------------------------------------

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Le bot est pensé pour un seul serveur — s'il est ajouté ailleurs (lien d'invitation
    qui a fuité, ajout par erreur...), il quitte automatiquement plutôt que de tourner à
    moitié cassé (spawns/salons introuvables) sur un serveur non prévu."""
    if config.GUILD_ID and guild.id != config.GUILD_ID:
        print(f"⚠️ Bot ajouté à un serveur non autorisé ({guild.name}, {guild.id}) — départ automatique.")
        journal.logger(f"🚪 Bot ajouté au serveur non autorisé **{guild.name}** ({guild.id}) — départ automatique.")
        try:
            await guild.leave()
        except discord.HTTPException:
            pass


async def _supprimer_message_orphelin(channel_id, message_id) -> bool:
    """Tente de supprimer un message laissé par un précédent redémarrage. Best-effort :
    toute erreur (channel/message introuvable, permissions...) est simplement ignorée."""
    try:
        channel = bot.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return False
    if channel is None:
        return False

    try:
        message = await channel.fetch_message(int(message_id))
        await message.delete()
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError, ValueError):
        return False


async def nettoyer_etats_orphelins_au_demarrage():
    """Supprime les messages de spawns/raids/dresseurs encore affichés d'avant un
    précédent redémarrage. Leurs vues ne sont pas persistantes d'un process à l'autre
    (VueSpawn, VueSalleAttente/VueRaid, VueDefiDresseur ont besoin d'un état précis en
    mémoire), donc leurs boutons ne fonctionnent plus de toute façon — sans ce nettoyage,
    il fallait les supprimer à la main après chaque redémarrage."""
    compte = 0

    for row in database.obtenir_spawns_actifs():
        if await _supprimer_message_orphelin(row["channel_id"], row["message_id"]):
            compte += 1
        database.retirer_spawn_actif(row["id"])

    for row in database.obtenir_raids_actifs():
        if row["message_id"] and await _supprimer_message_orphelin(row["channel_id"], row["message_id"]):
            compte += 1
        database.terminer_raid(row["id"])

    for row in database.obtenir_dresseurs_actifs_toutes():
        if row["message_id"] and await _supprimer_message_orphelin(row["channel_id"], row["message_id"]):
            compte += 1
        database.terminer_dresseur(row["id"])

    if compte:
        print(f"🧹 {compte} message(s) orphelin(s) (spawn/raid/dresseur) nettoyé(s) après redémarrage.")
        journal.logger(f"🧹 {compte} message(s) orphelin(s) nettoyé(s) après redémarrage.")


@bot.event
async def on_ready():
    database.init_db()
    await nettoyer_etats_orphelins_au_demarrage()
    bot.add_view(VuePokestop())  # réenregistre la vue persistante après un redémarrage
    bot.add_view(VueBoutique())  # idem pour la boutique
    bot.add_view(VueProfil())  # idem pour le profil
    bot.add_view(VueOuvrirPokedex())  # idem pour le bouton pokédex affiché sur le profil
    bot.add_view(maitre_types_module.VueMaitreTypes())  # idem pour le Maître des Types
    bot.add_view(exploration_module.VueCentreExploration())  # idem pour le Centre des Explorations
    bot.add_view(quetes_ui_module.VueCentreQuetes())  # idem pour les Quêtes
    bot.add_view(classement_module.VueClassements())  # idem pour les classements
    bot.add_view(elevage_module.VueLaboratoire())  # idem pour le Laboratoire
    # Note : VueRaid n'est plus enregistrée en persistante (elle a besoin d'un raid_id précis,
    # comme les spawns classiques un raid en cours au moment d'un redémarrage sera perdu)

    if config.GUILD_ID:
        # En développement : synchro uniquement sur le serveur de test (instantané,
        # évite les doublons qu'on aurait avec une synchro globale en parallèle)
        guild = discord.Object(id=config.GUILD_ID)

        # 1. On copie et synchronise d'abord sur le serveur, PENDANT que l'arbre
        #    de commandes globales contient encore toutes les commandes définies
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)

        # 2. Ensuite seulement, on nettoie les anciennes commandes globales côté Discord
        #    (celles qui causaient les doublons), sans toucher à ce qui vient d'être
        #    synchronisé sur le serveur
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
    else:
        # En production (bot sur plusieurs serveurs) : synchro globale classique
        await bot.tree.sync()

    if not boucle_spawn_classique.is_running():
        boucle_spawn_classique.start()
    if not boucle_spawn_vip.is_running():
        boucle_spawn_vip.start()

    if not getattr(bot, "boucle_meteo_lancee", False):
        bot.loop.create_task(boucle_meteo())
        bot.boucle_meteo_lancee = True

    if not getattr(bot, "boucle_evenement_pokestop_lancee", False):
        bot.loop.create_task(boucle_evenement_pokestop())
        bot.boucle_evenement_pokestop_lancee = True

    if not getattr(bot, "boucle_gladio_lancee", False):
        bot.loop.create_task(boucle_gladio_spontane())
        bot.boucle_gladio_lancee = True

    if not getattr(bot, "boucle_notifications_lancee", False):
        bot.loop.create_task(boucle_notifications_completion())
        bot.boucle_notifications_lancee = True

    if not getattr(bot, "boucle_logs_lancee", False) and config.CHANNEL_LOGS_ID:
        bot.loop.create_task(journal.boucle_envoi_logs(bot, config.CHANNEL_LOGS_ID, DERNIERE_ACTIVITE_BOUCLES))
        bot.boucle_logs_lancee = True

    if not getattr(bot, "boucle_raid_lancee", False):
        bot.loop.create_task(boucle_raid())
        bot.boucle_raid_lancee = True

    if not getattr(bot, "boucle_dresseurs_lancee", False):
        bot.loop.create_task(boucle_dresseurs())
        bot.boucle_dresseurs_lancee = True

    if not boucle_classement.is_running():
        boucle_classement.start()

    if not boucle_snapshot_economie.is_running():
        boucle_snapshot_economie.start()

    await poster_message_pokestop_si_absent()
    await poster_message_boutique_si_absent()
    await poster_message_maitre_types_si_absent()
    await poster_message_centre_exploration_si_absent()
    await poster_message_quetes_si_absent()
    await poster_message_profil_si_absent()
    await poster_message_laboratoire_si_absent()

    print(f"✅ Connecté en tant que {bot.user} — spawns et base de données prêts.")


@bot.event
async def on_message(message: discord.Message):
    """Modère les fils de combat publics : seuls les deux combattants (et le bot) ont
    le droit d'y écrire, pour permettre le visionnage sans polluer le déroulé du combat."""
    if message.author.bot:
        await bot.process_commands(message)
        return

    if isinstance(message.channel, discord.Thread):
        combat = database.obtenir_combat_par_thread(message.channel.id)
        if combat and message.author.id not in (combat["joueur1_id"], combat["joueur2_id"]):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

    await bot.process_commands(message)


async def poster_message_pokestop_si_absent():
    """Poste le message fixe du PokéStop, ou le met à jour s'il existe déjà
    (ainsi, toute amélioration du design s'applique automatiquement au redémarrage,
    sans jamais avoir besoin de retaper une commande)."""
    channel = bot.get_channel(config.CHANNEL_POKESTOP_ID)
    if channel is None:
        print(
            "⚠️ CHANNEL_POKESTOP_ID introuvable — vérifie l'ID dans config.py. "
            "Le message PokéStop n'a pas pu être posté automatiquement."
        )
        return

    embed = construire_embed_pokestop()
    message_id = database.obtenir_parametre("pokestop_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=VuePokestop())
            return
        except discord.NotFound:
            pass  # le message a été supprimé manuellement, on va en recréer un ci-dessous

    message = await channel.send(embed=embed, view=VuePokestop())
    database.definir_parametre("pokestop_message_id", str(message.id))


async def poster_message_boutique_si_absent():
    """Poste le message fixe de la boutique, ou le met à jour s'il existe déjà."""
    channel = bot.get_channel(config.CHANNEL_BOUTIQUE_ID)
    if channel is None:
        print(
            "⚠️ CHANNEL_BOUTIQUE_ID introuvable — vérifie l'ID dans config.py. "
            "Le message boutique n'a pas pu être posté automatiquement."
        )
        return

    embed = construire_embed_boutique()
    message_id = database.obtenir_parametre("boutique_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=VueBoutique())
            return
        except discord.NotFound:
            pass  # le message a été supprimé manuellement, on va en recréer un ci-dessous

    message = await channel.send(embed=embed, view=VueBoutique())
    database.definir_parametre("boutique_message_id", str(message.id))


async def poster_message_maitre_types_si_absent():
    """Poste le message fixe du Maître des Types (si le channel est configuré), ou le
    met à jour s'il existe déjà."""
    channel_id = getattr(config, "CHANNEL_MAITRE_TYPES_ID", None)
    if not channel_id:
        return  # channel non configuré : le Maître reste accessible via /maitre-types

    channel = bot.get_channel(channel_id)
    if channel is None:
        print("⚠️ CHANNEL_MAITRE_TYPES_ID introuvable — vérifie l'ID dans config.py.")
        return

    embed = maitre_types_module.construire_embed_maitre()
    message_id = database.obtenir_parametre("maitre_types_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=maitre_types_module.VueMaitreTypes())
            return
        except discord.NotFound:
            pass

    message = await channel.send(embed=embed, view=maitre_types_module.VueMaitreTypes())
    database.definir_parametre("maitre_types_message_id", str(message.id))


async def poster_message_centre_exploration_si_absent():
    """Poste le message fixe du Centre des Explorations (si le channel est configuré),
    ou le met à jour s'il existe déjà."""
    channel_id = getattr(config, "CHANNEL_EXPLORATION_ID", None)
    if not channel_id:
        return  # channel non configuré : reste accessible via /exploration

    channel = bot.get_channel(channel_id)
    if channel is None:
        print("⚠️ CHANNEL_EXPLORATION_ID introuvable — vérifie l'ID dans config.py.")
        return

    embed = exploration_module.construire_embed_centre()
    message_id = database.obtenir_parametre("exploration_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=exploration_module.VueCentreExploration())
            return
        except discord.NotFound:
            pass

    message = await channel.send(embed=embed, view=exploration_module.VueCentreExploration())
    database.definir_parametre("exploration_message_id", str(message.id))


async def poster_message_quetes_si_absent():
    """Poste le message fixe des Quêtes (si le channel est configuré), ou le met à jour
    s'il existe déjà."""
    channel_id = getattr(config, "CHANNEL_QUETES_ID", None)
    if not channel_id:
        return  # channel non configuré : reste accessible via /quetes

    channel = bot.get_channel(channel_id)
    if channel is None:
        print("⚠️ CHANNEL_QUETES_ID introuvable — vérifie l'ID dans config.py.")
        return

    embed = quetes_ui_module.construire_embed_centre()
    message_id = database.obtenir_parametre("quetes_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=quetes_ui_module.VueCentreQuetes())
            return
        except discord.NotFound:
            pass

    message = await channel.send(embed=embed, view=quetes_ui_module.VueCentreQuetes())
    database.definir_parametre("quetes_message_id", str(message.id))


async def poster_message_profil_si_absent():
    """Poste le message fixe du channel #profil, ou le met à jour s'il existe déjà."""
    channel = bot.get_channel(config.CHANNEL_PROFIL_ID)
    if channel is None:
        print(
            "⚠️ CHANNEL_PROFIL_ID introuvable — vérifie l'ID dans config.py. "
            "Le message profil n'a pas pu être posté automatiquement."
        )
        return

    embed = construire_embed_profil_fixe()
    message_id = database.obtenir_parametre("profil_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=VueProfil())
            return
        except discord.NotFound:
            pass  # le message a été supprimé manuellement, on va en recréer un ci-dessous

    message = await channel.send(embed=embed, view=VueProfil())
    database.definir_parametre("profil_message_id", str(message.id))


async def poster_message_laboratoire_si_absent():
    """Poste le message fixe du channel Laboratoire (Race + Incubateur), ou le met à
    jour s'il existe déjà."""
    channel = bot.get_channel(config.CHANNEL_LABORATOIRE_ID)
    if channel is None:
        print(
            "⚠️ CHANNEL_LABORATOIRE_ID introuvable — vérifie l'ID dans config.py. "
            "Le message Laboratoire n'a pas pu être posté automatiquement."
        )
        return

    embed = elevage_module.construire_embed_labo()
    message_id = database.obtenir_parametre("laboratoire_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=elevage_module.VueLaboratoire())
            return
        except discord.NotFound:
            pass  # le message a été supprimé manuellement, on va en recréer un ci-dessous

    message = await channel.send(embed=embed, view=elevage_module.VueLaboratoire())
    database.definir_parametre("laboratoire_message_id", str(message.id))


# ----------------------------------------------------------------------------
# Commandes
# ----------------------------------------------------------------------------

async def obtenir_ou_creer_role_equipe(guild: discord.Guild, nom_equipe: str) -> discord.Role:
    """Récupère le rôle Discord de l'équipe s'il existe, sinon le crée avec la bonne couleur."""
    role = discord.utils.get(guild.roles, name=nom_equipe)
    if role is None:
        role = await guild.create_role(
            name=nom_equipe,
            color=discord.Color(config.COULEURS_EQUIPES[nom_equipe]),
            mentionable=True,
            reason="Création automatique du rôle d'équipe",
        )
    return role


@bot.tree.command(name="equipe", description="Choisis ton clan (1 changement gratuit par semaine)")
@app_commands.choices(
    nom=[
        app_commands.Choice(name="Bleu", value="Bleu"),
        app_commands.Choice(name="Rouge", value="Rouge"),
        app_commands.Choice(name="Jaune", value="Jaune"),
    ]
)
async def equipe(interaction: discord.Interaction, nom: app_commands.Choice[str]):
    equipe_actuelle, peut_changer, secondes_restantes = database.obtenir_statut_equipe(interaction.user.id)

    if equipe_actuelle == nom.value:
        await interaction.response.send_message(
            f"Tu es déjà dans le clan **{nom.value}** !", ephemeral=True
        )
        return

    if not peut_changer:
        jours = secondes_restantes // 86400
        heures = (secondes_restantes % 86400) // 3600
        await interaction.response.send_message(
            f"⏳ Tu as déjà changé de clan récemment. Prochain changement gratuit possible "
            f"dans **{jours}j {heures}h**.",
            ephemeral=True,
        )
        return

    ancienne_equipe = equipe_actuelle
    database.changer_equipe(interaction.user.id, nom.value)

    verbe = "rejoint" if ancienne_equipe is None else "rejoint à nouveau"
    message = (
        f"🎉 Tu as {verbe} le clan {config.EMOJI_EQUIPES[nom.value]} **{nom.value}** ! "
        f"Prochain changement gratuit possible dans 7 jours."
    )

    if isinstance(interaction.user, discord.Member) and interaction.guild is not None:
        try:
            if ancienne_equipe is not None:
                ancien_role = discord.utils.get(interaction.guild.roles, name=ancienne_equipe)
                if ancien_role is not None:
                    await interaction.user.remove_roles(ancien_role, reason="Changement de clan")

            nouveau_role = await obtenir_ou_creer_role_equipe(interaction.guild, nom.value)
            await interaction.user.add_roles(nouveau_role, reason="Choix de clan")
        except discord.Forbidden:
            message += (
                "\n⚠️ Je n'ai pas la permission de gérer les rôles — demande à un admin de "
                "vérifier mes permissions (Gérer les rôles) et l'ordre des rôles sur le serveur."
            )

    await interaction.response.send_message(message)


@bot.tree.command(name="pokedex", description="Affiche ton Pokédex personnel")
@app_commands.choices(
    rarete=[
        app_commands.Choice(name="Toutes", value="toutes"),
        app_commands.Choice(name="Commun", value="commun"),
        app_commands.Choice(name="Peu commun", value="peu_commun"),
        app_commands.Choice(name="Rare", value="rare"),
        app_commands.Choice(name="Hyper Rare", value="hyper_rare"),
        app_commands.Choice(name="Légendaire", value="legendaire"),
    ],
    tri=[
        app_commands.Choice(name="Alphabétique", value="alphabetique"),
        app_commands.Choice(name="Ordre du Pokédex", value="numero"),
        app_commands.Choice(name="Rareté", value="rarete"),
    ],
    filtre_capture=[
        app_commands.Choice(name="Tous", value="tous"),
        app_commands.Choice(name="Non capturés", value="non_captures"),
        app_commands.Choice(name="Capturés", value="captures"),
    ],
)
@app_commands.describe(generation="Filtrer par génération (1 à 9)")
async def pokedex(
    interaction: discord.Interaction,
    rarete: app_commands.Choice[str] = None,
    tri: app_commands.Choice[str] = None,
    generation: app_commands.Range[int, 1, 9] = None,
    filtre_capture: app_commands.Choice[str] = None,
):
    filtre_rarete = None if (rarete is None or rarete.value == "toutes") else rarete.value
    valeur_tri = tri.value if tri else "alphabetique"
    valeur_filtre_capture = None if (filtre_capture is None or filtre_capture.value == "tous") else filtre_capture.value

    vue = pokedex_module.VuePokedex(
        interaction.user,
        filtre_rarete=filtre_rarete,
        filtre_generation=generation,
        tri=valeur_tri,
        filtre_capture=valeur_filtre_capture,
    )
    await interaction.response.send_message(embed=vue.construire_embed(), view=vue)


@bot.tree.command(name="pokedex-info", description="Affiche la fiche détaillée d'un Pokémon précis")
async def pokedex_info(interaction: discord.Interaction, nom: str):
    embed = pokedex_module.construire_embed_fiche(interaction.user.id, nom)
    if embed is None:
        await interaction.response.send_message(f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True)
        return
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="equipe-combat", description="Compose ton équipe de 6 Pokémon pour les futurs combats")
async def equipe_combat(interaction: discord.Interaction):
    embed = equipe_combat_module.construire_embed_equipe(interaction.user)
    vue = equipe_combat_module.VueEquipeCombat(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


@bot.tree.command(name="relacher", description="Relâche automatiquement tous tes doublons (garde le meilleur PC de chaque espèce)")
async def relacher(interaction: discord.Interaction):
    embed, y_a_quelque_chose = construire_apercu_relacher(interaction.user.id)
    if not y_a_quelque_chose:
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    vue = VueConfirmationRelacher(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


@bot.tree.command(name="profil", description="Affiche tes statistiques de dresseur")
async def profil(interaction: discord.Interaction):
    embed = construire_embed_profil(interaction.user)
    await interaction.response.send_message(embed=embed, view=VueOuvrirPokedex())


@bot.tree.command(name="setup-boutique", description="[Admin] Poste ou remet à jour le message fixe de la boutique dans ce channel")
@app_commands.checks.has_permissions(administrator=True)
async def setup_boutique(interaction: discord.Interaction):
    embed = construire_embed_boutique()
    await interaction.response.send_message(embed=embed, view=VueBoutique())


@bot.tree.command(name="setup-profil", description="[Admin] Poste ou remet à jour le message fixe du channel profil")
@app_commands.checks.has_permissions(administrator=True)
async def setup_profil(interaction: discord.Interaction):
    embed = construire_embed_profil_fixe()
    await interaction.response.send_message(embed=embed, view=VueProfil())


@bot.tree.command(name="classement", description="Affiche tous les classements du serveur")
async def classement(interaction: discord.Interaction):
    embed = classement_module.construire_embed_apercu()
    vue = classement_module.VueClassements()
    await interaction.response.send_message(embed=embed, view=vue)


@bot.tree.command(name="mon-classement", description="Affiche ta position personnelle dans les classements")
async def mon_classement(interaction: discord.Interaction):
    stats = database.obtenir_classement_personnel(interaction.user.id)
    total = stats["total_joueurs"]

    embed = discord.Embed(
        title=f"📊 Ton classement personnel",
        description=f"Parmi **{total}** joueurs enregistrés",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name=f"{EMOJI_POKEDOLLAR} Poké Dollars",
        value=f"**#{stats['rang_dollars']}** / {total} — {stats['valeur_dollars']} {EMOJI_POKEDOLLAR}",
        inline=False,
    )
    embed.add_field(
        name="🎯 Captures totales",
        value=f"**#{stats['rang_captures']}** / {total} — {stats['valeur_captures']} captures",
        inline=False,
    )
    total_especes = len(POKEDEX)
    pourcentage = stats["valeur_pokedex"] / total_especes if total_especes else 0
    embed.add_field(
        name="📖 Complétion du Pokédex",
        value=f"**#{stats['rang_pokedex']}** / {total} — {stats['valeur_pokedex']}/{total_especes} ({pourcentage:.0%})",
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setup-classement", description="[Admin] Force le rafraîchissement du message de classement")
@app_commands.checks.has_permissions(administrator=True)
async def setup_classement(interaction: discord.Interaction):
    await rafraichir_classement()
    await interaction.response.send_message("✅ Classement rafraîchi.", ephemeral=True)


@bot.tree.command(name="setup-pokestop", description="[Admin] Poste le message fixe du PokéStop dans ce channel")
@app_commands.checks.has_permissions(administrator=True)
async def setup_pokestop(interaction: discord.Interaction):
    embed = construire_embed_pokestop()
    await interaction.response.send_message(embed=embed, view=VuePokestop())


# ----------------------------------------------------------------------------
# Commandes admin
# ----------------------------------------------------------------------------

@bot.tree.command(name="give-objet", description="[Admin] Donne un objet (ball ou potion) à un joueur")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    objet=[
        app_commands.Choice(name="Poké Ball", value="pokeball"),
        app_commands.Choice(name="Super Ball", value="superball"),
        app_commands.Choice(name="Hyper Ball", value="hyperball"),
        app_commands.Choice(name="Master Ball", value="masterball"),
        app_commands.Choice(name="Potion", value="potion"),
        app_commands.Choice(name="Super Potion", value="superpotion"),
        app_commands.Choice(name="Hyper Potion", value="hyperpotion"),
        app_commands.Choice(name="Total Soin", value="totalsoin"),
        app_commands.Choice(name="Cristal de Mutation", value="cristal_mutation"),
        app_commands.Choice(name="Œuf Commun", value="oeuf_commun"),
        app_commands.Choice(name="Œuf Peu Commun", value="oeuf_peu_commun"),
        app_commands.Choice(name="Œuf Rare", value="oeuf_rare"),
        app_commands.Choice(name="Œuf Hyper Rare", value="oeuf_hyper_rare"),
        app_commands.Choice(name="Œuf Légendaire", value="oeuf_legendaire"),
    ]
)
async def give_objet(
    interaction: discord.Interaction,
    membre: discord.Member,
    objet: app_commands.Choice[str],
    quantite: int,
):
    noms_objets = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
    emojis_objets = {**EMOJI_BALLS, **EMOJI_SOINS, **EMOJI_OBJETS_DIVERS}
    database.ajouter_balls(membre.id, objet.value, quantite)
    journal.logger(f"🛠️ <@{interaction.user.id}> a donné {quantite}× {objet.value} à <@{membre.id}> (/give-objet).")
    await interaction.response.send_message(
        f"✅ **{quantite}× {emojis_objets.get(objet.value, '')} {noms_objets.get(objet.value, objet.value)}** donné(es) à {membre.mention}."
    )


@bot.tree.command(name="give-dollars", description="[Admin] Donne des Poké Dollars à un joueur")
@app_commands.checks.has_permissions(administrator=True)
async def give_dollars(interaction: discord.Interaction, membre: discord.Member, montant: int):
    database.ajouter_poke_dollars(membre.id, montant)
    journal.logger(f"🛠️ <@{interaction.user.id}> a donné {montant} PD à <@{membre.id}> (/give-dollars).")
    await interaction.response.send_message(f"✅ **{montant} {EMOJI_POKEDOLLAR} Poké Dollars** donnés à {membre.mention}.")


@bot.tree.command(name="give-xp", description="[Admin] Donne de l'XP à un joueur")
@app_commands.checks.has_permissions(administrator=True)
async def give_xp(interaction: discord.Interaction, membre: discord.Member, montant: int):
    niveau_avant, niveau_apres, recompenses_paliers = leveling.gagner_xp(membre.id, montant)
    journal.logger(f"🛠️ <@{interaction.user.id}> a donné {montant} XP à <@{membre.id}> (/give-xp).")
    texte = f"✅ **{montant} XP** donnés à {membre.mention}."
    if niveau_apres > niveau_avant:
        texte += f" (niveau {niveau_avant} → {niveau_apres})"
    await interaction.response.send_message(texte)


@bot.tree.command(
    name="backfill-niveaux",
    description="[Admin] Attribue un niveau (grille de rareté) aux Pokémon capturés avant le système de niveau",
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    forcer="Écrase aussi le niveau des Pokémon qui en ont déjà un (nouveau tirage aléatoire). Par défaut, seuls ceux sans niveau sont touchés."
)
async def backfill_niveaux(interaction: discord.Interaction, forcer: bool = False):
    await interaction.response.defer()

    paires = database.obtenir_toutes_paires_capturees() if forcer else database.obtenir_paires_sans_niveau()
    compte = 0
    for user_id, nom in paires:
        pokemon = obtenir_pokemon_par_nom(nom)
        if not pokemon:
            continue
        niveau = tirer_niveau_spawn(pokemon["rarete"])
        database.definir_niveau_xp_pokemon(user_id, nom, niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau))
        compte += 1

    journal.logger(
        f"🛠️ <@{interaction.user.id}> a lancé /backfill-niveaux"
        f"{' --forcer' if forcer else ''} : {compte} Pokémon mis à jour."
    )
    if forcer:
        await interaction.followup.send(
            f"✅ **{compte}** Pokémon (espèce × joueur) ont reçu un nouveau niveau aléatoire "
            f"selon la grille de rareté — y compris ceux qui en avaient déjà un (XP remise à "
            f"zéro pour ce nouveau niveau)."
        )
    else:
        await interaction.followup.send(
            f"✅ Niveau attribué (selon la grille de spawn par rareté) à **{compte}** Pokémon "
            f"(espèce × joueur) qui n'en avaient pas encore. Sans effet sur ceux qui ont déjà "
            f"un niveau — relançable sans risque."
        )


@bot.tree.command(name="give-ct", description="[Admin] Donne la CT d'une attaque à un joueur (possédée pour toujours)")
@app_commands.checks.has_permissions(administrator=True)
async def give_ct(interaction: discord.Interaction, membre: discord.Member, attaque: str):
    if attaque not in ATTAQUES:
        await interaction.response.send_message(f"❌ Attaque **{attaque}** introuvable.", ephemeral=True)
        return

    if database.possede_ct(membre.id, attaque):
        await interaction.response.send_message(
            f"{membre.mention} possède déjà la CT de **{attaque}**.", ephemeral=True
        )
        return

    database.acheter_ct(membre.id, attaque)
    journal.logger(f"🛠️ <@{interaction.user.id}> a donné la CT de {attaque} à <@{membre.id}> (/give-ct).")
    await interaction.response.send_message(f"✅ CT **{attaque}** donnée à {membre.mention} — utilisable pour toujours.")


@bot.tree.command(
    name="force-pokestop-dore",
    description="[Admin] Déclenche immédiatement l'Heure de pointe PokéStop pour 30 minutes",
)
@app_commands.checks.has_permissions(administrator=True)
async def force_pokestop_dore(interaction: discord.Interaction):
    tz = ZoneInfo("Europe/Paris")
    maintenant_dt = datetime.now(tz)
    database.definir_parametre("pokestop_event_date", maintenant_dt.date().isoformat())
    database.definir_parametre("pokestop_event_debut", str(int(maintenant_dt.timestamp())))
    etat_jeu.heure_de_pointe_pokestop_active = True
    await poster_message_pokestop_si_absent()

    journal.logger(f"🛠️ <@{interaction.user.id}> a déclenché l'Heure de pointe PokéStop manuellement (/force-pokestop-dore).")
    await interaction.response.send_message("🔥 **Heure de pointe PokéStop** déclenchée pour 30 minutes !")

    channel = bot.get_channel(config.CHANNEL_POKESTOP_ID) if getattr(config, "CHANNEL_POKESTOP_ID", None) else None
    if channel and channel.id != interaction.channel_id:
        try:
            await channel.send("🔥 **Heure de pointe au PokéStop !** Récompenses doublées pendant 30 minutes !")
        except (discord.Forbidden, discord.HTTPException):
            pass


@bot.tree.command(
    name="stop-pokestop-dore",
    description="[Admin] Coupe l'Heure de pointe PokéStop en cours, sans en reprogrammer une autre aujourd'hui",
)
@app_commands.checks.has_permissions(administrator=True)
async def stop_pokestop_dore(interaction: discord.Interaction):
    if not etat_jeu.heure_de_pointe_pokestop_active:
        await interaction.response.send_message("Il n'y a pas d'Heure de pointe en cours.", ephemeral=True)
        return

    # On pousse le créneau enregistré dans le passé (fin < maintenant) sans toucher à la
    # date du jour : la boucle voit "déjà fini" au prochain passage et ne retire PAS un
    # nouveau créneau aléatoire pour le reste de la journée.
    tz = ZoneInfo("Europe/Paris")
    maintenant_dt = datetime.now(tz)
    debut_dans_le_passe = maintenant_dt - timedelta(seconds=config.DUREE_HEURE_DE_POINTE_POKESTOP + 60)
    database.definir_parametre("pokestop_event_date", maintenant_dt.date().isoformat())
    database.definir_parametre("pokestop_event_debut", str(int(debut_dans_le_passe.timestamp())))

    etat_jeu.heure_de_pointe_pokestop_active = False
    await poster_message_pokestop_si_absent()

    journal.logger(f"🛠️ <@{interaction.user.id}> a coupé l'Heure de pointe PokéStop manuellement (/stop-pokestop-dore).")
    await interaction.response.send_message("🛑 **Heure de pointe PokéStop** coupée.")


# ----------------------------------------------------------------------------
# Codes promo
# ----------------------------------------------------------------------------

OBJETS_CODE_CHOICES = [
    app_commands.Choice(name="Poké Ball", value="pokeball"),
    app_commands.Choice(name="Super Ball", value="superball"),
    app_commands.Choice(name="Hyper Ball", value="hyperball"),
    app_commands.Choice(name="Master Ball", value="masterball"),
    app_commands.Choice(name="Potion", value="potion"),
    app_commands.Choice(name="Super Potion", value="superpotion"),
    app_commands.Choice(name="Hyper Potion", value="hyperpotion"),
    app_commands.Choice(name="Total Soin", value="totalsoin"),
    app_commands.Choice(name="Cristal de Mutation", value="cristal_mutation"),
    app_commands.Choice(name="Œuf Commun", value="oeuf_commun"),
    app_commands.Choice(name="Œuf Peu Commun", value="oeuf_peu_commun"),
    app_commands.Choice(name="Œuf Rare", value="oeuf_rare"),
    app_commands.Choice(name="Œuf Hyper Rare", value="oeuf_hyper_rare"),
    app_commands.Choice(name="Œuf Légendaire", value="oeuf_legendaire"),
]


@bot.tree.command(name="creer-code", description="[Admin] Crée un code promo à distribuer aux joueurs")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(objet=OBJETS_CODE_CHOICES)
@app_commands.describe(
    code="Le code que les joueurs devront taper (insensible à la casse)",
    dollars="Poké Dollars offerts (0 si aucun)",
    xp="XP offerte (0 si aucune)",
    objet="Objet offert en plus (optionnel)",
    quantite_objet="Quantité de l'objet ci-dessus (ignoré si aucun objet choisi)",
    max_utilisations="Nombre max de joueurs pouvant l'utiliser (laisse vide = illimité)",
    duree_jours="Le code expire après ce nombre de jours (laisse vide = jamais)",
)
async def creer_code(
    interaction: discord.Interaction,
    code: str,
    dollars: int = 0,
    xp: int = 0,
    objet: app_commands.Choice[str] | None = None,
    quantite_objet: int = 0,
    max_utilisations: int | None = None,
    duree_jours: int | None = None,
):
    if dollars <= 0 and xp <= 0 and (objet is None or quantite_objet <= 0):
        await interaction.response.send_message(
            "❌ Il faut au moins une récompense (Poké Dollars, XP, ou un objet avec une quantité > 0).",
            ephemeral=True,
        )
        return

    date_expiration = int(time.time()) + duree_jours * 86400 if duree_jours else None
    succes = database.creer_code_promo(
        code, dollars, xp,
        objet.value if objet else None, quantite_objet,
        max_utilisations, date_expiration, interaction.user.id,
    )
    if not succes:
        await interaction.response.send_message(
            f"❌ Le code **{code.strip().upper()}** existe déjà.", ephemeral=True
        )
        return

    recap = []
    if dollars > 0:
        recap.append(f"{dollars} {EMOJI_POKEDOLLAR} Poké Dollars")
    if xp > 0:
        recap.append(f"{xp} XP")
    if objet and quantite_objet > 0:
        noms_objets = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
        recap.append(f"{quantite_objet}× {noms_objets.get(objet.value, objet.value)}")

    texte = f"✅ Code **{code.strip().upper()}** créé — donne : {', '.join(recap)}."
    texte += f"\nLimite d'utilisations : {max_utilisations if max_utilisations else 'illimitée'}."
    texte += f"\nExpiration : {'jamais' if not duree_jours else f'dans {duree_jours} jour(s)'}."
    journal.logger(f"🛠️ <@{interaction.user.id}> a créé le code promo **{code.strip().upper()}** ({', '.join(recap)}).")
    await interaction.response.send_message(texte, ephemeral=True)


@bot.tree.command(name="desactiver-code", description="[Admin] Désactive un code promo avant son expiration")
@app_commands.checks.has_permissions(administrator=True)
async def desactiver_code(interaction: discord.Interaction, code: str):
    succes = database.desactiver_code_promo(code)
    if succes:
        journal.logger(f"🛠️ <@{interaction.user.id}> a désactivé le code promo **{code.strip().upper()}**.")
        await interaction.response.send_message(f"✅ Code **{code.strip().upper()}** désactivé.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Le code **{code.strip().upper()}** n'existe pas.", ephemeral=True)


@bot.tree.command(name="liste-codes", description="[Admin] Liste tous les codes promo créés")
@app_commands.checks.has_permissions(administrator=True)
async def liste_codes(interaction: discord.Interaction):
    codes = database.lister_codes_promo()
    if not codes:
        await interaction.response.send_message("Aucun code promo créé pour l'instant.", ephemeral=True)
        return

    noms_objets = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
    maintenant = int(time.time())
    lignes = []
    for c in codes[:25]:
        recap = []
        if c["dollars"] > 0:
            recap.append(f"{c['dollars']} PD")
        if c["xp"] > 0:
            recap.append(f"{c['xp']} XP")
        if c["objet"] and c["quantite_objet"] > 0:
            recap.append(f"{c['quantite_objet']}× {noms_objets.get(c['objet'], c['objet'])}")

        if not c["actif"]:
            statut = "🔴 désactivé"
        elif c["date_expiration"] and c["date_expiration"] < maintenant:
            statut = "⏳ expiré"
        elif c["max_utilisations"] and c["utilisations_actuelles"] >= c["max_utilisations"]:
            statut = "🔴 épuisé"
        else:
            statut = "🟢 actif"

        limite = f"{c['utilisations_actuelles']}/{c['max_utilisations']}" if c["max_utilisations"] else f"{c['utilisations_actuelles']}/∞"
        lignes.append(f"**{c['code']}** {statut} — {', '.join(recap)} — {limite} utilisations")

    embed = discord.Embed(title="🎟️ Codes promo", description="\n".join(lignes), color=discord.Color.blurple())
    if len(codes) > 25:
        embed.set_footer(text=f"25 plus récents affichés sur {len(codes)} au total.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="code", description="Utilise un code promo pour recevoir une récompense")
async def utiliser_code(interaction: discord.Interaction, code: str):
    succes, resultat = database.utiliser_code_promo(code, interaction.user.id)
    if not succes:
        await interaction.response.send_message(f"❌ {resultat}", ephemeral=True)
        return

    ligne = resultat
    recap = []
    if ligne["dollars"] > 0:
        dollars_reels = round(ligne["dollars"] * database.multiplicateur_boost(interaction.user.id, "argent"))
        database.ajouter_poke_dollars(interaction.user.id, dollars_reels)
        recap.append(f"{dollars_reels} {EMOJI_POKEDOLLAR} Poké Dollars")
    if ligne["xp"] > 0:
        leveling.gagner_xp(interaction.user.id, ligne["xp"])
        xp_affichee = round(ligne["xp"] * database.multiplicateur_boost(interaction.user.id, "xp"))
        recap.append(f"{xp_affichee} XP")
    if ligne["objet"] and ligne["quantite_objet"] > 0:
        database.ajouter_balls(interaction.user.id, ligne["objet"], ligne["quantite_objet"])
        noms_objets = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
        recap.append(f"{ligne['quantite_objet']}× {noms_objets.get(ligne['objet'], ligne['objet'])}")

    journal.logger(f"🎟️ <@{interaction.user.id}> a utilisé le code **{ligne['code']}** ({', '.join(recap)}).")
    await interaction.response.send_message(
        f"🎉 Code **{ligne['code']}** utilisé avec succès ! Tu as reçu : {', '.join(recap)}.",
        ephemeral=True,
    )


@bot.tree.command(name="give-boost", description="[Admin] Offre un boost temporaire gratuit à un joueur")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    type_boost=[
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="Argent", value="argent"),
        app_commands.Choice(name="Shiny", value="shiny"),
    ],
    duree=[
        app_commands.Choice(name="1h", value="1h"),
        app_commands.Choice(name="6h", value="6h"),
        app_commands.Choice(name="24h", value="24h"),
    ],
)
async def give_boost(
    interaction: discord.Interaction,
    membre: discord.Member,
    type_boost: app_commands.Choice[str],
    duree: app_commands.Choice[str],
):
    duree_secondes = config.DUREES_BOOST[duree.value]
    expiration = database.activer_boost(membre.id, type_boost.value, duree_secondes)
    journal.logger(f"🛠️ <@{interaction.user.id}> a offert un boost {type_boost.value} ({duree.value}) à <@{membre.id}>.")
    await interaction.response.send_message(
        f"✅ Boost **{type_boost.name} ({duree.name})** offert à {membre.mention} — expire <t:{expiration}:R>."
    )


@bot.tree.command(name="reset-pokestop", description="[Admin] Réinitialise le cooldown PokéStop d'un joueur")
@app_commands.checks.has_permissions(administrator=True)
async def reset_pokestop(interaction: discord.Interaction, membre: discord.Member):
    database.reinitialiser_pokestop(membre.id)
    await interaction.response.send_message(
        f"✅ Cooldown PokéStop réinitialisé pour {membre.mention}.", ephemeral=True
    )


@bot.tree.command(name="status-bot", description="[Admin] État des boucles de fond et des combats/dresseurs/raids en cours")
@app_commands.checks.has_permissions(administrator=True)
async def status_bot(interaction: discord.Interaction):
    maintenant = time.time()

    def _ligne_boucle(nom_affiche: str, cle: str, intervalle_attendu: int) -> str:
        derniere = DERNIERE_ACTIVITE_BOUCLES.get(cle)
        if derniere is None:
            return f"❓ **{nom_affiche}** — aucune activité enregistrée depuis le démarrage"
        ecart = int(maintenant - derniere)
        # Marge x3 sur l'intervalle attendu avant de considérer que ça sent le blocage —
        # une boucle peut légitimement sauter un tour (spawn ignoré, attente longue, etc.)
        if ecart > intervalle_attendu * 3:
            statut = "🔴 possiblement bloquée"
        elif ecart > intervalle_attendu * 1.5:
            statut = "🟡 en retard"
        else:
            statut = "🟢 OK"
        minutes = ecart // 60
        secondes = ecart % 60
        return f"{statut} **{nom_affiche}** — dernière activité il y a {minutes}m {secondes}s"

    lignes_boucles = [
        _ligne_boucle("Spawn classique", "spawn_classique", config.INTERVALLE_SPAWN_CLASSIQUE),
        _ligne_boucle("Spawn VIP", "spawn_vip", config.INTERVALLE_SPAWN_VIP),
        _ligne_boucle("Raids", "raid", 60),
        _ligne_boucle("Dresseurs", "dresseurs", 60),
        _ligne_boucle("Classement", "classement", config.INTERVALLE_CLASSEMENT),
        _ligne_boucle("Météo", "meteo", 30 * 60),
        _ligne_boucle("Gladio (spontané)", "gladio", 3 * 3600),
        _ligne_boucle("Notifications MP", "notifications", 30),
        _ligne_boucle("Envoi des logs", "logs", 5),
        _ligne_boucle("Snapshot économie", "snapshot_economie", 24 * 3600),
    ]

    compteurs = database.obtenir_compteurs_activite()

    embed = discord.Embed(title="🩺 État du bot", color=discord.Color.blurple())
    embed.add_field(name="Boucles de fond", value="\n".join(lignes_boucles), inline=False)
    embed.add_field(
        name="En cours actuellement",
        value=(
            f"⚔️ Combats actifs (PvP + dresseurs) : {compteurs['combats_actifs']}\n"
            f"🧑‍🏫 Dresseurs actifs : {compteurs['dresseurs_actifs']}\n"
            f"👹 Raids actifs : {compteurs['raids_actifs']}"
        ),
        inline=False,
    )
    embed.add_field(name="📶 Latence Discord", value=f"{round(bot.latency * 1000)} ms", inline=False)
    embed.set_footer(text="Les boucles @tasks.loop dont l'activité n'avance plus ont probablement planté silencieusement — un redémarrage du bot les relance.")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stats-economie", description="[Admin] Vue d'ensemble de la masse de Poké Dollars en circulation")
@app_commands.checks.has_permissions(administrator=True)
async def stats_economie(interaction: discord.Interaction):
    nb_joueurs, total_pd, moyenne_pd = database.obtenir_stats_economie_actuelles()
    historique = database.obtenir_historique_economie(14)  # jusqu'à 14 derniers instantanés (14 jours)

    embed = discord.Embed(title="📊 Économie du serveur", color=discord.Color.blurple())
    embed.add_field(name="👥 Joueurs actifs", value=str(nb_joueurs), inline=True)
    embed.add_field(name=f"{EMOJI_POKEDOLLAR} Total en circulation", value=f"{total_pd:,}".replace(",", " "), inline=True)
    embed.add_field(name="📈 Moyenne / joueur", value=f"{moyenne_pd:,.0f}".replace(",", " "), inline=True)

    if len(historique) >= 2:
        plus_recent = historique[0]
        plus_ancien = historique[-1]
        variation = plus_recent["total_pd"] - plus_ancien["total_pd"]
        jours_ecart = max(1, (plus_recent["date"] - plus_ancien["date"]) // 86400)
        pourcentage = (variation / plus_ancien["total_pd"] * 100) if plus_ancien["total_pd"] else 0
        fleche = "📈" if variation > 0 else ("📉" if variation < 0 else "➡️")
        embed.add_field(
            name=f"{fleche} Tendance (sur {jours_ecart}j, {len(historique)} instantanés)",
            value=f"{'+' if variation >= 0 else ''}{variation:,} PD ({pourcentage:+.1f}%)".replace(",", " "),
            inline=False,
        )
    else:
        embed.add_field(
            name="📈 Tendance",
            value="Pas encore assez d'instantanés (1 par jour) pour calculer une tendance.",
            inline=False,
        )

    embed.set_footer(text="Instantané enregistré automatiquement une fois par jour")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="voir-joueur", description="[Admin] Fiche de diagnostic complète d'un joueur")
@app_commands.checks.has_permissions(administrator=True)
async def voir_joueur(interaction: discord.Interaction, membre: discord.Member):
    dollars = database.obtenir_poke_dollars(membre.id)
    xp_totale = database.obtenir_xp(membre.id)
    niveau, xp_dans_niveau, xp_requise = leveling.progression_niveau(xp_totale)
    barre_xp = leveling.barre_progression(xp_dans_niveau, xp_requise)
    captures = database.obtenir_pokedex_joueur(membre.id)
    nb_especes = len({row["pokemon_nom"] for row in captures})
    nb_total = sum(row["quantite"] for row in captures)
    equipe = database.obtenir_equipe_combat(membre.id)
    combat_actif = database.combat_en_cours_pour_joueur(membre.id)
    boosts_actifs = database.obtenir_tous_boosts_actifs(membre.id)
    race_nom, pity = database.obtenir_race(membre.id)
    explorations = database.obtenir_explorations_actives(membre.id)
    titre_categorie = database.obtenir_titre_actif(membre.id)
    titre_txt = None
    if titre_categorie:
        valeurs = quetes_ui_module.valeurs_accomplissements(membre.id)
        palier = quetes_module.palier_atteint(titre_categorie, valeurs[titre_categorie])
        titre_txt = quetes_module.titre_complet(titre_categorie, palier)

    embed = discord.Embed(
        title=f"🔍 {membre.display_name}",
        description=(
            (f"🏅 *{titre_txt}*\n" if titre_txt else "")
            + f"**Niveau {niveau}**\n{barre_xp} `{xp_dans_niveau}/{xp_requise} XP` (total : {xp_totale})"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=membre.display_avatar.url)

    embed.add_field(name="Poké Dollars", value=f"{EMOJI_POKEDOLLAR} {dollars}", inline=True)
    embed.add_field(name="📖 Pokédex", value=f"{nb_especes} espèces • {nb_total} captures", inline=True)
    embed.add_field(name="⚔️ Équipe de combat", value=", ".join(equipe) if equipe else "*Non configurée*", inline=False)

    if race_nom:
        race = races.obtenir_race_par_nom(race_nom)
        embed.add_field(
            name="🧬 Race",
            value=f"{EMOJI_RARETE[race['palier']]} **{race['nom']}** — {races.texte_bonus(race['bonus'])}\n*Pity : {pity}/{config.PITY_SEUIL}*",
            inline=False,
        )
    else:
        embed.add_field(name="🧬 Race", value=f"*Aucune — Pity : {pity}/{config.PITY_SEUIL}*", inline=False)

    if explorations:
        maintenant = int(__import__("time").time())
        lignes = []
        for row in explorations:
            statut = "✅ prête" if row["date_fin"] <= maintenant else f"⏳ <t:{row['date_fin']}:R>"
            lignes.append(f"Emplacement {row['slot']} : {row['pokemon1']}, {row['pokemon2']}, {row['pokemon3']} — {statut}")
        embed.add_field(name="🗺️ Explorations en cours", value="\n".join(lignes), inline=False)

    combat_txt = "Aucun"
    if combat_actif:
        adversaire_id = combat_actif["joueur2_id"] if combat_actif["joueur1_id"] == membre.id else combat_actif["joueur1_id"]
        combat_txt = f"En cours (id {combat_actif['id']}) contre <@{adversaire_id}>"
    embed.add_field(name="🥊 Combat PvP", value=combat_txt, inline=True)

    boosts_txt = (
        "\n".join(f"• {type_b} — <t:{exp}:R>" for type_b, exp in boosts_actifs.items())
        if boosts_actifs else "Aucun"
    )
    embed.add_field(name="🚀 Boost temporaire", value=boosts_txt, inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="reset-joueur", description="[Admin] Réinitialise complètement le profil d'un joueur (irréversible)")
@app_commands.checks.has_permissions(administrator=True)
async def reset_joueur(interaction: discord.Interaction, membre: discord.Member, confirmation: str):
    if confirmation != membre.name:
        await interaction.response.send_message(
            f"❌ Confirmation invalide. Pour réinitialiser {membre.mention}, "
            f"tape exactement son nom d'utilisateur (`{membre.name}`) dans le paramètre `confirmation`.",
            ephemeral=True,
        )
        return

    database.reinitialiser_joueur(membre.id)
    await interaction.response.send_message(
        f"✅ Profil de {membre.mention} entièrement réinitialisé (PD, XP, captures, inventaire, équipe, boosts).",
        ephemeral=True,
    )


@bot.tree.command(name="annuler-raid", description="[Admin] Force l'annulation du raid actif dans un channel (débloque un raid fantôme)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    channel=[
        app_commands.Choice(name="Classique", value="classique"),
        app_commands.Choice(name="VIP", value="vip"),
    ]
)
async def annuler_raid(interaction: discord.Interaction, channel: app_commands.Choice[str]):
    channel_id = (
        config.CHANNEL_SPAWN_CLASSIQUE_ID if channel.value == "classique" else config.CHANNEL_SPAWN_VIP_ID
    )
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE raid_actuel SET actif = 0 WHERE channel_id = ? AND actif = 1",
        (str(channel_id),),
    )
    nb_annules = cur.rowcount
    conn.commit()
    conn.close()

    if nb_annules > 0:
        await interaction.response.send_message(
            f"✅ Raid annulé dans le channel **{channel.name}**. Un nouveau pourra démarrer normalement.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ Aucun raid actif trouvé dans le channel **{channel.name}**.", ephemeral=True
        )


@bot.tree.command(name="annuler-combat", description="[Admin] Force la fin du combat PvP en cours d'un joueur (débloque un combat fantôme)")
@app_commands.checks.has_permissions(administrator=True)
async def annuler_combat(interaction: discord.Interaction, membre: discord.Member):
    combat = database.combat_en_cours_pour_joueur(membre.id)
    if combat is None:
        await interaction.response.send_message(
            f"ℹ️ {membre.mention} n'a aucun combat en cours.", ephemeral=True
        )
        return

    database.terminer_combat_pvp(combat["id"])

    if combat["thread_id"]:
        try:
            thread = bot.get_channel(int(combat["thread_id"]))
            if thread:
                await thread.send("🛑 Ce combat a été annulé par un administrateur.")
        except Exception:
            pass

    await interaction.response.send_message(
        f"✅ Combat annulé (aucun vainqueur, aucune récompense distribuée). "
        f"<@{combat['joueur1_id']}> et <@{combat['joueur2_id']}> peuvent relancer un défi.",
        ephemeral=True,
    )


@bot.tree.command(name="ping-raid", description="Active ou désactive les notifications de raid pour toi")
async def ping_raid_toggle(interaction: discord.Interaction):
    role_id = getattr(config, "ROLE_PING_RAID_ID", None)
    if not role_id:
        await interaction.response.send_message(
            "⚠️ Le rôle de ping raid n'a pas encore été configuré par un admin.", ephemeral=True
        )
        return

    role = interaction.guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message(
            "⚠️ Le rôle configuré (ROLE_PING_RAID_ID) est introuvable sur ce serveur.", ephemeral=True
        )
        return

    if role in interaction.user.roles:
        await interaction.user.remove_roles(role)
        await interaction.response.send_message(
            "🔕 Tu ne recevras plus les notifications de raid.", ephemeral=True
        )
    else:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(
            "🔔 Tu recevras désormais un ping à chaque nouveau raid !", ephemeral=True
        )


@bot.tree.command(name="defier", description="Défie un autre joueur en combat Pokémon")
async def defier(interaction: discord.Interaction, adversaire: discord.Member):
    if adversaire.bot or adversaire.id == interaction.user.id:
        await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
        return

    if database.combat_en_cours_pour_joueur(interaction.user.id):
        await interaction.response.send_message("❌ Tu as déjà un combat en cours !", ephemeral=True)
        return

    if database.combat_en_cours_pour_joueur(adversaire.id):
        await interaction.response.send_message(f"❌ {adversaire.mention} a déjà un combat en cours !", ephemeral=True)
        return

    equipe_challenger = combat_module.preparer_equipe_pour_combat(interaction.user.id)
    if not equipe_challenger:
        await interaction.response.send_message("❌ Configure ton équipe de combat d'abord (`/equipe-combat`) !", ephemeral=True)
        return

    vue_defi = VueDefi(interaction.user, adversaire)
    await interaction.response.send_message(
        f"⚔️ {adversaire.mention}, **{interaction.user.display_name}** te défie en combat ! Tu as 60 secondes pour accepter.",
        view=vue_defi,
    )
    vue_defi.message = await interaction.original_response()


@bot.tree.command(name="echanger", description="Propose un échange de Pokémon et/ou Poké Dollars à un autre joueur")
async def echanger(interaction: discord.Interaction, membre: discord.Member):
    if membre.bot or membre.id == interaction.user.id:
        await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
        return

    if database.echange_en_cours_pour_joueur(interaction.user.id):
        await interaction.response.send_message("❌ Tu as déjà un échange en cours !", ephemeral=True)
        return

    if database.echange_en_cours_pour_joueur(membre.id):
        await interaction.response.send_message(f"❌ {membre.mention} a déjà un échange en cours !", ephemeral=True)
        return

    vue_proposition = VueEchangeProposition(interaction.user, membre)
    await interaction.response.send_message(
        f"🔄 {membre.mention}, **{interaction.user.display_name}** te propose un échange ! Tu as 60 secondes pour accepter.",
        view=vue_proposition,
    )
    vue_proposition.message = await interaction.original_response()


@bot.tree.command(name="maitre-types", description="Rends visite au Maître des Types pour gérer les attaques de tes Pokémon")
async def maitre_types_cmd(interaction: discord.Interaction):
    embed = maitre_types_module.construire_embed_maitre()
    vue = maitre_types_module.VueMaitreTypes()
    await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


@bot.tree.command(name="exploration", description="Ouvre le Centre des Explorations pour gérer tes équipes en exploration")
async def exploration_cmd(interaction: discord.Interaction):
    embed, vue = exploration_module.construire_tableau_de_bord(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


@bot.tree.command(name="quetes", description="Affiche tes quêtes journalières, hebdomadaires et tes accomplissements")
async def quetes_cmd(interaction: discord.Interaction):
    embed, vue = quetes_ui_module.construire_tableau_de_bord(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


@bot.tree.command(name="setup-quetes", description="[Admin] Poste ou remet à jour le message fixe des Quêtes dans ce channel")
@app_commands.checks.has_permissions(administrator=True)
async def setup_quetes(interaction: discord.Interaction):
    embed = quetes_ui_module.construire_embed_centre()
    message = await interaction.channel.send(embed=embed, view=quetes_ui_module.VueCentreQuetes())
    database.definir_parametre("quetes_message_id", str(message.id))
    await interaction.response.send_message("✅ Quêtes postées dans ce channel.", ephemeral=True)


@bot.tree.command(name="finir-exploration", description="[Admin] Termine immédiatement l'exploration d'un joueur (sans réduire la récompense)")
@app_commands.checks.has_permissions(administrator=True)
async def finir_exploration(interaction: discord.Interaction, membre: discord.Member, emplacement: int = 1):
    succes = database.forcer_fin_exploration(membre.id, emplacement)
    if not succes:
        await interaction.response.send_message(
            f"ℹ️ {membre.mention} n'a aucune exploration en cours sur l'emplacement {emplacement}.",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        f"✅ Exploration de {membre.mention} (emplacement {emplacement}) terminée immédiatement — "
        f"la récompense reste calculée sur la durée d'origine. Le joueur peut la récupérer via `/exploration`.",
        ephemeral=True,
    )


@bot.tree.command(name="finir-incubation", description="[Admin] Fait éclore immédiatement l'œuf en incubation d'un joueur")
@app_commands.checks.has_permissions(administrator=True)
async def finir_incubation(interaction: discord.Interaction, membre: discord.Member):
    succes = database.forcer_fin_incubation(membre.id)
    if not succes:
        await interaction.response.send_message(
            f"ℹ️ {membre.mention} n'a aucun œuf en incubation actuellement.",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        f"✅ L'œuf de {membre.mention} est prêt à éclore immédiatement — "
        f"le joueur peut le récupérer via le Laboratoire.",
        ephemeral=True,
    )


@bot.tree.command(name="ma-race", description="Affiche ta Race de dresseur et utilise tes Cristaux de Mutation")
async def ma_race_cmd(interaction: discord.Interaction):
    embed = race_ui_module.construire_embed_race(interaction.user.id)
    vue = race_ui_module.VueRace(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


@bot.tree.command(name="setup-centre-exploration", description="[Admin] Poste ou remet à jour le message fixe du Centre des Explorations dans ce channel")
@app_commands.checks.has_permissions(administrator=True)
async def setup_centre_exploration(interaction: discord.Interaction):
    embed = exploration_module.construire_embed_centre()
    message = await interaction.channel.send(embed=embed, view=exploration_module.VueCentreExploration())
    database.definir_parametre("exploration_message_id", str(message.id))
    await interaction.response.send_message("✅ Centre des Explorations posté dans ce channel.", ephemeral=True)


@bot.tree.command(name="abandonner-combat", description="Abandonne ton combat en cours (défaite par forfait)")
async def abandonner_combat(interaction: discord.Interaction):
    combat = database.combat_en_cours_pour_joueur(interaction.user.id)
    if not combat:
        await interaction.response.send_message("Tu n'as pas de combat en cours.", ephemeral=True)
        return
    await interaction.response.send_message("🏳️ Tu as abandonné. Défaite enregistrée.", ephemeral=True)
    await combat_module.resoudre_abandon(bot, combat["id"], interaction.user.id)


@bot.tree.command(name="force-dresseur", description="[Admin] Fait apparaître un dresseur immédiatement dans le channel Aventure")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    archetype=[
        app_commands.Choice(name=a["nom"], value=a["nom"]) for a in dresseurs_module.ARCHETYPES
    ]
)
async def force_dresseur(interaction: discord.Interaction, archetype: app_commands.Choice[str] | None = None):
    channel_id = getattr(config, "CHANNEL_AVENTURE_ID", None)
    if not channel_id:
        await interaction.response.send_message("❌ CHANNEL_AVENTURE_ID n'est pas configuré.", ephemeral=True)
        return
    succes = await demarrer_nouveau_dresseur(
        channel_id, ignorer_verification=True, archetype_force=archetype.value if archetype else None
    )
    await interaction.response.send_message(
        "✅ Dresseur envoyé !" if succes else "❌ Impossible d'envoyer le dresseur (channel introuvable).", ephemeral=True
    )


@bot.tree.command(name="force-raid", description="[Admin] Démarre un raid immédiatement")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    channel=[
        app_commands.Choice(name="Classique", value="classique"),
        app_commands.Choice(name="VIP", value="vip"),
    ]
)
async def force_raid(
    interaction: discord.Interaction,
    channel: app_commands.Choice[str],
    etoiles: app_commands.Range[int, 1, 5] = None,
    nom: str = None,
):
    boss_force = None
    if nom:
        boss_force = obtenir_pokemon_par_nom(nom)
        if not boss_force:
            await interaction.response.send_message(f"❌ Pokémon **{nom}** introuvable.", ephemeral=True)
            return

    channel_id = (
        config.CHANNEL_SPAWN_CLASSIQUE_ID if channel.value == "classique" else config.CHANNEL_SPAWN_VIP_ID
    )

    succes = await demarrer_nouveau_raid(channel_id, etoiles=etoiles, boss_force=boss_force)
    if succes:
        await interaction.response.send_message(f"✅ Raid démarré dans le channel **{channel.name}** !", ephemeral=True)
    else:
        await interaction.response.send_message(
            "⚠️ Impossible : un raid est déjà en cours dans ce channel, ou le channel est introuvable.",
            ephemeral=True,
        )


@bot.tree.command(name="give-pokemon", description="[Admin] Donne un Pokémon directement à un joueur")
@app_commands.checks.has_permissions(administrator=True)
async def give_pokemon(
    interaction: discord.Interaction,
    membre: discord.Member,
    nom: str,
    pc: int = None,
    shiny: bool = False,
):
    pokemon = obtenir_pokemon_par_nom(nom)
    if not pokemon:
        await interaction.response.send_message(
            f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True
        )
        return

    if pc is not None:
        pc = max(1, min(pc, config.PC_MAXIMUM))
    else:
        pc = generer_pc(pokemon)

    database.ajouter_capture(membre.id, pokemon["nom"], pc, shiny=shiny)
    prefixe = "✨ " if shiny else ""
    journal.logger(f"🛠️ <@{interaction.user.id}> a donné {prefixe}**{pokemon['nom']}** ({pc} PC) à <@{membre.id}> (/give-pokemon).")
    await interaction.response.send_message(
        f"✅ {prefixe}**{pokemon['nom']}** ({pc} PC) donné à {membre.mention}."
    )


@bot.tree.command(
    name="force-spawn-shiny",
    description="[Admin] Fait apparaître un Pokémon shiny garanti dans un channel de spawn",
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    channel=[
        app_commands.Choice(name="Classique", value="classique"),
        app_commands.Choice(name="VIP", value="vip"),
    ]
)
async def force_spawn_shiny(
    interaction: discord.Interaction,
    channel: app_commands.Choice[str],
    nom: str = None,
):
    if nom:
        pokemon = obtenir_pokemon_par_nom(nom)
        if not pokemon:
            await interaction.response.send_message(
                f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True
            )
            return
    else:
        pokemon = None  # tirage aléatoire classique dans envoyer_spawn

    if channel.value == "classique":
        channel_id, poids, nom_channel = config.CHANNEL_SPAWN_CLASSIQUE_ID, POIDS_RARETE_CLASSIQUE, "classique"
    else:
        channel_id, poids, nom_channel = config.CHANNEL_SPAWN_VIP_ID, POIDS_RARETE_VIP, "VIP"

    await envoyer_spawn(channel_id, poids, nom_channel, pokemon_force=pokemon, force_shiny=True)
    await interaction.response.send_message(
        f"✨ Spawn shiny garanti envoyé dans le channel **{channel.name}** !", ephemeral=True
    )


@bot.tree.command(
    name="force-spawn",
    description="[Admin] Fait apparaître un Pokémon (aléatoire ou précis, non-shiny) dans un channel de spawn",
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    channel=[
        app_commands.Choice(name="Classique", value="classique"),
        app_commands.Choice(name="VIP", value="vip"),
    ]
)
async def force_spawn(
    interaction: discord.Interaction,
    channel: app_commands.Choice[str],
    nom: str = None,
):
    if nom:
        pokemon = obtenir_pokemon_par_nom(nom)
        if not pokemon:
            await interaction.response.send_message(
                f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True
            )
            return
    else:
        pokemon = None  # tirage aléatoire classique dans envoyer_spawn

    if channel.value == "classique":
        channel_id, poids, nom_channel = config.CHANNEL_SPAWN_CLASSIQUE_ID, POIDS_RARETE_CLASSIQUE, "classique"
    else:
        channel_id, poids, nom_channel = config.CHANNEL_SPAWN_VIP_ID, POIDS_RARETE_VIP, "VIP"

    await envoyer_spawn(channel_id, poids, nom_channel, pokemon_force=pokemon)
    texte_pokemon = f"**{pokemon['nom']}**" if pokemon else "aléatoire"
    await interaction.response.send_message(
        f"✅ Spawn {texte_pokemon} envoyé dans le channel **{channel.name}** !", ephemeral=True
    )


@bot.tree.command(name="meteo-forcer", description="[Admin] Déclenche une météo précise immédiatement")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    type_meteo=[app_commands.Choice(name=m["nom"], value=m["nom"]) for m in meteo.METEOS]
)
async def meteo_forcer(
    interaction: discord.Interaction,
    type_meteo: app_commands.Choice[str],
    duree_minutes: int = None,
):
    meteo_choisie = next((m for m in meteo.METEOS if m["nom"] == type_meteo.value), None)
    if meteo_choisie is None:
        await interaction.response.send_message("❌ Météo introuvable.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"✅ Météo **{meteo_choisie['nom']}** déclenchée !", ephemeral=True
    )
    bot.loop.create_task(declencher_meteo(meteo_choisie, duree_minutes=duree_minutes))


@bot.tree.command(name="annonce", description="[Admin] Poste une annonce stylisée dans un channel choisi")
@app_commands.checks.has_permissions(administrator=True)
async def annonce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    titre: str,
    message: str,
    couleur: str = None,
):
    couleurs_disponibles = {
        "bleu": discord.Color.blue(),
        "vert": discord.Color.green(),
        "rouge": discord.Color.red(),
        "orange": discord.Color.orange(),
        "or": discord.Color.gold(),
        "violet": discord.Color.purple(),
    }
    couleur_finale = couleurs_disponibles.get((couleur or "").lower(), discord.Color.blurple())

    embed = discord.Embed(title=titre, description=message.replace("\\n", "\n"), color=couleur_finale)
    embed.set_footer(text=f"Annonce de {interaction.user.display_name}")

    await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Annonce postée dans {channel.mention}.", ephemeral=True)


@bot.tree.command(name="pause-spawns", description="[Admin] Met en pause les spawns")
@app_commands.checks.has_permissions(administrator=True)
async def pause_spawns(interaction: discord.Interaction, minutes: int = 0):
    boucle_spawn_classique.stop()
    boucle_spawn_vip.stop()

    if minutes > 0:
        bot.loop.create_task(reprendre_spawns_apres_delai(minutes * 60))
        await interaction.response.send_message(
            f"⏸️ Spawns mis en pause pour **{minutes} minute(s)**. Reprise automatique ensuite."
        )
    else:
        await interaction.response.send_message(
            "⏸️ Spawns mis en pause **indéfiniment**. Utilise `/resume-spawns` pour les relancer."
        )


async def reprendre_spawns_apres_delai(secondes: int):
    await asyncio.sleep(secondes)
    if not boucle_spawn_classique.is_running():
        boucle_spawn_classique.start()
    if not boucle_spawn_vip.is_running():
        boucle_spawn_vip.start()


@bot.tree.command(name="resume-spawns", description="[Admin] Relance les spawns s'ils sont en pause")
@app_commands.checks.has_permissions(administrator=True)
async def resume_spawns(interaction: discord.Interaction):
    deja_actifs = boucle_spawn_classique.is_running() and boucle_spawn_vip.is_running()

    if not boucle_spawn_classique.is_running():
        boucle_spawn_classique.start()
    if not boucle_spawn_vip.is_running():
        boucle_spawn_vip.start()

    if deja_actifs:
        await interaction.response.send_message("ℹ️ Les spawns tournaient déjà.", ephemeral=True)
    else:
        await interaction.response.send_message("▶️ Spawns relancés.")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "🚫 Tu dois être administrateur du serveur pour utiliser cette commande.",
            ephemeral=True,
        )
    else:
        raise error


class VueDefi(discord.ui.View):
    """Vue visible par tout le monde, mais seul l'adversaire ciblé peut accepter/refuser."""

    def __init__(self, challenger: discord.Member, adversaire: discord.Member):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.adversaire = adversaire
        self.resolu = False  # True dès qu'accepté/refusé, évite un double-traitement avec le timeout
        self.message = None  # défini juste après l'envoi, dans /defier

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.adversaire.id:
            await interaction.response.send_message("Ce défi ne te concerne pas !", ephemeral=True)
            return
        if self.resolu:
            await interaction.response.send_message("Ce défi n'est plus disponible.", ephemeral=True)
            return

        equipe_adv = combat_module.preparer_equipe_pour_combat(self.adversaire.id)
        if not equipe_adv:
            self.resolu = True
            await interaction.response.edit_message(
                content=f"❌ {self.adversaire.display_name} n'a pas d'équipe de combat configurée.",
                view=None,
            )
            return

        self.resolu = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {self.adversaire.mention} accepte le défi ! Le combat commence...",
            view=self,
        )
        await combat_module.demarrer_combat(bot, self.challenger, self.adversaire, interaction.channel)
        self.stop()

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.secondary, emoji="❌")
    async def refuser(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.adversaire.id:
            await interaction.response.send_message("Ce défi ne te concerne pas !", ephemeral=True)
            return
        if self.resolu:
            await interaction.response.send_message("Ce défi n'est plus disponible.", ephemeral=True)
            return
        self.resolu = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {self.adversaire.display_name} a refusé le défi.",
            view=self,
        )
        self.stop()

    async def on_timeout(self):
        if self.resolu:
            return  # déjà accepté/refusé entre-temps, rien à faire
        self.resolu = True
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=f"⌛ Le défi de **{self.challenger.display_name}** à {self.adversaire.mention} a expiré (60 secondes écoulées).",
                    view=self,
                )
            except discord.HTTPException:
                pass


class VueEchangeProposition(discord.ui.View):
    """Vue visible par tout le monde, mais seul le joueur ciblé peut accepter/refuser."""

    def __init__(self, proposeur: discord.Member, cible: discord.Member):
        super().__init__(timeout=60)
        self.proposeur = proposeur
        self.cible = cible
        self.resolu = False
        self.message = None

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.cible.id:
            await interaction.response.send_message("Cette proposition ne te concerne pas !", ephemeral=True)
            return
        if self.resolu:
            await interaction.response.send_message("Cette proposition n'est plus disponible.", ephemeral=True)
            return

        self.resolu = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {self.cible.mention} accepte ! Ouverture du fil d'échange...",
            view=self,
        )
        await demarrer_echange(self.proposeur, self.cible, interaction.channel)
        self.stop()

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.secondary, emoji="❌")
    async def refuser(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.cible.id:
            await interaction.response.send_message("Cette proposition ne te concerne pas !", ephemeral=True)
            return
        if self.resolu:
            await interaction.response.send_message("Cette proposition n'est plus disponible.", ephemeral=True)
            return
        self.resolu = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {self.cible.display_name} a refusé l'échange.",
            view=self,
        )
        self.stop()

    async def on_timeout(self):
        if self.resolu:
            return
        self.resolu = True
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=f"⌛ La proposition d'échange de **{self.proposeur.display_name}** à {self.cible.mention} a expiré.",
                    view=self,
                )
            except discord.HTTPException:
                pass


async def demarrer_echange(proposeur: discord.Member, cible: discord.Member, channel: discord.TextChannel):
    """Crée le fil privé d'échange et le premier message avec les deux offres vides."""
    echange_id = database.creer_echange(proposeur.id, cible.id)

    try:
        thread = await channel.create_thread(
            name=f"🔄 {proposeur.display_name} ↔ {cible.display_name}",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(proposeur)
        await thread.add_user(cible)
    except discord.HTTPException as e:
        await channel.send(f"❌ Impossible de créer le fil d'échange : {e}")
        database.annuler_echange(echange_id)
        return

    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE echanges SET thread_id = ? WHERE id = ?", (str(thread.id), echange_id))
    conn.commit()
    conn.close()

    noms = {proposeur.id: proposeur.display_name, cible.id: cible.display_name}
    embed, fichier = await echanges_module.construire_message_echange(echange_id, noms)
    vue = echanges_module.VueEchange(echange_id)
    envoi_kwargs = {"embed": embed, "view": vue}
    if fichier is not None:
        envoi_kwargs["file"] = fichier
    msg = await thread.send(
        content=f"{proposeur.mention} {cible.mention} — construisez vos offres puis validez chacun votre tour !",
        **envoi_kwargs,
    )
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE echanges SET message_id = ? WHERE id = ?", (str(msg.id), echange_id))
    conn.commit()
    conn.close()


bot.run(config.TOKEN)
