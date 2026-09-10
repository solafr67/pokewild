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


def construire_embed_enchere(annonce, vendeur_nom: str, pokemon_nom: str, pc: int, shiny: bool, enchereur_nom: str | None) -> discord.Embed:
    """Même principe que construire_embed_annonce, pour une enchère (type_annonce=
    'enchere') — affiche la plus haute enchère en cours si elle existe, sinon juste la
    mise à prix. enchereur_nom : None tant qu'aucune enchère n'a été placée."""
    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    shiny_txt = " ✨" if shiny else ""
    if annonce["prix_actuel"]:
        titre_prix = f"{annonce['prix_actuel']} {EMOJI_POKEDOLLAR} (enchère en cours)"
        ligne_enchere = f"🔨 Plus offrant : **{enchereur_nom}** — {annonce['prix_actuel']} {EMOJI_POKEDOLLAR}"
    else:
        titre_prix = f"Mise à prix {annonce['prix']} {EMOJI_POKEDOLLAR}"
        ligne_enchere = f"🔨 Aucune enchère pour l'instant — mise à prix {annonce['prix']} {EMOJI_POKEDOLLAR}"

    embed = discord.Embed(
        title=f"🔨 {pokemon_nom}{shiny_txt} — {titre_prix}",
        description=(
            f"Vendu par **{vendeur_nom}**\n"
            f"**{pc} PC**\n\n"
            f"{ligne_enchere}\n\n"
            f"⏳ Se termine <t:{annonce['date_expiration']}:R>"
        ),
        color=discord.Color.dark_orange(),
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


class VueAnnonceEnchere(discord.ui.View):
    """Équivalent de VueAnnonce pour une enchère — même principe de lecture de l'ID
    depuis le footer du message (voir VueAnnonce pour le raisonnement complet sur le
    partage d'instance après redémarrage). Bouton "Placer une enchère" pour tout le
    monde sauf le vendeur, "Retirer" réservé au vendeur ET bloqué dès qu'une enchère a
    été placée (la rétracter léserait l'enchérisseur, qui a déjà ses fonds retenus)."""

    def __init__(self, annonce_id: int | None = None):
        super().__init__(timeout=None)
        self.annonce_id = annonce_id

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

    @discord.ui.button(label="Placer une enchère", emoji="🔨", style=discord.ButtonStyle.success, custom_id="pokewild:marketplace_encherir")
    async def encherir(self, interaction: discord.Interaction, button: discord.ui.Button):
        annonce_id = self._annonce_id_depuis_message(interaction.message)
        if annonce_id is None:
            await interaction.response.send_message("❌ Impossible de retrouver cette enchère.", ephemeral=True)
            return
        annonce = database.obtenir_annonce_marketplace(annonce_id)
        if annonce is None or annonce["statut"] != "active":
            await interaction.response.send_message("❌ Cette enchère n'est plus disponible.", ephemeral=True)
            return
        if annonce["vendeur_id"] == interaction.user.id:
            await interaction.response.send_message("❌ Tu ne peux pas enchérir sur ton propre Pokémon !", ephemeral=True)
            return
        montant_minimum = annonce["prix_actuel"] + 1 if annonce["prix_actuel"] else annonce["prix"]
        await interaction.response.send_modal(_ModalPlacerEnchere(annonce_id, montant_minimum))

    @discord.ui.button(label="Retirer mon annonce", emoji="❌", style=discord.ButtonStyle.secondary, custom_id="pokewild:marketplace_retirer_enchere")
    async def retirer(self, interaction: discord.Interaction, button: discord.ui.Button):
        annonce_id = self._annonce_id_depuis_message(interaction.message)
        if annonce_id is None:
            await interaction.response.send_message("❌ Impossible de retrouver cette enchère.", ephemeral=True)
            return
        annonce = database.obtenir_annonce_marketplace(annonce_id)
        if annonce is None or annonce["statut"] != "active":
            await interaction.response.send_message("Cette enchère n'est déjà plus active.", ephemeral=True)
            return
        if annonce["vendeur_id"] != interaction.user.id:
            await interaction.response.send_message("Seul le vendeur peut retirer cette enchère !", ephemeral=True)
            return
        if annonce["enchereur_actuel_id"] is not None:
            await interaction.response.send_message(
                "❌ Impossible de retirer — une enchère a déjà été placée, elle doit aller à son terme "
                "(l'enchérisseur a déjà ses fonds retenus).",
                ephemeral=True,
            )
            return

        database.marquer_annonce_marketplace(annonce_id, "annulee")
        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.dark_grey()
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(
            "✅ Ton enchère a bien été retirée — ton Pokémon ne bouge pas, il est resté chez toi.", ephemeral=True
        )
        interaction.client.loop.create_task(_supprimer_message_apres_delai(interaction.message, DELAI_SUPPRESSION_MESSAGE))


class _ModalPlacerEnchere(discord.ui.Modal, title="Placer une enchère"):
    montant = discord.ui.TextInput(label="Montant en Poké Dollars", placeholder="ex: 500", required=True, max_length=7)

    def __init__(self, annonce_id: int, montant_minimum: int):
        super().__init__()
        self.annonce_id = annonce_id
        self.montant.placeholder = f"Minimum {montant_minimum}"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            montant_int = int(self.montant.value)
        except ValueError:
            await interaction.response.send_message("Montant invalide — indique un nombre entier.", ephemeral=True)
            return

        succes, erreur = database.placer_enchere(self.annonce_id, interaction.user.id, montant_int)
        if not succes:
            await interaction.response.send_message(f"❌ {erreur}", ephemeral=True)
            return

        annonce = database.obtenir_annonce_marketplace(self.annonce_id)
        conn = database.get_connexion()
        cur = conn.cursor()
        cur.execute("SELECT pokemon_nom, pc, shiny FROM captures WHERE id = ?", (annonce["capture_id"],))
        capture = cur.fetchone()
        conn.close()

        channel = interaction.client.get_channel(config.CHANNEL_MARKETPLACE_ID)
        if channel and annonce["message_id"]:
            try:
                message = await channel.fetch_message(int(annonce["message_id"]))
                vendeur = interaction.client.get_user(annonce["vendeur_id"]) or await interaction.client.fetch_user(annonce["vendeur_id"])
                embed = construire_embed_enchere(
                    annonce, vendeur.display_name if vendeur else "?",
                    capture["pokemon_nom"], capture["pc"], bool(capture["shiny"]), interaction.user.display_name,
                )
                await message.edit(embed=embed)
            except (discord.NotFound, discord.HTTPException):
                pass

        journal.logger(f"🔨 <@{interaction.user.id}> a enchéri {montant_int} PD sur l'annonce #{self.annonce_id}.")
        await interaction.response.send_message(
            f"✅ Enchère de **{montant_int} {EMOJI_POKEDOLLAR}** placée avec succès — tes fonds sont retenus tant "
            f"que tu n'es pas surenchéri (remboursés automatiquement si quelqu'un enchérit plus haut).",
            ephemeral=True,
        )


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
        self.recherche = None
        self.toutes_captures = database.obtenir_toutes_captures_detaillees(user_id)
        self._trier_captures()
        self._construire_composants()

    def _captures_affichees(self) -> list:
        if not self.recherche:
            return self.toutes_captures
        terme = cle_tri_alphabetique_fr(self.recherche)
        return [row for row in self.toutes_captures if terme in cle_tri_alphabetique_fr(row["pokemon_nom"])]

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
        captures_filtrees = self._captures_affichees()
        debut = self.page * CAPTURES_PAR_PAGE
        page_captures = captures_filtrees[debut : debut + CAPTURES_PAR_PAGE]

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
        elif self.recherche:
            self.add_item(discord.ui.Button(label=f"Aucun résultat pour « {self.recherche} »", style=discord.ButtonStyle.secondary, disabled=True, row=0))

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

        nb_pages = max(1, (len(captures_filtrees) + CAPTURES_PAR_PAGE - 1) // CAPTURES_PAR_PAGE)
        if nb_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=(self.page == 0), row=2)
            bouton_suiv = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=(self.page >= nb_pages - 1), row=2)
            bouton_prec.callback = self._page_precedente
            bouton_suiv.callback = self._page_suivante
            self.add_item(bouton_prec)
            self.add_item(bouton_suiv)

        bouton_recherche = discord.ui.Button(
            label=f"Recherche : {self.recherche}" if self.recherche else "Rechercher",
            emoji="🔍",
            style=discord.ButtonStyle.primary if self.recherche else discord.ButtonStyle.secondary,
            row=2,
        )
        bouton_recherche.callback = self._on_rechercher
        self.add_item(bouton_recherche)
        if self.recherche:
            bouton_effacer = discord.ui.Button(label="Effacer", emoji="❌", style=discord.ButtonStyle.secondary, row=2)
            bouton_effacer.callback = self._on_effacer_recherche
            self.add_item(bouton_effacer)

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

    async def _on_rechercher(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_ModalRechercheVente(self))

    async def _on_effacer_recherche(self, interaction: discord.Interaction):
        self.recherche = None
        self.page = 0
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

        vue = _VueChoixTypeVente(capture_id, row["pokemon_nom"], row["pc"], row["shiny"], row["total_espece"], row["rang"])
        await interaction.response.send_message(
            f"**{row['pokemon_nom']}** — comment veux-tu le mettre en vente ?",
            view=vue,
            ephemeral=True,
        )


class _ModalRechercheVente(discord.ui.Modal, title="Rechercher un Pokémon"):
    recherche_input = discord.ui.TextInput(label="Nom (ou partie du nom)", placeholder="Ex : Rat", required=False)

    def __init__(self, vue_parente: _VueChoixPokemonAVendre):
        super().__init__()
        self.vue_parente = vue_parente
        self.recherche_input.default = vue_parente.recherche or ""

    async def on_submit(self, interaction: discord.Interaction):
        terme = self.recherche_input.value.strip()
        self.vue_parente.recherche = terme or None
        self.vue_parente.page = 0
        self.vue_parente._construire_composants()
        await interaction.response.edit_message(view=self.vue_parente)



class _VueChoixTypeVente(discord.ui.View):
    """Choix intermédiaire vente directe / enchère, juste après avoir choisi QUEL
    Pokémon vendre — ouvre le modal de prix adapté selon le choix."""

    def __init__(self, capture_id: int, pokemon_nom: str, pc: int, shiny: bool, total_espece: int, rang: int):
        super().__init__(timeout=120)
        self.capture_id = capture_id
        self.pokemon_nom = pokemon_nom
        self.pc = pc
        self.shiny = shiny
        self.dernier_exemplaire = total_espece == 1 and rang == 1

    @discord.ui.button(label="Vente directe (prix fixe)", emoji="🛒", style=discord.ButtonStyle.primary)
    async def vente_directe(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = _ModalPrixVente(self.capture_id, self.pokemon_nom, self.pc, self.shiny, self.dernier_exemplaire)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Enchère", emoji="🔨", style=discord.ButtonStyle.primary)
    async def enchere(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = _ModalPrixEnchere(self.capture_id, self.pokemon_nom, self.pc, self.shiny, self.dernier_exemplaire)
        await interaction.response.send_modal(modal)


class _ModalPrixEnchere(discord.ui.Modal, title="Mise à prix de l'enchère"):
    prix = discord.ui.TextInput(label="Mise à prix en Poké Dollars", placeholder="ex: 100", required=True, max_length=7)

    def __init__(self, capture_id: int, pokemon_nom: str, pc: int, shiny: bool, dernier_exemplaire: bool):
        super().__init__()
        self.capture_id = capture_id
        self.pokemon_nom = pokemon_nom
        self.pc = pc
        self.shiny = shiny
        self.dernier_exemplaire = dernier_exemplaire

    async def on_submit(self, interaction: discord.Interaction):
        try:
            prix_int = int(self.prix.value)
        except ValueError:
            await interaction.response.send_message("Prix invalide — indique un nombre entier.", ephemeral=True)
            return
        if not (config.MARKETPLACE_PRIX_MIN <= prix_int <= config.MARKETPLACE_PRIX_MAX):
            await interaction.response.send_message(
                f"La mise à prix doit être comprise entre {config.MARKETPLACE_PRIX_MIN} et {config.MARKETPLACE_PRIX_MAX} Poké Dollars.",
                ephemeral=True,
            )
            return
        if database.capture_deja_en_vente(self.capture_id):
            await interaction.response.send_message("❌ Ce Pokémon vient d'être mis en vente ailleurs entre-temps.", ephemeral=True)
            return

        annonce_id = database.creer_annonce_enchere(
            interaction.user.id, self.capture_id, prix_int, config.MARKETPLACE_DUREE_ANNONCE_SECONDES
        )
        annonce = database.obtenir_annonce_marketplace(annonce_id)

        channel = interaction.client.get_channel(config.CHANNEL_MARKETPLACE_ID)
        if channel is None:
            await interaction.response.send_message(
                "⚠️ Le channel marketplace est introuvable (config.CHANNEL_MARKETPLACE_ID) — enchère annulée.",
                ephemeral=True,
            )
            database.marquer_annonce_marketplace(annonce_id, "annulee")
            return

        embed = construire_embed_enchere(annonce, interaction.user.display_name, self.pokemon_nom, self.pc, self.shiny, None)
        message = await channel.send(embed=embed, view=VueAnnonceEnchere(annonce_id))
        database.definir_message_annonce_marketplace(annonce_id, message.id)

        avertissement = (
            "\n⚠️ C'est ton dernier exemplaire de cette espèce — le vendre fera disparaître son entrée de ton Pokédex."
            if self.dernier_exemplaire else ""
        )
        await interaction.response.send_message(
            f"✅ **{self.pokemon_nom}** mis aux enchères, mise à prix **{prix_int} {EMOJI_POKEDOLLAR}**, dans {channel.mention} "
            f"— se termine dans 7 jours.{avertissement}",
            ephemeral=True,
        )
        journal.logger(f"🔨 <@{interaction.user.id}> a mis aux enchères **{self.pokemon_nom}** (mise à prix {prix_int} PD, annonce #{annonce_id}).")


class _ModalPrixVente(discord.ui.Modal, title="Prix de vente"):
    prix = discord.ui.TextInput(label="Prix en Poké Dollars", placeholder="ex: 500", required=True, max_length=7)

    def __init__(self, capture_id: int, pokemon_nom: str, pc: int, shiny: bool, dernier_exemplaire: bool):
        super().__init__()
        self.capture_id = capture_id
        self.pokemon_nom = pokemon_nom
        self.pc = pc
        self.shiny = shiny
        self.dernier_exemplaire = dernier_exemplaire

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
    """Marque expirées toutes les annonces dont la date est dépassée — pour une vente
    directe, édite le message (⌛ Expirée) et programme sa suppression (le Pokémon n'a
    jamais bougé, rien à faire côté inventaire). Pour une enchère (type_annonce=
    'enchere'), résout la vente au plus offrant s'il y en a un (voir
    database.resoudre_enchere_expiree) — message et couleur différents selon l'issue.
    Appelée périodiquement (voir config.MARKETPLACE_INTERVALLE_VERIFICATION_SECONDES)."""
    expirees = database.obtenir_annonces_marketplace_expirees(int(time.time()))
    if not expirees:
        return 0

    channel = bot.get_channel(config.CHANNEL_MARKETPLACE_ID)
    for annonce in expirees:
        if annonce["type_annonce"] == "enchere":
            resultat = database.resoudre_enchere_expiree(annonce["id"])
            if channel is None or not annonce["message_id"]:
                continue
            try:
                message = await channel.fetch_message(int(annonce["message_id"]))
                embed = message.embeds[0]
                if resultat["vendu"]:
                    embed.color = discord.Color.green()
                    embed.add_field(
                        name="🔨 Enchère terminée !",
                        value=(
                            f"Remportée par <@{resultat['enchereur_id']}> pour **{resultat['prix_final']} {EMOJI_POKEDOLLAR}** !\n"
                            f"<@{annonce['vendeur_id']}>, les fonds ont été crédités."
                        ),
                        inline=False,
                    )
                else:
                    embed.color = discord.Color.dark_grey()
                    embed.add_field(
                        name="⌛ Enchère terminée sans offre",
                        value=f"<@{annonce['vendeur_id']}>, aucune enchère n'a été placée — ton Pokémon reste bien dans ta collection.",
                        inline=False,
                    )
                await message.edit(embed=embed, view=discord.ui.View())
                bot.loop.create_task(_supprimer_message_apres_delai(message, DELAI_SUPPRESSION_MESSAGE))
            except (discord.NotFound, discord.HTTPException):
                pass
            continue

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


async def nettoyer_messages_annonces_terminees(bot):
    """Filet de sécurité pour les messages d'annonces vendue/annulée/expirée qui
    auraient dû être supprimés (voir _supprimer_message_apres_delai) mais dont la tâche
    a été perdue — typiquement un redémarrage du bot survenu entre la vente et
    l'échéance des DELAI_SUPPRESSION_MESSAGE secondes prévues. Contrairement à
    bot.loop.create_task, cette fonction est appelée PÉRIODIQUEMENT (voir
    boucle_marketplace) et relit l'état réel en base à chaque fois, donc rien ne peut
    rester bloqué indéfiniment même après plusieurs redémarrages d'affilée."""
    a_nettoyer = database.obtenir_annonces_marketplace_a_nettoyer(int(time.time()) - DELAI_SUPPRESSION_MESSAGE)
    if not a_nettoyer:
        return 0

    channel = bot.get_channel(config.CHANNEL_MARKETPLACE_ID)
    for annonce in a_nettoyer:
        if channel is not None:
            try:
                message = await channel.fetch_message(int(annonce["message_id"]))
                await message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
        database.effacer_message_id_annonce(annonce["id"])

    return len(a_nettoyer)


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
        if r["type_annonce"] == "enchere":
            prix_affiche = f"{r['prix_actuel']} {EMOJI_POKEDOLLAR} (enchère en cours)" if r["prix_actuel"] else f"mise à prix {r['prix']} {EMOJI_POKEDOLLAR}"
        else:
            prix_affiche = f"{r['prix']} {EMOJI_POKEDOLLAR}"
        ligne = f"**{r['pokemon_nom']}{shiny_txt}** ({r['pc']} PC) — {prix_affiche} — vendu par <@{r['vendeur_id']}>"
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
