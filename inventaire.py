import discord

import combat as combat_module
import config
import database
import equipe_combat
from pokemon_data import (
    EMOJI_BALLS,
    EMOJI_OBJETS_DIVERS,
    EMOJI_SOINS,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
    calculer_pv_max,
)

NOMS_OBJETS = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
EMOJIS_OBJETS = {**EMOJI_BALLS, **EMOJI_SOINS, **EMOJI_OBJETS_DIVERS}
TYPES_POTIONS = set(config.PRIX_SOINS.keys()) - {"totalsoin"}  # totalsoin ne soigne pas les PV, uniquement les statuts en combat


def construire_embed_inventaire(user: discord.abc.User) -> discord.Embed:
    inventaire = database.obtenir_inventaire_balls(user.id)
    lignes = [
        f"{EMOJIS_OBJETS.get(objet, '')} **{NOMS_OBJETS.get(objet, objet)}** : {quantite}"
        for objet, quantite in sorted(inventaire.items())
        if quantite > 0
    ]
    embed = discord.Embed(
        title=f"🎒 Inventaire de {user.display_name}",
        description="\n".join(lignes) or "Ton inventaire est vide.",
        color=discord.Color.teal(),
    )
    embed.set_footer(text="Sélectionne un objet pour le supprimer ou (pour une potion) soigner directement.")
    return embed


class ModalQuantiteSuppression(discord.ui.Modal):
    """Fenêtre de saisie pour supprimer une quantité précise d'un objet."""

    def __init__(self, vue_parente: "VueInventaire", objet: str):
        super().__init__(title=f"Supprimer {NOMS_OBJETS.get(objet, objet)}")
        self.vue_parente = vue_parente
        self.objet = objet
        self.quantite_input = discord.ui.TextInput(
            label="Quantité à supprimer", placeholder="Ex : 1", required=True, max_length=4
        )
        self.add_item(self.quantite_input)

    async def on_submit(self, interaction: discord.Interaction):
        texte = self.quantite_input.value.strip()
        if not texte.isdigit() or int(texte) <= 0:
            await interaction.response.send_message(
                "❌ Merci d'entrer un nombre entier positif.", ephemeral=True
            )
            return

        quantite = int(texte)
        succes = database.retirer_plusieurs_balls(interaction.user.id, self.objet, quantite)
        if not succes:
            await interaction.response.send_message(
                "❌ Tu n'as pas cette quantité en stock.", ephemeral=True
            )
            return

        self.vue_parente.objet_selectionne = None
        self.vue_parente._construire_composants()
        await interaction.response.edit_message(
            content=f"🗑️ **{quantite}× {NOMS_OBJETS.get(self.objet, self.objet)}** supprimé(s).",
            embed=construire_embed_inventaire(interaction.user),
            view=self.vue_parente,
        )


class VueSoinDepuisInventaire(discord.ui.View):
    """Variante du soin où la potion est déjà choisie (depuis l'inventaire) — il ne
    reste plus qu'à choisir le Pokémon à soigner."""

    def __init__(self, user_id: int, potion: str):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.potion = potion
        # Voir equipe_combat.VueSoin : cible le pool de PV du raid si le joueur est
        # actuellement engagé dedans, sinon ça n'aurait aucun effet sur ses vrais PV en raid.
        self.contexte = "raid" if database.joueur_dans_raid_actif(user_id) else "normal"
        self._construire_composants()

    def _lister_blesses(self):
        noms_equipe = database.obtenir_equipe_combat(self.user_id)
        stats = equipe_combat._stats_par_espece(self.user_id)
        blesses = []
        for nom in noms_equipe:
            if nom not in stats:
                continue
            pv_max = combat_module.stats_combattant_reel(self.user_id, nom)["pv"]
            pv_actuels = database.obtenir_pv_actuels(self.user_id, nom, pv_max, contexte=self.contexte)
            if pv_actuels < pv_max:
                blesses.append((nom, pv_actuels, pv_max))
        return blesses

    def _construire_composants(self):
        self.clear_items()
        blesses = self._lister_blesses()
        options = [
            discord.SelectOption(label=f"{nom} ({pv}/{pv_max} PV)", value=nom)
            for nom, pv, pv_max in blesses[:25]
        ]
        select = discord.ui.Select(
            placeholder="Quel Pokémon soigner ?",
            options=options if options else [discord.SelectOption(label="Aucun blessé", value="none")],
            disabled=not options,
        )
        select.callback = self._on_select_pokemon
        self.add_item(select)

    async def _on_select_pokemon(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton équipe !", ephemeral=True)
            return

        nom = interaction.data["values"][0]
        if nom == "none":
            return

        if not database.retirer_ball(self.user_id, self.potion):
            await interaction.response.edit_message(content="Tu n'as plus cette potion.", view=None)
            return

        pv_max = combat_module.stats_combattant_reel(self.user_id, nom)["pv"]
        delta = max(1, round(pv_max * config.SOIN_POURCENT[self.potion]))
        nouveau_pv = database.modifier_pv_pokemon(self.user_id, nom, delta, pv_max, contexte=self.contexte)

        await interaction.response.edit_message(
            content=f"✅ **{nom}** soigné avec {NOMS_OBJETS[self.potion]} ! ({nouveau_pv}/{pv_max} PV)",
            view=None,
        )


class VueInventaire(discord.ui.View):
    """Vue éphémère pour gérer son inventaire : suppression manuelle ou soin direct."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.objet_selectionne = None
        self._construire_composants()

    def _construire_composants(self):
        self.clear_items()

        inventaire = database.obtenir_inventaire_balls(self.user_id)
        options = [
            discord.SelectOption(
                label=f"{NOMS_OBJETS.get(objet, objet)} (x{quantite})",
                value=objet,
                emoji=EMOJIS_OBJETS.get(objet),
                default=(objet == self.objet_selectionne),
            )
            for objet, quantite in sorted(inventaire.items())
            if quantite > 0
        ]
        select = discord.ui.Select(
            placeholder="Choisis un objet...",
            options=options if options else [discord.SelectOption(label="Inventaire vide", value="none")],
            disabled=not options,
            row=0,
        )
        select.callback = self._on_select_objet
        self.add_item(select)

        if self.objet_selectionne:
            bouton_supprimer = discord.ui.Button(
                label="Supprimer", emoji="🗑️", style=discord.ButtonStyle.danger, row=1
            )
            bouton_supprimer.callback = self._on_supprimer
            self.add_item(bouton_supprimer)

            if self.objet_selectionne in TYPES_POTIONS:
                bouton_soigner = discord.ui.Button(
                    label="Soigner avec", emoji="❤️‍🩹", style=discord.ButtonStyle.success, row=1
                )
                bouton_soigner.callback = self._on_soigner
                self.add_item(bouton_soigner)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton inventaire !", ephemeral=True)
            return False
        return True

    async def _on_select_objet(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        valeur = interaction.data["values"][0]
        if valeur == "none":
            return
        self.objet_selectionne = valeur
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_supprimer(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        await interaction.response.send_modal(ModalQuantiteSuppression(self, self.objet_selectionne))

    async def _on_soigner(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        if database.combat_en_cours_pour_joueur(self.user_id):
            await interaction.response.send_message(
                "❌ Impossible de soigner ton équipe pendant qu'un combat est en cours — "
                "utilise le bouton Potion directement dans le combat.",
                ephemeral=True,
            )
            return

        vue_soin = VueSoinDepuisInventaire(self.user_id, self.objet_selectionne)
        if not vue_soin._lister_blesses():
            await interaction.response.send_message(
                "Aucun de tes Pokémon d'équipe n'est blessé pour l'instant !", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Choisis le Pokémon à soigner avec **{NOMS_OBJETS[self.objet_selectionne]}** :",
            view=vue_soin,
            ephemeral=True,
        )
