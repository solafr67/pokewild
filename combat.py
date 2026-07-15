import random
import time

import discord

import config
import database
import leveling
import quetes_ui
from pokemon_data import (
    ATTAQUE_DEFAUT_NOM,
    ATTAQUES_CHARGE,
    ATTAQUES_RECHARGE,
    ATTAQUES_TERRAIN,
    EMOJI_RARETE,
    EMOJI_TYPES,
    calculer_multiplicateur_type,
    obtenir_attaque,
    obtenir_pokemon_par_nom,
    pp_max_attaque,
    sprite_pokemon,
)

DUREE_TOUR = 45  # secondes avant qu'un tour se résolve automatiquement
DELAI_SUPPRESSION_FIL = 120  # secondes après la fin du combat avant suppression auto du fil
# Dégâts = PC × puissance_attaque / PUISSANCE_DIVISEUR_COMBAT × STAB × types × boosts × variance
# Calibré pour ~3 tours de K.O. à puissance égale avec une attaque standard (80 pcs)
PUISSANCE_DIVISEUR_COMBAT = 640

# Lutte : attaque de secours automatique quand toutes les attaques équipées sont à 0 PP
# (comme dans les vrais jeux). Ne consomme pas de PP (infinie), mais inflige un contrecoup.
NOM_LUTTE = "Lutte"
ATTAQUE_LUTTE = {"type": None, "puissance": 50, "precision": None, "classe": "physical", "stats": [], "cible": "adversaire"}
LUTTE_RECOIL_POURCENT = 0.25  # 25% des PV max de l'attaquant en contrecoup

# Altérations de statut : émoji, libellé, et effets
STATUTS_INFO = {
    "burn":      {"emoji": "🔥", "nom": "brûlé"},
    "poison":    {"emoji": "☠️", "nom": "empoisonné"},
    "paralysis": {"emoji": "⚡", "nom": "paralysé"},
    "sleep":     {"emoji": "💤", "nom": "endormi"},
    "freeze":    {"emoji": "❄️", "nom": "gelé"},
    "confusion": {"emoji": "🌀", "nom": "confus"},
}
DEGATS_BRULURE_POURCENT = 0.06   # 6% des PV max par tour
DEGATS_POISON_POURCENT = 0.10    # 10% des PV max par tour
CHANCE_PARALYSIE_SKIP = 0.25     # 25% de ne pas pouvoir agir
CHANCE_DEGEL = 0.20              # 20% de dégeler chaque tour
CHANCE_CONFUSION_SKIP = 0.33     # 33% de se blesser au lieu d'agir
DOLLARS_VICTOIRE = 150
XP_VICTOIRE = 80
XP_DEFAITE = 30


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------

def _barre_pv(pv_actuel: int, pv_max: int, longueur: int = 12) -> str:
    """Barre de PV colorée selon l'état : vert > 50%, jaune > 20%, rouge en dessous."""
    ratio = max(0, min(1, pv_actuel / pv_max)) if pv_max else 0
    rempli = round(longueur * ratio)
    if ratio > 0.5:
        bloc = "🟩"
    elif ratio > 0.2:
        bloc = "🟨"
    else:
        bloc = "🟥"
    return bloc * rempli + "⬛" * (longueur - rempli)


def sprite_anime(pokemon: dict) -> str | None:
    """Alias local vers pokemon_data.sprite_pokemon (couvre toutes les générations)."""
    return sprite_pokemon(pokemon)


def _bloc_reserve(equipe, actif_nom: str) -> str:
    """Ligne compacte listant la réserve : nom + PV, 💀 pour les K.O."""
    morceaux = []
    for row in equipe:
        if row["pokemon_nom"] == actif_nom:
            continue
        if row["pv_actuels"] <= 0:
            morceaux.append(f"💀 ~~{row['pokemon_nom']}~~")
        else:
            morceaux.append(f"{row['pokemon_nom']} ({row['pv_actuels']})")
    return " • ".join(morceaux) if morceaux else "*Aucune réserve*"


def construire_embeds_combat(combat_id: int, log_tour: list = None, noms: dict = None) -> list:
    """Construit les embeds du combat : un par joueur (sprite animé du Pokémon actif,
    barre de PV, réserve), plus un embed de log si un tour vient d'être résolu."""
    combat = database.obtenir_combat(combat_id)
    if combat is None:
        return [discord.Embed(description="Combat introuvable.", color=discord.Color.red())]

    embeds = []
    couleurs = [discord.Color.blue(), discord.Color.red()]
    cotes = [
        (combat["joueur1_id"], combat["actif1_nom"], combat["action1"]),
        (combat["joueur2_id"], combat["actif2_nom"], combat["action2"]),
    ]

    for (user_id, actif_nom, action), couleur in zip(cotes, couleurs):
        equipe = database.obtenir_equipe_pvp(combat_id, user_id)
        actif_row = next((r for r in equipe if r["pokemon_nom"] == actif_nom), None)
        pokemon = obtenir_pokemon_par_nom(actif_nom)

        nom_joueur = noms.get(user_id) if noms else None
        nom_joueur = nom_joueur or f"Joueur {str(user_id)[-4:]}"
        statut = "✅ prêt" if action else "⏳ choisit..."

        embed = discord.Embed(color=couleur)
        embed.set_author(name=f"{nom_joueur} — {statut}")
        if actif_row:
            # Émoji de statut à côté du nom (🔥 brûlé, 💤 endormi...)
            statut_actif = database.obtenir_statut(combat_id, user_id, actif_nom)
            emoji_statut = f" {STATUTS_INFO[statut_actif[0]]['emoji']}" if statut_actif and statut_actif[0] in STATUTS_INFO else ""
            embed.title = f"{actif_nom}{emoji_statut}"

            description = (
                f"{_barre_pv(actif_row['pv_actuels'], actif_row['pv_max'])}\n"
                f"❤️ **{actif_row['pv_actuels']} / {actif_row['pv_max']} PV**"
            )
            # Boosts de stats affichés s'ils sont non nuls (📊 Atq +1 • Vit -2)
            boosts = database.obtenir_boosts(combat_id, user_id, actif_nom)
            morceaux_boosts = [
                f"{label} {boosts[stat]:+d}"
                for stat, label in (("atk", "Atq"), ("def", "Déf"), ("vit", "Vit"))
                if boosts[stat] != 0
            ]
            if morceaux_boosts:
                description += f"\n📊 {' • '.join(morceaux_boosts)}"
            embed.description = description
        url_sprite = sprite_anime(pokemon)
        if url_sprite:
            embed.set_thumbnail(url=url_sprite)
        embed.add_field(name="Réserve", value=_bloc_reserve(equipe, actif_nom), inline=False)
        embeds.append(embed)

    dernier = discord.Embed(color=discord.Color.dark_grey())
    dernier.set_author(name=f"⚔️ Tour {combat['tour']}")
    if log_tour:
        dernier.description = "\n".join(log_tour)
    temps_restant = max(0, combat["date_limite_tour"] - int(time.time()))
    dernier.set_footer(text=f"Tour résolu quand les deux joueurs ont joué, ou dans ~{temps_restant}s")
    embeds.append(dernier)

    return embeds


def _texte_efficacite(multi: float) -> str:
    if multi >= 4.0:
        return "🔥🔥 C'est hyper efficace !!"
    if multi >= 2.0:
        return "🔥 C'est super efficace !"
    if multi == 0.0:
        return "🚫 Ça n'a aucun effet..."
    if multi <= 0.25:
        return "❄️❄️ C'est vraiment peu efficace..."
    if multi < 1.0:
        return "❄️ Ce n'est pas très efficace..."
    return ""


# ----------------------------------------------------------------------------
# Initialisation du combat
# ----------------------------------------------------------------------------

def preparer_equipe_pour_combat(user_id: int) -> list:
    """Construit la liste (nom, pv_max) à partir de l'équipe de combat et du meilleur PC connu.
    Utilise le facteur PV spécifique au PvP (plus bas que celui des raids, pour des
    combats en 3-5 tours à la Pokémon plutôt que des marathons)."""
    noms = database.obtenir_equipe_combat_disponible(user_id)
    captures = database.obtenir_pokedex_joueur(user_id)
    meilleur_pc = {row["pokemon_nom"]: row["meilleur_pc"] for row in captures}
    return [
        (nom, max(1, round(meilleur_pc.get(nom, 100) * config.FACTEUR_PV_COMBAT_PVP)))
        for nom in noms
        if nom in meilleur_pc
    ]


async def demarrer_combat(bot, joueur1: discord.Member, joueur2: discord.Member, channel: discord.TextChannel):
    """Crée le thread privé et envoie UN message unique contenant les embeds du combat
    ET les boutons d'action partagés (chaque joueur ne peut enregistrer que sa propre
    action, vérifié en base au moment du clic)."""
    equipe1 = preparer_equipe_pour_combat(joueur1.id)
    equipe2 = preparer_equipe_pour_combat(joueur2.id)

    if not equipe1 or not equipe2:
        await channel.send("❌ L'un des joueurs n'a pas d'équipe de combat configurée (`/equipe-combat`).")
        return

    date_limite = int(time.time()) + DUREE_TOUR
    actif1 = equipe1[0][0]
    actif2 = equipe2[0][0]

    combat_id = database.creer_combat(joueur1.id, joueur2.id, actif1, actif2, date_limite)
    database.initialiser_equipe_combat_pvp(combat_id, joueur1.id, equipe1)
    database.initialiser_equipe_combat_pvp(combat_id, joueur2.id, equipe2)

    try:
        thread = await channel.create_thread(
            name=f"⚔️ {joueur1.display_name} vs {joueur2.display_name}",
            type=discord.ChannelType.public_thread,  # public : visible et rejoignable par tous pour visionner
        )
        await thread.add_user(joueur1)
        await thread.add_user(joueur2)
    except discord.HTTPException as e:
        await channel.send(f"❌ Impossible de créer le thread : {e}")
        database.terminer_combat_pvp(combat_id)
        return

    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET thread_id = ? WHERE id = ?", (str(thread.id), combat_id))
    conn.commit()
    conn.close()

    noms = {joueur1.id: joueur1.display_name, joueur2.id: joueur2.display_name}
    embeds = construire_embeds_combat(combat_id, noms=noms)
    vue = VueActionCombat(combat_id, 1)

    msg = await thread.send(
        content=f"{joueur1.mention} {joueur2.mention} ⚔️ Le combat commence ! Choisissez votre action ci-dessous.",
        embeds=embeds,
        view=vue,
    )

    bot.loop.create_task(boucle_resolution_tour(bot, combat_id, thread.id, msg.id, DUREE_TOUR))


# ----------------------------------------------------------------------------
# Résolution d'un tour
# ----------------------------------------------------------------------------

def _appliquer_hazards_entree(combat_id: int, user_id: int, pokemon_nom: str, log: list):
    """Applique les pièges de terrain (posés contre le camp de user_id) au Pokémon qui
    vient d'entrer en combat. Comme dans les vrais jeux : Piège de Roc inflige des dégâts
    multipliés par la faiblesse au type roche, Picots cumulent, Pics Toxik empoisonnent."""
    hazards = database.obtenir_hazards(combat_id, user_id)
    if not hazards:
        return

    eq = database.obtenir_equipe_pvp(combat_id, user_id)
    row = next((r for r in eq if r["pokemon_nom"] == pokemon_nom), None)
    if row is None or row["pv_actuels"] <= 0:
        return

    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    types_pokemon = pokemon["types"] if pokemon else ["normal"]

    if "stealth_rock" in hazards:
        multi = calculer_multiplicateur_type(["roche"], types_pokemon)
        degats = max(1, round(row["pv_max"] * 0.125 * multi))
        pv = database.appliquer_degats_pvp(combat_id, user_id, pokemon_nom, degats)
        log.append(f"  🪨 **{pokemon_nom}** est blessé par le Piège de Roc ! (-{degats} PV)")
        if pv <= 0:
            log.append(f"  💀 **{pokemon_nom}** est K.O. !")
            return

    if "spikes" in hazards:
        part = {1: 0.08, 2: 0.12, 3: 0.17}.get(hazards["spikes"], 0.08)
        degats = max(1, round(row["pv_max"] * part))
        pv = database.appliquer_degats_pvp(combat_id, user_id, pokemon_nom, degats)
        log.append(f"  📌 **{pokemon_nom}** est blessé par les Picots ! (-{degats} PV)")
        if pv <= 0:
            log.append(f"  💀 **{pokemon_nom}** est K.O. !")
            return

    if "toxic_spikes" in hazards:
        if database.definir_statut(combat_id, user_id, pokemon_nom, "poison"):
            log.append(f"  ☠️ **{pokemon_nom}** est empoisonné par les Pics Toxik !")


async def resoudre_tour(combat_id: int) -> list:
    """Exécute les actions des deux joueurs et retourne le log du tour.

    Ordre de résolution (comme les vrais jeux) :
    1. Changements de Pokémon (toujours prioritaires)
    2. Potions
    3. Attaques, dans l'ordre de VITESSE (PC modifié par les stages de vitesse) —
       si le premier attaquant met K.O. l'adversaire, la riposte est annulée.
    """
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return []

    j1, j2 = combat["joueur1_id"], combat["joueur2_id"]
    a1 = combat["action1"] or f"attaque:{ATTAQUE_DEFAUT_NOM}"
    a2 = combat["action2"] or f"attaque:{ATTAQUE_DEFAUT_NOM}"

    log = []

    def infos_actif(user_id):
        cbt = database.obtenir_combat(combat_id)
        nom = cbt["actif1_nom"] if user_id == j1 else cbt["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        row = next((r for r in eq if r["pokemon_nom"] == nom), None)
        return nom, row

    def pc_depuis_pv_max(pv_max):
        return pv_max / config.FACTEUR_PV_COMBAT_PVP

    def mult_stage(stage: int) -> float:
        """Multiplicateur officiel Pokémon pour un stage de stat (-6..+6)."""
        return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)

    NOMS_STATS = {"atk": "Attaque", "def": "Défense", "vit": "Vitesse"}

    # --- Phase 1 : changements de Pokémon (réinitialisent les boosts du sortant) ---
    for user_id, action in ((j1, a1), (j2, a2)):
        if action.startswith("changer:"):
            ancien_nom, _ = infos_actif(user_id)
            nouveau = action.split(":", 1)[1]
            database.reinitialiser_boosts(combat_id, user_id, ancien_nom)
            database.reinitialiser_charge(combat_id, user_id, ancien_nom)
            database.changer_pokemon_actif_pvp(combat_id, user_id, nouveau)
            log.append(f"<@{user_id}> rappelle **{ancien_nom}** et envoie **{nouveau}** !")
            _appliquer_hazards_entree(combat_id, user_id, nouveau, log)

    # --- Phase 2 : potions ---
    for user_id, action in ((j1, a1), (j2, a2)):
        if action.startswith("potion:"):
            type_potion = action.split(":", 1)[1]
            nom, row = infos_actif(user_id)
            if row is None:
                continue

            if type_potion == "totalsoin":
                statut_actuel = database.obtenir_statut(combat_id, user_id, nom)
                if statut_actuel:
                    database.retirer_statut(combat_id, user_id, nom)
                    info = STATUTS_INFO.get(statut_actuel[0], {"emoji": "✨", "nom": statut_actuel[0]})
                    log.append(f"<@{user_id}> : **{nom}** utilise 🌿 Total Soin → {info['emoji']} {info['nom']} soigné !")
                else:
                    log.append(f"<@{user_id}> : **{nom}** utilise 🌿 Total Soin, mais n'avait aucun problème de statut.")
                continue

            delta = max(1, round(row["pv_max"] * config.SOIN_POURCENT.get(type_potion, 0.3)))
            pv_apres = database.soigner_pvp(combat_id, user_id, nom, delta)
            log.append(f"<@{user_id}> : **{nom}** est soigné → {pv_apres}/{row['pv_max']} PV")

    # --- Phase 3 : attaques, ordonnées par vitesse ---
    attaquants = []
    for user_id, adversaire_id, action in ((j1, j2, a1), (j2, j1, a2)):
        if not action.startswith("attaque:"):
            continue
        nom, row = infos_actif(user_id)
        if row is None or row["pv_actuels"] <= 0:
            continue
        boosts = database.obtenir_boosts(combat_id, user_id, nom)
        vitesse = pc_depuis_pv_max(row["pv_max"]) * mult_stage(boosts["vit"])
        statut_actuel = database.obtenir_statut(combat_id, user_id, nom)
        if statut_actuel and statut_actuel[0] == "paralysis":
            vitesse /= 2  # la paralysie ralentit
        attaquants.append((vitesse + random.random(), user_id, adversaire_id, action.split(":", 1)[1]))

    attaquants.sort(reverse=True)  # le plus rapide agit en premier

    for _, user_id, adversaire_id, nom_attaque in attaquants:
        nom_atk, row_atk = infos_actif(user_id)
        nom_def, row_def = infos_actif(adversaire_id)
        if row_atk is None or row_atk["pv_actuels"] <= 0:
            log.append(f"💫 **{nom_atk}** est K.O. et ne peut pas attaquer !")
            continue
        if row_def is None:
            continue

        # --- Le statut de l'attaquant peut l'empêcher d'agir ---
        statut_atk = database.obtenir_statut(combat_id, user_id, nom_atk)
        if statut_atk:
            code_statut = statut_atk[0]
            if code_statut == "sleep":
                compteur = database.decrementer_compteur_statut(combat_id, user_id, nom_atk)
                if compteur <= 0:
                    database.retirer_statut(combat_id, user_id, nom_atk)
                    log.append(f"☀️ **{nom_atk}** se réveille !")
                else:
                    log.append(f"💤 **{nom_atk}** dort profondément...")
                    continue
            elif code_statut == "freeze":
                if random.random() < CHANCE_DEGEL:
                    database.retirer_statut(combat_id, user_id, nom_atk)
                    log.append(f"☀️ **{nom_atk}** dégèle !")
                else:
                    log.append(f"❄️ **{nom_atk}** est gelé et ne peut pas bouger !")
                    continue
            elif code_statut == "paralysis" and random.random() < CHANCE_PARALYSIE_SKIP:
                log.append(f"⚡ **{nom_atk}** est paralysé ! Il ne peut pas attaquer !")
                continue
            elif code_statut == "confusion":
                compteur = database.decrementer_compteur_statut(combat_id, user_id, nom_atk)
                if compteur <= 0:
                    database.retirer_statut(combat_id, user_id, nom_atk)
                    log.append(f"✨ **{nom_atk}** n'est plus confus !")
                elif random.random() < CHANCE_CONFUSION_SKIP:
                    degats_confusion = max(1, round(row_atk["pv_max"] * 0.05))
                    database.appliquer_degats_pvp(combat_id, user_id, nom_atk, degats_confusion)
                    log.append(f"🌀 **{nom_atk}** est confus et se blesse lui-même ! (-{degats_confusion} PV)")
                    continue

        # --- Charge / recharge (attaques à deux tours type Lance-Soleil, Ultimaton) ---
        charge_info = database.obtenir_charge(combat_id, user_id, nom_atk)
        if charge_info["doit_recharger"]:
            database.definir_charge(combat_id, user_id, nom_atk, None, False)
            log.append(f"<@{user_id}> : **{nom_atk}** doit récupérer et ne peut pas attaquer ce tour-ci !")
            continue

        liberation_charge = False
        if charge_info["attaque_en_charge"]:
            # Le joueur ne choisit plus rien tant que la charge n'est pas relâchée — comme
            # dans les vrais jeux, l'attaque enregistrée ce tour-ci est ignorée.
            nom_attaque = charge_info["attaque_en_charge"]
            liberation_charge = True
            database.definir_charge(combat_id, user_id, nom_atk, None, False)

        if nom_attaque == NOM_LUTTE:
            attaque = ATTAQUE_LUTTE
        else:
            attaque = obtenir_attaque(nom_attaque)
            pp_max = pp_max_attaque(attaque)
            if liberation_charge:
                # Le PP a déjà été consommé au tour de charge — on ne fait que le lire ici.
                pp_restant = database.obtenir_pp(combat_id, user_id, nom_atk, nom_attaque, pp_max)
            else:
                pp_restant = database.consommer_pp(combat_id, user_id, nom_atk, nom_attaque, pp_max)
        emoji_type = EMOJI_TYPES.get(attaque["type"], "⚔️")

        if not liberation_charge and nom_attaque in ATTAQUES_CHARGE:
            database.definir_charge(combat_id, user_id, nom_atk, nom_attaque, False)
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** "
                f"— commence à charger son énergie !"
            )
            continue

        if liberation_charge:
            log.append(f"<@{user_id}> : **{nom_atk}** relâche toute son énergie chargée !")

        # Test de précision
        precision = attaque.get("precision")
        if precision is not None and random.random() * 100 > precision:
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... mais rate !")
            continue

        if attaque.get("puissance"):
            # --- Attaque offensive ---
            pok_atk = obtenir_pokemon_par_nom(nom_atk)
            pok_def = obtenir_pokemon_par_nom(nom_def)
            types_atk_pokemon = pok_atk["types"] if pok_atk else ["normal"]
            types_def = pok_def["types"] if pok_def else ["normal"]

            if attaque["type"] is None:
                multi_type, stab = 1.0, 1.0  # Lutte : ni faiblesse/résistance, ni STAB
            else:
                multi_type = calculer_multiplicateur_type([attaque["type"]], types_def)
                stab = 1.5 if attaque["type"] in types_atk_pokemon else 1.0

            # Immunité totale : aucun dégât (plus jamais de "-1 PV / aucun effet")
            if multi_type == 0.0:
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}**..."
                )
                log.append("  🚫 Ça n'affecte pas " + nom_def + " !")
                continue

            boosts_atk = database.obtenir_boosts(combat_id, user_id, nom_atk)
            boosts_def = database.obtenir_boosts(combat_id, adversaire_id, nom_def)

            pc = pc_depuis_pv_max(row_atk["pv_max"])
            variance = random.uniform(0.85, 1.15)
            degats = max(1, round(
                pc * attaque["puissance"] / PUISSANCE_DIVISEUR_COMBAT
                * multi_type * stab * variance
                * mult_stage(boosts_atk["atk"]) / mult_stage(boosts_def["def"])
            ))

            pv_restants = database.appliquer_degats_pvp(combat_id, adversaire_id, nom_def, degats)
            pp_txt = "" if nom_attaque == NOM_LUTTE else f" ({pp_restant}/{pp_max} PP)"
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}** → -{degats} PV{pp_txt}"
            )
            efficacite = _texte_efficacite(multi_type)
            if efficacite:
                log.append(f"  {efficacite}")
            if pv_restants <= 0:
                log.append(f"  💀 **{nom_def}** est K.O. !")

            if nom_attaque in ATTAQUES_RECHARGE:
                database.definir_charge(combat_id, user_id, nom_atk, None, True)
                log.append(f"  😵‍💫 **{nom_atk}** doit maintenant récupérer !")

            if nom_attaque == NOM_LUTTE:
                recoil = max(1, round(row_atk["pv_max"] * LUTTE_RECOIL_POURCENT))
                pv_apres_recoil = database.appliquer_degats_pvp(combat_id, user_id, nom_atk, recoil)
                log.append(f"  💥 **{nom_atk}** subit le contrecoup de Lutte ! (-{recoil} PV)")
                if pv_apres_recoil <= 0:
                    log.append(f"  💀 **{nom_atk}** est K.O. par le contrecoup !")

            # Altération de statut éventuelle (ex: Flammèche 10% de brûler)
            ailment = attaque.get("ailment")
            if ailment in STATUTS_INFO and pv_restants > 0:
                chance = attaque.get("ailment_chance", 0) or 100  # 0 = garanti (attaques de statut pur)
                if random.random() * 100 < chance:
                    compteur = 0
                    if ailment == "sleep":
                        compteur = random.randint(1, 3)
                    elif ailment == "confusion":
                        compteur = random.randint(1, 4)
                    if database.definir_statut(combat_id, adversaire_id, nom_def, ailment, compteur):
                        info = STATUTS_INFO[ailment]
                        log.append(f"  {info['emoji']} **{nom_def}** est {info['nom']} !")
        else:
            # --- Attaque de terrain (Piège de Roc, Picots, Pics Toxik) ---
            if nom_attaque in ATTAQUES_TERRAIN:
                effet = ATTAQUES_TERRAIN[nom_attaque]
                stacks_max = 3 if effet == "spikes" else 1
                stacks = database.poser_hazard(combat_id, adversaire_id, effet, stacks_max)
                couches_txt = f" (couche {stacks}/{stacks_max})" if stacks_max > 1 else ""
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** — "
                    f"le piège est posé du côté adverse !{couches_txt}"
                )
                continue

            # --- Attaque de statut (boosts / malus / altérations) ---
            changements = attaque.get("stats", [])
            ailment = attaque.get("ailment")

            if not changements and ailment not in STATUTS_INFO:
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** (sans effet notable)")
                continue

            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !")

            # Changements de stats éventuels
            if changements:
                if attaque.get("cible") == "soi":
                    cible_id, cible_nom = user_id, nom_atk
                else:
                    cible_id, cible_nom = adversaire_id, nom_def

                morceaux = []
                for stat, delta in changements:
                    nouveau_stage = database.modifier_boost(combat_id, cible_id, cible_nom, stat, delta)
                    signe = "+" if delta > 0 else ""
                    morceaux.append(f"{signe}{delta} {NOMS_STATS[stat]} (stage {nouveau_stage:+d})")
                log.append(f"  📊 **{cible_nom}** : {', '.join(morceaux)}")

            # Altération de statut pure (Hypnose → sommeil, Para-Spore → paralysie...)
            if ailment in STATUTS_INFO:
                compteur = 0
                if ailment == "sleep":
                    compteur = random.randint(1, 3)
                elif ailment == "confusion":
                    compteur = random.randint(1, 4)
                if database.definir_statut(combat_id, adversaire_id, nom_def, ailment, compteur):
                    info = STATUTS_INFO[ailment]
                    log.append(f"  {info['emoji']} **{nom_def}** est {info['nom']} !")
                else:
                    log.append(f"  ❌ **{nom_def}** a déjà une altération de statut !")

    # --- Dégâts de fin de tour : brûlure et poison ---
    combat = database.obtenir_combat(combat_id)
    for user_id in (j1, j2):
        nom_actif = combat["actif1_nom"] if user_id == j1 else combat["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        actif_row = next((r for r in eq if r["pokemon_nom"] == nom_actif), None)
        if actif_row is None or actif_row["pv_actuels"] <= 0:
            continue
        statut_actif = database.obtenir_statut(combat_id, user_id, nom_actif)
        if not statut_actif:
            continue
        code = statut_actif[0]
        if code in ("burn", "poison"):
            pourcent = DEGATS_BRULURE_POURCENT if code == "burn" else DEGATS_POISON_POURCENT
            degats_statut = max(1, round(actif_row["pv_max"] * pourcent))
            pv_apres = database.appliquer_degats_pvp(combat_id, user_id, nom_actif, degats_statut)
            info = STATUTS_INFO[code]
            log.append(f"{info['emoji']} **{nom_actif}** souffre de son statut ({info['nom']}) : -{degats_statut} PV")
            if pv_apres <= 0:
                log.append(f"  💀 **{nom_actif}** est K.O. !")

    # --- Vérifier les K.O. et changer auto si nécessaire ---
    combat = database.obtenir_combat(combat_id)
    for user_id in (j1, j2):
        nom_actif = combat["actif1_nom"] if user_id == j1 else combat["actif2_nom"]
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        actif_row = next((r for r in eq if r["pokemon_nom"] == nom_actif), None)
        if actif_row and actif_row["pv_actuels"] <= 0:
            database.reinitialiser_boosts(combat_id, user_id, nom_actif)
            suivant = next((r["pokemon_nom"] for r in eq if r["pv_actuels"] > 0), None)
            if suivant:
                database.changer_pokemon_actif_pvp(combat_id, user_id, suivant)
                log.append(f"  → <@{user_id}> envoie **{suivant}** !")
                _appliquer_hazards_entree(combat_id, user_id, suivant, log)

    return log


def verifier_fin_combat(combat_id: int) -> int | None:
    """Vérifie si une équipe est entièrement K.O. Retourne l'ID du vainqueur, ou None."""
    combat = database.obtenir_combat(combat_id)
    if not combat:
        return None

    for user_id, adversaire_id in [(combat["joueur1_id"], combat["joueur2_id"]), (combat["joueur2_id"], combat["joueur1_id"])]:
        eq = database.obtenir_equipe_pvp(combat_id, user_id)
        if all(r["pv_actuels"] <= 0 for r in eq):
            return adversaire_id  # l'adversaire a gagné

    return None


async def supprimer_fil_apres_delai(thread, delai_secondes: int):
    """Supprime le fil de combat après un délai, sans planter s'il a déjà disparu."""
    import asyncio

    await asyncio.sleep(delai_secondes)
    try:
        await thread.delete()
    except Exception:
        pass  # fil déjà supprimé, permissions manquantes, etc.


async def resoudre_abandon(bot, combat_id: int, perdant_id: int):
    """Résout un abandon : le joueur qui quitte perd, l'adversaire gagne par forfait."""
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return

    vainqueur_id = combat["joueur2_id"] if perdant_id == combat["joueur1_id"] else combat["joueur1_id"]
    database.terminer_combat_pvp(combat_id)
    mult_repetition = database.enregistrer_victoire_pvp_repetition(vainqueur_id, perdant_id)
    database.ajouter_poke_dollars(vainqueur_id, round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent")))
    quetes_completees = database.incrementer_progression_quete(vainqueur_id, "pvp_victoire")
    database.incrementer_victoires_pvp(vainqueur_id)
    leveling.gagner_xp(vainqueur_id, round(XP_VICTOIRE * mult_repetition))
    leveling.gagner_xp(perdant_id, XP_DEFAITE)

    vainqueur = bot.get_user(vainqueur_id)
    perdant = bot.get_user(perdant_id)
    nom_vainqueur = vainqueur.display_name if vainqueur else f"Joueur {vainqueur_id}"
    nom_perdant = perdant.display_name if perdant else f"Joueur {perdant_id}"

    dollars_reels = round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent"))
    # xp_reels = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp() applique
    # son propre multiplicateur en interne, on le reproduit ici seulement pour le texte affiché.
    xp_reels = round(round(XP_VICTOIRE * mult_repetition) * database.multiplicateur_boost(vainqueur_id, "xp"))
    xp_defaite_reelle = round(XP_DEFAITE * database.multiplicateur_boost(perdant_id, "xp"))
    note_reduction = "\n*(récompense réduite : déjà battu cet adversaire aujourd'hui)*" if mult_repetition < 1.0 else ""

    embed = discord.Embed(
        title=f"🏳️ {nom_perdant} a abandonné !",
        description=(
            f"**{nom_vainqueur}** remporte le combat par forfait.\n\n"
            f"🎖️ +{dollars_reels} Poké Dollars & +{xp_reels} XP au vainqueur.{note_reduction}\n"
            f"+{xp_defaite_reelle} XP de consolation pour {nom_perdant}."
            f"{quetes_ui.texte_notifications_completion(quetes_completees)}"
        ),
        color=discord.Color.orange(),
    )

    if combat["thread_id"]:
        try:
            thread = bot.get_channel(int(combat["thread_id"]))
            if thread:
                await thread.send(embed=embed)
                await thread.send(f"🗑️ Ce fil sera supprimé automatiquement dans {DELAI_SUPPRESSION_FIL // 60} minutes.")
                bot.loop.create_task(supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))
        except Exception:
            pass


async def boucle_resolution_tour(bot, combat_id: int, thread_id: int, message_id: int, duree: int):
    """Attend la fin du timer ou que les deux joueurs aient joué, puis résout le tour."""
    import asyncio

    while True:
        await asyncio.sleep(5)

        combat = database.obtenir_combat(combat_id)
        if not combat or not combat["actif"]:
            return

        # Un joueur en pleine charge/recharge (attaque à deux tours) n'a rien à choisir ce
        # tour-ci — son action reste NULL à raison, mais ça ne doit pas forcer à attendre le
        # timer complet si l'adversaire, lui, a déjà joué.
        charge1 = database.obtenir_charge(combat_id, combat["joueur1_id"], combat["actif1_nom"])
        charge2 = database.obtenir_charge(combat_id, combat["joueur2_id"], combat["actif2_nom"])
        j1_verrouille = bool(charge1["attaque_en_charge"]) or charge1["doit_recharger"]
        j2_verrouille = bool(charge2["attaque_en_charge"]) or charge2["doit_recharger"]

        action1_prete = combat["action1"] is not None or j1_verrouille
        action2_prete = combat["action2"] is not None or j2_verrouille
        deux_joueurs_prets = action1_prete and action2_prete
        timer_expire = int(time.time()) >= combat["date_limite_tour"]

        if not deux_joueurs_prets and not timer_expire:
            continue

        # Résoudre le tour
        log = await resoudre_tour(combat_id)
        vainqueur_id = verifier_fin_combat(combat_id)

        thread = bot.get_channel(int(thread_id))
        if thread is None:
            database.terminer_combat_pvp(combat_id)
            return

        if vainqueur_id is not None:
            database.terminer_combat_pvp(combat_id)
            perdant_id = combat["joueur2_id"] if vainqueur_id == combat["joueur1_id"] else combat["joueur1_id"]
            mult_repetition = database.enregistrer_victoire_pvp_repetition(vainqueur_id, perdant_id)
            database.ajouter_poke_dollars(vainqueur_id, round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent")))
            quetes_completees = database.incrementer_progression_quete(vainqueur_id, "pvp_victoire")
            database.incrementer_victoires_pvp(vainqueur_id)
            leveling.gagner_xp(vainqueur_id, round(XP_VICTOIRE * mult_repetition))
            leveling.gagner_xp(perdant_id, XP_DEFAITE)

            vainqueur = bot.get_user(vainqueur_id)
            nom_vainqueur = vainqueur.display_name if vainqueur else f"<@{vainqueur_id}>"
            dollars_reels = round(DOLLARS_VICTOIRE * mult_repetition * database.multiplicateur_boost(vainqueur_id, "argent"))
            # XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp() applique
            # son propre multiplicateur en interne, on le reproduit ici pour le texte affiché.
            xp_reels = round(round(XP_VICTOIRE * mult_repetition) * database.multiplicateur_boost(vainqueur_id, "xp"))
            texte_recompense = f"\n\n🎖️ +{dollars_reels} Poké Dollars & +{xp_reels} XP au vainqueur !"
            if mult_repetition < 1.0:
                texte_recompense += "\n*(récompense réduite : déjà battu cet adversaire aujourd'hui)*"
            embed = discord.Embed(
                title=f"🏆 {nom_vainqueur} remporte le combat !",
                description=(
                    "\n".join(log)
                    + texte_recompense
                    + quetes_ui.texte_notifications_completion(quetes_completees)
                ),
                color=discord.Color.gold(),
            )
            try:
                msg = await thread.fetch_message(message_id)
                await msg.edit(embed=embed, view=None)
            except discord.NotFound:
                await thread.send(embed=embed)
            try:
                await thread.send(f"🗑️ Ce fil sera supprimé automatiquement dans {DELAI_SUPPRESSION_FIL // 60} minutes.")
            except Exception:
                pass
            bot.loop.create_task(supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))
            return

        # Passer au tour suivant
        nouvelle_limite = int(time.time()) + duree
        database.passer_tour_pvp(combat_id, nouvelle_limite)
        combat = database.obtenir_combat(combat_id)
        nouveau_tour = combat["tour"]
        j1 = combat["joueur1_id"]
        j2 = combat["joueur2_id"]

        noms = {
            j1: (bot.get_user(j1).display_name if bot.get_user(j1) else f"Joueur {str(j1)[-4:]}"),
            j2: (bot.get_user(j2).display_name if bot.get_user(j2) else f"Joueur {str(j2)[-4:]}"),
        }
        embeds = construire_embeds_combat(combat_id, log_tour=log, noms=noms)
        vue = VueActionCombat(combat_id, nouveau_tour)
        try:
            msg = await thread.fetch_message(message_id)
            await msg.edit(embeds=embeds, view=vue)
        except discord.NotFound:
            pass


# ----------------------------------------------------------------------------
# Vue d'action (boutons de chaque joueur)
# ----------------------------------------------------------------------------

class VueActionCombat(discord.ui.View):
    """Panneau d'action PARTAGÉ, affiché dans le fil sous les embeds du combat.
    Chaque joueur clique sur le même panneau ; les vérifications se font en base :
    seul un des deux combattants peut agir, une seule fois par tour."""

    def __init__(self, combat_id: int, tour: int):
        super().__init__(timeout=None)  # le message est édité à chaque tour, pas de timeout
        self.combat_id = combat_id
        self.tour = tour

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est terminé.", ephemeral=True)
            return False
        if combat["tour"] != self.tour:
            await interaction.response.send_message("⌛ Ce tour est déjà résolu.", ephemeral=True)
            return False
        if interaction.user.id not in (combat["joueur1_id"], combat["joueur2_id"]):
            await interaction.response.send_message("Tu n'es pas un des combattants !", ephemeral=True)
            return False
        deja_joue = (
            combat["action1"] is not None
            if interaction.user.id == combat["joueur1_id"]
            else combat["action2"] is not None
        )
        if deja_joue:
            await interaction.response.send_message("Tu as déjà choisi ton action pour ce tour !", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Attaquer", style=discord.ButtonStyle.danger, emoji="⚔️", row=0)
    async def attaquer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        combat = database.obtenir_combat(self.combat_id)
        actif_nom = combat["actif1_nom"] if combat["joueur1_id"] == interaction.user.id else combat["actif2_nom"]
        equipees = database.obtenir_attaques_equipees(interaction.user.id, actif_nom)

        if not equipees:
            # Aucune attaque équipée : Charge par défaut, directement (illimitée, hors système de PP)
            database.enregistrer_action_pvp(self.combat_id, interaction.user.id, f"attaque:{ATTAQUE_DEFAUT_NOM}")
            await interaction.response.send_message(
                f"⚔️ **{actif_nom}** utilisera **{ATTAQUE_DEFAUT_NOM}** (aucune attaque équipée — "
                f"va voir le Maître des Types !)",
                ephemeral=True,
            )
            return

        # Ne proposer que les attaques ayant encore des PP
        equipees_avec_pp = {}
        for slot, nom in equipees.items():
            pp_max = pp_max_attaque(obtenir_attaque(nom))
            pp_restant = database.obtenir_pp(self.combat_id, interaction.user.id, actif_nom, nom, pp_max)
            if pp_restant > 0:
                equipees_avec_pp[slot] = nom

        if not equipees_avec_pp:
            # Toutes les attaques équipées sont à 0 PP : Lutte automatique, comme dans les vrais jeux
            database.enregistrer_action_pvp(self.combat_id, interaction.user.id, f"attaque:{NOM_LUTTE}")
            await interaction.response.send_message(
                f"💥 **{actif_nom}** n'a plus de PP pour aucune de ses attaques — il utilisera **Lutte** "
                f"(contrecoup de {round(LUTTE_RECOIL_POURCENT * 100)}% de ses PV max) !",
                ephemeral=True,
            )
            return

        vue = VueChoixAttaque(self.combat_id, interaction.user.id, actif_nom, equipees_avec_pp)
        await interaction.response.send_message("Quelle attaque utiliser ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Potion", style=discord.ButtonStyle.success, emoji="💊", row=0)
    async def potion(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        from pokemon_data import NOM_SOIN_AFFICHAGE
        inventaire = database.obtenir_inventaire_balls(interaction.user.id)
        potions_dispo = {k: v for k, v in inventaire.items() if k in NOM_SOIN_AFFICHAGE and v > 0}

        # Limite de potions de SOIN (PV) par combat — Total Soin n'est jamais concerné.
        limite_atteinte = (
            database.compter_potions_soin_utilisees(self.combat_id, interaction.user.id)
            >= config.LIMITE_POTIONS_SOIN_COMBAT
        )
        if limite_atteinte:
            potions_dispo = {k: v for k, v in potions_dispo.items() if k == "totalsoin"}

        if not potions_dispo:
            message = (
                f"Tu as déjà utilisé tes {config.LIMITE_POTIONS_SOIN_COMBAT} potions de soin "
                "pour ce combat !" if limite_atteinte else "Tu n'as plus aucune potion !"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        vue = VueChoixPotion(self.combat_id, interaction.user.id, potions_dispo)
        await interaction.response.send_message("Quel objet de soin utiliser ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Changer", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def changer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        combat = database.obtenir_combat(self.combat_id)
        actif_nom = combat["actif1_nom"] if combat["joueur1_id"] == interaction.user.id else combat["actif2_nom"]
        equipe = database.obtenir_equipe_pvp(self.combat_id, interaction.user.id)
        vivants = [r for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != actif_nom]
        if not vivants:
            await interaction.response.send_message("Tu n'as plus d'autres Pokémon vivants !", ephemeral=True)
            return
        vue = VueChoixChangement(self.combat_id, interaction.user.id, vivants)
        await interaction.response.send_message("Quel Pokémon envoyer ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Abandonner", style=discord.ButtonStyle.secondary, emoji="🏳️", row=1)
    async def abandonner(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est déjà terminé.", ephemeral=True)
            return
        if interaction.user.id not in (combat["joueur1_id"], combat["joueur2_id"]):
            await interaction.response.send_message("Tu n'es pas un des combattants !", ephemeral=True)
            return
        await interaction.response.send_message("🏳️ Tu as abandonné. Défaite enregistrée.", ephemeral=True)
        await resoudre_abandon(interaction.client, self.combat_id, interaction.user.id)


class VueChoixPotion(discord.ui.View):
    """Sous-menu éphémère : choisir quelle potion utiliser ce tour."""

    def __init__(self, combat_id: int, user_id: int, potions: dict):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id
        from pokemon_data import EMOJI_SOINS, NOM_SOIN_AFFICHAGE
        for type_potion, quantite in potions.items():
            bouton = discord.ui.Button(
                label=f"{NOM_SOIN_AFFICHAGE[type_potion]} (x{quantite})",
                emoji=EMOJI_SOINS.get(type_potion),
                style=discord.ButtonStyle.success,
            )
            bouton.callback = self._creer_callback(type_potion)
            self.add_item(bouton)

    def _creer_callback(self, type_potion: str):
        async def callback(interaction: discord.Interaction):
            combat = database.obtenir_combat(self.combat_id)
            deja_joue = (
                combat["action1"] is not None
                if interaction.user.id == combat["joueur1_id"]
                else combat["action2"] is not None
            )
            if deja_joue:
                await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
                return
            if type_potion != "totalsoin" and (
                database.compter_potions_soin_utilisees(self.combat_id, self.user_id)
                >= config.LIMITE_POTIONS_SOIN_COMBAT
            ):
                await interaction.response.edit_message(
                    content=f"Tu as déjà utilisé tes {config.LIMITE_POTIONS_SOIN_COMBAT} potions de soin pour ce combat !",
                    view=None,
                )
                return
            if not database.retirer_ball(self.user_id, type_potion):
                await interaction.response.edit_message(content="Tu n'as plus cette potion !", view=None)
                return
            database.enregistrer_action_pvp(self.combat_id, self.user_id, f"potion:{type_potion}")
            if type_potion != "totalsoin":
                database.incrementer_potions_soin_utilisees(self.combat_id, self.user_id)
            await interaction.response.edit_message(content="💊 Action enregistrée : potion !", view=None)
        return callback


class VueChoixChangement(discord.ui.View):
    """Sous-menu éphémère : choisir quel Pokémon envoyer ce tour."""

    def __init__(self, combat_id: int, user_id: int, vivants: list):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id
        options = [
            discord.SelectOption(
                label=f"{r['pokemon_nom']} ({r['pv_actuels']}/{r['pv_max']} PV)",
                value=r["pokemon_nom"],
            )
            for r in vivants[:25]
        ]
        select = discord.ui.Select(placeholder="Choisir un Pokémon...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        combat = database.obtenir_combat(self.combat_id)
        deja_joue = (
            combat["action1"] is not None
            if interaction.user.id == combat["joueur1_id"]
            else combat["action2"] is not None
        )
        if deja_joue:
            await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
            return
        nom = interaction.data["values"][0]
        database.enregistrer_action_pvp(self.combat_id, self.user_id, f"changer:{nom}")
        await interaction.response.edit_message(content=f"🔄 Action enregistrée : envoi de **{nom}** !", view=None)


class VueChoixAttaque(discord.ui.View):
    """Sous-menu éphémère : choisir laquelle des attaques équipées (avec PP restant) utiliser ce tour."""

    def __init__(self, combat_id: int, user_id: int, pokemon_nom: str, equipees: dict):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id

        options = []
        for slot in sorted(equipees):
            nom = equipees[slot]
            attaque = obtenir_attaque(nom)
            emoji = EMOJI_TYPES.get(attaque["type"], "⚔️")
            pp_max = pp_max_attaque(attaque)
            pp_restant = database.obtenir_pp(combat_id, user_id, pokemon_nom, nom, pp_max)
            if attaque.get("puissance"):
                desc = f"{attaque['puissance']} pcs — préc. {attaque.get('precision') or '∞'}% — {pp_restant}/{pp_max} PP"
            else:
                morceaux = [f"{'+' if d > 0 else ''}{d} {s.upper()}" for s, d in attaque.get("stats", [])]
                base = ", ".join(morceaux) if morceaux else "Attaque de statut"
                desc = f"{base} — {pp_restant}/{pp_max} PP"
            options.append(
                discord.SelectOption(label=nom[:100], description=desc[:100], value=nom, emoji=emoji)
            )

        select = discord.ui.Select(placeholder="Choisis ton attaque...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.edit_message(content="Ce combat est terminé.", view=None)
            return
        deja_joue = (
            combat["action1"] is not None
            if interaction.user.id == combat["joueur1_id"]
            else combat["action2"] is not None
        )
        if deja_joue:
            await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
            return
        nom = interaction.data["values"][0]
        database.enregistrer_action_pvp(self.combat_id, self.user_id, f"attaque:{nom}")
        await interaction.response.edit_message(content=f"⚔️ Action enregistrée : **{nom}** !", view=None)
