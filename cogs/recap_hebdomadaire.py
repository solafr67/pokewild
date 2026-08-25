"""Cog : /recap — progression personnelle depuis la dernière consultation (voir
recap_hebdomadaire.py pour le calcul).
"""

import discord
from discord import app_commands
from discord.ext import commands

import recap_hebdomadaire as rh
from pokemon_data import EMOJI_POKEDOLLAR


class RecapHebdomadaireCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="recap",
        description="Ta progression depuis la dernière fois que tu as consulté cette commande",
    )
    async def recap(self, interaction: discord.Interaction):
        resultat = rh.obtenir_recap(interaction.user.id)

        if resultat["premiere_fois"]:
            embed = discord.Embed(
                title="📊 Ton récap",
                description=(
                    "Premier point de départ enregistré ! Reviens dans quelques jours "
                    "avec `/recap` pour voir ta progression depuis maintenant."
                ),
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        jours = resultat["jours_ecoules"]
        embed = discord.Embed(
            title="📊 Ton récap",
            description=f"Depuis ta dernière consultation, il y a **{jours} jour(s)** :",
            color=discord.Color.blurple(),
        )

        lignes = []
        if resultat["captures_totales"] > 0:
            lignes.append(f"🎯 **{resultat['captures_totales']}** capture(s)")
        if resultat["shiny_totaux"] > 0:
            lignes.append(f"✨ **{resultat['shiny_totaux']}** shiny")
        if resultat["victoires_pvp"] > 0:
            lignes.append(f"⚔️ **{resultat['victoires_pvp']}** victoire(s) PvP")
        if resultat["victoires_pve"] > 0:
            lignes.append(f"🥊 **{resultat['victoires_pve']}** victoire(s) contre un dresseur")
        if resultat["explorations_terminees"] > 0:
            lignes.append(f"🗺️ **{resultat['explorations_terminees']}** exploration(s) terminée(s)")

        variation = resultat["variation_poke_dollars"]
        if variation != 0:
            signe = "+" if variation > 0 else ""
            lignes.append(f"{EMOJI_POKEDOLLAR} **{signe}{variation}** Poké Dollars (net, gains moins dépenses)")

        if lignes:
            embed.add_field(name="Progression", value="\n".join(lignes), inline=False)
        else:
            embed.add_field(name="Progression", value="*Rien de nouveau depuis la dernière fois !*", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RecapHebdomadaireCog(bot))
