import discord

import database
from pokemon_data import EMOJI_POKEDOLLAR

CAPTURES_PAR_PAGE = 25
DELAI_SUPPRESSION_FIL = 120


def _ligne_offre(captures: list, pd: int) -> str:
    if not captures and pd == 0:
        return "*Rien proposé pour l'instant*"
    lignes = []
    for row in captures[:15]:
        shiny_txt = " ✨" if row["shiny"] else ""
        lignes.append(f"• {row['pokemon_nom']}{shiny_txt} ({row['pc']} PC)")
    if len(captures) > 15:
        lignes.append(f"*... et {len(captures) - 15} autre(s)*")
    if pd > 0:
        lignes.append(f"{EMOJI_POKEDOLLAR} {pd} Poké Dollars")
    return "\n".join(lignes) if lignes else "*Rien proposé pour l'instant*"


def construire_embed_echange(echange_id: int, noms: dict) -> discord.Embed:
    echange = database.obtenir_echange(echange_id)
    if echange is None:
        return discord.Embed(description="Échange introuvable.", color=discord.Color.red())

    offre_j1 = database.obtenir_offre_echange(echange_id, echange["joueur1_id"])
    offre_j2 = database.obtenir_offre_echange(echange_id, echange["joueur2_id"])

    embed = discord.Embed(title="🔄 Échange en cours", color=discord.Color.blurple())

    statut_j1 = "✅ Offre validée" if echange["joueur1_valide"] else "⏳ En cours de construction..."
    statut_j2 = "✅ Offre validée" if echange["joueur2_valide"] else "⏳ En cours de construction..."

    embed.add_field(
        name=f"{noms.get(echange['joueur1_id'], 'Joueur 1')} — {statut_j1}",
        value=_ligne_offre(offre_j1, echange["joueur1_pd"]),
        inline=True,
    )
    embed.add_field(
        name=f"{noms.get(echange['joueur2_id'], 'Joueur 2')} — {statut_j2}",
        value=_ligne_offre(offre_j2, echange["joueur2_pd"]),
        inline=True,
    )
    embed.set_footer(text="Modifier son offre annule les deux validations — il faut revalider après tout changement.")

    return embed


class VueEchange(discord.ui.View):
    """Vue partagée dans le fil : chaque joueur gère sa propre offre via ces boutons."""

    def __init__(self, echange_id: int):
        super().__init__(timeout=None)
        self.echange_id = echange_id

    async def _verifier_participant(self, interaction: discord.Interaction) -> bool:
        echange = database.obtenir_echange(self.echange_id)
        if not echange or not echange["actif"]:
            await interaction.response.send_message("Cet échange est terminé.", ephemeral=True)
            return False
        if interaction.user.id not in (echange["joueur1_id"], echange["joueur2_id"]):
            await interaction.response.send_message("Tu ne fais pas partie de cet échange !", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Modifier mon offre", emoji="🎁", style=discord.ButtonStyle.primary, row=0)
    async def modifier(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier_participant(interaction):
            return
        vue = VueChoixOffre(self.echange_id, interaction.user.id)
        await interaction.response.send_message(
            "Choisis les Pokémon à proposer (tu pourras ajouter des Poké Dollars ensuite) :",
            view=vue,
            ephemeral=True,
        )

    @discord.ui.button(label="Valider mon offre", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier_participant(interaction):
            return
        echange_pret = database.valider_offre_echange(self.echange_id, interaction.user.id)

        if echange_pret:
            succes, erreur = database.executer_echange(self.echange_id)
            echange = database.obtenir_echange(self.echange_id)
            noms = await _obtenir_noms(interaction.client, echange["joueur1_id"], echange["joueur2_id"])
            if succes:
                embed = discord.Embed(
                    title="✅ Échange conclu !",
                    description="Les Pokémon et Poké Dollars ont changé de propriétaire.",
                    color=discord.Color.green(),
                )
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(embed=embed, view=self)
                if interaction.channel:
                    import asyncio
                    async def _supprimer():
                        await asyncio.sleep(DELAI_SUPPRESSION_FIL)
                        try:
                            await interaction.channel.delete()
                        except Exception:
                            pass
                    interaction.client.loop.create_task(_supprimer())
            else:
                database.annuler_echange(self.echange_id)
                embed = discord.Embed(
                    title="❌ Échange annulé",
                    description=f"Impossible de finaliser l'échange : {erreur}",
                    color=discord.Color.red(),
                )
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            embed = construire_embed_echange(self.echange_id, await _obtenir_noms_depuis_echange(interaction.client, self.echange_id))
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send("✅ Ton offre est validée, en attente de l'autre joueur.", ephemeral=True)

    @discord.ui.button(label="Annuler l'échange", emoji="❌", style=discord.ButtonStyle.danger, row=0)
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier_participant(interaction):
            return
        database.annuler_echange(self.echange_id)
        embed = discord.Embed(
            description=f"❌ Échange annulé par {interaction.user.mention}.",
            color=discord.Color.dark_grey(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


async def _obtenir_noms(bot, j1: int, j2: int) -> dict:
    def nom(uid):
        u = bot.get_user(uid)
        return u.display_name if u else f"Joueur {str(uid)[-4:]}"
    return {j1: nom(j1), j2: nom(j2)}


async def _obtenir_noms_depuis_echange(bot, echange_id: int) -> dict:
    echange = database.obtenir_echange(echange_id)
    return await _obtenir_noms(bot, echange["joueur1_id"], echange["joueur2_id"])


async def _rafraichir_message_principal(bot, echange_id: int):
    """Met à jour le message partagé du fil après qu'un joueur ait modifié son offre
    ailleurs (menu éphémère de sélection), pour que l'autre voie le changement en direct."""
    echange = database.obtenir_echange(echange_id)
    if not echange or not echange["thread_id"] or not echange["message_id"]:
        return
    try:
        thread = bot.get_channel(int(echange["thread_id"]))
        if thread is None:
            return
        message = await thread.fetch_message(int(echange["message_id"]))
        noms = await _obtenir_noms_depuis_echange(bot, echange_id)
        embed = construire_embed_echange(echange_id, noms)
        await message.edit(embed=embed)
    except discord.HTTPException:
        pass


class VueChoixOffre(discord.ui.View):
    """Sélection paginée des Pokémon à proposer, puis un bouton pour définir le montant de PD."""

    def __init__(self, echange_id: int, user_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.echange_id = echange_id
        self.user_id = user_id
        self.page = page

        captures_actuelles = {row["id"] for row in database.obtenir_offre_echange(echange_id, user_id)}
        self.selection = captures_actuelles
        self.toutes_captures = database.obtenir_toutes_captures_detaillees(user_id)
        self._construire_composants()

    def _construire_composants(self):
        self.clear_items()
        debut = self.page * CAPTURES_PAR_PAGE
        page_captures = self.toutes_captures[debut : debut + CAPTURES_PAR_PAGE]

        options = []
        for row in page_captures:
            shiny_txt = " ✨" if row["shiny"] else ""
            options.append(
                discord.SelectOption(
                    label=f"{row['pokemon_nom']}{shiny_txt} — {row['pc']} PC"[:100],
                    value=str(row["id"]),
                    default=(row["id"] in self.selection),
                )
            )

        if options:
            select = discord.ui.Select(
                placeholder=f"Coche les Pokémon à proposer ({len(self.selection)} sélectionné(s))",
                options=options,
                min_values=0,
                max_values=len(options),
                row=0,
            )
            select.callback = self._on_select
            self.add_item(select)

        nb_pages = max(1, (len(self.toutes_captures) + CAPTURES_PAR_PAGE - 1) // CAPTURES_PAR_PAGE)
        if nb_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1, disabled=self.page == 0)
            bouton_prec.callback = self._page_prec
            self.add_item(bouton_prec)
            bouton_suiv = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=1, disabled=self.page >= nb_pages - 1)
            bouton_suiv.callback = self._page_suiv
            self.add_item(bouton_suiv)

        bouton_pd = discord.ui.Button(label="Définir les Poké Dollars", emoji="💰", style=discord.ButtonStyle.secondary, row=2)
        bouton_pd.callback = self._on_definir_pd
        self.add_item(bouton_pd)

        bouton_confirmer = discord.ui.Button(label="Confirmer cette offre", emoji="✅", style=discord.ButtonStyle.success, row=2)
        bouton_confirmer.callback = self._on_confirmer
        self.add_item(bouton_confirmer)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton offre !", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        debut = self.page * CAPTURES_PAR_PAGE
        ids_page = {row["id"] for row in self.toutes_captures[debut : debut + CAPTURES_PAR_PAGE]}
        nouvelle_selection_page = {int(v) for v in interaction.data["values"]}
        self.selection = (self.selection - ids_page) | nouvelle_selection_page
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _page_prec(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _page_suiv(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_definir_pd(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        await interaction.response.send_modal(ModalMontantPD(self))

    async def _on_confirmer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        echange = database.obtenir_echange(self.echange_id)
        pd_actuel = echange["joueur1_pd"] if echange["joueur1_id"] == self.user_id else echange["joueur2_pd"]
        database.definir_offre_echange(self.echange_id, self.user_id, list(self.selection), pd_actuel)
        await interaction.response.edit_message(
            content=f"✅ Offre mise à jour : {len(self.selection)} Pokémon proposé(s). Retourne dans le fil !",
            view=None,
        )
        await _rafraichir_message_principal(interaction.client, self.echange_id)


class ModalMontantPD(discord.ui.Modal, title="Poké Dollars à ajouter à l'offre"):
    montant = discord.ui.TextInput(label="Montant (0 pour aucun)", placeholder="ex: 200", required=True, max_length=10)

    def __init__(self, vue_parente: VueChoixOffre):
        super().__init__()
        self.vue_parente = vue_parente

    async def on_submit(self, interaction: discord.Interaction):
        try:
            montant_int = int(self.montant.value)
        except ValueError:
            await interaction.response.send_message("Montant invalide.", ephemeral=True)
            return
        if montant_int < 0:
            await interaction.response.send_message("Le montant ne peut pas être négatif.", ephemeral=True)
            return
        solde = database.obtenir_poke_dollars(self.vue_parente.user_id)
        if montant_int > solde:
            await interaction.response.send_message(
                f"Tu n'as que {solde} {EMOJI_POKEDOLLAR}, tu ne peux pas en proposer {montant_int}.", ephemeral=True
            )
            return

        database.definir_offre_echange(
            self.vue_parente.echange_id, self.vue_parente.user_id, list(self.vue_parente.selection), montant_int
        )
        await interaction.response.edit_message(
            content=f"✅ Offre mise à jour : {len(self.vue_parente.selection)} Pokémon + {montant_int} {EMOJI_POKEDOLLAR}. Retourne dans le fil !",
            view=None,
        )
        await _rafraichir_message_principal(interaction.client, self.vue_parente.echange_id)
