"""Mini-jeu solo 'Plus ou Moins' — devine si le PC de base du prochain Pokémon est plus
haut ou plus bas que celui affiché, enchaîne les bonnes réponses pour faire une série.
Pur fun, seul le record personnel (best-effort, pas une vraie récompense) est gardé.
"""

import random

import discord

import database
from pokemon_data import POKEDEX, sprite_pokemon


def tirer_pokemon_pc() -> dict:
    return random.choice(POKEDEX)


def construire_embed_manche(actuel: dict, mystere: dict, streak: int) -> discord.Embed:
    embed = discord.Embed(title="📊 Plus ou Moins", color=discord.Color.blue())
    embed.add_field(name=f"Actuel — {actuel['nom']}", value=f"PC : **{actuel['base_pc']}**", inline=True)
    embed.add_field(name=f"Mystère — {mystere['nom']}", value="PC : **???**", inline=True)
    embed.description = "Le prochain a un PC de base plus **haut** ou plus **bas** ?"
    embed.set_footer(text=f"Série actuelle : {streak}")
    sprite = sprite_pokemon(mystere)
    if sprite:
        embed.set_thumbnail(url=sprite)
    return embed


class VuePlusOuMoins(discord.ui.View):
    def __init__(self, user_id: int, actuel: dict, mystere: dict, streak: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.actuel = actuel
        self.mystere = mystere
        self.streak = streak

        bouton_plus = discord.ui.Button(label="Plus haut", emoji="⬆️", style=discord.ButtonStyle.success)
        bouton_plus.callback = self._creer_callback(True)
        self.add_item(bouton_plus)

        bouton_moins = discord.ui.Button(label="Plus bas", emoji="⬇️", style=discord.ButtonStyle.danger)
        bouton_moins.callback = self._creer_callback(False)
        self.add_item(bouton_moins)

    def _creer_callback(self, veut_plus: bool):
        async def callback(interaction: discord.Interaction):
            await self._on_choix(interaction, veut_plus)

        return callback

    async def _on_choix(self, interaction: discord.Interaction, veut_plus: bool):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta partie !", ephemeral=True)
            return

        pc_actuel = self.actuel["base_pc"]
        pc_mystere = self.mystere["base_pc"]
        correct = (pc_mystere >= pc_actuel) if veut_plus else (pc_mystere <= pc_actuel)

        if correct:
            self.streak += 1
            nouveau_mystere = tirer_pokemon_pc()

            embed = discord.Embed(title="📊 Plus ou Moins — Bonne pioche !", color=discord.Color.green())
            embed.add_field(
                name="Résultat",
                value=f"**{self.mystere['nom']}** avait {pc_mystere} PC (contre {pc_actuel} pour {self.actuel['nom']}).",
                inline=False,
            )
            embed.add_field(name=f"Actuel — {self.mystere['nom']}", value=f"PC : **{pc_mystere}**", inline=True)
            embed.add_field(name=f"Mystère — {nouveau_mystere['nom']}", value="PC : **???**", inline=True)
            embed.set_footer(text=f"Série actuelle : {self.streak}")
            sprite = sprite_pokemon(nouveau_mystere)
            if sprite:
                embed.set_thumbnail(url=sprite)

            nouvelle_vue = VuePlusOuMoins(self.user_id, self.mystere, nouveau_mystere, self.streak)
            await interaction.response.edit_message(embed=embed, view=nouvelle_vue)
        else:
            record = database.obtenir_record_plus_ou_moins(self.user_id)
            nouveau_record = self.streak > record
            if nouveau_record:
                database.definir_record_plus_ou_moins(self.user_id, self.streak)

            embed = discord.Embed(title="📊 Plus ou Moins — Partie terminée", color=discord.Color.red())
            embed.add_field(
                name="Perdu !",
                value=f"**{self.mystere['nom']}** avait {pc_mystere} PC (contre {pc_actuel} pour {self.actuel['nom']}).",
                inline=False,
            )
            texte_score = f"Série de **{self.streak}**"
            texte_score += " — 🏆 Nouveau record !" if nouveau_record else f" (ton record : {record})"
            embed.add_field(name="Score final", value=texte_score, inline=False)
            await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
