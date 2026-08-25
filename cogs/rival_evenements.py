"""Cog : roster-raids, reset-cooldown-gladio, gladio, parrainage, defi-draft, badges-arene,
force-arene, force-repaire. Septième lot du découpage en Cogs — voir cogs/admin_economie.py
pour le contexte général.
"""

import discord
from discord import app_commands
from discord.ext import commands

import arene as arene_module
import config
import database
import draft_pvp as draft_pvp_module
import journal
import pnj
import repaires as repaires_module
from pokemon_data import EMOJI_TYPES, obtenir_roster_raid


class RivalEvenementsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="roster-raids", description="Vois quels Pokémon peuvent apparaître en raid actuellement, par palier d'étoiles")
    async def roster_raids_cmd(self, interaction: discord.Interaction):
        lignes = []
        for etoiles in (1, 2, 3, 4, 5):
            noms = obtenir_roster_raid(etoiles)
            lignes.append(f"{'⭐' * etoiles} : {', '.join(noms) if noms else '*(aucun défini pour ce palier)*'}")

        embed = discord.Embed(
            title="🐲 Pokémon actuellement en raid",
            description="\n".join(lignes),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Le boss précis d'un raid est tiré au hasard parmi ceux de son palier d'étoiles.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="reset-cooldown-gladio", description="[Admin] Réinitialise le cooldown de défi contre Gladio d'un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_cooldown_gladio(self, interaction: discord.Interaction, membre: discord.Member):
        database.reinitialiser_defi_gladio(membre.id)
        journal.logger(f"🛠️ <@{interaction.user.id}> a réinitialisé le cooldown Gladio de <@{membre.id}> (/reset-cooldown-gladio).")
        await interaction.response.send_message(f"✅ Cooldown Gladio réinitialisé pour {membre.mention}.")

    @app_commands.command(name="gladio", description="Découvre où tu en es avec Gladio, ton rival")
    async def gladio_cmd(self, interaction: discord.Interaction):
        statut = pnj.obtenir_statut(interaction.user.id)
        embed = discord.Embed(
            title=f"{pnj.EMOJI_RIVAL} {pnj.NOM_RIVAL} — ta relation",
            description=statut["description"],
            color=discord.Color.dark_grey(),
        )
        embed.set_thumbnail(url=pnj.IMAGE_RIVAL)
        embed.add_field(name="Palier actuel", value=statut["palier"].capitalize(), inline=True)
        embed.add_field(name="Interactions", value=str(statut["compteur"]), inline=True)
        if statut["prochain_seuil"] is not None:
            embed.add_field(
                name="Prochain palier",
                value=f"Dans **{statut['prochain_seuil'] - statut['compteur']}** interaction(s) de plus",
                inline=False,
            )
        else:
            embed.add_field(name="Prochain palier", value="Tu as atteint le palier maximum !", inline=False)
        embed.set_footer(text="La familiarité décroît lentement en cas de longue inactivité.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="parrainage", description="Vois combien de personnes tu as invitées sur le serveur, et ta prochaine récompense")
    async def parrainage_cmd(self, interaction: discord.Interaction):
        total = database.compter_parrainages(interaction.user.id)
        palier_actuel = total // config.PARRAINAGE_PALIER
        prochain_seuil = (palier_actuel + 1) * config.PARRAINAGE_PALIER
        restant = prochain_seuil - total

        objets_txt = ", ".join(f"{q}× {b}" for b, q in config.PARRAINAGE_RECOMPENSE_BALLS)
        embed = discord.Embed(
            title="🤝 Parrainage",
            description=(
                f"Tu as **{total}** invitation(s) confirmée(s) (le filleul est resté au moins "
                f"{config.PARRAINAGE_DELAI_JOURS} jours sur le serveur).\n\n"
                f"Tous les **{config.PARRAINAGE_PALIER}** invitations confirmées, tu débloques : "
                f"**{config.PARRAINAGE_RECOMPENSE_DOLLARS} Poké Dollars** + {objets_txt}.\n\n"
                f"Plus que **{restant}** invitation(s) confirmée(s) avant ta prochaine récompense !"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="Invite avec ton lien personnel Discord habituel — le bot détecte tout seul qui a invité qui.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="defi-draft",
        description="Défie un joueur en Draft PvP — pool privé pour chacun, niveau/attaques standardisés",
    )
    async def defi_draft_cmd(self, interaction: discord.Interaction, adversaire: discord.Member):
        if adversaire.id == interaction.user.id:
            await interaction.response.send_message("Tu ne peux pas te défier toi-même !", ephemeral=True)
            return
        if adversaire.bot:
            await interaction.response.send_message("Tu ne peux pas défier un bot !", ephemeral=True)
            return

        if not isinstance(interaction.channel, (discord.TextChannel, discord.VoiceChannel)):
            await interaction.response.send_message(
                "Cette commande doit être utilisée dans un channel classique (pas un fil).", ephemeral=True
            )
            return

        try:
            thread = await interaction.channel.create_thread(
                name=f"🎯 Draft PvP : {interaction.user.display_name} vs {adversaire.display_name}",
                type=discord.ChannelType.public_thread,
            )
            await thread.add_user(interaction.user)
            await thread.add_user(adversaire)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Impossible de créer le fil : {e}", ephemeral=True)
            return

        vue = draft_pvp_module.VueInvitationDraft(self.bot, interaction.user, adversaire, interaction.channel)
        await thread.send(
            f"🎯 {adversaire.mention}, **{interaction.user.display_name}** te défie en **Draft PvP** ! "
            f"Chacun pioche dans son **propre pool privé** de {config.DRAFT_TAILLE_POOL_PERSO} Pokémon "
            f"(jamais les mêmes des deux côtés) et choisit son équipe de {config.DRAFT_TAILLE_EQUIPE} dedans, "
            f"en toute confidentialité (niveau {config.DRAFT_NIVEAU}, attaques et talent tirés au hasard). "
            f"Le combat démarre dès que vous êtes prêts tous les deux. Tu acceptes ?",
            view=vue,
        )
        await interaction.response.send_message(f"Défi envoyé dans {thread.mention} !", ephemeral=True)

    @app_commands.command(name="badges-arene", description="Vois les badges d'Arène que tu as débloqués")
    async def badges_arene_cmd(self, interaction: discord.Interaction):
        badges = database.obtenir_badges_arene(interaction.user.id)
        bonus_pourcent = round(config.ARENE_BONUS_DEGATS_PAR_BADGE * 100)

        embed = discord.Embed(
            title=f"🎖️ Badges d'Arène — {len(badges)}/18",
            color=discord.Color.orange(),
        )
        if badges:
            texte = ", ".join(f"{EMOJI_TYPES.get(t, '')} {t.capitalize()}" for t in sorted(badges))
            embed.add_field(name="Débloqués", value=texte, inline=False)
        else:
            embed.description = "Aucun badge débloqué pour l'instant — bats un Champion d'Arène pour commencer !"
        embed.set_footer(text=f"Chaque badge donne +{bonus_pourcent}% de dégâts permanents avec les attaques de ce type.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="force-arene", description="[Admin] Force l'ouverture immédiate d'une arène")
    @app_commands.describe(type_pokemon="Type de l'arène (aléatoire si non précisé)")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_arene_cmd(self, interaction: discord.Interaction, type_pokemon: str = None):
        if type_pokemon and type_pokemon.lower() not in EMOJI_TYPES:
            await interaction.response.send_message(
                f"❌ Type inconnu. Types valides : {', '.join(sorted(EMOJI_TYPES.keys()))}", ephemeral=True
            )
            return

        channel_id = getattr(config, "CHANNEL_ARENE_ID", None)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            await interaction.response.send_message("❌ CHANNEL_ARENE_ID introuvable — vérifie l'ID dans config.py.", ephemeral=True)
            return

        await arene_module.demarrer_nouvelle_arene(self.bot, channel, type_arene=type_pokemon.lower() if type_pokemon else None)
        journal.logger(f"🛠️ <@{interaction.user.id}> a forcé l'ouverture d'une arène (/force-arene).")
        await interaction.response.send_message(f"✅ Arène ouverte dans {channel.mention} !", ephemeral=True)

    @app_commands.command(name="force-repaire", description="[Admin] Force l'ouverture immédiate d'un repaire de méchants")
    @app_commands.describe(equipe="Équipe méchante (aléatoire si non précisée)")
    @app_commands.choices(equipe=[
        app_commands.Choice(name=nom_equipe, value=nom_equipe) for nom_equipe in config.EQUIPES_MECHANTES
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def force_repaire_cmd(self, interaction: discord.Interaction, equipe: app_commands.Choice[str] = None):
        channel_id = getattr(config, "CHANNEL_REPAIRE_ID", None)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            await interaction.response.send_message("❌ CHANNEL_REPAIRE_ID introuvable — vérifie l'ID dans config.py.", ephemeral=True)
            return

        await repaires_module.demarrer_nouveau_repaire(self.bot, channel, equipe_mechante=equipe.value if equipe else None)
        journal.logger(f"🛠️ <@{interaction.user.id}> a forcé l'ouverture d'un repaire (/force-repaire).")
        await interaction.response.send_message(f"✅ Repaire ouvert dans {channel.mention} !", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RivalEvenementsCog(bot))
