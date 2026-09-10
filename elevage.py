import random
import time

import discord

import caisson_croissance as caisson_croissance_module
import config
import database
import niveaux_pokemon
import leveling
import quetes_ui
import race_ui
from pokedex import ORDRE_RARETE
from pokemon_data import (
    EMOJI_BALLS,
    EMOJI_OBJETS_DIVERS,
    EMOJI_SOINS,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
    calculer_pc_derive,
    cle_tri_alphabetique_fr,
    obtenir_pokemon_par_nom,
    sprite_pokemon,
    tirer_ivs,
    tirer_niveau_spawn,
    tirer_pokemon_par_rarete,
)


def _nom_oeuf(palier: str) -> str:
    return NOM_OBJETS_DIVERS.get(f"oeuf_{palier}", f"Œuf {palier}")


def _emoji_oeuf(palier: str) -> str:
    return EMOJI_OBJETS_DIVERS.get(f"oeuf_{palier}", "🥚")


def _duree_txt(secondes: int) -> str:
    if secondes >= 3600:
        return f"{secondes // 3600}h"
    return f"{secondes // 60}min"


def _oeufs_disponibles(user_id: int) -> list:
    """Liste des (palier, quantité) d'œufs possédés, dans l'ordre des paliers de rareté."""
    inventaire = database.obtenir_inventaire_balls(user_id)
    return [
        (palier, inventaire.get(f"oeuf_{palier}", 0))
        for palier in config.OEUF_PALIERS
        if inventaire.get(f"oeuf_{palier}", 0) > 0
    ]


# ----------------------------------------------------------------------------
# Message fixe du Laboratoire (Mutation + Incubateur + Transformateur)
# ----------------------------------------------------------------------------

def construire_embed_labo() -> discord.Embed:
    embed = discord.Embed(
        title="🧪 Le Laboratoire",
        description=(
            "Quatre choses à faire ici :\n\n"
            "🧬 **Ta Mutation de dresseur** — bonus permanents, tirés avec un Cristal de "
            "Mutation (obtenu en Exploration).\n\n"
            "🥚 **Ton incubateur** — place un œuf trouvé au PokéStop ou en Exploration pour "
            "le faire éclore. Chaque palier d'œuf garantit un Pokémon de sa rareté (ou "
            "légèrement mieux, sauf Légendaire), avec une chance de shiny doublée par rapport "
            "à un spawn sauvage.\n\n"
            "🔬 **Le Transformateur** — convertis 10 objets d'un palier en 1 du palier "
            "supérieur (Poké Ball → Super Ball → Hyper Ball ; Potion → Super Potion → Hyper "
            "Potion), pratique pour ne pas laisser traîner un surplus.\n\n"
            f"🧫 **Le Caisson de Croissance** — place jusqu'à {database.NB_SLOTS_CAISSON} "
            f"Pokémon possédés dedans, ils gagnent de l'XP passivement au fil du temps "
            f"({caisson_croissance_module.XP_PAR_HEURE} XP/heure chacun), même sans jouer."
        ),
        color=discord.Color.teal(),
    )
    return embed


class VueLaboratoire(discord.ui.View):
    """Vue persistante attachée au message fixe du Laboratoire."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ma Mutation", style=discord.ButtonStyle.primary, emoji="🧬", custom_id="labo_race_bouton"
    )
    async def race(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = race_ui.construire_embed_race(interaction.user.id)
        vue = race_ui.VueRace(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Mon incubateur", style=discord.ButtonStyle.success, emoji="🥚", custom_id="labo_incubateur_bouton"
    )
    async def incubateur(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, vue = construire_tableau_incubateur(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Transformateur", style=discord.ButtonStyle.secondary, emoji="🔬", custom_id="labo_transformateur_bouton"
    )
    async def transformateur(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = construire_embed_transformateur(interaction.user.id)
        vue = VueTransformateur(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Caisson de Croissance", style=discord.ButtonStyle.secondary, emoji="🧫", custom_id="labo_caisson_bouton"
    )
    async def caisson(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = construire_embed_caisson(interaction.user.id)
        vue = VueCaissonCroissance(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


# ----------------------------------------------------------------------------
# Transformateur — convertit 10 objets d'un palier en 1 du palier supérieur
# (Poké Ball → Super Ball → Hyper Ball ; Potion → Super Potion → Hyper Potion).
# Master Ball et Total Soin restent volontairement hors de cette chaîne, uniquement
# achetables en boutique — voir config.CHAINES_TRANSFORMATION.
# ----------------------------------------------------------------------------

def _nom_affichage_objet(type_objet: str) -> str:
    return NOM_BALL_AFFICHAGE.get(type_objet) or NOM_SOIN_AFFICHAGE.get(type_objet, type_objet)


def _emoji_objet(type_objet: str) -> str:
    return EMOJI_BALLS.get(type_objet) or EMOJI_SOINS.get(type_objet, "")


def construire_embed_transformateur(user_id: int) -> discord.Embed:
    inventaire = database.obtenir_inventaire_balls(user_id)
    embed = discord.Embed(
        title="🔬 Transformateur",
        description=(
            "Convertis 10 objets d'un palier en 1 du palier supérieur — pratique pour ne "
            "pas laisser traîner un surplus de Poké Balls ou de Potions basiques.\n\n"
            "Choisis l'objet, puis le **nombre de lots** que tu veux transformer (ou laisse "
            "vide pour tout transformer d'un coup).\n\n"
            "⚠️ La Master Ball et le Total Soin restent uniquement achetables en boutique, "
            "impossibles à obtenir par transformation."
        ),
        color=discord.Color.teal(),
    )
    for type_source, (type_cible, quantite_requise) in config.CHAINES_TRANSFORMATION.items():
        quantite_actuelle = inventaire.get(type_source, 0)
        nb_lots_possibles = quantite_actuelle // quantite_requise
        embed.add_field(
            name=f"{_emoji_objet(type_source)} {_nom_affichage_objet(type_source)}",
            value=(
                f"Tu en as **{quantite_actuelle}**\n"
                f"→ {quantite_requise} pour 1 {_emoji_objet(type_cible)} {_nom_affichage_objet(type_cible)}\n"
                f"({nb_lots_possibles} transformation(s) possible(s) maintenant)"
            ),
            inline=True,
        )
    return embed


# ----------------------------------------------------------------------------
# Caisson de Croissance — 3 emplacements, XP passive au fil du temps (voir
# caisson_croissance.py pour le calcul, réutilise niveaux_pokemon.gagner_xp_equipe).
# ----------------------------------------------------------------------------

ESPECES_PAR_PAGE_CAISSON = 20


def construire_embed_caisson(user_id: int) -> discord.Embed:
    caisson = database.obtenir_caisson(user_id)
    lignes = []
    maintenant = int(time.time())
    for slot in range(1, database.NB_SLOTS_CAISSON + 1):
        info = caisson[slot]
        if info is None:
            lignes.append(f"**Emplacement {slot}** — *vide*")
        else:
            xp_attente = caisson_croissance_module.xp_en_attente(info["date_debut"])
            secondes = maintenant - info["date_debut"]
            heures, minutes = secondes // 3600, (secondes % 3600) // 60
            lignes.append(
                f"**Emplacement {slot}** — {info['pokemon_nom']} (depuis {heures}h{minutes:02d}, "
                f"{xp_attente} XP en attente)"
            )
    embed = discord.Embed(title="🧫 Caisson de Croissance", description="\n".join(lignes), color=discord.Color.teal())
    embed.set_footer(
        text=f"{caisson_croissance_module.XP_PAR_HEURE} XP/heure par Pokémon — récupère l'XP en le retirant."
    )
    return embed


OPTIONS_TRI_CAISSON = [
    ("alphabetique", "Alphabétique"),
    ("rarete", "Rareté"),
    ("niveau_asc", "Niveau (croissant — les plus faibles d'abord)"),
]


class VueCaissonCroissance(discord.ui.View):
    """Dépôt (select paginé + recherche + tri des espèces possédées non déjà dedans)
    + retrait (un bouton par emplacement occupé, crédite l'XP accumulée immédiatement)."""

    def __init__(self, user_id: int, page: int = 0, tri: str = "alphabetique", recherche: str = None):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.page = page
        self.tri = tri
        self.recherche = recherche
        self.caisson = database.obtenir_caisson(user_id)
        self._construire_composants()

    def _especes_eligibles(self) -> list:
        deja_dedans = {info["pokemon_nom"] for info in self.caisson.values() if info}
        noms_possedes = list({row["pokemon_nom"] for row in database.obtenir_pokedex_joueur(self.user_id)} - deja_dedans)

        if self.recherche:
            terme = cle_tri_alphabetique_fr(self.recherche)
            noms_possedes = [nom for nom in noms_possedes if terme in cle_tri_alphabetique_fr(nom)]

        if self.tri == "rarete":
            def cle_rarete(nom):
                p = obtenir_pokemon_par_nom(nom)
                return (ORDRE_RARETE.get(p["rarete"], 99) if p else 99, cle_tri_alphabetique_fr(nom))
            noms_possedes.sort(key=cle_rarete)
        elif self.tri == "niveau_asc":
            def cle_niveau(nom):
                niveau, _xp = database.obtenir_niveau_pokemon(self.user_id, nom)
                return (niveau, cle_tri_alphabetique_fr(nom))
            noms_possedes.sort(key=cle_niveau)
        else:
            noms_possedes.sort(key=cle_tri_alphabetique_fr)

        return noms_possedes

    def _construire_composants(self):
        self.clear_items()

        slots_libres = any(info is None for info in self.caisson.values())
        especes = self._especes_eligibles() if slots_libres else []

        if slots_libres:
            if especes:
                debut = self.page * ESPECES_PAR_PAGE_CAISSON
                page_especes = especes[debut : debut + ESPECES_PAR_PAGE_CAISSON]
                options = [discord.SelectOption(label=nom[:100], value=nom) for nom in page_especes]
                select = discord.ui.Select(placeholder="Déposer un Pokémon possédé", options=options, row=0)
                select.callback = self._on_deposer
                self.add_item(select)
            # Aucun résultat pour la recherche en cours : pas de select vide, les
            # boutons de recherche/tri/effacement restent quand même disponibles plus bas.

            select_tri = discord.ui.Select(
                placeholder="Trier par...",
                options=[
                    discord.SelectOption(label=libelle, value=valeur, default=(valeur == self.tri))
                    for valeur, libelle in OPTIONS_TRI_CAISSON
                ],
                row=1,
            )
            select_tri.callback = self._on_select_tri
            self.add_item(select_tri)

            nb_pages = max(1, (len(especes) + ESPECES_PAR_PAGE_CAISSON - 1) // ESPECES_PAR_PAGE_CAISSON)
            if nb_pages > 1:
                bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=2, disabled=self.page == 0)
                bouton_prec.callback = self._page_prec
                self.add_item(bouton_prec)
                bouton_suiv = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=2, disabled=self.page >= nb_pages - 1)
                bouton_suiv.callback = self._page_suiv
                self.add_item(bouton_suiv)

            bouton_recherche = discord.ui.Button(
                label=f"Recherche : {self.recherche}" if self.recherche else "Rechercher",
                emoji="🔍",
                style=discord.ButtonStyle.primary if self.recherche else discord.ButtonStyle.secondary,
                row=2,
            )
            bouton_recherche.callback = self._on_rechercher
            self.add_item(bouton_recherche)
            if self.recherche:
                bouton_effacer = discord.ui.Button(label="Effacer", emoji="❌", style=discord.ButtonStyle.secondary, row=2)
                bouton_effacer.callback = self._on_effacer_recherche
                self.add_item(bouton_effacer)

        # Tous les boutons Retirer sur UNE SEULE ligne (jusqu'à 3, tient largement dans
        # la limite de 5 par ligne) — sans ça, avec le select de tri + la pagination/
        # recherche qui prennent maintenant les lignes 1 et 2, il ne resterait que les
        # lignes 3 et 4 pour au plus 3 boutons Retirer, un par ligne comme avant : ça ne
        # suffit plus (ancien bug de dépassement de ligne déjà corrigé une fois, cette
        # fois-ci le regroupement sur une seule ligne évite le problème pour de bon).
        for slot, info in self.caisson.items():
            if info is not None:
                bouton = discord.ui.Button(
                    label=f"Retirer {info['pokemon_nom']} (emplacement {slot})",
                    emoji="📤", style=discord.ButtonStyle.success, row=3,
                )
                bouton.callback = self._faire_retirer(slot)
                self.add_item(bouton)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton Caisson !", ephemeral=True)
            return False
        return True

    async def _on_deposer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        pokemon_nom = interaction.data["values"][0]
        succes, message = caisson_croissance_module.deposer(self.user_id, pokemon_nom)
        prefixe = "✅ " if succes else "❌ "
        self.caisson = database.obtenir_caisson(self.user_id)
        self._construire_composants()
        await interaction.response.edit_message(
            content=f"{prefixe}{message}", embed=construire_embed_caisson(self.user_id), view=self
        )

    def _faire_retirer(self, slot: int):
        async def callback(interaction: discord.Interaction):
            if not await self._verifier(interaction):
                return
            resultat = caisson_croissance_module.retirer(self.user_id, slot)
            if resultat is None:
                await interaction.response.send_message("Cet emplacement est déjà vide.", ephemeral=True)
                return
            texte = f"✅ **{resultat['pokemon_nom']}** retiré — +{resultat['xp_gagnee']} XP crédités !"
            if resultat["montees_niveau"]:
                texte += "\n" + niveaux_pokemon.texte_montees_niveau(resultat["montees_niveau"])
            self.caisson = database.obtenir_caisson(self.user_id)
            self._construire_composants()
            await interaction.response.edit_message(content=texte, embed=construire_embed_caisson(self.user_id), view=self)
        return callback

    async def _page_prec(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _page_suiv(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_select_tri(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.tri = interaction.data["values"][0]
        self.page = 0
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_rechercher(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        await interaction.response.send_modal(ModalRechercheCaisson(self))

    async def _on_effacer_recherche(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.recherche = None
        self.page = 0
        self._construire_composants()
        await interaction.response.edit_message(view=self)


class ModalRechercheCaisson(discord.ui.Modal, title="Rechercher un Pokémon"):
    recherche_input = discord.ui.TextInput(label="Nom (ou partie du nom)", placeholder="Ex : Rat", required=False)

    def __init__(self, vue_parente: VueCaissonCroissance):
        super().__init__()
        self.vue_parente = vue_parente
        self.recherche_input.default = vue_parente.recherche or ""

    async def on_submit(self, interaction: discord.Interaction):
        self.vue_parente.recherche = self.recherche_input.value.strip() or None
        self.vue_parente.page = 0
        self.vue_parente._construire_composants()
        await interaction.response.edit_message(
            embed=construire_embed_caisson(self.vue_parente.user_id), view=self.vue_parente
        )


class _ModalQuantiteTransformation(discord.ui.Modal):
    """Demande combien de lots transformer (1 à nb_lots_max), plutôt que de forcer le
    maximum comme avant — ouverte juste après avoir choisi QUEL objet transformer dans
    le select de VueTransformateur."""

    def __init__(self, user_id: int, type_source: str, nb_lots_max: int, vue_parente: "VueTransformateur"):
        super().__init__(title=f"Transformer {_nom_affichage_objet(type_source)}"[:45])
        self.user_id = user_id
        self.type_source = type_source
        self.nb_lots_max = nb_lots_max
        self.vue_parente = vue_parente
        self.quantite_input = discord.ui.TextInput(
            label=f"Nombre de lots (1 à {nb_lots_max})",
            placeholder=f"Maximum : {nb_lots_max} — laisse vide pour tout transformer",
            default=str(nb_lots_max),
            required=False,
            max_length=len(str(nb_lots_max)),
        )
        self.add_item(self.quantite_input)

    async def on_submit(self, interaction: discord.Interaction):
        valeur = self.quantite_input.value.strip()
        if not valeur:
            nb_lots_demande = self.nb_lots_max  # champ vide = tout transformer, comme avant
        else:
            try:
                nb_lots_demande = int(valeur)
            except ValueError:
                await interaction.response.send_message("❌ Entre un nombre entier valide.", ephemeral=True)
                return
            if nb_lots_demande <= 0:
                await interaction.response.send_message("❌ Le nombre de lots doit être positif.", ephemeral=True)
                return

        nb_lots, type_cible, quantite_consommee = database.transformer_objets(self.user_id, self.type_source, nb_lots_demande)
        if nb_lots <= 0:
            await interaction.response.send_message(
                "Il n'y avait plus assez d'objets pour transformer (quelqu'un a été plus rapide que toi ?).", ephemeral=True
            )
            return

        self.vue_parente._construire_options()
        embed = construire_embed_transformateur(self.user_id)
        await interaction.response.edit_message(embed=embed, view=self.vue_parente)
        await interaction.followup.send(
            f"✅ {quantite_consommee} {_emoji_objet(self.type_source)} {_nom_affichage_objet(self.type_source)} "
            f"transformés en {nb_lots} {_emoji_objet(type_cible)} {_nom_affichage_objet(type_cible)} !",
            ephemeral=True,
        )


class VueTransformateur(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self._construire_options()

    def _construire_options(self):
        self.clear_items()
        inventaire = database.obtenir_inventaire_balls(self.user_id)
        options = []
        for type_source, (type_cible, quantite_requise) in config.CHAINES_TRANSFORMATION.items():
            quantite_actuelle = inventaire.get(type_source, 0)
            nb_lots_possibles = quantite_actuelle // quantite_requise
            if nb_lots_possibles <= 0:
                continue  # pas assez pour un seul lot complet, inutile de le proposer
            options.append(
                discord.SelectOption(
                    label=f"{_nom_affichage_objet(type_source)} → {_nom_affichage_objet(type_cible)} "
                    f"({nb_lots_possibles}× possible)",
                    value=type_source,
                    emoji=_emoji_objet(type_source) or None,
                )
            )
        if options:
            select = discord.ui.Select(placeholder="Choisis quel objet transformer…", options=options)
            select.callback = self._on_select
            self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton Transformateur !", ephemeral=True)
            return
        type_source = interaction.data["values"][0]
        inventaire = database.obtenir_inventaire_balls(self.user_id)
        _type_cible, quantite_requise = config.CHAINES_TRANSFORMATION[type_source]
        nb_lots_max = inventaire.get(type_source, 0) // quantite_requise
        if nb_lots_max <= 0:
            await interaction.response.send_message(
                "Il n'y avait plus assez d'objets pour transformer (quelqu'un a été plus rapide que toi ?).", ephemeral=True
            )
            self._construire_options()
            await interaction.message.edit(view=self)
            return
        await interaction.response.send_modal(_ModalQuantiteTransformation(self.user_id, type_source, nb_lots_max, self))



# ----------------------------------------------------------------------------
# Incubateur
# ----------------------------------------------------------------------------

def construire_tableau_incubateur(user_id: int):
    row = database.obtenir_incubation_active(user_id)
    maintenant = int(time.time())
    embed = discord.Embed(title="🥚 Ton incubateur", color=discord.Color.teal())

    if row is None or row["palier"] is None:
        embed.add_field(name="Emplacement", value="*Libre*", inline=False)
    else:
        termine = row["date_fin"] <= maintenant
        statut = "✅ Prêt à éclore !" if termine else f"⏳ Éclosion <t:{row['date_fin']}:R>"
        embed.add_field(
            name="Emplacement",
            value=f"{_emoji_oeuf(row['palier'])} {_nom_oeuf(row['palier'])}\n{statut}",
            inline=False,
        )

    oeufs = _oeufs_disponibles(user_id)
    if oeufs:
        lignes = [f"{_emoji_oeuf(p)} {_nom_oeuf(p)} ×{q}" for p, q in oeufs]
        embed.add_field(name="🎒 Œufs en stock", value="\n".join(lignes), inline=False)
    else:
        embed.add_field(
            name="🎒 Œufs en stock",
            value="*Aucun pour l'instant — trouvables au PokéStop ou en Exploration.*",
            inline=False,
        )

    vue = VueTableauIncubateur(user_id, row, oeufs, maintenant)
    return embed, vue


class VueTableauIncubateur(discord.ui.View):
    def __init__(self, user_id: int, row, oeufs: list, maintenant: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        emplacement_libre = row is None or row["palier"] is None
        pret_a_eclore = not emplacement_libre and row["date_fin"] and row["date_fin"] <= maintenant

        if pret_a_eclore:
            bouton = discord.ui.Button(label="Récupérer l'éclosion", style=discord.ButtonStyle.success, emoji="🎉")
            bouton.callback = self._on_recuperer
            self.add_item(bouton)
        elif emplacement_libre and oeufs:
            options = [
                discord.SelectOption(
                    label=f"{_nom_oeuf(p)} (×{q})",
                    value=p,
                    description=f"Éclosion en {_duree_txt(config.OEUF_DUREE_INCUBATION[p])}",
                    emoji=_emoji_oeuf(p),
                )
                for p, q in oeufs
            ]
            select = discord.ui.Select(placeholder="Choisis un œuf à incuber...", options=options)
            select.callback = self._on_choisir
            self.add_item(select)
        # sinon : emplacement occupé mais pas encore prêt — rien à faire, juste attendre

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton incubateur !", ephemeral=True)
            return False
        return True

    async def _on_choisir(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        palier = interaction.data["values"][0]
        if not database.retirer_ball(self.user_id, f"oeuf_{palier}"):
            await interaction.response.send_message("Tu n'as plus cet œuf !", ephemeral=True)
            return
        database.demarrer_incubation(self.user_id, 1, palier, config.OEUF_DUREE_INCUBATION[palier])
        embed, vue = construire_tableau_incubateur(self.user_id)
        await interaction.response.edit_message(embed=embed, view=vue)

    async def _on_recuperer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        embed_resultat = eclore_oeuf(self.user_id)
        await interaction.response.edit_message(embed=embed_resultat, view=None)


def eclore_oeuf(user_id: int) -> discord.Embed:
    """Fait éclore l'œuf prêt sur l'emplacement du joueur, crédite la capture, et retourne
    l'embed de résultat. Ne vérifie PAS que l'œuf est vraiment prêt — appelant responsable
    (le bouton "Récupérer" n'apparaît que si c'est le cas)."""
    row = database.obtenir_incubation_active(user_id)
    if row is None or row["palier"] is None:
        return discord.Embed(description="Aucun œuf prêt à éclore.", color=discord.Color.red())

    palier = row["palier"]
    database.terminer_incubation(user_id, 1)

    distribution = config.OEUF_DISTRIBUTION_ECLOSION[palier]
    rarete_resultat = random.choices(list(distribution.keys()), weights=list(distribution.values()))[0]
    pokemon = tirer_pokemon_par_rarete(rarete_resultat)
    ivs = tirer_ivs()
    niveau = tirer_niveau_spawn(pokemon["rarete"])  # même grille que les spawns sauvages, cohérent selon la rareté
    pc = calculer_pc_derive(pokemon, ivs, niveau)

    chance_shiny = (
        config.CHANCE_SHINY_BASE
        * config.OEUF_MULTIPLICATEUR_SHINY
        * database.multiplicateur_boost(user_id, "shiny")
    )
    est_shiny = random.random() < chance_shiny

    nouvelle_entree = database.compter_captures_espece(user_id, pokemon["nom"]) == 0
    database.ajouter_capture(user_id, pokemon["nom"], pc, shiny=est_shiny, ivs=ivs)

    # Même règle que pour les captures sauvages : le niveau ne s'applique à l'équipe que
    # s'il est meilleur que celui déjà acquis (jamais de régression pour un Pokémon déjà entraîné).
    niveau_actuel, _xp_actuel = database.obtenir_niveau_pokemon(user_id, pokemon["nom"])
    if niveau > niveau_actuel:
        database.definir_niveau_xp_pokemon(user_id, pokemon["nom"], niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau))
    quetes_completees = database.incrementer_progression_quete(user_id, "capture", {"rarete": pokemon["rarete"]})

    xp_gagnee = config.XP_PAR_RARETE[pokemon["rarete"]]
    if est_shiny:
        xp_gagnee += config.XP_BONUS_SHINY
    # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
    # applique son propre multiplicateur en interne, on le reproduit ici pour le texte.
    xp_affichee = round(xp_gagnee * database.multiplicateur_boost(user_id, "xp"))
    leveling.gagner_xp(user_id, xp_gagnee)

    titre = "✨ ÉCLOSION SHINY ! ✨" if est_shiny else "🐣 Éclosion !"
    embed = discord.Embed(
        title=titre,
        description=(
            f"Ton {_emoji_oeuf(palier)} {_nom_oeuf(palier)} a éclos en "
            f"**{pokemon['nom']}**{' shiny' if est_shiny else ''} ({pc} PC) !\n"
            f"✨ +{xp_affichee} XP"
            f"{quetes_ui.texte_notifications_completion(quetes_completees)}"
        ),
        color=discord.Color.gold() if est_shiny else discord.Color.teal(),
    )
    if nouvelle_entree:
        embed.add_field(
            name="📖 Nouvelle entrée !",
            value=f"**{pokemon['nom']}** rejoint ton Pokédex pour la première fois !",
            inline=False,
        )

    sprite_url = sprite_pokemon(pokemon, shiny=est_shiny)
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    return embed
