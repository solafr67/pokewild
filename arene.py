"""Arène (PvE) — spawn à intervalle fixe dans le channel Aventure, un type de Pokémon
tiré au hasard à chaque fois. 3 combats d'affilée contre des dresseurs générés (2
Apprentis + le Champion, tous du type de l'arène), en réutilisant entièrement le moteur
dresseurs.py. Plusieurs joueurs peuvent tenter la même arène en parallèle, chacun son
run indépendant — une défaite met fin au run entier (retenter au prochain spawn).

Le Champion battu pour la première fois donne un badge PERMANENT (voir
database.accorder_badge_arene), qui apporte un petit bonus de dégâts durable pour les
attaques de ce type (voir config.ARENE_BONUS_DEGATS_PAR_BADGE, appliqué dans combat.py).
"""

import asyncio
import random
import time

import discord

import combat as combat_module
import config
import database
import dresseurs as dresseurs_module
import equipe_combat
import journal
from pokemon_data import EMOJI_TYPES, POKEDEX

NOMS_APPRENTI_1 = "Apprenti d'Arène"
NOMS_APPRENTI_2 = "Apprenti d'Arène Confirmé"


def _nom_champion(type_arene: str) -> str:
    return f"Champion {type_arene.capitalize()}"


def _archetype_etape(type_arene: str, etape: int) -> dict:
    """etape : 1 = premier Apprenti, 2 = second Apprenti, 3 = Champion."""
    if etape == 1:
        return {
            "nom": NOMS_APPRENTI_1, "types_theme": [type_arene], "tier": 1,
            "taille_equipe": config.ARENE_TAILLE_APPRENTI_1, "recompense_independante": True,
        }
    if etape == 2:
        return {
            "nom": NOMS_APPRENTI_2, "types_theme": [type_arene], "tier": 2,
            "taille_equipe": config.ARENE_TAILLE_APPRENTI_2, "recompense_independante": True,
        }
    return {
        "nom": _nom_champion(type_arene),
        "types_theme": [type_arene],
        "tier": 3,
        "taille_equipe": config.ARENE_TAILLE_CHAMPION,
        "raretes_autorisees": config.ARENE_RARETES_CHAMPION,
        "recompense_independante": True,
    }


def construire_embed_spawn(type_arene: str, date_expiration: int) -> discord.Embed:
    emoji = EMOJI_TYPES.get(type_arene, "")
    minutes = max(0, round((date_expiration - time.time()) / 60))
    embed = discord.Embed(
        title=f"🏟️ Arène {emoji} {type_arene.capitalize()} !",
        description=(
            f"Une arène **{type_arene.capitalize()}** vient d'ouvrir ! Affronte à la suite "
            f"2 Apprentis puis le **Champion** ({', '.join(sorted(config.ARENE_RARETES_CHAMPION))} minimum) "
            f"pour décrocher son badge.\n\n"
            f"⚠️ Une défaite met fin à ta tentative — il faudra attendre la prochaine arène "
            f"pour retenter. Plusieurs joueurs peuvent s'y essayer en parallèle."
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text=f"Disponible encore ~{minutes} min")
    return embed


class VueDefierArene(discord.ui.View):
    """Vue persistante attachée au message de spawn — n'importe quel joueur peut cliquer
    Défier pour démarrer SON run (une seule tentative par joueur et par spawn)."""

    def __init__(self, bot, arene_id: int):
        super().__init__(timeout=config.ARENE_DUREE_DISPONIBLE_MINUTES * 60)
        self.bot = bot
        self.arene_id = arene_id

        bouton = discord.ui.Button(
            label="Défier l'Arène", emoji="🏟️", style=discord.ButtonStyle.primary,
            custom_id=f"arene_defier_{arene_id}",
        )
        bouton.callback = self._on_defier
        self.add_item(bouton)

    async def _on_defier(self, interaction: discord.Interaction):
        spawn = database.obtenir_arene_spawn(self.arene_id)
        if not spawn or time.time() >= spawn["date_expiration"]:
            await interaction.response.send_message("Cette arène n'est plus disponible.", ephemeral=True)
            return

        if not database.creer_run_arene(self.arene_id, interaction.user.id):
            await interaction.response.send_message(
                "Tu as déjà tenté cette arène (gagné ou perdu, une seule chance par ouverture).",
                ephemeral=True,
            )
            return

        if not database.obtenir_equipe_combat_disponible(interaction.user.id):
            database.terminer_run_arene(self.arene_id, interaction.user.id, "defaite")
            await interaction.response.send_message(
                "❌ Configure ton équipe de combat d'abord (`/equipe-combat`) !", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🏟️ Tu entres dans l'arène **{spawn['type_arene'].capitalize()}** ! Premier combat...",
            ephemeral=True,
        )
        await _lancer_etape(self.bot, interaction.user, interaction.channel, self.arene_id, spawn["type_arene"], etape=1)


async def _lancer_etape(bot, joueur: discord.Member, channel: discord.TextChannel, arene_id: int, type_arene: str, etape: int):
    archetype = _archetype_etape(type_arene, etape)
    multiplicateur = config.ARENE_MULTIPLICATEUR_CHAMPION if etape == 3 else 1.0

    dresseur_id = database.creer_dresseur_actif(archetype["nom"], channel.id, int(time.time()) + 300)

    async def _apres_combat(gagne: bool, joueur_id: int, thread):
        await _resoudre_etape(bot, joueur_id, channel, arene_id, type_arene, etape, gagne, thread)

    await dresseurs_module.demarrer_combat_dresseur(
        bot, joueur, dresseur_id, channel,
        multiplicateur_pc=multiplicateur, apres_combat=_apres_combat, archetype_direct=archetype,
    )


async def _resoudre_etape(bot, joueur_id, channel, arene_id, type_arene, etape, gagne, thread):
    if not gagne:
        database.terminer_run_arene(arene_id, joueur_id, "defaite")
        try:
            await thread.send(
                f"💀 <@{joueur_id}> — ta tentative d'arène s'arrête là. Retente ta chance à la prochaine ouverture !"
            )
        except discord.HTTPException:
            pass
        return

    database.avancer_run_arene(arene_id, joueur_id, etape)

    if etape < 3:
        vue = VueContinuerArene(bot, joueur_id, channel, arene_id, type_arene, etape)
        try:
            await thread.send(
                f"🏟️ <@{joueur_id}> — victoire ! Prêt·e pour le combat suivant, ou tu préfères "
                f"soigner ton équipe avant (1 potion par Pokémon soigné) ?",
                view=vue,
            )
        except discord.HTTPException:
            pass
        return

    # Étape 3 = Champion battu : récompense + badge
    database.terminer_run_arene(arene_id, joueur_id, "victoire")
    mini, maxi = config.ARENE_RECOMPENSE_DOLLARS_CHAMPION
    dollars = round(random.randint(mini, maxi) * database.multiplicateur_boost(joueur_id, "argent"))
    database.ajouter_poke_dollars(joueur_id, dollars)

    nouveau_badge = database.accorder_badge_arene(joueur_id, type_arene)
    journal.logger(f"🏟️ <@{joueur_id}> a vaincu le {_nom_champion(type_arene)} !" + (" (nouveau badge)" if nouveau_badge else ""))

    emoji = EMOJI_TYPES.get(type_arene, "")
    texte = f"🏆 <@{joueur_id}> a vaincu le **{_nom_champion(type_arene)}** ! +{dollars} Poké Dollars"
    if nouveau_badge:
        bonus_pourcent = round(config.ARENE_BONUS_DEGATS_PAR_BADGE * 100)
        texte += (
            f"\n🎖️ **Nouveau badge {emoji} {type_arene.capitalize()} !** +{bonus_pourcent}% de dégâts "
            f"permanents avec les attaques de ce type."
        )
    try:
        await thread.send(texte)
    except discord.HTTPException:
        pass


class VueContinuerArene(discord.ui.View):
    """Entre deux combats d'un run d'arène : soin auto (1 potion par Pokémon soigné) ou continuer direct."""

    def __init__(self, bot, joueur_id: int, channel: discord.TextChannel, arene_id: int, type_arene: str, etape_terminee: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.joueur_id = joueur_id
        self.channel = channel
        self.arene_id = arene_id
        self.type_arene = type_arene
        self.etape_terminee = etape_terminee

        bouton_continuer = discord.ui.Button(label="Continuer", emoji="⚔️", style=discord.ButtonStyle.primary)
        bouton_continuer.callback = self._on_continuer
        self.add_item(bouton_continuer)

        bouton_soigner = discord.ui.Button(label="Soin auto", emoji="🧪", style=discord.ButtonStyle.success)
        bouton_soigner.callback = self._on_soigner
        self.add_item(bouton_soigner)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("Ce n'est pas ton run d'arène !", ephemeral=True)
            return False
        return True

    async def _on_continuer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.clear_items()
        await interaction.response.edit_message(view=self)
        await _lancer_etape(self.bot, interaction.user, self.channel, self.arene_id, self.type_arene, self.etape_terminee + 1)

    async def _on_soigner(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return

        noms_equipe = database.obtenir_equipe_combat_disponible(self.joueur_id)
        blesses = []
        for nom in noms_equipe:
            pv_max = combat_module.stats_combattant_reel(self.joueur_id, nom)["pv"]
            pv_actuels = database.obtenir_pv_actuels(self.joueur_id, nom, pv_max)
            if pv_actuels < pv_max:
                blesses.append((nom, pv_actuels, pv_max))

        if not blesses:
            await interaction.response.send_message("Ton équipe est déjà au maximum de ses PV !", ephemeral=True)
            return

        lignes, total_potions_utilisees = equipe_combat.soigner_toute_equipe_auto(self.joueur_id, blesses)
        if not lignes:
            await interaction.response.send_message(
                "Tu n'as aucune potion en stock — continue tel quel, ou reviens au prochain "
                "spawn une fois réapprovisionné (ce run reste perdu si tu abandonnes maintenant).",
                ephemeral=True,
            )
            return

        self.clear_items()
        await interaction.response.edit_message(
            content=(
                f"🩹 **Soin auto** ({total_potions_utilisees} potion(s) utilisée(s)) :\n" + "\n".join(lignes)
            ),
            view=self,
        )
        await _lancer_etape(self.bot, interaction.user, self.channel, self.arene_id, self.type_arene, self.etape_terminee + 1)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        database.terminer_run_arene(self.arene_id, self.joueur_id, "defaite")


async def demarrer_nouvelle_arene(bot, channel, type_arene: str = None) -> int:
    """Ouvre une nouvelle arène dans ce channel (type aléatoire si non précisé).
    Retourne l'ID de l'arène créée."""
    type_arene = type_arene or random.choice(list(EMOJI_TYPES.keys()))
    date_expiration = int(time.time()) + config.ARENE_DUREE_DISPONIBLE_MINUTES * 60
    arene_id = database.creer_arene_spawn(type_arene, channel.id, date_expiration)

    embed = construire_embed_spawn(type_arene, date_expiration)
    vue = VueDefierArene(bot, arene_id)
    await channel.send(embed=embed, view=vue)
    journal.logger(f"🏟️ Nouvelle arène {type_arene} ouverte.")
    return arene_id


async def boucle_arene(bot):
    """Toutes les config.ARENE_INTERVALLE_HEURES, ouvre une nouvelle arène d'un type
    aléatoire dans config.CHANNEL_ARENE_ID."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        await asyncio.sleep(config.ARENE_INTERVALLE_HEURES * 3600)

        try:
            channel_id = getattr(config, "CHANNEL_ARENE_ID", None)
            if not channel_id:
                continue
            channel = bot.get_channel(channel_id)
            if channel is None:
                print("⚠️ CHANNEL_ARENE_ID introuvable — vérifie l'ID dans config.py.")
                continue

            await demarrer_nouvelle_arene(bot, channel)
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_arene (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_arene` — voir les logs serveur.")
