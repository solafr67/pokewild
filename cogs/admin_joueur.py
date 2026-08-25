"""Cog : give-boost, finir-exploration, finir-incubation, setup-centre-exploration,
abandonner-combat, give-pokemon. Huitième lot du découpage en Cogs — voir
cogs/admin_economie.py pour le contexte général.

force-dresseur, force-raid, force-spawn-shiny restent dans main.py pour l'instant : ils
appellent demarrer_nouveau_dresseur()/demarrer_nouveau_raid()/envoyer_spawn(), des
fonctions qui vivent encore dans main.py lui-même (liées aux boucles de fond) — à
extraire avec ce lot-là, plus tard.
"""

import discord
from discord import app_commands
from discord.ext import commands

import combat as combat_module
import config
import database
import exploration as exploration_module
import journal
from pokemon_data import calculer_pc_derive, obtenir_pokemon_par_nom, tirer_ivs


class AdminJoueurCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="give-boost", description="[Admin] Offre un boost temporaire gratuit à un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        type_boost=[
            app_commands.Choice(name="XP", value="xp"),
            app_commands.Choice(name="Argent", value="argent"),
            app_commands.Choice(name="Shiny", value="shiny"),
        ],
        duree=[
            app_commands.Choice(name="1h", value="1h"),
            app_commands.Choice(name="6h", value="6h"),
            app_commands.Choice(name="24h", value="24h"),
        ],
    )
    async def give_boost(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        type_boost: app_commands.Choice[str],
        duree: app_commands.Choice[str],
    ):
        duree_secondes = config.DUREES_BOOST[duree.value]
        expiration = database.activer_boost(membre.id, type_boost.value, duree_secondes)
        journal.logger(f"🛠️ <@{interaction.user.id}> a offert un boost {type_boost.value} ({duree.value}) à <@{membre.id}>.")
        await interaction.response.send_message(
            f"✅ Boost **{type_boost.name} ({duree.name})** offert à {membre.mention} — expire <t:{expiration}:R>."
        )

    @app_commands.command(name="finir-exploration", description="[Admin] Termine immédiatement l'exploration d'un joueur (sans réduire la récompense)")
    @app_commands.checks.has_permissions(administrator=True)
    async def finir_exploration(self, interaction: discord.Interaction, membre: discord.Member, emplacement: int = 1):
        succes = database.forcer_fin_exploration(membre.id, emplacement)
        if not succes:
            await interaction.response.send_message(
                f"ℹ️ {membre.mention} n'a aucune exploration en cours sur l'emplacement {emplacement}.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"✅ Exploration de {membre.mention} (emplacement {emplacement}) terminée immédiatement — "
            f"la récompense reste calculée sur la durée d'origine. Le joueur peut la récupérer via `/exploration`.",
            ephemeral=True,
        )

    @app_commands.command(name="finir-incubation", description="[Admin] Fait éclore immédiatement l'œuf en incubation d'un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    async def finir_incubation(self, interaction: discord.Interaction, membre: discord.Member):
        succes = database.forcer_fin_incubation(membre.id)
        if not succes:
            await interaction.response.send_message(
                f"ℹ️ {membre.mention} n'a aucun œuf en incubation actuellement.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"✅ L'œuf de {membre.mention} est prêt à éclore immédiatement — "
            f"le joueur peut le récupérer via le Laboratoire.",
            ephemeral=True,
        )

    @app_commands.command(name="setup-centre-exploration", description="[Admin] Poste ou remet à jour le message fixe du Centre des Explorations dans ce channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_centre_exploration(self, interaction: discord.Interaction):
        embed = exploration_module.construire_embed_centre()
        message = await interaction.channel.send(embed=embed, view=exploration_module.VueCentreExploration())
        database.definir_parametre("exploration_message_id", str(message.id))
        await interaction.response.send_message("✅ Centre des Explorations posté dans ce channel.", ephemeral=True)

    @app_commands.command(name="abandonner-combat", description="Abandonne ton combat en cours (défaite par forfait)")
    async def abandonner_combat(self, interaction: discord.Interaction):
        combat = database.combat_en_cours_pour_joueur(interaction.user.id)
        if not combat:
            await interaction.response.send_message("Tu n'as pas de combat en cours.", ephemeral=True)
            return
        await interaction.response.send_message("🏳️ Tu as abandonné. Défaite enregistrée.", ephemeral=True)
        await combat_module.resoudre_abandon(self.bot, combat["id"], interaction.user.id)

    @app_commands.command(name="give-pokemon", description="[Admin] Donne un Pokémon directement à un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    async def give_pokemon(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        nom: str,
        pc: int = None,
        shiny: bool = False,
    ):
        pokemon = obtenir_pokemon_par_nom(nom)
        if not pokemon:
            await interaction.response.send_message(
                f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True
            )
            return

        ivs = tirer_ivs()
        if pc is not None:
            pc = max(1, min(pc, config.PC_MAXIMUM))
        else:
            pc = calculer_pc_derive(pokemon, ivs, 50)

        database.ajouter_capture(membre.id, pokemon["nom"], pc, shiny=shiny, ivs=ivs)
        prefixe = "✨ " if shiny else ""
        journal.logger(f"🛠️ <@{interaction.user.id}> a donné {prefixe}**{pokemon['nom']}** ({pc} PC) à <@{membre.id}> (/give-pokemon).")
        await interaction.response.send_message(
            f"✅ {prefixe}**{pokemon['nom']}** ({pc} PC) donné à {membre.mention}."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminJoueurCog(bot))
