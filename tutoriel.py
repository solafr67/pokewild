"""Tutoriel pour les nouveaux joueurs — guide façon Gladio à travers les channels
principaux. Déclenché automatiquement à l'arrivée d'un membre (voir main.py::on_member_join)
et rejouable à tout moment via /tuto.

Le message d'accueil est posté PUBLIQUEMENT (mentionne le nouveau joueur) — c'est le bouton
"Commencer le tuto" dessus qui, lui, ouvre le vrai contenu du tuto en message ÉPHÉMÈRE
(visible seulement par le joueur qui clique), pas le message d'accueil lui-même. Un message
Discord ne peut être éphémère qu'en réponse à une interaction (clic de bouton, commande) —
impossible de l'être "à froid" au moment où quelqu'un rejoint le serveur.
"""

import discord

import config
from pnj import EMOJI_RIVAL, IMAGE_RIVAL, NOM_RIVAL

# Chaque étape : (titre, texte). {channel} est remplacé par la mention du channel au moment
# de l'affichage (voir _texte_etape) — permet de garder ce tableau lisible sans avoir à
# écrire des f-strings avec les ID en dur partout.
_ETAPES = [
    (
        "Bienvenue !",
        (
            f"Salut, {{prenom}}. Moi c'est {NOM_RIVAL}, ton rival ici. Je vais te montrer "
            "vite fait où aller — après ça, tu te débrouilles.\n\n"
            "*(Utilise les boutons ci-dessous pour naviguer, à ton rythme.)*"
        ),
    ),
    (
        "Attraper des Pokémon",
        (
            "Les Pokémon sauvages apparaissent dans {spawn}. Un bouton \"Capturer\" arrive "
            "avec chaque apparition — tape dessus avant qu'il ne s'enfuie."
        ),
    ),
    (
        "Le PokéStop",
        f"Passe régulièrement par {{pokestop}} — objets gratuits toutes les quelques heures, "
        f"aucune raison de s'en priver.",
    ),
    (
        "La Boutique",
        "Une fois que t'as des Poké Dollars, {boutique} te permet d'acheter balls, potions "
        "et autres objets utiles.",
    ),
    (
        "Le Laboratoire",
        (
            "Deux trucs t'attendent dans {laboratoire} : ta Mutation de dresseur (bonus "
            "permanents) et ton incubateur à œufs."
        ),
    ),
    (
        "Exploration",
        "Envoie ton équipe explorer depuis {exploration} — ça tourne en arrière-plan et "
        "rapporte des récompenses pendant que tu fais autre chose.",
    ),
    (
        "Quêtes",
        "Des objectifs journaliers et hebdomadaires t'attendent dans {quetes} — bonnes "
        "récompenses pour peu d'effort, à checker régulièrement.",
    ),
    (
        "Ta fiche",
        "Toute ta progression (Pokédex, équipe, statistiques) est consultable dans {profil} "
        "à tout moment.",
    ),
    (
        "À toi de jouer",
        (
            f"Voilà, t'as l'essentiel. Le reste, tu le découvriras en jouant — et si "
            f"jamais un doute, {{wiki}} a réponse à presque tout.\n\n"
            f"*{{prenom}}, montre-moi ce que tu vaux.* — {NOM_RIVAL} {EMOJI_RIVAL}"
        ),
    ),
]


def _texte_etape(index: int, member: discord.Member) -> str:
    titre, texte = _ETAPES[index]
    return texte.format(
        prenom=member.display_name,
        spawn=f"<#{config.CHANNEL_SPAWN_CLASSIQUE_ID}>",
        pokestop=f"<#{config.CHANNEL_POKESTOP_ID}>",
        boutique=f"<#{config.CHANNEL_BOUTIQUE_ID}>",
        laboratoire=f"<#{config.CHANNEL_LABORATOIRE_ID}>",
        exploration=f"<#{config.CHANNEL_EXPLORATION_ID}>",
        quetes=f"<#{config.CHANNEL_QUETES_ID}>",
        profil=f"<#{config.CHANNEL_PROFIL_ID}>",
        wiki=f"<#{config.CHANNEL_WIKI_ID}>",
    )


def construire_embed_etape(index: int, member: discord.Member) -> discord.Embed:
    titre, _ = _ETAPES[index]
    embed = discord.Embed(
        title=f"{EMOJI_RIVAL} {titre}",
        description=_texte_etape(index, member),
        color=discord.Color.dark_grey(),
    )
    embed.set_thumbnail(url=IMAGE_RIVAL)
    embed.set_footer(text=f"Étape {index + 1}/{len(_ETAPES)}")
    return embed


class VueTutoriel(discord.ui.View):
    """Navigation Précédent/Suivant à travers les étapes — vue éphémère (message visible
    seulement par le joueur qui a cliqué sur "Commencer le tuto")."""

    def __init__(self, member: discord.Member, index: int = 0):
        super().__init__(timeout=300)
        self.member = member
        self.index = index
        self._construire_composants()

    def _construire_composants(self):
        self.clear_items()

        bouton_prec = discord.ui.Button(
            label="◀ Précédent", style=discord.ButtonStyle.secondary, disabled=self.index == 0
        )
        bouton_prec.callback = self._on_precedent
        self.add_item(bouton_prec)

        if self.index < len(_ETAPES) - 1:
            bouton_suiv = discord.ui.Button(label="Suivant ▶", style=discord.ButtonStyle.primary)
            bouton_suiv.callback = self._on_suivant
            self.add_item(bouton_suiv)
        else:
            bouton_fin = discord.ui.Button(label="Terminé ✅", style=discord.ButtonStyle.success)
            bouton_fin.callback = self._on_terminer
            self.add_item(bouton_fin)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Ce tuto ne te concerne pas !", ephemeral=True)
            return False
        return True

    async def _on_precedent(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.index = max(0, self.index - 1)
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_etape(self.index, self.member), view=self)

    async def _on_suivant(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.index = min(len(_ETAPES) - 1, self.index + 1)
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_etape(self.index, self.member), view=self)

    async def _on_terminer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        await interaction.response.edit_message(
            content="Bon jeu ! Retape `/tuto` à tout moment pour le revoir.",
            embed=None,
            view=None,
        )


async def poster_accueil(member: discord.Member):
    """Crée un fil PRIVÉ (visible seulement par le membre + le staff avec les permissions
    adéquates) dans CHANNEL_PROFIL_ID et y poste directement le tuto — un fil privé est la
    seule façon d'avoir un contenu "réservé à ce joueur, sur le serveur" en dehors d'une
    interaction (bouton/commande), un vrai message éphémère étant impossible à envoyer "à
    froid" au moment où quelqu'un rejoint (ça nécessite de répondre à une interaction, qui
    n'existe pas encore à ce moment-là). Même mécanisme de fil privé que pour les échanges
    (voir echanges.py::demarrer_echange). Échoue silencieusement (log seulement) si le
    channel est introuvable ou si le bot n'a pas la permission requise — ne doit jamais
    faire planter on_member_join."""
    channel = member.guild.get_channel(config.CHANNEL_PROFIL_ID)
    if channel is None:
        print(f"⚠️ CHANNEL_PROFIL_ID introuvable — impossible de créer le fil d'accueil pour {member}.")
        return
    try:
        thread = await channel.create_thread(
            name=f"👋 Bienvenue {member.display_name}",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(member)
        vue = VueTutoriel(member)
        await thread.send(
            f"👋 Bienvenue {member.mention} ! Un coup d'œil rapide avant de te lancer :",
            embed=construire_embed_etape(0, member),
            view=vue,
        )
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"⚠️ Échec de la création du fil d'accueil pour {member} : {e}")
