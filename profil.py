import io

import aiohttp
import discord
from PIL import Image

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
    emoji_pour_objet,
)


def url_avatar_fiable(user: discord.abc.User) -> str:
    """URL d'avatar à utiliser dans un embed (thumbnail/author icon).

    Bug de plateforme Discord documenté (github.com/discord/discord-api-docs/issues/467) :
    un avatar GIF animé ne s'anime pas — et dans les faits ne se charge souvent pas du
    tout dans un embed — si l'URL comporte un paramètre après l'extension .gif (le
    ?size=... que discord.py ajoute systématiquement). L'URL doit se terminer
    littéralement par ".gif" pour que Discord le traite correctement. On retire donc le
    paramètre de taille uniquement pour les avatars animés (une baisse de taille demandée
    ne suffisait pas — la vraie cause est la présence même du paramètre, pas sa valeur).
    Les avatars statiques ne sont pas concernés."""
    avatar = user.display_avatar
    url = avatar.url
    if avatar.is_animated() and "?" in url:
        url = url.split("?", 1)[0]
    return url


async def fichier_avatar_fiable(user: discord.abc.User, taille: int = 256) -> discord.File | None:
    """Version "impossible à rater" de url_avatar_fiable : télécharge l'avatar (animé ou
    non) et le convertit nous-mêmes en PNG STATIQUE, attaché au message plutôt que
    référencé par une URL Discord — plus aucune dépendance au comportement (parfois
    capricieux, voir url_avatar_fiable) du client Discord pour charger un GIF en embed.
    Coût assumé (demandé explicitement) : plus jamais animé, même pour un GIF.
    Retourne None si le téléchargement échoue (l'appelant doit alors se rabattre sur
    url_avatar_fiable() comme filet de sécurité)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(user.display_avatar.url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img.thumbnail((taille, taille), Image.LANCZOS)
        tampon = io.BytesIO()
        img.save(tampon, format="PNG")
        tampon.seek(0)
        return discord.File(tampon, filename="avatar.png")
    except Exception:
        return None


async def construire_embed_profil(user: discord.abc.User, autoriser_piece_jointe: bool = True) -> tuple:
    """Construit la carte de profil complète d'un joueur (réutilisée par /profil et le bouton du channel).
    Retourne (embed, fichier) — fichier (peut être None) doit être joint au message
    (files=[fichier] pour un envoi) si présent ; l'embed y fait référence via
    "attachment://avatar.png".

    autoriser_piece_jointe=False : à utiliser pour tout message ÉPHÉMÈRE — Discord a un
    bug confirmé (github.com/discord/discord-api-docs/issues/3842) où une image jointe via
    "attachment://" ne s'affiche JAMAIS dans un message éphémère. Dans ce cas, on retombe
    directement sur l'URL fiable (sans télécharger de fichier pour rien) ; l'avatar animé
    peut alors ne pas s'afficher (limite de Discord, acceptée pour ce contexte)."""
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
    # Avatar converti en PNG statique et joint au message (voir fichier_avatar_fiable) —
    # garantit l'affichage même pour les avatars GIF animés, au prix de l'animation.
    # Uniquement pour les messages PUBLICS (voir autoriser_piece_jointe ci-dessus) : un
    # message éphémère n'affichera jamais cette pièce jointe, autant ne pas la télécharger.
    fichier_avatar = await fichier_avatar_fiable(user) if autoriser_piece_jointe else None
    if fichier_avatar:
        embed.set_thumbnail(url="attachment://avatar.png")
    else:
        embed.set_thumbnail(url=url_avatar_fiable(user))

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
        return "\n".join(f"{emoji_pour_objet(k, emojis.get(k, ''))} {noms.get(k, k)} ×{v}" for k, v in dico.items()) or "—"

    embed.add_field(name="Balls", value=_ligne(balls, NOM_BALL_AFFICHAGE, EMOJI_BALLS), inline=True)
    embed.add_field(name="Soins", value=_ligne(soins, NOM_SOIN_AFFICHAGE, EMOJI_SOINS), inline=True)
    if divers:
        embed.add_field(name="Divers", value=_ligne(divers, NOM_OBJETS_DIVERS, EMOJI_OBJETS_DIVERS), inline=True)

    embed.set_footer(text="💡 /pokedex • /exploration • /ma-race • /equipe-combat")
    return embed, fichier_avatar


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


# ----------------------------------------------------------------------------
# Verrouillage de doublons — protège un exemplaire précis du relâcher automatique
# (/relacher) sans avoir à le décocher manuellement à chaque fois. Une fois verrouillé,
# une capture n'apparaît plus JAMAIS dans les listes de doublons proposées au relâcher,
# même si ce n'est pas le meilleur PC de son espèce (voir database.py).
# ----------------------------------------------------------------------------

CAPTURES_PAR_PAGE_VERROU = 25
OPTIONS_TRI_VERROU = [
    ("alphabetique", "Alphabétique"),
    ("pc_desc", "PC : fort → faible"),
    ("verrouilles_dabord", "Verrouillés d'abord"),
]


def construire_embed_verrouillage(user_id: int) -> discord.Embed:
    nb_verrouilles = len(database.obtenir_captures_verrouillees(user_id))
    embed = discord.Embed(
        title="🔒 Verrouillage de doublons",
        description=(
            "Coche les exemplaires à **verrouiller** — ils ne seront plus jamais proposés "
            "par `/relacher` (doublons), même si ce n'est pas ton meilleur PC de "
            "l'espèce. Reclique sur un exemplaire déjà coché pour le déverrouiller.\n\n"
            f"🔒 **{nb_verrouilles}** exemplaire(s) actuellement verrouillé(s)."
        ),
        color=discord.Color.dark_teal(),
    )
    return embed


class VueVerrouillage(discord.ui.View):
    """Sélection paginée/triable/cherchable de TOUTE la collection — cocher un exemplaire
    le verrouille, le décocher le déverrouille (appliqué immédiatement à chaque clic,
    pas besoin d'un bouton de confirmation séparé)."""

    def __init__(self, user_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.page = page
        self.tri = "alphabetique"
        self.recherche = None
        self.doublons_uniquement = True  # actif par défaut : c'est ce qu'on vient verrouiller la plupart du temps
        self.toutes_captures = database.obtenir_toutes_captures_detaillees(user_id)
        self._trier_captures()
        self._construire_composants()

    def _captures_affichees(self) -> list:
        captures = self.toutes_captures
        if self.doublons_uniquement:
            captures = [row for row in captures if row["rang"] > 1]
        if self.recherche:
            terme = cle_tri_alphabetique_fr(self.recherche)
            captures = [row for row in captures if terme in cle_tri_alphabetique_fr(row["pokemon_nom"])]
        return captures

    def _trier_captures(self):
        if self.tri == "pc_desc":
            self.toutes_captures.sort(key=lambda row: -row["pc"])
        elif self.tri == "verrouilles_dabord":
            self.toutes_captures.sort(key=lambda row: (not row["verrouille"], cle_tri_alphabetique_fr(row["pokemon_nom"])))
        else:
            self.toutes_captures.sort(key=lambda row: cle_tri_alphabetique_fr(row["pokemon_nom"]))

    def _construire_composants(self):
        self.clear_items()
        captures_affichees = self._captures_affichees()
        debut = self.page * CAPTURES_PAR_PAGE_VERROU
        page_captures = captures_affichees[debut : debut + CAPTURES_PAR_PAGE_VERROU]

        options = []
        for row in page_captures:
            shiny_txt = " ✨" if row["shiny"] else ""
            prefixe = "🔒 " if row["verrouille"] else ""
            options.append(
                discord.SelectOption(
                    label=f"{prefixe}{row['pokemon_nom']}{shiny_txt} — {row['pc']} PC"[:100],
                    value=str(row["id"]),
                )
            )
        if options:
            select = discord.ui.Select(placeholder="Coche pour verrouiller / décoche pour déverrouiller…", options=options, min_values=0, max_values=len(options), row=0)
            select.callback = self._on_select
            self.add_item(select)

        select_tri = discord.ui.Select(
            placeholder="Trier par...",
            options=[discord.SelectOption(label=libelle, value=valeur, default=(valeur == self.tri)) for valeur, libelle in OPTIONS_TRI_VERROU],
            row=1,
        )
        select_tri.callback = self._on_select_tri
        self.add_item(select_tri)

        nb_pages = max(1, (len(captures_affichees) + CAPTURES_PAR_PAGE_VERROU - 1) // CAPTURES_PAR_PAGE_VERROU)
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

        bouton_filtre = discord.ui.Button(
            label="Doublons uniquement" if self.doublons_uniquement else "Tout afficher",
            emoji="🔁",
            style=discord.ButtonStyle.success if self.doublons_uniquement else discord.ButtonStyle.secondary,
            row=3,
        )
        bouton_filtre.callback = self._on_basculer_filtre
        self.add_item(bouton_filtre)

    async def _rafraichir(self, interaction: discord.Interaction):
        self.toutes_captures = database.obtenir_toutes_captures_detaillees(self.user_id)
        self._trier_captures()
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_verrouillage(self.user_id), view=self)

    async def _on_select(self, interaction: discord.Interaction):
        ids_coches = {int(v) for v in interaction.data["values"]}
        captures_affichees = self._captures_affichees()
        debut = self.page * CAPTURES_PAR_PAGE_VERROU
        page_captures = captures_affichees[debut : debut + CAPTURES_PAR_PAGE_VERROU]

        for row in page_captures:
            nouvel_etat = row["id"] in ids_coches
            if bool(row["verrouille"]) != nouvel_etat:
                database.definir_verrouillage_capture(row["id"], nouvel_etat)

        await self._rafraichir(interaction)

    async def _on_select_tri(self, interaction: discord.Interaction):
        self.tri = interaction.data["values"][0]
        self.page = 0
        await self._rafraichir(interaction)

    async def _page_prec(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _page_suiv(self, interaction: discord.Interaction):
        self.page += 1
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_rechercher(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ModalRechercheVerrouillage(self))

    async def _on_effacer_recherche(self, interaction: discord.Interaction):
        self.recherche = None
        self.page = 0
        await self._rafraichir(interaction)

    async def _on_basculer_filtre(self, interaction: discord.Interaction):
        self.doublons_uniquement = not self.doublons_uniquement
        self.page = 0
        await self._rafraichir(interaction)


class ModalRechercheVerrouillage(discord.ui.Modal, title="Rechercher un Pokémon"):
    recherche_input = discord.ui.TextInput(label="Nom (ou partie du nom)", placeholder="Ex : Rat", required=False)

    def __init__(self, vue_parente: VueVerrouillage):
        super().__init__()
        self.vue_parente = vue_parente
        self.recherche_input.default = vue_parente.recherche or ""

    async def on_submit(self, interaction: discord.Interaction):
        terme = self.recherche_input.value.strip()
        self.vue_parente.recherche = terme or None
        self.vue_parente.page = 0
        self.vue_parente._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_verrouillage(self.vue_parente.user_id), view=self.vue_parente)


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

# ----------------------------------------------------------------------------
# Tableau de bord de clan — équipe actuelle, rang de contribution, objectif
# hebdomadaire (coopératif au sein de l'équipe, compétitif entre les 3), historique
# des saisons passées. Le changement d'équipe (VueChoixClan, juste après) reste
# accessible en un clic depuis ici.
# ----------------------------------------------------------------------------

def _titre_contribution(points: int) -> tuple:
    """(emoji, titre) du palier de contribution atteint — voir config.TITRES_CONTRIBUTION_CLAN."""
    titre_actuel = config.TITRES_CONTRIBUTION_CLAN[0]
    for seuil, nom, emoji in config.TITRES_CONTRIBUTION_CLAN:
        if points >= seuil:
            titre_actuel = (seuil, nom, emoji)
    return titre_actuel[2], titre_actuel[1]


def _barre_objectif(progres: int, cible: int, longueur: int = 10) -> str:
    ratio = max(0.0, min(1.0, progres / cible)) if cible else 0
    rempli = round(longueur * ratio)
    return "🟩" * rempli + "⬛" * (longueur - rempli)


def construire_embed_tableau_bord_clan(user_id: int) -> discord.Embed:
    equipe_actuelle, peut_changer, secondes_restantes = database.obtenir_statut_equipe(user_id)

    embed = discord.Embed(title="🛡️ Clan", color=discord.Color.dark_teal())

    if not equipe_actuelle:
        embed.description = (
            "Tu n'as pas encore choisi de clan ! Clique sur **Changer d'équipe** "
            "ci-dessous pour rejoindre Bleu, Rouge ou Jaune."
        )
        return embed

    emoji_equipe = config.EMOJI_EQUIPES.get(equipe_actuelle, "")
    contribution = database.obtenir_contribution_clan(user_id)
    emoji_titre, nom_titre = _titre_contribution(contribution)

    embed.description = (
        f"Tu es dans le clan {emoji_equipe} **{equipe_actuelle}**.\n"
        f"{emoji_titre} **{nom_titre}** — {contribution} points de contribution"
    )

    objectif = database.obtenir_objectif_semaine_actif()
    tous_progres = database.obtenir_tous_progres_objectif(objectif["id"])
    label_type = "Captures" if objectif["type"] == "capture" else "Combats gagnés"

    lignes_objectif = []
    for nom_equipe in ("Bleu", "Rouge", "Jaune"):
        p = tous_progres.get(nom_equipe, {"progres": 0, "complete_le": None})
        marqueur = " ✅" if p["complete_le"] else ""
        lignes_objectif.append(
            f"{config.EMOJI_EQUIPES.get(nom_equipe, '')} **{nom_equipe}** "
            f"{_barre_objectif(p['progres'], objectif['cible'])} "
            f"{min(p['progres'], objectif['cible'])}/{objectif['cible']}{marqueur}"
        )

    embed.add_field(
        name=f"🎯 Objectif de la semaine : {label_type}",
        value=(
            "\n".join(lignes_objectif)
            + f"\n\n💰 {config.CLAN_OBJECTIF_RECOMPENSE_BASE} PD par membre à l'équipe qui l'atteint "
            f"(+{config.CLAN_OBJECTIF_BONUS_PREMIER} PD bonus pour la 1ère des 3)."
        ),
        inline=False,
    )

    if not peut_changer:
        jours = secondes_restantes // 86400
        heures = (secondes_restantes % 86400) // 3600
        embed.set_footer(text=f"Prochain changement de clan gratuit possible dans {jours}j {heures}h.")
    else:
        embed.set_footer(text="Tu peux changer de clan gratuitement dès maintenant si tu le souhaites.")

    return embed


class VueTableauBordClan(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="Changer d'équipe", emoji="🔁", style=discord.ButtonStyle.primary)
    async def changer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton tableau de bord !", ephemeral=True)
            return
        vue = VueChoixClan(self.user_id)
        await interaction.response.send_message(
            "Choisis ton clan (1 changement gratuit par semaine) :", view=vue, ephemeral=True
        )

    @discord.ui.button(label="Historique des saisons", emoji="📜", style=discord.ButtonStyle.secondary)
    async def historique(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton tableau de bord !", ephemeral=True)
            return

        saisons = database.obtenir_historique_saisons_clan()
        if not saisons:
            await interaction.response.send_message(
                "Aucune saison archivée pour l'instant — la toute première sera enregistrée à la fin de ce mois-ci.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📜 Historique des saisons de clan", color=discord.Color.dark_gold())
        medailles = ["🥇", "🥈", "🥉"]
        for saison, classement in saisons:
            lignes = [
                f"{medailles[rang - 1] if rang <= 3 else f'{rang}.'} {config.EMOJI_EQUIPES.get(equipe, '')} "
                f"**{equipe}** — {score} PC cumulés"
                for equipe, rang, score in classement
            ]
            embed.add_field(name=saison, value="\n".join(lignes) or "—", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


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
                    ancien_role = interaction.guild.get_role(config.ROLES_EQUIPES_ID.get(ancienne_equipe))
                    if ancien_role is not None:
                        await interaction.user.remove_roles(ancien_role, reason="Changement de clan")

                nouveau_role = interaction.guild.get_role(config.ROLES_EQUIPES_ID.get(nom_equipe))
                if nouveau_role is None:
                    # L'ID configuré ne correspond à aucun rôle existant sur CE serveur
                    # (mauvais ID, ou rôle supprimé depuis) — on ne recrée JAMAIS un rôle à
                    # la volée pour un clan (contrairement à avant) : ces 3 rôles sont
                    # censés être gérés à la main par un admin, un doublon créé
                    # automatiquement ferait plus de mal que de bien. On prévient juste
                    # le joueur que la couleur n'a pas pu être appliquée.
                    message += (
                        f"\n⚠️ Le rôle Discord du clan **{nom_equipe}** est introuvable "
                        f"(ID mal configuré, ou rôle supprimé) — demande à un admin de "
                        f"vérifier `config.ROLES_EQUIPES_ID`."
                    )
                else:
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
        embed = construire_embed_tableau_bord_clan(interaction.user.id)
        vue = VueTableauBordClan(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


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
        # Reste éphémère (demandé) — Discord n'affiche jamais une image jointe via
        # "attachment://" dans un message éphémère (voir construire_embed_profil), donc
        # on ne tente pas la conversion PNG ici : l'avatar retombe sur l'ancienne méthode
        # (URL directe), avec le comportement d'avant pour les pp animées.
        embed, _ = await construire_embed_profil(interaction.user, autoriser_piece_jointe=False)
        await interaction.response.send_message(embed=embed, view=VueOuvrirPokedex(), ephemeral=True)
