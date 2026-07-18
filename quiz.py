"""Quiz communautaire multi-thèmes, posté dans un channel dédié (config.CHANNEL_QUIZ_ID).
Une question à la fois, un thème choisi au hasard parmi 4 (même chance chacun) :
- Qui est-ce ? (silhouette d'un Pokémon, réponse tapée dans le channel)
- Anagramme (nom mélangé, réponse tapée dans le channel)
- Quiz de types (QCM par boutons, table d'efficacité déjà utilisée en combat)
- Trivia (QCM par boutons, questions sur les règles de PokéWild lui-même — jamais fausses
  puisqu'elles pointent directement vers les constantes du jeu)

Dès qu'un joueur trouve, on enchaîne sur une nouvelle question après une courte pause.
Pur fun, aucune récompense.
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
from equipe_combat import TAILLE_MAX_EQUIPE
from pokemon_data import EFFICACITE_TYPES, EMOJI_TYPES, POKEDEX, affichage_types, calculer_multiplicateur_type

URL_ARTWORK_OFFICIEL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{numero}.png"

TRIVIA = [
    {
        "question": "Quel est le niveau maximum qu'un Pokémon peut atteindre dans PokéWild ?",
        "choix": ["50", "75", "100", "200"],
        "bonne": "100",
    },
    {
        "question": "Combien de Pokémon peux-tu avoir dans ton équipe de combat ?",
        "choix": [str(TAILLE_MAX_EQUIPE - 1), str(TAILLE_MAX_EQUIPE), str(TAILLE_MAX_EQUIPE + 1), "8"],
        "bonne": str(TAILLE_MAX_EQUIPE),
    },
    {
        "question": "Combien de Pokémon envoie-t-on en Exploration à la fois ?",
        "choix": ["1", "2", "3", "4"],
        "bonne": str(config.EXPLORATION_TAILLE_EQUIPE),
    },
    {
        "question": "Une CT achetée à la Boutique du Maître des Types...",
        "choix": [
            "Ne sert qu'une seule fois",
            "Est possédée pour toujours, sur tous tes Pokémon",
            "Expire au bout d'une semaine",
            "Ne fonctionne que sur l'espèce achetée",
        ],
        "bonne": "Est possédée pour toujours, sur tous tes Pokémon",
    },
    {
        "question": "Quel est le seul moyen d'apprendre une attaque sans attendre le niveau requis ?",
        "choix": ["Une CT achetée en boutique", "Un objet rare", "Rien, il faut toujours attendre", "Un Cristal de Mutation"],
        "bonne": "Une CT achetée en boutique",
    },
]


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


class VueQCM(discord.ui.View):
    """Vue générique pour les thèmes en QCM (Quiz de types, Trivia)."""

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
    candidats = [p for p in POKEDEX if p.get("numero")]
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


async def _poser_trivia(channel):
    q = random.choice(TRIVIA)
    choix = list(q["choix"])
    random.shuffle(choix)

    etat.theme = "trivia"
    etat.reponse_texte = None
    etat.reponse_affichee = q["bonne"]

    embed = discord.Embed(title="🎓 Trivia PokéWild", description=q["question"], color=discord.Color.teal())
    vue = VueQCM(choix, q["bonne"])
    await channel.send(embed=embed, view=vue)


async def poser_nouvelle_question(channel):
    etat.reinitialiser()
    themes = ["qui_est_ce", "anagramme", "quiz_types", "trivia"]
    theme = random.choice(themes)

    if theme == "qui_est_ce":
        if not await _poser_qui_est_ce(channel):
            theme = random.choice(["anagramme", "quiz_types", "trivia"])
        else:
            return

    if theme == "quiz_types":
        if not await _poser_quiz_types(channel):
            theme = "trivia"
        else:
            return

    if theme == "trivia":
        await _poser_trivia(channel)
    elif theme == "anagramme":
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
