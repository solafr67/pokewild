"""Cog : /recompense-quotidienne — série de connexion, récompense exponentielle
plafonnée (voir connexion_quotidienne.py pour le calcul et l'orchestration).
"""

import discord
from discord import app_commands
from discord.ext import commands

import connexion_quotidienne as cq


class ConnexionQuotidienneCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="recompense-quotidienne",
        description="Réclame ta récompense du jour — la série de jours consécutifs fait grandir le gain",
    )
    async def recompense_quotidienne(self, interaction: discord.Interaction):
        resultat = cq.reclamer(interaction.user.id)

        if resultat["deja_reclame"]:
            heures = resultat["temps_avant_prochain"] // 3600
            minutes = (resultat["temps_avant_prochain"] % 3600) // 60
            embed = discord.Embed(
                title="✅ Déjà réclamée aujourd'hui",
                description=(
                    f"Tu as déjà récupéré ta récompense du jour.\n\n"
                    f"Série actuelle : **{resultat['streak']} jour(s)**\n"
                    f"Prochaine récompense dans **{heures}h{minutes:02d}**."
                ),
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        recompense = resultat["recompense"]
        streak = resultat["streak"]
        serie_cassee = resultat["streak_precedente"] > 0 and resultat["streak_precedente"] != streak - 1

        embed = discord.Embed(
            title=f"🎁 Récompense du jour {streak} !",
            description=cq.texte_recompense(recompense),
            color=discord.Color.gold(),
        )
        if serie_cassee:
            embed.add_field(
                name="⚠️ Série recommencée",
                value=f"Ta série précédente ({resultat['streak_precedente']} jour(s)) a été interrompue — repartie à 1.",
                inline=False,
            )
        if streak < cq.PLAFOND_SERIE:
            recompense_demain = cq.calculer_recompense(streak + 1)
            embed.add_field(
                name=f"Demain (jour {streak + 1})",
                value=cq.texte_recompense(recompense_demain),
                inline=False,
            )
        else:
            embed.set_footer(text="Palier maximum atteint — récompense fixe désormais, plus un bonus d'objet tous les 7 jours.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ConnexionQuotidienneCog(bot))
