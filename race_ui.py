import discord

import database
import journal
import races
from pokemon_data import COULEUR_RARETE, EMOJI_RARETE


def construire_embed_race(user_id: int) -> discord.Embed:
    race_nom, pity = database.obtenir_race(user_id)
    nb_cristaux = database.obtenir_inventaire_balls(user_id).get("cristal_mutation", 0)

    if race_nom is None:
        embed = discord.Embed(
            title="🧬 Ta Race de dresseur",
            description=(
                "Tu n'as pas encore de Race ! Obtiens un 🔮 **Cristal de Mutation** au "
                "Centre des Explorations pour en tirer une au hasard."
            ),
            color=discord.Color.dark_grey(),
        )
    else:
        race = races.obtenir_race_par_nom(race_nom)
        emoji = EMOJI_RARETE[race["palier"]]
        embed = discord.Embed(
            title=f"🧬 Ta Race : {emoji} {race['nom']}",
            description=f"*{race['description']}*\n\n{races.texte_bonus(race['bonus'])}",
            color=COULEUR_RARETE[race["palier"]],
        )

    embed.add_field(name="🔮 Cristaux de Mutation possédés", value=str(nb_cristaux), inline=True)
    embed.add_field(name="Pity (rerolls sans rare+)", value=f"{pity}/10", inline=True)
    return embed


class VueRace(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        nb_cristaux = database.obtenir_inventaire_balls(user_id).get("cristal_mutation", 0)

        bouton = discord.ui.Button(
            label=f"Utiliser un Cristal de Mutation ({nb_cristaux})",
            emoji="🔮",
            style=discord.ButtonStyle.primary,
            disabled=nb_cristaux <= 0,
        )
        bouton.callback = self._on_reroll
        self.add_item(bouton)

    async def _on_reroll(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta Race !", ephemeral=True)
            return

        if not database.retirer_ball(self.user_id, "cristal_mutation"):
            await interaction.response.send_message("Tu n'as plus de Cristal de Mutation !", ephemeral=True)
            return

        _, pity_actuel = database.obtenir_race(self.user_id)
        nouvelle_race, nouveau_pity = races.tirer_race(pity_actuel)
        database.definir_race(self.user_id, nouvelle_race["nom"], nouveau_pity)
        journal.logger(
            f"🔮 <@{self.user_id}> a utilisé un Cristal de Mutation — nouvelle Race : "
            f"**{nouvelle_race['nom']}** ({nouvelle_race['palier']})."
        )

        emoji = EMOJI_RARETE[nouvelle_race["palier"]]
        embed = discord.Embed(
            title=f"🔮 Nouvelle Race obtenue : {emoji} {nouvelle_race['nom']} !",
            description=f"*{nouvelle_race['description']}*\n\n{races.texte_bonus(nouvelle_race['bonus'])}",
            color=COULEUR_RARETE[nouvelle_race["palier"]],
        )
        await interaction.response.edit_message(embed=embed, view=None)
