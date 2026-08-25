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

import database
from boutique import construire_embed_boutique, VueBoutique
from pokemon_data import EMOJI_POKEDOLLAR, POKEDEX
from profil import construire_embed_fixe as construire_embed_profil_fixe, VueProfil


class MessagesFixesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup-boutique", description="[Admin] Poste ou remet à jour le message fixe de la boutique dans ce channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_boutique(self, interaction: discord.Interaction):
        embed = construire_embed_boutique()
        await interaction.response.send_message(embed=embed, view=VueBoutique())

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
