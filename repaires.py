"""Repaires de méchants (PvE) — spawn à intervalle fixe dans le channel Aventure (même
channel que les dresseurs/l'arène, plus simple), une équipe méchante (Team Rocket, Aqua,
Magma, Galactic...) tirée au hasard à chaque fois. 3 combats d'affilée contre des
dresseurs générés (2 Sbires + le Boss, tous des types thématiques de l'équipe — voir
config.EQUIPES_MECHANTES), en réutilisant entièrement le moteur dresseurs.py. Même
structure que l'arène (arene.py), juste indexée par équipe méchante plutôt que par type
Pokémon.

Le Boss battu pour la première fois donne un badge PERMANENT (voir
database.accorder_badge_repaire), qui apporte un petit bonus permanent à UNE catégorie
précise (capture/shiny/argent/xp selon l'équipe — voir config.EQUIPES_MECHANTES et
database.multiplicateur_boost) — PAS un bonus de dégâts par type comme l'arène.

À la victoire du Boss, chaque objet de transformation (voir formes_objets.py) a une
chance INDÉPENDANTE de tomber en plus des Poké Dollars — peu importe l'équipe affrontée,
n'importe quel objet peut sortir. Les CT restent réservées aux Champions d'arène,
jamais données ici.
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
from pokemon_data import POKEDEX

NOMS_SBIRE_1 = "Sbire"
NOMS_SBIRE_2 = "Sbire Confirmé"


def _nom_boss(equipe_mechante: str) -> str:
    return config.EQUIPES_MECHANTES[equipe_mechante]["chef"]


def _archetype_etape(equipe_mechante: str, etape: int) -> dict:
    """etape : 1 = premier Sbire, 2 = second Sbire, 3 = Boss."""
    types_theme = config.EQUIPES_MECHANTES[equipe_mechante]["types_theme"]
    if etape == 1:
        return {
            "nom": f"{NOMS_SBIRE_1} {equipe_mechante}", "types_theme": types_theme, "tier": 1,
            "taille_equipe": config.REPAIRE_TAILLE_SBIRE_1, "recompense_independante": True,
            "sans_recompense_dollars": True,
        }
    if etape == 2:
        return {
            "nom": f"{NOMS_SBIRE_2} {equipe_mechante}", "types_theme": types_theme, "tier": 2,
            "taille_equipe": config.REPAIRE_TAILLE_SBIRE_2, "recompense_independante": True,
            "sans_recompense_dollars": True,
        }
    return {
        "nom": f"{_nom_boss(equipe_mechante)} ({equipe_mechante})",
        "types_theme": types_theme,
        "tier": 3,
        "taille_equipe": config.REPAIRE_TAILLE_BOSS,
        "raretes_autorisees": config.REPAIRE_RARETES_BOSS,
        "recompense_independante": True,
        "sans_recompense_dollars": True,
    }


def construire_embed_spawn(equipe_mechante: str, date_expiration: int) -> discord.Embed:
    info = config.EQUIPES_MECHANTES[equipe_mechante]
    minutes = max(0, round((date_expiration - time.time()) / 60))
    embed = discord.Embed(
        title=f"{info['emoji']} Repaire de la {equipe_mechante} !",
        description=(
            f"Un repaire de la **{equipe_mechante}** vient d'être repéré ! Affronte à la suite "
            f"2 sbires puis **{_nom_boss(equipe_mechante)}** "
            f"({', '.join(sorted(config.REPAIRE_RARETES_BOSS))} minimum) pour décrocher son badge.\n\n"
            f"⚠️ Une défaite met fin à ta tentative — il faudra attendre le prochain repaire "
            f"pour retenter. Plusieurs joueurs peuvent s'y essayer en parallèle."
        ),
        color=discord.Color.dark_red(),
    )
    if info.get("image_chef"):
        embed.set_thumbnail(url=info["image_chef"])
    embed.set_footer(text=f"Disponible encore ~{minutes} min")
    return embed


class VueDefierRepaire(discord.ui.View):
    """Vue persistante attachée au message de spawn — n'importe quel joueur peut cliquer
    Infiltrer pour démarrer SON run (une seule tentative par joueur et par spawn)."""

    def __init__(self, bot, repaire_id: int):
        super().__init__(timeout=config.REPAIRE_DUREE_DISPONIBLE_MINUTES * 60)
        self.bot = bot
        self.repaire_id = repaire_id

        bouton = discord.ui.Button(
            label="Infiltrer le repaire", emoji="🕵️", style=discord.ButtonStyle.danger,
            custom_id=f"repaire_defier_{repaire_id}",
        )
        bouton.callback = self._on_defier
        self.add_item(bouton)

    async def _on_defier(self, interaction: discord.Interaction):
        spawn = database.obtenir_repaire_spawn(self.repaire_id)
        if not spawn or time.time() >= spawn["date_expiration"]:
            await interaction.response.send_message("Ce repaire n'est plus disponible.", ephemeral=True)
            return

        if not database.creer_run_repaire(self.repaire_id, interaction.user.id):
            await interaction.response.send_message(
                "Tu as déjà tenté ce repaire (gagné ou perdu, une seule chance par ouverture).",
                ephemeral=True,
            )
            return

        if not database.obtenir_equipe_combat_disponible(interaction.user.id):
            database.terminer_run_repaire(self.repaire_id, interaction.user.id, "defaite")
            await interaction.response.send_message(
                "❌ Configure ton équipe de combat d'abord (`/equipe-combat`) !", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🕵️ Tu infiltres le repaire de la **{spawn['equipe_mechante']}** ! Premier combat...",
            ephemeral=True,
        )
        await _lancer_etape(self.bot, interaction.user, interaction.channel, self.repaire_id, spawn["equipe_mechante"], etape=1)


async def _lancer_etape(bot, joueur: discord.Member, channel: discord.TextChannel, repaire_id: int, equipe_mechante: str, etape: int, thread_existant: discord.Thread = None):
    archetype = _archetype_etape(equipe_mechante, etape)
    multiplicateur = config.REPAIRE_MULTIPLICATEUR_BOSS if etape == 3 else 1.0

    dresseur_id = database.creer_dresseur_actif(archetype["nom"], channel.id, int(time.time()) + 300)

    async def _apres_combat(gagne: bool, joueur_id: int, thread):
        await _resoudre_etape(bot, joueur_id, channel, repaire_id, equipe_mechante, etape, gagne, thread)

    await dresseurs_module.demarrer_combat_dresseur(
        bot, joueur, dresseur_id, channel,
        multiplicateur_pc=multiplicateur, apres_combat=_apres_combat, archetype_direct=archetype,
        thread_existant=thread_existant, gerer_suppression_fil=False,
    )


async def _resoudre_etape(bot, joueur_id, channel, repaire_id, equipe_mechante, etape, gagne, thread):
    if not gagne:
        database.terminer_run_repaire(repaire_id, joueur_id, "defaite")
        try:
            await thread.send(
                f"💀 <@{joueur_id}> — ta tentative d'infiltration s'arrête là. Retente ta chance au "
                f"prochain repaire ! (Ce fil sera supprimé dans {combat_module.DELAI_SUPPRESSION_FIL // 60} minutes.)"
            )
        except discord.HTTPException:
            pass
        bot.loop.create_task(dresseurs_module._supprimer_fil_apres_delai(thread, combat_module.DELAI_SUPPRESSION_FIL))
        return

    database.avancer_run_repaire(repaire_id, joueur_id, etape)

    if etape < 3:
        mini, maxi = config.REPAIRE_RECOMPENSE_DOLLARS_SBIRE
        mult_jour = database.multiplicateur_repaire_du_jour(joueur_id)
        dollars_sbire = round(
            random.randint(mini, maxi) * mult_jour * database.multiplicateur_boost(joueur_id, "argent")
        )
        database.ajouter_poke_dollars(joueur_id, dollars_sbire)
        note_sbire = " *(récompense réduite : plusieurs runs déjà complétés aujourd'hui)*" if mult_jour < 1.0 else ""

        vue = VueContinuerRepaire(bot, joueur_id, channel, repaire_id, equipe_mechante, etape, thread)
        try:
            if etape == 2:
                info = config.EQUIPES_MECHANTES[equipe_mechante]
                nom_boss = _nom_boss(equipe_mechante)
                embed = discord.Embed(
                    title=f"{info['emoji']} {nom_boss} t'attendait...",
                    description=(
                        f"Tu as éliminé les sbires — au fond du repaire, le chef de la "
                        f"**{equipe_mechante}** se lève de son fauteuil.\n\n"
                        f"**+{dollars_sbire} Poké Dollars**{note_sbire}\n\n"
                        f"⚔️ Derrière cette porte, **{nom_boss}** défend son badge. "
                        f"Soigne ton équipe si besoin... puis entre."
                    ),
                    color=discord.Color.dark_red(),
                )
                if info.get("image_chef"):
                    embed.set_image(url=info["image_chef"])
                await thread.send(content=f"<@{joueur_id}>", embed=embed, view=vue)
            else:
                await thread.send(
                    f"🕵️ <@{joueur_id}> — victoire ! **+{dollars_sbire} Poké Dollars**{note_sbire}\n"
                    f"Prêt·e pour le combat suivant, ou tu préfères soigner ton équipe avant "
                    f"(1 potion par Pokémon soigné) ?",
                    view=vue,
                )
        except discord.HTTPException:
            pass
        return

    # Étape 3 = Boss battu : récompense + badge (pas de CT ici, réservées aux Champions d'arène)
    database.terminer_run_repaire(repaire_id, joueur_id, "victoire")
    mini, maxi = config.REPAIRE_RECOMPENSE_DOLLARS_BOSS
    mult_jour = database.enregistrer_victoire_repaire_repetition(joueur_id)
    dollars = round(random.randint(mini, maxi) * mult_jour * database.multiplicateur_boost(joueur_id, "argent"))
    database.ajouter_poke_dollars(joueur_id, dollars)

    nouveau_badge = database.accorder_badge_repaire(joueur_id, equipe_mechante)
    journal.logger(f"🕵️ <@{joueur_id}> a vaincu {_nom_boss(equipe_mechante)} ({equipe_mechante}) !" + (" (nouveau badge)" if nouveau_badge else ""))

    import formes_objets as formes_objets_module

    objets_obtenus = []
    for cle_objet in formes_objets_module.FORMES_OBJETS:
        if random.random() < config.REPAIRE_CHANCE_OBJET_PAR_OBJET:
            database.ajouter_balls(joueur_id, cle_objet, 1)
            objets_obtenus.append(cle_objet)
    if objets_obtenus:
        journal.logger(f"🕵️ <@{joueur_id}> a trouvé {', '.join(objets_obtenus)} dans le repaire {equipe_mechante} !")

    info = config.EQUIPES_MECHANTES[equipe_mechante]
    texte = f"🏆 <@{joueur_id}> a vaincu **{_nom_boss(equipe_mechante)}** ({equipe_mechante}) ! +{dollars} Poké Dollars"
    for cle_objet in objets_obtenus:
        infos_objet = formes_objets_module.FORMES_OBJETS[cle_objet]
        texte += (
            f"\n{infos_objet['objet_emoji']} Butin rarissime ! Tu as trouvé une **{infos_objet['objet_nom']}** "
            f"— équipe-la à un **{infos_objet['espece']}** pour débloquer sa forme **{infos_objet['forme_nom']}**."
        )
    if mult_jour < 1.0:
        texte += " *(récompense réduite : plusieurs runs déjà complétés aujourd'hui)*"
    if nouveau_badge:
        bonus_pourcent = round(config.REPAIRE_BONUS_PAR_BADGE * 100)
        noms_categorie = {
            "capture": "chance de capture", "shiny": "chance de shiny",
            "argent": "gains de Poké Dollars", "xp": "gains d'XP",
        }
        categorie = info["categorie_bonus"]
        texte += (
            f"\n🎖️ **Nouveau badge {info['emoji']} {equipe_mechante} !** +{bonus_pourcent}% de "
            f"{noms_categorie.get(categorie, categorie)} en permanence."
        )
    try:
        await thread.send(
            texte + f"\n\n🗑️ Ce fil sera supprimé dans {combat_module.DELAI_SUPPRESSION_FIL // 60} minutes."
        )
    except discord.HTTPException:
        pass
    bot.loop.create_task(dresseurs_module._supprimer_fil_apres_delai(thread, combat_module.DELAI_SUPPRESSION_FIL))


class VueContinuerRepaire(discord.ui.View):
    """Entre deux combats d'un run de repaire : soin auto (1 potion par Pokémon soigné) ou continuer direct."""

    def __init__(self, bot, joueur_id: int, channel: discord.TextChannel, repaire_id: int, equipe_mechante: str, etape_terminee: int, thread: discord.Thread):
        super().__init__(timeout=300)
        self.bot = bot
        self.joueur_id = joueur_id
        self.channel = channel
        self.repaire_id = repaire_id
        self.equipe_mechante = equipe_mechante
        self.etape_terminee = etape_terminee
        self.thread = thread

        bouton_continuer = discord.ui.Button(label="Continuer", emoji="⚔️", style=discord.ButtonStyle.primary)
        bouton_continuer.callback = self._on_continuer
        self.add_item(bouton_continuer)

        bouton_soigner = discord.ui.Button(label="Soin auto", emoji="🧪", style=discord.ButtonStyle.success)
        bouton_soigner.callback = self._on_soigner
        self.add_item(bouton_soigner)

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("Ce n'est pas ton run de repaire !", ephemeral=True)
            return False
        return True

    async def _on_continuer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        self.clear_items()
        self.stop()
        await interaction.response.edit_message(view=self)
        await _lancer_etape(self.bot, interaction.user, self.channel, self.repaire_id, self.equipe_mechante, self.etape_terminee + 1, thread_existant=self.thread)

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
        self.stop()
        await interaction.response.edit_message(
            content=(
                f"🩹 **Soin auto** ({total_potions_utilisees} potion(s) utilisée(s)) :\n" + "\n".join(lignes)
            ),
            view=self,
        )
        await _lancer_etape(self.bot, interaction.user, self.channel, self.repaire_id, self.equipe_mechante, self.etape_terminee + 1, thread_existant=self.thread)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        database.terminer_run_repaire(self.repaire_id, self.joueur_id, "defaite")
        try:
            await self.thread.send(
                f"⏳ <@{self.joueur_id}> — plus de réponse, ton run de repaire s'arrête là. "
                f"Ce fil sera supprimé dans {combat_module.DELAI_SUPPRESSION_FIL // 60} minutes."
            )
        except discord.HTTPException:
            pass
        self.bot.loop.create_task(dresseurs_module._supprimer_fil_apres_delai(self.thread, combat_module.DELAI_SUPPRESSION_FIL))


async def demarrer_nouveau_repaire(bot, channel, equipe_mechante: str = None) -> int:
    """Ouvre un nouveau repaire dans ce channel (équipe aléatoire si non précisée).
    Retourne l'ID du repaire créé."""
    equipe_mechante = equipe_mechante or random.choice(list(config.EQUIPES_MECHANTES.keys()))
    date_expiration = int(time.time()) + config.REPAIRE_DUREE_DISPONIBLE_MINUTES * 60
    repaire_id = database.creer_repaire_spawn(equipe_mechante, channel.id, date_expiration)

    embed = construire_embed_spawn(equipe_mechante, date_expiration)
    vue = VueDefierRepaire(bot, repaire_id)
    message = await channel.send(embed=embed, view=vue)
    journal.logger(f"🕵️ Nouveau repaire {equipe_mechante} ouvert.")

    bot.loop.create_task(_supprimer_message_spawn_apres_delai(message, config.REPAIRE_DUREE_DISPONIBLE_MINUTES * 60))
    return repaire_id


async def _supprimer_message_spawn_apres_delai(message: discord.Message, delai_secondes: int):
    await asyncio.sleep(delai_secondes)
    try:
        await message.delete()
    except discord.HTTPException:
        pass


async def boucle_repaires(bot):
    """Toutes les config.REPAIRE_INTERVALLE_HEURES, ouvre un nouveau repaire d'une
    équipe aléatoire dans config.CHANNEL_REPAIRE_ID."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        await asyncio.sleep(config.REPAIRE_INTERVALLE_HEURES * 3600)

        try:
            channel_id = getattr(config, "CHANNEL_REPAIRE_ID", None)
            if not channel_id:
                continue
            channel = bot.get_channel(channel_id)
            if channel is None:
                print("⚠️ CHANNEL_REPAIRE_ID introuvable — vérifie l'ID dans config.py.")
                continue

            await demarrer_nouveau_repaire(bot, channel)
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_repaires (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_repaires` — voir les logs serveur.")
