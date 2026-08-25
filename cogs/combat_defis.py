"""Cog : combat-2v2-equipe, combat-2v2, defier (+ leurs Vues VueDefiDouble/VueDefi).
Douzième lot du découpage en Cogs — voir cogs/admin_economie.py pour le contexte général.

VueDefiDouble/VueDefi référençaient la variable globale `bot` de main.py dans leurs
callbacks de bouton — plutôt qu'un `import main` dans chaque callback, `bot` est
maintenant passé explicitement au constructeur (injection de dépendance classique) et
stocké en `self.bot`, ce qui est plus propre et testable qu'une référence globale.
"""

import discord
from discord import app_commands
from discord.ext import commands

import combat as combat_module
import combat_2v2 as combat_2v2_module
import database


class VueDefiDouble(discord.ui.View):
    """1v1 en format double combat (2 Pokémon actifs chacun, équipe complète) — même
    principe que VueDefi, adversaire ciblé seul habilité à répondre."""

    def __init__(self, challenger: discord.Member, adversaire: discord.Member, bot: commands.Bot):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.adversaire = adversaire
        self.bot = bot
        self.resolu = False
        self.message = None

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.adversaire.id:
            await interaction.response.send_message("Ce défi ne te concerne pas !", ephemeral=True)
            return
        if self.resolu:
            await interaction.response.send_message("Ce défi n'est plus disponible.", ephemeral=True)
            return

        equipe_adv = combat_module.preparer_equipe_pour_combat(self.adversaire.id)
        if len(equipe_adv) < 2:
            self.resolu = True
            await interaction.response.edit_message(
                content=(
                    f"❌ {self.adversaire.display_name} a besoin d'au moins 2 Pokémon dans son "
                    f"équipe de combat pour un 1v1 en double."
                ),
                view=None,
            )
            return

        self.resolu = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {self.adversaire.mention} accepte le défi en double ! Le combat commence...",
            view=self,
        )
        await combat_2v2_module.demarrer_combat_double(self.bot, self.challenger, self.adversaire, interaction.channel)
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
            return
        self.resolu = True
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content="⌛ Défi expiré — personne n'a répondu à temps.", view=self)
            except discord.HTTPException:
                pass


class VueDefi(discord.ui.View):
    """Vue visible par tout le monde, mais seul l'adversaire ciblé peut accepter/refuser."""

    def __init__(self, challenger: discord.Member, adversaire: discord.Member, bot: commands.Bot):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.adversaire = adversaire
        self.bot = bot
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
        await combat_module.demarrer_combat(self.bot, self.challenger, self.adversaire, interaction.channel)
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


class CombatDefisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="combat-2v2-equipe", description="Lance un lobby de combat 2v2 en équipe (4 joueurs, 2 équipes de 2)")
    async def combat_2v2(self, interaction: discord.Interaction):
        await combat_2v2_module.lancer_lobby_2v2(self.bot, interaction)

    @app_commands.command(name="combat-2v2", description="Défie un joueur en 1v1 format double combat (équipe de 6, 2 actifs chacun)")
    async def defier_double(self, interaction: discord.Interaction, adversaire: discord.Member):
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
        if len(equipe_challenger) < 2:
            await interaction.response.send_message(
                "❌ Il te faut au moins 2 Pokémon dans ton équipe de combat pour un 1v1 en double "
                "(`/equipe-combat`) !",
                ephemeral=True,
            )
            return

        vue_defi = VueDefiDouble(interaction.user, adversaire, self.bot)
        await interaction.response.send_message(
            f"⚔️ {adversaire.mention}, **{interaction.user.display_name}** te défie en **1v1 double combat** "
            f"(équipe complète, 2 Pokémon actifs chacun) ! Tu as 60 secondes pour accepter.",
            view=vue_defi,
        )
        vue_defi.message = await interaction.original_response()

    @app_commands.command(name="defier", description="Défie un autre joueur en combat Pokémon")
    async def defier(self, interaction: discord.Interaction, adversaire: discord.Member):
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

        vue_defi = VueDefi(interaction.user, adversaire, self.bot)
        await interaction.response.send_message(
            f"⚔️ {adversaire.mention}, **{interaction.user.display_name}** te défie en combat ! Tu as 60 secondes pour accepter.",
            view=vue_defi,
        )
        vue_defi.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(CombatDefisCog(bot))
