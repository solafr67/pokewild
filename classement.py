import discord

import config
import database
from pokemon_data import EMOJI_POKEDEX, EMOJI_POKEDOLLAR, POKEDEX

MEDAILLES = ["🥇", "🥈", "🥉"]


def _puce(rang: int) -> str:
    return MEDAILLES[rang] if rang < len(MEDAILLES) else f"{rang + 1}."


def _lignes_captures(limite: int) -> list:
    top = database.classement_captures_individuelles(limite)
    return [f"{_puce(i)} <@{row['user_id']}> — {row['total_captures']} captures" for i, row in enumerate(top)]


def _lignes_dollars(limite: int) -> list:
    top = [r for r in database.classement_poke_dollars(limite) if r["poke_dollars"] > 0]
    return [f"{_puce(i)} <@{row['user_id']}> — {row['poke_dollars']} {EMOJI_POKEDOLLAR}" for i, row in enumerate(top)]


def _lignes_pokedex(limite: int) -> list:
    total_especes = len(POKEDEX)
    top = database.classement_completion_pokedex(limite)
    return [
        f"{_puce(i)} <@{row['user_id']}> — {row['especes_distinctes']}/{total_especes} "
        f"({row['especes_distinctes'] / total_especes:.0%})"
        for i, row in enumerate(top)
    ]


def _lignes_pvp(limite: int) -> list:
    top = database.classement_victoires_pvp(limite)
    return [f"{_puce(i)} <@{row['user_id']}> — {row['victoires_pvp']} victoires" for i, row in enumerate(top)]


def _lignes_shiny(limite: int) -> list:
    top = database.classement_shiny(limite)
    return [f"{_puce(i)} <@{row['user_id']}> — {row['total_shiny']} ✨" for i, row in enumerate(top)]


def _lignes_exploration(limite: int) -> list:
    top = database.classement_explorations(limite)
    return [f"{_puce(i)} <@{row['user_id']}> — {row['explorations_terminees']} expéditions" for i, row in enumerate(top)]


def _lignes_clans() -> list:
    top_equipes = database.classement_equipes()
    scores_par_equipe = {row["equipe"]: row for row in top_equipes}
    toutes = []
    for nom_equipe in config.COULEURS_EQUIPES:
        if nom_equipe in scores_par_equipe:
            toutes.append(scores_par_equipe[nom_equipe])
        else:
            toutes.append({"equipe": nom_equipe, "total_captures": 0, "total_pc": 0})
    toutes.sort(key=lambda r: r["total_pc"], reverse=True)
    return [
        f"{_puce(i)} {config.EMOJI_EQUIPES.get(row['equipe'], '')} **{row['equipe']}** — "
        f"{row['total_captures']} captures, {row['total_pc']} PC cumulés"
        for i, row in enumerate(toutes)
    ]


CATEGORIES = {
    "captures": {"emoji": "🎯", "titre": "Plus de captures", "lignes": _lignes_captures},
    "dollars": {"emoji": EMOJI_POKEDOLLAR, "titre": "Plus de Poké Dollars", "lignes": _lignes_dollars},
    "pokedex": {"emoji": EMOJI_POKEDEX, "titre": "Meilleure complétion du Pokédex", "lignes": _lignes_pokedex},
    "pvp": {"emoji": "🥊", "titre": "Plus de victoires PvP", "lignes": _lignes_pvp},
    "shiny": {"emoji": "🌟", "titre": "Plus de Pokémon shiny capturés", "lignes": _lignes_shiny},
    "exploration": {"emoji": "🗺️", "titre": "Plus d'expéditions terminées", "lignes": _lignes_exploration},
}


def construire_embed_apercu() -> discord.Embed:
    """Vue d'ensemble CONCISE (top 3 seulement) postée/rafraîchie automatiquement — le
    détail complet (top 10) est accessible via le menu déroulant ci-dessous. Blocs en
    pleine largeur (pas de colonnes côte à côte) pour éviter que les mentions ne se
    tassent sur plusieurs lignes illisibles avec des pseudos longs."""
    embed = discord.Embed(title="🏆 Classements", color=discord.Color.gold())

    for cle in ("captures", "dollars", "pokedex", "pvp", "shiny"):
        cat = CATEGORIES[cle]
        lignes = cat["lignes"](3)
        if not lignes:
            continue  # catégorie vide : on ne l'affiche pas plutôt que "Aucune donnée"
        embed.add_field(name=f"{cat['emoji']} {cat['titre']}", value="\n".join(lignes), inline=False)

    embed.add_field(name="🚩 Classement des clans", value="\n".join(_lignes_clans()), inline=False)

    minutes = config.INTERVALLE_CLASSEMENT // 60
    embed.set_footer(text=f"Aperçu mis à jour toutes les {minutes} minutes — menu ci-dessous pour le détail complet")
    return embed


def construire_embed_categorie(cle: str) -> discord.Embed:
    cat = CATEGORIES[cle]
    lignes = cat["lignes"](config.TAILLE_TOP_CLASSEMENT)
    embed = discord.Embed(
        title=f"{cat['emoji']} {cat['titre']}",
        description="\n".join(lignes) if lignes else "Aucune donnée pour l'instant.",
        color=discord.Color.gold(),
    )
    return embed


class VueClassements(discord.ui.View):
    """Vue persistante : un menu déroulant pour consulter le détail (top 10) de
    n'importe quelle catégorie, sans surcharger l'aperçu automatique."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Voir le classement détaillé d'une catégorie...",
        custom_id="classement_categorie_select",
        options=[discord.SelectOption(label=cat["titre"], value=cle) for cle, cat in CATEGORIES.items()],
    )
    async def choisir_categorie(self, interaction: discord.Interaction, select: discord.ui.Select):
        cle = select.values[0]
        embed = construire_embed_categorie(cle)
        await interaction.response.send_message(embed=embed, ephemeral=True)
