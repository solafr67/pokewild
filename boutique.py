import discord

import config
import database
import journal
from pokemon_data import EMOJI_BALLS, EMOJI_POKEDOLLAR, EMOJI_SOINS, NOM_BALL_AFFICHAGE, NOM_SOIN_AFFICHAGE


# ----------------------------------------------------------------------------
# Message d'accueil (fixe, public) : juste 3 catégories, rien de plus
# ----------------------------------------------------------------------------

def construire_embed_boutique() -> discord.Embed:
    embed = discord.Embed(
        title="🛒 Boutique",
        description="Choisis une catégorie ci-dessous.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="🎯 Balls", value="Poké/Super/Hyper/Master Ball", inline=True)
    embed.add_field(name="💊 Potions", value="Potion/Super/Hyper Potion/Total Soin", inline=True)
    embed.add_field(name="📈 Améliorations", value="Extensions de stockage", inline=True)
    embed.set_footer(text="Ton solde s'affiche au moment de l'achat, visible seulement par toi.")
    return embed


class VueBoutique(discord.ui.View):
    """Vue persistante attachée au message fixe de la boutique. 3 catégories, chacune
    ouvre son propre sous-menu éphémère (visible seulement par le joueur qui clique)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Balls", emoji="🎯", style=discord.ButtonStyle.primary, custom_id="boutique_categorie_balls")
    async def categorie_balls(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=construire_embed_categorie_balls(interaction.user.id), view=VueCategorieBalls(), ephemeral=True
        )

    @discord.ui.button(label="Potions", emoji="💊", style=discord.ButtonStyle.success, custom_id="boutique_categorie_potions")
    async def categorie_potions(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=construire_embed_categorie_potions(interaction.user.id), view=VueCategoriePotions(), ephemeral=True
        )

    @discord.ui.button(label="Améliorations", emoji="📈", style=discord.ButtonStyle.secondary, custom_id="boutique_categorie_ameliorations")
    async def categorie_ameliorations(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=construire_embed_categorie_ameliorations(), view=VueCategorieAmeliorations(), ephemeral=True
        )


# ----------------------------------------------------------------------------
# Catégorie Balls
# ----------------------------------------------------------------------------

def construire_embed_categorie_balls(user_id: int) -> discord.Embed:
    inventaire = database.obtenir_inventaire_balls(user_id)
    objets_actuels = database.compter_objets_totaux(user_id)
    limite_objets = database.limite_stockage_objets(user_id)

    embed = discord.Embed(title="🎯 Boutique — Balls", color=discord.Color.blurple())
    embed.description = f"🎒 Sac : **{objets_actuels}/{limite_objets}** places utilisées"
    for ball_type, prix in config.PRIX_BALLS.items():
        possede = inventaire.get(ball_type, 0)
        embed.add_field(
            name=f"{EMOJI_BALLS.get(ball_type, '')} {NOM_BALL_AFFICHAGE[ball_type]}",
            value=f"{EMOJI_POKEDOLLAR} {prix} chacune\nTu en as : **{possede}**",
            inline=True,
        )
    embed.set_footer(text="Choisis un bouton ci-dessous pour acheter.")
    return embed


class ModalQuantiteAchat(discord.ui.Modal):
    """Fenêtre de saisie permettant d'entrer manuellement la quantité de balls à acheter."""

    def __init__(self, ball_type: str, solde_actuel: int):
        super().__init__(title=f"Acheter {NOM_BALL_AFFICHAGE[ball_type]}")
        self.ball_type = ball_type

        prix_unitaire = config.PRIX_BALLS[ball_type]
        self.quantite_input = discord.ui.TextInput(
            label=f"Quantité — {prix_unitaire} PD/u — Solde : {solde_actuel} PD",
            placeholder="Ex : 3",
            required=True,
            max_length=4,
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
        user_id = interaction.user.id
        prix_unitaire = config.PRIX_BALLS[self.ball_type]
        cout_total = prix_unitaire * quantite

        limite_objets = database.limite_stockage_objets(user_id)
        objets_actuels = database.compter_objets_totaux(user_id)
        if objets_actuels + quantite > limite_objets:
            place_restante = max(0, limite_objets - objets_actuels)
            await interaction.response.send_message(
                f"🎒 Pas assez de place dans ton sac ({objets_actuels}/{limite_objets}) ! "
                f"Il te reste {place_restante} place(s).",
                ephemeral=True,
            )
            return

        solde = database.obtenir_poke_dollars(user_id)
        if solde < cout_total:
            await interaction.response.send_message(
                f"❌ Solde insuffisant : il te faut {cout_total} Poké Dollars, tu en as {solde}.",
                ephemeral=True,
            )
            return

        database.ajouter_poke_dollars(user_id, -cout_total)
        database.ajouter_balls(user_id, self.ball_type, quantite)
        nouveau_solde = database.obtenir_poke_dollars(user_id)
        journal.logger(
            f"🛒 <@{user_id}> a acheté {quantite}× {NOM_BALL_AFFICHAGE[self.ball_type]} "
            f"pour {cout_total} PD."
        )

        await interaction.response.send_message(
            f"✅ Achat réussi : **{quantite}× {NOM_BALL_AFFICHAGE[self.ball_type]}** "
            f"pour {cout_total} Poké Dollars.\nNouveau solde : {EMOJI_POKEDOLLAR} {nouveau_solde}",
            ephemeral=True,
        )


class VueCategorieBalls(discord.ui.View):
    """Sous-menu éphémère listant les boutons d'achat pour chaque type de ball."""

    def __init__(self):
        super().__init__(timeout=120)
        for ball_type in config.PRIX_BALLS:
            bouton = discord.ui.Button(
                label=f"Acheter {NOM_BALL_AFFICHAGE[ball_type]}",
                emoji=EMOJI_BALLS.get(ball_type),
                style=discord.ButtonStyle.secondary,
            )
            bouton.callback = self._creer_callback(ball_type)
            self.add_item(bouton)

    def _creer_callback(self, ball_type: str):
        async def callback(interaction: discord.Interaction):
            solde_actuel = database.obtenir_poke_dollars(interaction.user.id)
            await interaction.response.send_modal(ModalQuantiteAchat(ball_type, solde_actuel))

        return callback


# ----------------------------------------------------------------------------
# Catégorie Potions
# ----------------------------------------------------------------------------

def construire_embed_categorie_potions(user_id: int) -> discord.Embed:
    inventaire = database.obtenir_inventaire_balls(user_id)
    objets_actuels = database.compter_objets_totaux(user_id)
    limite_objets = database.limite_stockage_objets(user_id)

    embed = discord.Embed(title="💊 Boutique — Potions", color=discord.Color.green())
    embed.description = f"🎒 Sac : **{objets_actuels}/{limite_objets}** places utilisées"
    for soin_type, prix in config.PRIX_SOINS.items():
        if soin_type == "totalsoin":
            soin_txt = "soigne tous les statuts (brûlure, poison, paralysie...) en combat"
        else:
            pourcent = round(config.SOIN_POURCENT.get(soin_type, 0) * 100)
            soin_txt = "soin complet" if pourcent >= 100 else f"+{pourcent}% des PV max"
        possede = inventaire.get(soin_type, 0)
        embed.add_field(
            name=f"{EMOJI_SOINS.get(soin_type, '')} {NOM_SOIN_AFFICHAGE[soin_type]}",
            value=f"{EMOJI_POKEDOLLAR} {prix} chacune — {soin_txt}\nTu en as : **{possede}**",
            inline=True,
        )
    embed.set_footer(text="Choisis un bouton ci-dessous pour acheter.")
    return embed


class ModalAchatSoin(discord.ui.Modal):
    """Fenêtre de saisie permettant d'entrer manuellement la quantité de potions à acheter."""

    def __init__(self, soin_type: str, solde_actuel: int):
        super().__init__(title=f"Acheter {NOM_SOIN_AFFICHAGE[soin_type]}")
        self.soin_type = soin_type

        prix_unitaire = config.PRIX_SOINS[soin_type]
        self.quantite_input = discord.ui.TextInput(
            label=f"Quantité — {prix_unitaire} PD/u — Solde : {solde_actuel} PD",
            placeholder="Ex : 3",
            required=True,
            max_length=4,
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
        user_id = interaction.user.id
        prix_unitaire = config.PRIX_SOINS[self.soin_type]
        cout_total = prix_unitaire * quantite

        limite_objets = database.limite_stockage_objets(user_id)
        objets_actuels = database.compter_objets_totaux(user_id)
        if objets_actuels + quantite > limite_objets:
            place_restante = max(0, limite_objets - objets_actuels)
            await interaction.response.send_message(
                f"🎒 Pas assez de place dans ton sac ({objets_actuels}/{limite_objets}) ! "
                f"Il te reste {place_restante} place(s).",
                ephemeral=True,
            )
            return

        solde = database.obtenir_poke_dollars(user_id)
        if solde < cout_total:
            await interaction.response.send_message(
                f"❌ Solde insuffisant : il te faut {cout_total} Poké Dollars, tu en as {solde}.",
                ephemeral=True,
            )
            return

        database.ajouter_poke_dollars(user_id, -cout_total)
        database.ajouter_balls(user_id, self.soin_type, quantite)
        nouveau_solde = database.obtenir_poke_dollars(user_id)
        journal.logger(
            f"🛒 <@{user_id}> a acheté {quantite}× {NOM_SOIN_AFFICHAGE[self.soin_type]} "
            f"pour {cout_total} PD."
        )

        await interaction.response.send_message(
            f"✅ Achat réussi : **{quantite}× {NOM_SOIN_AFFICHAGE[self.soin_type]}** "
            f"pour {cout_total} Poké Dollars.\nNouveau solde : {EMOJI_POKEDOLLAR} {nouveau_solde}",
            ephemeral=True,
        )


class VueCategoriePotions(discord.ui.View):
    """Sous-menu éphémère listant les boutons d'achat pour chaque type de potion."""

    def __init__(self):
        super().__init__(timeout=120)
        for soin_type in config.PRIX_SOINS:
            bouton = discord.ui.Button(
                label=f"Acheter {NOM_SOIN_AFFICHAGE[soin_type]}",
                emoji=EMOJI_SOINS.get(soin_type),
                style=discord.ButtonStyle.secondary,
            )
            bouton.callback = self._creer_callback(soin_type)
            self.add_item(bouton)

    def _creer_callback(self, soin_type: str):
        async def callback(interaction: discord.Interaction):
            solde_actuel = database.obtenir_poke_dollars(interaction.user.id)
            await interaction.response.send_modal(ModalAchatSoin(soin_type, solde_actuel))

        return callback


# ----------------------------------------------------------------------------
# Catégorie Améliorations (extensions de stockage, par paliers de 10, quantité au choix)
# ----------------------------------------------------------------------------

def construire_embed_categorie_ameliorations() -> discord.Embed:
    embed = discord.Embed(
        title="📈 Boutique — Améliorations",
        description="Achetables par paliers, en choisissant la quantité de paliers voulue.",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="📦 Extension stockage Pokémon",
        value=(
            f"+{config.EXTENSION_STOCKAGE_POKEMON} places par palier — "
            f"{EMOJI_POKEDOLLAR} {config.PRIX_EXTENSION_STOCKAGE_POKEMON} / palier"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎒 Extension stockage objets",
        value=(
            f"+{config.EXTENSION_STOCKAGE_OBJETS} places par palier — "
            f"{EMOJI_POKEDOLLAR} {config.PRIX_EXTENSION_STOCKAGE_OBJETS} / palier"
        ),
        inline=False,
    )
    embed.add_field(
        name="🗺️ 2e emplacement d'exploration",
        value=f"Achat unique — {EMOJI_POKEDOLLAR} {config.EXTENSION_SLOT_EXPLORATION_PRIX}",
        inline=False,
    )
    return embed


class ModalAchatExtension(discord.ui.Modal):
    """Fenêtre de saisie pour choisir combien de PALIERS d'extension acheter d'un coup."""

    NOMS = {
        "pokemon": "Extension stockage Pokémon",
        "objets": "Extension stockage objets",
    }

    def __init__(self, type_extension: str, solde_actuel: int):
        super().__init__(title=f"Acheter : {self.NOMS[type_extension]}")
        self.type_extension = type_extension

        if type_extension == "pokemon":
            prix_palier = config.PRIX_EXTENSION_STOCKAGE_POKEMON
            gain_palier = config.EXTENSION_STOCKAGE_POKEMON
        else:
            prix_palier = config.PRIX_EXTENSION_STOCKAGE_OBJETS
            gain_palier = config.EXTENSION_STOCKAGE_OBJETS

        self.quantite_input = discord.ui.TextInput(
            label=f"Paliers (+{gain_palier}/u) — {prix_palier} PD/u — Solde : {solde_actuel} PD",
            placeholder="Ex : 1",
            required=True,
            max_length=3,
        )
        self.add_item(self.quantite_input)

    async def on_submit(self, interaction: discord.Interaction):
        texte = self.quantite_input.value.strip()

        if not texte.isdigit() or int(texte) <= 0:
            await interaction.response.send_message(
                "❌ Merci d'entrer un nombre entier positif.", ephemeral=True
            )
            return

        quantite_paliers = int(texte)
        user_id = interaction.user.id

        if self.type_extension == "pokemon":
            prix_palier = config.PRIX_EXTENSION_STOCKAGE_POKEMON
            gain_palier = config.EXTENSION_STOCKAGE_POKEMON
        else:
            prix_palier = config.PRIX_EXTENSION_STOCKAGE_OBJETS
            gain_palier = config.EXTENSION_STOCKAGE_OBJETS

        cout_total = prix_palier * quantite_paliers
        gain_total = gain_palier * quantite_paliers

        solde = database.obtenir_poke_dollars(user_id)
        if solde < cout_total:
            await interaction.response.send_message(
                f"❌ Solde insuffisant : il te faut {cout_total} Poké Dollars, tu en as {solde}.",
                ephemeral=True,
            )
            return

        database.ajouter_poke_dollars(user_id, -cout_total)
        if self.type_extension == "pokemon":
            database.acheter_extension_stockage_pokemon(user_id, quantite_paliers)
            nouvelle_limite = database.limite_stockage_pokemon(user_id)
        else:
            database.acheter_extension_stockage_objets(user_id, quantite_paliers)
            nouvelle_limite = database.limite_stockage_objets(user_id)
        journal.logger(
            f"🛒 <@{user_id}> a acheté {quantite_paliers} palier(s) d'extension "
            f"({self.type_extension}) pour {cout_total} PD."
        )

        await interaction.response.send_message(
            f"✅ Stockage étendu de **{gain_total}** places pour {cout_total} {EMOJI_POKEDOLLAR} ! "
            f"Nouvelle limite : **{nouvelle_limite}**.",
            ephemeral=True,
        )


class VueCategorieAmeliorations(discord.ui.View):
    """Sous-menu éphémère pour acheter des extensions, en choisissant la quantité de paliers."""

    def __init__(self):
        super().__init__(timeout=120)

        bouton_pokemon = discord.ui.Button(
            label=f"Extension stockage Pokémon (+{config.EXTENSION_STOCKAGE_POKEMON}/palier)",
            emoji="📦",
            style=discord.ButtonStyle.success,
        )
        bouton_pokemon.callback = self._callback_pokemon
        self.add_item(bouton_pokemon)

        bouton_objets = discord.ui.Button(
            label=f"Extension stockage objets (+{config.EXTENSION_STOCKAGE_OBJETS}/palier)",
            emoji="🎒",
            style=discord.ButtonStyle.success,
        )
        bouton_objets.callback = self._callback_objets
        self.add_item(bouton_objets)

        bouton_exploration = discord.ui.Button(
            label=f"2e emplacement d'exploration — {config.EXTENSION_SLOT_EXPLORATION_PRIX} PD",
            emoji="🗺️",
            style=discord.ButtonStyle.success,
        )
        bouton_exploration.callback = self._callback_exploration
        self.add_item(bouton_exploration)

    async def _callback_pokemon(self, interaction: discord.Interaction):
        solde_actuel = database.obtenir_poke_dollars(interaction.user.id)
        await interaction.response.send_modal(ModalAchatExtension("pokemon", solde_actuel))

    async def _callback_objets(self, interaction: discord.Interaction):
        solde_actuel = database.obtenir_poke_dollars(interaction.user.id)
        await interaction.response.send_modal(ModalAchatExtension("objets", solde_actuel))

    async def _callback_exploration(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if database.nb_slots_exploration(user_id) >= 2:
            await interaction.response.send_message("Tu as déjà 2 emplacements d'exploration !", ephemeral=True)
            return
        solde = database.obtenir_poke_dollars(user_id)
        prix = config.EXTENSION_SLOT_EXPLORATION_PRIX
        if solde < prix:
            await interaction.response.send_message(
                f"❌ Solde insuffisant : il te faut {prix} Poké Dollars, tu en as {solde}.", ephemeral=True
            )
            return
        database.ajouter_poke_dollars(user_id, -prix)
        database.acheter_slot_exploration(user_id)
        nouveau_solde = database.obtenir_poke_dollars(user_id)
        await interaction.response.send_message(
            f"✅ 2e emplacement d'exploration débloqué pour {prix} Poké Dollars !\n"
            f"Nouveau solde : {EMOJI_POKEDOLLAR} {nouveau_solde}",
            ephemeral=True,
        )

