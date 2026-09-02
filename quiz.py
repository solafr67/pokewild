"""Quiz communautaire multi-thèmes, posté dans un channel dédié (config.CHANNEL_QUIZ_ID).
Une question à la fois, un thème choisi au hasard parmi 6 (même chance chacun) :
- Qui est-ce ? (silhouette d'un Pokémon, réponse tapée dans le channel)
- Sprite flouté (artwork flouté au filtre gaussien, réponse tapée dans le channel)
- Anagramme (nom mélangé, réponse tapée dans le channel)
- Quiz de types (QCM par boutons, table d'efficacité déjà utilisée en combat)
- Évolution (QCM par boutons, "en quel Pokémon évolue X ?")
- Stats comparées (QCM par boutons, "lequel de ces 4 a la plus haute stat Y ?")

Dès qu'un joueur trouve, on enchaîne sur une nouvelle question après une courte pause.
Une récompense (config.RECOMPENSE_QUIZ_PALIER) tombe tous les config.QUIZ_PALIER_RECOMPENSE
bonnes réponses CUMULÉES d'un même joueur (jamais remis à zéro, peu importe le thème).
"""

import asyncio
import io
import random
import traceback
import unicodedata

import aiohttp
import discord

import config
import database
import journal
import leveling
from equipe_combat import TAILLE_MAX_EQUIPE
from pokemon_data import (
    EFFICACITE_TYPES,
    EMOJI_POKEDOLLAR,
    EMOJI_TYPES,
    EVOLUTIONS_PAR_NIVEAU,
    POKEDEX,
    affichage_types,
    calculer_multiplicateur_type,
    obtenir_pokemon_par_nom,
)

URL_ARTWORK_OFFICIEL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{numero}.png"

STATS_COMPARABLES = {
    "pv": "PV", "attaque": "Attaque", "defense": "Défense",
    "attaque_spe": "Attaque Spé.", "defense_spe": "Défense Spé.", "vitesse": "Vitesse",
}

# Exclus des thèmes basés sur le sprite (Qui est-ce, Sprite flouté) : l'artwork officiel
# de Superdofin (Forme Zéro par défaut) est visuellement quasi identique à Dofin, sa
# pré-évolution — la Forme Héros, bien différente, ne s'active qu'en combat et n'a pas
# d'artwork officiel distinct côté PokéAPI. Deviner d'après le sprite serait donc
# trompeur/injuste pour ce cas précis, contrairement à toutes les autres évolutions.
ESPECES_EXCLUES_SPRITE = {"Superdofin"}


def _normaliser(texte: str) -> str:
    texte = texte.strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


class EtatQuiz:
    """État module-level de la question en cours — un seul quiz actif à la fois."""

    def __init__(self):
        self.theme = None
        self.reponse_texte = None  # normalisée, pour qui_est_ce/anagramme ; None si QCM
        self.reponse_affichee = None
        self.resolu = asyncio.Event()

    def reinitialiser(self):
        self.theme = None
        self.reponse_texte = None
        self.reponse_affichee = None
        self.resolu = asyncio.Event()


etat = EtatQuiz()


async def _appliquer_recompense_si_palier(channel, user_id: int, mention: str):
    """Incrémente le compteur CUMULATIF de bonnes réponses de ce joueur (jamais remis à
    zéro, peu importe le thème) ; si ça tombe sur un multiple de
    config.QUIZ_PALIER_RECOMPENSE, crédite la récompense et l'annonce dans le channel."""
    total = database.incrementer_quiz_bonnes_reponses(user_id)
    if total % config.QUIZ_PALIER_RECOMPENSE != 0:
        return
    recompense = config.RECOMPENSE_QUIZ_PALIER
    database.ajouter_poke_dollars(user_id, recompense["dollars"])
    leveling.gagner_xp(user_id, recompense["xp"])
    await channel.send(
        f"🏆 {mention} vient de trouver sa **{total}e** bonne réponse au quiz — "
        f"+{recompense['dollars']} {EMOJI_POKEDOLLAR} Poké Dollars, +{recompense['xp']} XP !"
    )


async def verifier_reponse_texte(message: discord.Message):
    """Appelée depuis on_message (main.py) pour les thèmes qui_est_ce/anagramme."""
    if etat.reponse_texte is None or etat.resolu.is_set():
        return
    if _normaliser(message.content) != etat.reponse_texte:
        return

    etat.resolu.set()
    try:
        await message.add_reaction("✅")
    except discord.HTTPException:
        pass
    await message.channel.send(f"🎉 {message.author.mention} a trouvé ! C'était **{etat.reponse_affichee}**.")
    await _appliquer_recompense_si_palier(message.channel, message.author.id, message.author.mention)


class VueQCM(discord.ui.View):
    """Vue générique pour les thèmes en QCM (Quiz de types, Évolution, Stats comparées)."""

    def __init__(self, choix: list, bonne_reponse: str):
        super().__init__(timeout=config.QUIZ_TIMEOUT_QUESTION + 10)
        self.bonne_reponse = bonne_reponse
        for option in choix:
            bouton = discord.ui.Button(label=option[:80], style=discord.ButtonStyle.secondary)
            bouton.callback = self._creer_callback(option)
            self.add_item(bouton)

    def _creer_callback(self, option: str):
        async def callback(interaction: discord.Interaction):
            if etat.resolu.is_set():
                await interaction.response.send_message("Cette question est déjà résolue !", ephemeral=True)
                return
            if option == self.bonne_reponse:
                etat.resolu.set()
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(
                    f"🎉 {interaction.user.mention} a trouvé ! C'était **{self.bonne_reponse}**."
                )
                await _appliquer_recompense_si_palier(interaction.channel, interaction.user.id, interaction.user.mention)
            else:
                await interaction.response.send_message("❌ Mauvaise réponse, retente ta chance !", ephemeral=True)

        return callback

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def _generer_silhouette(numero: int) -> discord.File:
    """Télécharge l'artwork officiel et le transforme en silhouette noire (garde juste la
    forme, via le canal alpha). Retourne None si le téléchargement échoue."""
    from PIL import Image

    url = URL_ARTWORK_OFFICIEL.format(numero=numero)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as reponse:
                if reponse.status != 200:
                    return None
                donnees = await reponse.read()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None

    try:
        image = Image.open(io.BytesIO(donnees)).convert("RGBA")
        alpha = image.getchannel("A")
        silhouette = Image.new("RGBA", image.size, (0, 0, 0, 0))
        noir = Image.new("RGBA", image.size, (15, 15, 15, 255))
        silhouette.paste(noir, (0, 0), alpha)
        tampon = io.BytesIO()
        silhouette.save(tampon, format="PNG")
        tampon.seek(0)
    except Exception:
        return None

    return discord.File(tampon, filename="silhouette.png")


async def _poser_qui_est_ce(channel) -> bool:
    """Retourne False si la génération d'image a échoué (l'appelant retombe sur un autre thème)."""
    candidats = [p for p in POKEDEX if p.get("numero") and p["nom"] not in ESPECES_EXCLUES_SPRITE]
    pokemon = random.choice(candidats)
    fichier = await _generer_silhouette(pokemon["numero"])
    if fichier is None:
        return False

    etat.theme = "qui_est_ce"
    etat.reponse_texte = _normaliser(pokemon["nom"])
    etat.reponse_affichee = pokemon["nom"]

    embed = discord.Embed(
        title="❓ Qui est-ce ?",
        description="Tape le nom de ce Pokémon dans le channel !",
        color=discord.Color.purple(),
    )
    embed.add_field(name="💡 Indice", value=f"Type : {affichage_types(pokemon['types'])}", inline=False)
    embed.set_image(url="attachment://silhouette.png")
    await channel.send(embed=embed, file=fichier)
    return True


async def _poser_anagramme(channel):
    pokemon = random.choice(POKEDEX)
    nom = pokemon["nom"]
    lettres = list(nom)
    melange = nom
    for _ in range(20):
        random.shuffle(lettres)
        melange = "".join(lettres)
        if melange.lower() != nom.lower():
            break

    etat.theme = "anagramme"
    etat.reponse_texte = _normaliser(nom)
    etat.reponse_affichee = nom

    embed = discord.Embed(
        title="🔤 Anagramme",
        description=f"Remets les lettres dans l'ordre et tape le nom du Pokémon !\n\n# {melange.upper()}",
        color=discord.Color.orange(),
    )
    embed.add_field(name="💡 Indice", value=f"Type : {affichage_types(pokemon['types'])}", inline=False)
    await channel.send(embed=embed)


async def _poser_quiz_types(channel):
    type_defenseur = random.choice(list(EMOJI_TYPES.keys()))
    types_efficaces = [
        t for t in EMOJI_TYPES if calculer_multiplicateur_type([t], [type_defenseur]) >= 2.0
    ]
    if not types_efficaces:
        return False

    bonne_reponse = random.choice(types_efficaces)
    distracteurs_possibles = [t for t in EMOJI_TYPES if t not in types_efficaces and t != type_defenseur]
    distracteurs = random.sample(distracteurs_possibles, min(3, len(distracteurs_possibles)))
    choix = distracteurs + [bonne_reponse]
    random.shuffle(choix)
    choix_affiches = [c.capitalize() for c in choix]
    bonne_affichee = bonne_reponse.capitalize()

    etat.theme = "quiz_types"
    etat.reponse_texte = None
    etat.reponse_affichee = bonne_affichee

    embed = discord.Embed(
        title="🧩 Quiz de types",
        description=f"Quel type est **super efficace** contre {EMOJI_TYPES[type_defenseur]} **{type_defenseur.capitalize()}** ?",
        color=discord.Color.gold(),
    )
    vue = VueQCM(choix_affiches, bonne_affichee)
    await channel.send(embed=embed, view=vue)
    return True


async def _poser_evolution(channel) -> bool:
    """QCM : en quel Pokémon évolue celui-ci ? Retourne False si jamais aucun Pokémon
    n'a d'évolution en base (ne devrait pas arriver), pour retomber sur un autre thème."""
    candidats = [nom for nom, info in EVOLUTIONS_PAR_NIVEAU.items() if info.get("evolue_vers")]
    if not candidats:
        return False
    nom_base = random.choice(candidats)
    bonne_reponse = EVOLUTIONS_PAR_NIVEAU[nom_base]["evolue_vers"]

    autres_noms = [p["nom"] for p in POKEDEX if p["nom"] not in (nom_base, bonne_reponse)]
    distracteurs = random.sample(autres_noms, min(3, len(autres_noms)))
    choix = distracteurs + [bonne_reponse]
    random.shuffle(choix)

    etat.theme = "evolution"
    etat.reponse_texte = None
    etat.reponse_affichee = bonne_reponse

    pokemon_base = obtenir_pokemon_par_nom(nom_base)
    embed = discord.Embed(
        title="🧬 Évolution",
        description=f"En quel Pokémon évolue **{nom_base}** ?",
        color=discord.Color.green(),
    )
    if pokemon_base:
        embed.add_field(name="💡 Indice", value=f"Type : {affichage_types(pokemon_base['types'])}", inline=False)
    vue = VueQCM(choix, bonne_reponse)
    await channel.send(embed=embed, view=vue)
    return True


async def _poser_stats_comparees(channel) -> bool:
    """QCM : lequel de ces 4 Pokémon a la plus haute stat X ? Quelques tentatives pour
    éviter une égalité entre les 4 tirés (réponse ambiguë) — improbable mais possible,
    d'où le retour False si jamais ça persiste, pour retomber sur un autre thème."""
    stat_cle = random.choice(list(STATS_COMPARABLES.keys()))
    stat_nom = STATS_COMPARABLES[stat_cle]

    for _ in range(10):
        candidats = random.sample(POKEDEX, 4)
        valeurs = [p["stats_detaillees"][stat_cle] for p in candidats]
        if valeurs.count(max(valeurs)) == 1:
            break
    else:
        return False

    meilleur = max(candidats, key=lambda p: p["stats_detaillees"][stat_cle])
    choix = [p["nom"] for p in candidats]

    etat.theme = "stats_comparees"
    etat.reponse_texte = None
    etat.reponse_affichee = meilleur["nom"]

    embed = discord.Embed(
        title="📊 Stats comparées",
        description=f"Lequel de ces 4 Pokémon a la plus haute stat de **{stat_nom}** ?",
        color=discord.Color.blue(),
    )
    vue = VueQCM(choix, meilleur["nom"])
    await channel.send(embed=embed, view=vue)
    return True


async def _generer_sprite_floute(numero: int) -> discord.File:
    """Télécharge l'artwork officiel et lui applique un flou gaussien fort — on devine
    la forme générale et les couleurs, mais pas les détails fins. Retourne None si le
    téléchargement échoue (même repli que _generer_silhouette)."""
    from PIL import Image, ImageFilter

    url = URL_ARTWORK_OFFICIEL.format(numero=numero)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as reponse:
                if reponse.status != 200:
                    return None
                donnees = await reponse.read()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None

    try:
        image = Image.open(io.BytesIO(donnees)).convert("RGBA")
        floute = image.filter(ImageFilter.GaussianBlur(radius=12))
        tampon = io.BytesIO()
        floute.save(tampon, format="PNG")
        tampon.seek(0)
    except Exception:
        return None

    return discord.File(tampon, filename="floute.png")


async def _poser_sprite_floute(channel) -> bool:
    """Retourne False si la génération d'image a échoué (l'appelant retombe sur un autre thème)."""
    candidats = [p for p in POKEDEX if p.get("numero") and p["nom"] not in ESPECES_EXCLUES_SPRITE]
    pokemon = random.choice(candidats)
    fichier = await _generer_sprite_floute(pokemon["numero"])
    if fichier is None:
        return False

    etat.theme = "sprite_floute"
    etat.reponse_texte = _normaliser(pokemon["nom"])
    etat.reponse_affichee = pokemon["nom"]

    embed = discord.Embed(
        title="🌫️ Sprite flouté",
        description="Tape le nom de ce Pokémon dans le channel !",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="💡 Indice", value=f"Type : {affichage_types(pokemon['types'])}", inline=False)
    embed.set_image(url="attachment://floute.png")
    await channel.send(embed=embed, file=fichier)
    return True


# Chaque générateur retourne False pour signaler un échec (l'appelant retente un autre
# thème au hasard) — True ou None (fonctions sans return explicite) = question posée
# avec succès. Beaucoup plus simple à étendre qu'une chaîne de if/else imbriqués à
# mesure que de nouveaux thèmes s'ajoutent.
GENERATEURS_THEME = {
    "qui_est_ce": _poser_qui_est_ce,
    "anagramme": _poser_anagramme,
    "quiz_types": _poser_quiz_types,
    "evolution": _poser_evolution,
    "stats_comparees": _poser_stats_comparees,
    "sprite_floute": _poser_sprite_floute,
}


async def poser_nouvelle_question(channel):
    etat.reinitialiser()
    themes_a_essayer = list(GENERATEURS_THEME.keys())
    random.shuffle(themes_a_essayer)

    for theme in themes_a_essayer:
        resultat = await GENERATEURS_THEME[theme](channel)
        if resultat is not False:
            return

    # Improbable que TOUS les thèmes échouent (nécessiterait un problème réseau pour
    # les deux thèmes basés sur une image ET une égalité en stats comparées) — filet de
    # sécurité sur anagramme, qui ne peut jamais échouer (aucun appel réseau, aucune
    # donnée pouvant manquer).
    await _poser_anagramme(channel)


async def boucle_quiz(bot):
    await bot.wait_until_ready()
    channel = bot.get_channel(config.CHANNEL_QUIZ_ID)
    if channel is None:
        print("⚠️ CHANNEL_QUIZ_ID introuvable — vérifie l'ID dans config.py. Le quiz ne démarre pas.")
        return

    while not bot.is_closed():
        try:
            await poser_nouvelle_question(channel)
            try:
                await asyncio.wait_for(etat.resolu.wait(), timeout=config.QUIZ_TIMEOUT_QUESTION)
            except asyncio.TimeoutError:
                if not etat.resolu.is_set() and etat.reponse_affichee:
                    await channel.send(f"⌛ Personne n'a trouvé ! C'était **{etat.reponse_affichee}**.")
                etat.resolu.set()
        except Exception:
            print("⚠️ Erreur dans boucle_quiz (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_quiz` — voir les logs serveur pour le détail complet.")

        await asyncio.sleep(config.QUIZ_DELAI_PROCHAINE_QUESTION)
