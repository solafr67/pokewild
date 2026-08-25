"""Cog : force-dresseur, force-raid, force-spawn-shiny, force-spawn, meteo-forcer,
pause-spawns, resume-spawns. Treizième et dernier lot du découpage en Cogs — voir
cogs/admin_economie.py pour le contexte général.

Ces commandes appellent des fonctions qui vivent encore dans main.py (les vraies
fonctions d'orchestration des boucles de fond : demarrer_nouveau_dresseur,
demarrer_nouveau_raid, envoyer_spawn, declencher_meteo) ou manipulent directement les
objets tasks.Loop (boucle_spawn_classique, boucle_spawn_vip). Import de `main` fait
localement dans chaque commande — voir la note de tête dans pokestop_classement.py pour
l'explication de pourquoi c'est sûr à cet endroit précis.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import config
import dresseurs as dresseurs_module
import meteo
from pokemon_data import POIDS_RARETE_CLASSIQUE, POIDS_RARETE_VIP, obtenir_pokemon_par_nom


class AdminSpawnsMeteoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="force-dresseur", description="[Admin] Fait apparaître un dresseur immédiatement dans le channel Aventure")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        archetype=[
            app_commands.Choice(name=a["nom"], value=a["nom"])
            for a in dresseurs_module.ARCHETYPES + dresseurs_module.ARCHETYPES_DUO
        ]
    )
    async def force_dresseur(self, interaction: discord.Interaction, archetype: app_commands.Choice[str] | None = None):
        import sys
        main_module = sys.modules["__main__"]

        channel_id = getattr(config, "CHANNEL_AVENTURE_ID", None)
        if not channel_id:
            await interaction.response.send_message("❌ CHANNEL_AVENTURE_ID n'est pas configuré.", ephemeral=True)
            return
        succes = await main_module.demarrer_nouveau_dresseur(
            channel_id, ignorer_verification=True, archetype_force=archetype.value if archetype else None
        )
        await interaction.response.send_message(
            "✅ Dresseur envoyé !" if succes else "❌ Impossible d'envoyer le dresseur (channel introuvable).", ephemeral=True
        )

    @app_commands.command(name="force-raid", description="[Admin] Démarre un raid immédiatement")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        channel=[
            app_commands.Choice(name="Classique", value="classique"),
            app_commands.Choice(name="VIP", value="vip"),
        ]
    )
    async def force_raid(
        self,
        interaction: discord.Interaction,
        channel: app_commands.Choice[str],
        etoiles: app_commands.Range[int, 1, 5] = None,
        nom: str = None,
    ):
        import sys
        main_module = sys.modules["__main__"]

        boss_force = None
        if nom:
            boss_force = obtenir_pokemon_par_nom(nom)
            if not boss_force:
                await interaction.response.send_message(f"❌ Pokémon **{nom}** introuvable.", ephemeral=True)
                return

        channel_id = (
            config.CHANNEL_SPAWN_CLASSIQUE_ID if channel.value == "classique" else config.CHANNEL_SPAWN_VIP_ID
        )

        succes = await main_module.demarrer_nouveau_raid(channel_id, etoiles=etoiles, boss_force=boss_force)
        if succes:
            await interaction.response.send_message(f"✅ Raid démarré dans le channel **{channel.name}** !", ephemeral=True)
        else:
            await interaction.response.send_message(
                "⚠️ Impossible : un raid est déjà en cours dans ce channel, ou le channel est introuvable.",
                ephemeral=True,
            )

    @app_commands.command(
        name="force-spawn-shiny",
        description="[Admin] Fait apparaître un Pokémon shiny garanti dans un channel de spawn",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        channel=[
            app_commands.Choice(name="Classique", value="classique"),
            app_commands.Choice(name="VIP", value="vip"),
        ]
    )
    async def force_spawn_shiny(
        self,
        interaction: discord.Interaction,
        channel: app_commands.Choice[str],
        nom: str = None,
    ):
        import sys
        main_module = sys.modules["__main__"]

        if nom:
            pokemon = obtenir_pokemon_par_nom(nom)
            if not pokemon:
                await interaction.response.send_message(
                    f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True
                )
                return
        else:
            pokemon = None  # tirage aléatoire classique dans envoyer_spawn

        if channel.value == "classique":
            channel_id, poids, nom_channel = config.CHANNEL_SPAWN_CLASSIQUE_ID, POIDS_RARETE_CLASSIQUE, "classique"
        else:
            channel_id, poids, nom_channel = config.CHANNEL_SPAWN_VIP_ID, POIDS_RARETE_VIP, "VIP"

        await main_module.envoyer_spawn(channel_id, poids, nom_channel, pokemon_force=pokemon, force_shiny=True)
        await interaction.response.send_message(
            f"✨ Spawn shiny garanti envoyé dans le channel **{channel.name}** !", ephemeral=True
        )

    @app_commands.command(
        name="force-spawn",
        description="[Admin] Fait apparaître un Pokémon (aléatoire ou précis, non-shiny) dans un channel de spawn",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        channel=[
            app_commands.Choice(name="Classique", value="classique"),
            app_commands.Choice(name="VIP", value="vip"),
        ]
    )
    async def force_spawn(
        self,
        interaction: discord.Interaction,
        channel: app_commands.Choice[str],
        nom: str = None,
    ):
        import sys
        main_module = sys.modules["__main__"]

        if nom:
            pokemon = obtenir_pokemon_par_nom(nom)
            if not pokemon:
                await interaction.response.send_message(
                    f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True
                )
                return
        else:
            pokemon = None  # tirage aléatoire classique dans envoyer_spawn

        if channel.value == "classique":
            channel_id, poids, nom_channel = config.CHANNEL_SPAWN_CLASSIQUE_ID, POIDS_RARETE_CLASSIQUE, "classique"
        else:
            channel_id, poids, nom_channel = config.CHANNEL_SPAWN_VIP_ID, POIDS_RARETE_VIP, "VIP"

        await main_module.envoyer_spawn(channel_id, poids, nom_channel, pokemon_force=pokemon)
        texte_pokemon = f"**{pokemon['nom']}**" if pokemon else "aléatoire"
        await interaction.response.send_message(
            f"✅ Spawn {texte_pokemon} envoyé dans le channel **{channel.name}** !", ephemeral=True
        )

    @app_commands.command(name="meteo-forcer", description="[Admin] Déclenche une météo précise immédiatement")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        type_meteo=[app_commands.Choice(name=m["nom"], value=m["nom"]) for m in meteo.METEOS]
    )
    async def meteo_forcer(
        self,
        interaction: discord.Interaction,
        type_meteo: app_commands.Choice[str],
        duree_minutes: int = None,
    ):
        import sys
        main_module = sys.modules["__main__"]

        meteo_choisie = next((m for m in meteo.METEOS if m["nom"] == type_meteo.value), None)
        if meteo_choisie is None:
            await interaction.response.send_message("❌ Météo introuvable.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ Météo **{meteo_choisie['nom']}** déclenchée !", ephemeral=True
        )
        self.bot.loop.create_task(main_module.declencher_meteo(meteo_choisie, duree_minutes=duree_minutes))

    @app_commands.command(name="pause-spawns", description="[Admin] Met en pause les spawns")
    @app_commands.checks.has_permissions(administrator=True)
    async def pause_spawns(self, interaction: discord.Interaction, minutes: int = 0):
        import sys
        main_module = sys.modules["__main__"]

        main_module.boucle_spawn_classique.stop()
        main_module.boucle_spawn_vip.stop()

        if minutes > 0:
            self.bot.loop.create_task(self._reprendre_spawns_apres_delai(minutes * 60))
            await interaction.response.send_message(
                f"⏸️ Spawns mis en pause pour **{minutes} minute(s)**. Reprise automatique ensuite."
            )
        else:
            await interaction.response.send_message(
                "⏸️ Spawns mis en pause **indéfiniment**. Utilise `/resume-spawns` pour les relancer."
            )

    async def _reprendre_spawns_apres_delai(self, secondes: int):
        import sys
        main_module = sys.modules["__main__"]

        await asyncio.sleep(secondes)
        if not main_module.boucle_spawn_classique.is_running():
            main_module.boucle_spawn_classique.start()
        if not main_module.boucle_spawn_vip.is_running():
            main_module.boucle_spawn_vip.start()

    @app_commands.command(name="resume-spawns", description="[Admin] Relance les spawns s'ils sont en pause")
    @app_commands.checks.has_permissions(administrator=True)
    async def resume_spawns(self, interaction: discord.Interaction):
        import sys
        main_module = sys.modules["__main__"]

        deja_actifs = main_module.boucle_spawn_classique.is_running() and main_module.boucle_spawn_vip.is_running()

        if not main_module.boucle_spawn_classique.is_running():
            main_module.boucle_spawn_classique.start()
        if not main_module.boucle_spawn_vip.is_running():
            main_module.boucle_spawn_vip.start()

        if deja_actifs:
            await interaction.response.send_message("ℹ️ Les spawns tournaient déjà.", ephemeral=True)
        else:
            await interaction.response.send_message("▶️ Spawns relancés.")


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminSpawnsMeteoCog(bot))
