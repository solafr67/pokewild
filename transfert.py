import datetime

import discord

import config
import database
from pokemon_data import EMOJI_POKEDOLLAR, EMOJI_RARETE, obtenir_pokemon_par_nom


def _especes_possedees(user_id: int) -> dict:
    """Retourne {pokemon_nom: quantite} pour toutes les espèces possédées par le joueur."""
    captures = database.obtenir_pokedex_joueur(user_id)
    especes = {}
    for row in captures:
        especes[row["pokemon_nom"]] = especes.get(row["pokemon_nom"], 0) + row["quantite"]
    return especes


def construire_embed_choix_espece(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🔄 Transfert sélectif",
        description=(
            "Choisis une espèce ci-dessous, puis sélectionne précisément quels exemplaires "
            "relâcher — pratique pour garder des Pokémon en stock en vue de futurs échanges.\n\n"
            "Pour tout relâcher d'un coup (tous les doublons, toutes espèces), utilise plutôt "
            "le bouton **Relâcher les doublons** sur ton profil."
        ),
        color=discord.Color.orange(),
    )
    return embed


class VueChoixEspeceTransfert(discord.ui.View):
    """Première étape : choisir l'espèce à gérer (recherche incluse si la collection est grande)."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.recherche = None
        self._construire_composants()

    def _lister_especes(self):
        especes = _especes_possedees(self.user_id)
        noms = sorted(especes.keys())
        if self.recherche:
            terme = self.recherche.lower()
            noms = [n for n in noms if terme in n.lower()]
        return noms, especes

    def _construire_composants(self):
        self.clear_items()
        noms, especes = self._lister_especes()

        options = [
            discord.SelectOption(label=f"{nom} (x{especes[nom]})", value=nom)
            for nom in noms[:25]
        ]
        placeholder = "Choisis une espèce..."
        if self.recherche:
            placeholder = f"Choisis une espèce (recherche : {self.recherche})"
        select = discord.ui.Select(
            placeholder=placeholder,
            options=options if options else [discord.SelectOption(label="Aucune espèce trouvée", value="none")],
            disabled=not options,
            row=0,
        )
        select.callback = self._on_select_espece
        self.add_item(select)

        bouton_recherche = discord.ui.Button(
            label="Rechercher", emoji="🔍", style=discord.ButtonStyle.secondary, row=1
        )
        bouton_recherche.callback = self._on_rechercher
        self.add_item(bouton_recherche)

        if self.recherche:
            bouton_effacer = discord.ui.Button(
                label="Effacer la recherche", emoji="❌", style=discord.ButtonStyle.secondary, row=1
            )
            bouton_effacer.callback = self._on_effacer_recherche
            self.add_item(bouton_effacer)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta collection !", ephemeral=True)
            return False
        return True

    async def _on_select_espece(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        nom = interaction.data["values"][0]
        if nom == "none":
            return

        vue_selection = VueSelectionCaptures(self.user_id, nom)
        embed = vue_selection.construire_embed()
        await interaction.response.edit_message(embed=embed, view=vue_selection)

    async def _on_rechercher(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        await interaction.response.send_modal(ModalRechercheEspece(self))

    async def _on_effacer_recherche(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.recherche = None
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_choix_espece(interaction.user), view=self)


class ModalRechercheEspece(discord.ui.Modal):
    def __init__(self, vue_parente: VueChoixEspeceTransfert):
        super().__init__(title="Rechercher une espèce")
        self.vue_parente = vue_parente
        self.recherche_input = discord.ui.TextInput(
            label="Nom (ou partie du nom)", placeholder="Ex : Rat", required=False
        )
        self.add_item(self.recherche_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.vue_parente.recherche = self.recherche_input.value.strip() or None
        self.vue_parente._construire_composants()
        await interaction.response.edit_message(
            embed=construire_embed_choix_espece(interaction.user), view=self.vue_parente
        )


class VueSelectionCaptures(discord.ui.View):
    """Deuxième étape : sélection manuelle (multi-select = cases à cocher) des exemplaires
    précis à relâcher, pour l'espèce choisie."""

    def __init__(self, user_id: int, pokemon_nom: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.pokemon_nom = pokemon_nom
        self.ids_selectionnes = set()
        self._construire_composants()

    def construire_embed(self) -> discord.Embed:
        pokemon = obtenir_pokemon_par_nom(self.pokemon_nom)
        emoji_rarete = EMOJI_RARETE[pokemon["rarete"]] if pokemon else ""
        captures = database.obtenir_captures_par_espece(self.user_id, self.pokemon_nom)

        lignes = []
        for row in captures:
            coche = "☑️" if row["id"] in self.ids_selectionnes else "⬜"
            shiny_txt = " ✨" if row["shiny"] else ""
            date_txt = datetime.datetime.fromtimestamp(row["date_capture"]).strftime("%d/%m/%Y")
            lignes.append(f"{coche} {row['pc']} PC{shiny_txt} — capturé le {date_txt}")

        embed = discord.Embed(
            title=f"{emoji_rarete} Transfert sélectif — {self.pokemon_nom}",
            description="\n".join(lignes) if lignes else "Plus aucun exemplaire de cette espèce.",
            color=discord.Color.orange(),
        )
        if self.ids_selectionnes:
            recompense = config.RECOMPENSE_RELACHER * len(self.ids_selectionnes)
            embed.set_footer(
                text=f"{len(self.ids_selectionnes)} sélectionné(s) — "
                f"+{recompense} {EMOJI_POKEDOLLAR} si confirmé"
            )
        else:
            embed.set_footer(text="Sélectionne un ou plusieurs exemplaires ci-dessous.")
        return embed

    def _construire_composants(self):
        self.clear_items()
        captures = database.obtenir_captures_par_espece(self.user_id, self.pokemon_nom)

        options = []
        for row in captures[:25]:
            shiny_txt = " ✨" if row["shiny"] else ""
            date_txt = datetime.datetime.fromtimestamp(row["date_capture"]).strftime("%d/%m/%Y")
            options.append(
                discord.SelectOption(
                    label=f"{row['pc']} PC{shiny_txt} — {date_txt}",
                    value=str(row["id"]),
                    default=(row["id"] in self.ids_selectionnes),
                )
            )

        select = discord.ui.Select(
            placeholder="Coche les exemplaires à relâcher...",
            options=options if options else [discord.SelectOption(label="Aucun exemplaire", value="none")],
            disabled=not options,
            min_values=0,
            max_values=len(options) if options else 1,
            row=0,
        )
        select.callback = self._on_select_captures
        self.add_item(select)

        bouton_confirmer = discord.ui.Button(
            label="Confirmer le transfert",
            emoji="✅",
            style=discord.ButtonStyle.danger,
            disabled=not self.ids_selectionnes,
            row=1,
        )
        bouton_confirmer.callback = self._on_confirmer
        self.add_item(bouton_confirmer)

        bouton_retour = discord.ui.Button(label="Retour", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
        bouton_retour.callback = self._on_retour
        self.add_item(bouton_retour)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta collection !", ephemeral=True)
            return False
        return True

    async def _on_select_captures(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        valeurs = interaction.data["values"]
        self.ids_selectionnes = {int(v) for v in valeurs if v != "none"}
        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _on_confirmer(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        if not self.ids_selectionnes:
            return

        nb_supprimes = database.relacher_captures_par_id(self.user_id, list(self.ids_selectionnes))
        recompense = config.RECOMPENSE_RELACHER * nb_supprimes
        database.ajouter_poke_dollars(self.user_id, recompense)

        embed = discord.Embed(
            title="✅ Transfert effectué",
            description=(
                f"**{nb_supprimes}× {self.pokemon_nom}** relâché(s) — "
                f"+{recompense} {EMOJI_POKEDOLLAR} Poké Dollars"
            ),
            color=discord.Color.green(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_retour(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        vue_choix = VueChoixEspeceTransfert(self.user_id)
        await interaction.response.edit_message(
            embed=construire_embed_choix_espece(interaction.user), view=vue_choix
        )
