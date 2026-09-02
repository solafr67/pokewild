"""Casino du Village Pokémon — Blackjack et Roulette, mises en Poké Dollars.

Toute la logique de jeu (deck, valeur de main, résolution, roulette) est volontairement
séparée de l'interface Discord ci-dessous : ce sont des fonctions PURES (aucun accès
base de données, aucun état caché), pour pouvoir les tester exhaustivement sans avoir à
simuler la moindre interaction Discord — un vrai système d'argent mérite cette rigueur.
"""

import asyncio
import random

import discord

import config
import database
from pokemon_data import EMOJI_POKEDOLLAR

MISE_MINIMUM = 50

# ============================================================================
# Blackjack — logique pure
# ============================================================================

VALEURS_CARTES = {
    "A": 11, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "10": 10, "V": 10, "D": 10, "R": 10,
}
COULEURS_CARTES = ["♠️", "♥️", "♦️", "♣️"]


def nouveau_deck() -> list:
    """Un deck de 52 cartes mélangé — (valeur, couleur), ex: ('A', '♠️')."""
    deck = [(valeur, couleur) for valeur in VALEURS_CARTES for couleur in COULEURS_CARTES]
    random.shuffle(deck)
    return deck


def valeur_main(cartes: list) -> int:
    """Valeur totale d'une main, As comptés à 11 sauf si ça ferait dépasser 21 (alors 1
    à la place, un à la fois — la règle "soft/hard" habituelle du Blackjack)."""
    total = sum(VALEURS_CARTES[c[0]] for c in cartes)
    nb_as = sum(1 for c in cartes if c[0] == "A")
    while total > 21 and nb_as > 0:
        total -= 10
        nb_as -= 1
    return total


def est_blackjack(cartes: list) -> bool:
    """21 avec exactement 2 cartes (les 2 premières) — un blackjack "naturel"."""
    return len(cartes) == 2 and valeur_main(cartes) == 21


def carte_texte(carte: tuple) -> str:
    valeur, couleur = carte
    return f"{valeur}{couleur}"


def main_texte(cartes: list) -> str:
    return " ".join(carte_texte(c) for c in cartes)


def jouer_croupier(cartes_croupier: list, deck: list):
    """Le croupier tire tant que sa main est sous 17 (règle standard "stand on all
    17s") — modifie cartes_croupier et deck EN PLACE."""
    while valeur_main(cartes_croupier) < 17:
        cartes_croupier.append(deck.pop())


def resoudre_blackjack(cartes_joueur: list, cartes_croupier: list) -> tuple:
    """Retourne (resultat, multiplicateur_retour) :
    - resultat : 'blackjack' / 'gagne' / 'perd' / 'egalite'
    - multiplicateur_retour : ce que le joueur récupère au total (mise incluse) —
      0 = mise perdue en entier, 1 = mise rendue (égalité), 2 = mise doublée (gain 1:1),
      2.5 = blackjack naturel (gain 3:2).
    Un bust (main joueur > 21) perd immédiatement, sans même regarder le croupier."""
    valeur_joueur = valeur_main(cartes_joueur)
    if valeur_joueur > 21:
        return "perd", 0

    valeur_croupier = valeur_main(cartes_croupier)
    joueur_bj = est_blackjack(cartes_joueur)
    croupier_bj = est_blackjack(cartes_croupier)

    if joueur_bj and croupier_bj:
        return "egalite", 1
    if joueur_bj:
        return "blackjack", 2.5
    if croupier_bj:
        return "perd", 0
    if valeur_croupier > 21:
        return "gagne", 2
    if valeur_joueur > valeur_croupier:
        return "gagne", 2
    if valeur_joueur < valeur_croupier:
        return "perd", 0
    return "egalite", 1


# ============================================================================
# Roulette — logique pure (roulette européenne, un seul zéro)
# ============================================================================

NUMEROS_ROUGES = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def couleur_numero(numero: int) -> str:
    if numero == 0:
        return "vert"
    return "rouge" if numero in NUMEROS_ROUGES else "noir"


def tirer_roulette() -> int:
    return random.randint(0, 36)


# Chaque mise "cote" = multiplicateur de RETOUR TOTAL (mise incluse), pas juste le gain
# net — ex: "rouge" à cote=2 veut dire "tu récupères 2x ta mise si tu gagnes" (gain 1:1).
TYPES_MISE_ROULETTE = {
    "rouge": {"nom": "Rouge", "emoji": "🔴", "cote": 2, "gagne": lambda n: couleur_numero(n) == "rouge"},
    "noir": {"nom": "Noir", "emoji": "⚫", "cote": 2, "gagne": lambda n: couleur_numero(n) == "noir"},
    "pair": {"nom": "Pair", "emoji": "🔢", "cote": 2, "gagne": lambda n: n != 0 and n % 2 == 0},
    "impair": {"nom": "Impair", "emoji": "🔢", "cote": 2, "gagne": lambda n: n != 0 and n % 2 == 1},
    "manque": {"nom": "1-18", "emoji": "⬇️", "cote": 2, "gagne": lambda n: 1 <= n <= 18},
    "passe": {"nom": "19-36", "emoji": "⬆️", "cote": 2, "gagne": lambda n: 19 <= n <= 36},
}
COTE_NUMERO_PLEIN = 36  # 35:1 + mise rendue = x36 au total


def resoudre_roulette(numero_tire: int, type_mise: str, numero_parie: int = None) -> tuple:
    """Retourne (gagne: bool, multiplicateur_retour: float). type_mise="plein" utilise
    numero_parie (0-36) au lieu du dict TYPES_MISE_ROULETTE."""
    if type_mise == "plein":
        gagne = numero_tire == numero_parie
        return gagne, COTE_NUMERO_PLEIN if gagne else 0

    info = TYPES_MISE_ROULETTE[type_mise]
    gagne = info["gagne"](numero_tire)
    return gagne, info["cote"] if gagne else 0


# ============================================================================
# Interface Discord
# ============================================================================

MISE_MAXIMUM = 10000


def _valider_mise(user_id: int, texte: str):
    """Retourne (True, mise_int) si valide, sinon (False, message_erreur) — vérifie
    format, bornes min/max, et solde suffisant, dans cet ordre."""
    texte = texte.strip()
    if not texte.isdigit():
        return False, "❌ Merci d'entrer un nombre entier positif."
    mise = int(texte)
    if mise < MISE_MINIMUM:
        return False, f"❌ Mise minimum : {MISE_MINIMUM} {EMOJI_POKEDOLLAR}."
    if mise > MISE_MAXIMUM:
        return False, f"❌ Mise maximum : {MISE_MAXIMUM} {EMOJI_POKEDOLLAR}."
    solde = database.obtenir_poke_dollars(user_id)
    if mise > solde:
        return False, f"❌ Solde insuffisant — tu as {solde} {EMOJI_POKEDOLLAR}, il t'en faut {mise}."
    return True, mise


def construire_embed_casino() -> discord.Embed:
    embed = discord.Embed(
        title="🎰 Casino",
        description=(
            f"Mise tes Poké Dollars — mise min. **{MISE_MINIMUM}**, max. **{MISE_MAXIMUM}** {EMOJI_POKEDOLLAR}.\n\n"
            "🃏 **Blackjack** — approche-toi de 21 sans le dépasser, bats le croupier. "
            "Blackjack naturel payé 3:2, victoire normale 1:1.\n"
            "🎡 **Roulette** — mise sur une couleur, pair/impair, une plage, ou un numéro plein (35:1)."
        ),
        color=discord.Color.dark_gold(),
    )
    return embed


class VueCasino(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Blackjack", emoji="🃏", style=discord.ButtonStyle.primary)
    async def blackjack(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalMiseBlackjack())

    @discord.ui.button(label="Roulette", emoji="🎡", style=discord.ButtonStyle.primary)
    async def roulette(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🎡 Choisis ton type de mise :", view=VueChoixMiseRoulette(), ephemeral=True
        )


# --- Blackjack ---

def _construire_embed_blackjack(mise: int, cartes_joueur: list, cartes_croupier: list, revele: bool, resultat_texte: str = None) -> discord.Embed:
    embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.dark_green())
    embed.add_field(name=f"Ta main ({valeur_main(cartes_joueur)})", value=main_texte(cartes_joueur), inline=False)
    if revele:
        embed.add_field(name=f"Main du croupier ({valeur_main(cartes_croupier)})", value=main_texte(cartes_croupier), inline=False)
    else:
        embed.add_field(name="Main du croupier (1 carte cachée)", value=f"{carte_texte(cartes_croupier[0])} 🎴", inline=False)
    embed.add_field(name="Mise", value=f"{mise} {EMOJI_POKEDOLLAR}", inline=True)
    if resultat_texte:
        embed.description = resultat_texte
    return embed


def _texte_resultat_blackjack(resultat: str, mise: int, gain_total: int) -> str:
    return {
        "blackjack": f"🎉 **BLACKJACK !** Tu remportes {gain_total} {EMOJI_POKEDOLLAR} (mise x2.5).",
        "gagne": f"✅ Tu gagnes ! Total récupéré : {gain_total} {EMOJI_POKEDOLLAR}",
        "perd": f"❌ Tu perds ta mise de {mise} {EMOJI_POKEDOLLAR}.",
        "egalite": f"🤝 Égalité — ta mise de {mise} {EMOJI_POKEDOLLAR} t'est rendue.",
    }[resultat]


def _resoudre_et_crediter_final(user_id: int, mise: int, cartes_joueur: list, cartes_croupier: list) -> discord.Embed:
    """Résout la partie avec les mains DÉJÀ complètes (croupier ayant déjà fini de
    tirer, ou joueur ayant déjà brûlé), crédite le gain éventuel en base, et retourne
    l'embed final. Fonction PURE côté logique (le seul effet de bord est le crédit en
    base) — délibérément séparée de l'animation du croupier ci-dessous, pour rester
    testable sans avoir à simuler la moindre interaction Discord."""
    resultat, multiplicateur = resoudre_blackjack(cartes_joueur, cartes_croupier)
    gain_total = round(mise * multiplicateur)
    if gain_total > 0:
        database.ajouter_poke_dollars(user_id, gain_total)
    texte = _texte_resultat_blackjack(resultat, mise, gain_total)
    return _construire_embed_blackjack(mise, cartes_joueur, cartes_croupier, revele=True, resultat_texte=texte)


DELAI_ANIMATION_CARTE = 1.1  # secondes entre chaque carte affichée (distribution ET
# tour du croupier) — la partie doit vraiment se dérouler sous les yeux du joueur,
# jamais un résultat final tout fait d'un coup.


def _construire_embed_distribution(mise: int, cartes_joueur: list, cartes_croupier: list) -> discord.Embed:
    """Version de l'embed utilisée PENDANT la distribution initiale — mains
    potentiellement incomplètes (0 ou 1 carte), contrairement à _construire_embed_blackjack
    qui suppose toujours au moins 1 carte de chaque côté."""
    embed = discord.Embed(title="🃏 Blackjack", description="🎴 Distribution en cours...", color=discord.Color.dark_green())
    nom_joueur = f"Ta main ({valeur_main(cartes_joueur)})" if cartes_joueur else "Ta main"
    embed.add_field(name=nom_joueur, value=main_texte(cartes_joueur) if cartes_joueur else "…", inline=False)

    if len(cartes_croupier) >= 2:
        nom_croupier, valeur_croupier = "Main du croupier (1 carte cachée)", f"{carte_texte(cartes_croupier[0])} 🎴"
    elif len(cartes_croupier) == 1:
        nom_croupier, valeur_croupier = "Main du croupier", carte_texte(cartes_croupier[0])
    else:
        nom_croupier, valeur_croupier = "Main du croupier", "…"
    embed.add_field(name=nom_croupier, value=valeur_croupier, inline=False)
    embed.add_field(name="Mise", value=f"{mise} {EMOJI_POKEDOLLAR}", inline=True)
    return embed


async def _animer_croupier_et_resoudre(interaction: discord.Interaction, user_id: int, mise: int, cartes_joueur: list, cartes_croupier: list, deck: list):
    """Fait jouer le croupier carte par carte (une édition de message entre chaque
    tirage, avec une pause), PUIS résout la partie et affiche le résultat final. Suppose
    que l'interaction a déjà été deferred par l'appelant. Si le joueur a déjà brûlé, le
    croupier ne tire rien du tout (partie déjà perdue, voir _resoudre_et_crediter_final)."""
    if valeur_main(cartes_joueur) <= 21:
        while valeur_main(cartes_croupier) < 17:
            await asyncio.sleep(DELAI_ANIMATION_CARTE)
            cartes_croupier.append(deck.pop())
            embed_intermediaire = _construire_embed_blackjack(mise, cartes_joueur, cartes_croupier, revele=True)
            embed_intermediaire.description = "🎴 Le croupier tire une carte..."
            await interaction.edit_original_response(embed=embed_intermediaire, view=None)

    embed_final = _resoudre_et_crediter_final(user_id, mise, cartes_joueur, cartes_croupier)
    await interaction.edit_original_response(embed=embed_final, view=None)


class ModalMiseBlackjack(discord.ui.Modal, title="Blackjack — Mise"):
    mise_input = discord.ui.TextInput(label=f"Montant ({MISE_MINIMUM}-{MISE_MAXIMUM} PD)", placeholder=str(MISE_MINIMUM), max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        ok, resultat = _valider_mise(interaction.user.id, self.mise_input.value)
        if not ok:
            await interaction.response.send_message(resultat, ephemeral=True)
            return
        mise = resultat
        user_id = interaction.user.id
        database.ajouter_poke_dollars(user_id, -mise)

        deck = nouveau_deck()
        cartes_joueur = []
        cartes_croupier = []
        vue = VueBlackjack(user_id, mise, cartes_joueur, cartes_croupier, deck)
        for item in vue.children:
            item.disabled = True  # inactifs tant que la distribution n'est pas terminée

        # La vue est attachée dès ce PREMIER envoi (via response.send_message, la voie
        # fiable déjà éprouvée ailleurs dans ce fichier) — les éditions suivantes ne
        # font que mettre à jour CETTE MÊME vue déjà en place (la réactiver à la fin),
        # jamais en attacher une nouvelle après coup via edit_original_response (piste
        # d'un bug réel signalé : les boutons Tirer/Rester disparaissaient totalement
        # avec cette dernière approche, sans que je puisse le vérifier en conditions
        # réelles faute de connexion Discord dans mon environnement de test).
        cartes_joueur.append(deck.pop())
        embed = _construire_embed_distribution(mise, cartes_joueur, cartes_croupier)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

        for cible in (cartes_croupier, cartes_joueur, cartes_croupier):
            await asyncio.sleep(DELAI_ANIMATION_CARTE)
            cible.append(deck.pop())
            embed_etape = _construire_embed_distribution(mise, cartes_joueur, cartes_croupier)
            await interaction.edit_original_response(embed=embed_etape)

        if est_blackjack(cartes_joueur):
            # Le croupier doit quand même jouer sa main (pour vérifier une éventuelle
            # égalité) — edit_original_response() suffit pour l'animer, pas besoin (et
            # surtout pas correct) d'un followup.send() qui créerait un DEUXIÈME
            # message séparé, jamais retouché par la suite (vécu en test réel : 2
            # messages Blackjack distincts affichés au lieu d'un seul).
            embed_initial = _construire_embed_blackjack(mise, cartes_joueur, cartes_croupier, revele=True)
            embed_initial.description = "🎉 Blackjack naturel ! Le croupier joue sa main..."
            await interaction.edit_original_response(embed=embed_initial, view=None)
            await _animer_croupier_et_resoudre(interaction, user_id, mise, cartes_joueur, cartes_croupier, deck)
            return

        for item in vue.children:
            item.disabled = False
        embed_final = _construire_embed_blackjack(mise, cartes_joueur, cartes_croupier, revele=False)
        await interaction.edit_original_response(embed=embed_final, view=vue)


class VueBlackjack(discord.ui.View):
    def __init__(self, user_id: int, mise: int, cartes_joueur: list, cartes_croupier: list, deck: list):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.mise = mise
        self.cartes_joueur = cartes_joueur
        self.cartes_croupier = cartes_croupier
        self.deck = deck

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta partie !", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Tirer", emoji="🎴", style=discord.ButtonStyle.primary)
    async def tirer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        self.cartes_joueur.append(self.deck.pop())
        if valeur_main(self.cartes_joueur) > 21:
            # Bust : le croupier ne joue même pas, résolution immédiate sans animation.
            embed = _resoudre_et_crediter_final(self.user_id, self.mise, self.cartes_joueur, self.cartes_croupier)
            await interaction.response.edit_message(embed=embed, view=None)
            return
        embed = _construire_embed_blackjack(self.mise, self.cartes_joueur, self.cartes_croupier, revele=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Rester", emoji="✋", style=discord.ButtonStyle.secondary)
    async def rester(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.defer()
        await _animer_croupier_et_resoudre(interaction, self.user_id, self.mise, self.cartes_joueur, self.cartes_croupier, self.deck)


# --- Roulette ---

async def _jouer_roulette(interaction: discord.Interaction, mise: int, type_mise: str, numero_parie: int = None):
    user_id = interaction.user.id
    database.ajouter_poke_dollars(user_id, -mise)

    numero_tire = tirer_roulette()
    gagne, multiplicateur = resoudre_roulette(numero_tire, type_mise, numero_parie)
    gain_total = round(mise * multiplicateur)
    if gain_total > 0:
        database.ajouter_poke_dollars(user_id, gain_total)

    emoji_couleur = {"rouge": "🔴", "noir": "⚫", "vert": "🟢"}[couleur_numero(numero_tire)]

    embed = discord.Embed(title="🎡 Roulette")
    embed.description = f"La bille s'arrête sur **{numero_tire}** {emoji_couleur}\n\n"
    if gagne:
        embed.description += f"🎉 Tu gagnes ! Total récupéré : {gain_total} {EMOJI_POKEDOLLAR}"
        embed.color = discord.Color.green()
    else:
        embed.description += f"❌ Tu perds ta mise de {mise} {EMOJI_POKEDOLLAR}."
        embed.color = discord.Color.red()
    await interaction.response.send_message(embed=embed, ephemeral=True)


class VueChoixMiseRoulette(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        for cle, info in TYPES_MISE_ROULETTE.items():
            bouton = discord.ui.Button(label=info["nom"], emoji=info["emoji"], style=discord.ButtonStyle.primary)
            bouton.callback = self._creer_callback(cle)
            self.add_item(bouton)
        bouton_plein = discord.ui.Button(label="Numéro plein (35:1)", emoji="🎯", style=discord.ButtonStyle.danger)
        bouton_plein.callback = self._callback_plein
        self.add_item(bouton_plein)

    def _creer_callback(self, type_mise: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(ModalMiseRoulette(type_mise))
        return callback

    async def _callback_plein(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ModalMiseRouletteNumeroPlein())


class ModalMiseRoulette(discord.ui.Modal):
    def __init__(self, type_mise: str):
        info = TYPES_MISE_ROULETTE[type_mise]
        super().__init__(title=f"Roulette — {info['nom']}"[:45])
        self.type_mise = type_mise
        self.mise_input = discord.ui.TextInput(
            label=f"Montant ({MISE_MINIMUM}-{MISE_MAXIMUM} PD)", placeholder=str(MISE_MINIMUM), max_length=6
        )
        self.add_item(self.mise_input)

    async def on_submit(self, interaction: discord.Interaction):
        ok, resultat = _valider_mise(interaction.user.id, self.mise_input.value)
        if not ok:
            await interaction.response.send_message(resultat, ephemeral=True)
            return
        await _jouer_roulette(interaction, resultat, self.type_mise)


class ModalMiseRouletteNumeroPlein(discord.ui.Modal, title="Roulette — Numéro plein"):
    numero_input = discord.ui.TextInput(label="Numéro (0-36)", placeholder="Ex : 17", max_length=2)
    mise_input = discord.ui.TextInput(label=f"Montant ({MISE_MINIMUM}-{MISE_MAXIMUM} PD)", placeholder=str(MISE_MINIMUM), max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        texte_numero = self.numero_input.value.strip()
        if not texte_numero.isdigit() or not (0 <= int(texte_numero) <= 36):
            await interaction.response.send_message("❌ Le numéro doit être un entier entre 0 et 36.", ephemeral=True)
            return
        numero = int(texte_numero)

        ok, resultat = _valider_mise(interaction.user.id, self.mise_input.value)
        if not ok:
            await interaction.response.send_message(resultat, ephemeral=True)
            return
        await _jouer_roulette(interaction, resultat, "plein", numero)
