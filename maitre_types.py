import discord

import capacites as capacites_module
import formes_objets as formes_objets_module
import database
from pokemon_data import (
    ATTAQUES,
    EMOJI_POKEDOLLAR,
    EMOJI_TYPES,
    affichage_types,
    attaque_necessite_ct,
    attaques_apprenables,
    attaques_verrouillees_par_niveau,
    emoji_pour_objet,
    obtenir_attaque,
    obtenir_pokemon_par_nom,
    prix_ct,
    sprite_pokemon,
    toutes_attaques_utilisables,
)

ATTAQUES_PAR_PAGE = 25  # limite Discord d'options par menu déroulant

CATEGORIES_CT = {
    "tous": "Toutes catégories",
    "physical": "Physique",
    "special": "Spécial",
    "status": "Statut",
}


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
            "*« Approche, dresseur ! Tes Pokémon apprennent gratuitement les attaques "
            "que leur niveau leur permet déjà. Pour le reste, il te faut une CT — achète-la "
            "une fois à ma boutique, elle est à toi pour toujours, utilisable sur "
            "n'importe lequel de tes Pokémon, autant de fois que tu veux. Choisis bien : "
            "chaque Pokémon ne peut retenir que 4 attaques à la fois. »*\n\n"
            "Clique sur **Gérer les attaques** pour ton équipe de combat, **Boutique CT** "
            "pour acheter de nouvelles attaques, ou **Objets tenus** pour équiper un objet "
            "de combat (achetable en boutique, onglet 🎒 Objets)."
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

    @discord.ui.button(
        label="Boutique CT",
        style=discord.ButtonStyle.secondary,
        emoji="🏪",
        custom_id="maitre_types_boutique_ct",
    )
    async def boutique(self, interaction: discord.Interaction, button: discord.ui.Button):
        vue = VueBoutiqueCT(interaction.user.id)
        await interaction.response.send_message(embed=vue.construire_embed(), view=vue, ephemeral=True)

    @discord.ui.button(
        label="Objets tenus",
        style=discord.ButtonStyle.secondary,
        emoji="🎒",
        custom_id="maitre_types_objets_tenus",
    )
    async def objets_tenus(self, interaction: discord.Interaction, button: discord.ui.Button):
        noms_equipe = database.obtenir_equipe_combat(interaction.user.id)
        if not noms_equipe:
            await interaction.response.send_message(
                "*« Reviens me voir quand tu auras configuré ton équipe de combat "
                "(`/equipe-combat`) ! »*",
                ephemeral=True,
            )
            return
        vue = VueChoixPokemonObjet(interaction.user.id)
        await interaction.response.send_message(
            "*« Quel Pokémon veux-tu équiper ? »*", view=vue, ephemeral=True
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


class VueChoixPokemonObjet(discord.ui.View):
    """Étape 1 (objets tenus) : choisir le Pokémon de son équipe de combat à équiper."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        noms_equipe = database.obtenir_equipe_combat(user_id)
        options = []
        for nom in noms_equipe[:25]:
            objet_actuel = database.obtenir_objet_tenu_reel(user_id, nom)
            info_objet = capacites_module.infos_objet(objet_actuel) if objet_actuel else None
            info_forme = formes_objets_module.FORMES_OBJETS.get(objet_actuel) if objet_actuel else None
            if info_objet:
                description = f"Tient : {info_objet['nom']}"
            elif info_forme:
                description = f"Tient : {info_forme['objet_nom']}"
            else:
                description = "Ne tient rien"
            options.append(discord.SelectOption(label=nom, value=nom, description=description))
        select = discord.ui.Select(placeholder="Choisis un Pokémon de ton équipe...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta session !", ephemeral=True)
            return
        nom = interaction.data["values"][0]
        vue = VueGestionObjet(self.user_id, nom)
        await interaction.response.edit_message(content=None, embed=vue.construire_embed(), view=vue)


class VueGestionObjet(discord.ui.View):
    """Étape 2 (objets tenus) : équiper/retirer l'objet tenu d'un Pokémon précis, parmi
    ceux réellement possédés dans le sac (voir boutique — onglet 🎒 Objets)."""

    def __init__(self, user_id: int, pokemon_nom: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.pokemon_nom = pokemon_nom
        self._construire_composants()

    def construire_embed(self) -> discord.Embed:
        objet_actuel = database.obtenir_objet_tenu_reel(self.user_id, self.pokemon_nom)
        info_objet = capacites_module.infos_objet(objet_actuel) if objet_actuel else None
        info_forme = formes_objets_module.FORMES_OBJETS.get(objet_actuel) if objet_actuel else None
        if info_objet:
            texte_tenu = f"Tient actuellement : {info_objet['emoji']} **{info_objet['nom']}** — {info_objet['description']}"
        elif info_forme:
            texte_tenu = (
                f"Tient actuellement : {info_forme['objet_emoji']} **{info_forme['objet_nom']}** — "
                f"*{info_forme['forme_nom']}* active tant qu'il le tient !"
            )
        else:
            texte_tenu = "Ne tient actuellement aucun objet."
        embed = discord.Embed(
            title=f"🎒 Objet tenu — {self.pokemon_nom}",
            description=texte_tenu,
            color=discord.Color.purple(),
        )
        image_objet = (info_objet or {}).get("image") or (info_forme or {}).get("objet_image")
        if image_objet:
            embed.set_thumbnail(url=image_objet)
        embed.set_footer(text="Choisis un objet de ton sac ci-dessous, ou clique Retirer.")
        return embed

    def _construire_composants(self):
        self.clear_items()
        inventaire = database.obtenir_inventaire_balls(self.user_id)
        # Deux familles d'objets équipables : les objets de combat classiques
        # (capacites.OBJETS_TENUS) et les objets de transformation (Fleur Gracidea...,
        # voir formes_objets.py) — les seconds n'étaient pas proposés ici avant, alors
        # qu'ils sont bien équipables comme n'importe quel autre objet tenu.
        toutes_les_infos = {
            **capacites_module.OBJETS_TENUS,
            **{cle: {"nom": info["objet_nom"], "emoji": info["objet_emoji"],
                     "description": f"Transforme {info['espece']} en {info['forme_nom']} tant qu'il le tient."}
               for cle, info in formes_objets_module.FORMES_OBJETS.items()},
        }
        options = []
        for cle, info in toutes_les_infos.items():
            quantite = inventaire.get(cle, 0)
            if quantite <= 0:
                continue  # pas dans le sac, inutile de le proposer ici (voir la boutique pour en acheter)
            options.append(
                discord.SelectOption(
                    label=f"{info['nom']} (×{quantite})"[:100],
                    value=cle,
                    description=info["description"][:100],
                    emoji=emoji_pour_objet(cle, info["emoji"]),
                )
            )
        if options:
            select = discord.ui.Select(placeholder="Choisis un objet de ton sac…", options=options)
            select.callback = self._on_select
            self.add_item(select)
        else:
            bouton_vide = discord.ui.Button(label="Ton sac ne contient aucun objet tenu — va en boutique", style=discord.ButtonStyle.secondary, disabled=True)
            self.add_item(bouton_vide)

        bouton_retirer = discord.ui.Button(label="Retirer l'objet actuel", emoji="❌", style=discord.ButtonStyle.danger)
        bouton_retirer.callback = self._on_retirer
        self.add_item(bouton_retirer)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta session !", ephemeral=True)
            return
        nouvel_objet = interaction.data["values"][0]
        ancien_objet = database.obtenir_objet_tenu_reel(self.user_id, self.pokemon_nom)
        if nouvel_objet == ancien_objet:
            await interaction.response.send_message(f"**{self.pokemon_nom}** tient déjà cet objet.", ephemeral=True)
            return

        inventaire = database.obtenir_inventaire_balls(self.user_id)
        if inventaire.get(nouvel_objet, 0) < 1:
            await interaction.response.send_message("Il semble que tu n'aies plus cet objet, réessaie.", ephemeral=True)
            return

        database.retirer_ball(self.user_id, nouvel_objet)
        if ancien_objet:
            database.ajouter_balls(self.user_id, ancien_objet, 1)  # rendu au sac, jamais perdu
        database.definir_objet_tenu_reel(self.user_id, self.pokemon_nom, nouvel_objet)

        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _on_retirer(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta session !", ephemeral=True)
            return
        ancien_objet = database.obtenir_objet_tenu_reel(self.user_id, self.pokemon_nom)
        if ancien_objet is None:
            await interaction.response.send_message(f"**{self.pokemon_nom}** ne tenait déjà aucun objet.", ephemeral=True)
            return
        database.definir_objet_tenu_reel(self.user_id, self.pokemon_nom, None)
        database.ajouter_balls(self.user_id, ancien_objet, 1)  # rendu au sac, jamais perdu

        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)


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
        self.pokemon = pokemon
        self.niveau, _xp = database.obtenir_niveau_pokemon(user_id, pokemon_nom)
        self.possedees = database.obtenir_ct_possedees(user_id)
        # Liste COMPLÈTE (pas filtrée par niveau) : les attaques pas encore débloquées
        # restent visibles — équipables gratuitement si la CT a déjà été achetée en
        # boutique, sinon un rappel invite à aller l'acheter.
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

        verrouillees = attaques_verrouillees_par_niveau(pokemon, self.niveau) if pokemon else []
        if verrouillees:
            apercu = ", ".join(f"{nom} (niv. {palier})" for nom, palier in verrouillees[:3])
            if len(verrouillees) > 3:
                apercu += f", +{len(verrouillees) - 3} autre(s)"
            embed.add_field(
                name="🔒 À venir par niveau (ou dès maintenant avec une CT achetée)",
                value=apercu,
                inline=False,
            )

        solde = database.obtenir_poke_dollars(self.user_id)
        nb_pages = max(1, (len(self.attaques_dispo) + ATTAQUES_PAR_PAGE - 1) // ATTAQUES_PAR_PAGE)
        embed.set_footer(
            text=(
                f"Niv. {self.niveau} — {solde} PD — "
                f"{len(self.attaques_dispo)} attaques — page {self.page + 1}/{nb_pages}"
            )
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
            if attaque_necessite_ct(self.pokemon, nom, self.niveau):
                description = "🎟️ CT possédée" if nom in self.possedees else "🔒 CT non achetée"
            else:
                description = _description_attaque(nom)
            options.append(
                discord.SelectOption(
                    label=_label_attaque(nom)[:100],
                    description=description[:100],
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

        bouton_boutique = discord.ui.Button(label="Boutique CT", emoji="🏪", style=discord.ButtonStyle.secondary, row=3)
        bouton_boutique.callback = self._on_boutique
        self.add_item(bouton_boutique)

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
            await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)
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

        if attaque_necessite_ct(self.pokemon, nom, self.niveau) and nom not in self.possedees:
            await interaction.response.send_message(
                f"*« Tu ne possèdes pas encore la CT de **{nom}**. Va la chercher à la "
                f"Boutique CT ({prix_ct(nom)} {EMOJI_POKEDOLLAR}) ! »*",
                ephemeral=True,
            )
            return

        database.equiper_attaque(self.user_id, self.pokemon_nom, self.slot_selectionne, nom)
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_page_prec(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_page_suiv(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_vider(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        database.retirer_attaque(self.user_id, self.pokemon_nom, self.slot_selectionne)
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_aleatoire(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        # Tire 4 attaques distinctes au hasard parmi celles déjà équipables gratuitement
        # (débloquées par le niveau, ou dont la CT a déjà été achetée) — priorité aux
        # offensives. Jamais une attaque dont la CT n'est pas encore possédée : ça reste
        # une décision d'achat explicite via la Boutique CT.
        import random

        gratuites = [
            n for n in self.attaques_dispo
            if not attaque_necessite_ct(self.pokemon, n, self.niveau) or n in self.possedees
        ]
        offensives = [n for n in gratuites if ATTAQUES[n].get("puissance")]
        statuts = [n for n in gratuites if not ATTAQUES[n].get("puissance")]
        random.shuffle(offensives)
        random.shuffle(statuts)
        tirage = (offensives[:3] + statuts)[:4] if len(offensives) >= 3 else (offensives + statuts)[:4]
        random.shuffle(tirage)  # évite que les offensives soient toujours en tête

        for slot, nom in enumerate(tirage, start=1):
            database.equiper_attaque(self.user_id, self.pokemon_nom, slot, nom)
        for slot in range(len(tirage) + 1, 5):
            database.retirer_attaque(self.user_id, self.pokemon_nom, slot)

        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_retour(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        vue = VueChoixPokemonAttaques(self.user_id)
        await interaction.response.edit_message(
            content="*« Quel Pokémon veux-tu entraîner ? »*", embed=None, view=vue
        )

    async def _on_boutique(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        vue = VueBoutiqueCT(self.user_id)
        await interaction.response.edit_message(content=None, embed=vue.construire_embed(), view=vue)


class VueBoutiqueCT(discord.ui.View):
    """Boutique de CT : indépendante d'un Pokémon précis. Une CT achetée est possédée
    définitivement par le joueur et utilisable sur n'importe lequel de ses Pokémon,
    autant de fois qu'il veut — contrairement à un achat ponctuel."""

    def __init__(self, user_id: int, filtre_type: str = "tous", filtre_categorie: str = "tous", page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.filtre_type = filtre_type
        self.filtre_categorie = filtre_categorie
        self.page = page
        self.possedees = database.obtenir_ct_possedees(user_id)
        self._recalculer_liste()
        self._construire_composants()

    def _recalculer_liste(self):
        noms = toutes_attaques_utilisables()
        if self.filtre_type != "tous":
            noms = [n for n in noms if obtenir_attaque(n)["type"] == self.filtre_type]
        if self.filtre_categorie != "tous":
            noms = [n for n in noms if obtenir_attaque(n).get("classe", "physical") == self.filtre_categorie]
        self.attaques = noms
        nb_pages = max(1, (len(self.attaques) + ATTAQUES_PAR_PAGE - 1) // ATTAQUES_PAR_PAGE)
        self.page = min(self.page, nb_pages - 1)

    def construire_embed(self) -> discord.Embed:
        solde = database.obtenir_poke_dollars(self.user_id)
        nb_pages = max(1, (len(self.attaques) + ATTAQUES_PAR_PAGE - 1) // ATTAQUES_PAR_PAGE)
        embed = discord.Embed(
            title="🏪 Boutique CT",
            description=(
                "*« Une CT achetée est à toi pour toujours — utilisable sur n'importe "
                "lequel de tes Pokémon, sans limite. »*"
            ),
            color=discord.Color.purple(),
        )
        embed.set_footer(
            text=(
                f"{solde} PD — {len(self.possedees)} CT possédées — "
                f"{len(self.attaques)} attaques (filtre) — page {self.page + 1}/{nb_pages}"
            )
        )
        return embed

    def _construire_composants(self):
        self.clear_items()

        options_type = [
            discord.SelectOption(label="Tous les types", value="tous", default=self.filtre_type == "tous")
        ]
        for type_nom, emoji in EMOJI_TYPES.items():
            options_type.append(
                discord.SelectOption(
                    label=type_nom.capitalize(), value=type_nom, emoji=emoji, default=self.filtre_type == type_nom
                )
            )
        select_type = discord.ui.Select(placeholder="Filtrer par type...", options=options_type[:25], row=0)
        select_type.callback = self._on_filtre_type
        self.add_item(select_type)

        options_cat = [
            discord.SelectOption(label=label, value=valeur, default=self.filtre_categorie == valeur)
            for valeur, label in CATEGORIES_CT.items()
        ]
        select_cat = discord.ui.Select(placeholder="Filtrer par catégorie...", options=options_cat, row=1)
        select_cat.callback = self._on_filtre_categorie
        self.add_item(select_cat)

        debut = self.page * ATTAQUES_PAR_PAGE
        page_attaques = self.attaques[debut : debut + ATTAQUES_PAR_PAGE]
        options = []
        for nom in page_attaques:
            attaque = obtenir_attaque(nom)
            description = "✅ Déjà possédée" if nom in self.possedees else f"{prix_ct(nom)} PD"
            options.append(
                discord.SelectOption(
                    label=_label_attaque(nom)[:100],
                    description=description[:100],
                    value=nom,
                    emoji=EMOJI_TYPES.get(attaque["type"]),
                )
            )
        select_achat = discord.ui.Select(
            placeholder="Choisis une CT à acheter...",
            options=options if options else [discord.SelectOption(label="Aucune attaque avec ce filtre", value="none")],
            disabled=not options,
            row=2,
        )
        select_achat.callback = self._on_achat
        self.add_item(select_achat)

        nb_pages = max(1, (len(self.attaques) + ATTAQUES_PAR_PAGE - 1) // ATTAQUES_PAR_PAGE)
        if nb_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=3, disabled=self.page == 0)
            bouton_prec.callback = self._on_page_prec
            self.add_item(bouton_prec)
            bouton_suiv = discord.ui.Button(
                label="▶", style=discord.ButtonStyle.secondary, row=3, disabled=self.page >= nb_pages - 1
            )
            bouton_suiv.callback = self._on_page_suiv
            self.add_item(bouton_suiv)

        bouton_retour = discord.ui.Button(label="Retour", emoji="↩️", style=discord.ButtonStyle.secondary, row=3)
        bouton_retour.callback = self._on_retour
        self.add_item(bouton_retour)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta session !", ephemeral=True)
            return False
        return True

    async def _on_filtre_type(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.filtre_type = interaction.data["values"][0]
        self.page = 0
        self._recalculer_liste()
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_filtre_categorie(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.filtre_categorie = interaction.data["values"][0]
        self.page = 0
        self._recalculer_liste()
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_page_prec(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_page_suiv(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(content=None, embed=self.construire_embed(), view=self)

    async def _on_achat(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        nom = interaction.data["values"][0]
        if nom == "none":
            return

        if nom in self.possedees:
            await interaction.response.send_message(f"Tu possèdes déjà la CT de **{nom}** !", ephemeral=True)
            return

        cout = prix_ct(nom)
        solde = database.obtenir_poke_dollars(self.user_id)
        if solde < cout:
            await interaction.response.send_message(
                f"*« Il te faut {cout} {EMOJI_POKEDOLLAR}, tu n'as que {solde} {EMOJI_POKEDOLLAR}. »*",
                ephemeral=True,
            )
            return

        database.ajouter_poke_dollars(self.user_id, -cout)
        database.acheter_ct(self.user_id, nom)
        self.possedees.add(nom)
        self._construire_composants()
        await interaction.response.edit_message(
            content=f"✅ CT **{nom}** achetée pour {cout} {EMOJI_POKEDOLLAR} — utilisable sur tous tes Pokémon dès maintenant.",
            embed=self.construire_embed(),
            view=self,
        )

    async def _on_retour(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        vue = VueChoixPokemonAttaques(self.user_id)
        await interaction.response.edit_message(
            content="*« Quel Pokémon veux-tu entraîner ? »*", embed=None, view=vue
        )
