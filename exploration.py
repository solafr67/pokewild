import random
import time

import discord

import config
import database
import formes_objets as formes_objets_module
import leveling
import niveaux_pokemon
import quetes_ui
import races
from equipe_combat import _stats_par_espece
from pokemon_data import EMOJI_OBJETS_DIVERS, EMOJI_POKEDOLLAR, NOM_OBJETS_DIVERS, obtenir_pokemon_par_nom

EMOJI_CRISTAL = "🔮"
NOM_CRISTAL = "Cristal de Mutation"

# --- Destinations thématiques ---
# Chaque destination biaise les 3 chances de récompense (multiplicateurs, appliqués
# APRÈS le calcul habituel par PC/durée, toujours plafonnés ensuite comme avant) — un
# vrai choix stratégique plutôt que "j'envoie qui a le plus de PC, peu importe où".
# BONUS_AFFINITE_TYPE s'ajoute EN PLUS si au moins 2 des 3 Pokémon envoyés ont un type
# qui correspond au thème de la destination — encourage à composer une équipe variée
# plutôt que toujours les 3 mêmes gros PC.
BONUS_AFFINITE_TYPE = 1.3
NB_AFFINITE_REQUIS = 2  # sur 3 Pokémon envoyés

DESTINATIONS_EXPLORATION = {
    "foret": {
        "nom": "Forêt Verdoyante", "emoji": "🌲",
        "types_affinite": ["plante", "insecte"],
        "mult_cristal": 1.0, "mult_oeuf": 1.4, "mult_objet_forme": 0.8,
        "description": "Grouille de vie sauvage — nettement plus de chances d'œufs.",
    },
    "volcan": {
        "nom": "Volcan Ardent", "emoji": "🌋",
        "types_affinite": ["feu", "roche"],
        "mult_cristal": 1.6, "mult_oeuf": 0.8, "mult_objet_forme": 0.9,
        "description": "Terrain hostile chargé d'énergie brute — nettement plus de Cristaux de Mutation.",
    },
    "grotte": {
        "nom": "Grotte Sous-Marine", "emoji": "🌊",
        "types_affinite": ["eau", "glace"],
        "mult_cristal": 0.9, "mult_oeuf": 1.2, "mult_objet_forme": 1.1,
        "description": "Passages engloutis et courants profonds — équilibré, un peu de tout.",
    },
    "ruines": {
        "nom": "Ruines Antiques", "emoji": "🏛️",
        "types_affinite": ["psy", "spectre", "dragon"],
        "mult_cristal": 1.0, "mult_oeuf": 0.7, "mult_objet_forme": 1.8,
        "description": "Vestiges d'une civilisation oubliée — de loin le meilleur endroit PERMANENT pour les objets de forme légendaire.",
    },
}

# Faille d'exploration — événement temporaire (1h/jour, voir main.py::boucle_faille_exploration),
# AJOUTÉE/RETIRÉE dynamiquement de DESTINATIONS_EXPLORATION plutôt que codée en dur dedans :
# VueChoixDestinationExploration itère directement sur ce dict, donc l'ajouter ici suffit à
# la faire apparaître comme destination sélectionnable sans toucher au code de l'interface.
# types_affinite couvre TOUTES les vraies valeurs de type utilisées dans ce Pokédex (dont les
# deux graphies fantome/spectre) — n'importe quelle équipe obtient donc le bonus d'affinité,
# aucune restriction de thème pour cet événement exceptionnel.
FAILLE_EXPLORATION = {
    "nom": "Faille Spatio-Temporelle", "emoji": "🌀",
    "types_affinite": [
        "acier", "combat", "dragon", "eau", "electrik", "fantome", "spectre", "fee",
        "feu", "glace", "insecte", "normal", "plante", "poison", "psy", "roche", "sol", "tenebres", "vol",
    ],
    "mult_cristal": 2.2, "mult_oeuf": 1.8, "mult_objet_forme": 2.2,
    "description": "Une brèche instable entre les dimensions — pour une heure seulement, tout y est démultiplié.",
}

# --- Événements aléatoires en cours de route ---
# Réservé aux explorations 6h/24h (une 1h est trop courte pour un "entre-temps"
# crédible) — une chance de déclenchement est tirée UNE FOIS au départ, avec le texte
# ET le bonus déjà décidés à ce moment (voir _tirer_evenement) ; seule la NOTIFICATION
# est différée dans le temps (voir boucle_notifications_completion dans main.py).
CHANCE_EVENEMENT_EXPLORATION = {"1h": 0.0, "6h": 0.35, "24h": 0.6}

EVENEMENTS_EXPLORATION = [
    {"texte": "a croisé un dresseur amical qui leur a indiqué un raccourci !", "bonus_dollars": 60},
    {"texte": "a dû contourner un éboulement, mais s'en est sortie sans encombre.", "bonus_dollars": 0},
    {"texte": "a trouvé un vieux sac abandonné contenant quelques Poké Dollars.", "bonus_dollars": 90},
    {"texte": "s'est arrêtée admirer un coucher de soleil magnifique.", "bonus_dollars": 0},
    {"texte": "a aidé un PNJ local, qui les a remerciés généreusement.", "bonus_dollars": 120},
    {"texte": "a dû rebrousser chemin face à une tempête soudaine, sans dommage.", "bonus_dollars": 0},
]


def _tirer_evenement(duree_label: str, date_debut: int, date_fin: int):
    """Décide, au moment où l'exploration DÉMARRE, si un événement aléatoire aura lieu
    en cours de route — et si oui, lequel et à quel moment. Retourne (planifie_a, texte,
    bonus_dollars) ou (None, None, 0) si aucun événement n'est tiré."""
    if random.random() >= CHANCE_EVENEMENT_EXPLORATION.get(duree_label, 0):
        return None, None, 0
    evenement = random.choice(EVENEMENTS_EXPLORATION)
    # Entre 20% et 80% de la durée totale — jamais pile au début ni juste avant la fin,
    # ça ferait doublon avec le message de départ ou celui de retour.
    fraction = random.uniform(0.2, 0.8)
    planifie_a = round(date_debut + (date_fin - date_debut) * fraction)
    return planifie_a, evenement["texte"], evenement["bonus_dollars"]


def _texte_types_pour_bouton(types_affinite: list) -> str:
    """Texte des types d'affinité à afficher DANS UN LABEL DE BOUTON DISCORD (limite
    stricte de 80 caractères sur le label ENTIER, emoji+nom+parenthèses inclus) — bascule
    sur "Tous types" au-delà de 6 types plutôt que de tous les lister, sinon une
    destination universelle (Faille Spatio-Temporelle, 19 types) fait planter l'envoi du
    message avec une erreur Discord peu claire (400 Bad Request, label trop long). Le
    message qui ACCOMPAGNE le bouton (contenu, pas composant) n'a pas cette limite et
    continue de lister le détail complet ailleurs."""
    if len(types_affinite) > 6:
        return "Tous types"
    return "/".join(t.capitalize() for t in types_affinite)


def _pokemon_correspond_destination(nom: str, destination: str) -> bool:
    """Ce Pokémon précis a-t-il un type correspondant au thème de cette destination ?
    Utilisé à la fois pour le calcul du bonus d'équipe (_a_affinite_type) et pour le
    marquage visuel ✨ individuel pendant la sélection d'équipe."""
    types_theme = DESTINATIONS_EXPLORATION[destination]["types_affinite"]
    pokemon = obtenir_pokemon_par_nom(nom)
    return bool(pokemon and any(t in types_theme for t in pokemon.get("types", [])))


def _a_affinite_type(pokemons: list, destination: str) -> bool:
    """Au moins NB_AFFINITE_REQUIS des Pokémon envoyés ont un type correspondant au
    thème de la destination."""
    nb_correspondants = sum(1 for nom in pokemons if _pokemon_correspond_destination(nom, destination))
    return nb_correspondants >= NB_AFFINITE_REQUIS


def _tirer_objet_forme_aleatoire() -> str:
    """Un objet de transformation au hasard parmi ceux existants (voir formes_objets.py)."""
    return random.choice(list(formes_objets_module.FORMES_OBJETS.keys()))


def construire_embed_centre() -> discord.Embed:
    embed = discord.Embed(
        title="🗺️ Centre des Explorations",
        description=(
            "Envoie une équipe de 3 Pokémon explorer pendant 1h, 6h ou 24h. Plus ton "
            "équipe est puissante, meilleure sera la récompense — Poké Dollars, XP, une "
            f"chance d'obtenir un {EMOJI_CRISTAL} **{NOM_CRISTAL}** (pour retenter ta Mutation), "
            "une chance de trouver un 🥚 **Œuf** à faire éclore au Laboratoire, et (uniquement "
            "sur les explorations 6h/24h) une petite chance de trouver un 💎 **objet de "
            "transformation** rarissime (Orbe Adamant, Fleur Gracidea...).\n\n"
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
        objet_forme = config.EXPLORATION_CHANCE_OBJET_FORME[duree_label]
        valeur = (
            f"{EMOJI_POKEDOLLAR} 0 à {dollars_max} PD\n"
            f"✨ 0 à {xp_max} XP\n"
            f"{EMOJI_CRISTAL} {cristal['base']*100:g}% à {cristal['max']*100:g}%\n"
            f"🥚 {oeuf['base']*100:g}% à {oeuf['max']*100:g}%"
        )
        if objet_forme["max"] > 0:
            valeur += f"\n💎 {objet_forme['base']*100:g}% à {objet_forme['max']*100:g}%"
        embed.add_field(name=f"⏱️ {nom_affiche}", value=valeur, inline=True)
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

    # Emplacement BONUS Faille : affiché SEULEMENT s'il est occupé (une expédition en
    # cours à suivre/récupérer) OU si la Faille est actuellement ouverte (invite à en
    # profiter) — jamais affiché "Libre" en permanence comme les emplacements normaux,
    # ce serait trompeur puisqu'il n'existe QUE pendant l'heure d'ouverture.
    row_faille = explorations.get(config.SLOT_FAILLE_EXPLORATION)
    if row_faille is not None:
        pokemons = [row_faille["pokemon1"], row_faille["pokemon2"], row_faille["pokemon3"]]
        termine = row_faille["date_fin"] <= maintenant
        statut = "✅ Prête à récupérer !" if termine else f"⏳ Retour <t:{row_faille['date_fin']}:R>"
        embed.add_field(
            name="🌀 Emplacement Faille (bonus)",
            value=f"{', '.join(pokemons)}\n{statut}",
            inline=False,
        )
    elif "faille" in DESTINATIONS_EXPLORATION:
        embed.add_field(
            name="🌀 Emplacement Faille (bonus)",
            value="*Libre — la Faille est ouverte, envoie une équipe depuis son message d'annonce !*",
            inline=False,
        )

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

        # Emplacement bonus Faille — mêmes callbacks génériques que les slots normaux
        # (ils fonctionnent pour n'importe quel numéro de slot), juste affiché seulement
        # quand pertinent (voir construire_tableau_de_bord pour la même condition).
        row_faille = explorations.get(config.SLOT_FAILLE_EXPLORATION)
        if row_faille is not None:
            if row_faille["date_fin"] <= maintenant:
                bouton_faille = discord.ui.Button(label="Récupérer (Faille)", emoji="🎁", style=discord.ButtonStyle.primary)
                bouton_faille.callback = self._creer_callback_recuperer(config.SLOT_FAILLE_EXPLORATION)
            else:
                bouton_faille = discord.ui.Button(
                    label="En cours (Faille)", emoji="⏳", style=discord.ButtonStyle.secondary, disabled=True
                )
            self.add_item(bouton_faille)
        elif "faille" in DESTINATIONS_EXPLORATION:
            bouton_faille = discord.ui.Button(label="Envoyer une équipe (Faille)", emoji="🌀", style=discord.ButtonStyle.success)
            bouton_faille.callback = self._creer_callback_envoyer(config.SLOT_FAILLE_EXPLORATION)
            self.add_item(bouton_faille)

    def _creer_callback_envoyer(self, slot: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Ce n'est pas ton tableau de bord !", ephemeral=True)
                return
            # Vérifié ici, AVANT même de proposer une destination — inutile de faire
            # choisir un thème à quelqu'un qui n'a de toute façon aucun Pokémon disponible.
            indisponibles = database.especes_en_exploration(self.user_id) | database.especes_en_caisson(self.user_id)
            stats = _stats_par_espece(self.user_id)
            if not any(nom not in indisponibles for nom in stats):
                await interaction.response.send_message(
                    "Tu n'as aucun Pokémon disponible (déjà tous en exploration, ou aucune capture) !",
                    ephemeral=True,
                )
                return
            vue = VueChoixDestinationExploration(self.user_id, slot)
            lignes_destinations = [
                f"{info['emoji']} **{info['nom']}** ({'/'.join(t.capitalize() for t in info['types_affinite'])}) "
                f"— {info['description']}"
                for info in DESTINATIONS_EXPLORATION.values()
            ]
            await interaction.response.send_message(
                content=(
                    f"🗺️ Choisis d'abord une destination (emplacement {slot}) — les types entre "
                    f"parenthèses donnent le bonus d'affinité si au moins {NB_AFFINITE_REQUIS} de tes "
                    f"3 Pokémon y correspondent :\n\n" + "\n".join(lignes_destinations)
                ),
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
    """Sélection de 3 Pokémon (parmi les espèces disponibles) — la destination est déjà
    choisie à ce stade (voir VueChoixDestinationExploration, désormais la toute première
    étape) : les espèces dont le type correspond au thème sont marquées ✨ pour aider à
    composer une équipe qui débloque le bonus d'affinité, plutôt que de le découvrir
    après coup et devoir tout annuler.

    Paginée par 25 (limite dure d'un menu déroulant Discord) — la sélection est
    conservée d'une page à l'autre, seul l'AFFICHAGE change en changeant de page."""

    TAILLE_PAGE = 25

    def __init__(self, user_id: int, slot: int, destination: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.slot = slot
        self.destination = destination
        self.selection = []
        self.page = 0

        indisponibles = database.especes_en_exploration(user_id) | database.especes_en_caisson(user_id)
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
                label=(
                    f"{'✨ ' if _pokemon_correspond_destination(nom, self.destination) else ''}"
                    f"{nom} ({stats[nom]['pc']} PC)"
                ),
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
        info = DESTINATIONS_EXPLORATION[self.destination]
        texte_affinite = (
            "\n✨ Affinité de type détectée — bonus supplémentaire sur les chances de récompense !"
            if _a_affinite_type(self.selection, self.destination) else ""
        )
        vue = VueChoixDureeExploration(self.user_id, self.slot, self.selection, self.destination)
        await interaction.response.edit_message(
            content=(
                f"Équipe : **{', '.join(self.selection)}**\n"
                f"Destination : {info['emoji']} **{info['nom']}**{texte_affinite}\n\n"
                f"Pour combien de temps ?"
            ),
            view=vue,
        )


class VueAnnonceFaille(discord.ui.View):
    """Bouton PERSISTANT (survit à un redémarrage, voir bot.add_view dans main.py) attaché
    DIRECTEMENT au message d'annonce de la Faille dans le channel Exploration — un SEUL
    message partagé par TOUS les joueurs, contrairement aux vues éphémères habituelles
    (VueTableauDeBord etc.) qui appartiennent à un seul utilisateur. Chaque clic construit
    dynamiquement une VueChoixEquipeExploration pour LA PERSONNE QUI CLIQUE, envoyée en
    réponse éphémère — jamais de state partagé entre joueurs différents.

    Pensé spécifiquement pour les joueurs dont les emplacements normaux (1-2) sont déjà
    occupés par de longues expéditions (6h/24h) : sans ce bouton, ils devraient attendre
    leur retour avant de pouvoir profiter de la fenêtre d'1h de la Faille, ratant
    l'événement entièrement. L'emplacement Faille (config.SLOT_FAILLE_EXPLORATION) est
    un BONUS indépendant des 1-2 emplacements normaux, jamais compté dans nb_slots_exploration."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Envoyer une équipe dans la Faille",
        emoji="🌀",
        style=discord.ButtonStyle.success,
        custom_id="faille_exploration_envoyer_bouton",
    )
    async def envoyer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if "faille" not in DESTINATIONS_EXPLORATION:
            await interaction.response.send_message(
                "❌ La Faille s'est refermée entre-temps — ce message est obsolète.", ephemeral=True
            )
            return

        user_id = interaction.user.id
        explorations_actuelles = {row["slot"]: row for row in database.obtenir_explorations_actives(user_id)}
        if config.SLOT_FAILLE_EXPLORATION in explorations_actuelles:
            await interaction.response.send_message(
                "❌ Tu as déjà envoyé une équipe dans la Faille aujourd'hui — un seul envoi bonus par ouverture "
                "(va au Centre des Explorations, bouton **Gérer mes explorations**, pour suivre ou récupérer cette expédition).",
                ephemeral=True,
            )
            return

        indisponibles = database.especes_en_exploration(user_id) | database.especes_en_caisson(user_id)
        stats = _stats_par_espece(user_id)
        if not any(nom not in indisponibles for nom in stats):
            await interaction.response.send_message(
                "❌ Tu n'as aucun Pokémon disponible (déjà tous en exploration/Caisson, ou aucune capture) !",
                ephemeral=True,
            )
            return

        vue = VueChoixEquipeExploration(user_id, config.SLOT_FAILLE_EXPLORATION, "faille")
        info = DESTINATIONS_EXPLORATION["faille"]
        await interaction.response.send_message(
            content=(
                f"{info['emoji']} **{info['nom']}** (bonus, 1h fixe) — ✨ dans la liste = affinité avec ce thème "
                f"(bonus si au moins {NB_AFFINITE_REQUIS} d'entre eux dans l'équipe, mais ici absolument TOUS "
                f"les types y correspondent).\n\nChoisis {config.EXPLORATION_TAILLE_EQUIPE} Pokémon à envoyer :"
            ),
            view=vue,
            ephemeral=True,
        )


class VueChoixDestinationExploration(discord.ui.View):
    """Première étape désormais : choisis la destination AVANT l'équipe (voir
    VueTableauDeBord._creer_callback_envoyer) — pour savoir quels types visent le bonus
    d'affinité avant même de composer l'équipe, plutôt que de devoir annuler et
    recommencer si l'équipe déjà choisie ne correspondait à aucun thème."""

    def __init__(self, user_id: int, slot: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.slot = slot

        for cle, info in DESTINATIONS_EXPLORATION.items():
            types_texte = _texte_types_pour_bouton(info["types_affinite"])
            bouton = discord.ui.Button(
                label=f"{info['nom']} ({types_texte})", emoji=info["emoji"], style=discord.ButtonStyle.primary
            )
            bouton.callback = self._creer_callback(cle)
            self.add_item(bouton)

    def _creer_callback(self, destination: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Ce n'est pas ta sélection !", ephemeral=True)
                return
            info = DESTINATIONS_EXPLORATION[destination]
            types_texte = "/".join(t.capitalize() for t in info["types_affinite"])
            vue = VueChoixEquipeExploration(self.user_id, self.slot, destination)
            await interaction.response.edit_message(
                content=(
                    f"Destination : {info['emoji']} **{info['nom']}** ({types_texte})\n"
                    f"✨ dans la liste = ce Pokémon a une affinité avec ce thème (bonus si au moins "
                    f"{NB_AFFINITE_REQUIS} d'entre eux dans l'équipe)\n\n"
                    f"Choisis {config.EXPLORATION_TAILLE_EQUIPE} Pokémon à envoyer explorer :"
                ),
                view=vue,
            )
        return callback


class VueChoixDureeExploration(discord.ui.View):
    def __init__(self, user_id: int, slot: int, pokemons: list, destination: str = None):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.slot = slot
        self.pokemons = pokemons
        self.destination = destination

        # La Faille Spatio-Temporelle ne dure qu'1h — proposer 6h/24h dessus ferait
        # perdre tout le bonus au moment de la récompense (le multiplicateur se relit
        # sur DESTINATIONS_EXPLORATION AU MOMENT DE LA RÉCUPÉRATION, or la clé "faille"
        # disparaît du dict dès que l'événement se referme). Une seule option, forcée.
        durees_proposees = ("1h",) if destination == "faille" else ("1h", "6h", "24h")
        for duree_label in durees_proposees:
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
            indisponibles = database.especes_en_exploration(self.user_id) | database.especes_en_caisson(self.user_id)
            if any(p in indisponibles for p in self.pokemons):
                await interaction.response.edit_message(
                    content="❌ Un des Pokémon choisis est déjà parti en exploration ou au Caisson de Croissance entre-temps.",
                    view=None,
                )
                return

            duree_secondes = config.EXPLORATION_DUREES[duree_label]
            date_debut = int(time.time())
            date_fin = date_debut + duree_secondes
            planifie_a, texte_evenement, bonus_dollars = _tirer_evenement(duree_label, date_debut, date_fin)
            database.demarrer_exploration(
                self.user_id, self.slot, self.pokemons, duree_secondes, duree_label,
                destination=self.destination, evenement_planifie_a=planifie_a,
                evenement_texte=texte_evenement, evenement_bonus_dollars=bonus_dollars,
            )

            texte_destination = ""
            if self.destination:
                info = DESTINATIONS_EXPLORATION[self.destination]
                texte_destination = f" vers {info['emoji']} **{info['nom']}**"

            await interaction.response.edit_message(
                content=(
                    f"🚀 **{', '.join(self.pokemons)}** partent explorer{texte_destination} pour **{duree_label}** !\n"
                    f"Retour <t:{date_fin}:R>."
                ),
                view=None,
            )
        return callback


def _calculer_recompense(user_id: int, pc_total: int, duree_label: str, destination: str = None, pokemons: list = None) -> dict:
    """destination/pokemons optionnels — None pour une exploration démarrée AVANT
    l'ajout des destinations thématiques, comportement inchangé dans ce cas (aucun
    biais, comme avant)."""
    pc_plafonne = min(pc_total, config.EXPLORATION_PLAFOND_PC)
    xp = round(pc_plafonne * config.EXPLORATION_FACTEUR_XP[duree_label])

    # Bonus "Chance" (Mutation de dresseur, voir races.py) : appliqué APRÈS les plafonds
    # normaux — laisse volontairement la Mutation dépasser ce plafond habituel (c'est
    # tout l'intérêt d'un vrai bonus de chance), avec un plafond ABSOLU de sécurité à
    # 95% pour ne jamais atteindre une certitude totale.
    mult_chance = database.multiplicateur_boost(user_id, "chance")
    PLAFOND_ABSOLU_CHANCE = 0.95

    # Faille Spatio-Temporelle : récompenses FIXES (voir config.FAILLE_*), pas la grille
    # normale par durée — court-circuite tout le calcul habituel ci-dessous, seul le
    # bonus "Chance" continue de s'appliquer par-dessus (même plafond de sécurité).
    if destination == "faille":
        return {
            "dollars": config.FAILLE_RECOMPENSE_DOLLARS, "xp": xp,
            "chance_cristal": min(PLAFOND_ABSOLU_CHANCE, config.FAILLE_CHANCE_CRISTAL * mult_chance),
            "chance_oeuf": min(PLAFOND_ABSOLU_CHANCE, config.FAILLE_CHANCE_OEUF * mult_chance),
            "chance_objet_forme": min(PLAFOND_ABSOLU_CHANCE, config.FAILLE_CHANCE_OBJET_FORME * mult_chance),
            "a_affinite": True,  # la Faille couvre tous les types, toujours vrai par construction
        }

    dollars = round(pc_plafonne * config.EXPLORATION_FACTEUR_DOLLARS[duree_label])
    ratio_puissance = pc_plafonne / config.EXPLORATION_PLAFOND_PC

    dest_info = DESTINATIONS_EXPLORATION.get(destination) if destination else None
    a_affinite = bool(dest_info and pokemons and _a_affinite_type(pokemons, destination))
    mult_affinite = BONUS_AFFINITE_TYPE if a_affinite else 1.0

    conf_cristal = config.EXPLORATION_CHANCE_CRISTAL[duree_label]
    chance_cristal = conf_cristal["base"] + conf_cristal["bonus_max"] * ratio_puissance
    if dest_info:
        chance_cristal *= dest_info["mult_cristal"] * mult_affinite
    chance_cristal = min(conf_cristal["max"], chance_cristal)
    chance_cristal = min(PLAFOND_ABSOLU_CHANCE, chance_cristal * mult_chance)

    conf_oeuf = config.EXPLORATION_CHANCE_OEUF[duree_label]
    chance_oeuf = conf_oeuf["base"] + conf_oeuf["bonus_max"] * ratio_puissance
    if dest_info:
        chance_oeuf *= dest_info["mult_oeuf"] * mult_affinite
    chance_oeuf = min(conf_oeuf["max"], chance_oeuf)
    chance_oeuf = min(PLAFOND_ABSOLU_CHANCE, chance_oeuf * mult_chance)

    conf_objet_forme = config.EXPLORATION_CHANCE_OBJET_FORME[duree_label]
    chance_objet_forme = conf_objet_forme["base"] + conf_objet_forme["bonus_max"] * ratio_puissance
    if dest_info:
        chance_objet_forme *= dest_info["mult_objet_forme"] * mult_affinite
    chance_objet_forme = min(conf_objet_forme["max"], chance_objet_forme)
    chance_objet_forme = min(PLAFOND_ABSOLU_CHANCE, chance_objet_forme * mult_chance)

    return {
        "dollars": dollars, "xp": xp, "chance_cristal": chance_cristal, "chance_oeuf": chance_oeuf,
        "chance_objet_forme": chance_objet_forme, "a_affinite": a_affinite,
    }


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
    total_objets_forme = []
    lignes_details = []
    toutes_quetes_completees = []
    toutes_montees_niveau = []

    for row in explorations:
        pokemons = [row["pokemon1"], row["pokemon2"], row["pokemon3"]]
        duree_label = row["duree_label"] or _retrouver_duree_label(row["date_fin"] - row["date_debut"])
        destination = row["destination"]

        stats = _stats_par_espece(user_id)
        pc_total = sum(stats.get(nom, {}).get("pc", 0) for nom in pokemons)
        recompense = _calculer_recompense(user_id, pc_total, duree_label, destination, pokemons)

        mult_repetition = database.enregistrer_completion_exploration_repetition(user_id)
        bonus_evenement = row["evenement_bonus_dollars"] or 0
        dollars = (
            round(recompense["dollars"] * mult_repetition * database.multiplicateur_boost(user_id, "argent"))
            + bonus_evenement
        )
        database.ajouter_poke_dollars(user_id, dollars)
        leveling.gagner_xp(user_id, recompense["xp"])
        # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
        # applique son propre multiplicateur en interne, on le reproduit ici pour le texte.
        xp_affichee = round(recompense["xp"] * database.multiplicateur_boost(user_id, "xp"))

        # XP du niveau PAR Pokémon : uniquement les 3 Pokémon envoyés sur CETTE
        # exploration précise (pas forcément l'équipe de combat), indépendamment de l'XP
        # de dresseur ci-dessus — même montant, comme pour une capture/PokéStop.
        toutes_montees_niveau.extend(niveaux_pokemon.gagner_xp_equipe(user_id, recompense["xp"], noms=pokemons))

        obtenu_cristal = random.random() < recompense["chance_cristal"]
        if obtenu_cristal:
            database.ajouter_balls(user_id, "cristal_mutation", 1)
            total_cristaux += 1

        if random.random() < recompense["chance_oeuf"]:
            palier_oeuf = _tirer_palier_oeuf()
            database.ajouter_balls(user_id, f"oeuf_{palier_oeuf}", 1)
            total_oeufs.append(palier_oeuf)

        if random.random() < recompense["chance_objet_forme"]:
            objet_forme = _tirer_objet_forme_aleatoire()
            database.ajouter_balls(user_id, objet_forme, 1)
            total_objets_forme.append(objet_forme)

        database.terminer_exploration(user_id, row["slot"])
        database.incrementer_explorations_terminees(user_id)
        quetes_completees = database.incrementer_progression_quete(user_id, "exploration_collectee")
        toutes_quetes_completees.extend(q for q in quetes_completees if q["id"] not in {t["id"] for t in toutes_quetes_completees})

        total_dollars += dollars
        total_xp += xp_affichee
        cristal_txt = f" + {EMOJI_CRISTAL}" if obtenu_cristal else ""
        emoji_dest = DESTINATIONS_EXPLORATION[destination]["emoji"] + " " if destination in DESTINATIONS_EXPLORATION else ""
        lignes_details.append(f"• {emoji_dest}Emplacement {row['slot']} ({', '.join(pokemons)}){cristal_txt}")
        if row["evenement_texte"]:
            lignes_details.append(f"  💬 En chemin, ton équipe {row['evenement_texte']}")

    description = (
        "\n".join(lignes_details)
        + f"\n\n{EMOJI_POKEDOLLAR} **+{total_dollars}** Poké Dollars\n"
        f"✨ **+{total_xp}** XP"
    )
    if total_cristaux:
        description += f"\n{EMOJI_CRISTAL} **+{total_cristaux}** {NOM_CRISTAL}(s) !"
    for palier_oeuf in total_oeufs:
        description += f"\n{EMOJI_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']} **+1** {NOM_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']} !"
    for objet_forme in total_objets_forme:
        info = formes_objets_module.FORMES_OBJETS[objet_forme]
        description += f"\n{info['objet_emoji']} **+1** {info['objet_nom']} — objet rarissime ! ({info['espece']} uniquement)"
    if toutes_montees_niveau:
        description += "\n\n" + niveaux_pokemon.texte_montees_niveau(toutes_montees_niveau)
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
    destination = row["destination"]  # None pour une exploration démarrée avant cet ajout

    stats = _stats_par_espece(user_id)
    pc_total = sum(stats.get(nom, {}).get("pc", 0) for nom in pokemons)

    recompense = _calculer_recompense(user_id, pc_total, duree_label, destination, pokemons)

    mult_repetition = database.enregistrer_completion_exploration_repetition(user_id)
    bonus_evenement = row["evenement_bonus_dollars"] or 0
    dollars = round(recompense["dollars"] * mult_repetition * database.multiplicateur_boost(user_id, "argent")) + bonus_evenement
    database.ajouter_poke_dollars(user_id, dollars)
    leveling.gagner_xp(user_id, recompense["xp"])
    # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
    # applique son propre multiplicateur en interne, on le reproduit ici pour le texte.
    xp_affichee = round(recompense["xp"] * database.multiplicateur_boost(user_id, "xp"))

    # XP du niveau PAR Pokémon : uniquement les 3 Pokémon envoyés sur cette exploration.
    montees_niveau = niveaux_pokemon.gagner_xp_equipe(user_id, recompense["xp"], noms=pokemons)

    obtenu_cristal = random.random() < recompense["chance_cristal"]
    if obtenu_cristal:
        database.ajouter_balls(user_id, "cristal_mutation", 1)

    palier_oeuf = None
    if random.random() < recompense["chance_oeuf"]:
        palier_oeuf = _tirer_palier_oeuf()
        database.ajouter_balls(user_id, f"oeuf_{palier_oeuf}", 1)

    objet_forme_obtenu = None
    if random.random() < recompense["chance_objet_forme"]:
        objet_forme_obtenu = _tirer_objet_forme_aleatoire()
        database.ajouter_balls(user_id, objet_forme_obtenu, 1)

    database.terminer_exploration(user_id, slot)
    database.incrementer_explorations_terminees(user_id)
    quetes_completees = database.incrementer_progression_quete(user_id, "exploration_collectee")

    description = f"**{', '.join(pokemons)}** reviennent d'exploration"
    if destination and destination in DESTINATIONS_EXPLORATION:
        info_dest = DESTINATIONS_EXPLORATION[destination]
        description += f" de {info_dest['emoji']} **{info_dest['nom']}**"
    description += " !\n"
    if row["evenement_texte"]:
        description += f"\n💬 En chemin, ton équipe {row['evenement_texte']}\n"
    if recompense.get("a_affinite"):
        description += "\n✨ Affinité de type avec la destination — récompenses boostées !\n"
    description += (
        f"\n{EMOJI_POKEDOLLAR} +{dollars} Poké Dollars\n"
        f"✨ +{xp_affichee} XP"
    )
    if obtenu_cristal:
        description += f"\n{EMOJI_CRISTAL} +1 **{NOM_CRISTAL}** !"
    if palier_oeuf:
        description += f"\n{EMOJI_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']} +1 **{NOM_OBJETS_DIVERS[f'oeuf_{palier_oeuf}']}** !"
    if objet_forme_obtenu:
        info = formes_objets_module.FORMES_OBJETS[objet_forme_obtenu]
        description += f"\n{info['objet_emoji']} +1 **{info['objet_nom']}** — objet rarissime ! ({info['espece']} uniquement)"
    if montees_niveau:
        description += "\n\n" + niveaux_pokemon.texte_montees_niveau(montees_niveau)
    description += quetes_ui.texte_notifications_completion(quetes_completees)

    return discord.Embed(title="🎁 Retour d'exploration", description=description, color=discord.Color.gold())


def _retrouver_duree_label(duree_secondes: int) -> str:
    """Retrouve le label de durée (1h/6h/24h) le plus proche de la durée effective stockée."""
    ecarts = {label: abs(duree_secondes - s) for label, s in config.EXPLORATION_DUREES.items()}
    return min(ecarts, key=ecarts.get)
