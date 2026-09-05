"""
Events serveur (/event) : boost global (shiny/argent/xp), défi collectif du serveur
(capture/combat dresseur/tour de pokéstop), chasse aux shiny chronométrée.

Toute la persistance vit dans database.py (evenement_boost_global, defi_collectif_serveur,
defi_collectif_participants, chasse_shiny_evenement) — ce module ne fait que l'UI Discord
(menus déroulants + formulaires) et la construction des embeds "en cours"/"terminé". La
détection de fin d'event se fait dans une boucle périodique côté main.py
(boucle_verification_evenements), qui ÉDITE le même message plutôt que d'en poster un
nouveau — le message_id est sauvegardé dès l'envoi (voir database.definir_message_*).
"""

import time

import discord

import config
import database
from pokemon_data import EMOJI_BALLS, EMOJI_OBJETS_DIVERS, EMOJI_POKEDOLLAR, EMOJI_SOINS, NOM_BALL_AFFICHAGE, NOM_OBJETS_DIVERS, NOM_SOIN_AFFICHAGE

# Catalogue volontairement restreint pour la récompense bonus d'un défi collectif — balls,
# potions et objets divers (Cristal de Mutation, Œufs...), pas d'objets tenus/gemmes méga
# (plus adaptés à un don ciblé via /give-objet qu'à une récompense d'event communautaire).
_CATALOGUE_RECOMPENSE_EVENT = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
_EMOJIS_RECOMPENSE_EVENT = {**EMOJI_BALLS, **EMOJI_SOINS, **EMOJI_OBJETS_DIVERS}


def _duree_invalide(texte: str) -> int | None:
    """Parse une durée en minutes depuis un TextInput. Retourne None si invalide ou <= 0."""
    try:
        minutes = int(texte.strip())
    except ValueError:
        return None
    return minutes if minutes > 0 else None


def _contenu_ping_event() -> str:
    return f"<@&{config.ROLE_PING_EVENT_ID}>"


ALLOWED_MENTIONS_ROLE_EVENT = discord.AllowedMentions(roles=True, everyone=False, users=False)


# --- Étape 1 : menu principal ----------------------------------------------------------

class VueChoixEvent(discord.ui.View):
    """Vue éphémère (pas persistante — outil admin ponctuel, pas un dashboard fixe)."""

    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.select(
        placeholder="Choisis le type d'event à lancer...",
        options=[
            discord.SelectOption(label="Boost Shiny", value="boost_shiny", emoji="✨", description="Augmente fortement le taux de shiny pour tout le serveur"),
            discord.SelectOption(label="Boost Argent", value="boost_argent", emoji="💰", description="Augmente les Poké Dollars gagnés pour tout le serveur"),
            discord.SelectOption(label="Boost XP", value="boost_xp", emoji="📈", description="Augmente l'XP gagnée (dresseur et Pokémon) pour tout le serveur"),
            discord.SelectOption(label="Défi collectif du serveur", value="defi_collectif", emoji="🎯", description="Objectif commun à tous les joueurs, récompense à l'atteinte"),
            discord.SelectOption(label="Chasse aux Shiny", value="chasse_shiny", emoji="🌟", description="Fenêtre chronométrée, boost de shiny + classement des trouvailles"),
            discord.SelectOption(label="Capture Classée", value="capture_rarete", emoji="🏆", description="Chaque capture (spawn classique) rapporte des points selon la rareté"),
        ],
    )
    async def choisir(self, interaction: discord.Interaction, select: discord.ui.Select):
        valeur = select.values[0]
        if valeur in ("boost_shiny", "boost_argent", "boost_xp"):
            type_boost = valeur.removeprefix("boost_")
            await interaction.response.send_modal(ModalDureeBoost(type_boost))
        elif valeur == "defi_collectif":
            await interaction.response.edit_message(
                content="🎯 Quel type de défi collectif ?", view=VueChoixTypeDefi()
            )
        elif valeur == "chasse_shiny":
            await interaction.response.send_modal(ModalDureeChasseShiny())
        elif valeur == "capture_rarete":
            await interaction.response.send_modal(ModalDureeCaptureRarete())


# --- Boost global : durée --------------------------------------------------------------

class ModalDureeBoost(discord.ui.Modal):
    def __init__(self, type_boost: str):
        super().__init__(title=f"Boost {config.NOMS_BOOST_EVENT[type_boost]}")
        self.type_boost = type_boost
        self.duree_input = discord.ui.TextInput(
            label="Durée de l'event (en minutes)",
            placeholder="Ex: 60",
            required=True,
            max_length=6,
        )
        self.add_item(self.duree_input)

    async def on_submit(self, interaction: discord.Interaction):
        minutes = _duree_invalide(self.duree_input.value)
        if minutes is None:
            await interaction.response.send_message("❌ Durée invalide — donne un nombre entier de minutes supérieur à 0.", ephemeral=True)
            return

        multiplicateur = config.MULTIPLICATEURS_EVENT_BOOST[self.type_boost]
        channel = interaction.guild.get_channel(config.CHANNEL_EVENT_ID) if interaction.guild else None
        database.activer_boost_global(self.type_boost, multiplicateur, minutes * 60, channel.id if channel else None)

        await interaction.response.send_message(
            f"✅ Boost **{config.NOMS_BOOST_EVENT[self.type_boost]}** (x{multiplicateur:g}) lancé pour **{minutes} minute(s)** !",
            ephemeral=True,
        )
        if channel:
            message = await channel.send(
                content=_contenu_ping_event(),
                embed=construire_embed_boost_en_cours(self.type_boost, multiplicateur, minutes),
                allowed_mentions=ALLOWED_MENTIONS_ROLE_EVENT,
            )
            database.definir_message_boost_global(self.type_boost, message.id)


def construire_embed_boost_en_cours(type_boost: str, multiplicateur: float, minutes: int) -> discord.Embed:
    emoji = config.EMOJI_BOOST_EVENT[type_boost]
    nom = config.NOMS_BOOST_EVENT[type_boost]
    embed = discord.Embed(
        title=f"{emoji} Event en cours : Boost {nom} !",
        description=(
            f"**x{multiplicateur:g}** sur {nom.lower()} pour **tout le serveur**, "
            f"pendant **{minutes} minute(s)** !\n\nProfitez-en pendant que ça dure 🔥"
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="🟢 Event en cours")
    return embed


def construire_embed_boost_termine(type_boost: str) -> discord.Embed:
    emoji = config.EMOJI_BOOST_EVENT[type_boost]
    nom = config.NOMS_BOOST_EVENT[type_boost]
    embed = discord.Embed(
        title=f"{emoji} Event terminé : Boost {nom}",
        description="Le boost est terminé, les taux reviennent à la normale. Merci d'avoir participé !",
        color=discord.Color.dark_gold(),
    )
    embed.set_footer(text="🔴 Event terminé")
    return embed


# --- Défi collectif : type puis quantité cible ------------------------------------------

class VueChoixTypeDefi(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.select(
        placeholder="Choisis le type de défi...",
        options=[
            discord.SelectOption(label=nom, value=cle)
            for cle, nom in config.TYPES_DEFI_COLLECTIF.items()
        ],
    )
    async def choisir(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_modal(ModalCibleDefi(select.values[0]))


class ModalCibleDefi(discord.ui.Modal):
    def __init__(self, type_evenement: str):
        super().__init__(title=f"Défi : {config.TYPES_DEFI_COLLECTIF[type_evenement]}")
        self.type_evenement = type_evenement
        self.cible_input = discord.ui.TextInput(
            label="Quantité cible (cumulée, tous joueurs)",
            placeholder="Ex: 5000",
            required=True,
            max_length=8,
        )
        self.duree_input = discord.ui.TextInput(
            label="Durée limite (en minutes)",
            placeholder="Ex: 120 — si non atteint à temps, personne ne reçoit rien",
            required=True,
            max_length=6,
        )
        self.recompense_pd_input = discord.ui.TextInput(
            label="Récompense en Poké Dollars (par participant)",
            placeholder="Ex: 300",
            required=True,
            max_length=8,
        )
        self.objet_input = discord.ui.TextInput(
            label="Objet bonus (optionnel) — clé exacte",
            placeholder="Ex: cristal_mutation, superball, oeuf_rare... (laisser vide si aucun)",
            required=False,
            max_length=40,
        )
        self.quantite_objet_input = discord.ui.TextInput(
            label="Quantité de l'objet bonus",
            placeholder="Ignoré si aucun objet bonus renseigné",
            required=False,
            max_length=4,
        )
        self.add_item(self.cible_input)
        self.add_item(self.duree_input)
        self.add_item(self.recompense_pd_input)
        self.add_item(self.objet_input)
        self.add_item(self.quantite_objet_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cible = int(self.cible_input.value.strip())
        except ValueError:
            cible = -1
        if cible <= 0:
            await interaction.response.send_message("❌ Cible invalide — donne un nombre entier supérieur à 0.", ephemeral=True)
            return

        minutes = _duree_invalide(self.duree_input.value)
        if minutes is None:
            await interaction.response.send_message("❌ Durée invalide — donne un nombre entier de minutes supérieur à 0.", ephemeral=True)
            return

        try:
            recompense_pd = int(self.recompense_pd_input.value.strip())
        except ValueError:
            recompense_pd = -1
        if recompense_pd <= 0:
            await interaction.response.send_message("❌ Récompense invalide — donne un nombre entier de Poké Dollars supérieur à 0.", ephemeral=True)
            return

        objet_cle = self.objet_input.value.strip() or None
        quantite_objet = 0
        if objet_cle:
            if objet_cle not in _CATALOGUE_RECOMPENSE_EVENT:
                await interaction.response.send_message(
                    f"❌ Objet inconnu : `{objet_cle}`. Clés valides : balls, potions, objets divers "
                    f"(ex: pokeball, superpotion, cristal_mutation, oeuf_rare...).",
                    ephemeral=True,
                )
                return
            try:
                quantite_objet = int(self.quantite_objet_input.value.strip())
            except ValueError:
                quantite_objet = -1
            if quantite_objet <= 0:
                await interaction.response.send_message(
                    "❌ Quantité d'objet bonus invalide — donne un nombre entier supérieur à 0 (ou laisse "
                    "les 2 champs objet/quantité vides pour n'avoir aucun objet bonus).",
                    ephemeral=True,
                )
                return

        channel = interaction.guild.get_channel(config.CHANNEL_EVENT_ID) if interaction.guild else None
        defi_id = database.demarrer_defi_collectif(
            self.type_evenement, cible, channel.id if channel else None,
            duree_secondes=minutes * 60, recompense_pd=recompense_pd,
            recompense_objet=objet_cle, recompense_quantite_objet=quantite_objet,
        )

        nom = config.TYPES_DEFI_COLLECTIF[self.type_evenement]
        await interaction.response.send_message(
            f"✅ Défi collectif lancé : **{nom}** — objectif **{cible}** en **{minutes} minute(s)** !",
            ephemeral=True,
        )
        if channel:
            date_fin = int(time.time()) + minutes * 60
            message = await channel.send(
                content=_contenu_ping_event(),
                embed=construire_embed_defi_en_cours(
                    nom, cible, 0, date_fin, recompense_pd, objet_cle, quantite_objet
                ),
                allowed_mentions=ALLOWED_MENTIONS_ROLE_EVENT,
            )
            database.definir_message_defi_collectif(defi_id, message.id)


def construire_embed_defi_en_cours(
    nom: str, cible: int, progres: int, date_fin: int,
    recompense_pd: int, recompense_objet: str | None, recompense_quantite_objet: int,
) -> discord.Embed:
    """Barre de progression + temps restant + détail de la récompense — voir
    main.py::boucle_verification_evenements pour le rafraîchissement périodique de cet
    embed (le progrès et le temps restant changent, donc le message est réédité)."""
    barre_len = 20
    remplie = round((progres / cible) * barre_len) if cible > 0 else 0
    barre = "🟩" * remplie + "⬜" * (barre_len - remplie)

    secondes_restantes = max(0, date_fin - int(time.time()))
    minutes_restantes = secondes_restantes // 60
    if minutes_restantes >= 60:
        temps_texte = f"{minutes_restantes // 60}h{minutes_restantes % 60:02d}"
    else:
        temps_texte = f"{minutes_restantes} min"

    lignes_recompense = [f"{EMOJI_POKEDOLLAR} {recompense_pd} Poké Dollars"]
    if recompense_objet and recompense_quantite_objet:
        emoji_objet = _EMOJIS_RECOMPENSE_EVENT.get(recompense_objet, "")
        nom_objet = _CATALOGUE_RECOMPENSE_EVENT.get(recompense_objet, recompense_objet)
        lignes_recompense.append(f"{emoji_objet} {recompense_quantite_objet}× {nom_objet}")

    embed = discord.Embed(
        title="🎯 Event en cours : Défi collectif !",
        description=(
            f"Objectif du serveur : **{cible} {nom.lower()}**, tous joueurs confondus !\n\n"
            f"{barre}\n**{progres}/{cible}**\n\n"
            f"⏳ Temps restant : **{temps_texte}**\n"
            f"⚠️ Si l'objectif n'est pas atteint à temps, personne ne reçoit rien !\n\n"
            f"Chaque contribution compte — dès que l'objectif est atteint, **tous ceux qui "
            f"y ont participé** (au moins 1 fois pendant l'event) reçoivent :\n" + "\n".join(lignes_recompense)
        ),
        color=discord.Color.blue(),
    )
    embed.set_footer(text="🟢 Event en cours")
    return embed


def construire_embed_defi_echoue(nom: str, cible: int, progres: int) -> discord.Embed:
    """Le temps est écoulé sans que la cible ait été atteinte — personne ne reçoit rien
    (durée = vraie limite dure, voir ModalCibleDefi)."""
    embed = discord.Embed(
        title="⏱️ Event terminé : Défi collectif — Temps écoulé",
        description=(
            f"L'objectif **{cible} {nom.lower()}** n'a pas été atteint à temps "
            f"(**{progres}/{cible}** au moment où le temps s'est écoulé).\n\n"
            f"Aucune récompense n'est distribuée cette fois-ci — merci d'avoir participé, "
            f"et à la prochaine tentative !"
        ),
        color=discord.Color.dark_grey(),
    )
    embed.set_footer(text="🔴 Event terminé — échoué")
    return embed


def construire_embed_defi_termine(
    nom: str, cible: int, nb_participants: int,
    recompense_pd: int, recompense_objet: str | None, recompense_quantite_objet: int,
) -> discord.Embed:
    texte_recompense = f"**{recompense_pd} Poké Dollars**"
    if recompense_objet and recompense_quantite_objet:
        emoji_objet = _EMOJIS_RECOMPENSE_EVENT.get(recompense_objet, "")
        nom_objet = _CATALOGUE_RECOMPENSE_EVENT.get(recompense_objet, recompense_objet)
        texte_recompense += f" + **{recompense_quantite_objet}× {emoji_objet} {nom_objet}**"
    embed = discord.Embed(
        title="🎉 Défi collectif terminé — Réussi !",
        description=(
            f"L'objectif **{cible} {nom.lower()}** a été atteint grâce à **{nb_participants}** "
            f"participant(s) ! Chacun reçoit {texte_recompense} en récompense. 🎉"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text="🔴 Event terminé")
    return embed


# --- Chasse aux shiny : durée ------------------------------------------------------------

class ModalDureeChasseShiny(discord.ui.Modal, title="Chasse aux Shiny"):
    duree_input = discord.ui.TextInput(
        label="Durée de la chasse (en minutes)",
        placeholder="Ex: 120",
        required=True,
        max_length=6,
    )

    async def on_submit(self, interaction: discord.Interaction):
        minutes = _duree_invalide(self.duree_input.value)
        if minutes is None:
            await interaction.response.send_message("❌ Durée invalide — donne un nombre entier de minutes supérieur à 0.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(config.CHANNEL_EVENT_ID) if interaction.guild else None
        channel_id = channel.id if channel else None
        chasse_id = database.demarrer_chasse_shiny(minutes * 60, channel_id)
        # Combine avec un boost de shiny pour la même durée — sans ça, "chasse aux shiny"
        # ne serait qu'un classement sans rien qui la rende vraiment spéciale.
        multiplicateur = config.MULTIPLICATEURS_EVENT_BOOST["shiny"]
        database.activer_boost_global("shiny", multiplicateur, minutes * 60, channel_id)

        await interaction.response.send_message(
            f"✅ Chasse aux Shiny lancée pour **{minutes} minute(s)** (avec boost x{multiplicateur:g}) !",
            ephemeral=True,
        )
        if channel:
            message = await channel.send(
                content=_contenu_ping_event(),
                embed=construire_embed_chasse_shiny_en_cours(minutes, multiplicateur),
                allowed_mentions=ALLOWED_MENTIONS_ROLE_EVENT,
            )
            database.definir_message_chasse_shiny(chasse_id, message.id)
            # Le boost partage la même durée : pas besoin d'un 2e message qui ping — son
            # propre message "en cours" serait redondant avec celui de la chasse.


def construire_embed_chasse_shiny_en_cours(minutes: int, multiplicateur: float) -> discord.Embed:
    embed = discord.Embed(
        title="🌟 Event en cours : Chasse aux Shiny !",
        description=(
            f"Pendant **{minutes} minute(s)**, le taux de shiny est boosté (**x{multiplicateur:g}**) "
            f"pour tout le serveur !\n\nÀ la fin de la fenêtre, le classement de qui en a trouvé "
            f"le plus sera annoncé ici. Bonne chasse ! 🎯"
        ),
        color=discord.Color.purple(),
    )
    embed.set_footer(text="🟢 Event en cours")
    return embed


def construire_embed_chasse_shiny_terminee(classement: list) -> discord.Embed:
    if not classement:
        embed = discord.Embed(
            title="🌟 Chasse aux Shiny terminée",
            description="Personne n'a trouvé de shiny pendant cette fenêtre... la prochaine sera la bonne !",
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text="🔴 Event terminé")
        return embed
    medailles = ["🥇", "🥈", "🥉"]
    lignes = []
    for i, (user_id, nb) in enumerate(classement[:10]):
        prefixe = medailles[i] if i < 3 else f"**{i + 1}.**"
        lignes.append(f"{prefixe} <@{user_id}> — **{nb}** shiny")
    embed = discord.Embed(
        title="🌟 Chasse aux Shiny terminée — Classement !",
        description="\n".join(lignes),
        color=discord.Color.purple(),
    )
    embed.set_footer(text="🔴 Event terminé")
    return embed


# --- Capture Classée : durée, classement live (mis à jour toutes les 30 min), fin -------

BAREME_CAPTURE_RARETE_TEXTE = (
    "Pokémon Commun → **+1** point\n"
    "Pokémon Peu Commun → **+3** points\n"
    "Pokémon Rare → **+6** points\n"
    "Pokémon Hyper Rare → **+10** points\n"
    "Pokémon Légendaire → **+15** points\n"
    "Pokémon Shiny → **+25** points (en plus des points de rareté)\n\n"
    "**Chaque capture compte** — un doublon rapporte autant de points qu'une nouvelle "
    "capture. Seules les captures du **spawn classique** sont comptabilisées (le spawn "
    "VIP ne rapporte aucun point, pour rester équitable)."
)


class ModalDureeCaptureRarete(discord.ui.Modal, title="Capture Classée"):
    duree_input = discord.ui.TextInput(
        label="Durée de l'event (en minutes)",
        placeholder="Ex: 1440",
        required=True,
        max_length=6,
    )

    async def on_submit(self, interaction: discord.Interaction):
        minutes = _duree_invalide(self.duree_input.value)
        if minutes is None:
            await interaction.response.send_message("❌ Durée invalide — donne un nombre entier de minutes supérieur à 0.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(config.CHANNEL_EVENT_ID) if interaction.guild else None
        channel_id = channel.id if channel else None
        event_id = database.demarrer_event_capture_rarete(minutes * 60, channel_id)

        await interaction.response.send_message(
            f"✅ Capture Classée lancée pour **{minutes} minute(s)** !",
            ephemeral=True,
        )
        if channel:
            message = await channel.send(
                content=_contenu_ping_event(),
                embed=construire_embed_capture_rarete_classement(minutes, []),
                allowed_mentions=ALLOWED_MENTIONS_ROLE_EVENT,
            )
            database.definir_message_event_capture_rarete(event_id, message.id)


def construire_embed_capture_rarete_classement(minutes_totales: int, classement: list) -> discord.Embed:
    """Un SEUL embed réutilisé à la fois pour l'annonce initiale (classement vide) et
    chaque mise à jour périodique (toutes les 30 min, voir main.py) — juste le classement
    live qui se remplit avec le temps, le barème reste affiché en permanence."""
    medailles = ["🥇", "🥈", "🥉"]
    if classement:
        lignes_classement = [
            f"{medailles[i] if i < 3 else f'**{i + 1}.**'} <@{user_id}> — **{points}** point(s)"
            for i, (user_id, points) in enumerate(classement[:10])
        ]
        texte_classement = "\n".join(lignes_classement)
    else:
        texte_classement = "*Aucune capture pour l'instant — sois le premier !*"

    embed = discord.Embed(
        title="🏆 Event en cours : Capture Classée !",
        description=(
            f"Pendant **{minutes_totales} minute(s)**, chaque capture (spawn classique "
            f"uniquement) rapporte des points selon sa rareté !\n\n{BAREME_CAPTURE_RARETE_TEXTE}\n\n"
            f"**Classement actuel :**\n{texte_classement}"
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="🟢 Event en cours — classement mis à jour toutes les 30 minutes")
    return embed


def construire_embed_capture_rarete_terminee(classement: list) -> discord.Embed:
    if not classement:
        embed = discord.Embed(
            title="🏆 Capture Classée terminée",
            description="Personne n'a marqué de points pendant cet event... la prochaine sera la bonne !",
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="🔴 Event terminé")
        return embed
    medailles = ["🥇", "🥈", "🥉"]
    lignes = [
        f"{medailles[i] if i < 3 else f'**{i + 1}.**'} <@{user_id}> — **{points}** point(s)"
        for i, (user_id, points) in enumerate(classement[:10])
    ]
    embed = discord.Embed(
        title="🏆 Capture Classée terminée — Podium !",
        description="\n".join(lignes),
        color=discord.Color.gold(),
    )
    if len(classement) >= 3:
        embed.add_field(
            name="🎉 Félicitations au podium !",
            value=f"<@{classement[0][0]}>, <@{classement[1][0]}> et <@{classement[2][0]}> repartent avec les récompenses mises en jeu !",
            inline=False,
        )
    embed.set_footer(text="🔴 Event terminé")
    return embed
