"""Cog : setup-boutique, setup-profil, mon-classement. Cinquième lot du découpage en Cogs
— voir cogs/admin_economie.py pour le contexte général.

setup-classement et setup-pokestop restent dans main.py pour l'instant : ils dépendent
de rafraichir_classement()/construire_embed_pokestop()/VuePokestop, qui vivent encore
dans main.py lui-même (pas des modules externes comme boutique.py/profil.py) — à
extraire plus tard avec le lot des boucles de fond, plus cohérent pour ces deux-là.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import database
import etat_jeu
import journal
from boutique import construire_embed_boutique, construire_embed_marche_noir, VueBoutique, VueMarcheNoir
from casino import construire_embed_casino, VueCasino
from maitre_types import construire_embed_maitre, VueMaitreTypes
from pokemon_data import EMOJI_POKEDOLLAR, POKEDEX
from profil import construire_embed_fixe as construire_embed_profil_fixe, VueProfil


def construire_embed_village() -> discord.Embed:
    embed = discord.Embed(
        title="🏘️ Village Pokémon",
        description=(
            "Choisis une destination ci-dessous — chaque bouton ouvre un panneau "
            "visible **seulement par toi**.\n\n"
            "🛒 **Boutique** — balls, potions, objets tenus, gemmes méga...\n"
            "🔵 **PokéStop** — objets gratuits toutes les 5 minutes\n"
            "🧙 **Maître des Capacités** — gère les attaques et objets tenus de ton équipe\n"
            "🏥 **Centre Pokémon** — soin complet gratuit de ton équipe de combat, toutes les 30 minutes\n"
            "🎰 **Casino** — mise tes Poké Dollars au Blackjack ou à la Roulette"
        ),
        color=discord.Color.gold(),
    )
    return embed


class VueVillage(discord.ui.View):
    """Message fixe UNIQUE regroupant Boutique/PokéStop/Maître des Capacités — chaque
    bouton ouvre le panneau correspondant en message éphémère (visible seulement par le
    joueur qui clique), en réutilisant TEL QUEL l'embed et la vue de chaque système
    (aucune logique dupliquée, juste un point d'entrée commun). PokéStop vit dans
    main.py (pas un module externe comme boutique.py/maitre_types.py) — accédé via
    sys.modules["__main__"] plutôt qu'un `import main`, qui recharge tout le script
    depuis zéro (voir la mise en garde historique à ce sujet)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Boutique", emoji="🛒", style=discord.ButtonStyle.primary, custom_id="village_boutique")
    async def boutique(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=construire_embed_boutique(), view=VueBoutique(), ephemeral=True)

    @discord.ui.button(label="PokéStop", emoji="🔵", style=discord.ButtonStyle.primary, custom_id="village_pokestop")
    async def pokestop(self, interaction: discord.Interaction, button: discord.ui.Button):
        import sys
        main_module = sys.modules["__main__"]
        await interaction.response.send_message(
            embed=main_module.construire_embed_pokestop(), view=main_module.VuePokestop(), ephemeral=True
        )

    @discord.ui.button(
        label="Maître des Capacités", emoji="🧙", style=discord.ButtonStyle.primary, custom_id="village_maitre_types"
    )
    async def maitre_types(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=construire_embed_maitre(), view=VueMaitreTypes(), ephemeral=True)

    @discord.ui.button(label="Centre Pokémon", emoji="🏥", style=discord.ButtonStyle.success, custom_id="village_centre_pokemon")
    async def centre_pokemon(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        peut_soigner, temps_restant = database.peut_utiliser_centre_pokemon(user_id, config.COOLDOWN_CENTRE_POKEMON)

        if not peut_soigner:
            minutes = temps_restant // 60
            secondes = temps_restant % 60
            await interaction.response.send_message(
                f"⏳ Le Centre Pokémon n'est pas encore prêt — reviens dans **{minutes}m {secondes}s**.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "🏥 Veux-tu soigner intégralement ton équipe de combat (PvP, Dresseurs, Arène, Raids) ? "
            "Le prochain soin gratuit ne sera possible que dans 30 minutes après confirmation.",
            view=VueConfirmationCentrePokemon(user_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Casino", emoji="🎰", style=discord.ButtonStyle.danger, custom_id="village_casino")
    async def casino(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=construire_embed_casino(), view=VueCasino(), ephemeral=True)


class VueConfirmationCentrePokemon(discord.ui.View):
    """Confirmation avant de soigner — évite qu'un simple clic accidentel sur le bouton
    principal pose le cooldown de 30 minutes pour rien, alors que l'équipe n'avait peut-
    être même pas besoin de soin. "Annuler" est déclaré EN PREMIER, même raisonnement que
    pour l'abandon de combat (voir combat.py::VueConfirmationAbandon) : un double-tap
    accidentel au même endroit doit tomber sur l'option sûre."""

    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta confirmation !", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.edit_message(content="Soin annulé — le cooldown n'a pas été posé.", view=None)

    @discord.ui.button(label="Oui, soigner", emoji="🏥", style=discord.ButtonStyle.success)
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        # Revérifié au moment de la confirmation (pas seulement au clic initial) — évite
        # un double-soin si le joueur a ouvert deux confirmations en parallèle.
        peut_soigner, temps_restant = database.peut_utiliser_centre_pokemon(self.user_id, config.COOLDOWN_CENTRE_POKEMON)
        if not peut_soigner:
            minutes = temps_restant // 60
            secondes = temps_restant % 60
            await interaction.response.edit_message(
                content=f"⏳ Le Centre Pokémon n'est plus disponible — reviens dans **{minutes}m {secondes}s**.",
                view=None,
            )
            return

        database.soigner_completement_equipe(self.user_id, "normal")
        database.soigner_completement_equipe(self.user_id, "raid")
        database.marquer_centre_pokemon_utilise(self.user_id)
        await interaction.response.edit_message(
            content="🏥 Ton équipe de combat est intégralement soignée ! (PvP, Dresseurs, Arène, Raids.)",
            view=None,
        )


class MessagesFixesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup-boutique", description="[Admin] Poste ou remet à jour le message fixe de la boutique dans ce channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_boutique(self, interaction: discord.Interaction):
        embed = construire_embed_boutique()
        await interaction.response.send_message(embed=embed, view=VueBoutique())

    @app_commands.command(
        name="setup-village",
        description="[Admin] Poste ou remet à jour le message fixe du Village Pokémon dans ce channel",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_village(self, interaction: discord.Interaction):
        embed = construire_embed_village()
        await interaction.response.send_message(embed=embed, view=VueVillage())

    @app_commands.command(
        name="force-marche-noir",
        description="[Admin] Déclenche immédiatement le Marché Noir pour 1h dans le Village Pokémon",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def force_marche_noir(self, interaction: discord.Interaction):
        tz = ZoneInfo("Europe/Paris")
        maintenant_dt = datetime.now(tz)
        database.definir_parametre("marche_noir_event_date", maintenant_dt.date().isoformat())
        database.definir_parametre("marche_noir_event_debut", str(int(maintenant_dt.timestamp())))
        etat_jeu.marche_noir_actif = True

        channel_id = getattr(config, "CHANNEL_VILLAGE_ID", None)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            await interaction.response.send_message(
                "❌ CHANNEL_VILLAGE_ID introuvable — vérifie l'ID dans config.py ou le .env.", ephemeral=True
            )
            return

        message = await channel.send(embed=construire_embed_marche_noir(), view=VueMarcheNoir())
        database.definir_parametre("marche_noir_message_id", str(message.id))

        journal.logger(f"🛠️ <@{interaction.user.id}> a déclenché le Marché Noir manuellement (/force-marche-noir).")
        confirmation = "🏴‍☠️ **Marché Noir** déclenché pour 1h dans le Village Pokémon !"
        if channel.id == interaction.channel_id:
            await interaction.response.send_message(confirmation, ephemeral=True)
        else:
            await interaction.response.send_message(confirmation)

    @app_commands.command(
        name="fermer-marche-noir",
        description="[Admin] Ferme le Marché Noir en cours, sans en reprogrammer un autre aujourd'hui",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fermer_marche_noir(self, interaction: discord.Interaction):
        if not etat_jeu.marche_noir_actif:
            await interaction.response.send_message("Il n'y a pas de Marché Noir en cours.", ephemeral=True)
            return

        # On pousse le créneau enregistré dans le passé (fin < maintenant) sans toucher à
        # la date du jour : la boucle voit "déjà fini" au prochain passage et ne retire
        # PAS un nouveau créneau aléatoire pour le reste de la journée.
        tz = ZoneInfo("Europe/Paris")
        maintenant_dt = datetime.now(tz)
        debut_dans_le_passe = maintenant_dt - timedelta(seconds=config.DUREE_MARCHE_NOIR + 60)
        database.definir_parametre("marche_noir_event_date", maintenant_dt.date().isoformat())
        database.definir_parametre("marche_noir_event_debut", str(int(debut_dans_le_passe.timestamp())))
        etat_jeu.marche_noir_actif = False

        channel_id = getattr(config, "CHANNEL_VILLAGE_ID", None)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        message_id = database.obtenir_parametre("marche_noir_message_id")
        if channel and message_id:
            try:
                message = await channel.fetch_message(int(message_id))
                await message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        journal.logger(f"🛠️ <@{interaction.user.id}> a fermé le Marché Noir manuellement (/fermer-marche-noir).")
        await interaction.response.send_message("🛑 **Marché Noir** fermé.", ephemeral=True)

    @app_commands.command(name="setup-profil", description="[Admin] Poste ou remet à jour le message fixe du channel profil")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_profil(self, interaction: discord.Interaction):
        embed = construire_embed_profil_fixe()
        await interaction.response.send_message(embed=embed, view=VueProfil())

    @app_commands.command(name="mon-classement", description="Affiche ta position personnelle dans les classements")
    async def mon_classement(self, interaction: discord.Interaction):
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


async def setup(bot: commands.Bot):
    await bot.add_cog(MessagesFixesCog(bot))
