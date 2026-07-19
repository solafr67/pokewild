"""Le Rival — PNJ récurrent qui commente les événements marquants du serveur, et qu'on
peut désormais défier directement (voir dresseurs.defier_gladio / /defi-gladio).

V1 : répliques pré-écrites, tirées au hasard, avec quelques valeurs injectées (nom du
joueur, du Pokémon...). Zéro coût, mais réagit toujours de la même poignée de façons.

Système de familiarité : Gladio se souvient (compteur simple en base) de combien de fois
il a déjà réagi à un joueur précis, et adoucit son ton avec le temps — distant au début,
puis plus familier, puis un respect bourru. La familiarité décroît lentement en cas de
longue inactivité (voir database.obtenir_relation_gladio).

Pensé pour un remplacement facile par une vraie génération IA plus tard : tout le reste
du code appelle uniquement `reagir(...)` / `construire_embed_reaction(...)` — le jour où
on branche un LLM, seul le contenu de ces fonctions change, aucun appelant n'a besoin
d'être touché.
"""

import random

import discord

import database

NOM_RIVAL = "Gladio"
EMOJI_RIVAL = "⚔️"
IMAGE_RIVAL = "https://archives.bulbagarden.net/media/upload/4/44/VSGladion_2.png"

# Paliers de familiarité, du plus bas au plus haut — le dernier seuil atteint l'emporte.
SEUILS_RELATION = [(0, "distant"), (3, "familier"), (8, "respect")]

DESCRIPTION_PALIER = {
    "distant": "Gladio te garde à distance. Il commente tes exploits du bout des lèvres, sans vraiment s'impliquer.",
    "familier": "Gladio commence à te connaître. Le ton se détend, il ose même la vanne de temps en temps.",
    "respect": "Gladio te respecte, sincèrement. Ses compliments, rares, sonnent vrai.",
}


def _palier_relation(compteur: int) -> str:
    palier = "distant"
    for seuil, nom in SEUILS_RELATION:
        if compteur >= seuil:
            palier = nom
    return palier


def obtenir_statut(user_id: int) -> dict:
    """Statut de familiarité lisible pour /gladio : compteur effectif, palier actuel, sa
    description, et le nombre d'interactions restantes avant le prochain palier (None si
    déjà au maximum)."""
    compteur = database.obtenir_relation_gladio(user_id)
    palier = _palier_relation(compteur)
    prochain_seuil = next((seuil for seuil, _nom in SEUILS_RELATION if seuil > compteur), None)
    return {
        "compteur": compteur,
        "palier": palier,
        "description": DESCRIPTION_PALIER[palier],
        "prochain_seuil": prochain_seuil,
    }


# Chaque {clé} dans une réplique doit correspondre à un argument passé à reagir(**contexte).
# Les situations liées à un joueur précis sont organisées par palier de familiarité
# (distant/familier/respect) ; les situations "collectives" (spontane) sont une simple liste.
REPLIQUES = {
    "capture_shiny": {
        "distant": [
            "Tiens, {joueur} qui déniche un {pokemon} chromatique... Encore un coup de bol, j'imagine.",
            "Un {pokemon} shiny pour {joueur} ? Pff. Le jour où j'en trouve un, je te préviens.",
            "{joueur} et un {pokemon} brillant. Statistiquement, ça devrait pas arriver aussi souvent.",
        ],
        "familier": [
            "{joueur} et son {pokemon} brillant. T'façon, la chance, c'est pas une stratégie.",
            "Encore un shiny pour toi, {joueur}. Tu commences à avoir un sacré flair.",
            "Un {pokemon} chromatique de plus dans ta collection, {joueur}. J'arrête de compter les coïncidences.",
        ],
        "respect": [
            "Un {pokemon} chromatique de plus... Je dois admettre que ton flair pour ça devient franchement impressionnant.",
            "T'as vraiment un don pour ces trucs rares. Je ne dirai ça qu'une fois.",
            "{joueur}, à ce niveau-là, ce n'est plus de la chance. C'est du talent, et je le reconnais.",
        ],
    },
    "capture_legendaire": {
        "distant": [
            "{joueur} qui capture {pokemon}... Je vais devoir revoir mon équipe, moi.",
            "Un {pokemon} en plus dans l'équipe de {joueur}. Ça devient sérieux.",
            "{pokemon} entre les mains de {joueur} ? Voilà qui change la donne.",
        ],
        "familier": [
            "{pokemon}, capturé par toi ? J'avoue, celui-là, je l'aurais bien voulu aussi.",
            "Tu collectionnes les Légendaires maintenant, {joueur}. Faudra qu'on en reparle.",
            "{joueur}, avec {pokemon} dans ton équipe, tu commences à m'inquiéter un peu.",
        ],
        "respect": [
            "{pokemon}... Sincèrement, bien joué. Peu de monde y arrive.",
            "Un Légendaire de plus pour toi. À ce rythme, c'est moi qui vais devoir m'entraîner plus.",
            "{joueur}. {pokemon}. Je n'ai rien à redire, c'est du grand travail.",
        ],
    },
    "capture_rare": {
        "distant": [
            "{pokemon}, pas mal comme prise pour {joueur}.",
            "{joueur} qui met la main sur {pokemon}... Solide.",
        ],
        "familier": [
            "{pokemon} dans l'équipe de {joueur} ? Bon choix.",
            "T'as l'œil pour ces prises-là, {joueur}.",
        ],
        "respect": [
            "{pokemon}, capturé par {joueur}. Ça ne m'étonne plus venant de toi.",
        ],
    },
    "victoire_raid": {
        "distant": [
            "Raid nettoyé par {joueur} et son équipe. Pas mal, pour une fois.",
            "{joueur} qui termine le raid en tête... Je note.",
            "Ce raid n'a pas fait long feu face à {joueur}.",
        ],
        "familier": [
            "Encore un raid plié. {joueur}, arrête de me donner des complexes.",
            "T'as porté cette équipe, {joueur}. Content de voir que je ne t'ai pas trop mal jugé.",
            "{joueur} qui gère ce raid comme si de rien n'était. J'ai vu.",
        ],
        "respect": [
            "Ce raid, c'était du sérieux, et tu l'as géré comme si de rien n'était. Respect.",
            "{joueur}. C'était du bon travail sur ce raid. Vraiment.",
            "Je ne m'attendais à rien de moins venant de toi, {joueur}. Bien joué.",
        ],
    },
    "defaite_dresseur": {
        "distant": [
            "Perdu contre un simple dresseur, {joueur} ? Reviens quand tu seras prêt.",
            "{joueur} qui se fait battre... Ça arrive aux meilleurs, paraît-il.",
            "Une défaite, {joueur}. Note-le, retiens-en quelque chose.",
        ],
        "familier": [
            "Encore une défaite, {joueur} ? T'inquiète, je suis passé par là aussi.",
            "Ça arrive. Relève-toi et retente ta chance, {joueur}.",
            "{joueur}, une défaite de plus ne change rien à ce que tu vaux vraiment.",
        ],
        "respect": [
            "Une défaite ne veut rien dire venant de toi, {joueur}. On sait tous les deux que tu reviendras plus fort.",
            "{joueur}, même les meilleurs trébuchent. La suite compte plus.",
            "Ça arrive, même aux meilleurs. Et tu en fais partie, {joueur}.",
        ],
    },
    "defaite_pvp": {
        "distant": [
            "Battu en duel, {joueur} ? Ça arrive. Retente ta chance.",
            "{joueur} qui perd un combat... Tout le monde en passe par là.",
        ],
        "familier": [
            "Une défaite en PvP, {joueur}. T'en as vu d'autres, ça va passer.",
            "{joueur}, ça arrive même aux bons. Reviens plus fort.",
        ],
        "respect": [
            "{joueur}, une défaite ne définit pas un dresseur de ton niveau. La revanche, c'est pour bientôt j'imagine.",
        ],
    },
    "serie_victoires_pvp": {
        "distant": [
            "{joueur} qui enchaîne les victoires en PvP... Intéressant.",
            "Une série comme ça, ce n'est pas rien, {joueur}.",
            "{joueur} qui ne perd plus en ce moment. Je surveille.",
        ],
        "familier": [
            "{joueur}, ça fait plusieurs victoires d'affilée maintenant. Je commence à te surveiller de près.",
            "Cette série de victoires n'est pas passée inaperçue, {joueur}.",
            "T'enchaînes les victoires, {joueur}. Faudra qu'on se croise un jour.",
        ],
        "respect": [
            "{joueur}. Cette série de victoires, c'est du niveau championnat. Je suis sérieux.",
            "Personne n'enchaîne comme ça par hasard. Bien joué, {joueur}.",
            "{joueur}, à ce niveau de régularité, tu mérites clairement ta place en haut du classement.",
        ],
    },
    "pokedex_complet": {
        "distant": [
            "{joueur} qui termine le Pokédex... C'est un sacré chantier que tu viens de boucler.",
            "Pokédex complet pour {joueur}. Ça force le respect, même de ma part.",
        ],
        "familier": [
            "Le Pokédex complet, {joueur} ? Sincèrement, chapeau.",
            "{joueur}, tu viens de faire un truc que très peu de monde termine. Bien joué.",
        ],
        "respect": [
            "{joueur}. Le Pokédex complet. Il n'y a pas grand monde qui va jusqu'au bout. Je suis impressionné.",
        ],
    },
    "bienvenue_nouveau_joueur": {
        "distant": [
            "Un nouveau, {joueur} ? On verra si tu tiens la distance.",
            "{joueur} qui débute... Bonne chance, tu vas en avoir besoin.",
            "Encore un nouveau dresseur. On verra ce que ça donne, {joueur}.",
        ],
    },
    "changement_leader_classement": {
        "distant": [
            "{joueur} qui prend la tête du classement... On va voir combien de temps ça dure.",
            "Nouveau nom en tête, {joueur}. Les autres vont vouloir réagir.",
        ],
        "familier": [
            "{joueur} en tête du classement. Ça ne me surprend qu'à moitié, venant de toi.",
        ],
        "respect": [
            "{joueur} qui prend la tête, encore. À ce stade, c'est presque devenu ta place attitrée.",
        ],
    },
    "rejoint_clan": {
        "distant": [
            "{joueur} qui rejoint un clan... Bon choix, ou coup de tête ? On verra bien.",
            "Encore un clan qui se renforce avec {joueur}. Note.",
        ],
        "familier": [
            "{joueur} dans ce clan, ça change un peu la donne. Intéressant.",
        ],
        "respect": [
            "{joueur} qui rejoint un clan — avec ton niveau, ils ont de la chance de t'avoir.",
        ],
    },
    "victoire_gladio": {
        "distant": [
            "...T'as gagné. Cette fois. Ne t'habitue pas trop, {joueur}.",
            "Bien joué, {joueur}. Je ne m'y attendais pas, pour être honnête.",
        ],
        "familier": [
            "{joueur}, tu m'as vraiment battu. J'ai sous-estimé ton équipe, je l'admets.",
            "Une revanche s'impose, {joueur}. Mais pour l'instant... bien joué.",
        ],
        "respect": [
            "{joueur}. Tu m'as battu à la loyale, et je n'ai aucune excuse. Respect total.",
            "Franchement, {joueur}, ce combat restera dans ma mémoire. Bien joué, sincèrement.",
        ],
    },
    # Situation "collective" : pas liée à un joueur précis, pas de palier de relation.
    "spontane": [
        "Je passais par là. Ne vous inquiétez pas, je surveille juste la concurrence.",
        "Un serveur plein de dresseurs qui montent en niveau... Faut que je m'entraîne plus, moi aussi.",
        "Personne ne m'a demandé mon avis, mais ce serveur devient plutôt costaud dernièrement.",
        "Un jour, l'un de vous me battra pour de bon. Ce jour n'est pas encore arrivé.",
    ],
}


def reagir(situation: str, user_id: int | None = None, **contexte) -> str | None:
    """Retourne une réplique du rival pour cette situation, ou None si rien à dire
    (situation inconnue, ou variable de contexte manquante pour la remplir). Si user_id
    est fourni et que la situation a des paliers de familiarité, le ton s'adapte et
    l'interaction est comptabilisée (fait progresser la familiarité pour la prochaine fois)."""
    pool_situation = REPLIQUES.get(situation)
    if not pool_situation:
        return None

    if isinstance(pool_situation, dict):
        palier = _palier_relation(database.obtenir_relation_gladio(user_id)) if user_id is not None else "distant"
        pool = pool_situation.get(palier) or pool_situation.get("distant") or []
    else:
        pool = pool_situation

    if not pool:
        return None

    modele = random.choice(pool)
    try:
        ligne = modele.format(**contexte)
    except KeyError:
        return None

    if user_id is not None and isinstance(pool_situation, dict):
        database.incrementer_relation_gladio(user_id)

    return ligne


def construire_embed_reaction(situation: str, user_id: int | None = None, **contexte) -> discord.Embed | None:
    """Comme reagir(), mais retourne directement un petit embed prêt à ajouter à côté
    de l'embed principal (portrait en vignette) — None si le rival n'a rien à dire cette
    fois. Se pose comme un SECOND embed du message plutôt qu'un champ, pour ne pas entrer
    en conflit avec la vignette (sprite du Pokémon, boss de raid...) déjà utilisée par
    l'embed principal — un embed n'a qu'un seul emplacement de vignette possible."""
    ligne = reagir(situation, user_id=user_id, **contexte)
    if not ligne:
        return None
    embed = discord.Embed(description=f"**{NOM_RIVAL}** : *{ligne}*", color=discord.Color.dark_grey())
    embed.set_thumbnail(url=IMAGE_RIVAL)
    return embed
