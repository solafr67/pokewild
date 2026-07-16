import asyncio
import io

import discord

import database
import journal
from pokedex import ORDRE_RARETE
from pokemon_data import EMOJI_POKEDOLLAR, cle_tri_alphabetique_fr, obtenir_pokemon_par_nom, sprite_pokemon

CAPTURES_PAR_PAGE = 25
DELAI_SUPPRESSION_FIL = 120
MAX_CARTES_PAR_JOUEUR = 2  # aperçu rapide dans le message principal — le reste est dans la galerie paginée

OPTIONS_TRI = [
    ("alphabetique", "Alphabétique"),
    ("rarete", "Rareté"),
    ("pc_desc", "PC : fort → faible"),
    ("pc_asc", "PC : faible → fort"),
]


def _ligne_offre(captures: list, pd: int) -> str:
    if not captures and pd == 0:
        return "*Rien proposé pour l'instant*"
    lignes = []
    for row in captures[:15]:
        shiny_txt = " ✨" if row["shiny"] else ""
        lignes.append(f"• {row['pokemon_nom']}{shiny_txt} ({row['pc']} PC)")
    if len(captures) > 15:
        lignes.append(f"*... et {len(captures) - 15} autre(s)*")
    if pd > 0:
        lignes.append(f"{EMOJI_POKEDOLLAR} {pd} Poké Dollars")
    return "\n".join(lignes) if lignes else "*Rien proposé pour l'instant*"


def _cartes_pokemon(captures: list) -> list:
    """Une mini-carte par Pokémon proposé : sprite animé en vignette, PC dans le titre.
    Plafonné à MAX_CARTES_PAR_JOUEUR pour rester sous la limite Discord de 10 embeds/message."""
    cartes = []
    for row in captures[:MAX_CARTES_PAR_JOUEUR]:
        pokemon = obtenir_pokemon_par_nom(row["pokemon_nom"])
        shiny_txt = "✨ " if row["shiny"] else ""
        carte = discord.Embed(
            title=f"{shiny_txt}{row['pokemon_nom']} — {row['pc']} PC",
            color=discord.Color.gold() if row["shiny"] else discord.Color.blurple(),
        )
        if pokemon:
            sprite_url = sprite_pokemon(pokemon, shiny=bool(row["shiny"]))
            if sprite_url:
                carte.set_thumbnail(url=sprite_url)
        cartes.append(carte)
    if len(captures) > MAX_CARTES_PAR_JOUEUR:
        carte_reste = discord.Embed(
            description=(
                f"*+ {len(captures) - MAX_CARTES_PAR_JOUEUR} autre(s) Pokémon proposé(s) — "
                f"clique sur \"🖼️ Voir toutes les cartes\" pour tout voir avec sprites.*"
            ),
            color=discord.Color.blurple(),
        )
        cartes.append(carte_reste)
    return cartes


def construire_embeds_echange(echange_id: int, noms: dict) -> list:
    """Retourne une LISTE d'embeds : le résumé principal, puis une mini-carte visuelle
    (sprite + PC) par Pokémon proposé de chaque côté."""
    echange = database.obtenir_echange(echange_id)
    if echange is None:
        return [discord.Embed(description="Échange introuvable.", color=discord.Color.red())]

    offre_j1 = database.obtenir_offre_echange(echange_id, echange["joueur1_id"])
    offre_j2 = database.obtenir_offre_echange(echange_id, echange["joueur2_id"])

    embed = discord.Embed(title="🔄 Échange en cours", color=discord.Color.blurple())

    statut_j1 = "✅ Offre validée" if echange["joueur1_valide"] else "⏳ En cours de construction..."
    statut_j2 = "✅ Offre validée" if echange["joueur2_valide"] else "⏳ En cours de construction..."

    embed.add_field(
        name=f"{noms.get(echange['joueur1_id'], 'Joueur 1')} — {statut_j1}",
        value=_ligne_offre(offre_j1, echange["joueur1_pd"]),
        inline=True,
    )
    embed.add_field(
        name=f"{noms.get(echange['joueur2_id'], 'Joueur 2')} — {statut_j2}",
        value=_ligne_offre(offre_j2, echange["joueur2_pd"]),
        inline=True,
    )
    embed.set_footer(text="Modifier son offre annule les deux validations — il faut revalider après tout changement.")

    return [embed, *_cartes_pokemon(offre_j1), *_cartes_pokemon(offre_j2)]


class VueEchange(discord.ui.View):
    """Vue partagée dans le fil : chaque joueur gère sa propre offre via ces boutons."""

    def __init__(self, echange_id: int):
        super().__init__(timeout=None)
        self.echange_id = echange_id

    async def _verifier_participant(self, interaction: discord.Interaction) -> bool:
        echange = database.obtenir_echange(self.echange_id)
        if not echange or not echange["actif"]:
            await interaction.response.send_message("Cet échange est terminé.", ephemeral=True)
            return False
        if interaction.user.id not in (echange["joueur1_id"], echange["joueur2_id"]):
            await interaction.response.send_message("Tu ne fais pas partie de cet échange !", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Modifier mon offre", emoji="🎁", style=discord.ButtonStyle.primary, row=0)
    async def modifier(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier_participant(interaction):
            return
        vue = VueChoixOffre(self.echange_id, interaction.user.id)
        await interaction.response.send_message(
            "Choisis les Pokémon à proposer (tu pourras ajouter des Poké Dollars ensuite) :",
            view=vue,
            ephemeral=True,
        )

    @discord.ui.button(label="Voir toutes les cartes", emoji="🖼️", style=discord.ButtonStyle.secondary, row=0)
    async def galerie(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier_participant(interaction):
            return
        # La composition de l'image peut dépasser les 3 secondes accordées par Discord
        # (téléchargement des sprites + traitement) — on defer d'abord pour avoir le temps.
        await interaction.response.defer(ephemeral=True)

        echange = database.obtenir_echange(self.echange_id)
        offre_j1 = database.obtenir_offre_echange(self.echange_id, echange["joueur1_id"])
        offre_j2 = database.obtenir_offre_echange(self.echange_id, echange["joueur2_id"])
        toutes_captures = list(offre_j1) + list(offre_j2)

        if not toutes_captures:
            await interaction.followup.send("Aucun Pokémon proposé pour l'instant.", ephemeral=True)
            return

        fichier = await construire_fichier_grille(toutes_captures)
        embed = discord.Embed(title="🖼️ Toutes les cartes proposées", color=discord.Color.blurple())
        embed.set_image(url="attachment://offre.png")
        if len(toutes_captures) > MAX_POKEMON_GRILLE:
            embed.set_footer(text=f"Affichage limité aux {MAX_POKEMON_GRILLE} premiers ({len(toutes_captures)} au total).")
        await interaction.followup.send(embed=embed, file=fichier, ephemeral=True)

    @discord.ui.button(label="Valider mon offre", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier_participant(interaction):
            return
        echange_pret = database.valider_offre_echange(self.echange_id, interaction.user.id)

        if echange_pret:
            succes, erreur = database.executer_echange(self.echange_id)
            echange = database.obtenir_echange(self.echange_id)
            noms = await _obtenir_noms(interaction.client, echange["joueur1_id"], echange["joueur2_id"])
            if succes:
                journal.logger(f"🔄 Échange conclu entre <@{echange['joueur1_id']}> et <@{echange['joueur2_id']}>.")
                embed = discord.Embed(
                    title="✅ Échange conclu !",
                    description="Les Pokémon et Poké Dollars ont changé de propriétaire.",
                    color=discord.Color.green(),
                )
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(embed=embed, view=self)
                if interaction.channel:
                    import asyncio
                    async def _supprimer():
                        await asyncio.sleep(DELAI_SUPPRESSION_FIL)
                        try:
                            await interaction.channel.delete()
                        except Exception:
                            pass
                    interaction.client.loop.create_task(_supprimer())
            else:
                database.annuler_echange(self.echange_id)
                embed = discord.Embed(
                    title="❌ Échange annulé",
                    description=f"Impossible de finaliser l'échange : {erreur}",
                    color=discord.Color.red(),
                )
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            embeds = construire_embeds_echange(self.echange_id, await _obtenir_noms_depuis_echange(interaction.client, self.echange_id))
            await interaction.response.edit_message(embeds=embeds, view=self)
            await interaction.followup.send("✅ Ton offre est validée, en attente de l'autre joueur.", ephemeral=True)

    @discord.ui.button(label="Annuler l'échange", emoji="❌", style=discord.ButtonStyle.danger, row=0)
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier_participant(interaction):
            return
        database.annuler_echange(self.echange_id)
        embed = discord.Embed(
            description=f"❌ Échange annulé par {interaction.user.mention}.",
            color=discord.Color.dark_grey(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


async def _obtenir_noms(bot, j1: int, j2: int) -> dict:
    def nom(uid):
        u = bot.get_user(uid)
        return u.display_name if u else f"Joueur {str(uid)[-4:]}"
    return {j1: nom(j1), j2: nom(j2)}


async def _obtenir_noms_depuis_echange(bot, echange_id: int) -> dict:
    echange = database.obtenir_echange(echange_id)
    return await _obtenir_noms(bot, echange["joueur1_id"], echange["joueur2_id"])


async def _rafraichir_message_principal(bot, echange_id: int):
    """Met à jour le message partagé du fil après qu'un joueur ait modifié son offre
    ailleurs (menu éphémère de sélection), pour que l'autre voie le changement en direct."""
    echange = database.obtenir_echange(echange_id)
    if not echange or not echange["thread_id"] or not echange["message_id"]:
        return
    try:
        thread = bot.get_channel(int(echange["thread_id"]))
        if thread is None:
            return
        message = await thread.fetch_message(int(echange["message_id"]))
        noms = await _obtenir_noms_depuis_echange(bot, echange_id)
        embeds = construire_embeds_echange(echange_id, noms)
        await message.edit(embeds=embeds)
    except discord.HTTPException:
        pass


TAILLE_CELLULE_GRILLE = 96
COLONNES_GRILLE = 5
MARGE_GRILLE = 8
HAUTEUR_TEXTE_GRILLE = 28
MAX_POKEMON_GRILLE = 30  # garde-fou : au-delà, l'image deviendrait énorme et lente à générer


async def _telecharger_sprites_statiques(captures: list) -> dict:
    """Télécharge en parallèle les sprites STATIQUES (pas les GIF animés — une seule
    image par Pokémon suffit pour la grille, et c'est bien plus rapide/léger à traiter
    que de décoder des animations). Retourne {(nom, shiny): bytes}, silencieusement
    incomplet si un téléchargement échoue plutôt que de tout faire planter."""
    import aiohttp

    urls = {}
    for row in captures:
        pokemon = obtenir_pokemon_par_nom(row["pokemon_nom"])
        if not pokemon:
            continue
        url = pokemon.get("sprite_shiny") if row["shiny"] else pokemon.get("sprite")
        if url:
            urls[(row["pokemon_nom"], bool(row["shiny"]))] = url

    resultats = {}

    async def _fetch(session, cle, url):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as reponse:
                if reponse.status == 200:
                    resultats[cle] = await reponse.read()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass  # ce sprite manquera juste dans la grille, pas grave

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(_fetch(session, cle, url) for cle, url in urls.items()))
    return resultats


def _composer_grille(captures: list, sprites: dict) -> bytes:
    """Colle les sprites + PC dans une grille statique. Fonction SYNCHRONE et CPU-bound —
    doit être lancée via asyncio.to_thread pour ne jamais bloquer la boucle d'événements
    du bot pendant qu'elle dessine."""
    from PIL import Image, ImageDraw, ImageFont

    n = len(captures)
    colonnes = min(COLONNES_GRILLE, max(1, n))
    lignes = (n + colonnes - 1) // colonnes
    largeur = colonnes * (TAILLE_CELLULE_GRILLE + MARGE_GRILLE) + MARGE_GRILLE
    hauteur = lignes * (TAILLE_CELLULE_GRILLE + HAUTEUR_TEXTE_GRILLE + MARGE_GRILLE) + MARGE_GRILLE

    grille = Image.new("RGBA", (largeur, hauteur), (47, 49, 54, 255))  # fond façon Discord (mode sombre)
    dessin = ImageDraw.Draw(grille)
    police = ImageFont.load_default()

    for i, row in enumerate(captures):
        col, lig = i % colonnes, i // colonnes
        x = MARGE_GRILLE + col * (TAILLE_CELLULE_GRILLE + MARGE_GRILLE)
        y = MARGE_GRILLE + lig * (TAILLE_CELLULE_GRILLE + HAUTEUR_TEXTE_GRILLE + MARGE_GRILLE)

        donnees = sprites.get((row["pokemon_nom"], bool(row["shiny"])))
        if donnees:
            try:
                sprite_img = Image.open(io.BytesIO(donnees)).convert("RGBA")
                sprite_img.thumbnail((TAILLE_CELLULE_GRILLE, TAILLE_CELLULE_GRILLE))
                offset_x = x + (TAILLE_CELLULE_GRILLE - sprite_img.width) // 2
                offset_y = y + (TAILLE_CELLULE_GRILLE - sprite_img.height) // 2
                grille.paste(sprite_img, (offset_x, offset_y), sprite_img)
            except Exception:
                pass  # sprite corrompu/illisible — la cellule reste vide, pas bloquant

        shiny_txt = "✨" if row["shiny"] else ""
        texte = f"{shiny_txt}{row['pokemon_nom']}\n{row['pc']} PC"
        dessin.multiline_text(
            (x + TAILLE_CELLULE_GRILLE // 2, y + TAILLE_CELLULE_GRILLE + 2),
            texte, font=police, fill=(255, 255, 255, 255), anchor="ma", align="center",
        )

    tampon = io.BytesIO()
    grille.save(tampon, format="PNG")
    tampon.seek(0)
    return tampon.getvalue()


async def construire_fichier_grille(captures: list):
    """Point d'entrée : télécharge les sprites (async, en parallèle) puis compose la
    grille dans un thread séparé (CPU-bound), retourne un discord.File prêt à envoyer.
    Retourne None si la liste est vide."""
    if not captures:
        return None
    captures = captures[:MAX_POKEMON_GRILLE]
    sprites = await _telecharger_sprites_statiques(captures)
    donnees_png = await asyncio.to_thread(_composer_grille, captures, sprites)
    return discord.File(io.BytesIO(donnees_png), filename="offre.png")


class VueChoixOffre(discord.ui.View):
    """Sélection paginée des Pokémon à proposer, puis un bouton pour définir le montant de PD."""

    def __init__(self, echange_id: int, user_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.echange_id = echange_id
        self.user_id = user_id
        self.page = page
        self.tri = "alphabetique"

        captures_actuelles = {row["id"] for row in database.obtenir_offre_echange(echange_id, user_id)}
        self.selection = captures_actuelles
        self.toutes_captures = database.obtenir_toutes_captures_detaillees(user_id)
        self._trier_captures()
        self._construire_composants()

    def _trier_captures(self):
        if self.tri == "rarete":
            def cle_rarete(row):
                p = obtenir_pokemon_par_nom(row["pokemon_nom"])
                return (ORDRE_RARETE.get(p["rarete"], 99) if p else 99, cle_tri_alphabetique_fr(row["pokemon_nom"]))

            self.toutes_captures.sort(key=cle_rarete)
        elif self.tri == "pc_desc":
            self.toutes_captures.sort(key=lambda row: -row["pc"])
        elif self.tri == "pc_asc":
            self.toutes_captures.sort(key=lambda row: row["pc"])
        else:
            self.toutes_captures.sort(key=lambda row: cle_tri_alphabetique_fr(row["pokemon_nom"]))

    def _construire_composants(self):
        self.clear_items()
        debut = self.page * CAPTURES_PAR_PAGE
        page_captures = self.toutes_captures[debut : debut + CAPTURES_PAR_PAGE]

        options = []
        for row in page_captures:
            shiny_txt = " ✨" if row["shiny"] else ""
            options.append(
                discord.SelectOption(
                    label=f"{row['pokemon_nom']}{shiny_txt} — {row['pc']} PC"[:100],
                    value=str(row["id"]),
                    default=(row["id"] in self.selection),
                )
            )

        if options:
            select = discord.ui.Select(
                placeholder=f"Coche les Pokémon à proposer ({len(self.selection)} sélectionné(s))",
                options=options,
                min_values=0,
                max_values=len(options),
                row=0,
            )
            select.callback = self._on_select
            self.add_item(select)

        select_tri = discord.ui.Select(
            placeholder="Trier par...",
            options=[
                discord.SelectOption(label=libelle, value=valeur, default=(valeur == self.tri))
                for valeur, libelle in OPTIONS_TRI
            ],
            row=1,
        )
        select_tri.callback = self._on_select_tri
        self.add_item(select_tri)

        nb_pages = max(1, (len(self.toutes_captures) + CAPTURES_PAR_PAGE - 1) // CAPTURES_PAR_PAGE)
        if nb_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=2, disabled=self.page == 0)
            bouton_prec.callback = self._page_prec
            self.add_item(bouton_prec)
            bouton_suiv = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=2, disabled=self.page >= nb_pages - 1)
            bouton_suiv.callback = self._page_suiv
            self.add_item(bouton_suiv)

        bouton_pd = discord.ui.Button(label="Définir les Poké Dollars", emoji="💰", style=discord.ButtonStyle.secondary, row=3)
        bouton_pd.callback = self._on_definir_pd
        self.add_item(bouton_pd)

        bouton_confirmer = discord.ui.Button(label="Confirmer cette offre", emoji="✅", style=discord.ButtonStyle.success, row=3)
        bouton_confirmer.callback = self._on_confirmer
        self.add_item(bouton_confirmer)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton offre !", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        debut = self.page * CAPTURES_PAR_PAGE
        ids_page = {row["id"] for row in self.toutes_captures[debut : debut + CAPTURES_PAR_PAGE]}
        nouvelle_selection_page = {int(v) for v in interaction.data["values"]}
        self.selection = (self.selection - ids_page) | nouvelle_selection_page
        self._construire_composants()
        await interaction.response.edit_message(view=self)

    async def _on_select_tri(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.tri = interaction.data["values"][0]
        self.page = 0
        self._trier_captures()
        self._construire_composants()
        await interaction.response.edit_message(view=self)

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

    async def _on_definir_pd(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        await interaction.response.send_modal(ModalMontantPD(self))

    async def _on_confirmer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        echange = database.obtenir_echange(self.echange_id)
        pd_actuel = echange["joueur1_pd"] if echange["joueur1_id"] == self.user_id else echange["joueur2_pd"]
        database.definir_offre_echange(self.echange_id, self.user_id, list(self.selection), pd_actuel)
        await interaction.response.edit_message(
            content=f"✅ Offre mise à jour : {len(self.selection)} Pokémon proposé(s). Retourne dans le fil !",
            view=None,
        )
        await _rafraichir_message_principal(interaction.client, self.echange_id)


class ModalMontantPD(discord.ui.Modal, title="Poké Dollars à ajouter à l'offre"):
    montant = discord.ui.TextInput(label="Montant (0 pour aucun)", placeholder="ex: 200", required=True, max_length=10)

    def __init__(self, vue_parente: VueChoixOffre):
        super().__init__()
        self.vue_parente = vue_parente

    async def on_submit(self, interaction: discord.Interaction):
        try:
            montant_int = int(self.montant.value)
        except ValueError:
            await interaction.response.send_message("Montant invalide.", ephemeral=True)
            return
        if montant_int < 0:
            await interaction.response.send_message("Le montant ne peut pas être négatif.", ephemeral=True)
            return
        solde = database.obtenir_poke_dollars(self.vue_parente.user_id)
        if montant_int > solde:
            await interaction.response.send_message(
                f"Tu n'as que {solde} {EMOJI_POKEDOLLAR}, tu ne peux pas en proposer {montant_int}.", ephemeral=True
            )
            return

        database.definir_offre_echange(
            self.vue_parente.echange_id, self.vue_parente.user_id, list(self.vue_parente.selection), montant_int
        )
        await interaction.response.edit_message(
            content=f"✅ Offre mise à jour : {len(self.vue_parente.selection)} Pokémon + {montant_int} {EMOJI_POKEDOLLAR}. Retourne dans le fil !",
            view=None,
        )
        await _rafraichir_message_principal(interaction.client, self.vue_parente.echange_id)
