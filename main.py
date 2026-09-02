from dotenv import load_dotenv

load_dotenv()  # charge un fichier .env s'il existe (utile en local/test) — ne fait rien
# en production si le fichier n'existe pas, les vraies variables d'environnement système
# (définies par le service systemd) continuent de fonctionner exactement comme avant.

import asyncio
import json
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
import combat_2v2 as combat_2v2_module
import echanges as echanges_module
import marketplace as marketplace_module
import roguelike as roguelike_module
import maitre_types as maitre_types_module
import exploration as exploration_module
import race_ui as race_ui_module
import races
import quetes as quetes_module
import quetes_ui as quetes_ui_module
import evenements as evenements_module
import dresseurs as dresseurs_module
import defi_stats as defi_stats_module
import plus_ou_moins as plus_ou_moins_module
import quiz as quiz_module
import elevage as elevage_module
import journal
import pnj
import database
import etat_jeu
import leveling
import saison as saison_module
import wiki as wiki_module
import parrainage as parrainage_module
import draft_pvp as draft_pvp_module
import arene as arene_module
import repaires as repaires_module
import tutoriel as tutoriel_module
import meteo
import niveaux_pokemon
import aiohttp

from pokemon_data import (
    ATTAQUES,
    EMOJI_BALLS,
    EMOJI_OBJETS_DIVERS,
    EMOJI_POKEDOLLAR,
    EMOJI_RARETE,
    EMOJI_TYPES,
    EMOJI_SOINS,
    IMAGE_SOINS,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
    recharger_cache_emojis_objets,
    appliquer_emojis_objets,
    POIDS_RARETE_CLASSIQUE,
    POIDS_RARETE_VIP,
    POKEDEX,
    generer_pc,
    obtenir_pokemon_par_nom,
    tirer_boss_raid_par_etoile,
    obtenir_roster_raid,
    tirer_ivs,
    tirer_niveau_spawn,
    tirer_pokemon_aleatoire,
    appliquer_deguisement_si_applicable,
    calculer_pc_derive,
)
from boutique import construire_embed_boutique, construire_embed_marche_noir, VueBoutique, VueMarcheNoir
from cogs.messages_fixes import construire_embed_village, VueVillage
from profil import (
    construire_embed_fixe as construire_embed_profil_fixe,
    construire_embed_profil,
    construire_apercu_relacher,
    construire_embed_verrouillage,
    construire_embed_favoris,
    construire_embed_surnoms,
    effectuer_relacher_tous,
    fichier_avatar_fiable,
    url_avatar_fiable,
    VueConfirmationRelacher,
    VueOuvrirPokedex,
    VueProfil,
    VueVerrouillage,
    VueFavoris,
    VueSurnoms,
)
import pokedex as pokedex_module
import capacites as capacites_module
import formes_objets as formes_objets_module
import equipe_combat as equipe_combat_module
from views import VueSpawn, construire_embed_spawn

intents = discord.Intents.default()
intents.message_content = True  # requis pour lire les réponses tapées au quiz (Qui est-ce / Anagramme)
intents.members = True  # requis pour le suivi des invitations (parrainage) et des boosts serveur
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
        # Acquitte l'interaction TOUT DE SUITE, avant la moindre écriture en base — sur
        # mobile/réseau lent, la séquence d'écritures qui suit peut dépasser les 3 secondes
        # que Discord accorde pour répondre, ce qui affiche "Interaction échouée" côté
        # joueur alors que tout s'est bien exécuté côté serveur (cooldown posé, récompenses
        # données) sans que le joueur le voie jamais. defer() lève cette limite à 15 minutes.
        await interaction.response.defer(ephemeral=True)

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
            await interaction.followup.send(embed=embed_attente, ephemeral=True)
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
        texte_bonus_oeuf = None

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

        await interaction.followup.send(embed=embed_resultat, ephemeral=True)


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
        # Zorua/Zoroark/Métamorph apparaissent toujours déguisés — voir
        # pokemon_data.py::appliquer_deguisement_si_applicable pour le détail. Ne
        # s'applique qu'au tirage aléatoire normal, jamais à un spawn forcé par un admin
        # (qui veut explicitement CE Pokémon-là affiché, pas un autre).
        pokemon = appliquer_deguisement_si_applicable(pokemon)

    niveau = tirer_niveau_spawn(pokemon["rarete"])
    ivs = tirer_ivs()
    pc = calculer_pc_derive(pokemon, ivs, niveau)

    embed = construire_embed_spawn(pokemon, pc, niveau, force_shiny=force_shiny, duree_avant_disparition=config.DUREE_AVANT_DISPARITION)
    vue = VueSpawn(pokemon, pc, niveau, ivs, force_shiny=force_shiny, type_spawn=nom_channel)
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


@tasks.loop(seconds=config.MARKETPLACE_INTERVALLE_VERIFICATION_SECONDES)
async def boucle_marketplace():
    DERNIERE_ACTIVITE_BOUCLES["marketplace"] = time.time()
    try:
        await marketplace_module.purger_annonces_expirees(bot)
    except Exception as e:
        print(f"⚠️ Erreur dans boucle_marketplace (la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_marketplace` : {e}")


@tasks.loop(seconds=60)
async def boucle_verification_evenements():
    """Surveille les 3 events serveur (/event) pour détecter et annoncer leur fin : boost
    global expiré, défi collectif tout juste complété, chasse aux shiny arrivée à échéance.
    Base de données uniquement (pas de suivi en mémoire) — résiste aux redémarrages du bot,
    contrairement à un simple délai programmé (voir la leçon marketplace/pokestop_dore).
    ÉDITE le message "en cours" existant pour dire "terminé" (pas un nouveau message) —
    si ce message a été supprimé entre-temps, retombe sur un envoi normal."""
    DERNIERE_ACTIVITE_BOUCLES["evenements"] = time.time()

    async def _editer_ou_envoyer(channel, message_id, embed):
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(content=None, embed=embed)
                return
            except discord.NotFound:
                pass  # message supprimé entre-temps : on retombe sur un envoi normal
            except discord.HTTPException:
                return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    try:
        maintenant = int(time.time())

        # Boosts globaux expirés
        for ligne in database.obtenir_tous_boosts_globaux():
            if ligne["date_expiration"] > maintenant:
                continue
            channel = bot.get_channel(ligne["channel_annonce_id"]) if ligne["channel_annonce_id"] else None
            if channel:
                await _editer_ou_envoyer(channel, ligne.get("message_id"), evenements_module.construire_embed_boost_termine(ligne["type_boost"]))
            database.desactiver_boost_global(ligne["type_boost"])

        # Défis collectifs tout juste complétés (pas annulés — voir la requête SQL)
        for defi in database.obtenir_defis_collectifs_a_recompenser():
            participants = database.obtenir_participants_defi_collectif(defi["id"])
            for user_id, _contribution in participants:
                database.ajouter_poke_dollars(user_id, config.RECOMPENSE_DEFI_COLLECTIF_PD)
            database.marquer_defi_collectif_recompense(defi["id"])
            channel = bot.get_channel(defi["channel_annonce_id"]) if defi["channel_annonce_id"] else None
            if channel:
                nom = config.TYPES_DEFI_COLLECTIF.get(defi["type_evenement"], defi["type_evenement"])
                embed = evenements_module.construire_embed_defi_termine(nom, defi["cible"], len(participants))
                await _editer_ou_envoyer(channel, defi.get("message_id"), embed)

        # Chasses aux shiny arrivées à échéance
        for chasse in database.obtenir_chasses_shiny_a_terminer():
            classement = database.terminer_chasse_shiny(chasse["id"])
            channel = bot.get_channel(chasse["channel_annonce_id"]) if chasse["channel_annonce_id"] else None
            if channel:
                embed = evenements_module.construire_embed_chasse_shiny_terminee(classement)
                await _editer_ou_envoyer(channel, chasse.get("message_id"), embed)

        # Capture Classée arrivées à échéance
        for event in database.obtenir_events_capture_rarete_a_terminer():
            classement = database.terminer_event_capture_rarete(event["id"])
            channel = bot.get_channel(event["channel_annonce_id"]) if event["channel_annonce_id"] else None
            if channel:
                embed = evenements_module.construire_embed_capture_rarete_terminee(classement)
                await _editer_ou_envoyer(channel, event.get("message_id"), embed)
    except Exception as e:
        print(f"⚠️ Erreur dans boucle_verification_evenements (la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_verification_evenements` : {e}")


@tasks.loop(minutes=30)
async def boucle_classement_capture_rarete():
    """Édite le message d'annonce de l'event Capture Classée (s'il y en a un actif) avec
    le classement à jour — indépendante de boucle_verification_evenements (toutes les
    60s) car un rafraîchissement toutes les 30 min suffit largement et évite d'éditer le
    message bien plus souvent que nécessaire."""
    DERNIERE_ACTIVITE_BOUCLES["classement_capture_rarete"] = time.time()
    try:
        event = database.obtenir_event_capture_rarete_actif()
        if event is None:
            return
        channel = bot.get_channel(event["channel_annonce_id"]) if event["channel_annonce_id"] else None
        if channel is None or not event.get("message_id"):
            return
        classement = database.classement_event_capture_rarete_en_cours(event["id"])
        minutes_totales = round((event["date_fin"] - event["date_debut"]) / 60)
        embed = evenements_module.construire_embed_capture_rarete_classement(minutes_totales, classement)
        try:
            message = await channel.fetch_message(event["message_id"])
            await message.edit(embed=embed)
        except discord.NotFound:
            pass  # message supprimé entre-temps : la prochaine passe de 30 min retentera
        except discord.HTTPException:
            pass
    except Exception as e:
        print(f"⚠️ Erreur dans boucle_classement_capture_rarete (la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_classement_capture_rarete` : {e}")


@tasks.loop(hours=24)
async def boucle_snapshot_economie():
    """Enregistre un instantané quotidien de la masse de Poké Dollars en circulation,
    pour repérer un futur déséquilibre économique tôt plutôt que par analyse manuelle.
    Vérifie aussi (même cadence, largement suffisant pour un événement mensuel) si une
    nouvelle saison de clan doit être archivée — ne fait rien la plupart des jours."""
    DERNIERE_ACTIVITE_BOUCLES["snapshot_economie"] = time.time()
    try:
        database.enregistrer_snapshot_economie()
    except Exception as e:
        print(f"⚠️ Erreur dans boucle_snapshot_economie (la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `boucle_snapshot_economie` : {e}")
    try:
        database.cloturer_saison_clan_si_necessaire()
    except Exception as e:
        print(f"⚠️ Erreur dans cloturer_saison_clan_si_necessaire (la boucle continue) : {e}")
        journal.logger(f"🔴 Erreur dans `cloturer_saison_clan_si_necessaire` : {e}")


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
                        message_annonce = await channel.send(
                            "🔥 **Heure de pointe au PokéStop !** Récompenses doublées pendant 30 minutes !"
                        )
                        database.definir_parametre("pokestop_annonce_message_id", str(message_annonce.id))
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                journal.logger("🔥 Heure de pointe PokéStop activée pour 30 minutes.")
            elif not en_cours and etat_jeu.heure_de_pointe_pokestop_active:
                etat_jeu.heure_de_pointe_pokestop_active = False
                await poster_message_pokestop_si_absent()
                channel = bot.get_channel(config.CHANNEL_POKESTOP_ID) if getattr(config, "CHANNEL_POKESTOP_ID", None) else None
                message_annonce_id = database.obtenir_parametre("pokestop_annonce_message_id")
                if channel and message_annonce_id:
                    try:
                        message_annonce = await channel.fetch_message(int(message_annonce_id))
                        await message_annonce.delete()
                    except (discord.NotFound, discord.HTTPException):
                        pass
                journal.logger("🔥 Heure de pointe PokéStop terminée.")
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_evenement_pokestop (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_evenement_pokestop` — voir les logs serveur pour le détail complet.")


async def boucle_evenement_marche_noir():
    """Tire un créneau aléatoire de 1h par jour (9h-23h, heure de Paris), INDÉPENDANT
    de l'Heure de pointe PokéStop (horaire séparé, voir config.DUREE_MARCHE_NOIR),
    pendant lequel un message dédié apparaît dans le Village Pokémon avec les objets du
    jour (voir boutique.py::VueMarcheNoir) — un vrai spawn temporaire, retiré à la fin
    du créneau plutôt qu'un bouton toujours accessible. Le créneau et l'ID du message
    posté sont stockés en base (table parametres) pour survivre à un redémarrage du bot
    en plein milieu."""
    await bot.wait_until_ready()
    tz = ZoneInfo("Europe/Paris")

    while not bot.is_closed():
        await asyncio.sleep(60)
        DERNIERE_ACTIVITE_BOUCLES["evenement_marche_noir"] = time.time()

        try:
            maintenant_dt = datetime.now(tz)
            aujourdhui = maintenant_dt.date().isoformat()

            date_programmee = database.obtenir_parametre("marche_noir_event_date")
            debut_str = database.obtenir_parametre("marche_noir_event_debut")

            if date_programmee != aujourdhui:
                # Nouveau jour : tirer un nouvel horaire aléatoire, indépendant de celui
                # du PokéStop (clé de paramètre différente = tirage différent).
                fin_fenetre_dt = maintenant_dt.replace(
                    hour=config.HEURE_FIN_FENETRE_POINTE, minute=0, second=0, microsecond=0
                )
                dernier_depart_possible = fin_fenetre_dt - timedelta(seconds=config.DUREE_MARCHE_NOIR)
                minutes_fenetre = int((dernier_depart_possible.hour * 60 + dernier_depart_possible.minute) - config.HEURE_DEBUT_FENETRE_POINTE * 60)
                offset_minutes = random.randint(0, max(0, minutes_fenetre))
                debut_dt = maintenant_dt.replace(
                    hour=config.HEURE_DEBUT_FENETRE_POINTE, minute=0, second=0, microsecond=0
                ) + timedelta(minutes=offset_minutes)

                database.definir_parametre("marche_noir_event_date", aujourdhui)
                database.definir_parametre("marche_noir_event_debut", str(int(debut_dt.timestamp())))
                debut_str = str(int(debut_dt.timestamp()))
                print(f"🏴‍☠️ Marché Noir programmé aujourd'hui à {debut_dt.strftime('%H:%M')} (heure de Paris).")

            debut_epoch = int(debut_str)
            fin_epoch = debut_epoch + config.DUREE_MARCHE_NOIR
            maintenant_epoch = time.time()
            en_cours = debut_epoch <= maintenant_epoch < fin_epoch

            if en_cours and not etat_jeu.marche_noir_actif:
                etat_jeu.marche_noir_actif = True
                channel_id = getattr(config, "CHANNEL_VILLAGE_ID", None)
                channel = bot.get_channel(channel_id) if channel_id else None
                if channel:
                    try:
                        message = await channel.send(embed=construire_embed_marche_noir(), view=VueMarcheNoir())
                        database.definir_parametre("marche_noir_message_id", str(message.id))
                        journal.logger("🏴‍☠️ Marché Noir ouvert pour 1h dans le Village Pokémon.")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                else:
                    print("⚠️ CHANNEL_VILLAGE_ID introuvable — le Marché Noir n'a pas pu s'ouvrir aujourd'hui.")
            elif not en_cours and etat_jeu.marche_noir_actif:
                etat_jeu.marche_noir_actif = False
                channel_id = getattr(config, "CHANNEL_VILLAGE_ID", None)
                channel = bot.get_channel(channel_id) if channel_id else None
                message_id = database.obtenir_parametre("marche_noir_message_id")
                if channel and message_id:
                    try:
                        message = await channel.fetch_message(int(message_id))
                        await message.delete()
                    except (discord.NotFound, discord.HTTPException):
                        pass
                journal.logger("🏴‍☠️ Marché Noir fermé pour aujourd'hui.")
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_evenement_marche_noir (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_evenement_marche_noir` — voir les logs serveur pour le détail complet.")


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

            # Événements aléatoires "en cours de route" (destinations thématiques,
            # voir exploration.py::_tirer_evenement) — purement narratif, aucun effet
            # mécanique immédiat (le bonus éventuel est déjà appliqué à la récupération
            # finale de la récompense, pas ici).
            for row in database.obtenir_evenements_exploration_a_notifier():
                utilisateur = bot.get_user(row["user_id"]) or await bot.fetch_user(row["user_id"])
                pokemons = ", ".join(p for p in (row["pokemon1"], row["pokemon2"], row["pokemon3"]) if p)
                try:
                    await utilisateur.send(f"💬 En chemin, ton équipe ({pokemons}) {row['evenement_texte']}")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                database.marquer_evenement_exploration_notifie(row["user_id"], row["slot"])

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

        # Chaque raid est un combat neuf : on remet à plein le pool de PV séparé du raid
        # pour tous les participants. Sans ça, une équipe K.O. par la riposte d'un raid
        # précédent restait K.O. à vie dans ce pool (jamais soignée hors raid) → 0 dégât
        # infligé au boss ET 0 riposte subie, équipe pourtant affichée full vie partout.
        for row in database.obtenir_participants_raid(raid_id):
            database.reinitialiser_pool_raid_joueur(row["user_id"])

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
    # get_channel ne lit que le cache local et a déjà retourné None à tort par le passé
    # (même correctif que combat.py/dresseurs.py) : on vérifie pour de vrai auprès de
    # Discord, et surtout on ne sort plus JAMAIS en silence — un raid dont la boucle ne
    # démarre pas reste sinon figé 15 min sans aucun dégât ni riposte, sans aucune trace.
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None
    if channel is None:
        database.terminer_raid(raid_id)
        journal.logger(
            f"🔴 Raid {raid_id} : channel {channel_id} introuvable au démarrage du combat — "
            f"raid annulé (la boucle de combat n'a pas pu démarrer)."
        )
        return

    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        database.terminer_raid(raid_id)
        journal.logger(
            f"🔴 Raid {raid_id} : message de raid introuvable au démarrage du combat — "
            f"raid annulé (la boucle de combat n'a pas pu démarrer)."
        )
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
        # Les participants ne sont pour rien dans ce redémarrage — leur équipe (pool de
        # PV séparé "raid") est soignée gratuitement plutôt que de rester endommagée par
        # un raid qui n'a de toute façon donné ni victoire ni récompense.
        for participant in database.obtenir_participants_raid(row["id"]):
            database.soigner_completement_equipe(participant["user_id"], contexte="raid")
        database.terminer_raid(row["id"])
        # Prévenir les participants : sans ce message, le raid disparaissait sans explication.
        try:
            channel = bot.get_channel(int(row["channel_id"])) or await bot.fetch_channel(int(row["channel_id"]))
            await channel.send(
                "⚠️ Le serveur a redémarré : le raid en cours a été annulé (aucune récompense, "
                "aucune pénalité, équipes des participants soignées gratuitement). Un nouveau "
                "raid apparaîtra au prochain cycle."
            )
        except (discord.HTTPException, ValueError, TypeError):
            pass

    for row in database.obtenir_dresseurs_actifs_toutes():
        if row["message_id"] and await _supprimer_message_orphelin(row["channel_id"], row["message_id"]):
            compte += 1
        database.terminer_dresseur(row["id"])

    # Combats (dresseur/Arène/Gladio/PvP) encore actifs : leurs boucles de résolution sont
    # mortes avec l'ancien process — sans clôture, les joueurs restaient "déjà en combat"
    # (bloqués jusqu'au garde-fou de 10 min) dans des fils aux boutons morts. On les
    # termine en forfait (ni vainqueur ni récompense), on prévient dans le fil, et on
    # programme la suppression du fil comme pour une fin de combat normale.
    combats_annules = 0
    for row in database.obtenir_combats_pvp_actifs():
        database.terminer_combat_pvp(row["id"])
        combats_annules += 1
        # Les joueurs ne sont pour rien dans ce redémarrage — équipe soignée gratuitement
        # plutôt que de rester endommagée par un combat qui n'a de toute façon abouti à
        # rien (ni victoire, ni défaite). joueur2_id peut être une IA (ID négatif, dresseur
        # /Arène/Gladio) : on ne soigne jamais une IA, seulement de vrais joueurs.
        for joueur_id in (row["joueur1_id"], row["joueur2_id"]):
            if joueur_id and joueur_id > 0:
                database.soigner_completement_equipe(joueur_id, contexte="normal")
        if row["thread_id"]:
            try:
                thread = bot.get_channel(int(row["thread_id"])) or await bot.fetch_channel(int(row["thread_id"]))
                await thread.send(
                    "⚠️ Le serveur a redémarré : ce combat est annulé en forfait — ni vainqueur, "
                    "ni récompense, personne n'est pénalisé, et vos équipes ont été soignées "
                    "gratuitement. Vous pouvez relancer un combat dès maintenant. Ce fil sera "
                    f"supprimé dans {combat_module.DELAI_SUPPRESSION_FIL // 60} minutes."
                )
                bot.loop.create_task(
                    dresseurs_module._supprimer_fil_apres_delai(thread, combat_module.DELAI_SUPPRESSION_FIL)
                )
            except (discord.HTTPException, ValueError, TypeError):
                pass

    runs_arene_perdus = database.marquer_runs_arene_en_cours_defaite()
    if combats_annules or runs_arene_perdus:
        journal.logger(
            f"🧹 Redémarrage : {combats_annules} combat(s) clôturé(s) en forfait"
            + (f", {runs_arene_perdus} run(s) d'arène interrompu(s)." if runs_arene_perdus else ".")
        )

    if compte:
        print(f"🧹 {compte} message(s) orphelin(s) (spawn/raid/dresseur) nettoyé(s) après redémarrage.")
        journal.logger(f"🧹 {compte} message(s) orphelin(s) nettoyé(s) après redémarrage.")


@bot.event
async def on_ready():
    database.init_db()

    # Chargement des Cogs (découpage progressif de main.py en modules par domaine — voir
    # cogs/). DOIT se faire avant bot.tree.sync() ci-dessous, sinon leurs commandes ne
    # sont pas encore dans l'arbre au moment de la synchro. Gardé par un flag comme les
    # boucles plus bas : on_ready peut être rappelé après une reconnexion, et charger une
    # extension déjà chargée lève ExtensionAlreadyLoaded.
    if not getattr(bot, "cogs_charges", False):
        await bot.load_extension("cogs.admin_economie")
        await bot.load_extension("cogs.codes_promo")
        await bot.load_extension("cogs.admin_diagnostics")
        await bot.load_extension("cogs.minijeux_marketplace")
        await bot.load_extension("cogs.messages_fixes")
        await bot.load_extension("cogs.gestion_pokemon")
        await bot.load_extension("cogs.rival_evenements")
        await bot.load_extension("cogs.admin_joueur")
        await bot.load_extension("cogs.gladio_raids_echanges")
        await bot.load_extension("cogs.saison_annonces")
        await bot.load_extension("cogs.pokestop_classement")
        await bot.load_extension("cogs.combat_defis")
        await bot.load_extension("cogs.admin_spawns_meteo")
        await bot.load_extension("cogs.tutoriel")
        await bot.load_extension("cogs.connexion_quotidienne")
        await bot.load_extension("cogs.recap_hebdomadaire")
        bot.cogs_charges = True

    # Remplace en place les emoji Unicode génériques des objets par les vrais sprites déjà
    # importés (voir /admin-importer-emojis-objets) — met à jour tous les affichages du bot
    # d'un coup (inventaire, profil, combat, exploration, raids, repaires, roguelike, pokédex...).
    appliquer_emojis_objets(capacites_module.OBJETS_TENUS, formes_objets_module.FORMES_OBJETS, EMOJI_SOINS)
    await nettoyer_etats_orphelins_au_demarrage()
    bot.add_view(VuePokestop())  # réenregistre la vue persistante après un redémarrage
    bot.add_view(VueBoutique())  # idem pour la boutique
    bot.add_view(VueVillage())  # idem pour le Village Pokémon (Boutique/PokéStop/Maître des Capacités regroupés)
    bot.add_view(VueProfil())  # idem pour le profil
    bot.add_view(VueOuvrirPokedex())  # idem pour le bouton pokédex affiché sur le profil
    bot.add_view(maitre_types_module.VueMaitreTypes())  # idem pour le Maître des Types
    bot.add_view(wiki_module.VueWiki())  # idem pour le wiki
    bot.add_view(exploration_module.VueCentreExploration())  # idem pour le Centre des Explorations
    bot.add_view(quetes_ui_module.VueCentreQuetes())  # idem pour les Quêtes
    bot.add_view(classement_module.VueClassements())  # idem pour les classements
    bot.add_view(elevage_module.VueLaboratoire())  # idem pour le Laboratoire
    bot.add_view(VuePingRaid())  # idem pour le bouton de ping raid
    bot.add_view(marketplace_module.VueAnnonce())  # idem pour les annonces marketplace (générique, voir la classe)
    bot.add_view(roguelike_module.VueRoom())  # idem pour le bouton "Continuer" (générique, voir la classe)
    bot.add_view(roguelike_module.VueCombatRoguelike())  # idem pour le bouton "Attaquer"
    # Note : VueRaid n'est plus enregistrée en persistante (elle a besoin d'un raid_id précis,
    # comme les spawns classiques un raid en cours au moment d'un redémarrage sera perdu)

    # ⚠️ Toute la synchro est entourée d'un try/except : une erreur ici (ex: trop de
    # choix sur un paramètre, limite Discord = 25) ne doit JAMAIS empêcher le reste de
    # on_ready() de s'exécuter — sinon les boucles de spawn, entre autres, ne démarrent
    # plus DU TOUT (vécu le 08/08/2026 : plus aucun spawn tant que le bot n'a pas pu
    # passer cette étape, à chaque tentative de reconnexion en plus).
    try:
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
    except Exception as e:
        print(f"🔴 Erreur lors de la synchro des commandes (le bot continue de démarrer quand même) : {e}")
        journal.logger(
            f"🔴 Synchro des commandes échouée — les commandes slash peuvent être obsolètes/manquantes, "
            f"mais spawns et autres boucles démarrent normalement : {e}"
        )

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

    if not getattr(bot, "boucle_evenement_marche_noir_lancee", False):
        bot.loop.create_task(boucle_evenement_marche_noir())
        bot.boucle_evenement_marche_noir_lancee = True

    if not getattr(bot, "boucle_quiz_lancee", False):
        bot.loop.create_task(quiz_module.boucle_quiz(bot))
        bot.boucle_quiz_lancee = True

    if not getattr(bot, "boucle_parrainage_lancee", False):
        bot.loop.create_task(parrainage_module.boucle_confirmation_parrainages(bot))
        bot.boucle_parrainage_lancee = True

    if not getattr(bot, "boucle_arene_lancee", False):
        bot.loop.create_task(arene_module.boucle_arene(bot))
        bot.boucle_arene_lancee = True

    if not getattr(bot, "boucle_repaires_lancee", False):
        bot.loop.create_task(repaires_module.boucle_repaires(bot))
        bot.boucle_repaires_lancee = True

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

    if not boucle_marketplace.is_running():
        boucle_marketplace.start()

    if not boucle_verification_evenements.is_running():
        boucle_verification_evenements.start()

    if not boucle_classement_capture_rarete.is_running():
        boucle_classement_capture_rarete.start()

    # Les 3 auto-publications individuelles (PokéStop/Boutique/Maître des Capacités)
    # ont été remplacées par un seul message fixe regroupé — voir
    # poster_message_village_si_absent() et cogs/messages_fixes.py::VueVillage.
    # Chaque fonction/commande /setup-X individuelle reste utilisable telle quelle si
    # besoin (rien de supprimé, juste plus appelé automatiquement ici).
    await poster_message_village_si_absent()
    await poster_message_wiki_si_absent()

    for guild in bot.guilds:
        await parrainage_module.rafraichir_cache(guild)
        parrainage_module.synchroniser_boosters(guild)
    await poster_message_centre_exploration_si_absent()
    # poster_message_quetes_si_absent() n'est plus appelée automatiquement — les Quêtes
    # sont maintenant intégrées au message fixe du profil (voir profil.py::VueProfil,
    # 3 boutons repris de VueCentreQuetes). La fonction reste définie plus bas, utilisable
    # telle quelle si besoin un jour de la reposter séparément.
    await poster_message_profil_si_absent()
    await poster_message_laboratoire_si_absent()
    await poster_message_ping_raid_si_absent()

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

    if message.channel.id == getattr(config, "CHANNEL_QUIZ_ID", None):
        await quiz_module.verifier_reponse_texte(message)

    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    await parrainage_module.traiter_arrivee(member)
    # Si un rôle de vérification est configuré, on attend qu'il soit attribué (voir
    # on_member_update, fusionné avec le suivi du statut booster serveur plus bas) plutôt
    # que de tenter ici — sur un serveur avec vérification anti-raid, le membre n'a pas
    # encore accès à la catégorie du channel #profil à ce stade, ce qui empêchait le fil
    # privé de se synchroniser correctement côté client.
    if not config.ROLE_VERIFICATION_ID:
        await tutoriel_module.poster_accueil(member)


@bot.event
async def on_member_remove(member: discord.Member):
    await parrainage_module.traiter_depart(member)


@bot.event
async def on_invite_create(invite: discord.Invite):
    await parrainage_module.rafraichir_cache(invite.guild)


@bot.event
async def on_invite_delete(invite: discord.Invite):
    await parrainage_module.rafraichir_cache(invite.guild)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Suit en direct le statut de booster serveur (before.premium_since vs
    after.premium_since) pour alimenter le bonus argent/xp/shiny correspondant.
    Sert aussi à déclencher le fil d'accueil du tuto sur les serveurs avec vérification
    anti-raid, une fois que le rôle de vérification vient tout juste d'être attribué —
    voir on_member_join, qui ne tente rien dans ce cas précisément pour cette raison."""
    if before.premium_since != after.premium_since:
        database.definir_booster_serveur(after.id, after.premium_since is not None)

    if config.ROLE_VERIFICATION_ID:
        roles_avant = {r.id for r in before.roles}
        roles_apres = {r.id for r in after.roles}
        if config.ROLE_VERIFICATION_ID in roles_apres and config.ROLE_VERIFICATION_ID not in roles_avant:
            await tutoriel_module.poster_accueil(after)


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


async def poster_message_village_si_absent():
    """Poste le message fixe UNIQUE du Village Pokémon (Boutique/PokéStop/Maître des
    Capacités regroupés, voir cogs/messages_fixes.py::VueVillage), ou le met à jour
    s'il existe déjà — remplace les 3 anciennes auto-publications séparées."""
    channel_id = getattr(config, "CHANNEL_VILLAGE_ID", None)
    if not channel_id:
        return  # channel non configuré : chaque système reste accessible via /setup-X individuellement

    channel = bot.get_channel(channel_id)
    if channel is None:
        print("⚠️ CHANNEL_VILLAGE_ID introuvable — vérifie l'ID dans config.py ou le .env.")
        return

    embed = construire_embed_village()
    message_id = database.obtenir_parametre("village_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=VueVillage())
            return
        except discord.NotFound:
            pass

    message = await channel.send(embed=embed, view=VueVillage())
    database.definir_parametre("village_message_id", str(message.id))


async def poster_message_wiki_si_absent():
    """Poste le message fixe du wiki (si le channel est configuré), ou le met à jour
    s'il existe déjà."""
    channel_id = getattr(config, "CHANNEL_WIKI_ID", None)
    if not channel_id:
        return  # channel non configuré : le wiki reste accessible via /wiki

    channel = bot.get_channel(channel_id)
    if channel is None:
        print("⚠️ CHANNEL_WIKI_ID introuvable — vérifie l'ID dans config.py.")
        return

    embed = wiki_module.construire_embed_accueil()
    message_id = database.obtenir_parametre("wiki_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=wiki_module.VueWiki())
            return
        except discord.NotFound:
            pass

    message = await channel.send(embed=embed, view=wiki_module.VueWiki())
    database.definir_parametre("wiki_message_id", str(message.id))


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


async def _basculer_role_ping(interaction: discord.Interaction, role_id: int | None, nom_config: str, nom_notification: str):
    """Logique partagée par les 4 boutons de notification ci-dessous : ajoute/retire le
    rôle selon que le joueur l'a déjà ou non."""
    if not role_id:
        await interaction.response.send_message(
            f"⚠️ Le rôle de notification {nom_notification} n'a pas encore été configuré par un admin ({nom_config}).",
            ephemeral=True,
        )
        return

    role = interaction.guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message(
            f"⚠️ Le rôle configuré ({nom_config}) est introuvable sur ce serveur.", ephemeral=True
        )
        return

    if role in interaction.user.roles:
        await interaction.user.remove_roles(role)
        await interaction.response.send_message(f"🔕 Tu ne recevras plus les notifications {nom_notification}.", ephemeral=True)
    else:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"🔔 Tu recevras désormais un ping à chaque {nom_notification} !", ephemeral=True)


class VuePingRaid(discord.ui.View):
    """Message fixe (channel dédié) permettant à chacun d'activer/désactiver ses rôles de
    notification (raid, event, annonce, mise à jour) sans passer par une commande —
    un bouton toggle par catégorie."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Notifications Raid", emoji="🔔", style=discord.ButtonStyle.primary, custom_id="pokewild:toggle_ping_raid")
    async def basculer_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id = getattr(config, "ROLE_PING_RAID_ID", None)
        await _basculer_role_ping(interaction, role_id, "ROLE_PING_RAID_ID", "nouveau raid")

    @discord.ui.button(label="Notifications Event", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="pokewild:toggle_ping_event")
    async def basculer_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id = getattr(config, "ROLE_PING_EVENT_ID", None)
        await _basculer_role_ping(interaction, role_id, "ROLE_PING_EVENT_ID", "event serveur")

    @discord.ui.button(label="Notifications Annonce", emoji="📢", style=discord.ButtonStyle.secondary, custom_id="pokewild:toggle_ping_annonce")
    async def basculer_annonce(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id = getattr(config, "ROLE_PING_ANNONCE_ID", None)
        await _basculer_role_ping(interaction, role_id, "ROLE_PING_ANNONCE_ID", "annonce")

    @discord.ui.button(label="Notifications Mise à Jour", emoji="🛠️", style=discord.ButtonStyle.secondary, custom_id="pokewild:toggle_ping_maj")
    async def basculer_maj(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id = getattr(config, "ROLE_PING_MAJ_ID", None)
        await _basculer_role_ping(interaction, role_id, "ROLE_PING_MAJ_ID", "mise à jour")


async def poster_message_ping_raid_si_absent():
    """Poste (ou met à jour) le message fixe du channel dédié au ping raid — même
    principe que poster_message_profil_si_absent/poster_message_laboratoire_si_absent."""
    channel = bot.get_channel(config.CHANNEL_PING_RAID_ID)
    if channel is None:
        print(
            "⚠️ CHANNEL_PING_RAID_ID introuvable — vérifie l'ID dans config.py. "
            "Le message de ping raid n'a pas pu être posté automatiquement."
        )
        return

    embed = discord.Embed(
        title="🔔 Notifications",
        description=(
            "Clique sur les boutons ci-dessous pour activer/désactiver chaque type de "
            "notification — reclique à tout moment pour te désabonner.\n\n"
            "🔔 **Raid** — un nouveau raid apparaît\n"
            "🎉 **Event** — un event serveur démarre (boost, défi collectif, chasse aux shiny...)\n"
            "📢 **Annonce** — une annonce importante du staff\n"
            "🛠️ **Mise à jour** — une nouvelle mise à jour du bot"
        ),
        color=discord.Color.blue(),
    )
    message_id = database.obtenir_parametre("ping_raid_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=VuePingRaid())
            return
        except discord.NotFound:
            pass  # le message a été supprimé manuellement, on va en recréer un ci-dessous

    message = await channel.send(embed=embed, view=VuePingRaid())
    database.definir_parametre("ping_raid_message_id", str(message.id))


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






# defi-gladio, reroll-raids : déplacées dans cogs/gladio_raids_echanges.py — 9e lot.


# roster-raids, reset-cooldown-gladio, gladio : déplacées dans cogs/rival_evenements.py
# — 7e lot du découpage en Cogs.

# passe-saison : déplacée dans cogs/saison_annonces.py — 10e lot du découpage en Cogs.



# parrainage, defi-draft, badges-arene, force-arene, force-repaire : déplacées dans
# cogs/rival_evenements.py — 7e lot du découpage en Cogs.

# admin-importer-emojis-objets : déplacée dans cogs/gladio_raids_echanges.py — 9e lot.


# pokedex-info, equiper-objet, objets-disponibles, defi-stats, plus-ou-moins,
# verrouiller-pokemon, favoris, surnommer : déplacées dans cogs/gestion_pokemon.py
# — 6e lot du découpage en Cogs.



# setup-boutique, setup-profil, mon-classement : déplacées dans cogs/messages_fixes.py
# — 5e lot du découpage en Cogs. setup-classement (juste en dessous) et setup-pokestop
# (plus bas) restent ici pour l'instant, voir la note dans messages_fixes.py.
# setup-classement, setup-pokestop, force-pokestop-dore, stop-pokestop-dore :
# déplacées dans cogs/pokestop_classement.py — 11e lot (dernier lot du découpage en Cogs).

# ----------------------------------------------------------------------------
# Codes promo
# ----------------------------------------------------------------------------

# creer-code, desactiver-code, liste-codes, code : déplacées dans cogs/codes_promo.py
# (voir le chargement des extensions dans on_ready) — 2e lot du découpage en Cogs.

# give-boost : déplacée dans cogs/admin_joueur.py — 8e lot du découpage en Cogs.

# reset-pokestop, status-bot, stats-economie, voir-joueur, reset-joueur, annuler-raid,
# annuler-combat : déplacées dans cogs/admin_diagnostics.py — 3e lot du découpage en Cogs.

# roguelike, roguelike-abandonner, roguelike-classement, vendre-pokemon,
# marketplace-recherche, marketplace-historique : déplacées dans
# cogs/minijeux_marketplace.py — 4e lot du découpage en Cogs.


# combat-2v2-equipe, combat-2v2, defier (+ VueDefiDouble, VueDefi plus bas) :
# déplacées dans cogs/combat_defis.py — 12e lot.

# echanger : déplacée dans cogs/gladio_raids_echanges.py (avec sa Vue et son helper
# demarrer_echange, qui vivaient en fin de fichier) — 9e lot du découpage en Cogs.










# setup-quetes : déplacée dans cogs/gladio_raids_echanges.py — 9e lot.


# finir-exploration, finir-incubation : déplacées dans cogs/admin_joueur.py — 8e lot.



# setup-centre-exploration, abandonner-combat : déplacées dans cogs/admin_joueur.py — 8e lot.

# force-dresseur, force-raid, force-spawn-shiny, force-spawn, meteo-forcer,
# pause-spawns, resume-spawns : déplacées dans cogs/admin_spawns_meteo.py — 13e et
# dernier lot du découpage en Cogs.

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "🚫 Tu dois être administrateur du serveur pour utiliser cette commande.",
            ephemeral=True,
        )
    else:
        raise error


# VueDefi (utilisée par /defier, voir cogs/combat_defis.py) : déplacée avec la commande
# — 12e lot du découpage en Cogs.

# VueEchangeProposition + demarrer_echange : déplacées dans cogs/gladio_raids_echanges.py
# avec la commande echanger — 9e lot du découpage en Cogs.


bot.run(config.TOKEN)
