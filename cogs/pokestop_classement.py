"""Cog : setup-classement, setup-pokestop, force-pokestop-dore, stop-pokestop-dore.
Onzième lot du découpage en Cogs — voir cogs/admin_economie.py pour le contexte général.

Ces commandes dépendent de fonctions qui vivent encore dans main.py lui-même
(rafraichir_classement, construire_embed_pokestop, VuePokestop,
poster_message_pokestop_si_absent — toutes liées aux boucles de fond pas encore
migrées). Import de `main` fait localement à l'intérieur de chaque commande (pas au
niveau du module) : sûr car ce Cog n'est chargé (bot.load_extension, dans on_ready)
qu'une fois main.py entièrement exécuté — pas un vrai import circulaire — mais un
import en tête de fichier échouerait plus tôt dans la séquence de démarrage.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

import config
import database
import etat_jeu
import journal


class PokestopClassementCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup-classement", description="[Admin] Force le rafraîchissement du message de classement")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_classement(self, interaction: discord.Interaction):
        import sys
        main_module = sys.modules["__main__"]

        await main_module.rafraichir_classement()
        await interaction.response.send_message("✅ Classement rafraîchi.", ephemeral=True)

    @app_commands.command(name="setup-pokestop", description="[Admin] Poste le message fixe du PokéStop dans ce channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_pokestop(self, interaction: discord.Interaction):
        import sys
        main_module = sys.modules["__main__"]

        embed = main_module.construire_embed_pokestop()
        await interaction.response.send_message(embed=embed, view=main_module.VuePokestop())

    @app_commands.command(
        name="force-pokestop-dore",
        description="[Admin] Déclenche immédiatement l'Heure de pointe PokéStop pour 30 minutes",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def force_pokestop_dore(self, interaction: discord.Interaction):
        import sys
        main_module = sys.modules["__main__"]

        tz = ZoneInfo("Europe/Paris")
        maintenant_dt = datetime.now(tz)
        database.definir_parametre("pokestop_event_date", maintenant_dt.date().isoformat())
        database.definir_parametre("pokestop_event_debut", str(int(maintenant_dt.timestamp())))
        etat_jeu.heure_de_pointe_pokestop_active = True
        await main_module.poster_message_pokestop_si_absent()

        journal.logger(f"🛠️ <@{interaction.user.id}> a déclenché l'Heure de pointe PokéStop manuellement (/force-pokestop-dore).")
        await interaction.response.send_message("🔥 **Heure de pointe PokéStop** déclenchée pour 30 minutes !")

        channel = self.bot.get_channel(config.CHANNEL_POKESTOP_ID) if getattr(config, "CHANNEL_POKESTOP_ID", None) else None
        if channel and channel.id != interaction.channel_id:
            try:
                await channel.send("🔥 **Heure de pointe au PokéStop !** Récompenses doublées pendant 30 minutes !")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @app_commands.command(
        name="stop-pokestop-dore",
        description="[Admin] Coupe l'Heure de pointe PokéStop en cours, sans en reprogrammer une autre aujourd'hui",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def stop_pokestop_dore(self, interaction: discord.Interaction):
        import sys
        main_module = sys.modules["__main__"]

        if not etat_jeu.heure_de_pointe_pokestop_active:
            await interaction.response.send_message("Il n'y a pas d'Heure de pointe en cours.", ephemeral=True)
            return

        # On pousse le créneau enregistré dans le passé (fin < maintenant) sans toucher à la
        # date du jour : la boucle voit "déjà fini" au prochain passage et ne retire PAS un
        # nouveau créneau aléatoire pour le reste de la journée.
        tz = ZoneInfo("Europe/Paris")
        maintenant_dt = datetime.now(tz)
        debut_dans_le_passe = maintenant_dt - timedelta(seconds=config.DUREE_HEURE_DE_POINTE_POKESTOP + 60)
        database.definir_parametre("pokestop_event_date", maintenant_dt.date().isoformat())
        database.definir_parametre("pokestop_event_debut", str(int(debut_dans_le_passe.timestamp())))

        etat_jeu.heure_de_pointe_pokestop_active = False
        await main_module.poster_message_pokestop_si_absent()

        journal.logger(f"🛠️ <@{interaction.user.id}> a coupé l'Heure de pointe PokéStop manuellement (/stop-pokestop-dore).")
        await interaction.response.send_message("🛑 **Heure de pointe PokéStop** coupée.")


async def setup(bot: commands.Bot):
    await bot.add_cog(PokestopClassementCog(bot))
