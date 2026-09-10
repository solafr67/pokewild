"""Journal de dresseur mensuel : résumé façon "Wrapped" envoyé en DM le 1er de chaque
mois à chaque joueur actif (voir main.py::boucle_journal_dresseur_mensuel).

Les stats affichées sont des DELTAS (progression DEPUIS le dernier journal), calculés
par database.generer_journal_dresseur — stats_lifetime étant cumulatif depuis toujours,
c'est le seul moyen d'isoler "ce mois-ci" sans ajouter un timestamp à chaque événement
individuel du jeu.
"""

import discord

import database
from pokemon_data import EMOJI_POKEDOLLAR


def construire_embed_journal(user_id: int, deltas: dict, rang_captures: int | None, total_joueurs: int) -> discord.Embed:
    """deltas vient de database.generer_journal_dresseur (déjà calculé par l'appelant,
    cette fonction ne fait QUE l'affichage — voir boucle_journal_dresseur_mensuel pour
    le calcul du classement, fait une seule fois pour tous les joueurs d'un coup)."""
    if deltas["premier_journal"]:
        titre = "📖 Ton tout premier Journal de dresseur !"
        intro = "Voici tout ton parcours jusqu'ici — le prochain journal ne couvrira, lui, que le mois à venir."
    else:
        titre = "📖 Ton Journal de dresseur du mois"
        intro = "Voici ce que tu as accompli ce mois-ci !"

    embed = discord.Embed(title=titre, description=intro, color=discord.Color.blurple())

    embed.add_field(name="🎯 Captures", value=f"**{deltas['captures']}** Pokémon capturés", inline=True)
    embed.add_field(name="🌟 Shiny", value=f"**{deltas['shiny']}** chromatiques", inline=True)
    embed.add_field(name="🥊 Victoires PvP", value=f"**{deltas['victoires_pvp']}** combats remportés", inline=True)
    embed.add_field(name="🗺️ Explorations", value=f"**{deltas['explorations']}** expéditions terminées", inline=True)

    if rang_captures is not None and deltas["captures"] > 0:
        embed.add_field(
            name="🏆 Ton classement du mois",
            value=f"**#{rang_captures}** / {total_joueurs} joueurs (captures)",
            inline=False,
        )

    if all(deltas[cle] == 0 for cle in ("captures", "shiny", "victoires_pvp", "explorations")):
        embed.add_field(
            name="😴 Un mois tranquille",
            value="Aucune activité enregistrée ce mois-ci — reviens vite nous voir !",
            inline=False,
        )

    embed.set_footer(text="À très vite pour le prochain journal, le 1er du mois prochain !")
    return embed
