import discord

import database
import niveaux_pokemon
from pokemon_data import COULEUR_RARETE, EMOJI_POKEDEX, EMOJI_RARETE, POKEDEX, affichage_types, cle_tri_alphabetique_fr, obtenir_pokemon_par_nom, sprite_pokemon, stat_effective

STATS_HEXAGONE = [
    ("pv", "PV"),
    ("attaque", "Attaque"),
    ("defense", "Défense"),
    ("attaque_spe", "Atq. Spé"),
    ("defense_spe", "Déf. Spé"),
    ("vitesse", "Vitesse"),
]


def _texte_hexagone(pokemon: dict, pc: int, niveau: int, niveau_max: int) -> str:
    """Représentation texte des 6 stats de combat (l'équivalent de l'hexagone des jeux
    principaux), avec une mini barre pour comparer d'un coup d'œil. Repère visuel à 200
    (les stats peuvent dépasser sans problème, la barre plafonne juste à 10/10 dans ce cas).
    Retourne None si stats_detaillees n'est pas encore disponible pour cette espèce."""
    echelle = 200
    lignes = []
    for cle, label in STATS_HEXAGONE:
        valeur = stat_effective(pokemon, cle, pc, niveau, niveau_max)
        if valeur is None:
            return None
        rempli = min(10, round(valeur / echelle * 10))
        barre = "█" * rempli + "░" * (10 - rempli)
        lignes.append(f"{label:<9}{barre} {valeur}")
    return "\n".join(lignes)

TAILLE_PAGE = 10

ORDRE_RARETE = {"legendaire": 0, "hyper_rare": 1, "rare": 2, "peu_commun": 3, "commun": 4}


def _agreger_captures(user_id: int) -> dict:
    """Regroupe les lignes de captures (potentiellement séparées shiny/normal) par espèce."""
    captures = database.obtenir_pokedex_joueur(user_id)
    par_nom = {}
    for row in captures:
        entry = par_nom.setdefault(row["pokemon_nom"], {"quantite": 0, "shiny": False, "meilleur_pc": 0})
        entry["quantite"] += row["quantite"]
        entry["meilleur_pc"] = max(entry["meilleur_pc"], row["meilleur_pc"])
        if row["shiny"]:
            entry["shiny"] = True
    return par_nom


def construire_lignes(
    user_id: int,
    filtre_rarete: str = None,
    filtre_generation: int = None,
    tri: str = "alphabetique",
    filtre_capture: str = None,  # None = tous, "non_captures", "captures"
):
    """Retourne (lignes formatées, nb_captures_distinctes, total_especes).
    Chaque ligne est numérotée selon sa POSITION dans la liste actuellement triée et
    filtrée (pas le numéro national du Pokédex) — ex: en filtrant sur la génération 1,
    Bulbizarre devient 1/151 plutôt que son 1/1025 habituel toutes générations confondues."""
    captures_par_nom = _agreger_captures(user_id)

    especes = POKEDEX
    if filtre_rarete:
        especes = [p for p in especes if p["rarete"] == filtre_rarete]
    if filtre_generation:
        especes = [p for p in especes if p.get("generation") == filtre_generation]
    if filtre_capture == "non_captures":
        especes = [p for p in especes if p["nom"] not in captures_par_nom]
    elif filtre_capture == "captures":
        especes = [p for p in especes if p["nom"] in captures_par_nom]

    if tri == "rarete":
        especes = sorted(especes, key=lambda p: (ORDRE_RARETE[p["rarete"]], cle_tri_alphabetique_fr(p["nom"])))
    elif tri == "generation":
        especes = sorted(especes, key=lambda p: (p.get("generation", 0), cle_tri_alphabetique_fr(p["nom"])))
    elif tri == "numero":
        especes = sorted(especes, key=lambda p: p.get("numero", 9999))
    else:
        especes = sorted(especes, key=lambda p: cle_tri_alphabetique_fr(p["nom"]))

    total_liste = len(especes)
    lignes = []
    for position, p in enumerate(especes, start=1):
        emoji = EMOJI_RARETE[p["rarete"]]
        prefixe = f"`{position}/{total_liste}`"
        info = captures_par_nom.get(p["nom"])
        if info:
            shiny_txt = " ✨" if info["shiny"] else ""
            lignes.append(
                f"{prefixe} {emoji} **{p['nom']}**{shiny_txt} — ×{info['quantite']} (meilleur PC : {info['meilleur_pc']})"
            )
        else:
            lignes.append(f"{prefixe} {emoji} ~~{p['nom']}~~ — non capturé")

    nb_captures_distinctes = len(captures_par_nom)
    return lignes, nb_captures_distinctes, len(POKEDEX)


class VuePokedex(discord.ui.View):
    """Vue paginée et interactive du pokédex : tri, filtre rareté/génération, pagination.
    Réservée au joueur qui l'a ouverte."""

    OPTIONS_TRI = [
        ("alphabetique", "Alphabétique"),
        ("numero", "Ordre du Pokédex"),
        ("rarete", "Rareté"),
    ]
    OPTIONS_RARETE = [
        (None, "Toutes les raretés"),
        ("commun", "Commun"),
        ("peu_commun", "Peu commun"),
        ("rare", "Rare"),
        ("hyper_rare", "Hyper Rare"),
        ("legendaire", "Légendaire"),
    ]

    def __init__(
        self,
        user: discord.abc.User,
        filtre_rarete: str = None,
        filtre_generation: int = None,
        tri: str = "alphabetique",
        filtre_capture: str = None,
        page: int = 0,
    ):
        super().__init__(timeout=180)
        self.user = user
        self.filtre_rarete = filtre_rarete
        self.filtre_generation = filtre_generation
        self.tri = tri
        self.filtre_capture = filtre_capture
        self.page = page
        self._recalculer()
        self._construire_composants()

    def _recalculer(self):
        self.lignes, self.nb_captures, self.total = construire_lignes(
            self.user.id,
            filtre_rarete=self.filtre_rarete,
            filtre_generation=self.filtre_generation,
            tri=self.tri,
            filtre_capture=self.filtre_capture,
        )
        self.derniere_page = max(0, (len(self.lignes) - 1) // TAILLE_PAGE)
        self.page = min(self.page, self.derniere_page)

    def _construire_composants(self):
        self.clear_items()

        bouton_precedent = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=0, disabled=self.page <= 0)
        bouton_precedent.callback = self._precedent
        self.add_item(bouton_precedent)

        bouton_suivant = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=0, disabled=self.page >= self.derniere_page)
        bouton_suivant.callback = self._suivant
        self.add_item(bouton_suivant)

        # Cycle Tous -> Non capturés -> Capturés -> Tous... Le libellé indique l'état ACTUEL,
        # et un clic passe à l'état suivant.
        labels_filtre = {None: "Tous", "non_captures": "Non capturés", "captures": "Capturés"}
        couleurs_filtre = {
            None: discord.ButtonStyle.secondary,
            "non_captures": discord.ButtonStyle.primary,
            "captures": discord.ButtonStyle.success,
        }
        bouton_filtre_capture = discord.ui.Button(
            label=labels_filtre[self.filtre_capture],
            style=couleurs_filtre[self.filtre_capture],
            emoji="🔁",
            row=0,
        )
        bouton_filtre_capture.callback = self._cycle_filtre_capture
        self.add_item(bouton_filtre_capture)

        select_tri = discord.ui.Select(
            placeholder="Trier par...",
            row=1,
            options=[
                discord.SelectOption(label=libelle, value=valeur, default=(valeur == self.tri))
                for valeur, libelle in self.OPTIONS_TRI
            ],
        )
        select_tri.callback = self._on_select_tri
        self.add_item(select_tri)

        select_rarete = discord.ui.Select(
            placeholder="Filtrer par rareté...",
            row=2,
            options=[
                discord.SelectOption(
                    label=libelle, value=valeur or "toutes", default=(valeur == self.filtre_rarete)
                )
                for valeur, libelle in self.OPTIONS_RARETE
            ],
        )
        select_rarete.callback = self._on_select_rarete
        self.add_item(select_rarete)

        options_generation = [discord.SelectOption(label="Toutes générations", value="0", default=(self.filtre_generation is None))]
        options_generation += [
            discord.SelectOption(label=f"Génération {i}", value=str(i), default=(self.filtre_generation == i))
            for i in range(1, 10)
        ]
        select_generation = discord.ui.Select(placeholder="Filtrer par génération...", row=3, options=options_generation)
        select_generation.callback = self._on_select_generation
        self.add_item(select_generation)

    def construire_embed(self) -> discord.Embed:
        debut = self.page * TAILLE_PAGE
        fin = debut + TAILLE_PAGE
        description = "\n".join(self.lignes[debut:fin]) or "Aucun résultat pour ces filtres."

        embed = discord.Embed(
            title=f"{EMOJI_POKEDEX} Pokédex de {self.user.display_name}",
            description=description,
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Complétion",
            value=f"{self.nb_captures}/{self.total} espèces capturées ({self.nb_captures / self.total:.0%})",
            inline=False,
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.derniere_page + 1}")
        return embed

    async def _verifier_proprietaire(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("Ce n'est pas ton pokédex !", ephemeral=True)
            return False
        return True

    async def _rafraichir(self, interaction: discord.Interaction):
        self._recalculer()
        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def _precedent(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.page = max(0, self.page - 1)
        await self._rafraichir(interaction)

    async def _suivant(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.page = min(self.derniere_page, self.page + 1)
        await self._rafraichir(interaction)

    async def _cycle_filtre_capture(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        ordre = [None, "non_captures", "captures"]
        index_actuel = ordre.index(self.filtre_capture)
        self.filtre_capture = ordre[(index_actuel + 1) % len(ordre)]
        self.page = 0
        await self._rafraichir(interaction)

    async def _on_select_tri(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        self.tri = interaction.data["values"][0]
        self.page = 0
        await self._rafraichir(interaction)

    async def _on_select_rarete(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        valeur = interaction.data["values"][0]
        self.filtre_rarete = None if valeur == "toutes" else valeur
        self.page = 0
        await self._rafraichir(interaction)

    async def _on_select_generation(self, interaction: discord.Interaction):
        if not await self._verifier_proprietaire(interaction):
            return
        valeur = int(interaction.data["values"][0])
        self.filtre_generation = None if valeur == 0 else valeur
        self.page = 0
        await self._rafraichir(interaction)


def construire_embed_fiche(user_id: int, nom_pokemon: str) -> discord.Embed:
    """Fiche détaillée d'une espèce précise pour un joueur donné."""
    pokemon = obtenir_pokemon_par_nom(nom_pokemon)
    if not pokemon:
        return None

    captures_par_nom = _agreger_captures(user_id)
    info = captures_par_nom.get(pokemon["nom"])

    emoji = EMOJI_RARETE[pokemon["rarete"]]
    types_affiches = affichage_types(pokemon["types"])

    embed = discord.Embed(
        title=f"{pokemon['nom']}",
        color=COULEUR_RARETE[pokemon["rarete"]],
    )
    embed.add_field(name="Type", value=types_affiches, inline=True)
    embed.add_field(name="Rareté", value=f"{emoji} {pokemon['rarete'].replace('_', ' ').upper()}", inline=True)

    if info:
        embed.add_field(name="Capturés", value=f"×{info['quantite']}", inline=True)
        embed.add_field(name="Meilleur PC", value=str(info["meilleur_pc"]), inline=True)
        embed.add_field(name="Shiny obtenu", value="✨ Oui" if info["shiny"] else "Non", inline=True)

        niveau, _xp = database.obtenir_niveau_pokemon(user_id, pokemon["nom"])
        niveau_max = niveaux_pokemon.niveau_max_pour_rarete(pokemon["rarete"])
        embed.add_field(name="Niveau", value=f"⭐ {niveau}/{niveau_max}", inline=True)

        texte_hexagone = _texte_hexagone(pokemon, info["meilleur_pc"], niveau, niveau_max)
        if texte_hexagone:
            embed.add_field(name="📊 Statistiques", value=f"```{texte_hexagone}```", inline=False)

        sprite_url = sprite_pokemon(pokemon, shiny=info["shiny"])
    else:
        embed.add_field(name="Statut", value="Non capturé", inline=False)
        sprite_url = sprite_pokemon(pokemon)

    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    return embed
