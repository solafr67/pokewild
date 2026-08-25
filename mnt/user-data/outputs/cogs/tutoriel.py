"""Cog : /tuto — rejoue le tutoriel d'accueil (voir tutoriel.py) à tout moment, en
éphémère. Complète le déclenchement automatique à l'arrivée (main.py::on_member_join).
"""

import discord
from discord import app_commands
from discord.ext import commands

import tutoriel as tutoriel_module


class TutorielCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="tuto", description="Revoir le tutoriel de prise en main (channels principaux)")
    async def tuto(self, interaction: discord.Interaction):
        vue = tutoriel_module.VueTutoriel(interaction.user)
        await interaction.response.send_message(
            embed=tutoriel_module.construire_embed_etape(0, interaction.user), view=vue, ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TutorielCog(bot))
