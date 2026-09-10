"""Cog : defi-gladio, reroll-raids, admin-importer-emojis-objets, setup-quetes, echanger.
Neuvième lot du découpage en Cogs — voir cogs/admin_economie.py pour le contexte général.

echanger embarque aussi sa Vue (VueEchangeProposition) et son helper (demarrer_echange) —
ni l'un ni l'autre ne référence `bot`, donc le trio migre proprement ensemble.

VueDefierGladio est une vue PERSISTANTE (custom_id fixe) — enregistrée via bot.add_view()
dans le setup() du Cog. Son message fixe (channel dresseur, CHANNEL_AVENTURE_ID) est posté
directement depuis ce même setup() (PAS via un écouteur on_ready du Cog — piégeux, voir
le commentaire dans setup() plus bas pour l'explication précise du timing).
"""

import asyncio
import json
import random

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import capacites as capacites_module
import config
import database
import dresseurs as dresseurs_module
import echanges as echanges_module
import journal
import pnj
import quetes_ui as quetes_ui_module
import formes_objets as formes_objets_module
from pokemon_data import (
    EMOJI_SOINS,
    IMAGE_SOINS,
    POKEDEX,
    appliquer_emojis_objets,
    recharger_cache_emojis_objets,
)


def effectuer_reroll_raids() -> tuple:
    """Tire un nouveau roster de raid aléatoire (sur toute la base actuelle), palier par
    palier, et le sauvegarde en base — réutilisée à la fois par /reroll-raids (manuel)
    et par la boucle automatique du dimanche 20h (voir main.py::boucle_reroll_raids_hebdomadaire).
    Retourne (nouveau_roster, lignes_resultat) pour que l'appelant construise l'annonce
    qui lui convient (embed followup pour la commande, embed + ping de rôle pour la boucle)."""
    taille_par_etoile = {1: 5, 2: 5, 3: 5, 4: 3, 5: 3}
    par_rarete = {}
    for pokemon in POKEDEX:
        par_rarete.setdefault(pokemon["rarete"], []).append(pokemon["nom"])

    nouveau_roster = {}
    lignes_resultat = []
    for etoiles, taille in taille_par_etoile.items():
        rarete = config.RARETE_PAR_ETOILES.get(etoiles, "commun")
        candidats = par_rarete.get(rarete, [])
        taille_reelle = min(taille, len(candidats))
        noms = random.sample(candidats, taille_reelle) if candidats else []
        nouveau_roster[str(etoiles)] = noms
        lignes_resultat.append(f"{'⭐' * etoiles} : {', '.join(noms) if noms else '*(aucun disponible)*'}")

    database.definir_parametre("roster_raid_json", json.dumps(nouveau_roster, ensure_ascii=False))
    return nouveau_roster, lignes_resultat


class VueEchangeProposition(discord.ui.View):
    """Vue visible par tout le monde, mais seul le joueur ciblé peut accepter/refuser."""

    def __init__(self, proposeur: discord.Member, cible: discord.Member):
        super().__init__(timeout=60)
        self.proposeur = proposeur
        self.cible = cible
        self.resolu = False
        self.message = None

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.cible.id:
            await interaction.response.send_message("Cette proposition ne te concerne pas !", ephemeral=True)
            return
        if self.resolu:
            await interaction.response.send_message("Cette proposition n'est plus disponible.", ephemeral=True)
            return

        self.resolu = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {self.cible.mention} accepte ! Ouverture du fil d'échange...",
            view=self,
        )
        await demarrer_echange(self.proposeur, self.cible, interaction.channel)
        self.stop()

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.secondary, emoji="❌")
    async def refuser(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.cible.id:
            await interaction.response.send_message("Cette proposition ne te concerne pas !", ephemeral=True)
            return
        if self.resolu:
            await interaction.response.send_message("Cette proposition n'est plus disponible.", ephemeral=True)
            return
        self.resolu = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {self.cible.display_name} a refusé l'échange.",
            view=self,
        )
        self.stop()

    async def on_timeout(self):
        if self.resolu:
            return
        self.resolu = True
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=f"⌛ La proposition d'échange de **{self.proposeur.display_name}** à {self.cible.mention} a expiré.",
                    view=self,
                )
            except discord.HTTPException:
                pass


async def demarrer_echange(proposeur: discord.Member, cible: discord.Member, channel: discord.TextChannel):
    """Crée le fil privé d'échange et le premier message avec les deux offres vides."""
    echange_id = database.creer_echange(proposeur.id, cible.id)

    try:
        thread = await channel.create_thread(
            name=f"🔄 {proposeur.display_name} ↔ {cible.display_name}",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(proposeur)
        await thread.add_user(cible)
    except discord.HTTPException as e:
        await channel.send(f"❌ Impossible de créer le fil d'échange : {e}")
        database.annuler_echange(echange_id)
        return

    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE echanges SET thread_id = ? WHERE id = ?", (str(thread.id), echange_id))
    conn.commit()
    conn.close()

    noms = {proposeur.id: proposeur.display_name, cible.id: cible.display_name}
    embed, fichier = await echanges_module.construire_message_echange(echange_id, noms)
    vue = echanges_module.VueEchange(echange_id)
    envoi_kwargs = {"embed": embed, "view": vue}
    if fichier is not None:
        envoi_kwargs["file"] = fichier
    msg = await thread.send(
        content=f"{proposeur.mention} {cible.mention} — construisez vos offres puis validez chacun votre tour !",
        **envoi_kwargs,
    )
    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE echanges SET message_id = ? WHERE id = ?", (str(msg.id), echange_id))
    conn.commit()
    conn.close()


async def _lancer_defi_gladio(bot: commands.Bot, interaction: discord.Interaction):
    """Logique du défi Gladio, partagée entre /defi-gladio et le bouton persistant
    (voir VueDefierGladio) — évite de dupliquer les vérifications aux deux endroits."""
    if not isinstance(interaction.channel, (discord.TextChannel, discord.VoiceChannel)):
        await interaction.response.send_message(
            "Cette commande doit être utilisée dans un channel classique (pas un fil).", ephemeral=True
        )
        return

    if database.combat_en_cours_pour_joueur(interaction.user.id):
        await interaction.response.send_message("❌ Tu as déjà un combat en cours !", ephemeral=True)
        return

    noms_equipe = database.obtenir_equipe_combat_disponible(interaction.user.id)
    if not noms_equipe:
        await interaction.response.send_message(
            "❌ Configure ton équipe de combat d'abord (`/equipe-combat`) !", ephemeral=True
        )
        return

    restant = database.temps_restant_defi_gladio(interaction.user.id)
    if restant > 0:
        heures = restant // 3600
        minutes = (restant % 3600) // 60
        await interaction.response.send_message(
            f"⏳ Gladio n'est pas encore prêt à te redéfier. Reviens dans **{heures}h{minutes:02d}**.",
            ephemeral=True,
        )
        return

    try:
        await interaction.response.send_message("⚔️ Gladio accepte ton défi !", ephemeral=True)
    except (discord.NotFound, discord.HTTPException):
        pass
    await dresseurs_module.defier_gladio(bot, interaction.user, interaction.channel, interaction)


class VueDefierGladio(discord.ui.View):
    """Vue PERSISTANTE (custom_id fixe) attachée au message fixe du channel dresseur —
    doit survivre à un redémarrage du bot, donc pas de timeout et enregistrée via
    bot.add_view() dans on_ready (voir main.py)."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Défier Gladio", emoji="⚔️", style=discord.ButtonStyle.danger, custom_id="gladio_defier_bouton")
    async def defier(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _lancer_defi_gladio(self.bot, interaction)


def _construire_embed_defi_gladio() -> discord.Embed:
    embed = discord.Embed(
        title=f"{pnj.EMOJI_RIVAL} Défier {pnj.NOM_RIVAL}",
        description=(
            f"**{pnj.NOM_RIVAL}** est toujours partant pour un combat — configure ton "
            f"équipe (bouton **Équipe de combat** sur ton profil) puis tape sur le bouton "
            f"ci-dessous.\n\nRejouable une fois par jour."
        ),
        color=discord.Color.dark_grey(),
    )
    embed.set_thumbnail(url=pnj.IMAGE_RIVAL)
    return embed


async def _poster_message_defi_gladio_si_absent(bot: commands.Bot):
    """Poste le message fixe du défi Gladio dans CHANNEL_AVENTURE_ID (le channel
    dresseur), ou le met à jour s'il existe déjà — même principe que les autres messages
    fixes du jeu (Laboratoire, Profil, etc., voir main.py). Auto-suffisant dans ce Cog
    (appelé depuis setup() ci-dessous) plutôt qu'ajouté au bloc équivalent de main.py, pour
    ne pas avoir à modifier main.py à chaque nouveau message fixe ajouté par un Cog."""
    channel = bot.get_channel(config.CHANNEL_AVENTURE_ID)
    if channel is None:
        print(
            "⚠️ CHANNEL_AVENTURE_ID introuvable — le message de défi Gladio n'a pas pu "
            "être posté automatiquement."
        )
        return

    embed = _construire_embed_defi_gladio()
    message_id = database.obtenir_parametre("defi_gladio_message_id")

    if message_id:
        try:
            message_existant = await channel.fetch_message(int(message_id))
            await message_existant.edit(embed=embed, view=VueDefierGladio(bot))
            return
        except discord.NotFound:
            pass  # le message a été supprimé manuellement, on va en recréer un ci-dessous

    message = await channel.send(embed=embed, view=VueDefierGladio(bot))
    database.definir_parametre("defi_gladio_message_id", str(message.id))


class GladioRaidsEchangesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="defi-gladio",
        description="Défie Gladio, ton rival — un vrai combat, équipe légèrement plus forte que la tienne",
    )
    async def defi_gladio_cmd(self, interaction: discord.Interaction):
        await _lancer_defi_gladio(self.bot, interaction)

    @app_commands.command(
        name="reroll-raids",
        description="[Admin] Tire un nouveau roster de raid aléatoire (sur toute la base actuelle), palier par palier",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def reroll_raids_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()

        nouveau_roster, lignes_resultat = effectuer_reroll_raids()

        journal.logger(f"🛠️ <@{interaction.user.id}> a relancé le roster de raid (/reroll-raids).")
        embed = discord.Embed(
            title="🎲 Nouveau roster de raid",
            description="\n".join(lignes_resultat),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Effectif immédiatement pour les prochains raids, aucun redéploiement nécessaire.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="admin-importer-emojis-objets",
        description="[Admin] Upload les sprites d'objets comme emoji Discord perso (une fois, pour les menus déroulants)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_importer_emojis_objets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Les 3 familles d'objets qui ont un vrai sprite (voir objets_sprites/, objets_sprites_v2/) :
        # objets de combat, objets de transformation, potions. Clé interne = nom de l'emoji créé.
        a_importer = {}
        for cle, info in capacites_module.OBJETS_TENUS.items():
            if info.get("image"):
                a_importer[cle] = info["image"]
        for cle, info in formes_objets_module.FORMES_OBJETS.items():
            if info.get("objet_image"):
                a_importer[cle] = info["objet_image"]
        for cle, url in IMAGE_SOINS.items():
            a_importer[cle] = url

        deja_importes = database.obtenir_emojis_objets()
        a_faire = {cle: url for cle, url in a_importer.items() if cle not in deja_importes}

        if not a_faire:
            await interaction.followup.send(
                f"✅ Rien à faire — les {len(a_importer)} objets ont déjà un emoji personnalisé importé.",
                ephemeral=True,
            )
            return

        reussis, echoues, limite_atteinte = [], [], False
        async with aiohttp.ClientSession() as session:
            for cle, url in a_faire.items():
                if limite_atteinte:
                    echoues.append((cle, "limite d'emplacements du serveur atteinte"))
                    continue
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            echoues.append((cle, f"téléchargement échoué (HTTP {resp.status})"))
                            continue
                        image_bytes = await resp.read()
                    emoji = await interaction.guild.create_custom_emoji(
                        name=cle, image=image_bytes, reason="Import sprites objets PokéWild"
                    )
                    database.enregistrer_emoji_objet(cle, emoji.id, emoji.name)
                    reussis.append(cle)
                    await asyncio.sleep(1)  # reste courtois vis-à-vis du rate limit Discord
                except discord.HTTPException as e:
                    if getattr(e, "code", None) == 30008 or "Maximum number of emojis reached" in str(e):
                        limite_atteinte = True
                        echoues.append((cle, "limite d'emplacements du serveur atteinte"))
                    else:
                        echoues.append((cle, str(e)))

        recharger_cache_emojis_objets()
        appliquer_emojis_objets(capacites_module.OBJETS_TENUS, formes_objets_module.FORMES_OBJETS, EMOJI_SOINS)
        journal.logger(f"🛠️ <@{interaction.user.id}> a importé {len(reussis)} emoji d'objets (/admin-importer-emojis-objets).")

        description = f"✅ **{len(reussis)}** emoji créés et branchés.\n"
        if echoues:
            lignes_echec = "\n".join(f"— `{cle}` : {raison}" for cle, raison in echoues[:15])
            description += f"\n❌ **{len(echoues)}** échoués :\n{lignes_echec}"
            if len(echoues) > 15:
                description += f"\n… et {len(echoues) - 15} de plus."
            if limite_atteinte:
                description += (
                    "\n\n⚠️ Le serveur a atteint sa limite d'emplacements d'emoji. "
                    "Il faut soit booster le serveur (plus d'emplacements), soit supprimer des emoji existants, "
                    "puis relancer cette commande — elle ne refera que ceux qui manquent encore."
                )
        embed = discord.Embed(
            title="🖼️ Import des emoji d'objets",
            description=description,
            color=discord.Color.green() if not echoues else discord.Color.orange(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setup-quetes", description="[Admin] Poste ou remet à jour le message fixe des Quêtes dans ce channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_quetes(self, interaction: discord.Interaction):
        embed = quetes_ui_module.construire_embed_centre()
        message = await interaction.channel.send(embed=embed, view=quetes_ui_module.VueCentreQuetes())
        database.definir_parametre("quetes_message_id", str(message.id))
        await interaction.response.send_message("✅ Quêtes postées dans ce channel.", ephemeral=True)

    @app_commands.command(name="echanger", description="Propose un échange de Pokémon et/ou Poké Dollars à un autre joueur")
    async def echanger(self, interaction: discord.Interaction, membre: discord.Member):
        if membre.bot or membre.id == interaction.user.id:
            await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
            return

        if database.echange_en_cours_pour_joueur(interaction.user.id):
            await interaction.response.send_message("❌ Tu as déjà un échange en cours !", ephemeral=True)
            return

        if database.echange_en_cours_pour_joueur(membre.id):
            await interaction.response.send_message(f"❌ {membre.mention} a déjà un échange en cours !", ephemeral=True)
            return

        vue_proposition = VueEchangeProposition(interaction.user, membre)
        await interaction.response.send_message(
            f"🔄 {membre.mention}, **{interaction.user.display_name}** te propose un échange ! Tu as 60 secondes pour accepter.",
            view=vue_proposition,
        )
        vue_proposition.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(GladioRaidsEchangesCog(bot))
    bot.add_view(VueDefierGladio(bot))  # réenregistre la vue persistante après un redémarrage
    # Posté directement ICI plutôt que via un écouteur on_ready du Cog : main.py charge
    # les extensions DEPUIS L'INTÉRIEUR de son propre on_ready (avant bot.tree.sync()) —
    # un listener on_ready ajouté à ce moment-là rate l'événement en cours (déjà en train
    # de se dispatcher) et n'aurait attendu qu'une future RECONNEXION, jamais le tout
    # premier démarrage. setup() tourne de façon synchrone exactement au bon moment
    # (le cache guildes/channels est déjà rempli à ce stade, comme pour tous les autres
    # messages fixes du jeu postés directement dans le on_ready de main.py).
    await _poster_message_defi_gladio_si_absent(bot)
