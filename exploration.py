import random
import time

import discord

import config
import database
import leveling
import quetes_ui
import races
from equipe_combat import _stats_par_espece
from pokemon_data import EMOJI_OBJETS_DIVERS, EMOJI_POKEDOLLAR, NOM_OBJETS_DIVERS, obtenir_pokemon_par_nom

EMOJI_CRISTAL = "🔮"
NOM_CRISTAL = "Cristal de Mutation"


def construire_embed_centre() -> discord.Embed:
    embed = discord.Embed(
        title="🗺️ Centre des Explorations",
        description=(
            "Envoie une équipe de 3 Pokémon explorer pendant 1h, 6h ou 24h. Plus ton "
            "équipe est puissante, meilleure sera la récompense — Poké Dollars, XP, une "
            f"chance d'obtenir un {EMOJI_CRISTAL} **{NOM_CRISTAL}** (pour retenter ta Race), "
            "et une chance de trouver un 🥚 **Œuf** à faire éclore au Laboratoire.\n\n"
            "⚠️ Les Pokémon partis en exploration ne peuvent plus être utilisés en combat "
            "ni en raid tant qu'ils ne sont pas revenus."
        ),
        color=discord.Color.dark_gold(),
    )

    noms_duree = {"1h": "1 heure", "6h": "6 heures", "24h": "24 heures"}
    for duree_label, nom_affiche in noms_duree.items():
        dollars_max = round(config.EXPLORATION_PLAFOND_PC * config.EXPLORATION_FACTEUR_DOLLARS[duree_label])
        xp_max = round(config.EXPLORATION_PLAFOND_PC * config.EXPLORATION_FACTEUR_XP[duree_label])
        cristal = config.EXPLORATION_CHANCE_CRISTAL[duree_label]
        oeuf = config.EXPLORATION_CHANCE_OEUF[duree_label]
        embed.add_field(
            name=f"⏱️ {nom_affiche}",
            value=(
                f"{EMOJI_POKEDOLLAR} 0 à {dollars_max} PD\n"
                f"✨ 0 à {xp_max} XP\n"
                f"{EMOJI_CRISTAL} {cristal['base']*100:g}% à {cristal['max']*100:g}%\n"
                f"🥚 {oeuf['base']*100:g}% à {oeuf['max']*100:g}%"
            ),
            inline=True,
        )
    embed.set_footer(text="Le minimum correspond à une équipe faible, le maximum au plafond de PC (6000 cumulés).")
    return embed


class VueCentreExploration(discord.ui.View):
    """Vue persistante attachée au message fixe du Centre des Explorations."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Gérer mes explorations",
        style=discord.ButtonStyle.primary,
        emoji="🗺️",
        custom_id="exploration_gerer",
    )
    async def gerer(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, vue = construire_tableau_de_bord(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Récupérer mes récompenses",
        style=discord.ButtonStyle.success,
        emoji="🎁",
        custom_id="exploration_recuperer_tout",
    )
    async def recuperer_tout(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = recuperer_toutes_recompenses_pretes(interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)


def construire_tableau_de_bord(user_id: int):
    """Construit l'embed + vue récapitulatif de tous les emplacements d'un joueur
    (occupés ou libres), avec les boutons adaptés à chaque état."""
    nb_slots = database.nb_slots_exploration(user_id)
    explorations = {row["slot"]: row for row in database.obtenir_explorations_actives(user_id)}
    maintenant = int(time.time())

    embed = discord.Embed(title="🗺️ Tes explorations", color=discord.Color.dark_gold())

    for slot in range(1, nb_slots + 1):
        row = explorations.get(slot)
        if row is None:
            embed.add_field(name=f"Emplacement {slot}", value="*Libre*", inline=False)
        else:
            pokemons = [row["pokemon1"], row["pokemon2"], row["pokemon3"]]
            termine = row["date_fin"] <= maintenant
            statut = "✅ Prête à récupérer !" if termine else f"⏳ Retour <t:{row['date_fin']}:R>"
            embed.add_field(
                name=f"Emplacement {slot}",
                value=f"{', '.join(pokemons)}\n{statut}",
                inline=False,
            )

    if nb_slots < 2:
        embed.set_footer(text="Astuce : un 2e emplacement est achetable dans la boutique (catégorie Améliorations).")

    vue = VueTableauDeBord(user_id, nb_slots, explorations, maintenant)
    return embed, vue


class VueTableauDeBord(discord.ui.View):
    def __init__(self, user_id: int, nb_slots: int, explorations: dict, maintenant: int):
        super().__init__(timeout=120)
        self.user_id = user_id

        for slot in range(1, nb_slots + 1):
            row = explorations.get(slot)
            if row is None:
                bouton = discord.ui.Button(
                    label=f"Envoyer une équipe (emplacement {slot})", emoji="🚀", style=discord.ButtonStyle.success
                )
                bouton.callback = self._creer_callback_envoyer(slot)
            elif row["date_fin"] <= maintenant:
                bouton = discord.ui.Button(
                    label=f"Récupérer (emplacement {slot})", emoji="🎁", style=discord.ButtonStyle.primary
                )
                bouton.callback = self._creer_callback_recuperer(slot)
            else:
                bouton = discord.ui.Button(
                    label=f"En cours (emplacement {slot})", emoji="⏳", style=discord.ButtonStyle.secondary, disabled=True
                )
            self.add_item(bouton)

    def _creer_callback_envoyer(self, slot: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Ce n'est pas ton tableau de bord !", ephemeral=True)
                return
            vue = VueChoixEquipeExploration(self.user_id, slot)
            if not vue.especes_disponibles:
                await interaction.response.send_message(
                    "Tu n'as aucun Pokémon disponible (déjà tous en exploration, ou aucune capture) !",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"Choisis {config.EXPLORATION_TAILLE_EQUIPE} Pokémon à envoyer explorer (emplacement {slot}) :",
                view=vue,
                ephemeral=True,
            )
        return callback

    def _creer_callback_recuperer(self, slot: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Ce n'est pas ton tableau de bord !", ephemeral=True)
                return
            embed = recuperer_recompense(self.user_id, slot)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return callback


class VueChoixEquipeExploration(discord.ui.View):
    """Sélection de 3 Pokémon (parmi les espèces disponibles) puis de la durée.

    Paginée par 25 (limite dure d'un menu déroulant Discord) — la sélection est
    conservée d'une page à l'autre, seul l'AFFICHAGE change en changeant de page."""

    TAILLE_PAGE = 25

    def __init__(self, user_id: int, slot: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.slot = slot
        self.selection = []
        self.page = 0

        indisponibles = database.especes_en_exploration(user_id)
        stats = _stats_par_espece(user_id)
        self.especes_disponibles = sorted(
            (nom for nom in stats if nom not in indisponibles),
            key=lambda n: -stats[n]["pc"],
        )
        self._construire_composants(stats)

    def _construire_composants(self, stats: dict):
        self.clear_items()
        nb_pages = max(1, (len(self.especes_disponibles) + self.TAILLE_PAGE - 1) // self.TAILLE_PAGE)
        self.page = max(0, min(self.page, nb_pages - 1))
        especes_page = self.especes_disponibles[self.page * self.TAILLE_PAGE : (self.page + 1) * self.TAILLE_PAGE]

        options = [
            discord.SelectOption(
                label=f"{nom} ({stats[nom]['pc']} PC)",
                value=nom,
                default=(nom in self.selection),
            )
            for nom in especes_page
        ]
        placeholder = f"Choisis {config.EXPLORATION_TAILLE_EQUIPE} Pokémon..."
        if nb_pages > 1:
            placeholder += f" — page {self.page + 1}/{nb_pages}"
        select = discord.ui.Select(
            placeholder=placeholder,
            options=options,
            min_values=0,
            max_values=len(options),
            row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

        if nb_pages > 1:
            bouton_precedent = discord.ui.Button(
                label="◀ Page précédente", style=discord.ButtonStyle.secondary,
                disabled=(self.page == 0), row=1,
            )
            bouton_precedent.callback = self._on_page_precedente
            self.add_item(bouton_precedent)

            bouton_suivant = discord.ui.Button(
                label="Page suivante ▶", style=discord.ButtonStyle.secondary,
                disabled=(self.page >= nb_pages - 1), row=1,
            )
            bouton_suivant.callback = self._on_page_suivante
            self.add_item(bouton_suivant)

        bouton_valider = discord.ui.Button(
            label=f"Confirmer l'équipe ({len(self.selection)}/{config.EXPLORATION_TAILLE_EQUIPE})",
            style=discord.ButtonStyle.success,
            emoji="✅",
            disabled=len(self.selection) != config.EXPLORATION_TAILLE_EQUIPE,
            row=2,
        )
        bouton_valider.callback = self._on_valider
        self.add_item(bouton_valider)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta sélection !", ephemeral=True)
            return
        # Ne remplace que les coches de LA PAGE COURANTE — sinon changer de page effacerait
        # la sélection faite sur les pages précédentes.
        ids_page_courante = set(
            self.especes_disponibles[self.page * self.TAILLE_PAGE : (self.page + 1) * self.TAILLE_PAGE]
        )
        nouvelles_coches = set(interaction.data["values"])
        self.selection = [n for n in self.selection if n not in ids_page_courante] + list(nouvelles_coches)
        self.selection = self.selection[: config.EXPLORATION_TAILLE_EQUIPE]  # garde-fou si >3 au total
        stats = _stats_par_espece(self.user_id)
        self._construire_composants(stats)
        await interaction.response.edit_message(view=self)

    async def _on_page_precedente(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta sélection !", ephemeral=True)
            return
        self.page -= 1
        stats = _stats_par_espece(self.user_id)
        self._construire_composants(stats)
        await interaction.response.edit_message(view=self)

    async def _on_page_suivante(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta sélection !", ephemeral=True)
            return
        self.page += 1
        stats = _stats_par_espece(self.user_id)
        self._construire_composants(stats)
        await interaction.response.edit_message(view=self)

    async def _on_valider(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta sélection !", ephemeral=True)
            return
        if len(self.selection) != config.EXPLORATION_TAILLE_EQUIPE:
            return
        vue = VueChoixDureeExploration(self.user_id, self.slot, self.selection)
        await interaction.response.edit_message(
            content=f"Équipe choisie : **{', '.join(self.selection)}**. Pour combien de temps ?",
            view=vue,
        )


class VueChoixDureeExploration(discord.ui.View):
    def __init__(self, user_id: int, slot: int, pokemons: list):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.slot = slot
        self.pokemons = pokemons

        for duree_label in ("1h", "6h", "24h"):
            bouton = discord.ui.Button(label=duree_label, style=discord.ButtonStyle.primary, emoji="⏱️")
            bouton.callback = self._creer_callback(duree_label)
            self.add_item(bouton)

    def _creer_callback(self, duree_label: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Ce n'est pas ta sélection !", ephemeral=True)
                return

            # Revérifier la disponibilité au moment de la confirmation (évite un doublon
            # si le joueur a ouvert deux menus en parallèle)
            indisponibles = database.especes_en_exploration(self.user_id)
            if any(p in indisponibles for p in self.pokemons):
                await interaction.response.edit_message(
                    content="❌ Un des Pokémon choisis est déjà parti en exploration entre-temps.",
                    view=None,
                )
                return

            duree_secondes = config.EXPLORATION_DUREES[duree_label]
            database.demarrer_exploration(self.user_id, self.slot, self.pokemons, duree_secondes, duree_label)
            date_fin = int(time.time()) + duree_secondes

            await interaction.response.edit_message(
                content=(
                    f"🚀 **{', '.join(self.pokemons)}** partent explorer pour **{duree_label}** !\n"
                    f"Retour <t:{date_fin}:R>."
                ),
                view=None,
            )
        return callback


def _calculer_recompense(pc_total: int, duree_label: str) -> dict:
    pc_plafonne = min(pc_total, config.EXPLORATION_PLAFOND_PC)
    dollars = round(pc_plafonne * config.EXPLORATION_FACTEUR_DOLLARS[duree_label])
    xp = round(pc_plafonne * config.EXPLORATION_FACTEUR_XP[duree_label])
    ratio_puissance = pc_plafonne / config.EXPLORATION_PLAFOND_PC

    conf_cristal = config.EXPLORATION_CHANCE_CRISTAL[duree_label]
    chance_cristal = min(conf_cristal["max"], conf_cristal["base"] + conf_cristal["bonus_max"] * ratio_puissance)

    conf_oeuf = config.EXPLORATION_CHANCE_OEUF[duree_label]
    chance_oeuf = min(conf_oeuf["max"], conf_oeuf["base"] + conf_oeuf["bonus_max"] * ratio_puissance)

    return {"dollars": dollars, "xp": xp, "chance_cristal": chance_cristal, "chance_oeuf": chance_oeuf}


def _tirer_palier_oeuf() -> str:
    """Tire un palier d'œuf selon les mêmes proportions relatives que le PokéStop
    (Légendaire y reste écrasé de rareté)."""
    paliers = list(config.OEUF_POIDS_POKESTOP.keys())
    poids = list(config.OEUF_POIDS_POKESTOP.values())
    return random.choices(paliers, weights=poids)[0]


def recuperer_toutes_recompenses_pretes(user_id: int) -> discord.Embed:
    """Récupère automatiquement TOUTES les explorations terminées d'un joueur en un
    seul clic (tous emplacements confondus), et retourne un résumé cumulé."""
    maintenant = int(time.time())
    explorations = [
        row for row in database.obtenir_explorations_actives(user_id)
        if row["date_fin"] <= maintenant
    ]

    if not explorations:
        return discord.Embed(
            description="Aucune exploration prête à être récupérée pour le moment.",
            color=discord.Color.dark_grey(),
        )

    total_dollars = 0
    total_xp = 0
    total_cristaux = 0
    total_oeufs = []
    lignes_details = []
    toutes_quetes_completees = []

    for row in explorations:
        pokemons = [row["pokemon1"], row["pokemon2"], row["pokemon3"]]
        duree_label = row["duree_label"] or _retrouver_duree_label(row["date_fin"] - row["date_debut"])

        stats = _stats_par_espece(user_id)
        pc_total = sum(stats.get(nom, {}).get("pc", 0) for nom in pokemons)
        recompense = _calculer_recompense(pc_total, duree_label)

        dollars = round(recompense["dollars"] * database.multiplicateur_boost(user_id, "argent"))
        database.ajouter_poke_dollars(user_id, dollars)
        leveling.gagner_xp(user_id, recompense["xp"])
        # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
        # applique son propre multiplicateur en interne, on le reproduit ici pour le texte.
        xp_affichee = round(recompense["xp"] * database.multiplicateur_boost(user_id, "xp"))

        obtenu_cristal = random.random() < recompense["chance_cristal"]
        if obtenu_cristal:
            database.ajouter_balls(user_id, "cristal_mutation", 1)
            total_cristaux += 1

        if random.random() < recompense["chance_oeuf"]:
            palier_oeuf = _tirer_palier_oeuf()
            database.ajouter_balls(user_id, f"oeuf_{palier_oeuf}", 1)
            total_oeufs.append(palier_oeuf)

        database.terminer_exploration(user_id, row["slot"])
        database.incrementer_explorations_terminees(user_id)
        quetes_completees = database.incrementer_progression_quete(user_id, "exploration_collectee")
        toutes_quetes_completees.extend(q for q in quetes_completees if q["id"] not in {t["id"] for t in toutes_quetes_completees})

        total_dollars += dollars
        total_xp += xp_affichee
        cristal_txt = f" + {EMOJI_CRISTAL}" if obtenu_cristal else ""
        lignes_details.append(f"• Emplacement {row['slot']} ({', '.join(pokemons)}){cristal_txt}")

    description = (
        "\n".join(lignes_details)
        + f"\n\n{EMOJI_POKEDOLLAR} **+{total_dollars}** Poké Dollars\n"
        f"✨ **+{total_xp}** XP"
    )
    if total_cristaux:
        description += f"\n{EMOJI_CRISTAL} **+{total_cristaux}** {NOM_CRISTAL}(s) !"
    for palier_oeuf in total_oeufs:
        description += f"\n{EMOJI_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']} **+1** {NOM_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']} !"
    description += quetes_ui.texte_notifications_completion(toutes_quetes_completees)

    return discord.Embed(
        title=f"🎁 {len(explorations)} exploration(s) récupérée(s) !",
        description=description,
        color=discord.Color.gold(),
    )


def recuperer_recompense(user_id: int, slot: int) -> discord.Embed:
    """Calcule et distribue la récompense d'une exploration terminée, libère l'emplacement,
    et retourne l'embed de résultat."""
    explorations = {row["slot"]: row for row in database.obtenir_explorations_actives(user_id)}
    row = explorations.get(slot)
    if row is None:
        return discord.Embed(description="Aucune exploration à récupérer sur cet emplacement.", color=discord.Color.red())

    maintenant = int(time.time())
    if row["date_fin"] > maintenant:
        return discord.Embed(
            description=f"⏳ Cette exploration n'est pas encore terminée — retour <t:{row['date_fin']}:R>.",
            color=discord.Color.orange(),
        )

    pokemons = [row["pokemon1"], row["pokemon2"], row["pokemon3"]]
    duree_label = row["duree_label"] or _retrouver_duree_label(row["date_fin"] - row["date_debut"])

    stats = _stats_par_espece(user_id)
    pc_total = sum(stats.get(nom, {}).get("pc", 0) for nom in pokemons)

    recompense = _calculer_recompense(pc_total, duree_label)

    dollars = round(recompense["dollars"] * database.multiplicateur_boost(user_id, "argent"))
    database.ajouter_poke_dollars(user_id, dollars)
    leveling.gagner_xp(user_id, recompense["xp"])
    # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
    # applique son propre multiplicateur en interne, on le reproduit ici pour le texte.
    xp_affichee = round(recompense["xp"] * database.multiplicateur_boost(user_id, "xp"))

    obtenu_cristal = random.random() < recompense["chance_cristal"]
    if obtenu_cristal:
        database.ajouter_balls(user_id, "cristal_mutation", 1)

    palier_oeuf = None
    if random.random() < recompense["chance_oeuf"]:
        palier_oeuf = _tirer_palier_oeuf()
        database.ajouter_balls(user_id, f"oeuf_{palier_oeuf}", 1)

    database.terminer_exploration(user_id, slot)
    database.incrementer_explorations_terminees(user_id)
    quetes_completees = database.incrementer_progression_quete(user_id, "exploration_collectee")

    description = (
        f"**{', '.join(pokemons)}** reviennent d'exploration !\n\n"
        f"{EMOJI_POKEDOLLAR} +{dollars} Poké Dollars\n"
        f"✨ +{xp_affichee} XP"
    )
    if obtenu_cristal:
        description += f"\n{EMOJI_CRISTAL} +1 **{NOM_CRISTAL}** !"
    if palier_oeuf:
        description += f"\n{EMOJI_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']} +1 **{NOM_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']}** !"
    description += quetes_ui.texte_notifications_completion(quetes_completees)

    return discord.Embed(title="🎁 Retour d'exploration", description=description, color=discord.Color.gold())


def _retrouver_duree_label(duree_secondes: int) -> str:
    """Retrouve le label de durée (1h/6h/24h) le plus proche de la durée effective stockée."""
    ecarts = {label: abs(duree_secondes - s) for label, s in config.EXPLORATION_DUREES.items()}
    return min(ecarts, key=ecarts.get)
