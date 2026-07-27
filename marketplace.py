"""Marketplace — vente de Pokémon entre joueurs à prix fixe (pas d'enchères pour
l'instant). Chaque annonce vend UN Pokémon précis (une capture, pas une espèce) contre
des Poké Dollars, postée dans config.CHANNEL_MARKETPLACE_ID, et disparaît automatiquement
au bout de config.MARKETPLACE_DUREE_ANNONCE_SECONDES (1 semaine) si personne ne l'achète
— le Pokémon n'a jamais quitté son propriétaire entre-temps, rien à rembourser.

Pas de limite au nombre d'annonces actives par joueur (demandé explicitement).
"""

import asyncio
import time

import discord

import config
import database
import journal
from pokemon_data import EMOJI_POKEDOLLAR, cle_tri_alphabetique_fr, obtenir_pokemon_par_nom, sprite_pokemon

CAPTURES_PAR_PAGE = 25
DELAI_SUPPRESSION_MESSAGE = 300  # 5 min après vente/retrait/expiration, comme les fils de combat/échange

OPTIONS_TRI = [
    ("alphabetique", "Alphabétique"),
    ("rarete", "Rareté"),
    ("pc_desc", "PC : fort → faible"),
    ("pc_asc", "PC : faible → fort"),
]

try:
    from pokedex import ORDRE_RARETE
except ImportError:
    ORDRE_RARETE = {}


async def _supprimer_message_apres_delai(message: discord.Message, delai: int):
    if message is None:
        return
    await asyncio.sleep(delai)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


def construire_embed_annonce(annonce, vendeur_nom: str, pokemon_nom: str, pc: int, shiny: bool) -> discord.Embed:
    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    shiny_txt = " ✨" if shiny else ""
    # Timestamp Discord natif (style "R" = relatif) plutôt qu'un texte calculé une fois à
    # la création de l'annonce : le client Discord l'affiche et le met à jour tout seul en
    # direct ("expire dans 3 jours", puis "dans 2 jours"...) — sans ça, le texte restait
    # figé sur la valeur du moment de la création tant que le message n'était pas réédité
    # pour une autre raison (achat, retrait), donnant l'impression à tort d'un problème de
    # redémarrage du bot alors que ce n'était qu'un texte jamais recalculé.
    embed = discord.Embed(
        title=f"🛒 {pokemon_nom}{shiny_txt} — {annonce['prix']} {EMOJI_POKEDOLLAR}",
        description=(
            f"Vendu par **{vendeur_nom}**\n"
            f"**{pc} PC**\n\n"
            f"⏳ Expire <t:{annonce['date_expiration']}:R>"
        ),
        color=discord.Color.gold(),
    )
    if pokemon:
        url_sprite = sprite_pokemon(pokemon, shiny=shiny)
        if url_sprite:
            embed.set_thumbnail(url=url_sprite)
    embed.set_footer(text=f"Annonce #{annonce['id']}")
    return embed


class VueAnnonce(discord.ui.View):
    """Message d'annonce posté dans le channel marketplace — bouton d'achat pour tout le
    monde, bouton de retrait réservé au vendeur.

    IMPORTANT : après un redémarrage du bot, discord.py réutilise UNE SEULE instance de
    cette vue (ré-enregistrée via bot.add_view) pour TOUS les messages d'annonce déjà
    postés — self.annonce_id de cette instance serait alors faux pour tous, sauf celui
    qui l'a créée dans la session en cours. On lit donc TOUJOURS l'ID réel depuis le
    footer du message ("Annonce #123") plutôt que depuis self.annonce_id, ce qui rend
    n'importe quelle instance valable pour n'importe quel message."""

    def __init__(self, annonce_id: int | None = None):
        super().__init__(timeout=None)
        self.annonce_id = annonce_id  # utile seulement juste après la création (même session)

    @staticmethod
    def _annonce_id_depuis_message(message: discord.Message) -> int | None:
        if not message.embeds or not message.embeds[0].footer or not message.embeds[0].footer.text:
            return None
        texte = message.embeds[0].footer.text
        if not texte.startswith("Annonce #"):
            return None
        try:
            return int(texte.removeprefix("Annonce #"))
        except ValueError:
            return None

    @discord.ui.button(label="Acheter", emoji="🛒", style=discord.ButtonStyle.success, custom_id="pokewild:marketplace_acheter")
    async def acheter(self, interaction: discord.Interaction, button: discord.ui.Button):
        annonce_id = self._annonce_id_depuis_message(interaction.message)
        if annonce_id is None:
            await interaction.response.send_message("❌ Impossible de retrouver cette annonce.", ephemeral=True)
            return
        annonce = database.obtenir_annonce_marketplace(annonce_id)
        if annonce is None or annonce["statut"] != "active":
            await interaction.response.send_message("❌ Cette annonce n'est plus disponible.", ephemeral=True)
            return
        if annonce["vendeur_id"] == interaction.user.id:
            await interaction.response.send_message("❌ Tu ne peux pas acheter ton propre Pokémon !", ephemeral=True)
            return

        vue_confirmation = VueConfirmationAchat(annonce_id)
        await interaction.response.send_message(
            f"Confirmer l'achat pour **{annonce['prix']} {EMOJI_POKEDOLLAR}** ? Cette action est définitive.",
            view=vue_confirmation,
            ephemeral=True,
        )

    @discord.ui.button(label="Retirer mon annonce", emoji="❌", style=discord.ButtonStyle.secondary, custom_id="pokewild:marketplace_retirer")
    async def retirer(self, interaction: discord.Interaction, button: discord.ui.Button):
        annonce_id = self._annonce_id_depuis_message(interaction.message)
        if annonce_id is None:
            await interaction.response.send_message("❌ Impossible de retrouver cette annonce.", ephemeral=True)
            return
        annonce = database.obtenir_annonce_marketplace(annonce_id)
        if annonce is None or annonce["statut"] != "active":
            await interaction.response.send_message("Cette annonce n'est déjà plus active.", ephemeral=True)
            return
        if annonce["vendeur_id"] != interaction.user.id:
            await interaction.response.send_message("Seul le vendeur peut retirer cette annonce !", ephemeral=True)
            return

        database.marquer_annonce_marketplace(annonce_id, "annulee")
        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.dark_grey()
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(
            "✅ Ton annonce a bien été retirée — ton Pokémon ne bouge pas, il est resté chez toi.", ephemeral=True
        )
        interaction.client.loop.create_task(_supprimer_message_apres_delai(interaction.message, DELAI_SUPPRESSION_MESSAGE))


class VueConfirmationAchat(discord.ui.View):
    def __init__(self, annonce_id: int):
        super().__init__(timeout=30)
        self.annonce_id = annonce_id

    @discord.ui.button(label="Confirmer l'achat", emoji="✅", style=discord.ButtonStyle.success)
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        succes, erreur = database.executer_achat_marketplace(self.annonce_id, interaction.user.id)
        if not succes:
            await interaction.response.edit_message(content=f"❌ {erreur}", view=None)
            return

        annonce = database.obtenir_annonce_marketplace(self.annonce_id)
        await interaction.response.edit_message(
            content=f"✅ Achat conclu pour **{annonce['prix']} {EMOJI_POKEDOLLAR}** ! Le Pokémon est maintenant dans ta collection.",
            view=None,
        )
        journal.logger(
            f"🛒 <@{interaction.user.id}> a acheté l'annonce marketplace #{self.annonce_id} "
            f"pour {annonce['prix']} PD (vendeur : <@{annonce['vendeur_id']}>)."
        )

        try:
            channel = interaction.client.get_channel(config.CHANNEL_MARKETPLACE_ID)
            if channel is not None and annonce["message_id"]:
                message = await channel.fetch_message(int(annonce["message_id"]))
                embed = message.embeds[0]
                embed.color = discord.Color.dark_grey()
                embed.add_field(name="✅ Vendu", value=f"<@{interaction.user.id}>", inline=False)
                await message.edit(embed=embed, view=discord.ui.View())
                interaction.client.loop.create_task(_supprimer_message_apres_delai(message, DELAI_SUPPRESSION_MESSAGE))
        except (discord.NotFound, discord.HTTPException):
            pass

    @discord.ui.button(label="Annuler", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Achat annulé.", view=None)


class _VueChoixPokemonAVendre(discord.ui.View):
    """Sélection paginée d'UN Pokémon précis à mettre en vente — même principe que le
    choix d'offre d'échange (echanges.VueChoixOffre), adapté à une sélection unique."""

    def __init__(self, user_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.page = page
        self.tri = "alphabetique"
        self.toutes_captures = database.obtenir_toutes_captures_detaillees(user_id)
        self._trier_captures()
        self._construire_composants()

    def _trier_captures(self):
        if self.tri == "rarete":
            def cle_rarete(row):
                p = obtenir_pokemon_par_nom(row["pokemon_nom"])
                return (ORDRE_RARETE.get(p["rarete"], 99) if p else 99, cle_tri_alphabetique_fr(row["pokemon_nom"]))

            self.toutes_captures.sort(key=cle_rarete)
        elif self.tri == "pc_desc":
            self.toutes_captures.sort(key=lambda row: -row["pc"])
        elif self.tri == "pc_asc":
            self.toutes_captures.sort(key=lambda row: row["pc"])
        else:
            self.toutes_captures.sort(key=lambda row: cle_tri_alphabetique_fr(row["pokemon_nom"]))

    def _construire_composants(self):
        self.clear_items()
        debut = self.page * CAPTURES_PAR_PAGE
        page_captures = self.toutes_captures[debut : debut + CAPTURES_PAR_PAGE]

        options = []
        for row in page_captures:
            shiny_txt = " ✨" if row["shiny"] else ""
            label = f"{row['pokemon_nom']}{shiny_txt} — {row['pc']} PC"
            if database.capture_deja_en_vente(row["id"]):
                label += " (déjà en vente)"
            options.append(discord.SelectOption(label=label[:100], value=str(row["id"])))

        if options:
            select = discord.ui.Select(placeholder="Choisis le Pokémon à vendre…", options=options, row=0)
            select.callback = self._on_select
            self.add_item(select)

        select_tri = discord.ui.Select(
            placeholder="Trier par...",
            options=[
                discord.SelectOption(label=libelle, value=valeur, default=(valeur == self.tri))
                for valeur, libelle in OPTIONS_TRI
            ],
            row=1,
        )
        select_tri.callback = self._on_select_tri
        self.add_item(select_tri)

        nb_pages = max(1, (len(self.toutes_captures) + CAPTURES_PAR_PAGE - 1) // CAPTURES_PAR_PAGE)
        if nb_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=(self.page == 0), row=2)
            bouton_suiv = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=(self.page >= nb_pages - 1), row=2)
            bouton_prec.callback = self._page_precedente
            bouton_suiv.callback = self._page_suivante
            self.add_item(bouton_prec)
            self.add_item(bouton_suiv)

    async def _page_precedente(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _page_suivante(self, interaction: discord.Interaction):
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_select_tri(self, interaction: discord.Interaction):
        self.tri = interaction.data["values"][0]
        self.page = 0
        self._trier_captures()
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_select(self, interaction: discord.Interaction):
        capture_id = int(interaction.data["values"][0])
        if database.capture_deja_en_vente(capture_id):
            await interaction.response.send_message("❌ Ce Pokémon est déjà en vente ailleurs sur le marketplace.", ephemeral=True)
            return
        row = next((r for r in self.toutes_captures if r["id"] == capture_id), None)
        if row is None:
            await interaction.response.send_message("❌ Pokémon introuvable.", ephemeral=True)
            return

        modal = _ModalPrixVente(capture_id, row["pokemon_nom"], row["pc"], row["shiny"], row["total_espece"], row["rang"])
        await interaction.response.send_modal(modal)


class _ModalPrixVente(discord.ui.Modal, title="Prix de vente"):
    prix = discord.ui.TextInput(label="Prix en Poké Dollars", placeholder="ex: 500", required=True, max_length=7)

    def __init__(self, capture_id: int, pokemon_nom: str, pc: int, shiny: bool, total_espece: int, rang: int):
        super().__init__()
        self.capture_id = capture_id
        self.pokemon_nom = pokemon_nom
        self.pc = pc
        self.shiny = shiny
        self.dernier_exemplaire = total_espece == 1 and rang == 1

    async def on_submit(self, interaction: discord.Interaction):
        try:
            prix_int = int(self.prix.value)
        except ValueError:
            await interaction.response.send_message("Prix invalide — indique un nombre entier.", ephemeral=True)
            return
        if not (config.MARKETPLACE_PRIX_MIN <= prix_int <= config.MARKETPLACE_PRIX_MAX):
            await interaction.response.send_message(
                f"Le prix doit être compris entre {config.MARKETPLACE_PRIX_MIN} et {config.MARKETPLACE_PRIX_MAX} Poké Dollars.",
                ephemeral=True,
            )
            return
        if database.capture_deja_en_vente(self.capture_id):
            await interaction.response.send_message("❌ Ce Pokémon vient d'être mis en vente ailleurs entre-temps.", ephemeral=True)
            return

        annonce_id = database.creer_annonce_marketplace(
            interaction.user.id, self.capture_id, prix_int, config.MARKETPLACE_DUREE_ANNONCE_SECONDES
        )
        annonce = database.obtenir_annonce_marketplace(annonce_id)

        channel = interaction.client.get_channel(config.CHANNEL_MARKETPLACE_ID)
        if channel is None:
            await interaction.response.send_message(
                "⚠️ Le channel marketplace est introuvable (config.CHANNEL_MARKETPLACE_ID) — annonce annulée.",
                ephemeral=True,
            )
            database.marquer_annonce_marketplace(annonce_id, "annulee")
            return

        embed = construire_embed_annonce(annonce, interaction.user.display_name, self.pokemon_nom, self.pc, self.shiny)
        message = await channel.send(embed=embed, view=VueAnnonce(annonce_id))
        database.definir_message_annonce_marketplace(annonce_id, message.id)

        avertissement = (
            "\n⚠️ C'est ton dernier exemplaire de cette espèce — le vendre fera disparaître son entrée de ton Pokédex."
            if self.dernier_exemplaire else ""
        )
        await interaction.response.send_message(
            f"✅ **{self.pokemon_nom}** mis en vente pour **{prix_int} {EMOJI_POKEDOLLAR}** dans {channel.mention} "
            f"— disponible 7 jours.{avertissement}",
            ephemeral=True,
        )
        journal.logger(f"🛒 <@{interaction.user.id}> a mis en vente **{self.pokemon_nom}** pour {prix_int} PD (annonce #{annonce_id}).")


async def lancer_vente(interaction: discord.Interaction):
    """Point d'entrée de la commande /vendre-pokemon."""
    vue = _VueChoixPokemonAVendre(interaction.user.id)
    if not vue.toutes_captures:
        await interaction.response.send_message("Tu n'as aucun Pokémon à vendre !", ephemeral=True)
        return
    await interaction.response.send_message("Quel Pokémon veux-tu mettre en vente ?", view=vue, ephemeral=True)


async def purger_annonces_expirees(bot):
    """Marque expirées toutes les annonces dont la date est dépassée, édite leur message
    (⌛ Expirée) et programme sa suppression — le Pokémon n'a jamais bougé, rien à faire
    côté inventaire. Appelée périodiquement (voir config.MARKETPLACE_INTERVALLE_VERIFICATION_SECONDES)."""
    expirees = database.obtenir_annonces_marketplace_expirees(int(time.time()))
    if not expirees:
        return 0

    channel = bot.get_channel(config.CHANNEL_MARKETPLACE_ID)
    for annonce in expirees:
        database.marquer_annonce_marketplace(annonce["id"], "expiree")
        if channel is None or not annonce["message_id"]:
            continue
        try:
            message = await channel.fetch_message(int(annonce["message_id"]))
            embed = message.embeds[0]
            embed.color = discord.Color.dark_grey()
            embed.add_field(
                name="⌛ Expirée",
                value=f"<@{annonce['vendeur_id']}>, ton Pokémon reste bien dans ta collection.",
                inline=False,
            )
            await message.edit(embed=embed, view=discord.ui.View())
            bot.loop.create_task(_supprimer_message_apres_delai(message, DELAI_SUPPRESSION_MESSAGE))
        except (discord.NotFound, discord.HTTPException):
            pass

    return len(expirees)


LIBELLE_STATUT = {
    "vendue": "✅ Vendu",
    "annulee": "🚫 Retiré",
    "expiree": "⌛ Expiré",
    "active": "🛒 En vente",
}


async def rechercher_annonces(interaction: discord.Interaction, nom: str):
    """Point d'entrée de la commande /marketplace-recherche."""
    resultats = database.rechercher_annonces_marketplace_actives(nom)
    if not resultats:
        await interaction.response.send_message(f"Aucune annonce active pour « {nom} ».", ephemeral=True)
        return

    lignes = []
    for r in resultats:
        shiny_txt = " ✨" if r["shiny"] else ""
        ligne = f"**{r['pokemon_nom']}{shiny_txt}** ({r['pc']} PC) — {r['prix']} {EMOJI_POKEDOLLAR} — vendu par <@{r['vendeur_id']}>"
        if r["message_id"] and interaction.guild_id:
            lien = f"https://discord.com/channels/{interaction.guild_id}/{config.CHANNEL_MARKETPLACE_ID}/{r['message_id']}"
            ligne += f" — [Voir l'annonce]({lien})"
        lignes.append(ligne)

    embed = discord.Embed(
        title=f"🔍 Marketplace — résultats pour « {nom} »",
        description="\n".join(lignes),
        color=discord.Color.gold(),
    )
    if len(resultats) == 15:
        embed.set_footer(text="15 résultats les plus récents affichés — affine ta recherche si besoin.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def afficher_historique(interaction: discord.Interaction):
    """Point d'entrée de la commande /marketplace-historique."""
    lignes_data = database.obtenir_historique_marketplace_joueur(interaction.user.id)
    if not lignes_data:
        await interaction.response.send_message("Tu n'as encore aucune activité sur le marketplace.", ephemeral=True)
        return

    lignes = []
    for r in lignes_data:
        nom = r["pokemon_nom"] or "*Pokémon introuvable*"
        if r["vendeur_id"] == interaction.user.id:
            lignes.append(f"{LIBELLE_STATUT.get(r['statut'], r['statut'])} — **{nom}** ({r['prix']} {EMOJI_POKEDOLLAR}) — mis en vente")
        else:
            lignes.append(f"🟢 Acheté — **{nom}** ({r['prix']} {EMOJI_POKEDOLLAR})")

    embed = discord.Embed(
        title="📜 Ton historique marketplace",
        description="\n".join(lignes),
        color=discord.Color.blurple(),
    )
    if len(lignes_data) == 15:
        embed.set_footer(text="15 entrées les plus récentes affichées.")
    await interaction.response.send_message(embed=embed, ephemeral=True)
