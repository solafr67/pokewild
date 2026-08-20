"""Draft PvP — mode de combat "compétitif équitable", indépendant de la collection des
joueurs. Chaque joueur reçoit son PROPRE pool privé de 12 Pokémon tirés au hasard (les
deux pools sont disjoints — jamais le même Pokémon proposé aux deux joueurs, donc jamais
la même équipe des deux côtés), et choisit 6 Pokémon dedans, EN PARALLÈLE et en toute
confidentialité (message éphémère, l'adversaire ne voit jamais les choix de l'autre avant
la fin). Le combat démarre automatiquement dès que les deux ont validé leurs 6.

Stats standardisées pour tout le monde (même niveau, IV neutres — voir
config.DRAFT_NIVEAU) : ici, c'est la lecture du plateau qui compte, pas qui a le plus
farmé. Les 4 attaques ET le talent de chaque Pokémon drafté sont tirés AU HASARD (talent :
voir capacites.capacite_pour_espece, mêmes règles que pour un dresseur IA — même un vrai
joueur ne doit jamais hériter du talent de sa vraie capture ici, puisque l'espèce piochée
n'est pas forcément dans sa collection réelle). Rien de tout ça ne touche le loadout
permanent réel des joueurs, même s'ils possèdent l'espèce en vrai (voir
database.equiper_attaque_draft / definir_capacite_combat, toutes deux scopées à CE combat
précis uniquement).
"""

import random

import discord

import combat as combat_module
import config
import database
from pokemon_data import IV_DEFAUT, POKEDEX, attaques_apprenables, calculer_toutes_stats

DELAI_SUPPRESSION_FIL_DRAFT = 120  # secondes après la fin du draft avant suppression du fil de draft


def _stats_draft(pokemon: dict) -> dict:
    stats = calculer_toutes_stats(pokemon, IV_DEFAUT, config.DRAFT_NIVEAU)
    if not stats:
        stats = {"pv": 120, "attaque": 60, "defense": 60, "attaque_spe": 60, "defense_spe": 60, "vitesse": 60}
    return {"nom": pokemon["nom"], "niveau": config.DRAFT_NIVEAU, **stats}


def _tirer_attaques_aleatoires(pokemon: dict) -> list:
    """4 attaques tirées au hasard dans TOUT le movepool possible de l'espèce,
    indépendamment du niveau requis ou d'une CT possédée — le Draft ignore ces
    restrictions volontairement, seule la lecture du jeu compte ici."""
    pool = attaques_apprenables(pokemon)  # niveau=None => liste complète, sans filtre
    taille = min(4, len(pool))
    return random.sample(pool, taille) if taille else []


class EtatDraft:
    """État partagé d'un draft en cours — un seul par draft, référencé à la fois par la
    vue publique (bouton "Choisir mon équipe") et par les deux vues éphémères privées
    (une par joueur). Les deux pools sont tirés une seule fois, à la création, et ne se
    recoupent jamais (voir __init__)."""

    def __init__(self, bot, joueur1: discord.Member, joueur2: discord.Member, channel_original: discord.TextChannel):
        self.bot = bot
        self.joueur1 = joueur1
        self.joueur2 = joueur2
        self.channel_original = channel_original
        self.message_public = None  # défini juste après l'envoi du message (voir VueInvitationDraft)

        taille_totale = min(2 * config.DRAFT_TAILLE_POOL_PERSO, len(POKEDEX))
        tirage = random.sample(POKEDEX, taille_totale)
        moitie = taille_totale // 2
        self.pools = {joueur1.id: tirage[:moitie], joueur2.id: tirage[moitie:taille_totale]}
        self.picks = {joueur1.id: None, joueur2.id: None}  # None = pas encore validé, sinon liste de noms

    @property
    def tous_prets(self) -> bool:
        return all(picks is not None for picks in self.picks.values())

    def joueur_pour(self, user_id: int) -> discord.Member:
        return self.joueur1 if user_id == self.joueur1.id else self.joueur2


def _construire_embed_public(etat: EtatDraft) -> discord.Embed:
    embed = discord.Embed(
        title="🎯 Draft PvP",
        description=(
            f"Chaque joueur choisit son équipe de **{config.DRAFT_TAILLE_EQUIPE}** Pokémon "
            f"dans son propre pool de **{config.DRAFT_TAILLE_POOL_PERSO}** — clique sur le "
            f"bouton ci-dessous (visible seulement par toi, ton adversaire ne verra pas tes choix)."
        ),
        color=discord.Color.purple(),
    )
    for joueur in (etat.joueur1, etat.joueur2):
        pret = etat.picks[joueur.id] is not None
        embed.add_field(
            name=joueur.display_name,
            value="✅ Équipe prête !" if pret else "⏳ En train de choisir...",
            inline=True,
        )
    if etat.tous_prets:
        embed.set_footer(text="Les deux équipes sont prêtes — lancement du combat...")
    return embed


class VueSelectionDraft(discord.ui.View):
    """Vue ÉPHÉMÈRE, privée — un menu déroulant sur le pool de CE joueur uniquement
    (min=max=DRAFT_TAILLE_EQUIPE, donc validée automatiquement dès la sélection)."""

    def __init__(self, etat: EtatDraft, user_id: int, vue_publique: "VueDraftPublic"):
        super().__init__(timeout=180)
        self.etat = etat
        self.user_id = user_id
        self.vue_publique = vue_publique

        pool = etat.pools[user_id]
        options = [discord.SelectOption(label=p["nom"], value=p["nom"]) for p in pool]
        select = discord.ui.Select(
            placeholder=f"Choisis exactement {config.DRAFT_TAILLE_EQUIPE} Pokémon...",
            options=options,
            min_values=config.DRAFT_TAILLE_EQUIPE,
            max_values=config.DRAFT_TAILLE_EQUIPE,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        noms_choisis = interaction.data["values"]
        self.etat.picks[self.user_id] = noms_choisis
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Équipe validée : **{', '.join(noms_choisis)}**", view=self
        )

        try:
            await self.etat.message_public.edit(embed=_construire_embed_public(self.etat))
        except discord.HTTPException:
            pass

        if self.etat.tous_prets:
            self.vue_publique.stop()
            for item in self.vue_publique.children:
                item.disabled = True
            try:
                await self.etat.message_public.edit(view=self.vue_publique)
            except discord.HTTPException:
                pass
            await _lancer_combat_draft(self.etat)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class VueDraftPublic(discord.ui.View):
    """Vue PUBLIQUE (non éphémère) affichée dans le fil de draft — n'importe lequel des
    deux joueurs peut cliquer pour ouvrir SON propre pool en privé."""

    def __init__(self, etat: EtatDraft):
        super().__init__(timeout=300)
        self.etat = etat

    @discord.ui.button(label="Choisir mon équipe", emoji="🎯", style=discord.ButtonStyle.primary)
    async def choisir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.etat.joueur1.id, self.etat.joueur2.id):
            await interaction.response.send_message("Ce draft ne te concerne pas !", ephemeral=True)
            return
        if self.etat.picks[interaction.user.id] is not None:
            await interaction.response.send_message("Tu as déjà validé ton équipe !", ephemeral=True)
            return

        vue = VueSelectionDraft(self.etat, interaction.user.id, self)
        pool = self.etat.pools[interaction.user.id]
        noms_pool = ", ".join(p["nom"] for p in pool)
        await interaction.response.send_message(
            f"🎯 Voici tes **{len(pool)}** Pokémon — choisis-en exactement "
            f"**{config.DRAFT_TAILLE_EQUIPE}** :\n{noms_pool}",
            view=vue,
            ephemeral=True,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def _lancer_combat_draft(etat: EtatDraft):
    """Construit les équipes à partir des picks, équipe des attaques ET un talent tirés
    au hasard pour chaque Pokémon drafté, puis lance le combat via le moteur PvP habituel."""
    import capacites as capacites_module

    noms_par_espece = {p["nom"]: p for p in POKEDEX}
    equipe1 = [_stats_draft(noms_par_espece[nom]) for nom in etat.picks[etat.joueur1.id] if nom in noms_par_espece]
    equipe2 = [_stats_draft(noms_par_espece[nom]) for nom in etat.picks[etat.joueur2.id] if nom in noms_par_espece]

    if len(equipe1) != config.DRAFT_TAILLE_EQUIPE or len(equipe2) != config.DRAFT_TAILLE_EQUIPE:
        try:
            await etat.message_public.reply("❌ Le draft n'a pas pu être complété correctement — combat annulé.")
        except discord.HTTPException:
            pass
        return

    async def _preparer_combat(combat_id: int):
        for user_id, noms in ((etat.joueur1.id, etat.picks[etat.joueur1.id]), (etat.joueur2.id, etat.picks[etat.joueur2.id])):
            for nom in noms:
                pokemon = noms_par_espece.get(nom)
                if not pokemon:
                    continue
                for slot, attaque in enumerate(_tirer_attaques_aleatoires(pokemon), start=1):
                    database.equiper_attaque_draft(combat_id, user_id, nom, slot, attaque)
                # Talent tiré au hasard — même règle qu'un dresseur IA (voir docstring du
                # module) : jamais le vrai talent de la capture du joueur, s'il en a une.
                database.definir_capacite_combat(combat_id, user_id, nom, capacites_module.capacite_pour_espece(nom))

    try:
        combat_id = await combat_module.lancer_combat_avec_equipes(
            etat.bot, etat.joueur1, etat.joueur2, etat.channel_original, equipe1, equipe2, avant_lancement=_preparer_combat
        )
    except Exception:
        import traceback

        print(f"⚠️ Erreur en lançant le combat Draft PvP ({etat.joueur1.id} vs {etat.joueur2.id}) :")
        traceback.print_exc()
        try:
            await etat.message_public.reply(
                "❌ Une erreur a empêché le lancement du combat — réessaie avec `/defi-draft`. "
                "(Erreur journalisée pour investigation.)"
            )
        except discord.HTTPException:
            pass
        return

    combat_row = database.obtenir_combat(combat_id)
    mention_fil = ""
    if combat_row and combat_row["thread_id"]:
        mention_fil = f" <#{combat_row['thread_id']}>"

    try:
        await etat.message_public.reply(f"🎯 Draft terminé, le combat est lancé !{mention_fil}")
    except discord.HTTPException:
        pass

    # Supprime le FIL de draft entier (pas juste ce message) — le combat vit maintenant
    # dans son propre fil, celui du draft n'a plus d'utilité.
    fil_draft = etat.message_public.channel
    etat.bot.loop.create_task(combat_module.supprimer_fil_apres_delai(fil_draft, DELAI_SUPPRESSION_FIL_DRAFT))


class VueInvitationDraft(discord.ui.View):
    """Invitation avant de démarrer un Draft — évite d'en lancer un non désiré."""

    def __init__(self, bot, challenger: discord.Member, adversaire: discord.Member, channel_original: discord.TextChannel):
        super().__init__(timeout=120)
        self.bot = bot
        self.challenger = challenger
        self.adversaire = adversaire
        self.channel_original = channel_original

        bouton_accepter = discord.ui.Button(label="Accepter", emoji="🎯", style=discord.ButtonStyle.success)
        bouton_accepter.callback = self._on_accepter
        self.add_item(bouton_accepter)

        bouton_refuser = discord.ui.Button(label="Refuser", emoji="❌", style=discord.ButtonStyle.secondary)
        bouton_refuser.callback = self._on_refuser
        self.add_item(bouton_refuser)

    async def _on_accepter(self, interaction: discord.Interaction):
        if interaction.user.id != self.adversaire.id:
            await interaction.response.send_message("Cette invitation ne t'est pas destinée !", ephemeral=True)
            return

        etat = EtatDraft(self.bot, self.challenger, self.adversaire, self.channel_original)
        vue = VueDraftPublic(etat)
        await interaction.response.edit_message(content=None, embed=_construire_embed_public(etat), view=vue)
        etat.message_public = await interaction.original_response()

    async def _on_refuser(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.adversaire.id, self.challenger.id):
            await interaction.response.send_message("Cette invitation ne te concerne pas !", ephemeral=True)
            return
        self.clear_items()
        await interaction.response.edit_message(
            content=f"❌ {self.adversaire.display_name} n'a pas donné suite au Draft. "
            f"Ce fil sera supprimé dans {DELAI_SUPPRESSION_FIL_DRAFT // 60} minutes.",
            embed=None,
            view=None,
        )
        self.bot.loop.create_task(combat_module.supprimer_fil_apres_delai(interaction.channel, DELAI_SUPPRESSION_FIL_DRAFT))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
