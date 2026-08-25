"""Cog : passe-saison, annonce, event. Dixième lot du découpage en Cogs — voir
cogs/admin_economie.py pour le contexte général.

Les 14 commandes restantes dans main.py après ce lot (setup-classement, setup-pokestop,
force-pokestop-dore, stop-pokestop-dore, combat-2v2-equipe, combat-2v2, defier,
force-dresseur, force-raid, force-spawn, force-spawn-shiny, meteo-forcer, pause-spawns,
resume-spawns) sont d'une nature différente des lots précédents : elles n'appellent pas
des modules externes, mais des fonctions/objets qui SONT l'orchestration des boucles de
fond elles-mêmes (rafraichir_classement, demarrer_nouveau_raid, demarrer_nouveau_dresseur,
envoyer_spawn, declencher_meteo, les objets tasks.Loop boucle_spawn_classique/vip, l'état
partagé etat_jeu...) — toutes définies dans main.py. Les extraire proprement demanderait
soit de migrer aussi les boucles (refactor plus large, à faire à part), soit de multiplier
les `import main` locaux (fonctionnel mais disperse les références vers main.py au lieu de
les concentrer). Décision : laisser ce noyau d'orchestration dans main.py pour l'instant —
c'est une architecture standard pour un bot Discord (fichier principal = boucles + lancement,
Cogs = tout le reste), pas une étape bâclée.
"""

import discord
from discord import app_commands
from discord.ext import commands

import evenements as evenements_module
import saison as saison_module


class SaisonAnnoncesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="passe-saison", description="Affiche ta progression dans le passe saisonnier")
    async def passe_saison_cmd(self, interaction: discord.Interaction):
        embed = saison_module.construire_embed_statut(interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="annonce", description="[Admin] Poste une annonce stylisée dans un channel choisi")
    @app_commands.checks.has_permissions(administrator=True)
    async def annonce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        titre: str,
        message: str,
        couleur: str = None,
    ):
        couleurs_disponibles = {
            "bleu": discord.Color.blue(),
            "vert": discord.Color.green(),
            "rouge": discord.Color.red(),
            "orange": discord.Color.orange(),
            "or": discord.Color.gold(),
            "violet": discord.Color.purple(),
        }
        couleur_finale = couleurs_disponibles.get((couleur or "").lower(), discord.Color.blurple())

        embed = discord.Embed(title=titre, description=message.replace("\\n", "\n"), color=couleur_finale)
        embed.set_footer(text=f"Annonce de {interaction.user.display_name}")

        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Annonce postée dans {channel.mention}.", ephemeral=True)

    @app_commands.command(name="event", description="[Admin] Lance un event serveur (boost, défi collectif, chasse aux shiny)")
    @app_commands.checks.has_permissions(administrator=True)
    async def event_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "🎉 Quel type d'event veux-tu lancer ?", view=evenements_module.VueChoixEvent(), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SaisonAnnoncesCog(bot))
