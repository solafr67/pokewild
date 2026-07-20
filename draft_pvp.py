"""Draft PvP — mode de combat "compétitif équitable", indépendant de la collection des
joueurs. Un pool de Pokémon aléatoires est proposé ; les deux joueurs piochent à tour de
rôle (draft façon "serpent" : J1, J2, J2, J1, J1, J2) pour construire leur équipe de 3.

Stats standardisées pour tout le monde (même niveau, IV neutres — voir
config.DRAFT_NIVEAU) : ici, c'est la lecture du plateau qui compte, pas qui a le plus
farmé. Les 4 attaques de chaque Pokémon drafté sont tirées AU HASARD dans tout son
movepool possible, sans tenir compte du niveau requis ni d'une CT possédée — équipées
dans une table dédiée (voir database.equiper_attaque_draft) qui ne touche jamais le
loadout permanent réel des joueurs, même s'ils possèdent l'espèce en vrai.
"""

import random

import discord

import combat as combat_module
import config
import database
from pokemon_data import IV_DEFAUT, POKEDEX, attaques_apprenables, calculer_toutes_stats

DELAI_SUPPRESSION_FIL_DRAFT = 120  # secondes après la fin du draft avant suppression du fil de draft


def _tirer_pool() -> list:
    taille = min(config.DRAFT_TAILLE_POOL, len(POKEDEX))
    return random.sample(POKEDEX, taille)


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


class VueDraft(discord.ui.View):
    """Draft façon "serpent" dans un fil dédié — un menu déroulant partagé, restreint au
    joueur dont c'est le tour."""

    ORDRE_PICKS = [1, 2, 2, 1, 1, 2]  # 1 = joueur1, 2 = joueur2 ; 3 picks chacun

    def __init__(self, bot, joueur1: discord.Member, joueur2: discord.Member, channel_original: discord.TextChannel):
        super().__init__(timeout=180)
        self.bot = bot
        self.joueur1 = joueur1
        self.joueur2 = joueur2
        self.channel_original = channel_original
        self.pool = _tirer_pool()
        self.picks = {joueur1.id: [], joueur2.id: []}
        self._construire_composants()

    @property
    def index_pick(self) -> int:
        return len(self.picks[self.joueur1.id]) + len(self.picks[self.joueur2.id])

    @property
    def termine(self) -> bool:
        return self.index_pick >= len(self.ORDRE_PICKS)

    @property
    def joueur_actuel(self) -> discord.Member:
        return self.joueur1 if self.ORDRE_PICKS[self.index_pick] == 1 else self.joueur2

    def _construire_composants(self):
        self.clear_items()
        if self.termine or not self.pool:
            return
        options = [discord.SelectOption(label=p["nom"], value=p["nom"]) for p in self.pool]
        select = discord.ui.Select(placeholder="Choisis un Pokémon...", options=options)
        select.callback = self._on_pick
        self.add_item(select)

    def construire_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎯 Draft PvP", color=discord.Color.purple())
        embed.add_field(
            name="Pool disponible",
            value=", ".join(p["nom"] for p in self.pool) if self.pool else "*(épuisé)*",
            inline=False,
        )
        embed.add_field(
            name=f"Équipe — {self.joueur1.display_name}",
            value=", ".join(self.picks[self.joueur1.id]) or "*(vide)*",
            inline=True,
        )
        embed.add_field(
            name=f"Équipe — {self.joueur2.display_name}",
            value=", ".join(self.picks[self.joueur2.id]) or "*(vide)*",
            inline=True,
        )
        if not self.termine:
            embed.description = f"C'est au tour de **{self.joueur_actuel.display_name}** de choisir."
        else:
            embed.description = "Draft terminé — lancement du combat..."
        return embed

    async def _on_pick(self, interaction: discord.Interaction):
        if interaction.user.id != self.joueur_actuel.id:
            await interaction.response.send_message("Ce n'est pas ton tour de choisir !", ephemeral=True)
            return

        nom = interaction.data["values"][0]
        pokemon = next((p for p in self.pool if p["nom"] == nom), None)
        if not pokemon:
            await interaction.response.send_message("Ce Pokémon n'est plus disponible.", ephemeral=True)
            return

        self.pool.remove(pokemon)
        self.picks[interaction.user.id].append(nom)

        if self.termine:
            self._construire_composants()
            await interaction.response.edit_message(embed=self.construire_embed(), view=self)
            await _lancer_combat_draft(self.bot, self.joueur1, self.joueur2, self.channel_original, self.picks, interaction.message)
            return

        self._construire_composants()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def _lancer_combat_draft(bot, joueur1, joueur2, channel_original, picks, message_draft):
    """Construit les équipes à partir des picks, équipe des attaques aléatoires pour
    chaque Pokémon drafté, puis lance le combat via le moteur PvP habituel."""
    noms_par_espece = {p["nom"]: p for p in POKEDEX}
    equipe1 = [_stats_draft(noms_par_espece[nom]) for nom in picks[joueur1.id] if nom in noms_par_espece]
    equipe2 = [_stats_draft(noms_par_espece[nom]) for nom in picks[joueur2.id] if nom in noms_par_espece]

    if not equipe1 or not equipe2:
        try:
            await message_draft.reply("❌ Le draft n'a pas pu être complété correctement — combat annulé.")
        except discord.HTTPException:
            pass
        return

    async def _equiper_attaques_draft(combat_id: int):
        for user_id, noms in ((joueur1.id, picks[joueur1.id]), (joueur2.id, picks[joueur2.id])):
            for nom in noms:
                pokemon = noms_par_espece.get(nom)
                if not pokemon:
                    continue
                for slot, attaque in enumerate(_tirer_attaques_aleatoires(pokemon), start=1):
                    database.equiper_attaque_draft(combat_id, user_id, nom, slot, attaque)

    await combat_module.lancer_combat_avec_equipes(
        bot, joueur1, joueur2, channel_original, equipe1, equipe2, avant_lancement=_equiper_attaques_draft
    )

    try:
        await message_draft.reply(f"🎯 Draft terminé, le combat est lancé plus bas dans le channel !")
    except discord.HTTPException:
        pass

    bot.loop.create_task(_supprimer_message_apres_delai(message_draft, DELAI_SUPPRESSION_FIL_DRAFT))


async def _supprimer_message_apres_delai(message: discord.Message, delai: int):
    import asyncio

    await asyncio.sleep(delai)
    try:
        await message.delete()
    except discord.HTTPException:
        pass


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
        vue = VueDraft(self.bot, self.challenger, self.adversaire, self.channel_original)
        await interaction.response.edit_message(content=None, embed=vue.construire_embed(), view=vue)

    async def _on_refuser(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.adversaire.id, self.challenger.id):
            await interaction.response.send_message("Cette invitation ne te concerne pas !", ephemeral=True)
            return
        self.clear_items()
        await interaction.response.edit_message(
            content=f"❌ {self.adversaire.display_name} n'a pas donné suite au Draft.", embed=None, view=None
        )
