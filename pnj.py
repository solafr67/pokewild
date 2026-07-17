"""Le Rival — PNJ récurrent qui commente les événements marquants du serveur.

V1 : répliques pré-écrites, tirées au hasard, avec quelques valeurs injectées (nom du
joueur, du Pokémon...). Zéro coût, mais réagit toujours de la même poignée de façons.

Pensé pour un remplacement facile par une vraie génération IA plus tard : tout le reste
du code appelle uniquement `reagir(situation, **contexte)` — le jour où on branche un
LLM, seul le contenu de cette fonction change, aucun appelant n'a besoin d'être touché.
"""

import random

import discord

NOM_RIVAL = "Gladio"
EMOJI_RIVAL = "⚔️"
IMAGE_RIVAL = "https://archives.bulbagarden.net/media/upload/4/44/VSGladion_2.png"

# Chaque {clé} dans une réplique doit correspondre à un argument passé à reagir(**contexte).
# Plusieurs variantes par situation pour ne pas répéter toujours la même ligne.
REPLIQUES = {
    "capture_shiny": [
        "Tiens, {joueur} qui déniche un {pokemon} chromatique... Encore un coup de bol, j'imagine.",
        "Un {pokemon} shiny pour {joueur} ? Pff. Le jour où j'en trouve un, je te préviens.",
        "{joueur} et son {pokemon} brillant. T'façon, la chance, c'est pas une stratégie.",
        "Un {pokemon} chromatique... {joueur} a plus de bol que de talent, mais bon, ça compte quand même.",
    ],
    "capture_legendaire": [
        "{joueur} qui capture {pokemon}... Je vais devoir revoir mon équipe, moi.",
        "Un {pokemon} en plus dans l'équipe de {joueur}. Ça devient sérieux.",
        "{pokemon}, capturé par {joueur}. J'avoue, celui-là, je l'aurais bien voulu aussi.",
    ],
    "victoire_raid": [
        "Raid nettoyé par {joueur} et son équipe. Pas mal, pour une fois.",
        "{joueur} qui termine le raid en tête... Je note.",
        "Encore un raid plié. {joueur}, arrête de me donner des complexes.",
    ],
}


def reagir(situation: str, **contexte) -> str | None:
    """Retourne une réplique du rival pour cette situation, ou None si rien à dire
    (situation inconnue, ou variable de contexte manquante pour la remplir)."""
    pool = REPLIQUES.get(situation)
    if not pool:
        return None
    modele = random.choice(pool)
    try:
        return modele.format(**contexte)
    except KeyError:
        return None


def construire_embed_reaction(situation: str, **contexte) -> discord.Embed | None:
    """Comme reagir(), mais retourne directement un petit embed prêt à ajouter à côté
    de l'embed principal (portrait en vignette) — None si le rival n'a rien à dire cette
    fois. Se pose comme un SECOND embed du message plutôt qu'un champ, pour ne pas entrer
    en conflit avec la vignette (sprite du Pokémon, boss de raid...) déjà utilisée par
    l'embed principal — un embed n'a qu'un seul emplacement de vignette possible."""
    ligne = reagir(situation, **contexte)
    if not ligne:
        return None
    embed = discord.Embed(description=f"**{NOM_RIVAL}** : *{ligne}*", color=discord.Color.dark_grey())
    embed.set_thumbnail(url=IMAGE_RIVAL)
    return embed
