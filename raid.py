import random
import time

import discord

import combat as combat_module
import config
import database
import equipe_combat
import etat_jeu
import leveling
import niveaux_pokemon
import pnj
import quetes_ui as quetes_ui_module
from pokemon_data import (
    COULEUR_RARETE,
    EMOJI_BALLS,
    EMOJI_POKEDOLLAR,
    TAUX_CAPTURE,
    affichage_types,
    calculer_pc_derive,
    sprite_pokemon,
    tirer_ivs,
)


def _etoiles_txt(etoiles: int) -> str:
    return "⭐" * etoiles


def _barre_pv(pv_actuel: int, pv_max: int, longueur: int = 20) -> str:
    ratio = max(0, min(1, pv_actuel / pv_max)) if pv_max else 0
    rempli = round(longueur * ratio)
    return "🟥" * rempli + "⬛" * (longueur - rempli)


# ----------------------------------------------------------------------------
# Salle d'attente
# ----------------------------------------------------------------------------

def construire_embed_salle_attente(boss: dict, etoiles: int, date_debut_combat: int, nb_joueurs_prets: int) -> discord.Embed:
    types_affiches = affichage_types(boss["types"])
    temps_restant = max(0, date_debut_combat - int(time.time()))

    embed = discord.Embed(
        title=f"🕐 SALLE D'ATTENTE : {boss['nom'].upper()} {_etoiles_txt(etoiles)}",
        description=(
            f"{types_affiches}\n\n"
            f"Un raid va commencer ! Une fois le combat lancé, ton équipe attaquera "
            f"**automatiquement toutes les {config.INTERVALLE_TICK_COMBAT_RAID} secondes**, "
            f"tant que tu as rejoint."
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(name="⏱️ Combat dans", value=f"{temps_restant} secondes", inline=True)
    embed.add_field(name="🙋 Joueurs prêts", value=str(nb_joueurs_prets), inline=True)
    embed.add_field(
        name="Comment participer",
        value=(
            "Clique sur **Rejoindre** pour t'engager. "
            "Clique sur **Équipe la plus forte** si tu n'as pas encore configuré la tienne.\n\n"
            "⚠️ Plus il y a de monde présent, plus le boss sera costaud une fois le combat lancé !"
        ),
        inline=False,
    )

    sprite_url = sprite_pokemon(boss)
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    return embed


class VueSalleAttente(discord.ui.View):
    """Vue affichée pendant la phase de rassemblement, avant que le combat ne démarre vraiment."""

    def __init__(self, raid_id: int, boss: dict, etoiles: int, date_debut_combat: int):
        super().__init__(timeout=None)
        self.raid_id = raid_id
        self.boss = boss
        self.etoiles = etoiles
        self.date_debut_combat = date_debut_combat

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.primary, emoji="🙋")
    async def rejoindre(self, interaction: discord.Interaction, button: discord.ui.Button):
        database.inscrire_participant_raid(self.raid_id, interaction.user.id)
        nb_joueurs = len(database.obtenir_participants_raid(self.raid_id))
        embed = construire_embed_salle_attente(self.boss, self.etoiles, self.date_debut_combat, nb_joueurs)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Équipe la plus forte", style=discord.ButtonStyle.secondary, emoji="🛡️")
    async def equipe_auto(self, interaction: discord.Interaction, button: discord.ui.Button):
        noms = equipe_combat.equiper_meilleure_equipe(interaction.user.id)
        if not noms:
            await interaction.response.send_message(
                "Tu n'as encore aucun Pokémon capturé à mettre dans une équipe !", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🛡️ Ton équipe a été remplie avec tes meilleurs Pokémon : {', '.join(noms)}",
            ephemeral=True,
        )

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def quitter(self, interaction: discord.Interaction, button: discord.ui.Button):
        vue_confirmation = VueConfirmerQuitterRaid(self, interaction.message, interaction.user.id)
        await interaction.response.send_message(
            "Tu veux vraiment quitter ce raid ?", view=vue_confirmation, ephemeral=True
        )


class VueConfirmerQuitterRaid(discord.ui.View):
    """Confirmation avant de quitter une salle d'attente de raid — évite les clics
    accidentels sur un bouton qui te fait perdre ta place."""

    def __init__(self, vue_salle_attente: "VueSalleAttente", message_salle_attente: discord.Message, user_id: int):
        super().__init__(timeout=30)
        self.vue_salle_attente = vue_salle_attente
        self.message_salle_attente = message_salle_attente
        self.user_id = user_id

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta confirmation !", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Oui, quitter", style=discord.ButtonStyle.danger, emoji="🚪")
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return

        succes = database.quitter_raid(self.vue_salle_attente.raid_id, self.user_id)
        if not succes:
            await interaction.response.edit_message(content="Tu n'avais pas encore rejoint ce raid.", view=None)
            return

        nb_joueurs = len(database.obtenir_participants_raid(self.vue_salle_attente.raid_id))
        embed = construire_embed_salle_attente(
            self.vue_salle_attente.boss,
            self.vue_salle_attente.etoiles,
            self.vue_salle_attente.date_debut_combat,
            nb_joueurs,
        )
        try:
            await self.message_salle_attente.edit(embed=embed, view=self.vue_salle_attente)
        except (discord.NotFound, discord.HTTPException):
            pass

        await interaction.response.edit_message(content="🚪 Tu as quitté le raid.", view=None)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.edit_message(content="Tu restes dans le raid !", view=None)


# ----------------------------------------------------------------------------
# Combat (tick automatique)
# ----------------------------------------------------------------------------

def construire_embed_raid(raid_row, boss: dict, nb_participants: int) -> discord.Embed:
    pv_actuel = raid_row["pv_actuel"]
    pv_max = raid_row["pv_max"]
    etoiles = raid_row["etoiles"]
    types_affiches = affichage_types(boss["types"])

    temps_restant = max(0, raid_row["date_fin"] - int(time.time()))
    minutes_restantes = temps_restant // 60

    embed = discord.Embed(
        title=f"⚔️ RAID {_etoiles_txt(etoiles)} : {boss['nom'].upper()} SAUVAGE !",
        description=f"{types_affiches}",
        color=COULEUR_RARETE[boss["rarete"]],
    )
    embed.add_field(
        name=f"PV : {pv_actuel:,}/{pv_max:,}".replace(",", " "),
        value=_barre_pv(pv_actuel, pv_max),
        inline=False,
    )
    embed.add_field(name="⏱️ Temps restant", value=f"~{minutes_restantes} min", inline=True)
    embed.add_field(name="⚔️ Participants engagés", value=str(nb_participants), inline=True)
    embed.add_field(
        name="Comment participer",
        value=(
            "Le combat est lancé — seuls les Dresseurs engagés en salle d'attente y participent. "
            f"Ton équipe attaquera automatiquement toutes les {config.INTERVALLE_TICK_COMBAT_RAID}s tant que le raid dure."
        ),
        inline=False,
    )

    sprite_url = sprite_pokemon(boss)
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    return embed


class VueRaidEnCombat(discord.ui.View):
    """Vue affichée pendant le combat automatique. On ne peut plus rejoindre une fois le
    combat lancé (seule la salle d'attente le permet) — on peut juste configurer son
    équipe ou quitter. Aucune action manuelle n'est nécessaire pour attaquer."""

    def __init__(self, raid_id: int):
        super().__init__(timeout=None)
        self.raid_id = raid_id

    @discord.ui.button(label="Équipe la plus forte", style=discord.ButtonStyle.secondary, emoji="🛡️")
    async def equipe_auto(self, interaction: discord.Interaction, button: discord.ui.Button):
        noms = equipe_combat.equiper_meilleure_equipe(interaction.user.id)
        if not noms:
            await interaction.response.send_message(
                "Tu n'as encore aucun Pokémon capturé à mettre dans une équipe !", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🛡️ Ton équipe a été remplie avec tes meilleurs Pokémon : {', '.join(noms)}",
            ephemeral=True,
        )

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def quitter(self, interaction: discord.Interaction, button: discord.ui.Button):
        vue_confirmation = VueConfirmerQuitterRaidEnCombat(self.raid_id, interaction.user.id)
        await interaction.response.send_message(
            "⚠️ Le combat est déjà lancé — si tu quittes, tu ne pourras **pas** rejoindre ce "
            "raid à nouveau. Tu veux vraiment quitter ?",
            view=vue_confirmation,
            ephemeral=True,
        )


class VueConfirmerQuitterRaidEnCombat(discord.ui.View):
    """Confirmation avant de quitter un raid dont le combat est déjà lancé — départ
    définitif (impossible de rejoindre ensuite), donc encore plus important à confirmer
    que dans la salle d'attente."""

    def __init__(self, raid_id: int, user_id: int):
        super().__init__(timeout=30)
        self.raid_id = raid_id
        self.user_id = user_id

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta confirmation !", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Oui, quitter", style=discord.ButtonStyle.danger, emoji="🚪")
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        succes = database.quitter_raid(self.raid_id, self.user_id)
        texte = (
            "🚪 Tu as quitté ce raid. Le combat étant déjà lancé, tu ne pourras pas le rejoindre à nouveau."
            if succes
            else "Tu n'avais pas rejoint ce raid."
        )
        await interaction.response.edit_message(content=texte, view=None)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.edit_message(content="Tu restes dans le raid !", view=None)


def calculer_degats(user_id: int) -> int:
    """Calcule les dégâts d'un tick pour un joueur : chaque Pokémon de son équipe de combat
    ENCORE EN VIE (PV > 0) inflige ses propres dégâts (stat offensive réelle × variance
    indépendante). Un Pokémon K.O. (0 PV) ne contribue plus tant qu'il n'est pas soigné."""
    noms_equipe = database.obtenir_equipe_combat_disponible(user_id)
    if not noms_equipe:
        return 0

    captures = database.obtenir_pokedex_joueur(user_id)
    especes_possedees = {row["pokemon_nom"] for row in captures}

    degats_total = 0
    for nom in noms_equipe:
        if nom not in especes_possedees:
            continue
        stats = combat_module.stats_combattant_reel(user_id, nom)
        pv_actuels = database.obtenir_pv_actuels(user_id, nom, stats["pv"], contexte="raid")
        if pv_actuels <= 0:
            continue  # K.O., ne participe plus

        stat_offensive = (stats["attaque"] + stats["attaque_spe"]) / 2
        degats_pokemon = stat_offensive * config.FACTEUR_DEGATS_RAID
        variance = random.uniform(config.DEGATS_VARIANCE_MIN, config.DEGATS_VARIANCE_MAX)
        degats_total += round(degats_pokemon * variance)
    return degats_total


def appliquer_riposte_boss(user_id: int, etoiles: int):
    """Le boss riposte sur l'équipe engagée d'un joueur : dégâts répartis entre ses
    Pokémon encore en vie. Un POURCENTAGE des PV max (pas un nombre fixe) : reste
    cohérent quelle que soit l'échelle de PV réelle, contrairement à un dégât absolu qui
    peut one-shot ou devenir dérisoire selon le niveau/les stats en jeu à un instant T."""
    noms_equipe = database.obtenir_equipe_combat_disponible(user_id)
    if not noms_equipe:
        return []

    captures = database.obtenir_pokedex_joueur(user_id)
    especes_possedees = {row["pokemon_nom"] for row in captures}

    vivants = []
    for nom in noms_equipe:
        if nom not in especes_possedees:
            continue
        pv_max = combat_module.stats_combattant_reel(user_id, nom)["pv"]
        pv_actuels = database.obtenir_pv_actuels(user_id, nom, pv_max, contexte="raid")
        if pv_actuels > 0:
            vivants.append((nom, pv_max))

    if not vivants:
        return []

    pourcent_riposte = config.RIPOSTE_POURCENT_PAR_ETOILE.get(etoiles, 0.10)

    nouveaux_ko = []
    for nom, pv_max in vivants:
        degats = max(1, round(pv_max * pourcent_riposte))
        nouveau_pv = database.modifier_pv_pokemon(user_id, nom, -degats, pv_max, contexte="raid")
        if nouveau_pv <= 0:
            nouveaux_ko.append(nom)

    return nouveaux_ko


# ----------------------------------------------------------------------------
# Victoire / capture
# ----------------------------------------------------------------------------

def construire_embed_victoire(boss: dict, etoiles: int, participants: list, completions_par_joueur: dict = None) -> list:
    dollars = config.DOLLARS_RAID_PAR_ETOILE.get(etoiles, 50)
    xp = config.XP_RAID_PAR_ETOILE.get(etoiles, 50)

    embed = discord.Embed(
        title=f"🎉 {boss['nom']} a été vaincu ! {_etoiles_txt(etoiles)}",
        description=f"**{len(participants)}** dresseur(s) ont participé à cette victoire.",
        color=discord.Color.gold(),
    )
    sprite_url = sprite_pokemon(boss)
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    if participants:
        lignes = [
            f"<@{row['user_id']}> — {row['degats_total']:,} dégâts".replace(",", " ")
            for row in participants[:10]
        ]
        embed.add_field(name="🏆 Participants", value="\n".join(lignes), inline=False)

    embed.add_field(
        name="Récompenses (pour chaque participant, peu importe les dégâts infligés)",
        value=f"{dollars} {EMOJI_POKEDOLLAR} Poké Dollars, {xp} XP *(+ bonus de Race individuel éventuel)*",
        inline=False,
    )

    if completions_par_joueur:
        lignes_quetes = []
        for user_id, quetes_completees in completions_par_joueur.items():
            noms = ", ".join(f"{q['emoji']} {q['nom']}" for q in quetes_completees)
            lignes_quetes.append(f"<@{user_id}> : {noms}")
        embed.add_field(
            name="📜 Quêtes complétées par cette victoire",
            value="\n".join(lignes_quetes) + "\nVa les réclamer avec `/quetes` !",
            inline=False,
        )

    embed.add_field(
        name=f"{EMOJI_BALLS['honorball']} Capture",
        value=(
            f"Chaque participant a **{config.TENTATIVES_CAPTURE_RAID} tentatives** pour capturer "
            f"**{boss['nom']}** (bouton ci-dessous) !"
        ),
        inline=False,
    )

    if participants:
        embed_rival = pnj.construire_embed_reaction(
            "victoire_raid", user_id=participants[0]["user_id"], joueur=f"<@{participants[0]['user_id']}>", pokemon=boss["nom"]
        )
        if embed_rival:
            return [embed, embed_rival]

    return [embed]


def distribuer_recompenses_victoire(raid_id: int, etoiles: int) -> dict:
    """Crédite Poké Dollars et XP à CHAQUE participant, peu importe les dégâts infligés —
    seule la participation compte. Initialise aussi leurs 5 tentatives de capture pour
    CE raid précis (pas un objet ajouté à l'inventaire général). Retourne
    {user_id: [quêtes tout juste complétées]} pour les afficher directement dans
    l'embed public de victoire (pas besoin d'un clic supplémentaire)."""
    participants = database.obtenir_participants_raid(raid_id)
    dollars = config.DOLLARS_RAID_PAR_ETOILE.get(etoiles, 50)
    xp = config.XP_RAID_PAR_ETOILE.get(etoiles, 50)
    completions_par_joueur = {}

    for row in participants:
        user_id = row["user_id"]
        dollars_boostes = round(dollars * database.multiplicateur_boost(user_id, "argent"))
        database.ajouter_poke_dollars(user_id, dollars_boostes)
        leveling.gagner_xp(user_id, xp)
        quetes_completees = database.incrementer_progression_quete(user_id, "raid_victoire")
        if quetes_completees:
            completions_par_joueur[user_id] = quetes_completees

    database.initialiser_tentatives_capture_raid(raid_id, config.TENTATIVES_CAPTURE_RAID)
    return completions_par_joueur


class VueCaptureRaid(discord.ui.View):
    """Vue affichée après la victoire, permettant à chaque participant de tenter
    jusqu'à TENTATIVES_CAPTURE_RAID captures de CE boss précis (pas un objet stocké
    dans l'inventaire général — les tentatives n'existent que pour ce raid)."""

    def __init__(self, raid_id: int, boss: dict, etoiles: int):
        super().__init__(timeout=None)
        self.raid_id = raid_id
        self.boss = boss
        self.etoiles = etoiles

    @discord.ui.button(label="Capturer", style=discord.ButtonStyle.success, emoji=EMOJI_BALLS["honorball"])
    async def capturer(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id

        participants = {row["user_id"] for row in database.obtenir_participants_raid(self.raid_id)}
        if user_id not in participants:
            await interaction.response.send_message(
                "Tu n'as pas participé à ce raid, tu n'as pas de tentative pour celui-ci.",
                ephemeral=True,
            )
            return

        if database.a_deja_capture_raid(self.raid_id, user_id):
            await interaction.response.send_message(
                f"Tu as déjà capturé **{self.boss['nom']}** pour ce raid !", ephemeral=True
            )
            return

        peut_tenter, tentatives_restantes = database.tenter_capture_raid(self.raid_id, user_id)
        if not peut_tenter:
            await interaction.response.send_message(
                f"Tu n'as plus de tentatives pour capturer **{self.boss['nom']}** sur ce raid "
                f"({config.TENTATIVES_CAPTURE_RAID}/{config.TENTATIVES_CAPTURE_RAID} déjà utilisées).",
                ephemeral=True,
            )
            return

        limite = database.limite_stockage_pokemon(user_id)
        if database.compter_captures_totales(user_id) >= limite:
            await interaction.response.send_message(
                f"📦 Ton stockage est plein ({limite}/{limite}) ! Cette tentative est perdue "
                f"({tentatives_restantes} restante(s)), libère de la place avec `/relacher`.",
                ephemeral=True,
            )
            return

        taux = min(1.0, TAUX_CAPTURE[self.boss["rarete"]]["honorball"] * database.multiplicateur_boost(user_id, "capture"))
        reussite = random.random() < taux

        if not reussite:
            message = f"💨 **{self.boss['nom']}** s'est échappé... ({tentatives_restantes} tentative(s) restante(s))"
            if tentatives_restantes == 0:
                message += "\nC'était ta dernière tentative pour ce raid."
            await interaction.response.send_message(message, ephemeral=True)
            return

        ivs = tirer_ivs()
        niveau = self.etoiles * 15  # niveau approximatif selon la difficulté du raid
        pc = calculer_pc_derive(self.boss, ivs, niveau)
        chance_shiny = (
            config.CHANCE_SHINY_BASE
            * etat_jeu.obtenir_multiplicateur_shiny()
            * database.multiplicateur_boost(user_id, "shiny")
        )
        est_shiny = random.random() < chance_shiny
        database.ajouter_capture(user_id, self.boss["nom"], pc, shiny=est_shiny, ivs=ivs)

        # Même règle que pour les captures sauvages/œufs : le niveau ne s'applique à
        # l'équipe que s'il est meilleur que celui déjà acquis (jamais de régression).
        niveau_actuel, _xp_actuel = database.obtenir_niveau_pokemon(user_id, self.boss["nom"])
        if niveau > niveau_actuel:
            database.definir_niveau_xp_pokemon(user_id, self.boss["nom"], niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau))
        database.marquer_capture_reussie_raid(self.raid_id, user_id)
        quetes_completees = database.incrementer_progression_quete(user_id, "capture", {"rarete": self.boss["rarete"]})

        shiny_txt = "✨ SHINY ✨ " if est_shiny else ""
        await interaction.response.send_message(
            f"🎉 Tu as capturé {shiny_txt}**{self.boss['nom']}** ({pc} PC) !"
            f"{quetes_ui_module.texte_notifications_completion(quetes_completees)}",
            ephemeral=True,
        )
