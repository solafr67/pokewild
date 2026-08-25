"""Cog : roguelike (mini-jeu indépendant) + marketplace. Quatrième lot du découpage en
Cogs — voir cogs/admin_economie.py pour le contexte général.

Lot particulièrement simple : chaque commande ne fait qu'un seul appel de délégation vers
roguelike.py / marketplace.py, toute la logique vit déjà dans ces modules dédiés.
"""

import discord
from discord import app_commands
from discord.ext import commands

import marketplace as marketplace_module
import roguelike as roguelike_module


class MinijeuxMarketplaceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="roguelike",
        description="Lance une run du mini-jeu roguelike (mini-jeu indépendant, aucune récompense liée au bot)",
    )
    async def roguelike_cmd(self, interaction: discord.Interaction):
        await roguelike_module.lancer_run(self.bot, interaction)

    @app_commands.command(name="roguelike-abandonner", description="Abandonne ta run roguelike en cours")
    async def roguelike_abandonner_cmd(self, interaction: discord.Interaction):
        await roguelike_module.abandonner_run(interaction)

    @app_commands.command(name="roguelike-classement", description="Classement du meilleur étage atteint en roguelike")
    async def roguelike_classement_cmd(self, interaction: discord.Interaction):
        await roguelike_module.afficher_classement(interaction)

    @app_commands.command(name="vendre-pokemon", description="Met un de tes Pokémon en vente sur le marketplace (prix fixe)")
    async def vendre_pokemon(self, interaction: discord.Interaction):
        await marketplace_module.lancer_vente(interaction)

    @app_commands.command(name="marketplace-recherche", description="Cherche une annonce active du marketplace par nom de Pokémon")
    async def marketplace_recherche_cmd(self, interaction: discord.Interaction, nom: str):
        await marketplace_module.rechercher_annonces(interaction, nom)

    @app_commands.command(name="marketplace-historique", description="Affiche ton historique personnel de ventes et d'achats sur le marketplace")
    async def marketplace_historique_cmd(self, interaction: discord.Interaction):
        await marketplace_module.afficher_historique(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(MinijeuxMarketplaceCog(bot))
