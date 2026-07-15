import discord

import config
import database
from pokedex import ORDRE_RARETE
from pokemon_data import EMOJI_RARETE, EMOJI_SOINS, NOM_SOIN_AFFICHAGE, calculer_pv_max, cle_tri_alphabetique_fr, obtenir_pokemon_par_nom

TAILLE_MAX_EQUIPE = database.TAILLE_MAX_EQUIPE_COMBAT

OPTIONS_TRI = [
    ("alphabetique", "Alphabétique"),
    ("rarete", "Rareté"),
    ("pc_desc", "PC : fort → faible"),
    ("pc_asc", "PC : faible → fort"),
]


def _stats_par_espece(user_id: int) -> dict:
    """Retourne {pokemon_nom: {"pc": meilleur_pc, "shiny": bool}} à partir des captures du joueur."""
    captures = database.obtenir_pokedex_joueur(user_id)
    stats = {}
    for row in captures:
        entry = stats.setdefault(row["pokemon_nom"], {"pc": 0, "shiny": False})
        entry["pc"] = max(entry["pc"], row["meilleur_pc"])
        if row["shiny"]:
            entry["shiny"] = True
    return stats


def equiper_meilleure_equipe(user_id: int) -> list:
    """Vide l'équipe actuelle et la reconstitue avec les 6 meilleures espèces par PC.
    Retourne la liste des noms sélectionnés."""
    stats = _stats_par_espece(user_id)
    top = sorted(stats.items(), key=lambda kv: -kv[1]["pc"])[:TAILLE_MAX_EQUIPE]

    database.vider_equipe_combat(user_id)
    noms_selectionnes = []
    for nom, _info in top:
        database.ajouter_a_equipe_combat(user_id, nom)
        noms_selectionnes.append(nom)
    return noms_selectionnes


def construire_embed_equipe(user: discord.abc.User) -> discord.Embed:
    noms_equipe = database.obtenir_equipe_combat(user.id)
    stats = _stats_par_espece(user.id)

    lignes = []
    for i in range(TAILLE_MAX_EQUIPE):
        if i < len(noms_equipe):
            nom = noms_equipe[i]
            info = stats.get(nom)
            pokemon = obtenir_pokemon_par_nom(nom)
            emoji_rarete = EMOJI_RARETE[pokemon["rarete"]] if pokemon else ""
            shiny_txt = " ✨" if info and info["shiny"] else ""
            pc_txt = info["pc"] if info else "?"

            pv_max = calculer_pv_max(info["pc"]) if info else 1
            pv_actuels = database.obtenir_pv_actuels(user.id, nom, pv_max)
            ko_txt = " 💀 K.O." if pv_actuels <= 0 else ""

            lignes.append(
                f"{i + 1}. {emoji_rarete} **{nom}**{shiny_txt} — {pc_txt} PC — "
                f"❤️ {pv_actuels}/{pv_max} PV{ko_txt}"
            )
        else:
            lignes.append(f"{i + 1}. *Emplacement vide*")

    embed = discord.Embed(
        title=f"⚔️ Équipe de combat de {user.display_name}",
        description="\n".join(lignes),
        color=discord.Color.dark_red(),
    )
    embed.set_footer(
        text=f"{len(noms_equipe)}/{TAILLE_MAX_EQUIPE} emplacements utilisés — "
        f"soigne tes Pokémon blessés avec le bouton Soigner !"
    )
    return embed


class ModalRechercheEquipe(discord.ui.Modal):
    """Fenêtre de saisie pour filtrer le menu d'ajout par nom."""

    def __init__(self, vue_parente: "VueEquipeCombat"):
        super().__init__(title="Rechercher un Pokémon")
        self.vue_parente = vue_parente
        self.recherche_input = discord.ui.TextInput(
            label="Nom (ou partie du nom)",
            placeholder="Ex : Rat",
            required=False,
            default=vue_parente.recherche or "",
        )
        self.add_item(self.recherche_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.vue_parente.recherche = self.recherche_input.value.strip() or None
        self.vue_parente.page_ajout = 0
        self.vue_parente._construire_composants()
        await interaction.response.edit_message(
            embed=construire_embed_equipe(interaction.user), view=self.vue_parente
        )


class VueEquipeCombat(discord.ui.View):
    """Vue éphémère pour composer son équipe de combat (ajout/retrait, tri, recherche)."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.tri = "alphabetique"
        self.recherche = None
        self.page_ajout = 0
        self._construire_composants()

    def _lister_especes_disponibles(self, stats: dict, equipe_actuelle: set) -> list:
        noms = [n for n in stats.keys() if n not in equipe_actuelle]

        if self.recherche:
            terme = self.recherche.lower()
            noms = [n for n in noms if terme in n.lower()]

        if self.tri == "rarete":
            def cle_rarete(n):
                p = obtenir_pokemon_par_nom(n)
                return (ORDRE_RARETE.get(p["rarete"], 99) if p else 99, n)

            noms.sort(key=cle_rarete)
        elif self.tri == "pc_desc":
            noms.sort(key=lambda n: -stats[n]["pc"])
        elif self.tri == "pc_asc":
            noms.sort(key=lambda n: stats[n]["pc"])
        else:
            noms.sort(key=cle_tri_alphabetique_fr)

        return noms

    def _construire_composants(self):
        self.clear_items()

        equipe_actuelle = set(database.obtenir_equipe_combat(self.user_id))
        stats = _stats_par_espece(self.user_id)
        especes_disponibles = self._lister_especes_disponibles(stats, equipe_actuelle)

        if especes_disponibles and len(equipe_actuelle) < TAILLE_MAX_EQUIPE:
            TAILLE_PAGE = 25
            nb_pages = max(1, (len(especes_disponibles) + TAILLE_PAGE - 1) // TAILLE_PAGE)
            self.page_ajout = max(0, min(self.page_ajout, nb_pages - 1))
            especes_page = especes_disponibles[self.page_ajout * TAILLE_PAGE : (self.page_ajout + 1) * TAILLE_PAGE]

            options = [
                discord.SelectOption(label=n, value=n, description=f"{stats[n]['pc']} PC")
                for n in especes_page
            ]
            placeholder = "➕ Ajouter un Pokémon..."
            if self.recherche:
                placeholder = f"➕ Ajouter (recherche : {self.recherche})"
            if nb_pages > 1:
                placeholder += f" — page {self.page_ajout + 1}/{nb_pages}"
            select_ajouter = discord.ui.Select(placeholder=placeholder, options=options, row=0)
            select_ajouter.callback = self._on_ajouter
            self.add_item(select_ajouter)

            if nb_pages > 1:
                bouton_page_precedente = discord.ui.Button(
                    label="◀", style=discord.ButtonStyle.secondary,
                    disabled=(self.page_ajout == 0), row=3,
                )
                bouton_page_precedente.callback = self._on_page_ajout_precedente
                self.add_item(bouton_page_precedente)

                bouton_page_suivante = discord.ui.Button(
                    label="▶", style=discord.ButtonStyle.secondary,
                    disabled=(self.page_ajout >= nb_pages - 1), row=3,
                )
                bouton_page_suivante.callback = self._on_page_ajout_suivante
                self.add_item(bouton_page_suivante)
        elif self.recherche:
            # Recherche active mais aucun résultat : on informe via le placeholder d'un select désactivé
            select_vide = discord.ui.Select(
                placeholder=f"Aucun résultat pour \"{self.recherche}\"",
                options=[discord.SelectOption(label="Aucun résultat", value="none")],
                disabled=True,
                row=0,
            )
            self.add_item(select_vide)

        if equipe_actuelle:
            options_retrait = [
                discord.SelectOption(label=n, value=n) for n in sorted(equipe_actuelle, key=cle_tri_alphabetique_fr)
            ]
            select_retirer = discord.ui.Select(
                placeholder="➖ Retirer un Pokémon...", options=options_retrait, row=1
            )
            select_retirer.callback = self._on_retirer
            self.add_item(select_retirer)

        select_tri = discord.ui.Select(
            placeholder="Trier le menu d'ajout par...",
            row=2,
            options=[
                discord.SelectOption(label=libelle, value=valeur, default=(valeur == self.tri))
                for valeur, libelle in OPTIONS_TRI
            ],
        )
        select_tri.callback = self._on_select_tri
        self.add_item(select_tri)

        bouton_recherche = discord.ui.Button(
            label="Rechercher", emoji="🔍", style=discord.ButtonStyle.secondary, row=3
        )
        bouton_recherche.callback = self._on_rechercher
        self.add_item(bouton_recherche)

        bouton_soigner = discord.ui.Button(
            label="Soigner", emoji="❤️‍🩹", style=discord.ButtonStyle.success, row=4
        )
        bouton_soigner.callback = self._on_soigner
        self.add_item(bouton_soigner)

        bouton_soin_auto = discord.ui.Button(
            label="Soin auto", emoji="🩹", style=discord.ButtonStyle.success, row=4
        )
        bouton_soin_auto.callback = self._on_soin_auto
        self.add_item(bouton_soin_auto)

        bouton_auto = discord.ui.Button(
            label="Auto (meilleure équipe)", emoji="🏆", style=discord.ButtonStyle.primary, row=4
        )
        bouton_auto.callback = self._on_auto
        self.add_item(bouton_auto)

        if equipe_actuelle:
            bouton_reorganiser = discord.ui.Button(
                label="Réorganiser l'ordre", emoji="🔀", style=discord.ButtonStyle.secondary, row=4
            )
            bouton_reorganiser.callback = self._on_reorganiser
            self.add_item(bouton_reorganiser)

        if self.recherche:
            bouton_effacer = discord.ui.Button(
                label="Effacer la recherche", emoji="❌", style=discord.ButtonStyle.secondary, row=3
            )
            bouton_effacer.callback = self._on_effacer_recherche
            self.add_item(bouton_effacer)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton équipe !", ephemeral=True)
            return False
        return True

    async def _on_ajouter(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        nom = interaction.data["values"][0]
        database.ajouter_a_equipe_combat(self.user_id, nom)
        self._construire_composants()
        await interaction.response.edit_message(
            embed=construire_embed_equipe(interaction.user), view=self
        )

    async def _on_retirer(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        nom = interaction.data["values"][0]
        database.retirer_de_equipe_combat(self.user_id, nom)
        self._construire_composants()
        await interaction.response.edit_message(
            embed=construire_embed_equipe(interaction.user), view=self
        )

    async def _on_select_tri(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.tri = interaction.data["values"][0]
        self.page_ajout = 0
        self._construire_composants()
        await interaction.response.edit_message(
            embed=construire_embed_equipe(interaction.user), view=self
        )

    async def _on_rechercher(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        await interaction.response.send_modal(ModalRechercheEquipe(self))

    async def _on_page_ajout_precedente(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.page_ajout -= 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_page_ajout_suivante(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.page_ajout += 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_soigner(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        vue_soin = VueSoin(self.user_id)
        if not vue_soin._lister_blesses():
            await interaction.response.send_message(
                "Aucun de tes Pokémon d'équipe n'est blessé pour l'instant !", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Choisis le Pokémon à soigner, puis la potion à utiliser :",
            view=vue_soin,
            ephemeral=True,
        )

    async def _on_soin_auto(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return

        vue_soin = VueSoin(self.user_id)
        blesses = vue_soin._lister_blesses()
        if not blesses:
            await interaction.response.send_message(
                "Aucun de tes Pokémon d'équipe n'est blessé pour l'instant !", ephemeral=True
            )
            return

        # Du plus faible au plus fort, pour économiser les Hyper Potions : chaque Pokémon
        # blessé reçoit d'abord des Potions normales, et on n'utilise une potion plus forte
        # que si les plus faibles ne suffisent plus (stock épuisé) et qu'il lui manque encore
        # des PV.
        ordre_potions = ("potion", "superpotion", "hyperpotion")
        lignes = []
        total_potions_utilisees = 0

        for nom, pv_actuels, pv_max in blesses:
            pv_courant = pv_actuels
            for potion in ordre_potions:
                while pv_courant < pv_max:
                    if not database.retirer_ball(self.user_id, potion):
                        break  # plus de stock de cette potion, on tente la suivante
                    delta = max(1, round(pv_max * config.SOIN_POURCENT[potion]))
                    pv_courant = database.modifier_pv_pokemon(self.user_id, nom, delta, pv_max)
                    total_potions_utilisees += 1
                if pv_courant >= pv_max:
                    break
            if pv_courant != pv_actuels:
                lignes.append(f"**{nom}** : {pv_actuels} → {pv_courant}/{pv_max} PV")

        if not lignes:
            await interaction.response.send_message(
                "Tu n'as aucune potion en stock pour soigner ton équipe !", ephemeral=True
            )
            return

        self._construire_composants()
        await interaction.response.edit_message(
            content=(
                f"🩹 **Soin auto** ({total_potions_utilisees} potion(s) utilisée(s)) :\n"
                + "\n".join(lignes)
            ),
            embed=construire_embed_equipe(interaction.user),
            view=self,
        )

    async def _on_auto(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        noms = equiper_meilleure_equipe(self.user_id)
        self._construire_composants()
        await interaction.response.edit_message(
            content=f"🏆 Équipe recomposée avec tes {len(noms)} Pokémon les plus puissants (par PC) !",
            embed=construire_embed_equipe(interaction.user),
            view=self,
        )

    async def _on_reorganiser(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        vue = VueReorganiserEquipe(self.user_id)
        await interaction.response.send_message(
            "Choisis un Pokémon puis utilise ⬆️/⬇️ pour changer sa place :",
            embed=construire_embed_equipe(interaction.user),
            view=vue,
            ephemeral=True,
        )

    async def _on_effacer_recherche(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.recherche = None
        self._construire_composants()
        await interaction.response.edit_message(
            embed=construire_embed_equipe(interaction.user), view=self
        )


class VueSoin(discord.ui.View):
    """Vue éphémère pour soigner les Pokémon blessés de son équipe avec des potions."""

    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.pokemon_selectionne = None
        self._construire_composants()

    def _lister_blesses(self):
        noms_equipe = database.obtenir_equipe_combat(self.user_id)
        stats = _stats_par_espece(self.user_id)
        blesses = []
        for nom in noms_equipe:
            pc = stats.get(nom, {}).get("pc", 0)
            pv_max = calculer_pv_max(pc)
            pv_actuels = database.obtenir_pv_actuels(self.user_id, nom, pv_max)
            if pv_actuels < pv_max:
                blesses.append((nom, pv_actuels, pv_max))
        return blesses

    def _construire_composants(self):
        self.clear_items()
        blesses = self._lister_blesses()

        options_pokemon = [
            discord.SelectOption(
                label=f"{nom} ({pv}/{pv_max} PV)",
                value=nom,
                default=(nom == self.pokemon_selectionne),
            )
            for nom, pv, pv_max in blesses[:25]
        ]
        select_pokemon = discord.ui.Select(
            placeholder="Quel Pokémon soigner ?",
            options=options_pokemon if options_pokemon else [discord.SelectOption(label="Aucun blessé", value="none")],
            disabled=not options_pokemon,
            row=0,
        )
        select_pokemon.callback = self._on_select_pokemon
        self.add_item(select_pokemon)

        if self.pokemon_selectionne:
            inventaire = database.obtenir_inventaire_balls(self.user_id)
            options_potion = [
                discord.SelectOption(
                    label=f"{NOM_SOIN_AFFICHAGE[cle]} (x{inventaire.get(cle, 0)})",
                    value=cle,
                    emoji=EMOJI_SOINS[cle],
                )
                for cle in ("potion", "superpotion", "hyperpotion")
                if inventaire.get(cle, 0) > 0
            ]
            select_potion = discord.ui.Select(
                placeholder="Avec quelle potion ?",
                options=options_potion if options_potion else [discord.SelectOption(label="Aucune potion possédée", value="none")],
                disabled=not options_potion,
                row=1,
            )
            select_potion.callback = self._on_select_potion
            self.add_item(select_potion)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton équipe !", ephemeral=True)
            return False
        return True

    async def _on_select_pokemon(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.pokemon_selectionne = interaction.data["values"][0]
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_select_potion(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return

        potion = interaction.data["values"][0]
        nom = self.pokemon_selectionne
        if potion == "none" or nom is None:
            return

        if not database.retirer_ball(self.user_id, potion):
            await interaction.response.edit_message(content="Tu n'as plus cette potion.", view=self)
            return

        stats = _stats_par_espece(self.user_id)
        pc = stats.get(nom, {}).get("pc", 0)
        pv_max = calculer_pv_max(pc)
        delta = max(1, round(pv_max * config.SOIN_POURCENT[potion]))
        nouveau_pv = database.modifier_pv_pokemon(self.user_id, nom, delta, pv_max)

        self.pokemon_selectionne = None
        self._construire_composants()
        await interaction.response.edit_message(
            content=f"✅ **{nom}** soigné avec {NOM_SOIN_AFFICHAGE[potion]} ! ({nouveau_pv}/{pv_max} PV)",
            view=self,
        )


class VueReorganiserEquipe(discord.ui.View):
    """Vue éphémère simple pour changer l'ordre des Pokémon dans l'équipe : on choisit
    un Pokémon dans le menu, puis ⬆️/⬇️ l'échange de place avec son voisin."""

    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.pokemon_selectionne = None
        self._construire_composants()

    def _construire_composants(self):
        self.clear_items()
        ordre = database.obtenir_equipe_combat(self.user_id)

        options = [
            discord.SelectOption(label=f"{i + 1}. {nom}", value=nom, default=(nom == self.pokemon_selectionne))
            for i, nom in enumerate(ordre)
        ]
        select = discord.ui.Select(placeholder="Quel Pokémon déplacer ?", options=options, row=0)
        select.callback = self._on_select
        self.add_item(select)

        index_actuel = ordre.index(self.pokemon_selectionne) if self.pokemon_selectionne in ordre else None

        bouton_monter = discord.ui.Button(
            label="Monter",
            emoji="⬆️",
            style=discord.ButtonStyle.primary,
            disabled=(index_actuel is None or index_actuel == 0),
            row=1,
        )
        bouton_monter.callback = self._on_monter
        self.add_item(bouton_monter)

        bouton_descendre = discord.ui.Button(
            label="Descendre",
            emoji="⬇️",
            style=discord.ButtonStyle.primary,
            disabled=(index_actuel is None or index_actuel == len(ordre) - 1),
            row=1,
        )
        bouton_descendre.callback = self._on_descendre
        self.add_item(bouton_descendre)

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton équipe !", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.pokemon_selectionne = interaction.data["values"][0]
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_equipe(interaction.user), view=self)

    async def _deplacer(self, interaction: discord.Interaction, direction: int):
        if not await self._verifier_proprietaire(interaction):
            return
        if self.pokemon_selectionne is None:
            return
        database.deplacer_pokemon_equipe(self.user_id, self.pokemon_selectionne, direction)
        self._construire_composants()
        try:
            await interaction.response.edit_message(embed=construire_embed_equipe(interaction.user), view=self)
        except (discord.NotFound, discord.HTTPException):
            # Interaction expirée (bot ralenti/redémarré entre le clic et la réponse) — le
            # déplacement est déjà appliqué en base, il ne manque que la confirmation visuelle.
            pass

    async def _on_monter(self, interaction: discord.Interaction):
        await self._deplacer(interaction, -1)

    async def _on_descendre(self, interaction: discord.Interaction):
        await self._deplacer(interaction, 1)
