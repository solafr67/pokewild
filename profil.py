import discord

import config
import database
import equipe_combat as equipe_combat_module
import inventaire as inventaire_module
import journal
import leveling
import pokedex as pokedex_module
import quetes as quetes_module
import quetes_ui
import races
from pokemon_data import (
    EMOJI_BALLS,
    EMOJI_OBJETS_DIVERS,
    EMOJI_POKEDEX,
    EMOJI_POKEDOLLAR,
    EMOJI_RARETE,
    EMOJI_SOINS,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
    cle_tri_alphabetique_fr,
)


def construire_embed_profil(user: discord.abc.User) -> discord.Embed:
    """Construit la carte de profil complète d'un joueur (réutilisée par /profil et le bouton du channel)."""
    especes, total = database.obtenir_stats_joueur(user.id)
    poke_dollars = database.obtenir_poke_dollars(user.id)
    inventaire = database.obtenir_inventaire_balls(user.id)

    limite_pokemon = database.limite_stockage_pokemon(user.id)
    limite_objets = database.limite_stockage_objets(user.id)
    total_objets = database.compter_objets_totaux(user.id)

    equipe_actuelle, peut_changer, secondes_restantes = database.obtenir_statut_equipe(user.id)
    if equipe_actuelle is None:
        clan_txt = "*Aucun*"
    else:
        emoji_clan = config.EMOJI_EQUIPES.get(equipe_actuelle, "")
        if peut_changer:
            clan_txt = f"{emoji_clan} {equipe_actuelle}"
        else:
            import time
            date_deblocage = int(time.time()) + secondes_restantes
            clan_txt = f"{emoji_clan} {equipe_actuelle}\n🔒 <t:{date_deblocage}:R>"

    xp_totale = database.obtenir_xp(user.id)
    niveau, xp_dans_niveau, xp_requise = leveling.progression_niveau(xp_totale)
    barre_xp = leveling.barre_progression(xp_dans_niveau, xp_requise)

    race_nom, _ = database.obtenir_race(user.id)
    race = races.obtenir_race_par_nom(race_nom) if race_nom else None
    if race:
        race_txt = f"{EMOJI_RARETE[race['palier']]} {race['nom']}\n{races.texte_bonus(race['bonus'])}"
    else:
        race_txt = "*Aucune*"

    titre_categorie = database.obtenir_titre_actif(user.id)
    titre_txt = None
    if titre_categorie:
        valeurs = quetes_ui.valeurs_accomplissements(user.id)
        palier = quetes_module.palier_atteint(titre_categorie, valeurs[titre_categorie])
        titre_txt = quetes_module.titre_complet(titre_categorie, palier)

    # --- En-tête : juste le titre cosmétique + le niveau, sans surcharge ---
    embed = discord.Embed(
        title=f"🎽 {user.display_name}",
        description=(f"🏅 *{titre_txt}*\n" if titre_txt else "") + f"**Niveau {niveau}**",
        color=discord.Color.blue(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(name="✨ Progression", value=f"{barre_xp}\n`{xp_dans_niveau}/{xp_requise} XP`", inline=False)

    # --- Rangée 1 : ressources ---
    embed.add_field(name="💰 Poké Dollars", value=str(poke_dollars), inline=True)
    embed.add_field(name="📖 Espèces", value=f"{especes} distinctes", inline=True)
    embed.add_field(name="📦 Stockage", value=f"{total}/{limite_pokemon}", inline=True)

    # --- Rangée 2 : identité du dresseur ---
    embed.add_field(name="🛡️ Clan", value=clan_txt, inline=True)
    embed.add_field(name="🧬 Race", value=race_txt, inline=True)
    embed.add_field(name="🎒 Objets", value=f"{total_objets}/{limite_objets}", inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=False)  # séparateur visuel

    # --- Inventaire, une catégorie par colonne plutôt qu'un bloc de texte dense ---
    balls = {k: v for k, v in inventaire.items() if k in NOM_BALL_AFFICHAGE and v > 0}
    soins = {k: v for k, v in inventaire.items() if k in NOM_SOIN_AFFICHAGE and v > 0}
    divers = {k: v for k, v in inventaire.items() if k in NOM_OBJETS_DIVERS and v > 0}

    def _ligne(dico, noms, emojis):
        return "\n".join(f"{emojis.get(k, '')} {noms.get(k, k)} ×{v}" for k, v in dico.items()) or "—"

    embed.add_field(name="Balls", value=_ligne(balls, NOM_BALL_AFFICHAGE, EMOJI_BALLS), inline=True)
    embed.add_field(name="Soins", value=_ligne(soins, NOM_SOIN_AFFICHAGE, EMOJI_SOINS), inline=True)
    if divers:
        embed.add_field(name="Divers", value=_ligne(divers, NOM_OBJETS_DIVERS, EMOJI_OBJETS_DIVERS), inline=True)

    embed.set_footer(text="💡 /pokedex • /exploration • /ma-race • /equipe-combat")
    return embed


def construire_embed_fixe() -> discord.Embed:
    """Embed du message fixe posté dans le channel #profil."""
    embed = discord.Embed(
        title="📋 Ton profil de Dresseur",
        description="Clique sur le bouton ci-dessous pour voir ta carte de profil complète.",
        color=discord.Color.blue(),
    )
    embed.set_footer(text="Visible seulement par toi une fois affichée.")
    return embed


def _construire_lignes_et_total(resultats: dict, user_id: int):
    """Calcule les lignes d'affichage et le total de récompense à partir d'un dict
    {pokemon_nom: quantite}, sans toucher à la base de données."""
    multiplicateur = database.multiplicateur_boost(user_id, "argent")
    lignes = []
    total_recompense = 0
    for nom, quantite in sorted(resultats.items(), key=lambda kv: cle_tri_alphabetique_fr(kv[0])):
        recompense = round(config.RECOMPENSE_RELACHER * quantite * multiplicateur)
        total_recompense += recompense
        lignes.append(f"• **{nom}** ×{quantite} — +{recompense} {EMOJI_POKEDOLLAR}")

    description = "\n".join(lignes)
    if len(description) > 3800:  # marge de sécurité sous la limite Discord de 4096 caractères
        description = description[:3800] + "\n... (liste tronquée, trop de doublons pour tout afficher)"

    return description, total_recompense


def construire_apercu_relacher(user_id: int):
    """Calcule ce qui SERAIT relâché, sans rien supprimer. Retourne (embed, y_a_quelque_chose)."""
    resultats = database.previsualiser_doublons(user_id)

    if not resultats:
        embed = discord.Embed(
            description="Tu n'as aucun doublon à relâcher pour l'instant !",
            color=discord.Color.greyple(),
        )
        return embed, False

    description, total_recompense = _construire_lignes_et_total(resultats, user_id)
    embed = discord.Embed(
        title="⚠️ Que veux-tu relâcher ?",
        description=description,
        color=discord.Color.orange(),
    )
    texte_footer = f"Total si tout relâché : +{total_recompense} Poké Dollars — action irréversible"
    if sum(resultats.values()) > 25:
        texte_footer += " (sélection manuelle limitée aux 25 premiers, utilise \"Tout relâcher d'un coup\" pour le reste)"
    embed.set_footer(text=texte_footer)
    return embed, True


def effectuer_relacher_tous(user_id: int) -> discord.Embed:
    """Relâche RÉELLEMENT tous les doublons du joueur (garde le meilleur PC de chaque
    espèce), crédite la récompense, et retourne un embed de confirmation prêt à afficher."""
    resultats = database.relacher_tous_doublons(user_id)

    if not resultats:
        return discord.Embed(
            description="Tu n'as aucun doublon à relâcher pour l'instant !",
            color=discord.Color.greyple(),
        )

    description, total_recompense = _construire_lignes_et_total(resultats, user_id)
    database.ajouter_poke_dollars(user_id, total_recompense)

    embed = discord.Embed(
        title="👋 Doublons relâchés !",
        description=description,
        color=discord.Color.green(),
    )
    embed.set_footer(text=f"Total : +{total_recompense} Poké Dollars")
    return embed


class VueConfirmationRelacher(discord.ui.View):
    """Vue éphémère pour relâcher les doublons (action irréversible).
    Propose un relâcher classique en un clic ou une sélection manuelle précise."""

    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.doublons = database.obtenir_doublons_detailles(user_id)
        self.ids_coches = {row["id"] for row in self.doublons[:25]}  # tout coché par défaut
        self._construire_composants()

    def _construire_composants(self):
        self.clear_items()

        options = []
        for row in self.doublons[:25]:
            shiny_txt = " ✨" if row["shiny"] else ""
            options.append(
                discord.SelectOption(
                    label=f"{row['pokemon_nom']} — {row['pc']} PC{shiny_txt}",
                    value=str(row["id"]),
                    default=(row["id"] in self.ids_coches),
                )
            )

        if options:
            select = discord.ui.Select(
                placeholder="Décoche ceux à GARDER (les autres seront relâchés)",
                options=options,
                min_values=0,
                max_values=len(options),
                row=0,
            )
            select.callback = self._on_select
            self.add_item(select)

        bouton_confirmer = discord.ui.Button(
            label=f"Relâcher la sélection ({len(self.ids_coches)})",
            emoji="✅",
            style=discord.ButtonStyle.danger,
            disabled=not self.ids_coches,
            row=1,
        )
        bouton_confirmer.callback = self._on_confirmer_selection
        self.add_item(bouton_confirmer)

        bouton_tout = discord.ui.Button(
            label="Tout relâcher d'un coup", emoji="🗑️", style=discord.ButtonStyle.secondary, row=1
        )
        bouton_tout.callback = self._on_tout_relacher
        self.add_item(bouton_tout)

        bouton_annuler = discord.ui.Button(
            label="Annuler", emoji="❌", style=discord.ButtonStyle.secondary, row=1
        )
        bouton_annuler.callback = self._on_annuler
        self.add_item(bouton_annuler)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta confirmation !", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.ids_coches = {int(v) for v in interaction.data["values"]}
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_confirmer_selection(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        if not self.ids_coches:
            return
        nb_supprimes = database.relacher_captures_par_id(self.user_id, list(self.ids_coches))
        recompense = round(config.RECOMPENSE_RELACHER * nb_supprimes * database.multiplicateur_boost(self.user_id, "argent"))
        database.ajouter_poke_dollars(self.user_id, recompense)
        embed = discord.Embed(
            title="👋 Sélection relâchée !",
            description=f"**{nb_supprimes}** Pokémon relâché(s) — +{recompense} {EMOJI_POKEDOLLAR} Poké Dollars",
            color=discord.Color.green(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def _on_tout_relacher(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        embed = effectuer_relacher_tous(self.user_id)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def _on_annuler(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(description="Annulé, rien n'a été relâché.", color=discord.Color.greyple())
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


class VueSuppressionLibre(discord.ui.View):
    """Vue éphémère pour supprimer n'importe quel Pokémon de sa collection (y compris
    les uniques) afin de libérer de la place. Affiche un avertissement ⚠️ si l'exemplaire
    sélectionné est le dernier de son espèce (l'entrée Pokédex sera perdue).

    Paginée par 25 (limite dure d'un menu déroulant Discord) — la sélection cochée est
    conservée d'une page à l'autre, seul l'AFFICHAGE change en changeant de page."""

    TAILLE_PAGE = 25

    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.ids_coches = set()
        self.page = 0
        self._construire_composants()

    def _construire_composants(self):
        self.clear_items()
        captures = database.obtenir_toutes_captures_detaillees(self.user_id)
        nb_pages = max(1, (len(captures) + self.TAILLE_PAGE - 1) // self.TAILLE_PAGE)
        self.page = max(0, min(self.page, nb_pages - 1))
        captures_page = captures[self.page * self.TAILLE_PAGE : (self.page + 1) * self.TAILLE_PAGE]

        options = []
        for row in captures_page:
            shiny_txt = " ✨" if row["shiny"] else ""
            est_unique = row["total_espece"] == 1
            avert_txt = " ⚠️" if est_unique else ""
            options.append(
                discord.SelectOption(
                    label=f"{row['pokemon_nom']} — {row['pc']} PC{shiny_txt}{avert_txt}",
                    description="⚠️ Dernier exemplaire — entrée Pokédex perdue" if est_unique else None,
                    value=str(row["id"]),
                    default=(row["id"] in self.ids_coches),
                )
            )

        if options:
            select = discord.ui.Select(
                placeholder=(
                    f"Coche les Pokémon à supprimer (⚠️ = dernier exemplaire)"
                    + (f" — page {self.page + 1}/{nb_pages}" if nb_pages > 1 else "")
                ),
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

        bouton_supprimer = discord.ui.Button(
            label=f"Supprimer la sélection ({len(self.ids_coches)})",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            disabled=not self.ids_coches,
            row=2,
        )
        bouton_supprimer.callback = self._on_supprimer
        self.add_item(bouton_supprimer)

        bouton_annuler = discord.ui.Button(
            label="Annuler", emoji="❌", style=discord.ButtonStyle.secondary, row=2
        )
        bouton_annuler.callback = self._on_annuler
        self.add_item(bouton_annuler)

    async def _on_page_precedente(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.page -= 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_page_suivante(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta collection !", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        # Ne remplace que les coches de LA PAGE COURANTE — sinon changer de page effacerait
        # la sélection faite sur les pages précédentes.
        captures = database.obtenir_toutes_captures_detaillees(self.user_id)
        ids_page_courante = {
            row["id"] for row in captures[self.page * self.TAILLE_PAGE : (self.page + 1) * self.TAILLE_PAGE]
        }
        ids_coches_page = {int(v) for v in interaction.data["values"]}
        self.ids_coches = (self.ids_coches - ids_page_courante) | ids_coches_page
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_supprimer(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        if not self.ids_coches:
            return
        captures = database.obtenir_toutes_captures_detaillees(self.user_id)
        perdus_pokedex = list(dict.fromkeys(
            row["pokemon_nom"] for row in captures
            if row["id"] in self.ids_coches and row["total_espece"] == 1
        ))
        nb_supprimes = database.relacher_captures_par_id(self.user_id, list(self.ids_coches))
        recompense = round(config.RECOMPENSE_RELACHER * nb_supprimes * database.multiplicateur_boost(self.user_id, "argent"))
        database.ajouter_poke_dollars(self.user_id, recompense)
        description = f"**{nb_supprimes}** Pokémon supprimé(s) — +{recompense} {EMOJI_POKEDOLLAR} Poké Dollars"
        if perdus_pokedex:
            description += f"\n\n⚠️ Entrée(s) Pokédex perdue(s) : **{', '.join(perdus_pokedex)}**"
        embed = discord.Embed(
            title="🗑️ Pokémon supprimés",
            description=description,
            color=discord.Color.red(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def _on_annuler(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(description="Annulé, rien n'a été supprimé.", color=discord.Color.greyple())
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

class VueChoixClan(discord.ui.View):
    """Vue éphémère pour changer de clan directement depuis le profil — mêmes règles que
    la commande /equipe (1 changement gratuit par semaine)."""

    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.select(
        placeholder="Choisis ton clan...",
        options=[
            discord.SelectOption(label=nom, value=nom, emoji=config.EMOJI_EQUIPES.get(nom))
            for nom in ("Bleu", "Rouge", "Jaune")
        ],
    )
    async def choisir(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton profil !", ephemeral=True)
            return

        nom_equipe = select.values[0]
        equipe_actuelle, peut_changer, secondes_restantes = database.obtenir_statut_equipe(self.user_id)

        if equipe_actuelle == nom_equipe:
            await interaction.response.send_message(
                f"Tu es déjà dans le clan **{nom_equipe}** !", ephemeral=True
            )
            return

        if not peut_changer:
            jours = secondes_restantes // 86400
            heures = (secondes_restantes % 86400) // 3600
            await interaction.response.send_message(
                f"⏳ Tu as déjà changé de clan récemment. Prochain changement gratuit possible "
                f"dans **{jours}j {heures}h**.",
                ephemeral=True,
            )
            return

        ancienne_equipe = equipe_actuelle
        database.changer_equipe(self.user_id, nom_equipe)
        journal.logger(f"🛡️ <@{self.user_id}> a rejoint le clan **{nom_equipe}** (venait de : {ancienne_equipe or 'aucun'}).")

        verbe = "rejoint" if ancienne_equipe is None else "rejoint à nouveau"
        message = (
            f"🎉 Tu as {verbe} le clan {config.EMOJI_EQUIPES[nom_equipe]} **{nom_equipe}** ! "
            f"Prochain changement gratuit possible dans 7 jours."
        )

        if isinstance(interaction.user, discord.Member) and interaction.guild is not None:
            try:
                if ancienne_equipe is not None:
                    ancien_role = discord.utils.get(interaction.guild.roles, name=ancienne_equipe)
                    if ancien_role is not None:
                        await interaction.user.remove_roles(ancien_role, reason="Changement de clan")

                nouveau_role = discord.utils.get(interaction.guild.roles, name=nom_equipe)
                if nouveau_role is None:
                    nouveau_role = await interaction.guild.create_role(
                        name=nom_equipe,
                        color=discord.Color(config.COULEURS_EQUIPES[nom_equipe]),
                        mentionable=True,
                        reason="Création automatique du rôle d'équipe",
                    )
                await interaction.user.add_roles(nouveau_role, reason="Choix de clan")
            except discord.Forbidden:
                message += (
                    "\n⚠️ Je n'ai pas la permission de gérer les rôles — demande à un admin de "
                    "vérifier mes permissions (Gérer les rôles) et l'ordre des rôles sur le serveur."
                )

        await interaction.response.edit_message(content=message, embed=None, view=None)


class VueOuvrirPokedex(discord.ui.View):
    """Vue réutilisable (persistante) avec les actions rapides du profil : pokédex et relâcher.
    Peu importe le profil affiché — chaque joueur qui clique agit sur SA PROPRE collection."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Voir mon Pokédex",
        style=discord.ButtonStyle.secondary,
        emoji=EMOJI_POKEDEX,
        custom_id="profil_ouvrir_pokedex_bouton",  # requis pour la persistance après redémarrage
    )
    async def voir_pokedex(self, interaction: discord.Interaction, button: discord.ui.Button):
        vue = pokedex_module.VuePokedex(interaction.user)
        await interaction.response.send_message(embed=vue.construire_embed(), view=vue, ephemeral=True)

    @discord.ui.button(
        label="Relâcher les doublons",
        style=discord.ButtonStyle.danger,
        emoji="👋",
        custom_id="profil_relacher_bouton",  # requis pour la persistance après redémarrage
    )
    async def relacher(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, y_a_quelque_chose = construire_apercu_relacher(interaction.user.id)
        if not y_a_quelque_chose:
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        vue = VueConfirmationRelacher(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Supprimer des Pokémon",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="profil_suppression_libre_bouton",
    )
    async def supprimer_pokemon(self, interaction: discord.Interaction, button: discord.ui.Button):
        captures = database.obtenir_toutes_captures_detaillees(interaction.user.id)
        if not captures:
            await interaction.response.send_message(
                "Tu n'as aucun Pokémon dans ta collection !", ephemeral=True
            )
            return
        vue = VueSuppressionLibre(interaction.user.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🗑️ Supprimer des Pokémon",
                description=(
                    "Coche les Pokémon à supprimer pour libérer de la place.\n"
                    "**⚠️ marqués** = dernier exemplaire de l'espèce, l'entrée Pokédex sera perdue."
                ),
                color=discord.Color.red(),
            ),
            view=vue,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Équipe de combat",
        style=discord.ButtonStyle.secondary,
        emoji="⚔️",
        custom_id="profil_equipe_combat_bouton",  # requis pour la persistance après redémarrage
    )
    async def equipe_combat(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = equipe_combat_module.construire_embed_equipe(interaction.user)
        vue = equipe_combat_module.VueEquipeCombat(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Inventaire",
        style=discord.ButtonStyle.secondary,
        emoji="🎒",
        custom_id="profil_inventaire_bouton",  # requis pour la persistance après redémarrage
    )
    async def inventaire(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = inventaire_module.construire_embed_inventaire(interaction.user)
        vue = inventaire_module.VueInventaire(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Clan",
        style=discord.ButtonStyle.secondary,
        emoji="🛡️",
        custom_id="profil_clan_bouton",  # requis pour la persistance après redémarrage
    )
    async def clan(self, interaction: discord.Interaction, button: discord.ui.Button):
        vue = VueChoixClan(interaction.user.id)
        await interaction.response.send_message(
            "Choisis ton clan (1 changement gratuit par semaine) :", view=vue, ephemeral=True
        )


class VueProfil(discord.ui.View):
    """Vue persistante attachée au message fixe du channel #profil."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Voir mon profil",
        style=discord.ButtonStyle.primary,
        emoji="📋",
        custom_id="profil_voir_bouton",  # requis pour la persistance après redémarrage
    )
    async def voir_profil(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = construire_embed_profil(interaction.user)
        await interaction.response.send_message(embed=embed, view=VueOuvrirPokedex(), ephemeral=True)
