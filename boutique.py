import random
import time

import discord

import capacites as capacites_module
import config
import database
import formes_objets as formes_objets_module
import journal
import mega_evolutions as mega_evolutions_module
from pokemon_data import (
    EMOJI_BALLS, EMOJI_OBJETS_DIVERS, EMOJI_POKEDOLLAR, EMOJI_SOINS, NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS, NOM_SOIN_AFFICHAGE, emoji_pour_objet, prix_ct, toutes_attaques_utilisables,
)


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
    embed.add_field(name="🎒 Objets", value="Objets tenus de combat (talents, Objets Choix, baies...)", inline=True)
    embed.add_field(name="🎖️ Rôle VIP", value="Accès permanent au channel spawn-vip", inline=True)
    embed.add_field(name="💠 Gemmes Méga", value="Méga-Évolutions activables en combat", inline=True)
    embed.set_footer(text="Ton solde s'affiche au moment de l'achat, visible seulement par toi.")
    return embed


# ----------------------------------------------------------------------------
# Marché Noir — SPAWN TEMPORAIRE public dans le Village Pokémon (posté et retiré par
# boucle_evenement_marche_noir dans main.py, PAS un bouton permanent de la boutique).
# Objets normalement UNIQUEMENT gagnés par le hasard (exploration, quêtes, roguelike) à
# prix fort, + CT à prix réduit. Rotation quotidienne : 2 objets rares + 2 CT, tirés au
# hasard mais de façon DÉTERMINISTE à partir de la date du jour (même sélection pour
# tout le monde, stable toute la journée).
#
# ⚠️ Message PARTAGÉ par tous les joueurs qui le voient — impossible de désactiver un
# bouton "déjà acheté" pour un seul joueur sans que ça s'applique à tout le monde. Les
# boutons restent donc TOUJOURS actifs ; chaque plafond (voir config.CAP_MARCHE_NOIR_*)
# est vérifié individuellement au moment du clic, pas via l'état visuel du bouton.
# ----------------------------------------------------------------------------

def _rotation_marche_noir_du_jour() -> tuple:
    date_du_jour = time.strftime("%Y-%m-%d")
    rng = random.Random(date_du_jour)
    pool_objets = list(config.PRIX_MARCHE_NOIR_COMMUN.keys()) + list(config.PRIX_MARCHE_NOIR_LEGENDAIRE.keys())
    objets_rares = rng.sample(pool_objets, config.NB_OBJETS_RARES_MARCHE_NOIR)
    cts = rng.sample(toutes_attaques_utilisables(), config.NB_CT_MARCHE_NOIR)
    return objets_rares, cts


def _nom_emoji_prix_objet_rare(cle: str) -> tuple:
    if cle in config.PRIX_MARCHE_NOIR_COMMUN:
        return NOM_OBJETS_DIVERS[cle], EMOJI_OBJETS_DIVERS[cle], config.PRIX_MARCHE_NOIR_COMMUN[cle], config.CAP_MARCHE_NOIR_COMMUN
    info = formes_objets_module.FORMES_OBJETS[cle]
    return info["objet_nom"], info["objet_emoji"], config.PRIX_MARCHE_NOIR_LEGENDAIRE[cle], config.CAP_MARCHE_NOIR_LEGENDAIRE


def construire_embed_marche_noir() -> discord.Embed:
    """Embed PUBLIC, sans état par-joueur (voir avertissement ci-dessus) — les plafonds
    individuels sont mentionnés en toutes lettres plutôt qu'affichés dynamiquement."""
    objets_rares, cts = _rotation_marche_noir_du_jour()
    minutes = config.DUREE_MARCHE_NOIR // 60
    embed = discord.Embed(
        title="🏴‍☠️ Marché Noir",
        description=(
            "*Des objets qu'on ne trouve nulle part ailleurs... contre le bon prix.*\n"
            f"*Ouvert pour **{minutes} minutes** seulement — ne repassera pas avant demain !*"
        ),
        color=discord.Color.dark_red(),
    )

    lignes_rares = []
    for cle in objets_rares:
        nom, emoji, prix, plafond = _nom_emoji_prix_objet_rare(cle)
        lignes_rares.append(f"{emoji} **{nom}** — {prix} {EMOJI_POKEDOLLAR} *(max {plafond}/joueur)*")
    embed.add_field(name="💎 Objets rares du jour", value="\n".join(lignes_rares), inline=False)

    lignes_ct = []
    for nom_attaque in cts:
        prix_normal = prix_ct(nom_attaque)
        prix_reduit = round(prix_normal * (1 - config.REMISE_MARCHE_NOIR_CT))
        lignes_ct.append(f"📘 **CT {nom_attaque}** — ~~{prix_normal}~~ **{prix_reduit}** {EMOJI_POKEDOLLAR} *(max {config.CAP_MARCHE_NOIR_CT}/joueur)*")
    embed.add_field(name=f"📘 CT à prix réduit (-{int(config.REMISE_MARCHE_NOIR_CT * 100)}%)", value="\n".join(lignes_ct), inline=False)

    embed.set_footer(text="Chaque joueur a son propre plafond d'achat — clique pour voir si tu l'as déjà atteint.")
    return embed


class ModalQuantiteMarcheNoir(discord.ui.Modal):
    """Quantité choisie directement plutôt que de devoir recliquer le bouton plusieurs
    fois — surtout utile pour les objets communs (plafond 3), les légendaires/CT ayant
    de toute façon un plafond de 1 (pas de quantité à choisir dans leur cas, voir
    _creer_callback_ct qui reste un achat direct)."""

    def __init__(self, cle: str, nom: str, emoji: str, prix: int, plafond: int, deja_achete: int):
        super().__init__(title=f"Acheter {nom}"[:45])
        self.cle = cle
        self.nom = nom
        self.emoji = emoji
        self.prix = prix
        self.plafond = plafond
        self.deja_achete = deja_achete
        restant = plafond - deja_achete

        self.quantite_input = discord.ui.TextInput(
            label=f"Quantité (max {restant}, {prix} PD/u)"[:45],
            placeholder="1",
            max_length=2,
        )
        self.add_item(self.quantite_input)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        texte = self.quantite_input.value.strip()
        if not texte.isdigit() or int(texte) <= 0:
            await interaction.response.send_message("❌ Merci d'entrer un nombre entier positif.", ephemeral=True)
            return
        quantite = int(texte)

        # Revérifié au moment de la confirmation (pas seulement à l'ouverture de la
        # modale) — évite un dépassement si le joueur a traîné avant de valider.
        deja_actuel = database.compter_achats_marche_noir(user_id, self.cle)
        restant = self.plafond - deja_actuel
        if restant <= 0:
            await interaction.response.send_message(
                f"❌ Tu as déjà atteint ta limite de {self.plafond} pour **{self.nom}** aujourd'hui !", ephemeral=True
            )
            return
        if quantite > restant:
            await interaction.response.send_message(
                f"❌ Il ne te reste que {restant} exemplaire(s) possible(s) pour **{self.nom}** aujourd'hui (limite {self.plafond}).",
                ephemeral=True,
            )
            return

        cout_total = self.prix * quantite
        solde = database.obtenir_poke_dollars(user_id)
        if solde < cout_total:
            await interaction.response.send_message(
                f"❌ Solde insuffisant : il te faut {cout_total} {EMOJI_POKEDOLLAR}, tu en as {solde}.", ephemeral=True
            )
            return

        database.ajouter_poke_dollars(user_id, -cout_total)
        database.ajouter_balls(user_id, self.cle, quantite)
        database.incrementer_achat_marche_noir(user_id, self.cle, quantite)
        journal.logger(
            f"🏴‍☠️ <@{user_id}> a acheté {quantite}× {self.nom} au Marché Noir pour {cout_total} PD "
            f"({deja_actuel + quantite}/{self.plafond})."
        )
        await interaction.response.send_message(
            f"✅ Acheté : {self.emoji} **{quantite}× {self.nom}** pour {cout_total} {EMOJI_POKEDOLLAR} "
            f"({deja_actuel + quantite}/{self.plafond} aujourd'hui).",
            ephemeral=True,
        )


class VueMarcheNoir(discord.ui.View):
    """Vue PARTAGÉE (pas de user_id constructeur) — un seul message pour tout le monde
    pendant tout le créneau. timeout=None : doit tenir jusqu'à 1h, largement au-delà du
    timeout par défaut d'une vue Discord classique."""

    def __init__(self):
        super().__init__(timeout=None)
        objets_rares, cts = _rotation_marche_noir_du_jour()

        for cle in objets_rares:
            nom, _emoji, _prix, _plafond = _nom_emoji_prix_objet_rare(cle)
            bouton = discord.ui.Button(
                label=nom[:80], emoji="💎", style=discord.ButtonStyle.danger, custom_id=f"marche_noir_rare_{cle}"
            )
            bouton.callback = self._creer_callback_rare(cle)
            self.add_item(bouton)

        for nom_attaque in cts:
            bouton = discord.ui.Button(
                label=f"CT {nom_attaque}"[:80], emoji="📘", style=discord.ButtonStyle.primary,
                custom_id=f"marche_noir_ct_{nom_attaque}",
            )
            bouton.callback = self._creer_callback_ct(nom_attaque)
            self.add_item(bouton)

    def _creer_callback_rare(self, cle: str):
        async def callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            nom, emoji, prix, plafond = _nom_emoji_prix_objet_rare(cle)
            deja = database.compter_achats_marche_noir(user_id, cle)
            if deja >= plafond:
                await interaction.response.send_message(
                    f"❌ Tu as déjà atteint ta limite de {plafond} pour **{nom}** aujourd'hui !", ephemeral=True
                )
                return
            await interaction.response.send_modal(ModalQuantiteMarcheNoir(cle, nom, emoji, prix, plafond, deja))
        return callback

    def _creer_callback_ct(self, nom_attaque: str):
        async def callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            cle_suivi = f"ct_{nom_attaque}"
            if database.compter_achats_marche_noir(user_id, cle_suivi) >= config.CAP_MARCHE_NOIR_CT:
                await interaction.response.send_message(f"❌ Tu as déjà acheté la CT **{nom_attaque}** aujourd'hui !", ephemeral=True)
                return
            if nom_attaque in database.obtenir_ct_possedees(user_id):
                await interaction.response.send_message("❌ Tu possèdes déjà cette CT !", ephemeral=True)
                return
            prix_normal = prix_ct(nom_attaque)
            prix_reduit = round(prix_normal * (1 - config.REMISE_MARCHE_NOIR_CT))
            solde = database.obtenir_poke_dollars(user_id)
            if solde < prix_reduit:
                await interaction.response.send_message(
                    f"❌ Solde insuffisant : il te faut {prix_reduit} {EMOJI_POKEDOLLAR}, tu en as {solde}.", ephemeral=True
                )
                return
            database.ajouter_poke_dollars(user_id, -prix_reduit)
            database.acheter_ct(user_id, nom_attaque)
            database.incrementer_achat_marche_noir(user_id, cle_suivi)
            journal.logger(f"🏴‍☠️ <@{user_id}> a acheté la CT {nom_attaque} au Marché Noir pour {prix_reduit} PD.")
            await interaction.response.send_message(
                f"✅ CT achetée : **{nom_attaque}** pour {prix_reduit} {EMOJI_POKEDOLLAR} (au lieu de {prix_normal}).",
                ephemeral=True,
            )
        return callback


class VueBoutique(discord.ui.View):
    """Vue persistante attachée au message fixe de la boutique. 4 catégories, chacune
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

    @discord.ui.button(label="Objets", emoji="🎒", style=discord.ButtonStyle.secondary, custom_id="boutique_categorie_objets")
    async def categorie_objets(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=construire_embed_categorie_objets(interaction.user.id), view=VueCategorieObjets(), ephemeral=True
        )

    @discord.ui.button(label="Rôle VIP", emoji="🎖️", style=discord.ButtonStyle.secondary, custom_id="boutique_role_vip")
    async def role_vip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=construire_embed_role_vip(interaction.user), view=VueAchatRoleVip(), ephemeral=True
        )

    @discord.ui.button(label="Gemmes Méga", emoji="💠", style=discord.ButtonStyle.secondary, custom_id="boutique_categorie_gemmes_mega")
    async def categorie_gemmes_mega(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=construire_embed_categorie_gemmes_mega(interaction.user.id), view=VueCategorieGemmesMega(), ephemeral=True
        )


# ----------------------------------------------------------------------------
# Catégorie Rôle PokéVIP — achat permanent, unique, donne accès au channel
# spawn-vip (le rôle existait déjà, attribué à la main aux joueurs fidèles ; ceci
# ajoute une seconde voie d'accès, achetable, sans rien retirer à la première).
# ----------------------------------------------------------------------------

def construire_embed_role_vip(membre: discord.Member) -> discord.Embed:
    role = membre.guild.get_role(config.ROLE_VIP_ID)
    deja_possede = role in membre.roles if role else False

    embed = discord.Embed(
        title="🎖️ Rôle PokéVIP",
        description=(
            "Un achat **permanent, à vie** — donne accès au channel spawn-vip, où les "
            "chances de rareté sont meilleures qu'en spawn classique.\n\n"
            f"**Prix : {config.PRIX_ROLE_VIP} {EMOJI_POKEDOLLAR} Poké Dollars**"
        ),
        color=discord.Color.gold(),
    )
    if deja_possede:
        embed.set_footer(text="Tu as déjà ce rôle !")
    else:
        embed.add_field(
            name="Ton solde actuel",
            value=f"{database.obtenir_poke_dollars(membre.id)} {EMOJI_POKEDOLLAR}",
            inline=False,
        )
    return embed


class VueAchatRoleVip(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Confirmer l'achat", emoji="✅", style=discord.ButtonStyle.success)
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(config.ROLE_VIP_ID)
        if role is None:
            await interaction.response.send_message("❌ Le rôle VIP est introuvable sur ce serveur (contacte un admin).", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.response.send_message("Tu as déjà le rôle PokéVIP !", ephemeral=True)
            return

        solde = database.obtenir_poke_dollars(interaction.user.id)
        if solde < config.PRIX_ROLE_VIP:
            manque = config.PRIX_ROLE_VIP - solde
            await interaction.response.send_message(
                f"❌ Il te manque {manque} {EMOJI_POKEDOLLAR} Poké Dollars pour te l'offrir.", ephemeral=True
            )
            return

        try:
            await interaction.user.add_roles(role, reason="Achat boutique — Rôle PokéVIP")
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ Impossible de t'attribuer le rôle : {e}", ephemeral=True)
            return

        database.ajouter_poke_dollars(interaction.user.id, -config.PRIX_ROLE_VIP)
        journal.logger(f"🎖️ <@{interaction.user.id}> a acheté le rôle PokéVIP pour {config.PRIX_ROLE_VIP} Poké Dollars.")

        await interaction.response.edit_message(
            content=f"🎖️ Rôle PokéVIP obtenu ! Bienvenue dans le channel spawn-vip.", embed=None, view=None
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
                emoji=emoji_pour_objet(soin_type, EMOJI_SOINS.get(soin_type)),
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


# ----------------------------------------------------------------------------
# Catégorie Objets tenus de combat
# ----------------------------------------------------------------------------

def construire_embed_categorie_objets(user_id: int) -> discord.Embed:
    objets_actuels = database.compter_objets_totaux(user_id)
    limite_objets = database.limite_stockage_objets(user_id)
    embed = discord.Embed(title="🎒 Boutique — Objets tenus de combat", color=discord.Color.blurple())
    embed.description = (
        f"🎒 Sac : **{objets_actuels}/{limite_objets}** places utilisées\n\n"
        "Ces objets s'équipent ensuite sur un de tes Pokémon au Maître des Capacités "
        "(bouton **Objets tenus**).\n\n"
        "Choisis un objet dans le menu ci-dessous pour l'acheter."
    )
    embed.set_footer(text="Prix indicatifs — un objet équipé reste actif tant que tu ne le changes pas.")
    return embed


class ModalQuantiteAchatObjet(discord.ui.Modal):
    """Fenêtre de saisie permettant d'entrer manuellement la quantité d'objets à acheter."""

    def __init__(self, type_objet: str, solde_actuel: int):
        info = capacites_module.infos_objet(type_objet)
        super().__init__(title=f"Acheter {info['nom']}"[:45])
        self.type_objet = type_objet

        prix_unitaire = config.PRIX_OBJETS_TENUS[type_objet]
        self.quantite_input = discord.ui.TextInput(
            label=f"Quantité — {prix_unitaire} PD/u — Solde : {solde_actuel} PD"[:45],
            placeholder="Ex : 1",
            required=True,
            max_length=3,
        )
        self.add_item(self.quantite_input)

    async def on_submit(self, interaction: discord.Interaction):
        texte = self.quantite_input.value.strip()
        if not texte.isdigit() or int(texte) <= 0:
            await interaction.response.send_message("❌ Merci d'entrer un nombre entier positif.", ephemeral=True)
            return

        quantite = int(texte)
        user_id = interaction.user.id
        info = capacites_module.infos_objet(self.type_objet)
        prix_unitaire = config.PRIX_OBJETS_TENUS[self.type_objet]
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
        database.ajouter_balls(user_id, self.type_objet, quantite)
        nouveau_solde = database.obtenir_poke_dollars(user_id)
        journal.logger(f"🛒 <@{user_id}> a acheté {quantite}× {info['nom']} pour {cout_total} PD.")

        embed_achat = discord.Embed(
            description=(
                f"✅ Achat réussi : **{quantite}× {info['emoji']} {info['nom']}** pour {cout_total} Poké Dollars.\n"
                f"Nouveau solde : {EMOJI_POKEDOLLAR} {nouveau_solde}\nÉquipe-le au Maître des Capacités (bouton **Objets tenus**)."
            ),
            color=discord.Color.green(),
        )
        if info.get("image"):
            embed_achat.set_thumbnail(url=info["image"])
        await interaction.response.send_message(embed=embed_achat, ephemeral=True)


class VueCategorieObjets(discord.ui.View):
    """Sous-menu éphémère : un menu déroulant listant les 20 objets tenus (nom + prix),
    la sélection ouvre une fenêtre de saisie de quantité (même principe que Balls/Potions)."""

    def __init__(self):
        super().__init__(timeout=120)
        options = [
            discord.SelectOption(
                label=f"{info['nom']} — {config.PRIX_OBJETS_TENUS[cle]} PD"[:100],
                value=cle,
                description=info["description"][:100],
                emoji=emoji_pour_objet(cle, info["emoji"]),
            )
            for cle, info in capacites_module.OBJETS_TENUS.items()
        ]
        select = discord.ui.Select(placeholder="Choisis un objet à acheter…", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        type_objet = interaction.data["values"][0]
        solde_actuel = database.obtenir_poke_dollars(interaction.user.id)
        await interaction.response.send_modal(ModalQuantiteAchatObjet(type_objet, solde_actuel))


# ----------------------------------------------------------------------------
# Catégorie Gemmes Méga — mega_evolutions.py — prix unique pour les 21, contrairement
# aux objets tenus classiques (prix variable par objet). Même principe d'achat sinon
# (menu déroulant -> fenêtre de saisie de quantité -> déduction PD + ajout au sac).
# ----------------------------------------------------------------------------

def construire_embed_categorie_gemmes_mega(user_id: int) -> discord.Embed:
    objets_actuels = database.compter_objets_totaux(user_id)
    limite_objets = database.limite_stockage_objets(user_id)
    embed = discord.Embed(title="💠 Boutique — Gemmes Méga", color=discord.Color.purple())
    embed.description = (
        f"🎒 Sac : **{objets_actuels}/{limite_objets}** places utilisées\n\n"
        f"Permettent à un Pokémon compatible de **Méga-Évoluer en combat** (PvP, Draft, "
        f"Dresseurs, Arène, Repaires) — statistiques boostées pour le reste du "
        f"combat, une seule fois par combat, jamais les PV.\n\n"
        f"**Prix unique : {config.PRIX_GEMME_MEGA} {EMOJI_POKEDOLLAR}/gemme**\n\n"
        "S'équipent au Maître des Capacités (bouton **Objets tenus**), s'activent avec le bouton dédié en combat.\n\n"
        "Choisis une gemme dans le menu ci-dessous pour l'acheter."
    )
    embed.set_footer(text="Une gemme donnée ne fonctionne que sur son espèce précise.")
    return embed


class ModalQuantiteAchatGemmeMega(discord.ui.Modal):
    """Fenêtre de saisie de quantité — même principe que ModalQuantiteAchatObjet, mais
    prix unique (PRIX_GEMME_MEGA) au lieu d'un prix par objet."""

    def __init__(self, cle_gemme: str, solde_actuel: int):
        info = mega_evolutions_module.MEGA_EVOLUTIONS[cle_gemme]
        super().__init__(title=f"Acheter {info['objet_nom']}"[:45])
        self.cle_gemme = cle_gemme

        self.quantite_input = discord.ui.TextInput(
            label=f"Quantité — {config.PRIX_GEMME_MEGA} PD/u — Solde : {solde_actuel} PD"[:45],
            placeholder="Ex : 1",
            required=True,
            max_length=3,
        )
        self.add_item(self.quantite_input)

    async def on_submit(self, interaction: discord.Interaction):
        texte = self.quantite_input.value.strip()
        if not texte.isdigit() or int(texte) <= 0:
            await interaction.response.send_message("❌ Merci d'entrer un nombre entier positif.", ephemeral=True)
            return

        quantite = int(texte)
        user_id = interaction.user.id
        info = mega_evolutions_module.MEGA_EVOLUTIONS[self.cle_gemme]
        cout_total = config.PRIX_GEMME_MEGA * quantite

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
        database.ajouter_balls(user_id, self.cle_gemme, quantite)
        nouveau_solde = database.obtenir_poke_dollars(user_id)
        journal.logger(f"💠 <@{user_id}> a acheté {quantite}× {info['objet_nom']} pour {cout_total} PD.")

        embed_achat = discord.Embed(
            description=(
                f"✅ Achat réussi : **{quantite}× {info['objet_emoji']} {info['objet_nom']}** pour {cout_total} Poké Dollars.\n"
                f"Nouveau solde : {EMOJI_POKEDOLLAR} {nouveau_solde}\n"
                f"Équipe-la sur **{info['espece']}** au Maître des Capacités (bouton **Objets tenus**) pour pouvoir Méga-Évoluer en combat."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed_achat, ephemeral=True)


GEMMES_PAR_PAGE = 24  # marge de sécurité sous la vraie limite Discord de 25 options/select


class VueCategorieGemmesMega(discord.ui.View):
    """Sous-menu éphémère : menu déroulant paginé + recherche sur les 50 Gemmes Méga
    (espèce + prix unique), la sélection ouvre une fenêtre de saisie de quantité.

    Paginé car Discord plafonne un menu déroulant à 25 options MAXIMUM — avec 50
    gemmes, un seul select géant plantait l'ouverture entière de la boutique
    (discord.errors.HTTPException: 400, 'Must be between 1 and 25 in length')."""

    def __init__(self, page: int = 0, recherche: str = None):
        super().__init__(timeout=120)
        self.page = page
        self.recherche = recherche
        self._construire_composants()

    def _gemmes_filtrees(self) -> list:
        items = list(mega_evolutions_module.MEGA_EVOLUTIONS.items())
        if self.recherche:
            terme = self.recherche.lower()
            items = [
                (cle, info) for cle, info in items
                if terme in info["objet_nom"].lower() or terme in info["espece"].lower()
            ]
        return items

    def _construire_composants(self):
        self.clear_items()
        gemmes = self._gemmes_filtrees()

        if gemmes:
            debut = self.page * GEMMES_PAR_PAGE
            page_gemmes = gemmes[debut : debut + GEMMES_PAR_PAGE]
            options = [
                discord.SelectOption(
                    label=f"{info['objet_nom']} — {info['espece']} — {config.PRIX_GEMME_MEGA} PD"[:100],
                    value=cle,
                    description=f"Devient {info['forme_nom']} en combat"[:100],
                    emoji=info["objet_emoji"],
                )
                for cle, info in page_gemmes
            ]
            select = discord.ui.Select(placeholder="Choisis une gemme à acheter…", options=options, row=0)
            select.callback = self._on_select
            self.add_item(select)
        # Aucun résultat pour la recherche en cours : pas de select vide, les boutons de
        # recherche/pagination restent quand même disponibles plus bas.

        nb_pages = max(1, (len(gemmes) + GEMMES_PAR_PAGE - 1) // GEMMES_PAR_PAGE)
        if nb_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1, disabled=self.page == 0)
            bouton_prec.callback = self._page_prec
            self.add_item(bouton_prec)
            bouton_suiv = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=1, disabled=self.page >= nb_pages - 1)
            bouton_suiv.callback = self._page_suiv
            self.add_item(bouton_suiv)

        bouton_recherche = discord.ui.Button(
            label=f"Recherche : {self.recherche}" if self.recherche else "Rechercher",
            emoji="🔍",
            style=discord.ButtonStyle.primary if self.recherche else discord.ButtonStyle.secondary,
            row=1,
        )
        bouton_recherche.callback = self._on_rechercher
        self.add_item(bouton_recherche)
        if self.recherche:
            bouton_effacer = discord.ui.Button(label="Effacer", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
            bouton_effacer.callback = self._on_effacer_recherche
            self.add_item(bouton_effacer)

    async def _on_select(self, interaction: discord.Interaction):
        cle_gemme = interaction.data["values"][0]
        solde_actuel = database.obtenir_poke_dollars(interaction.user.id)
        await interaction.response.send_modal(ModalQuantiteAchatGemmeMega(cle_gemme, solde_actuel))

    async def _page_prec(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _page_suiv(self, interaction: discord.Interaction):
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_rechercher(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ModalRechercheGemmeMega(self))

    async def _on_effacer_recherche(self, interaction: discord.Interaction):
        self.recherche = None
        self.page = 0
        self._construire_composants()
        await interaction.response.edit_message(view=self)


class ModalRechercheGemmeMega(discord.ui.Modal, title="Rechercher une Gemme Méga"):
    recherche_input = discord.ui.TextInput(label="Nom de la pierre ou de l'espèce", placeholder="Ex : Lucario", required=False)

    def __init__(self, vue_parente: VueCategorieGemmesMega):
        super().__init__()
        self.vue_parente = vue_parente
        self.recherche_input.default = vue_parente.recherche or ""

    async def on_submit(self, interaction: discord.Interaction):
        self.vue_parente.recherche = self.recherche_input.value.strip() or None
        self.vue_parente.page = 0
        self.vue_parente._construire_composants()
        await interaction.response.edit_message(view=self.vue_parente)

