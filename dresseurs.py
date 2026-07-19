import random
import time

import discord

import combat as combat_module
import config
import database
import journal
import leveling
import pnj
import quetes_ui
from pokemon_data import (
    POKEDEX,
    attaques_apprenables,
    calculer_pv_max,
    obtenir_pokemon_par_nom,
    pp_max_attaque,
)

# IDs synthétiques réservés aux dresseurs — négatifs, donc jamais en collision avec un
# vrai ID Discord (toujours positif).
ID_DRESSEUR_BASE = -1_000_000_000_000

ARCHETYPES = [
    # "sprite" : URL vers un GIF/PNG hébergé publiquement (même principe que sprite_pokemon()
    # dans pokemon_data.py). Laisse None tant que tu n'as pas d'asset — le thumbnail est
    # simplement omis dans ce cas, rien ne casse.
    {
        "nom": "Éleveuse Blanche",  # ex-Ingénieur Colress : Acier -> Normal, sprite Whitney/Blanche
        "types_theme": ["normal"], "emoji": "🥛", "tier": 1,
        "sprite": "https://www.pokepedia.fr/images/a/ad/Sprite_Blanche_HGSS.gif",
    },
    {
        "nom": "Ombreflamme Silver",  # ex-Pyromane Fenwick : sprite du rival Silver/Argent
        "types_theme": ["feu"], "emoji": "🔥", "tier": 1,
        "sprite": "https://www.pokepedia.fr/images/0/00/Sprite_Silver_HGSS.gif",
    },
    {
        "nom": "Naïade Coralie", "types_theme": ["eau"], "emoji": "💧", "tier": 1,
        "sprite": "https://www.pokepedia.fr/images/2/2e/Sprite_Ondine_HGSS.gif",
    },
    {
        "nom": "Botaniste Sylvie",  # sprite remplacé par Erika (Championne Plante de Céladopole)
        "types_theme": ["plante"], "emoji": "🌿", "tier": 1,
        "sprite": "https://www.pokepedia.fr/images/1/19/Sprite_Erika_HGSS.gif",
    },
    {
        "nom": "Fulguro Max", "types_theme": ["electrik"], "emoji": "⚡", "tier": 2,
        "sprite": "https://www.pokepedia.fr/images/5/55/Sprite_Major_Bob_HGSS.gif",
    },
    {
        "nom": "Ombremage Lucia", "types_theme": ["spectre", "tenebres"], "emoji": "👻", "tier": 2,
        "sprite": "https://www.pokepedia.fr/images/d/dc/Sprite_Jeannine_HGSS.gif",
    },
    {
        "nom": "Roc Solide Grant", "types_theme": ["roche", "sol"], "emoji": "🪨", "tier": 2,
        "sprite": "https://www.pokepedia.fr/images/6/68/Sprite_Pierre_HGSS.gif",
    },
    {
        "nom": "Dracoseigneur Ryu",  # revenu au masculin : sprite de Peter/Lance (HGSS)
        "types_theme": ["dragon"], "emoji": "🐉", "tier": 3,
        "sprite": "https://www.pokepedia.fr/images/c/c6/Sprite_Peter_HGSS.gif",
    },
]

TAILLE_EQUIPE_DRESSEUR = 4

# Gladio n'est PAS dans ARCHETYPES : il ne doit jamais apparaître comme dresseur spontané
# aléatoire, seulement via /defi-gladio (voir defier_gladio ci-dessous).
ARCHETYPE_GLADIO = {
    "nom": pnj.NOM_RIVAL,
    "types_theme": ["tenebres", "spectre"],
    "emoji": pnj.EMOJI_RIVAL,
    "tier": 3,
    "sprite": pnj.IMAGE_RIVAL,
    "taille_equipe": 6,  # équipe complète, plus dure qu'un dresseur normal (4)
}


def _pc_cumule_equipe(user_id: int) -> int:
    noms = database.obtenir_equipe_combat_disponible(user_id)
    captures = database.obtenir_pokedex_joueur(user_id)
    meilleur_pc = {row["pokemon_nom"]: row["meilleur_pc"] for row in captures}
    return sum(meilleur_pc.get(nom, 0) for nom in noms)


def choisir_archetype(nom_force: str | None = None) -> dict:
    if nom_force:
        for archetype in ARCHETYPES:
            if archetype["nom"] == nom_force:
                return archetype
    return random.choice(ARCHETYPES)


def generer_equipe_dresseur(archetype: dict, pc_cible: int) -> list:
    """Sélectionne une équipe de Pokémon correspondant au thème de l'archétype, dont le
    PC cumulé vise pc_cible (± la variance configurée). Retourne [(nom, pc), ...]."""
    types_theme = archetype["types_theme"]
    if types_theme:
        pool = [p for p in POKEDEX if any(t in p["types"] for t in types_theme)]
    else:
        pool = list(POKEDEX)
    if not pool:
        pool = list(POKEDEX)

    taille = min(archetype.get("taille_equipe", TAILLE_EQUIPE_DRESSEUR), len(pool))
    choisis = random.sample(pool, taille)

    variance = random.uniform(1 - config.DRESSEUR_VARIANCE_PC, 1 + config.DRESSEUR_VARIANCE_PC)
    pc_total_vise = max(300, round(pc_cible * variance))
    pc_par_pokemon = max(50, pc_total_vise // taille)

    equipe = []
    for pokemon in choisis:
        pc_individuel = max(50, round(pc_par_pokemon * random.uniform(0.8, 1.2)))
        pc_individuel = min(pc_individuel, config.PC_MAXIMUM)
        equipe.append((pokemon["nom"], pc_individuel))
    return equipe


def _equiper_attaques_aleatoires(dresseur_id: int, pokemon_nom: str):
    """Donne au Pokémon du dresseur jusqu'à 4 attaques (priorité aux offensives), en
    reprenant la même logique que le bouton aléatoire du Maître des Types."""
    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    attaques_dispo = attaques_apprenables(pokemon)
    from pokemon_data import ATTAQUES

    offensives = [n for n in attaques_dispo if ATTAQUES[n].get("puissance")]
    statuts = [n for n in attaques_dispo if not ATTAQUES[n].get("puissance")]
    random.shuffle(offensives)
    random.shuffle(statuts)
    tirage = (offensives[:3] + statuts)[:4] if len(offensives) >= 3 else (offensives + statuts)[:4]
    random.shuffle(tirage)
    for slot, nom in enumerate(tirage, start=1):
        database.equiper_attaque(dresseur_id, pokemon_nom, slot, nom)


def construire_embed_spawn(archetype: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"{archetype['emoji']} {archetype['nom']} veut se battre !",
        description=(
            "Un dresseur apparaît sur la route, prêt à en découdre.\n\n"
            "**Puissance de son équipe** : s'adapte à celle de chaque adversaire "
            "(calculée au moment où tu le défies).\n"
            "⚔️ Tout le monde peut le défier — chacun son propre combat, une seule fois par apparition.\n"
            "⚠️ Tes PV restent ceux de ton pool habituel (les mêmes qu'en raid) — "
            "soigne ton équipe avant si besoin !"
        ),
        color=discord.Color.dark_orange(),
    )
    embed.set_footer(text=f"Repart dans {config.DUREE_DISPONIBILITE_DRESSEUR // 60} minutes.")
    if archetype.get("sprite"):
        embed.set_thumbnail(url=archetype["sprite"])
    return embed


class VueDefiDresseur(discord.ui.View):
    def __init__(self, dresseur_id: int):
        super().__init__(timeout=None)
        self.dresseur_id = dresseur_id

    @discord.ui.button(label="Défier", emoji="⚔️", style=discord.ButtonStyle.danger, custom_id="dresseur_defier")
    async def defier(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id

        if database.combat_en_cours_pour_joueur(user_id):
            await interaction.response.send_message("❌ Tu as déjà un combat en cours !", ephemeral=True)
            return

        noms_equipe = database.obtenir_equipe_combat_disponible(user_id)
        if not noms_equipe:
            await interaction.response.send_message(
                "❌ Configure ton équipe de combat d'abord (`/equipe-combat`) !", ephemeral=True
            )
            return

        dresseur = database.obtenir_dresseur_actif(self.dresseur_id)
        if dresseur is None or not dresseur["actif"]:
            await interaction.response.send_message("❌ Ce dresseur n'est plus disponible.", ephemeral=True)
            return

        if database.a_deja_defie_dresseur(self.dresseur_id, user_id):
            await interaction.response.send_message(
                "❌ Tu as déjà affronté ce dresseur — reviens au prochain spawn !", ephemeral=True
            )
            return

        try:
            await interaction.response.send_message(
                f"⚔️ Combat contre **{dresseur['archetype_nom']}** lancé !", ephemeral=True
            )
        except (discord.NotFound, discord.HTTPException):
            # Interaction expirée (bot ralenti/redémarré entre le clic et la réponse) — pas
            # grave en soi, mais il ne faut surtout pas que ça empêche le combat de démarrer.
            pass
        await demarrer_combat_dresseur(interaction.client, interaction.user, self.dresseur_id, interaction.channel, interaction)


def _equipe_a_un_vivant(user_id: int) -> bool:
    """True si au moins un Pokémon de l'équipe de combat a des PV persistants > 0."""
    noms = database.obtenir_equipe_combat_disponible(user_id)
    captures = database.obtenir_pokedex_joueur(user_id)
    meilleur_pc = {row["pokemon_nom"]: row["meilleur_pc"] for row in captures}
    for nom in noms:
        pc = meilleur_pc.get(nom, 0)
        if pc <= 0:
            continue
        pv_max = calculer_pv_max(pc)
        if database.obtenir_pv_actuels(user_id, nom, pv_max) > 0:
            return True
    return False


async def demarrer_combat_dresseur(
    bot,
    joueur: discord.Member,
    dresseur_id: int,
    channel: discord.TextChannel,
    interaction: discord.Interaction = None,
    multiplicateur_pc: float = 1.0,
):
    dresseur_row = database.obtenir_dresseur_actif(dresseur_id)
    archetype = next(
        (a for a in ARCHETYPES + [ARCHETYPE_GLADIO] if a["nom"] == dresseur_row["archetype_nom"]), ARCHETYPES[0]
    )

    pc_cible = round(_pc_cumule_equipe(joueur.id) * multiplicateur_pc)
    if pc_cible <= 0:
        pc_cible = 500  # équipe joueur vide/non chiffrée : petit combat par défaut

    equipe_dresseur_brute = generer_equipe_dresseur(archetype, pc_cible)

    # --- Équipe du joueur : PV tirés du pool PERSISTANT (partagé avec les raids) ---
    noms_joueur = database.obtenir_equipe_combat_disponible(joueur.id)
    captures = database.obtenir_pokedex_joueur(joueur.id)
    meilleur_pc = {row["pokemon_nom"]: row["meilleur_pc"] for row in captures}
    equipe_joueur = []
    for nom in noms_joueur:
        pc = meilleur_pc.get(nom, 0)
        if pc <= 0:
            continue
        pv_max = calculer_pv_max(pc)
        pv_actuels = database.obtenir_pv_actuels(joueur.id, nom, pv_max)
        equipe_joueur.append((nom, pv_max, pv_actuels))

    equipe_joueur_vivante = [(nom, pv_max) for nom, pv_max, pv_actuels in equipe_joueur if pv_actuels > 0]
    if not equipe_joueur_vivante:
        texte_ko = (
            f"❌ {joueur.mention} — toute ton équipe est K.O. (PV persistants à 0) ! "
            f"Soigne-la via `/equipe-combat` avant de défier un dresseur."
        )
        if interaction is not None:
            try:
                await interaction.followup.send(texte_ko, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                await channel.send(texte_ko)  # interaction expirée : repli visible plutôt que perdu
        else:
            await channel.send(texte_ko)
        return

    # Le dresseur utilise le facteur PV du PvP (0.4), pas celui des raids (0.8) : le moteur
    # de combat réutilisé ici est calibré dégâts/PV pour le PvP, sinon les PV sont ~2x trop
    # hauts par rapport à ce que les dégâts sont censés gérer, et les combats traînent.
    equipe_dresseur = [
        (nom, max(1, round(pc * config.FACTEUR_PV_COMBAT_PVP))) for nom, pc in equipe_dresseur_brute
    ]

    date_limite = int(time.time()) + combat_module.DUREE_TOUR
    actif_joueur = equipe_joueur_vivante[0][0]
    actif_dresseur = equipe_dresseur[0][0]

    # id_dresseur_combat doit être unique PAR COMBAT (pas par spawn) : plusieurs joueurs
    # peuvent désormais affronter le même dresseur en parallèle, et attaques_equipees
    # est indexée par cet ID sans notion de combat_id — un ID partagé entre deux combats
    # simultanés ferait que le second écrase les attaques équipées du premier.
    combat_id = database.creer_combat(joueur.id, 0, actif_joueur, actif_dresseur, date_limite)
    id_dresseur_combat = ID_DRESSEUR_BASE - combat_id
    database.definir_adversaire_combat(combat_id, id_dresseur_combat)

    # Les PV de départ, côté joueur, respectent l'état ACTUEL (potentiellement déjà blessé)
    conn = database.get_connexion()
    cur = conn.cursor()
    for nom, pv_max, pv_actuels in equipe_joueur:
        if pv_actuels <= 0:
            continue
        cur.execute(
            "INSERT INTO combat_equipe (combat_id, user_id, pokemon_nom, pv_max, pv_actuels, position) VALUES (?, ?, ?, ?, ?, ?)",
            (combat_id, joueur.id, nom, pv_max, pv_actuels, len(equipe_joueur)),
        )
    conn.commit()
    conn.close()
    database.initialiser_equipe_combat_pvp(combat_id, id_dresseur_combat, equipe_dresseur)

    for nom, _ in equipe_dresseur:
        _equiper_attaques_aleatoires(id_dresseur_combat, nom)

    database.enregistrer_defi_dresseur(dresseur_id, joueur.id)

    try:
        thread = await channel.create_thread(
            name=f"⚔️ {joueur.display_name} vs {archetype['nom']}",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(joueur)
    except discord.HTTPException as e:
        await channel.send(f"❌ Impossible de créer le fil de combat : {e}")
        database.terminer_combat_pvp(combat_id)
        # Ne touche pas au dresseur lui-même : c'est un spawn partagé, l'échec pour un
        # joueur ne doit pas le retirer pour les autres.
        return

    noms = {joueur.id: joueur.display_name, id_dresseur_combat: archetype["nom"]}
    embeds = combat_module.construire_embeds_combat(combat_id, noms=noms)
    vue = combat_module.VueActionCombat(combat_id, 1)

    msg = await thread.send(
        content=f"{joueur.mention} ⚔️ **{archetype['nom']}** te défie ! Choisis ton action ci-dessous.",
        embeds=embeds,
        view=vue,
    )

    # L'IA joue immédiatement son premier tour (le joueur n'attend jamais après elle)
    await _jouer_tour_ia(combat_id, id_dresseur_combat)

    bot.loop.create_task(
        _boucle_resolution_dresseur(bot, combat_id, thread.id, msg.id, dresseur_id, joueur.id, id_dresseur_combat, archetype, pc_cible)
    )


def _nettoyer_log_dresseur(log: list, id_dresseur_combat: int, nom_dresseur: str) -> list:
    """Remplace la mention <@id_synthétique> (invalide côté Discord, un ID négatif ne
    correspond à aucun utilisateur réel) par le nom du dresseur dans le log de combat."""
    mention_cassee = f"<@{id_dresseur_combat}>"
    return [ligne.replace(mention_cassee, f"**{nom_dresseur}**") for ligne in log]


async def _jouer_tour_ia(combat_id: int, dresseur_id: int):
    """L'IA choisit une action pour son tour : privilégie l'attaque (avec PP restant),
    ne switch/soigne jamais volontairement (seulement l'auto-switch sur K.O. déjà géré
    par resoudre_tour). Reste simple par choix, pour ne pas créer un adversaire frustrant."""
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return
    actif_nom = combat["actif2_nom"] if combat["joueur2_id"] == dresseur_id else combat["actif1_nom"]

    equipees = database.obtenir_attaques_equipees(dresseur_id, actif_nom)
    dispo = []
    for nom in equipees.values():
        pp_max = pp_max_attaque(combat_module.obtenir_attaque(nom))
        pp_restant = database.obtenir_pp(combat_id, dresseur_id, actif_nom, nom, pp_max)
        if pp_restant > 0:
            dispo.append(nom)

    action = f"attaque:{random.choice(dispo)}" if dispo else f"attaque:{combat_module.NOM_LUTTE}"
    database.enregistrer_action_pvp(combat_id, dresseur_id, action)


async def _boucle_resolution_dresseur(bot, combat_id, thread_id, message_id, dresseur_id, joueur_id, id_dresseur_combat, archetype, pc_cible):
    import asyncio

    while True:
        await asyncio.sleep(5)

        combat = database.obtenir_combat(combat_id)
        if not combat or not combat["actif"]:
            return

        deux_prets = combat["action1"] is not None and combat["action2"] is not None
        timer_expire = int(time.time()) >= combat["date_limite_tour"]
        if not deux_prets and not timer_expire:
            continue

        log = await combat_module.resoudre_tour(combat_id)
        log = _nettoyer_log_dresseur(log, id_dresseur_combat, archetype["nom"])
        vainqueur_id = combat_module.verifier_fin_combat(combat_id)

        thread = bot.get_channel(int(thread_id))
        if thread is None:
            database.terminer_combat_pvp(combat_id)
            return

        if vainqueur_id is not None:
            database.terminer_combat_pvp(combat_id)
            database.synchroniser_pv_persistant_depuis_combat(combat_id, joueur_id)

            if vainqueur_id == joueur_id:
                # Dégression progressive tous dresseurs confondus (voir config) — appliquée
                # AVANT le bonus de Race, comme pour l'anti-collusion PvP.
                mult_repetition = database.enregistrer_victoire_dresseur_repetition(joueur_id)
                journal.logger(f"🥾 <@{joueur_id}> a battu le dresseur **{archetype['nom']}**.")

                if archetype["nom"] == pnj.NOM_RIVAL:
                    # Gladio est limité à une fois par jour (cooldown dédié) : récompense
                    # fixe et généreuse, indépendante du PC et de la dégression anti-farm
                    # des dresseurs classiques (qui n'a pas de sens pour un combat unique/jour).
                    dollars = round(
                        random.randint(config.GLADIO_RECOMPENSE_MIN, config.GLADIO_RECOMPENSE_MAX)
                        * database.multiplicateur_boost(joueur_id, "argent")
                    )
                else:
                    dollars = round(
                        pc_cible * config.DRESSEUR_FACTEUR_DOLLARS * mult_repetition
                        * database.multiplicateur_boost(joueur_id, "argent")
                    )
                xp = round(pc_cible * config.DRESSEUR_FACTEUR_XP * mult_repetition)
                # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
                # applique son propre multiplicateur en interne, donc on le reproduit ici seulement
                # pour le texte, sans le compter deux fois en base.
                xp_affichee = round(xp * database.multiplicateur_boost(joueur_id, "xp"))
                database.ajouter_poke_dollars(joueur_id, dollars)
                leveling.gagner_xp(joueur_id, xp)
                database.incrementer_victoires_pve(joueur_id)
                quetes_completees = database.incrementer_progression_quete(joueur_id, "pve_victoire")

                note_reduction = (
                    "\n*(récompense réduite : plusieurs dresseurs déjà battus aujourd'hui)*"
                    if mult_repetition < 1.0 and archetype["nom"] != pnj.NOM_RIVAL else ""
                )
                embed = discord.Embed(
                    title=f"🏆 Victoire contre {archetype['nom']} !",
                    description=(
                        "\n".join(log)
                        + f"\n\n🎖️ +{dollars} Poké Dollars & +{xp_affichee} XP !{note_reduction}"
                        + quetes_ui.texte_notifications_completion(quetes_completees)
                    ),
                    color=discord.Color.gold(),
                )
            else:
                embed = discord.Embed(
                    title=f"💀 Défaite face à {archetype['nom']}...",
                    description="\n".join(log) + "\n\nTon équipe est à plat — pense à la soigner avant de repartir à l'aventure.",
                    color=discord.Color.red(),
                )

            embed_rival = None
            if vainqueur_id != joueur_id and random.random() < 0.3:
                embed_rival = pnj.construire_embed_reaction("defaite_dresseur", user_id=joueur_id, joueur=f"<@{joueur_id}>")
            elif vainqueur_id == joueur_id and archetype["nom"] == pnj.NOM_RIVAL:
                embed_rival = pnj.construire_embed_reaction("victoire_gladio", user_id=joueur_id, joueur=f"<@{joueur_id}>")

            try:
                msg = await thread.fetch_message(message_id)
                embeds_a_envoyer = [embed, embed_rival] if embed_rival else [embed]
                await msg.edit(embeds=embeds_a_envoyer, view=None)
            except discord.NotFound:
                await thread.send(embeds=embeds_a_envoyer)

            bot.loop.create_task(_supprimer_fil_apres_delai(thread, combat_module.DELAI_SUPPRESSION_FIL))
            return

        # Tour suivant : l'IA rejoue tout de suite, seul le joueur humain fait attendre
        nouvelle_limite = int(time.time()) + combat_module.DUREE_TOUR
        database.passer_tour_pvp(combat_id, nouvelle_limite)
        await _jouer_tour_ia(combat_id, id_dresseur_combat)

        combat = database.obtenir_combat(combat_id)
        utilisateur = bot.get_user(joueur_id)
        noms = {joueur_id: (utilisateur.display_name if utilisateur else "Toi"), id_dresseur_combat: archetype["nom"]}
        embeds = combat_module.construire_embeds_combat(combat_id, log_tour=log, noms=noms)
        vue = combat_module.VueActionCombat(combat_id, combat["tour"])
        try:
            msg = await thread.fetch_message(message_id)
            await msg.edit(embeds=embeds, view=vue)
        except discord.NotFound:
            pass


async def _supprimer_fil_apres_delai(thread, delai):
    import asyncio
    await asyncio.sleep(delai)
    try:
        await thread.delete()
    except Exception:
        pass


async def faire_partir_dresseur_si_non_defie(bot, dresseur_id: int, channel_id: int, delai: int):
    """Fait disparaître le dresseur (message mis à jour) une fois sa fenêtre de
    disponibilité écoulée — que personne, un seul joueur, ou plusieurs l'aient déjà
    défié entre-temps (spawn partagé, pas un verrou premier-arrivé)."""
    import asyncio
    await asyncio.sleep(delai)

    dresseur = database.obtenir_dresseur_actif(dresseur_id)
    if dresseur is None or not dresseur["actif"]:
        return  # déjà terminé, rien à faire

    database.terminer_dresseur(dresseur_id)
    channel = bot.get_channel(int(channel_id))
    if channel is None or not dresseur["message_id"]:
        return
    try:
        message = await channel.fetch_message(int(dresseur["message_id"]))
        embed = discord.Embed(
            title=f"💨 {dresseur['archetype_nom']} est reparti sur la route...",
            description="Son temps est écoulé.",
            color=discord.Color.dark_grey(),
        )
        await message.edit(embed=embed, view=None)
        bot.loop.create_task(_supprimer_message_apres_delai(message, 120))
    except discord.HTTPException:
        pass


async def _supprimer_message_apres_delai(message, delai):
    import asyncio
    await asyncio.sleep(delai)
    try:
        await message.delete()
    except Exception:
        pass


async def defier_gladio(bot, joueur: discord.Member, channel: discord.TextChannel, interaction: discord.Interaction):
    """Défi à la demande contre Gladio (le rival) — réutilise entièrement le moteur de
    combat dresseur existant. Équipe légèrement plus forte que celle du joueur (+15% de
    PC cible) pour un vrai ressenti de rival, cooldown dédié (config.GLADIO_COOLDOWN_DEFI,
    indépendant des dresseurs spontanés).

    Le cooldown n'est marqué qu'une fois confirmé que le combat peut vraiment démarrer
    (équipe pas entièrement K.O.) — sinon une tentative ratée grillerait le défi du jour
    pour rien."""
    if not _equipe_a_un_vivant(joueur.id):
        texte_ko = (
            f"❌ {joueur.mention} — toute ton équipe est K.O. (PV persistants à 0) ! "
            f"Soigne-la via `/equipe-combat` avant de défier Gladio."
        )
        if interaction is not None:
            try:
                await interaction.followup.send(texte_ko, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                await channel.send(texte_ko)
        else:
            await channel.send(texte_ko)
        return

    dresseur_id = database.creer_dresseur_actif(ARCHETYPE_GLADIO["nom"], channel.id, int(time.time()) + 300)
    database.marquer_defi_gladio(joueur.id)
    await demarrer_combat_dresseur(bot, joueur, dresseur_id, channel, interaction, multiplicateur_pc=1.15)
