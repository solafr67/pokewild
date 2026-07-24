"""Combat PvP 2v2 — deux équipes de deux joueurs, un Pokémon actif par joueur (4 sur le
terrain), comme les combats duo des jeux officiels.

Architecture : le combat est ANCRÉ dans une ligne combat_pvp classique (les deux
"capitaines" y figurent) — ça garantit un combat_id unique partagé avec toutes les tables
annexes du moteur 1v1 (combat_equipe, combat_pp, combat_boosts, combat_statuts,
combat_charge, combat_terrain, combat_choix_ko), déjà indexées par (combat_id, user_id,
pokemon_nom) et donc réutilisées TELLES QUELLES. Le nettoyage au redémarrage (forfait +
message dans le fil) et le verrou "déjà en combat" fonctionnent aussi automatiquement.
Les 4 joueurs (camp, actif, action du tour) vivent dans combat_2v2_joueurs.

Les dresseurs 2v2 (PvE) pourront se brancher directement : un "joueur" à user_id négatif
est traité comme l'IA des combats dresseur actuels (pas de choix K.O. interactif, envoi
automatique).
"""

import asyncio
import random
import time

import discord

import config
import database
import journal
import leveling
import dresseurs as dresseurs_module
from combat import (
    ATTAQUE_LUTTE,
    CHANCE_CONFUSION_SKIP,
    CHANCE_DEGEL,
    CHANCE_PARALYSIE_SKIP,
    DEGATS_BRULURE_POURCENT,
    DEGATS_POISON_POURCENT,
    DELAI_SUPPRESSION_FIL,
    DOLLARS_VICTOIRE,
    LUTTE_RECOIL_POURCENT,
    NOM_LUTTE,
    STATUTS_INFO,
    XP_DEFAITE,
    XP_VICTOIRE,
    _appliquer_hazards_entree,
    _barre_pv,
    _bloc_reserve,
    _texte_efficacite,
    preparer_equipe_pour_combat,
    stats_combattant_reel,
    supprimer_fil_apres_delai,
)
from pokemon_data import (
    ATTAQUES_CHARGE,
    ATTAQUES_RECHARGE,
    ATTAQUES_TERRAIN,
    EMOJI_SOINS,
    EMOJI_TYPES,
    NOM_SOIN_AFFICHAGE,
    calculer_multiplicateur_type,
    obtenir_attaque,
    obtenir_pokemon_par_nom,
    pp_max_attaque,
)

TAILLE_EQUIPE_2V2 = 3  # Pokémon par joueur (validé : combats plus courts que le 1v1)
DUREE_TOUR_2V2 = 45  # secondes avant résolution automatique du tour
DUREE_LOBBY_2V2 = 180  # secondes pour remplir le lobby avant annulation

# --- Double combat (dresseurs DUO, PvE) -------------------------------------------------
# Un combat 2v2 a toujours 4 "sièges" (identités qui possèdent chacune un actif + une
# équipe stockée normalement). Pour un double combat 1 joueur humain vs 2 dresseurs IA :
#   - le joueur occupe 2 sièges : son propre ID Discord (son équipe, 1ère moitié) + un
#     "ID délégué" dérivé (2e moitié de son équipe) — un identifiant synthétique très
#     élevé (toujours positif, donc traité comme "humain" par tout le moteur : choix K.O.
#     interactif, etc.) qui n'existe dans aucune autre table que celles de ce combat.
#   - les 2 dresseurs IA occupent chacun un siège à ID négatif classique (même convention
#     que les dresseurs 1v1 : database.combat_en_cours_pour_joueur ne les concerne jamais).
# Aucune autre partie du moteur (resoudre_tour_2v2, ciblage, hazards, choix K.O...) n'a
# besoin de savoir qu'un siège est délégué : chaque siège a sa PROPRE équipe stockée
# séparément (la moitié du joueur splittée en 2, pas une équipe partagée) — le seul
# endroit qui doit "voir à travers" le délégué est l'interface (savoir qui a le droit de
# cliquer pour ce siège) et l'affichage (mentions Discord, récompenses).
DELEGUE_OFFSET = 2_000_000_000_000_000_000  # loin au-dessus de tout ID Discord réel (~10^18)


def id_delegue(id_reel: int) -> int:
    """ID du 2e siège d'un joueur humain en double combat, dérivé de son vrai ID."""
    return id_reel + DELEGUE_OFFSET


def est_delegue(siege_id: int) -> bool:
    return siege_id >= DELEGUE_OFFSET


def controleur_reel(siege_id: int) -> int:
    """L'ID Discord qui a le droit d'agir pour ce siège (lui-même si ce n'est pas un
    délégué). Ne rien renvoyer de sensé pour un siège IA (négatif) — jamais appelé pour ça."""
    return siege_id - DELEGUE_OFFSET if est_delegue(siege_id) else siege_id


# Attaques à deux tours (charge type Lance-Soleil, recharge type Ultralaser) : gérées
# comme en 1v1, avec une subtilité 2v2 — la CIBLE est choisie et mémorisée au tour de
# charge (colonne cible_user_id de combat_charge), puis relâchée dessus au tour suivant,
# avec la redirection habituelle si elle est tombée entre-temps.

NOMS_STATS = {"atk": "Attaque", "def": "Défense", "atk_spe": "Attaque Spé", "def_spe": "Défense Spé", "vit": "Vitesse"}


def _mult_stage(stage: int) -> float:
    """Multiplicateur officiel Pokémon pour un stage de stat (-6..+6)."""
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


def _mapping_mentions(joueurs: list, noms_ia: dict) -> dict:
    """siege_id -> texte de remplacement pour les mentions <@id> illisibles/invalides du
    log de combat : un délégué doit pointer vers le vrai joueur (mention valide), une IA
    négative n'a pas d'ID Discord valide donc devient un nom en gras."""
    mapping = {}
    for j in joueurs:
        uid = j["user_id"]
        if est_delegue(uid):
            mapping[uid] = f"<@{controleur_reel(uid)}>"
        elif uid < 0:
            mapping[uid] = f"**{noms_ia.get(uid, 'Adversaire')}**"
    return mapping


def _nettoyer_log_2v2(log: list, joueurs: list, noms_ia: dict) -> list:
    mapping = _mapping_mentions(joueurs, noms_ia)
    if not mapping:
        return log
    resultat = []
    for ligne in log:
        for uid, remplacement in mapping.items():
            ligne = ligne.replace(f"<@{uid}>", remplacement)
        resultat.append(ligne)
    return resultat


async def _jouer_tour_ia_2v2(combat_id: int, ia_user_id: int, joueurs: list):
    """Choisit une attaque ET une cible pour un siège IA — même philosophie que
    dresseurs._jouer_tour_ia (priorité aux attaques offensives, reste simple), étendue au
    ciblage 2v2 (cible tirée au hasard parmi les actifs adverses vivants). Sans effet si
    l'IA a déjà une action, ou n'a pas d'actif (K.O., équipe à plat)."""
    j = next((x for x in joueurs if x["user_id"] == ia_user_id), None)
    if j is None or j["action"] is not None or not j["actif_nom"]:
        return
    row = _row_actif(combat_id, ia_user_id, j["actif_nom"])
    if row is None or row["pv_actuels"] <= 0:
        return

    equipe_adverse = 2 if j["equipe"] == 1 else 1
    cibles = _cibles_vivantes(combat_id, joueurs, equipe_adverse)
    if not cibles:
        return
    cible_id = random.choice(cibles)[0]

    equipees = database.obtenir_attaques_equipees(ia_user_id, j["actif_nom"])
    offensives, statuts = [], []
    for nom in equipees.values():
        attaque = obtenir_attaque(nom)
        if not attaque:
            continue
        pp_max = pp_max_attaque(attaque)
        if database.obtenir_pp(combat_id, ia_user_id, j["actif_nom"], nom, pp_max) <= 0:
            continue
        (offensives if (attaque.get("puissance") or 0) > 0 else statuts).append(nom)

    if offensives and (not statuts or random.random() < 0.8):
        choix = random.choice(offensives)
    elif statuts:
        choix = random.choice(statuts)
    elif offensives:
        choix = random.choice(offensives)
    else:
        choix = NOM_LUTTE  # plus aucun PP nulle part : Lutte de secours

    database.definir_action_2v2(combat_id, ia_user_id, f"attaque:{choix}@{cible_id}")


# ----------------------------------------------------------------------------
# État du combat
# ----------------------------------------------------------------------------

def _joueurs(combat_id: int) -> list:
    return database.obtenir_joueurs_2v2(combat_id)


def _row_actif(combat_id: int, user_id: int, actif_nom: str):
    if not actif_nom:
        return None
    eq = database.obtenir_equipe_pvp(combat_id, user_id)
    return next((r for r in eq if r["pokemon_nom"] == actif_nom), None)


def _joueur_hors_combat(combat_id: int, jrow) -> bool:
    """Un joueur est hors combat s'il a abandonné, ou si toute son équipe est K.O."""
    if jrow["abandonne"]:
        return True
    eq = database.obtenir_equipe_pvp(combat_id, jrow["user_id"])
    return all(r["pv_actuels"] <= 0 for r in eq)


def _cibles_vivantes(combat_id: int, joueurs: list, equipe_adverse: int) -> list:
    """Actifs adverses encore ciblables : [(user_id, actif_nom, row_equipe)]."""
    cibles = []
    for j in joueurs:
        if j["equipe"] != equipe_adverse or j["abandonne"]:
            continue
        row = _row_actif(combat_id, j["user_id"], j["actif_nom"])
        if row is not None and row["pv_actuels"] > 0:
            cibles.append((j["user_id"], j["actif_nom"], row))
    return cibles


def _equipe_vaincue(combat_id: int, joueurs: list, equipe: int) -> bool:
    return all(_joueur_hors_combat(combat_id, j) for j in joueurs if j["equipe"] == equipe)


def _equipe_entierement_ko(combat_id: int, joueurs: list, equipe: int) -> bool:
    """True si TOUS les Pokémon de l'équipe sont K.O. (victoire "réelle", par opposition
    à une victoire obtenue uniquement par abandons — qui ne compte pas pour les quêtes)."""
    for j in joueurs:
        if j["equipe"] != equipe:
            continue
        eq = database.obtenir_equipe_pvp(combat_id, j["user_id"])
        if any(r["pv_actuels"] > 0 for r in eq):
            return False
    return True


# ----------------------------------------------------------------------------
# Embeds
# ----------------------------------------------------------------------------

def construire_embeds_2v2(combat_id: int, noms: dict, log_tour: list = None) -> list:
    combat = database.obtenir_combat(combat_id)
    joueurs = _joueurs(combat_id)
    if combat is None or not joueurs:
        return [discord.Embed(description="Combat introuvable.", color=discord.Color.red())]

    embeds = []
    for equipe, couleur in ((1, discord.Color.blue()), (2, discord.Color.red())):
        embed = discord.Embed(title=f"{'🔵' if equipe == 1 else '🔴'} Équipe {equipe}", color=couleur)
        for j in [x for x in joueurs if x["equipe"] == equipe]:
            nom_joueur = noms.get(j["user_id"], f"Joueur…{str(j['user_id'])[-4:]}")
            if j["abandonne"]:
                embed.add_field(name=f"🏳️ {nom_joueur}", value="*A abandonné*", inline=True)
                continue
            eq = database.obtenir_equipe_pvp(combat_id, j["user_id"])
            row = _row_actif(combat_id, j["user_id"], j["actif_nom"])
            statut_txt = "✅ prêt" if j["action"] else "⏳ choisit..."
            if row is None or all(r["pv_actuels"] <= 0 for r in eq):
                embed.add_field(name=f"💀 {nom_joueur}", value="*Équipe entière K.O.*", inline=True)
                continue
            statut_actif = database.obtenir_statut(combat_id, j["user_id"], j["actif_nom"])
            emoji_statut = (
                f" {STATUTS_INFO[statut_actif[0]]['emoji']}"
                if statut_actif and statut_actif[0] in STATUTS_INFO
                else ""
            )
            valeur = (
                f"**{j['actif_nom']}**{emoji_statut}\n"
                f"{_barre_pv(row['pv_actuels'], row['pv_max'], longueur=8)}\n"
                f"❤️ {row['pv_actuels']}/{row['pv_max']} PV\n"
                f"{_bloc_reserve(eq, j['actif_nom'])}"
            )
            embed.add_field(name=f"{nom_joueur} — {statut_txt}", value=valeur[:1024], inline=True)
        embeds.append(embed)

    dernier = discord.Embed(color=discord.Color.dark_grey())
    dernier.set_author(name=f"⚔️ Tour {combat['tour']} — 2v2")
    if log_tour:
        texte_log = "\n".join(log_tour)
        if len(texte_log) > 4000:
            texte_log = texte_log[:4000] + "\n… *(log du tour tronqué)*"
        dernier.description = texte_log
    temps_restant = max(0, combat["date_limite_tour"] - int(time.time()))
    dernier.set_footer(text=f"Tour résolu quand tout le monde a joué, ou dans ~{temps_restant}s")
    embeds.append(dernier)
    return embeds


# ----------------------------------------------------------------------------
# Résolution d'un tour (miroir fidèle du moteur 1v1, généralisé à 4 acteurs + ciblage)
# ----------------------------------------------------------------------------

async def resoudre_tour_2v2(combat_id: int) -> list:
    log = []
    joueurs = _joueurs(combat_id)
    actions = {j["user_id"]: (j["action"] or "") for j in joueurs}
    equipes = {j["user_id"]: j["equipe"] for j in joueurs}

    def infos_actif(user_id: int):
        j = next((x for x in _joueurs(combat_id) if x["user_id"] == user_id), None)
        if j is None or not j["actif_nom"]:
            return None, None
        return j["actif_nom"], _row_actif(combat_id, user_id, j["actif_nom"])

    # --- Phase 1 : changements de Pokémon ---
    for j in joueurs:
        action = actions[j["user_id"]]
        if action.startswith("changer:"):
            ancien_nom, _row = infos_actif(j["user_id"])
            nouveau = action.split(":", 1)[1]
            database.reinitialiser_boosts(combat_id, j["user_id"], ancien_nom)
            database.reinitialiser_charge(combat_id, j["user_id"], ancien_nom)
            database.definir_actif_2v2(combat_id, j["user_id"], nouveau)
            log.append(f"<@{j['user_id']}> rappelle **{ancien_nom}** et envoie **{nouveau}** !")
            _appliquer_hazards_entree(combat_id, j["user_id"], nouveau, log)

    # --- Phase 2 : potions ---
    for j in joueurs:
        action = actions[j["user_id"]]
        if action.startswith("potion:"):
            type_potion = action.split(":", 1)[1]
            nom, row = infos_actif(j["user_id"])
            if row is None or row["pv_actuels"] <= 0:
                continue
            if type_potion == "totalsoin":
                statut = database.obtenir_statut(combat_id, j["user_id"], nom)
                if statut:
                    database.retirer_statut(combat_id, j["user_id"], nom)
                    log.append(f"<@{j['user_id']}> : **{nom}** utilise 🌿 Total Soin — statut guéri !")
                else:
                    log.append(f"<@{j['user_id']}> : **{nom}** utilise 🌿 Total Soin, mais n'avait aucun problème de statut.")
                continue
            delta = max(1, round(row["pv_max"] * config.SOIN_POURCENT.get(type_potion, 0.3)))
            pv_apres = database.soigner_pvp(combat_id, j["user_id"], nom, delta)
            log.append(f"<@{j['user_id']}> : **{nom}** est soigné → {pv_apres}/{row['pv_max']} PV")

    # --- Phase 3 : attaques, ordonnées par vitesse (les 4 actifs confondus) ---
    attaquants = []
    for j in joueurs:
        action = actions[j["user_id"]]
        nom, row = infos_actif(j["user_id"])
        if row is None or row["pv_actuels"] <= 0:
            continue
        # Un Pokémon en pleine charge (ou qui doit récupérer) agit d'office ce tour,
        # même si son joueur n'a rien enregistré — comme en 1v1.
        charge_en_cours = database.obtenir_charge(combat_id, j["user_id"], nom)
        if not action.startswith("attaque:") and not (
            charge_en_cours["attaque_en_charge"] or charge_en_cours["doit_recharger"]
        ):
            continue
        boosts = database.obtenir_boosts(combat_id, j["user_id"], nom)
        vitesse = row["vit"] * _mult_stage(boosts["vit"])
        statut_actuel = database.obtenir_statut(combat_id, j["user_id"], nom)
        if statut_actuel and statut_actuel[0] == "paralysis":
            vitesse /= 2
        # action = "attaque:Nom@cible_user_id" — ou vide si l'acteur n'agit que par sa
        # charge/recharge en cours (le nom réel sera résolu au moment de son tour).
        if action.startswith("attaque:"):
            reste = action.split(":", 1)[1]
            if "@" in reste:
                nom_attaque, cible_str = reste.rsplit("@", 1)
                try:
                    cible_voulue = int(cible_str)
                except ValueError:
                    cible_voulue = None
            else:
                nom_attaque, cible_voulue = reste, None
        else:
            nom_attaque, cible_voulue = None, None
        attaquants.append((vitesse + random.random(), j["user_id"], nom_attaque, cible_voulue))

    attaquants.sort(reverse=True)

    for _, user_id, nom_attaque, cible_voulue in attaquants:
        nom_atk, row_atk = infos_actif(user_id)
        if row_atk is None or row_atk["pv_actuels"] <= 0:
            log.append(f"💫 **{nom_atk}** est K.O. et ne peut pas attaquer !")
            continue

        # --- Le statut de l'attaquant peut l'empêcher d'agir (identique au 1v1) ---
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

        # --- Charge / recharge (attaques à deux tours, identique au 1v1) ---
        charge_info = database.obtenir_charge(combat_id, user_id, nom_atk)
        if charge_info["doit_recharger"]:
            database.definir_charge(combat_id, user_id, nom_atk, None, False)
            log.append(f"<@{user_id}> : **{nom_atk}** doit récupérer et ne peut pas attaquer ce tour-ci !")
            continue

        liberation_charge = False
        if charge_info["attaque_en_charge"]:
            # L'attaque et la CIBLE mémorisées au tour de charge s'imposent — l'action
            # éventuellement enregistrée ce tour est ignorée, comme dans les vrais jeux.
            nom_attaque = charge_info["attaque_en_charge"]
            cible_voulue = charge_info["cible_user_id"]
            liberation_charge = True
            database.definir_charge(combat_id, user_id, nom_atk, None, False)

        if nom_attaque is None:
            continue  # pas d'action ce tour et ni charge ni recharge : rien à faire

        if nom_attaque == NOM_LUTTE:
            attaque = ATTAQUE_LUTTE
            pp_restant, pp_max = None, None
        else:
            attaque = obtenir_attaque(nom_attaque)
            pp_max = pp_max_attaque(attaque)
            if liberation_charge:
                # Le PP a déjà été consommé au tour de charge — simple lecture ici.
                pp_restant = database.obtenir_pp(combat_id, user_id, nom_atk, nom_attaque, pp_max)
            else:
                pp_restant = database.consommer_pp(combat_id, user_id, nom_atk, nom_attaque, pp_max)
        emoji_type = EMOJI_TYPES.get(attaque["type"], "⚔️")

        # Tour de charge : on mémorise l'attaque ET la cible visée, rien d'autre ne se
        # passe ce tour-ci (la libération aura lieu au tour suivant).
        if not liberation_charge and nom_attaque in ATTAQUES_CHARGE:
            database.definir_charge(combat_id, user_id, nom_atk, nom_attaque, False, cible_user_id=cible_voulue)
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** "
                f"— commence à charger son énergie !"
            )
            continue

        # --- Choix / redirection de la cible : si la cible voulue est tombée plus tôt
        # dans le tour (ou a abandonné), l'attaque est redirigée vers l'autre actif
        # adverse — comme dans les vrais jeux, jamais perdue dans le vide.
        joueurs_maj = _joueurs(combat_id)
        equipe_adverse = 2 if equipes[user_id] == 1 else 1
        cibles = _cibles_vivantes(combat_id, joueurs_maj, equipe_adverse)
        if not cibles:
            continue  # plus personne en face : la fin de combat sera constatée après
        cible = next((c for c in cibles if c[0] == cible_voulue), None)
        redirigee = cible is None and cible_voulue is not None
        if cible is None:
            cible = cibles[0]
        adversaire_id, nom_def, row_def = cible
        note_redirection = " *(cible K.O. — redirigée !)*" if redirigee else ""

        if liberation_charge:
            log.append(f"<@{user_id}> : **{nom_atk}** relâche toute son énergie chargée !")

        # Test de précision
        precision = attaque.get("precision")
        if precision is not None and random.random() * 100 > precision:
            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}**... mais rate !")
            continue

        if attaque.get("puissance"):
            # --- Attaque offensive (formule identique au 1v1) ---
            pok_atk = obtenir_pokemon_par_nom(nom_atk)
            pok_def = obtenir_pokemon_par_nom(nom_def)
            types_atk_pokemon = pok_atk["types"] if pok_atk else ["normal"]
            types_def = pok_def["types"] if pok_def else ["normal"]

            if attaque["type"] is None:
                multi_type, stab = 1.0, 1.0
            else:
                multi_type = calculer_multiplicateur_type([attaque["type"]], types_def)
                stab = 1.5 if attaque["type"] in types_atk_pokemon else 1.0

            if multi_type == 0.0:
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}**...{note_redirection}")
                log.append("  🚫 Ça n'affecte pas " + nom_def + " !")
                continue

            boosts_atk = database.obtenir_boosts(combat_id, user_id, nom_atk)
            boosts_def = database.obtenir_boosts(combat_id, adversaire_id, nom_def)

            est_special = attaque.get("classe") == "special"
            stat_off = row_atk["atq_spe"] if est_special else row_atk["atq"]
            stat_def = row_def["def_spe"] if est_special else row_def["defe"]

            variance = random.uniform(0.85, 1.15)
            cle_boost_off = "atk_spe" if est_special else "atk"
            cle_boost_def = "def_spe" if est_special else "def"
            stat_def_boostee = max(1, stat_def / _mult_stage(boosts_def[cle_boost_def]))
            stat_off_boostee = max(1, stat_off * _mult_stage(boosts_atk[cle_boost_off]))
            bonus_badge = 1.0
            if user_id > 0 and database.possede_badge_arene(user_id, attaque["type"]):
                bonus_badge = 1.0 + config.ARENE_BONUS_DEGATS_PAR_BADGE

            degats = max(1, round(
                ((2 * row_atk["niveau"] / 5 + 2) * attaque["puissance"] * stat_off_boostee / stat_def_boostee / 50 + 2)
                * multi_type * stab * variance * bonus_badge
            ))

            pv_restants = database.appliquer_degats_pvp(combat_id, adversaire_id, nom_def, degats)
            pp_txt = "" if nom_attaque == NOM_LUTTE else f" ({pp_restant}/{pp_max} PP)"
            log.append(
                f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** sur **{nom_def}** → -{degats} PV{pp_txt}{note_redirection}"
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

            ailment = attaque.get("ailment")
            if ailment in STATUTS_INFO and pv_restants > 0:
                chance = attaque.get("ailment_chance", 0) or 100
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
            # --- Pièges de terrain : posés du côté des DEUX adversaires en 2v2 ---
            if nom_attaque in ATTAQUES_TERRAIN:
                effet = ATTAQUES_TERRAIN[nom_attaque]
                stacks_max = 3 if effet == "spikes" else 1
                for j_adv in [x for x in joueurs_maj if x["equipe"] == equipe_adverse]:
                    database.poser_hazard(combat_id, j_adv["user_id"], effet, stacks_max)
                log.append(
                    f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** — "
                    f"le piège est posé du côté adverse (les deux terrains) !"
                )
                continue

            # --- Attaque de statut ---
            changements = attaque.get("stats", [])
            ailment = attaque.get("ailment")
            if not changements and ailment not in STATUTS_INFO:
                log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** (sans effet notable)")
                continue

            log.append(f"<@{user_id}> : **{nom_atk}** utilise {emoji_type} **{nom_attaque}** !{note_redirection}")

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

    # --- Dégâts de fin de tour : brûlure et poison, sur les 4 actifs ---
    for j in _joueurs(combat_id):
        if j["abandonne"] or not j["actif_nom"]:
            continue
        row = _row_actif(combat_id, j["user_id"], j["actif_nom"])
        if row is None or row["pv_actuels"] <= 0:
            continue
        statut_actif = database.obtenir_statut(combat_id, j["user_id"], j["actif_nom"])
        if not statut_actif:
            continue
        code = statut_actif[0]
        if code in ("burn", "poison"):
            pourcent = DEGATS_BRULURE_POURCENT if code == "burn" else DEGATS_POISON_POURCENT
            degats_statut = max(1, round(row["pv_max"] * pourcent))
            pv_apres = database.appliquer_degats_pvp(combat_id, j["user_id"], j["actif_nom"], degats_statut)
            info = STATUTS_INFO[code]
            log.append(f"{info['emoji']} **{j['actif_nom']}** souffre de son statut ({info['nom']}) : -{degats_statut} PV")
            if pv_apres <= 0:
                log.append(f"  💀 **{j['actif_nom']}** est K.O. !")

    # --- K.O. et remplacements (choix du joueur, comme en 1v1) ---
    for j in _joueurs(combat_id):
        if j["abandonne"] or not j["actif_nom"]:
            continue
        row = _row_actif(combat_id, j["user_id"], j["actif_nom"])
        if row is None or row["pv_actuels"] > 0:
            continue
        database.reinitialiser_boosts(combat_id, j["user_id"], j["actif_nom"])
        eq = database.obtenir_equipe_pvp(combat_id, j["user_id"])
        vivants = [r["pokemon_nom"] for r in eq if r["pv_actuels"] > 0]
        if not vivants:
            continue  # ce joueur est hors combat, la fin d'équipe sera constatée après
        if j["user_id"] > 0 and len(vivants) >= 2:
            database.creer_choix_ko(combat_id, j["user_id"], int(time.time()) + config.CHOIX_KO_DUREE_SECONDES)
            log.append(
                f"  🔁 <@{j['user_id']}> — choisis ton prochain Pokémon avec le bouton "
                f"**Envoyer un Pokémon** ({config.CHOIX_KO_DUREE_SECONDES}s, sinon envoi automatique) !"
            )
        else:
            suivant = vivants[0]
            database.definir_actif_2v2(combat_id, j["user_id"], suivant)
            log.append(f"  → <@{j['user_id']}> envoie **{suivant}** !" if j["user_id"] > 0 else f"  → **{suivant}** entre en jeu !")
            _appliquer_hazards_entree(combat_id, j["user_id"], suivant, log)

    return log


async def traiter_choix_ko_2v2(combat_id: int, thread) -> bool:
    """Version 2v2 de combat.traiter_choix_ko : l'actif vit dans combat_2v2_joueurs.
    Retourne True s'il reste au moins un choix en attente (la résolution patiente)."""
    rows = database.obtenir_choix_ko(combat_id)
    if not rows:
        return False
    maintenant = int(time.time())
    reste = False
    for row in rows:
        if maintenant < row["date_limite"]:
            reste = True
            continue
        if not database.supprimer_choix_ko(combat_id, row["user_id"]):
            continue
        eq = database.obtenir_equipe_pvp(combat_id, row["user_id"])
        suivant = next((r["pokemon_nom"] for r in eq if r["pv_actuels"] > 0), None)
        if suivant is None:
            continue
        database.definir_actif_2v2(combat_id, row["user_id"], suivant)
        mini_log = [f"⏳ <@{row['user_id']}> n'a pas choisi à temps — **{suivant}** est envoyé automatiquement !"]
        _appliquer_hazards_entree(combat_id, row["user_id"], suivant, mini_log)
        if thread is not None:
            try:
                await thread.send("\n".join(mini_log))
            except discord.HTTPException:
                pass
    return reste


# ----------------------------------------------------------------------------
# Fin de combat
# ----------------------------------------------------------------------------

async def _annoncer_victoire(bot, combat_id: int, thread, joueurs: list, equipe_gagnante: int, noms: dict, par_abandon_uniquement: bool):
    # Les sièges IA (dresseurs duo, user_id < 0) ne touchent jamais de récompense, et un
    # joueur qui occupe 2 sièges (double combat, son 2e siège est un ID délégué — voir
    # est_delegue/controleur_reel) n'est payé qu'UNE fois, pas deux : on résout chaque
    # siège vers son contrôleur réel et on déduplique via un set.
    gagnants = sorted({
        controleur_reel(j["user_id"]) for j in joueurs
        if j["equipe"] == equipe_gagnante and (j["user_id"] > 0 or est_delegue(j["user_id"]))
    })
    perdants = sorted({
        controleur_reel(j["user_id"]) for j in joueurs
        if j["equipe"] != equipe_gagnante and (j["user_id"] > 0 or est_delegue(j["user_id"]))
    })

    lignes = []
    for uid in gagnants:
        # Anti-collusion : même mécanisme qu'en 1v1, appliqué aux deux adversaires
        # rencontrés — la réduction la plus forte des deux s'applique.
        mults = [database.enregistrer_victoire_pvp_repetition(uid, p) for p in perdants]
        mult = min(mults) if mults else 1.0
        dollars = round(DOLLARS_VICTOIRE * mult * database.multiplicateur_boost(uid, "argent"))
        database.ajouter_poke_dollars(uid, dollars)
        database.incrementer_victoires_pvp(uid)
        xp = round(XP_VICTOIRE * mult)
        leveling.gagner_xp(uid, xp)
        # La quête "gagner un combat PvP" ne compte que les victoires RÉELLES (équipe
        # adverse entièrement K.O.) — une victoire obtenue uniquement par abandons ne
        # progresse pas la quête (cohérent avec le 1v1 : anti-échange de victoires).
        if not par_abandon_uniquement:
            database.incrementer_progression_quete(uid, "pvp_victoire")
        note = " *(récompense réduite : adversaire déjà battu aujourd'hui)*" if mult < 1.0 else ""
        lignes.append(f"🏅 <@{uid}> : +{dollars} Poké Dollars & +{round(xp * database.multiplicateur_boost(uid, 'xp'))} XP{note}")
    for uid in perdants:
        leveling.gagner_xp(uid, XP_DEFAITE)

    noms_gagnants = " & ".join(dict.fromkeys(
        noms.get(j["user_id"], f"Joueur…{str(j['user_id'])[-4:]}")
        for j in joueurs if j["equipe"] == equipe_gagnante
    ))
    journal.logger(f"⚔️ 2v2 terminé — victoire de l'Équipe {equipe_gagnante} ({noms_gagnants}).")

    embed = discord.Embed(
        title=f"🏆 Victoire de l'Équipe {equipe_gagnante} !",
        description=(
            f"{'🔵' if equipe_gagnante == 1 else '🔴'} **{noms_gagnants}** remportent le combat 2v2 !\n\n"
            + "\n".join(lignes)
            + f"\n+{XP_DEFAITE} XP de consolation pour chaque adversaire."
        ),
        color=discord.Color.gold(),
    )
    if thread is not None:
        try:
            await thread.send(embed=embed)
            await thread.send(f"🗑️ Ce fil sera supprimé automatiquement dans {DELAI_SUPPRESSION_FIL // 60} minutes.")
            bot.loop.create_task(supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))
        except discord.HTTPException:
            pass


# ----------------------------------------------------------------------------
# Boucle de résolution (mêmes protections que le 1v1 : retentes + clôture de secours)
# ----------------------------------------------------------------------------

async def boucle_resolution_2v2(bot, combat_id: int, thread_id: int, message_id: int, noms: dict, noms_ia: dict = None):
    noms_ia = noms_ia or {}
    echecs_consecutifs = 0
    while True:
        await asyncio.sleep(5)
        try:
            fini = await _tick_resolution_2v2(bot, combat_id, thread_id, message_id, noms, noms_ia)
            if fini:
                return
            echecs_consecutifs = 0
            continue
        except Exception:
            import traceback

            echecs_consecutifs += 1
            print(f"⚠️ Erreur au tick de résolution du combat 2v2 {combat_id} (tentative {echecs_consecutifs}/3) :")
            traceback.print_exc()
            if echecs_consecutifs == 1:
                journal.logger(f"🔴 Erreur dans la résolution du combat 2v2 {combat_id} — nouvelle tentative au prochain tick.")
            if echecs_consecutifs >= 3:
                database.terminer_combat_pvp(combat_id)
                journal.logger(
                    f"🔴 Combat 2v2 {combat_id} clôturé de force après 3 erreurs consécutives — "
                    f"les joueurs ne sont plus bloqués (aucune récompense distribuée)."
                )
                try:
                    thread = bot.get_channel(int(thread_id)) or await bot.fetch_channel(int(thread_id))
                    if thread is not None:
                        await thread.send(
                            "⚠️ Une erreur répétée a interrompu ce combat 2v2. Il a été annulé "
                            "(ni victoire ni défaite), vous pouvez en relancer un."
                        )
                        bot.loop.create_task(supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))
                except Exception:
                    pass
                return


async def _tick_resolution_2v2(bot, combat_id: int, thread_id: int, message_id: int, noms: dict, noms_ia: dict = None) -> bool:
    noms_ia = noms_ia or {}
    combat = database.obtenir_combat(combat_id)
    if not combat or not combat["actif"]:
        return True

    thread = bot.get_channel(int(thread_id))
    if thread is None:
        try:
            thread = await bot.fetch_channel(int(thread_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            thread = None
    if thread is None:
        database.terminer_combat_pvp(combat_id)
        return True

    # Choix de remplaçant en attente : la résolution patiente (envoi auto géré dedans)
    if await traiter_choix_ko_2v2(combat_id, thread):
        return False

    joueurs = _joueurs(combat_id)

    # Fin de combat ? (peut arriver via abandons entre deux résolutions)
    for equipe_gagnante, equipe_perdante in ((1, 2), (2, 1)):
        if _equipe_vaincue(combat_id, joueurs, equipe_perdante):
            par_abandon = not _equipe_entierement_ko(combat_id, joueurs, equipe_perdante)
            database.terminer_combat_pvp(combat_id)
            await _annoncer_victoire(bot, combat_id, thread, joueurs, equipe_gagnante, noms, par_abandon)
            return True

    # Sièges IA (dresseurs duo) : jouent d'office, comme en 1v1 ("l'IA rejoue tout de
    # suite, seul le joueur humain fait attendre") — sans effet sur un combat PvP pur
    # (aucun user_id négatif là-dedans).
    for j in joueurs:
        if j["user_id"] < 0 and not j["abandonne"] and not _joueur_hors_combat(combat_id, j):
            await _jouer_tour_ia_2v2(combat_id, j["user_id"], joueurs)
    joueurs = _joueurs(combat_id)

    # Joueurs encore censés jouer ce tour : vivants, non abandonnés, sans action posée
    en_attente = []
    for j in joueurs:
        if j["abandonne"] or _joueur_hors_combat(combat_id, j):
            continue
        if j["action"] is None:
            # Un Pokémon en pleine charge (ou qui doit récupérer) agit d'office : son
            # joueur n'a rien à choisir ce tour, il ne doit pas retarder la résolution.
            if j["actif_nom"]:
                charge = database.obtenir_charge(combat_id, j["user_id"], j["actif_nom"])
                if charge["attaque_en_charge"] or charge["doit_recharger"]:
                    continue
            en_attente.append(j["user_id"])

    timer_expire = int(time.time()) >= combat["date_limite_tour"]
    if en_attente and not timer_expire:
        return False

    log = await resoudre_tour_2v2(combat_id)

    joueurs = _joueurs(combat_id)
    for equipe_gagnante, equipe_perdante in ((1, 2), (2, 1)):
        if _equipe_vaincue(combat_id, joueurs, equipe_perdante):
            par_abandon = not _equipe_entierement_ko(combat_id, joueurs, equipe_perdante)
            database.terminer_combat_pvp(combat_id)
            for uid in [j["user_id"] for j in joueurs]:
                pass  # PvP : pas de synchronisation vers le pool persistant, comme en 1v1
            log_propre = _nettoyer_log_2v2(log, joueurs, noms_ia)
            embeds = construire_embeds_2v2(combat_id, noms, log_tour=log_propre)
            try:
                msg = await thread.fetch_message(message_id)
                await msg.edit(embeds=embeds, view=None)
            except discord.HTTPException:
                pass
            await _annoncer_victoire(bot, combat_id, thread, joueurs, equipe_gagnante, noms, par_abandon)
            return True

    # Tour suivant
    database.vider_actions_2v2(combat_id)
    database.passer_tour_pvp(combat_id, int(time.time()) + DUREE_TOUR_2V2)
    log_propre = _nettoyer_log_2v2(log, joueurs, noms_ia)
    embeds = construire_embeds_2v2(combat_id, noms, log_tour=log_propre)
    vue = VueAction2v2(combat_id, avec_choix_ko=bool(database.obtenir_choix_ko(combat_id)))
    try:
        msg = await thread.fetch_message(message_id)
        await msg.edit(embeds=embeds, view=vue)
    except discord.HTTPException:
        pass
    return False


# ----------------------------------------------------------------------------
# Vues d'action en combat
# ----------------------------------------------------------------------------

class VueAction2v2(discord.ui.View):
    """Panneau d'action partagé du combat 2v2 — mêmes principes que VueActionCombat 1v1,
    avec en plus le CHOIX DE LA CIBLE sur les attaques, et le support du DOUBLE COMBAT
    (un joueur humain peut contrôler 2 sièges à la fois face à un duo de dresseurs — voir
    _demarrer_action, qui insère une étape "quel Pokémon ?" dans ce cas précis)."""

    def __init__(self, combat_id: int, avec_choix_ko: bool = False):
        super().__init__(timeout=None)
        self.combat_id = combat_id
        if avec_choix_ko:
            bouton = discord.ui.Button(label="Envoyer un Pokémon", emoji="🔁", style=discord.ButtonStyle.primary, row=1)
            bouton.callback = self._on_envoyer_remplacant
            self.add_item(bouton)

    def _joueur(self, siege_id: int):
        return next((j for j in _joueurs(self.combat_id) if j["user_id"] == siege_id), None)

    async def _demarrer_action(self, interaction: discord.Interaction, flux):
        """Résout QUEL siège cette interaction concerne, puis appelle flux(interaction, j).
        Un joueur ne contrôle normalement qu'un seul siège (comme avant) ; en double combat
        (dresseur DUO) il peut en contrôler 2 simultanément — dans ce cas, une étape
        supplémentaire lui demande lequel de ses 2 Pokémon doit agir."""
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est terminé.", ephemeral=True)
            return

        sieges = [j for j in _joueurs(self.combat_id) if controleur_reel(j["user_id"]) == interaction.user.id]
        if not sieges:
            await interaction.response.send_message("Tu n'es pas un des combattants !", ephemeral=True)
            return

        eligibles = []
        message_bloquant = None
        for j in sieges:
            if j["abandonne"]:
                message_bloquant = message_bloquant or "Tu as abandonné ce combat."
                continue
            if _joueur_hors_combat(self.combat_id, j):
                message_bloquant = message_bloquant or "💀 Toute ton équipe est K.O. !"
                continue
            if j["action"] is not None:
                message_bloquant = message_bloquant or "Tu as déjà choisi ton action pour ce tour !"
                continue
            if any(r["user_id"] == j["user_id"] for r in database.obtenir_choix_ko(self.combat_id)):
                message_bloquant = message_bloquant or (
                    "🔁 Ton Pokémon est K.O. — choisis d'abord ton remplaçant avec le bouton "
                    "**Envoyer un Pokémon** !"
                )
                continue
            eligibles.append(j)

        if not eligibles:
            await interaction.response.send_message(message_bloquant or "Rien à faire pour l'instant.", ephemeral=True)
            return

        if len(eligibles) == 1:
            await flux(interaction, eligibles[0])
            return

        # Double combat : 2 Pokémon à faire agir, on demande lequel avant d'ouvrir le
        # menu normal (attaque/potion/changement) pour le siège choisi.
        vue = _VueChoixSiege2v2(eligibles, flux)
        await interaction.response.send_message("⚔️ Tu contrôles 2 Pokémon — lequel fait agir ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Attaquer", style=discord.ButtonStyle.danger, emoji="⚔️", row=0)
    async def attaquer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._demarrer_action(interaction, self._flux_attaquer)

    async def _flux_attaquer(self, interaction: discord.Interaction, j):
        charge = database.obtenir_charge(self.combat_id, j["user_id"], j["actif_nom"])
        if charge["attaque_en_charge"]:
            await interaction.response.send_message(
                f"⚡ **{j['actif_nom']}** charge **{charge['attaque_en_charge']}** — il la relâchera "
                f"automatiquement ce tour-ci, rien à choisir !",
                ephemeral=True,
            )
            return
        if charge["doit_recharger"]:
            await interaction.response.send_message(
                f"😵‍💫 **{j['actif_nom']}** doit récupérer ce tour-ci — rien à choisir !",
                ephemeral=True,
            )
            return
        equipees = database.obtenir_attaques_equipees(j["user_id"], j["actif_nom"], combat_id=self.combat_id)
        equipees_dispo = {}
        for slot, nom in equipees.items():
            pp_max = pp_max_attaque(obtenir_attaque(nom))
            pp_restant = database.obtenir_pp(self.combat_id, j["user_id"], j["actif_nom"], nom, pp_max)
            if pp_restant > 0:
                equipees_dispo[slot] = (nom, pp_restant, pp_max)

        if not equipees_dispo:
            # Aucune attaque utilisable : Lutte, sur une cible à choisir
            await self._choisir_cible(interaction, j, NOM_LUTTE)
            return

        vue = _VueChoixAttaque2v2(self, j, equipees_dispo)
        await interaction.response.send_message("Quelle attaque utiliser ?", view=vue, ephemeral=True)

    async def _choisir_cible(self, interaction: discord.Interaction, j, nom_attaque: str, depuis_selection: bool = False):
        """Étape cible : 2 adversaires vivants → boutons ; 1 seul → enregistrement direct."""
        joueurs = _joueurs(self.combat_id)
        equipe_adverse = 2 if j["equipe"] == 1 else 1
        cibles = _cibles_vivantes(self.combat_id, joueurs, equipe_adverse)
        if not cibles:
            contenu = "Plus aucune cible en face — le combat va se terminer."
            if depuis_selection:
                await interaction.response.edit_message(content=contenu, view=None)
            else:
                await interaction.response.send_message(contenu, ephemeral=True)
            return
        if len(cibles) == 1:
            cible_id = cibles[0][0]
            if database.definir_action_2v2(self.combat_id, j["user_id"], f"attaque:{nom_attaque}@{cible_id}"):
                contenu = f"⚔️ Action enregistrée : **{nom_attaque}** sur **{cibles[0][1]}** !"
            else:
                contenu = "Tu as déjà choisi ton action pour ce tour !"
            if depuis_selection:
                await interaction.response.edit_message(content=contenu, view=None)
            else:
                await interaction.response.send_message(contenu, ephemeral=True)
            return
        vue = _VueChoixCible2v2(self.combat_id, j["user_id"], nom_attaque, cibles)
        contenu = f"🎯 **{nom_attaque}** — sur quel Pokémon ?"
        if depuis_selection:
            await interaction.response.edit_message(content=contenu, view=vue)
        else:
            await interaction.response.send_message(contenu, view=vue, ephemeral=True)

    @discord.ui.button(label="Potion", style=discord.ButtonStyle.success, emoji="🧪", row=0)
    async def potion(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._demarrer_action(interaction, self._flux_potion)

    async def _flux_potion(self, interaction: discord.Interaction, j):
        inventaire = database.obtenir_inventaire_balls(j["user_id"])
        potions = {t: q for t, q in inventaire.items() if t in config.SOIN_POURCENT or t == "totalsoin"}
        potions = {t: q for t, q in potions.items() if q > 0}
        if not potions:
            await interaction.response.send_message("Tu n'as aucune potion en stock !", ephemeral=True)
            return
        vue = _VueChoixPotion2v2(self.combat_id, j["user_id"], potions)
        await interaction.response.send_message("Quelle potion utiliser ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Changer", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def changer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._demarrer_action(interaction, self._flux_changer)

    async def _flux_changer(self, interaction: discord.Interaction, j):
        equipe = database.obtenir_equipe_pvp(self.combat_id, j["user_id"])
        vivants = [r for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != j["actif_nom"]]
        if not vivants:
            await interaction.response.send_message("Tu n'as plus d'autres Pokémon vivants !", ephemeral=True)
            return
        vue = _VueChoixChangement2v2(self.combat_id, j["user_id"], vivants)
        await interaction.response.send_message("Quel Pokémon envoyer ?", view=vue, ephemeral=True)

    @discord.ui.button(label="Abandonner", style=discord.ButtonStyle.secondary, emoji="🏳️", row=1)
    async def abandonner(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est déjà terminé.", ephemeral=True)
            return
        # Abandonner concerne TOUS les sièges de ce joueur d'un coup (les 2 Pokémon d'un
        # double combat, pas un seul) — abandonner "à moitié" n'aurait pas de sens.
        sieges = [j for j in _joueurs(self.combat_id) if controleur_reel(j["user_id"]) == interaction.user.id]
        if not sieges:
            await interaction.response.send_message("Tu n'es pas un des combattants !", ephemeral=True)
            return
        if all(j["abandonne"] for j in sieges):
            await interaction.response.send_message("Tu as déjà abandonné.", ephemeral=True)
            return
        for j in sieges:
            database.marquer_abandon_2v2(self.combat_id, j["user_id"])
            database.supprimer_choix_ko(self.combat_id, j["user_id"])
        await interaction.response.send_message("🏳️ Tu as abandonné.", ephemeral=True)
        try:
            texte = (
                "— ton coéquipier continue seul !" if len(sieges) == 1
                else "— le combat se termine."
            )
            await interaction.channel.send(f"🏳️ <@{interaction.user.id}> abandonne le combat {texte}")
        except discord.HTTPException:
            pass
        # La fin de combat éventuelle (équipe entière hors jeu) est constatée au prochain tick.

    async def _on_envoyer_remplacant(self, interaction: discord.Interaction):
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.send_message("Ce combat est terminé.", ephemeral=True)
            return
        choix_en_attente = [
            r for r in database.obtenir_choix_ko(self.combat_id)
            if controleur_reel(r["user_id"]) == interaction.user.id
        ]
        if not choix_en_attente:
            await interaction.response.send_message(
                "Tu n'as pas de Pokémon K.O. à remplacer (ou l'envoi automatique a déjà eu lieu).",
                ephemeral=True,
            )
            return
        # S'il y en a 2 en attente en même temps (double K.O. au même tour), on traite le
        # premier — le bouton reste affiché pour traiter le second juste après.
        siege_id = choix_en_attente[0]["user_id"]
        j = self._joueur(siege_id)
        equipe = database.obtenir_equipe_pvp(self.combat_id, siege_id)
        vivants = [r for r in equipe if r["pv_actuels"] > 0 and r["pokemon_nom"] != (j["actif_nom"] if j else None)]
        if not vivants:
            await interaction.response.send_message("Tu n'as plus d'autres Pokémon vivants !", ephemeral=True)
            return
        vue = _VueChoixRemplacant2v2(self.combat_id, siege_id, vivants)
        await interaction.response.send_message("Quel Pokémon envoyer au combat ?", view=vue, ephemeral=True)


class _VueChoixSiege2v2(discord.ui.View):
    """Double combat uniquement : le joueur contrôle 2 Pokémon à la fois (face à un duo de
    dresseurs) — ce sous-menu lui fait choisir lequel des deux agit, avant d'entrer dans le
    flux normal (attaque/potion/changement) demandé au départ."""

    def __init__(self, sieges: list, flux):
        super().__init__(timeout=30)
        self.flux = flux
        for j in sieges:
            bouton = discord.ui.Button(label=j["actif_nom"], emoji="🔹", style=discord.ButtonStyle.primary)
            bouton.callback = self._creer_callback(j)
            self.add_item(bouton)

    def _creer_callback(self, j):
        async def callback(interaction: discord.Interaction):
            await self.flux(interaction, j)
        return callback


class _VueChoixAttaque2v2(discord.ui.View):
    def __init__(self, vue_parente: VueAction2v2, j, equipees_dispo: dict):
        super().__init__(timeout=30)
        self.vue_parente = vue_parente
        self.j = j
        options = []
        for slot, (nom, pp_restant, pp_max) in sorted(equipees_dispo.items()):
            attaque = obtenir_attaque(nom)
            desc = f"{attaque['puissance'] or '—'} pcs — préc. {attaque.get('precision') or '∞'}% — {pp_restant}/{pp_max} PP"
            options.append(discord.SelectOption(label=nom, description=desc[:100]))
        select = discord.ui.Select(placeholder="Choisis ton attaque…", options=options[:25])
        select.callback = self._on_choix
        self.add_item(select)
        self._select = select

    async def _on_choix(self, interaction: discord.Interaction):
        # Relire l'état actuel du siège via son ID propre (pas interaction.user.id : en
        # double combat, le siège peut être un ID délégué différent de l'ID Discord réel).
        j = self.vue_parente._joueur(self.j["user_id"])
        if j is None or j["action"] is not None:
            await interaction.response.edit_message(content="Tu as déjà choisi ton action pour ce tour !", view=None)
            return
        await self.vue_parente._choisir_cible(interaction, j, self._select.values[0], depuis_selection=True)


class _VueChoixCible2v2(discord.ui.View):
    def __init__(self, combat_id: int, user_id: int, nom_attaque: str, cibles: list):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id
        self.nom_attaque = nom_attaque
        for cible_id, cible_nom, row in cibles[:4]:
            bouton = discord.ui.Button(
                label=f"{cible_nom} ({row['pv_actuels']}/{row['pv_max']} PV)",
                emoji="🎯",
                style=discord.ButtonStyle.danger,
            )
            bouton.callback = self._creer_callback(cible_id, cible_nom)
            self.add_item(bouton)

    def _creer_callback(self, cible_id: int, cible_nom: str):
        async def callback(interaction: discord.Interaction):
            if database.definir_action_2v2(self.combat_id, self.user_id, f"attaque:{self.nom_attaque}@{cible_id}"):
                await interaction.response.edit_message(
                    content=f"⚔️ Action enregistrée : **{self.nom_attaque}** sur **{cible_nom}** !", view=None
                )
            else:
                await interaction.response.edit_message(content="Tu as déjà choisi ton action pour ce tour !", view=None)
        return callback


class _VueChoixPotion2v2(discord.ui.View):
    def __init__(self, combat_id: int, user_id: int, potions: dict):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id
        for type_potion, quantite in potions.items():
            bouton = discord.ui.Button(
                label=f"{NOM_SOIN_AFFICHAGE.get(type_potion, type_potion)} (x{quantite})",
                emoji=EMOJI_SOINS.get(type_potion),
                style=discord.ButtonStyle.success,
            )
            bouton.callback = self._creer_callback(type_potion)
            self.add_item(bouton)

    def _creer_callback(self, type_potion: str):
        async def callback(interaction: discord.Interaction):
            j = next((x for x in _joueurs(self.combat_id) if x["user_id"] == self.user_id), None)
            if j is None or j["action"] is not None:
                await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
                return
            if type_potion != "totalsoin" and j["potions_soin"] >= config.LIMITE_POTIONS_SOIN_COMBAT:
                await interaction.response.edit_message(
                    content=f"Tu as déjà utilisé tes {config.LIMITE_POTIONS_SOIN_COMBAT} potions de soin pour ce combat !",
                    view=None,
                )
                return
            if not database.retirer_ball(self.user_id, type_potion):
                await interaction.response.edit_message(content="Tu n'as plus cette potion !", view=None)
                return
            if not database.definir_action_2v2(self.combat_id, self.user_id, f"potion:{type_potion}"):
                await interaction.response.edit_message(content="Tu as déjà joué ce tour !", view=None)
                return
            if type_potion != "totalsoin":
                database.incrementer_potions_2v2(self.combat_id, self.user_id)
            await interaction.response.edit_message(content="💊 Action enregistrée : potion !", view=None)
        return callback


class _VueChoixChangement2v2(discord.ui.View):
    def __init__(self, combat_id: int, user_id: int, vivants: list):
        super().__init__(timeout=30)
        self.combat_id = combat_id
        self.user_id = user_id
        options = [
            discord.SelectOption(label=r["pokemon_nom"], description=f"{r['pv_actuels']}/{r['pv_max']} PV")
            for r in vivants[:25]
        ]
        select = discord.ui.Select(placeholder="Choisis ton prochain Pokémon…", options=options)
        select.callback = self._on_choix
        self.add_item(select)
        self._select = select

    async def _on_choix(self, interaction: discord.Interaction):
        if database.definir_action_2v2(self.combat_id, self.user_id, f"changer:{self._select.values[0]}"):
            await interaction.response.edit_message(
                content=f"🔄 Action enregistrée : envoyer **{self._select.values[0]}** !", view=None
            )
        else:
            await interaction.response.edit_message(content="Tu as déjà choisi ton action pour ce tour !", view=None)


class _VueChoixRemplacant2v2(discord.ui.View):
    """Choix du remplaçant après K.O. — changement GRATUIT (ne consomme pas le tour)."""

    def __init__(self, combat_id: int, user_id: int, vivants: list):
        super().__init__(timeout=config.CHOIX_KO_DUREE_SECONDES)
        self.combat_id = combat_id
        self.user_id = user_id
        options = [
            discord.SelectOption(label=r["pokemon_nom"], description=f"{r['pv_actuels']}/{r['pv_max']} PV")
            for r in vivants[:25]
        ]
        select = discord.ui.Select(placeholder="Choisis ton prochain Pokémon…", options=options)
        select.callback = self._on_choix
        self.add_item(select)
        self._select = select

    async def _on_choix(self, interaction: discord.Interaction):
        if not database.supprimer_choix_ko(self.combat_id, self.user_id):
            await interaction.response.edit_message(content="⏳ Trop tard — l'envoi automatique a déjà eu lieu !", view=None)
            return
        combat = database.obtenir_combat(self.combat_id)
        if not combat or not combat["actif"]:
            await interaction.response.edit_message(content="Ce combat est terminé.", view=None)
            return
        nouveau_nom = self._select.values[0]
        database.definir_actif_2v2(self.combat_id, self.user_id, nouveau_nom)
        mention = f"<@{controleur_reel(self.user_id)}>" if self.user_id > 0 else "L'adversaire"
        mini_log = [f"🔁 {mention} envoie **{nouveau_nom}** !"]
        _appliquer_hazards_entree(self.combat_id, self.user_id, nouveau_nom, mini_log)
        await interaction.response.edit_message(content=f"✅ **{nouveau_nom}** entre en jeu !", view=None)
        try:
            await interaction.channel.send("\n".join(mini_log))
        except discord.HTTPException:
            pass


# ----------------------------------------------------------------------------
# Lobby
# ----------------------------------------------------------------------------

class VueLobby2v2(discord.ui.View):
    """Lobby du /combat-2v2 : menu déroulant Équipe 1 / Équipe 2 (2 places chacune),
    démarrage automatique à 4/4, annulation si incomplet à la fin du délai."""

    def __init__(self, bot, createur_id: int):
        super().__init__(timeout=DUREE_LOBBY_2V2)
        self.bot = bot
        self.createur_id = createur_id
        self.inscrits = {}  # user_id -> equipe (1 ou 2)
        self.noms = {}  # user_id -> display_name
        self.message = None
        self.demarre = False

        select = discord.ui.Select(
            placeholder="Choisis ton équipe…",
            options=[
                discord.SelectOption(label="Rejoindre l'Équipe 1", value="1", emoji="🔵"),
                discord.SelectOption(label="Rejoindre l'Équipe 2", value="2", emoji="🔴"),
                discord.SelectOption(label="Se retirer du combat", value="retrait", emoji="🚪"),
            ],
        )
        select.callback = self._on_choix
        self.add_item(select)

    def construire_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⚔️ Combat 2v2 — Recherche de combattants !",
            description=(
                f"Deux équipes de deux joueurs, **{TAILLE_EQUIPE_2V2} Pokémon chacun** "
                f"(les {TAILLE_EQUIPE_2V2} premiers de ton équipe de combat).\n"
                f"Le combat démarre automatiquement à 4/4."
            ),
            color=discord.Color.purple(),
        )
        for equipe, emoji in ((1, "🔵"), (2, "🔴")):
            membres = [self.noms.get(u, "?") for u, e in self.inscrits.items() if e == equipe]
            valeur = "\n".join(f"• {n}" for n in membres) if membres else "*Personne pour l'instant*"
            embed.add_field(name=f"{emoji} Équipe {equipe} ({len(membres)}/2)", value=valeur, inline=True)
        embed.set_footer(text=f"Lobby ouvert pendant {DUREE_LOBBY_2V2 // 60} minutes.")
        return embed

    async def _on_choix(self, interaction: discord.Interaction):
        if self.demarre:
            await interaction.response.send_message("Le combat a déjà démarré !", ephemeral=True)
            return
        choix = interaction.data["values"][0]
        user_id = interaction.user.id

        if choix == "retrait":
            if user_id in self.inscrits:
                del self.inscrits[user_id]
                await interaction.response.edit_message(embed=self.construire_embed(), view=self)
            else:
                await interaction.response.send_message("Tu n'es pas inscrit à ce combat.", ephemeral=True)
            return

        equipe = int(choix)
        if database.combat_en_cours_pour_joueur(user_id) is not None:
            await interaction.response.send_message("Tu es déjà dans un combat en cours !", ephemeral=True)
            return
        equipe_dispo = database.obtenir_equipe_combat_disponible(user_id)
        if not equipe_dispo:
            await interaction.response.send_message(
                "❌ Configure ton équipe de combat d'abord (`/equipe-combat`) !", ephemeral=True
            )
            return
        places = sum(1 for u, e in self.inscrits.items() if e == equipe and u != user_id)
        if places >= 2:
            await interaction.response.send_message(f"L'Équipe {equipe} est déjà complète !", ephemeral=True)
            return

        self.inscrits[user_id] = equipe
        self.noms[user_id] = interaction.user.display_name
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

        if len(self.inscrits) == 4 and list(sorted(
            [e for e in self.inscrits.values()]
        )) == [1, 1, 2, 2]:
            self.demarre = True
            self.stop()
            await demarrer_combat_2v2(self.bot, interaction.channel, dict(self.inscrits), dict(self.noms), self.message)

    async def on_timeout(self):
        if self.demarre:
            return
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="⌛ Lobby 2v2 expiré — pas assez de combattants. Relancez `/combat-2v2` quand vous êtes 4 !",
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                pass


async def demarrer_combat_2v2(bot, channel, inscrits: dict, noms: dict, message_lobby):
    """Crée le fil, initialise le combat (ancrage combat_pvp + 4 joueurs + équipes de 3),
    et lance la boucle de résolution."""
    # Re-vérification finale : personne ne doit avoir rejoint un autre combat entre-temps
    for uid in inscrits:
        if database.combat_en_cours_pour_joueur(uid) is not None:
            try:
                await channel.send(f"❌ <@{uid}> est déjà dans un autre combat — 2v2 annulé, relancez un lobby.")
            except discord.HTTPException:
                pass
            return

    equipes_stats = {}
    for uid in inscrits:
        stats = preparer_equipe_pour_combat(uid)[:TAILLE_EQUIPE_2V2]
        if not stats:
            try:
                await channel.send(f"❌ <@{uid}> n'a pas d'équipe de combat valide — 2v2 annulé.")
            except discord.HTTPException:
                pass
            return
        equipes_stats[uid] = stats

    eq1 = [u for u, e in inscrits.items() if e == 1]
    eq2 = [u for u, e in inscrits.items() if e == 2]

    # Ancrage combat_pvp : les deux "capitaines" y figurent (ID unique partagé avec les
    # tables annexes + verrou "déjà en combat" + nettoyage au redémarrage gratuits).
    date_limite = int(time.time()) + DUREE_TOUR_2V2
    combat_id = database.creer_combat(eq1[0], eq2[0], equipes_stats[eq1[0]][0]["nom"], equipes_stats[eq2[0]][0]["nom"], date_limite)

    inscriptions = [(uid, inscrits[uid], equipes_stats[uid][0]["nom"]) for uid in inscrits]
    database.creer_joueurs_2v2(combat_id, inscriptions)
    for uid in inscrits:
        database.initialiser_equipe_combat_pvp(combat_id, uid, equipes_stats[uid])

    try:
        thread = await channel.create_thread(
            name=f"⚔️ 2v2 — {noms.get(eq1[0], '?')} & {noms.get(eq1[1], '?')} vs {noms.get(eq2[0], '?')} & {noms.get(eq2[1], '?')}"[:100],
            type=discord.ChannelType.public_thread,
        )
        for uid in inscrits:
            membre = channel.guild.get_member(uid)
            if membre is not None:
                try:
                    await thread.add_user(membre)
                except discord.HTTPException:
                    pass
    except discord.HTTPException as e:
        database.terminer_combat_pvp(combat_id)
        try:
            await channel.send(f"❌ Impossible de créer le fil de combat : {e}")
        except discord.HTTPException:
            pass
        return

    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET thread_id = ? WHERE id = ?", (str(thread.id), combat_id))
    conn.commit()
    conn.close()

    mentions = " ".join(f"<@{u}>" for u in inscrits)
    embeds = construire_embeds_2v2(combat_id, noms)
    vue = VueAction2v2(combat_id)
    msg = await thread.send(content=f"{mentions} — le combat 2v2 commence ! Choisissez vos actions.", embeds=embeds, view=vue)

    if message_lobby is not None:
        try:
            await message_lobby.edit(content=f"⚔️ Le combat 2v2 a démarré → {thread.mention}", embed=None, view=None)
        except discord.HTTPException:
            pass

    journal.logger(f"⚔️ Combat 2v2 lancé : Équipe 1 ({eq1[0]}, {eq1[1]}) vs Équipe 2 ({eq2[0]}, {eq2[1]}).")
    bot.loop.create_task(boucle_resolution_2v2(bot, combat_id, thread.id, msg.id, noms))


async def demarrer_duo_dresseur(bot, joueur: discord.Member, dresseur_id: int, archetype: dict, channel, interaction: discord.Interaction = None):
    """Double combat 2v2 PvE : un seul joueur humain affronte SIMULTANÉMENT les 2
    dresseurs d'un archétype DUO (voir dresseurs.ARCHETYPES_DUO). Le joueur contrôle 2
    Pokémon actifs à la fois — son équipe de combat (jusqu'à 6) est répartie en 2 moitiés,
    une par siège (voir id_delegue / DELEGUE_OFFSET en tête de ce fichier)."""
    if database.combat_en_cours_pour_joueur(joueur.id) is not None:
        texte = "❌ Tu as déjà un combat en cours !"
        if interaction is not None:
            try:
                await interaction.followup.send(texte, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                pass
        return

    # --- Équipe du joueur : PV persistants réels (comme un dresseur solo), répartie en
    # 2 moitiés — une par Pokémon actif simultané. ---
    noms_joueur = database.obtenir_equipe_combat_disponible(joueur.id)
    captures = database.obtenir_pokedex_joueur(joueur.id)
    especes_possedees = {row["pokemon_nom"] for row in captures}
    equipe_joueur = []
    for nom in noms_joueur:
        if nom not in especes_possedees:
            continue
        stats = stats_combattant_reel(joueur.id, nom)
        pv_actuels = database.obtenir_pv_actuels(joueur.id, nom, stats["pv"])
        equipe_joueur.append((stats, pv_actuels))
    equipe_joueur_vivante = [(s, pv) for s, pv in equipe_joueur if pv > 0]

    if len(equipe_joueur_vivante) < 2:
        texte = (
            f"❌ {joueur.mention} — il te faut au moins **2 Pokémon vivants** (PV persistants > 0) "
            f"pour un double combat : tu contrôles 2 actifs en même temps ! "
            f"Soigne ton équipe via `/equipe-combat` si besoin."
        )
        if interaction is not None:
            try:
                await interaction.followup.send(texte, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                await channel.send(texte)
        else:
            await channel.send(texte)
        return

    milieu = max(1, len(equipe_joueur_vivante) // 2 + len(equipe_joueur_vivante) % 2)
    moitie_a = equipe_joueur_vivante[:milieu]
    moitie_b = equipe_joueur_vivante[milieu:] or [equipe_joueur_vivante[-1]]
    # (le "or" ci-dessus ne devrait jamais servir vu la garde len>=2 ci-dessus, filet de sécurité)

    id_reel = joueur.id
    id_delegue_val = id_delegue(joueur.id)

    # --- Les 2 dresseurs IA : équipes indépendantes de 6, générées comme un dresseur solo ---
    pc_cible = round(dresseurs_module._pc_cumule_equipe(joueur.id))
    if pc_cible <= 0:
        pc_cible = 500
    niveau_reference = dresseurs_module._niveau_moyen_equipe(joueur.id)
    equipe_ia_1 = dresseurs_module.generer_equipe_dresseur(archetype, pc_cible, niveau_reference)
    equipe_ia_2 = dresseurs_module.generer_equipe_dresseur(archetype, pc_cible, niveau_reference)
    if not equipe_ia_1 or not equipe_ia_2:
        await channel.send("❌ Impossible de générer l'équipe adverse — double combat annulé.")
        return

    # --- Ancrage combat_pvp (comme le PvP 2v2) : réel + 1er dresseur IA comme "capitaines" ---
    date_limite = int(time.time()) + DUREE_TOUR_2V2
    combat_id = database.creer_combat(id_reel, dresseurs_module.ID_DRESSEUR_BASE - joueur.id, moitie_a[0][0]["nom"], equipe_ia_1[0]["nom"], date_limite)
    id_ia_1 = dresseurs_module.ID_DRESSEUR_BASE - combat_id * 2
    id_ia_2 = dresseurs_module.ID_DRESSEUR_BASE - combat_id * 2 - 1

    database.creer_joueurs_2v2(combat_id, [
        (id_reel, 1, moitie_a[0][0]["nom"]),
        (id_delegue_val, 1, moitie_b[0][0]["nom"]),
        (id_ia_1, 2, equipe_ia_1[0]["nom"]),
        (id_ia_2, 2, equipe_ia_2[0]["nom"]),
    ])

    # Équipe du joueur : insertion directe avec PV RÉELS (pas via initialiser_equipe_combat_pvp,
    # qui met tout le monde à pleine vie — ici on veut les PV persistants, comme un dresseur solo).
    conn = database.get_connexion()
    cur = conn.cursor()
    for siege_id, moitie in ((id_reel, moitie_a), (id_delegue_val, moitie_b)):
        for i, (stats, pv_actuels) in enumerate(moitie):
            cur.execute(
                """
                INSERT INTO combat_equipe
                    (combat_id, user_id, pokemon_nom, pv_max, pv_actuels, position, atq, defe, atq_spe, def_spe, vit, niveau)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    combat_id, siege_id, stats["nom"], stats["pv"], pv_actuels, i,
                    stats["attaque"], stats["defense"], stats["attaque_spe"], stats["defense_spe"], stats["vitesse"],
                    stats["niveau"],
                ),
            )
    conn.commit()
    conn.close()

    # Équipes IA : pleine vie, comme n'importe quel dresseur solo fraîchement généré.
    database.initialiser_equipe_combat_pvp(combat_id, id_ia_1, equipe_ia_1)
    database.initialiser_equipe_combat_pvp(combat_id, id_ia_2, equipe_ia_2)
    for mon in equipe_ia_1:
        dresseurs_module._equiper_attaques_aleatoires(id_ia_1, mon["nom"])
    for mon in equipe_ia_2:
        dresseurs_module._equiper_attaques_aleatoires(id_ia_2, mon["nom"])

    database.enregistrer_defi_dresseur(dresseur_id, joueur.id)

    # --- Fil de combat ---
    sous_noms = archetype.get("sous_noms", (archetype["nom"], archetype["nom"]))
    try:
        thread = await channel.create_thread(
            name=f"⚔️ {joueur.display_name} vs {archetype['nom']}"[:100],
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(joueur)
    except discord.HTTPException as e:
        database.terminer_combat_pvp(combat_id)
        try:
            await channel.send(f"❌ Impossible de créer le fil de combat : {e}")
        except discord.HTTPException:
            pass
        return

    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET thread_id = ? WHERE id = ?", (str(thread.id), combat_id))
    conn.commit()
    conn.close()

    noms = {
        id_reel: joueur.display_name,
        id_delegue_val: f"{joueur.display_name} (2)",
        id_ia_1: sous_noms[0],
        id_ia_2: sous_noms[1],
    }
    noms_ia = {
        id_ia_1: f"{sous_noms[0]} ({archetype['nom']})",
        id_ia_2: f"{sous_noms[1]} ({archetype['nom']})",
    }

    # L'IA joue d'office son tout premier tour, comme en 1v1 ("le joueur n'attend jamais
    # après elle") — protégé : si ça plante, le combat démarre quand même.
    try:
        joueurs_initiaux = _joueurs(combat_id)
        await _jouer_tour_ia_2v2(combat_id, id_ia_1, joueurs_initiaux)
        await _jouer_tour_ia_2v2(combat_id, id_ia_2, joueurs_initiaux)
    except Exception:
        import traceback

        print(f"⚠️ Erreur au 1er tour IA du duo dresseur {combat_id} :")
        traceback.print_exc()

    embeds = construire_embeds_2v2(combat_id, noms)
    vue = VueAction2v2(combat_id)
    msg = await thread.send(
        content=f"{joueur.mention} ⚔️ **{sous_noms[0]}** et **{sous_noms[1]}** ({archetype['nom']}) vous défient en double combat !",
        embeds=embeds, view=vue,
    )

    if interaction is not None:
        try:
            await interaction.followup.send(f"⚔️ Double combat contre **{archetype['nom']}** lancé !", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass

    journal.logger(f"⚔️ <@{joueur.id}> affronte le duo **{archetype['nom']}** en double combat (2v2 PvE).")
    bot.loop.create_task(boucle_resolution_2v2(bot, combat_id, thread.id, msg.id, noms, noms_ia))


async def demarrer_combat_double(bot, joueur1: discord.Member, joueur2: discord.Member, channel):
    """1v1 en FORMAT double combat : 2 joueurs humains, une équipe COMPLÈTE (jusqu'à 6)
    chacun, répartie en 2 moitiés (2 Pokémon actifs simultanés par joueur — voir
    id_delegue/DELEGUE_OFFSET en tête de fichier). Contrairement au double combat contre
    un duo de dresseurs (PvE, PV persistants), ce mode est du PvP classique : équipes à
    pleine vie à chaque combat, comme /defier (voir combat.demarrer_combat)."""
    equipe1 = preparer_equipe_pour_combat(joueur1.id)
    equipe2 = preparer_equipe_pour_combat(joueur2.id)
    if len(equipe1) < 2 or len(equipe2) < 2:
        manquant = joueur1.display_name if len(equipe1) < 2 else joueur2.display_name
        await channel.send(
            f"❌ {manquant} a besoin d'au moins **2 Pokémon** dans son équipe de combat pour "
            f"un 1v1 en double (2 actifs simultanés) — configure `/equipe-combat` !"
        )
        return

    milieu1 = len(equipe1) // 2 + len(equipe1) % 2
    moitie1_a, moitie1_b = equipe1[:milieu1], equipe1[milieu1:] or [equipe1[-1]]
    milieu2 = len(equipe2) // 2 + len(equipe2) % 2
    moitie2_a, moitie2_b = equipe2[:milieu2], equipe2[milieu2:] or [equipe2[-1]]

    id1_delegue = id_delegue(joueur1.id)
    id2_delegue = id_delegue(joueur2.id)

    date_limite = int(time.time()) + DUREE_TOUR_2V2
    combat_id = database.creer_combat(joueur1.id, joueur2.id, moitie1_a[0]["nom"], moitie2_a[0]["nom"], date_limite)

    database.creer_joueurs_2v2(combat_id, [
        (joueur1.id, 1, moitie1_a[0]["nom"]),
        (id1_delegue, 1, moitie1_b[0]["nom"]),
        (joueur2.id, 2, moitie2_a[0]["nom"]),
        (id2_delegue, 2, moitie2_b[0]["nom"]),
    ])
    database.initialiser_equipe_combat_pvp(combat_id, joueur1.id, moitie1_a)
    database.initialiser_equipe_combat_pvp(combat_id, id1_delegue, moitie1_b)
    database.initialiser_equipe_combat_pvp(combat_id, joueur2.id, moitie2_a)
    database.initialiser_equipe_combat_pvp(combat_id, id2_delegue, moitie2_b)

    try:
        thread = await channel.create_thread(
            name=f"⚔️ {joueur1.display_name} vs {joueur2.display_name} (double)"[:100],
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        for j in (joueur1, joueur2):
            try:
                await thread.add_user(j)
            except discord.HTTPException:
                pass
    except discord.HTTPException as e:
        database.terminer_combat_pvp(combat_id)
        try:
            await channel.send(f"❌ Impossible de créer le fil de combat : {e}")
        except discord.HTTPException:
            pass
        return

    conn = database.get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE combat_pvp SET thread_id = ? WHERE id = ?", (str(thread.id), combat_id))
    conn.commit()
    conn.close()

    noms = {
        joueur1.id: joueur1.display_name, id1_delegue: f"{joueur1.display_name} (2)",
        joueur2.id: joueur2.display_name, id2_delegue: f"{joueur2.display_name} (2)",
    }

    embeds = construire_embeds_2v2(combat_id, noms)
    vue = VueAction2v2(combat_id)
    msg = await thread.send(
        content=f"{joueur1.mention} {joueur2.mention} — le combat 1v1 en double commence ! "
                f"Chacun contrôle 2 Pokémon actifs.",
        embeds=embeds, view=vue,
    )

    journal.logger(f"⚔️ Combat double lancé : <@{joueur1.id}> vs <@{joueur2.id}> (1v1, format 2v2, équipes de 6).")
    bot.loop.create_task(boucle_resolution_2v2(bot, combat_id, thread.id, msg.id, noms))


async def lancer_lobby_2v2(bot, interaction: discord.Interaction):
    """Point d'entrée de la commande /combat-2v2."""
    if database.combat_en_cours_pour_joueur(interaction.user.id) is not None:
        await interaction.response.send_message("Tu es déjà dans un combat en cours !", ephemeral=True)
        return
    vue = VueLobby2v2(bot, interaction.user.id)
    await interaction.response.send_message(embed=vue.construire_embed(), view=vue)
    vue.message = await interaction.original_response()
