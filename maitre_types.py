import discord

import database
from pokemon_data import (
    ATTAQUES,
    EMOJI_TYPES,
    affichage_types,
    attaques_apprenables,
    obtenir_attaque,
    obtenir_pokemon_par_nom,
    sprite_pokemon,
)

ATTAQUES_PAR_PAGE = 25  # limite Discord d'options par menu déroulant


def _label_attaque(nom: str) -> str:
    """Label compact d'une attaque : nom, puissance ou effet de statut (sans émoji
    custom dans le texte — Discord ne les affiche pas dans les labels/descriptions
    de menu déroulant, seul le paramètre `emoji=` dédié fonctionne)."""
    attaque = obtenir_attaque(nom)
    if attaque.get("puissance"):
        return f"{nom} — {attaque['puissance']} pcs"
    if attaque.get("stats"):
        morceaux = []
        for stat, delta in attaque["stats"]:
            signe = "+" if delta > 0 else ""
            morceaux.append(f"{signe}{delta} {stat.upper()}")
        cible = "soi" if attaque.get("cible") == "soi" else "adv."
        return f"{nom} — {', '.join(morceaux)} ({cible})"
    return f"{nom} — statut"


def _description_attaque(nom: str) -> str:
    attaque = obtenir_attaque(nom)
    precision = attaque.get("precision")
    return f"Précision : {precision}%" if precision else "Ne rate jamais"


def construire_embed_maitre() -> discord.Embed:
    embed = discord.Embed(
        title="🧙 Le Maître des Types",
        description=(
            "*« Approche, dresseur ! Je peux enseigner à tes Pokémon n'importe quelle "
            "attaque qu'ils sont capables d'apprendre. Choisis bien : chaque Pokémon ne "
            "peut retenir que 4 attaques à la fois. »*\n\n"
            "Clique sur le bouton ci-dessous pour gérer les attaques de ton équipe de combat."
        ),
        color=discord.Color.purple(),
    )
    embed.set_footer(text="Sans attaque équipée, tes Pokémon utiliseront Charge (40 pcs) par défaut.")
    return embed


class VueMaitreTypes(discord.ui.View):
    """Vue persistante attachée au message fixe du Maître des Types."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Gérer les attaques",
        style=discord.ButtonStyle.primary,
        emoji="⚔️",
        custom_id="maitre_types_gerer",
    )
    async def gerer(self, interaction: discord.Interaction, button: discord.ui.Button):
        noms_equipe = database.obtenir_equipe_combat(interaction.user.id)
        if not noms_equipe:
            await interaction.response.send_message(
                "*« Reviens me voir quand tu auras configuré ton équipe de combat "
                "(`/equipe-combat`) ! »*",
                ephemeral=True,
            )
            return
        vue = VueChoixPokemonAttaques(interaction.user.id)
        await interaction.response.send_message(
            "*« Quel Pokémon veux-tu entraîner ? »*", view=vue, ephemeral=True
        )


class VueChoixPokemonAttaques(discord.ui.View):
    """Étape 1 : choisir le Pokémon de son équipe de combat à entraîner."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        noms_equipe = database.obtenir_equipe_combat(user_id)
        options = []
        for nom in noms_equipe[:25]:
            pokemon = obtenir_pokemon_par_nom(nom)
            # Texte brut uniquement : les descriptions de menu déroulant Discord n'affichent
            # pas les émojis custom (<:nom:id>), contrairement au titre de l'embed plus loin.
            types_txt = " / ".join(t.capitalize() for t in pokemon["types"]) if pokemon else None
            options.append(discord.SelectOption(label=nom, value=nom, description=types_txt))
        select = discord.ui.Select(placeholder="Choisis un Pokémon de ton équipe...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta session !", ephemeral=True)
            return
        nom = interaction.data["values"][0]
        vue = VueGestionAttaques(self.user_id, nom)
        await interaction.response.edit_message(
            content=None, embed=vue.construire_embed(), view=vue
        )


class VueGestionAttaques(discord.ui.View):
    """Étape 2 : gérer les 4 emplacements d'attaques d'un Pokémon précis.
    Choisir un emplacement (1-4), puis une attaque dans la liste déroulante paginée."""

    def __init__(self, user_id: int, pokemon_nom: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.pokemon_nom = pokemon_nom
        self.slot_selectionne = 1
        self.page = 0
        pokemon = obtenir_pokemon_par_nom(pokemon_nom)
        self.attaques_dispo = attaques_apprenables(pokemon)
        self._construire_composants()

    def construire_embed(self) -> discord.Embed:
        equipees = database.obtenir_attaques_equipees(self.user_id, self.pokemon_nom)
        lignes = []
        for slot in range(1, 5):
            fleche = "▶️ " if slot == self.slot_selectionne else "▫️ "
            if slot in equipees:
                attaque_equipee = obtenir_attaque(equipees[slot])
                emoji_type = EMOJI_TYPES.get(attaque_equipee["type"], "")
                lignes.append(f"{fleche}**Emplacement {slot}** : {emoji_type} {_label_attaque(equipees[slot])}")
            else:
                lignes.append(f"{fleche}**Emplacement {slot}** : *vide*")

        pokemon = obtenir_pokemon_par_nom(self.pokemon_nom)
        types_txt = f" ({affichage_types(pokemon['types'])})" if pokemon else ""
        embed = discord.Embed(
            title=f"⚔️ Attaques de {self.pokemon_nom}{types_txt}",
            description="\n".join(lignes),
            color=discord.Color.purple(),
        )
        if pokemon and sprite_pokemon(pokemon):
            embed.set_thumbnail(url=sprite_pokemon(pokemon))
        nb_pages = max(1, (len(self.attaques_dispo) + ATTAQUES_PAR_PAGE - 1) // ATTAQUES_PAR_PAGE)
        embed.set_footer(
            text=f"{len(self.attaques_dispo)} attaques apprenables — page {self.page + 1}/{nb_pages}"
        )
        return embed

    def _construire_composants(self):
        self.clear_items()

        # Boutons de choix d'emplacement (1-4)
        for slot in range(1, 5):
            bouton = discord.ui.Button(
                label=f"Emplacement {slot}",
                style=discord.ButtonStyle.primary if slot == self.slot_selectionne else discord.ButtonStyle.secondary,
                row=0,
            )
            bouton.callback = self._creer_callback_slot(slot)
            self.add_item(bouton)

        # Menu déroulant paginé des attaques apprenables
        debut = self.page * ATTAQUES_PAR_PAGE
        page_attaques = self.attaques_dispo[debut : debut + ATTAQUES_PAR_PAGE]
        options = []
        for nom in page_attaques:
            attaque = obtenir_attaque(nom)
            options.append(
                discord.SelectOption(
                    label=_label_attaque(nom)[:100],
                    description=_description_attaque(nom)[:100],
                    value=nom,
                    emoji=EMOJI_TYPES.get(attaque["type"]),  # seul endroit où Discord rend un émoji custom sur une option
                )
            )
        select = discord.ui.Select(
            placeholder=f"Attaque pour l'emplacement {self.slot_selectionne}...",
            options=options if options else [discord.SelectOption(label="Aucune attaque", value="none")],
            disabled=not options,
            row=1,
        )
        select.callback = self._on_select_attaque
        self.add_item(select)

        # Pagination
        nb_pages = max(1, (len(self.attaques_dispo) + ATTAQUES_PAR_PAGE - 1) // ATTAQUES_PAR_PAGE)
        if nb_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=2, disabled=self.page == 0)
            bouton_prec.callback = self._on_page_prec
            self.add_item(bouton_prec)
            bouton_suiv = discord.ui.Button(
                label="▶", style=discord.ButtonStyle.secondary, row=2, disabled=self.page >= nb_pages - 1
            )
            bouton_suiv.callback = self._on_page_suiv
            self.add_item(bouton_suiv)

        # Vider l'emplacement + retour
        bouton_vider = discord.ui.Button(label="Vider l'emplacement", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
        bouton_vider.callback = self._on_vider
        self.add_item(bouton_vider)

        bouton_retour = discord.ui.Button(label="Autre Pokémon", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
        bouton_retour.callback = self._on_retour
        self.add_item(bouton_retour)

        bouton_aleatoire = discord.ui.Button(
            label="Attaques aléatoires (remplit les 4)", emoji="🎲", style=discord.ButtonStyle.secondary, row=3
        )
        bouton_aleatoire.callback = self._on_aleatoire
        self.add_item(bouton_aleatoire)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta session !", ephemeral=True)
            return False
        return True

    def _creer_callback_slot(self, slot: int):
        async def callback(interaction: discord.Interaction):
            if not await self._verifier(interaction):
                return
            self.slot_selectionne = slot
            self._construire_composants()
            await interaction.response.edit_message(embed=self.construire_embed(), view=self)
        return callback

    async def _on_select_attaque(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        nom = interaction.data["values"][0]
        if nom == "none":
            return

        # Empêcher la même attaque dans deux emplacements
        equipees = database.obtenir_attaques_equipees(self.user_id, self.pokemon_nom)
        for slot, attaque in equipees.items():
            if attaque == nom and slot != self.slot_selectionne:
                await interaction.response.send_message(
                    f"**{nom}** est déjà équipée dans l'emplacement {slot} !", ephemeral=True
                )
                return

        database.equiper_attaque(self.user_id, self.pokemon_nom, self.slot_selectionne, nom)
        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _on_page_prec(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _on_page_suiv(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _on_vider(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        database.retirer_attaque(self.user_id, self.pokemon_nom, self.slot_selectionne)
        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _on_aleatoire(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        # Tire 4 attaques distinctes au hasard parmi celles apprenables par ce Pokémon
        # (priorité aux offensives, complétées par des attaques de statut s'il n'y en a pas assez)
        import random

        offensives = [n for n in self.attaques_dispo if ATTAQUES[n].get("puissance")]
        statuts = [n for n in self.attaques_dispo if not ATTAQUES[n].get("puissance")]
        random.shuffle(offensives)
        random.shuffle(statuts)
        tirage = (offensives[:3] + statuts)[:4] if len(offensives) >= 3 else (offensives + statuts)[:4]
        random.shuffle(tirage)  # évite que les offensives soient toujours en tête

        for slot, nom in enumerate(tirage, start=1):
            database.equiper_attaque(self.user_id, self.pokemon_nom, slot, nom)
        for slot in range(len(tirage) + 1, 5):
            database.retirer_attaque(self.user_id, self.pokemon_nom, slot)

        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _on_retour(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        vue = VueChoixPokemonAttaques(self.user_id)
        await interaction.response.edit_message(
            content="*« Quel Pokémon veux-tu entraîner ? »*", embed=None, view=vue
        )
