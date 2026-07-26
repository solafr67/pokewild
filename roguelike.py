"""Roguelike — mini-jeu indépendant du bot principal (aucune récompense en Poké Dollars/XP,
salon dédié config.CHANNEL_ROGUELIKE_ID). Équipe de 3 Pokémon GÉNÉRIQUES tirés au hasard
dans un pool fixe (pas les captures du joueur — décision explicite pour ne jamais toucher
au Pokédex ni aux attaques équipées du joueur), permadeath : à la mort, la run est perdue
intégralement et il faut recommencer de zéro. Accès illimité, aucun cooldown.

Moteur de combat volontairement SIMPLIFIÉ et autonome (pas de PP/statuts/objets en combat,
résolution du tour instantanée au clic — pas de tick d'attente comme le PvP principal) :
c'est un choix délibéré pour rester indépendant du moteur principal et de ses tables
(attaques_equipees notamment, qui est indexée par joueur+espèce et NE DOIT PAS être polluée
par une espèce générique de run qui coïnciderait avec une vraie capture du joueur).
"""

import random
import time

import discord

import config
import database
from pokemon_data import (
    EMOJI_TYPES,
    IV_DEFAUT,
    calculer_multiplicateur_type,
    calculer_toutes_stats,
    obtenir_pokemon_par_nom,
    sprite_pokemon,
)

DELAI_SUPPRESSION_FIL = 300  # 5 min après la fin d'une run (victoire ou mort), comme ailleurs

# Pool des Pokémon "génériques" pouvant être tirés comme starter — volontairement varié en
# types et modeste en puissance (pas de légendaires) pour que chaque run parte sur un pied
# d'égalité, peu importe le vrai Pokédex du joueur.
STARTER_POOL = [
    "Salamèche", "Carapuce", "Bulbizarre", "Racaillou", "Nosferapti", "Ponyta",
    "Machoc", "Magicarpe", "Abo", "Chenipan", "Rondoudou", "Goupix", "Psykokwak",
    "Tadmorv", "Griknot", "Mimigal", "Coxy", "Motisma",
]

# --- Pools d'ennemis ÉCHELONNÉS par palier de progression ---
# La "rareté" du Pokédex principal reflète la fréquence de CAPTURE, pas sa force réelle
# en combat — piocher au hasard parmi "commun/peu_commun/rare" pouvait donc sortir un
# Pokémon bien plus costaud que prévu dès l'étage 2 (ex: un Bétochef, aux stats de
# combat élevées malgré une rareté "commune"), écrasant une équipe encore faible sans
# que ce soit un choix injuste du joueur. On utilise donc des pools CURATÉS, dont la
# force monte avec la progression, plutôt que la rareté brute.
ENNEMIS_FAIBLE = STARTER_POOL  # même vivier que les starters : les 4-5 premiers étages
ENNEMIS_MOYEN = [
    "Roucoups", "Arbok", "Dardargnan", "Nosferalto", "Feunard",
    "Simiabraz", "Colhomard", "Galopa", "Akwakwak", "Papilusion", "Fouinar", "Pharamp",
]
ENNEMIS_FORT = [
    "Ronflex", "Léviator", "Dracaufeu", "Tortank", "Florizarre", "Alakazam",
    "Machamp", "Ptéra", "Scarabrute", "Tyranocif",
]


def _pool_ennemis_pour_etage(salle_index: int) -> list:
    if salle_index <= 3:
        return ENNEMIS_FAIBLE
    if salle_index <= 7:
        return ENNEMIS_MOYEN
    return ENNEMIS_FORT

# Une attaque neutre toujours disponible, + 2 attaques tirées du/des type(s) du Pokémon.
ATTAQUE_NEUTRE = {"nom": "Écrasement", "type": "normal", "puissance": 45, "precision": 100}
MOUVEPOOL_PAR_TYPE = {
    "normal":   [{"nom": "Vive-Attaque", "type": "normal", "puissance": 40, "precision": 100}, {"nom": "Cru-Aile", "type": "normal", "puissance": 60, "precision": 100}],
    "feu":      [{"nom": "Flammèche", "type": "feu", "puissance": 55, "precision": 100}, {"nom": "Lance-Flammes", "type": "feu", "puissance": 80, "precision": 95}],
    "eau":      [{"nom": "Pistolet à O", "type": "eau", "puissance": 55, "precision": 100}, {"nom": "Hydrocanon", "type": "eau", "puissance": 80, "precision": 90}],
    "plante":   [{"nom": "Tranch'Herbe", "type": "plante", "puissance": 55, "precision": 100}, {"nom": "Lance-Soleil éclair", "type": "plante", "puissance": 80, "precision": 95}],
    "electrik": [{"nom": "Éclair", "type": "electrik", "puissance": 55, "precision": 100}, {"nom": "Fatal-Foudre", "type": "electrik", "puissance": 80, "precision": 95}],
    "glace":    [{"nom": "Éclat Glace", "type": "glace", "puissance": 55, "precision": 100}, {"nom": "Blizzard éclair", "type": "glace", "puissance": 80, "precision": 90}],
    "combat":   [{"nom": "Poing-Karaté", "type": "combat", "puissance": 55, "precision": 100}, {"nom": "Close Combat", "type": "combat", "puissance": 80, "precision": 95}],
    "poison":   [{"nom": "Poisdart", "type": "poison", "puissance": 55, "precision": 100}, {"nom": "Bombe Toxik", "type": "poison", "puissance": 80, "precision": 90}],
    "sol":      [{"nom": "Jet de Sable", "type": "sol", "puissance": 55, "precision": 100}, {"nom": "Séisme éclair", "type": "sol", "puissance": 80, "precision": 95}],
    "vol":      [{"nom": "Tornade", "type": "vol", "puissance": 55, "precision": 100}, {"nom": "Ouragan éclair", "type": "vol", "puissance": 80, "precision": 90}],
    "psy":      [{"nom": "Choc Mental", "type": "psy", "puissance": 55, "precision": 100}, {"nom": "Psyko", "type": "psy", "puissance": 80, "precision": 95}],
    "insecte":  [{"nom": "Dard-Venin", "type": "insecte", "puissance": 55, "precision": 100}, {"nom": "Lame-Cutter", "type": "insecte", "puissance": 80, "precision": 95}],
    "roche":    [{"nom": "Jet de Pierres", "type": "roche", "puissance": 55, "precision": 100}, {"nom": "Éboulement", "type": "roche", "puissance": 80, "precision": 90}],
    "spectre":  [{"nom": "Griffe Ombre", "type": "spectre", "puissance": 55, "precision": 100}, {"nom": "Bal Masqué", "type": "spectre", "puissance": 80, "precision": 95}],
    "dragon":   [{"nom": "Draco-Griffe", "type": "dragon", "puissance": 55, "precision": 100}, {"nom": "Draco-Souffle éclair", "type": "dragon", "puissance": 80, "precision": 90}],
    "tenebres": [{"nom": "Morsure", "type": "tenebres", "puissance": 55, "precision": 100}, {"nom": "Étreinte éclair", "type": "tenebres", "puissance": 80, "precision": 95}],
    "acier":    [{"nom": "Griffe Acier", "type": "acier", "puissance": 55, "precision": 100}, {"nom": "Tête de Fer", "type": "acier", "puissance": 80, "precision": 95}],
    "fee":      [{"nom": "Vent Féérique", "type": "fee", "puissance": 55, "precision": 100}, {"nom": "Beau Sourire éclair", "type": "fee", "puissance": 80, "precision": 90}],
}

# --- Reliques : effets passifs propres à la run, jamais persistants au-delà ---
RELIQUES = {
    "griffes_aiguisees": {"nom": "Griffes Aiguisées", "emoji": "🗡️", "description": "+15% de dégâts infligés"},
    "peau_de_fer": {"nom": "Peau de Fer", "emoji": "🛡️", "description": "-15% de dégâts subis"},
    "carapace_solide": {"nom": "Carapace Solide", "emoji": "❤️", "description": "+20% de PV max (immédiat) sur toute l'équipe"},
    "regeneration": {"nom": "Régénération", "emoji": "💚", "description": "Soigne 8% des PV max de l'équipe après chaque victoire"},
    "instinct_predateur": {"nom": "Instinct Prédateur", "emoji": "⚡", "description": "Ton Pokémon agit toujours en premier"},
    "amulette_trouble": {"nom": "Amulette du Trouble", "emoji": "🌀", "description": "-10% de précision pour les ennemis"},
    "sauvegarde_ultime": {"nom": "Sauvegarde Ultime", "emoji": "✨", "description": "La 1ère fois où toute l'équipe tomberait K.O., un Pokémon survit avec 1 PV"},
}

TYPES_ROOM = ["combat", "elite", "tresor", "repos", "evenement", "recrutement"]
POIDS_ROOM = [0.40, 0.15, 0.15, 0.12, 0.08, 0.10]

EVENEMENTS = [
    {
        "titre": "🕯️ Un autel oublié",
        "texte": "Une aura étrange émane d'un autel de pierre. Le toucher pourrait te renforcer... ou te faire mal.",
        "choix": [("Toucher l'autel (60% renforcer, 40% blessure)", "risque_pv"), ("Continuer sans y toucher", "rien")],
    },
    {
        "titre": "🎁 Une caisse abandonnée",
        "texte": "Une caisse en bois traîne sur le chemin, entrouverte.",
        "choix": [("L'ouvrir", "petit_soin"), ("L'ignorer", "rien")],
    },
    {
        "titre": "🌊 Une source scintillante",
        "texte": "L'eau semble avoir des propriétés curatives.",
        "choix": [("Boire", "soin_moyen"), ("Passer son chemin", "rien")],
    },
]


def _emoji_types_pokemon(pokemon: dict) -> str:
    return " ".join(EMOJI_TYPES.get(t, "") for t in pokemon.get("types", []))


def _attaques_disponibles(pokemon_nom: str) -> list:
    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    if not pokemon:
        return [ATTAQUE_NEUTRE]
    attaques = [ATTAQUE_NEUTRE]
    for t in pokemon.get("types", [])[:2]:
        attaques.extend(MOUVEPOOL_PAR_TYPE.get(t, []))
    return attaques


def _niveau_pour_etage(salle_index: int) -> int:
    return config.ROGUELIKE_NIVEAU_DEPART + salle_index * config.ROGUELIKE_NIVEAU_PAR_ETAGE


def _generer_stats(pokemon_nom: str, niveau: int) -> dict:
    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    return calculer_toutes_stats(pokemon, IV_DEFAUT, niveau)


def _generer_chemin() -> list:
    nb_salles = random.randint(config.ROGUELIKE_NB_SALLES_MIN, config.ROGUELIKE_NB_SALLES_MAX)
    chemin = random.choices(TYPES_ROOM, weights=POIDS_ROOM, k=nb_salles)
    chemin.append("boss")
    return chemin


def _tirer_ennemi(salle_index: int, elite: bool = False, boss: bool = False) -> dict:
    pool = ENNEMIS_FORT if boss else _pool_ennemis_pour_etage(salle_index)
    nom = random.choice(pool)
    niveau = _niveau_pour_etage(salle_index)
    if elite:
        niveau += 3
    if boss:
        niveau += 6
    stats = _generer_stats(nom, niveau)
    pv_max = round(stats["pv"] * (1.3 if boss else 1.15 if elite else 1.0))
    return {"nom": nom, "niveau": niveau, "pv_max": pv_max, "stats": stats}


def _appliquer_degats(attaquant_stats: dict, defenseur_stats: dict, attaque: dict, attaquant_types: list, defenseur_types: list, mult_degats_extra: float = 1.0) -> tuple:
    """Retourne (degats, multi_type, a_touche)."""
    precision = attaque.get("precision", 100)
    if random.random() * 100 > precision:
        return 0, 1.0, False
    multi_type = calculer_multiplicateur_type([attaque["type"]], defenseur_types)
    if multi_type == 0.0:
        return 0, 0.0, True
    stab = 1.5 if attaque["type"] in attaquant_types else 1.0
    variance = random.uniform(0.85, 1.15)
    degats = max(1, round(
        ((2 * 50 / 5 + 2) * attaque["puissance"] * attaquant_stats["attaque"] / defenseur_stats["defense"] / 50 + 2)
        * multi_type * stab * variance * mult_degats_extra
    ))
    return degats, multi_type, True


def _texte_efficacite(multi: float) -> str:
    if multi == 0:
        return "🚫 Ça n'affecte pas la cible !"
    if multi >= 2:
        return "💥 C'est super efficace !"
    if 0 < multi < 1:
        return "❄️ Ce n'est pas très efficace..."
    return ""


class VueRoom(discord.ui.View):
    """Panneau affiché entre deux salles (résultat + bouton Continuer).

    IMPORTANT : après un redémarrage, discord.py réutilise UNE SEULE instance générique de
    cette vue (ré-enregistrée via bot.add_view) pour TOUS les fils de run déjà ouverts —
    self.run_id ne serait donc valable que pour la run créée dans la session en cours.
    Chaque run vivant dans son PROPRE fil dédié, on retrouve la bonne run via
    interaction.channel.id plutôt que via self.run_id, ce qui rend l'instance valable
    pour n'importe quel fil."""

    def __init__(self, run_id: int | None = None):
        super().__init__(timeout=None)
        self.run_id = run_id  # utile seulement juste après la création (même session)

    @discord.ui.button(label="Continuer", emoji="➡️", style=discord.ButtonStyle.primary, custom_id="pokewild:roguelike_continuer")
    async def continuer(self, interaction: discord.Interaction, button: discord.ui.Button):
        run = database.obtenir_run_roguelike_par_thread(interaction.channel.id)
        if run is None or run["joueur_id"] != interaction.user.id:
            await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
            return
        await interaction.response.defer()
        await avancer_salle(interaction.client, run["id"])


class VueEvenement(discord.ui.View):
    def __init__(self, run_id: int, evenement: dict):
        super().__init__(timeout=None)
        self.run_id = run_id
        self.evenement = evenement
        for label, effet in evenement["choix"]:
            bouton = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            bouton.callback = self._creer_callback(effet)
            self.add_item(bouton)

    def _creer_callback(self, effet: str):
        async def callback(interaction: discord.Interaction):
            run = database.obtenir_run_roguelike(self.run_id)
            if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
                await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
                return
            await interaction.response.defer()
            texte = _resoudre_effet_evenement(self.run_id, effet)
            embed = discord.Embed(title=self.evenement["titre"], description=texte, color=discord.Color.purple())
            vue = VueRoom(self.run_id)
            await interaction.message.edit(embed=embed, view=vue)
        return callback


class VueRecrutement(discord.ui.View):
    """Salle de recrutement : 3 candidats aléatoires, le joueur en choisit UN pour
    rejoindre son équipe (jusqu'à config.ROGUELIKE_TAILLE_EQUIPE_MAX)."""

    def __init__(self, run_id: int, candidats: list, salle_index: int):
        super().__init__(timeout=None)
        self.run_id = run_id
        self.salle_index = salle_index
        for nom in candidats:
            bouton = discord.ui.Button(label=nom, emoji="🔹", style=discord.ButtonStyle.success)
            bouton.callback = self._creer_callback(nom)
            self.add_item(bouton)

    def _creer_callback(self, nom: str):
        async def callback(interaction: discord.Interaction):
            run = database.obtenir_run_roguelike(self.run_id)
            if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
                await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
                return
            await interaction.response.defer()
            niveau = _niveau_pour_etage(self.salle_index)
            stats = _generer_stats(nom, niveau)
            database.ajouter_membre_equipe_roguelike(self.run_id, nom, niveau, stats["pv"])
            embed = discord.Embed(
                title="🧭 Nouveau coéquipier !",
                description=f"**{nom}** (Niv. {niveau}) rejoint ton équipe !",
                color=discord.Color.teal(),
            )
            await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))
        return callback


class VueChoixRelique(discord.ui.View):
    def __init__(self, run_id: int, options: list):
        super().__init__(timeout=None)
        self.run_id = run_id
        for relique_id in options:
            info = RELIQUES[relique_id]
            bouton = discord.ui.Button(label=f"{info['nom']}", emoji=info["emoji"], style=discord.ButtonStyle.success)
            bouton.callback = self._creer_callback(relique_id)
            self.add_item(bouton)

    def _creer_callback(self, relique_id: str):
        async def callback(interaction: discord.Interaction):
            run = database.obtenir_run_roguelike(self.run_id)
            if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
                await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
                return
            await interaction.response.defer()
            database.ajouter_relique_roguelike(self.run_id, relique_id)
            if relique_id == "carapace_solide":
                for mon in database.obtenir_equipe_roguelike(self.run_id):
                    nouveau_max = round(mon["pv_max"] * 1.2)
                    conn = database.get_connexion()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE roguelike_equipe SET pv_max = ?, pv_actuels = pv_actuels + ? WHERE run_id = ? AND position = ?",
                        (nouveau_max, nouveau_max - mon["pv_max"], self.run_id, mon["position"]),
                    )
                    conn.commit()
                    conn.close()
            info = RELIQUES[relique_id]
            embed = discord.Embed(
                title=f"{info['emoji']} Relique obtenue : {info['nom']}",
                description=info["description"],
                color=discord.Color.gold(),
            )
            vue = VueRoom(self.run_id)
            await interaction.message.edit(embed=embed, view=vue)
        return callback


class VueCombatRoguelike(discord.ui.View):
    """Même remarque que VueRoom : run retrouvée via le fil, pas via self.run_id, pour
    rester valable après un redémarrage."""

    def __init__(self, run_id: int | None = None):
        super().__init__(timeout=None)
        self.run_id = run_id

    @discord.ui.button(label="Attaquer", emoji="⚔️", style=discord.ButtonStyle.danger, custom_id="pokewild:roguelike_attaquer")
    async def attaquer(self, interaction: discord.Interaction, button: discord.ui.Button):
        run = database.obtenir_run_roguelike_par_thread(interaction.channel.id)
        if run is None or run["joueur_id"] != interaction.user.id:
            await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
            return
        run_id = run["id"]
        combat = database.obtenir_combat_roguelike(run_id)
        if combat is None:
            await interaction.response.send_message("Aucun combat en cours.", ephemeral=True)
            return
        equipe = database.obtenir_equipe_roguelike(run_id)
        actif = next((m for m in equipe if m["position"] == combat["actif_position"]), None)
        if actif is None or actif["pv_actuels"] <= 0:
            await interaction.response.send_message("Ton Pokémon actif est K.O. !", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=f"{a['nom']} — {a['puissance']} pcs", value=str(i), emoji=EMOJI_TYPES.get(a["type"]))
            for i, a in enumerate(_attaques_disponibles(actif["pokemon_nom"]))
        ]
        select = discord.ui.Select(placeholder="Choisis ton attaque…", options=options)

        async def on_select(inter: discord.Interaction):
            await inter.response.defer()
            index = int(select.values[0])
            attaque = _attaques_disponibles(actif["pokemon_nom"])[index]
            await resoudre_tour_roguelike(inter.client, run_id, attaque)

        select.callback = on_select
        vue = discord.ui.View(timeout=60)
        vue.add_item(select)
        await interaction.response.send_message("Quelle attaque ?", view=vue, ephemeral=True)


def construire_embed_run(run_id: int) -> discord.Embed:
    import json as json_module

    run = database.obtenir_run_roguelike(run_id)
    equipe = database.obtenir_equipe_roguelike(run_id)
    reliques = json_module.loads(run["reliques"])
    salle_index = run["salle_index"]
    embed = discord.Embed(
        title=f"🗺️ Roguelike — Salle {salle_index + 1}",
        color=discord.Color.dark_purple(),
    )
    lignes_equipe = []
    for mon in equipe:
        etat = "💀" if mon["pv_actuels"] <= 0 else f"{mon['pv_actuels']}/{mon['pv_max']} PV"
        lignes_equipe.append(f"**{mon['pokemon_nom']}** (Niv. {mon['niveau']}) — {etat}")
    embed.add_field(name="Équipe", value="\n".join(lignes_equipe), inline=False)
    if reliques:
        texte_reliques = " • ".join(f"{RELIQUES[r]['emoji']} {RELIQUES[r]['nom']}" for r in reliques)
        embed.add_field(name="Reliques", value=texte_reliques, inline=False)
    return embed


async def _supprimer_fil_apres_delai(thread, delai: int):
    import asyncio

    await asyncio.sleep(delai)
    try:
        await thread.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


def _resoudre_effet_evenement(run_id: int, effet: str) -> str:
    equipe = database.obtenir_equipe_roguelike(run_id)
    vivants = [m for m in equipe if m["pv_actuels"] > 0]
    if effet == "rien":
        return "Tu poursuis ta route sans rien faire de particulier."
    if effet == "petit_soin":
        database.soigner_equipe_roguelike(run_id, 0.15)
        return "🎁 La caisse contenait des baies ! Ton équipe récupère un peu de PV (+15%)."
    if effet == "soin_moyen":
        database.soigner_equipe_roguelike(run_id, 0.30)
        return "🌊 L'eau te revigore ! Ton équipe récupère des PV (+30%)."
    if effet == "risque_pv":
        if random.random() < 0.6 and vivants:
            cible = random.choice(vivants)
            database.definir_pv_roguelike(run_id, cible["position"], min(cible["pv_max"], cible["pv_actuels"] + round(cible["pv_max"] * 0.35)))
            return f"✨ L'autel renforce **{cible['pokemon_nom']}** ! (+35% PV)"
        elif vivants:
            cible = random.choice(vivants)
            degats = round(cible["pv_max"] * 0.2)
            database.definir_pv_roguelike(run_id, cible["position"], cible["pv_actuels"] - degats)
            return f"⚡ L'autel te punit ! **{cible['pokemon_nom']}** perd {degats} PV."
        return "Rien ne se passe."
    return "Rien ne se passe."


class VueChoixStarter(discord.ui.View):
    """1er écran d'une run : 6 candidats aléatoires, le joueur en choisit UN seul comme
    starter — le reste de l'équipe se construira via les salles de recrutement."""

    def __init__(self, run_id: int, candidats: list):
        super().__init__(timeout=600)
        self.run_id = run_id
        options = [discord.SelectOption(label=nom, emoji="🔹") for nom in candidats]
        select = discord.ui.Select(placeholder="Choisis ton starter…", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        run = database.obtenir_run_roguelike(self.run_id)
        if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
            await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
            return
        nom = interaction.data["values"][0]
        niveau = config.ROGUELIKE_NIVEAU_DEPART
        stats = _generer_stats(nom, niveau)
        database.ajouter_membre_equipe_roguelike(self.run_id, nom, niveau, stats["pv"])

        await interaction.response.defer()
        embed = construire_embed_run(self.run_id)
        chemin = __import__("json").loads(run["chemin"])
        embed.description = (
            f"**{nom}** rejoint l'aventure ! **{len(chemin)} salles** t'attendent, dont un boss final.\n"
            f"Tu pourras recruter jusqu'à {config.ROGUELIKE_TAILLE_EQUIPE_MAX} Pokémon en cours de route "
            f"(salles 🧭 Recrutement).\n"
            f"⚠️ Mini-jeu indépendant : aucune récompense liée à ton profil PokéWild — juste le plaisir "
            f"(et un classement du meilleur étage atteint)."
        )
        message = await interaction.message.edit(content=None, embed=embed, view=VueRoom(self.run_id))
        database.definir_message_run_roguelike(self.run_id, interaction.channel.id, interaction.message.id)


async def lancer_run(bot, interaction: discord.Interaction):
    """Point d'entrée de la commande /roguelike."""
    run_existante = database.obtenir_run_roguelike_actif(interaction.user.id)
    if run_existante is not None:
        await interaction.response.send_message(
            "❌ Tu as déjà une run en cours ! Continue-la dans son fil, ou abandonne-la avant d'en relancer une nouvelle.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    chemin = _generer_chemin()
    run_id = database.creer_run_roguelike(interaction.user.id, chemin)

    channel = bot.get_channel(config.CHANNEL_ROGUELIKE_ID)
    if channel is None:
        await interaction.followup.send("⚠️ Le salon roguelike est introuvable (config.CHANNEL_ROGUELIKE_ID).", ephemeral=True)
        database.terminer_run_roguelike(run_id)
        return

    try:
        thread = await channel.create_thread(
            name=f"🗺️ Run de {interaction.user.display_name}"[:100],
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(interaction.user)

        candidats = random.sample(STARTER_POOL, 6)
        embed = discord.Embed(
            title="🗺️ Roguelike — Choisis ton starter !",
            description="Sélectionne le Pokémon avec lequel tu vas commencer l'aventure :\n\n" + "\n".join(f"🔹 {n}" for n in candidats),
            color=discord.Color.dark_purple(),
        )
        message = await thread.send(content=interaction.user.mention, embed=embed, view=VueChoixStarter(run_id, candidats))
        database.definir_message_run_roguelike(run_id, thread.id, message.id)
        await interaction.followup.send(f"✅ Run lancée dans {thread.mention} !", ephemeral=True)
    except Exception as e:
        # Filet de sécurité indispensable : sans ça, la moindre exception après la
        # création de la run (fil, embed, envoi du message...) laissait l'interaction
        # bloquée sur "PokéWild réfléchit..." pour toujours (aucun followup jamais
        # envoyé) ET la run restait "active" en base sans fil ni message associé —
        # bloquant tout nouveau /roguelike avec "tu as déjà une run en cours" sans
        # qu'il y ait quoi que ce soit à reprendre. On nettoie systématiquement la run
        # ET on informe toujours le joueur, quelle que soit l'erreur rencontrée.
        import traceback

        print(f"⚠️ Erreur lors de la création d'une run roguelike (run {run_id}) :")
        traceback.print_exc()
        database.terminer_run_roguelike(run_id)
        try:
            await interaction.followup.send(
                "❌ Une erreur est survenue pendant la création de ta run — réessaie avec `/roguelike` "
                "(rien n'a été bloqué, tu peux relancer tout de suite).",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass


async def avancer_salle(bot, run_id: int):
    run = database.obtenir_run_roguelike(run_id)
    if run is None or not run["actif"]:
        return
    import json as json_module

    chemin = json_module.loads(run["chemin"])
    nouvel_index = database.avancer_salle_roguelike(run_id)

    if nouvel_index >= len(chemin):
        await _conclure_run(bot, run_id, victoire=True)
        return

    type_salle = chemin[nouvel_index]
    thread = bot.get_channel(int(run["thread_id"])) or await bot.fetch_channel(int(run["thread_id"]))

    try:
        if type_salle in ("combat", "elite", "boss"):
            await _demarrer_combat(bot, thread, run_id, nouvel_index, elite=(type_salle == "elite"), boss=(type_salle == "boss"))
        elif type_salle == "repos":
            database.soigner_equipe_roguelike(run_id, config.ROGUELIKE_SOIN_REPOS_POURCENT)
            embed = discord.Embed(
                title=f"🏕️ Salle {nouvel_index + 1} — Un lieu de repos",
                description=f"Ton équipe récupère {round(config.ROGUELIKE_SOIN_REPOS_POURCENT * 100)}% de ses PV.",
                color=discord.Color.green(),
            )
            embed2 = construire_embed_run(run_id)
            await thread.send(embeds=[embed, embed2], view=VueRoom(run_id))
        elif type_salle == "evenement":
            evenement = random.choice(EVENEMENTS)
            embed = discord.Embed(title=evenement["titre"], description=evenement["texte"], color=discord.Color.purple())
            await thread.send(embed=embed, view=VueEvenement(run_id, evenement))
        elif type_salle == "tresor":
            run_actuelle = database.obtenir_run_roguelike(run_id)
            deja = json_module.loads(run_actuelle["reliques"])
            disponibles = [r for r in RELIQUES if r not in deja]
            if not disponibles:
                database.soigner_equipe_roguelike(run_id, 0.25)
                embed = discord.Embed(
                    title=f"💰 Salle {nouvel_index + 1} — Trésor",
                    description="Tu as déjà toutes les reliques disponibles ! Un peu de soin à la place (+25% PV).",
                    color=discord.Color.gold(),
                )
                await thread.send(embed=embed, view=VueRoom(run_id))
            else:
                options = random.sample(disponibles, min(3, len(disponibles)))
                embed = discord.Embed(
                    title=f"💰 Salle {nouvel_index + 1} — Trésor",
                    description="Choisis une relique :\n\n" + "\n".join(
                        f"{RELIQUES[r]['emoji']} **{RELIQUES[r]['nom']}** — {RELIQUES[r]['description']}" for r in options
                    ),
                    color=discord.Color.gold(),
                )
                await thread.send(embed=embed, view=VueChoixRelique(run_id, options))
        elif type_salle == "recrutement":
            equipe_actuelle = database.obtenir_equipe_roguelike(run_id)
            if len(equipe_actuelle) >= config.ROGUELIKE_TAILLE_EQUIPE_MAX:
                database.soigner_equipe_roguelike(run_id, 0.20)
                embed = discord.Embed(
                    title=f"🧭 Salle {nouvel_index + 1} — Recrutement",
                    description=f"Ton équipe est déjà au complet ({config.ROGUELIKE_TAILLE_EQUIPE_MAX} Pokémon) ! Un peu de soin à la place (+20% PV).",
                    color=discord.Color.teal(),
                )
                await thread.send(embed=embed, view=VueRoom(run_id))
            else:
                deja_dans_equipe = {m["pokemon_nom"] for m in equipe_actuelle}
                candidats_dispo = [n for n in (ENNEMIS_FAIBLE + ENNEMIS_MOYEN) if n not in deja_dans_equipe]
                options = random.sample(candidats_dispo, min(3, len(candidats_dispo)))
                embed = discord.Embed(
                    title=f"🧭 Salle {nouvel_index + 1} — Recrutement",
                    description="Un Pokémon errant souhaite se joindre à toi. Lequel recrutes-tu ?\n\n"
                    + "\n".join(f"🔹 {n}" for n in options),
                    color=discord.Color.teal(),
                )
                await thread.send(embed=embed, view=VueRecrutement(run_id, options, nouvel_index))
    except Exception as e:
        # Même filet de sécurité que lancer_run : une erreur ici (fil supprimé, sprite
        # indisponible, etc.) ne doit jamais laisser la run silencieusement bloquée — le
        # joueur voit au moins un message d'erreur dans son fil plutôt que rien du tout.
        import traceback

        print(f"⚠️ Erreur en avançant la run roguelike {run_id} (salle {nouvel_index}) :")
        traceback.print_exc()
        try:
            await thread.send(
                "⚠️ Une erreur est survenue en générant cette salle. Utilise `/roguelike-abandonner` "
                "puis relance une nouvelle run si le problème persiste."
            )
        except discord.HTTPException:
            pass


async def _demarrer_combat(bot, thread, run_id: int, salle_index: int, elite: bool = False, boss: bool = False):
    ennemi = _tirer_ennemi(salle_index, elite=elite, boss=boss)
    equipe = database.obtenir_equipe_roguelike(run_id)
    premier_vivant = next((m for m in equipe if m["pv_actuels"] > 0), None)
    if premier_vivant is None:
        await _conclure_run(bot, run_id, victoire=False)
        return

    database.creer_combat_roguelike(run_id, ennemi["nom"], ennemi["niveau"], ennemi["pv_max"], premier_vivant["position"])

    pokemon = obtenir_pokemon_par_nom(ennemi["nom"])
    prefixe = "👑 BOSS" if boss else ("⭐ Élite" if elite else "⚔️")
    embed = discord.Embed(
        title=f"{prefixe} — {ennemi['nom']} sauvage ! (Niv. {ennemi['niveau']})",
        description=f"{_emoji_types_pokemon(pokemon)}\n❤️ {ennemi['pv_max']}/{ennemi['pv_max']} PV",
        color=discord.Color.red() if not boss else discord.Color.dark_gold(),
    )
    url_sprite = sprite_pokemon(pokemon)
    if url_sprite:
        embed.set_thumbnail(url=url_sprite)
    embed2 = construire_embed_run(run_id)
    await thread.send(embeds=[embed, embed2], view=VueCombatRoguelike(run_id))


async def resoudre_tour_roguelike(bot, run_id: int, attaque: dict):
    run = database.obtenir_run_roguelike(run_id)
    if run is None or not run["actif"]:
        return
    combat = database.obtenir_combat_roguelike(run_id)
    if combat is None:
        return

    equipe = database.obtenir_equipe_roguelike(run_id)
    actif = next((m for m in equipe if m["position"] == combat["actif_position"]), None)
    if actif is None or actif["pv_actuels"] <= 0:
        return

    import json as json_module
    reliques = json_module.loads(run["reliques"])
    mult_degats = 1.15 if "griffes_aiguisees" in reliques else 1.0
    mult_reduction = 0.85 if "peau_de_fer" in reliques else 1.0
    malus_precision_ennemi = 10 if "amulette_trouble" in reliques else 0
    joueur_premier = "instinct_predateur" in reliques

    stats_joueur = _generer_stats(actif["pokemon_nom"], actif["niveau"])
    stats_ennemi = _generer_stats(combat["ennemi_nom"], combat["ennemi_niveau"])
    pokemon_joueur = obtenir_pokemon_par_nom(actif["pokemon_nom"])
    pokemon_ennemi = obtenir_pokemon_par_nom(combat["ennemi_nom"])
    types_joueur = pokemon_joueur["types"] if pokemon_joueur else ["normal"]
    types_ennemi = pokemon_ennemi["types"] if pokemon_ennemi else ["normal"]

    log = []
    pv_ennemi = combat["ennemi_pv_actuels"]
    pv_joueur = actif["pv_actuels"]

    async def _tour_joueur():
        nonlocal pv_ennemi
        degats, multi, touche = _appliquer_degats(stats_joueur, stats_ennemi, attaque, types_joueur, types_ennemi, mult_degats)
        if not touche:
            log.append(f"**{actif['pokemon_nom']}** utilise {attaque['nom']}... et rate !")
            return
        pv_ennemi = max(0, pv_ennemi - degats)
        database.definir_pv_ennemi_roguelike(run_id, pv_ennemi)
        log.append(f"**{actif['pokemon_nom']}** utilise {attaque['nom']} → -{degats} PV")
        efficacite = _texte_efficacite(multi)
        if efficacite:
            log.append(f"  {efficacite}")
        if pv_ennemi <= 0:
            log.append(f"  💀 **{combat['ennemi_nom']}** est vaincu !")

    async def _tour_ennemi():
        nonlocal pv_joueur
        attaques_ennemi = _attaques_disponibles(combat["ennemi_nom"])
        attaque_ennemi = random.choice(attaques_ennemi)
        precision_ajustee = max(10, (attaque_ennemi.get("precision", 100)) - malus_precision_ennemi)
        attaque_ennemi_ajustee = dict(attaque_ennemi, precision=precision_ajustee)
        degats, multi, touche = _appliquer_degats(stats_ennemi, stats_joueur, attaque_ennemi_ajustee, types_ennemi, types_joueur, mult_reduction)
        if not touche:
            log.append(f"**{combat['ennemi_nom']}** utilise {attaque_ennemi['nom']}... et rate !")
            return
        pv_joueur = max(0, pv_joueur - degats)
        database.definir_pv_roguelike(run_id, actif["position"], pv_joueur)
        log.append(f"**{combat['ennemi_nom']}** utilise {attaque_ennemi['nom']} → -{degats} PV")
        efficacite = _texte_efficacite(multi)
        if efficacite:
            log.append(f"  {efficacite}")
        if pv_joueur <= 0:
            log.append(f"  💀 **{actif['pokemon_nom']}** est K.O. !")

    if joueur_premier:
        await _tour_joueur()
        if pv_ennemi > 0:
            await _tour_ennemi()
    else:
        # Vitesse simplifiée : le plus rapide agit en premier.
        if stats_joueur["vitesse"] >= stats_ennemi["vitesse"]:
            await _tour_joueur()
            if pv_ennemi > 0:
                await _tour_ennemi()
        else:
            await _tour_ennemi()
            if pv_joueur > 0:
                await _tour_joueur()

    thread = bot.get_channel(int(run["thread_id"])) or await bot.fetch_channel(int(run["thread_id"]))

    # --- Victoire sur ce combat ---
    if pv_ennemi <= 0:
        database.terminer_combat_roguelike(run_id)
        if "regeneration" in reliques:
            database.soigner_equipe_roguelike(run_id, 0.08)
        embed = discord.Embed(title="🏆 Victoire !", description="\n".join(log), color=discord.Color.green())
        await thread.send(embed=embed, view=VueRoom(run_id))
        return

    # --- Le Pokémon actif est tombé : passer au suivant, ou fin de run ---
    if pv_joueur <= 0:
        equipe_maj = database.obtenir_equipe_roguelike(run_id)
        vivants = [m for m in equipe_maj if m["pv_actuels"] > 0]
        if not vivants and "sauvegarde_ultime" in reliques:
            # Relique à usage unique : un Pokémon survit avec 1 PV, puis se consomme.
            survivant = equipe_maj[0]
            database.definir_pv_roguelike(run_id, survivant["position"], 1)
            reliques.remove("sauvegarde_ultime")
            conn = database.get_connexion()
            cur = conn.cursor()
            cur.execute("UPDATE roguelike_runs SET reliques = ? WHERE id = ?", (json_module.dumps(reliques), run_id))
            conn.commit()
            conn.close()
            log.append(f"✨ **Sauvegarde Ultime** se déclenche — **{survivant['pokemon_nom']}** s'accroche avec 1 PV !")
            vivants = [survivant]

        if not vivants:
            embed = discord.Embed(title="💀 Équipe anéantie...", description="\n".join(log), color=discord.Color.dark_red())
            await thread.send(embed=embed)
            await _conclure_run(bot, run_id, victoire=False)
            return

        nouveau_actif = vivants[0]
        database.definir_actif_position_roguelike(run_id, nouveau_actif["position"])
        log.append(f"🔁 **{nouveau_actif['pokemon_nom']}** entre au combat !")
        embed = discord.Embed(title="⚔️ Combat en cours", description="\n".join(log), color=discord.Color.orange())
        embed.add_field(name=f"{combat['ennemi_nom']}", value=f"❤️ {pv_ennemi}/{combat['ennemi_pv_max']} PV", inline=False)
        await thread.send(embed=embed, view=VueCombatRoguelike(run_id))
        return

    # --- Combat continue normalement ---
    embed = discord.Embed(title="⚔️ Combat en cours", description="\n".join(log), color=discord.Color.orange())
    embed.add_field(name=f"{actif['pokemon_nom']}", value=f"❤️ {pv_joueur}/{actif['pv_max']} PV", inline=True)
    embed.add_field(name=f"{combat['ennemi_nom']}", value=f"❤️ {pv_ennemi}/{combat['ennemi_pv_max']} PV", inline=True)
    await thread.send(embed=embed, view=VueCombatRoguelike(run_id))


async def _conclure_run(bot, run_id: int, victoire: bool):
    run = database.obtenir_run_roguelike(run_id)
    etage_atteint = run["salle_index"]
    database.terminer_run_roguelike(run_id)
    nouveau_record = database.enregistrer_record_roguelike(run["joueur_id"], etage_atteint)

    thread = bot.get_channel(int(run["thread_id"])) or await bot.fetch_channel(int(run["thread_id"]))
    if victoire:
        embed = discord.Embed(
            title="🎉 Run terminée avec succès !",
            description=f"Tu as vaincu le boss final et terminé la run à la salle {etage_atteint} !",
            color=discord.Color.gold(),
        )
    else:
        embed = discord.Embed(
            title="💀 Fin de la run",
            description=f"Ton équipe est tombée à la salle {etage_atteint + 1}. Direction la case départ !",
            color=discord.Color.dark_red(),
        )
    if nouveau_record:
        embed.add_field(name="🏆 Nouveau record personnel !", value=f"Meilleur étage atteint : {etage_atteint}", inline=False)
    embed.set_footer(text=f"🗑️ Ce fil sera supprimé automatiquement dans {DELAI_SUPPRESSION_FIL // 60} minutes.")
    await thread.send(embed=embed)
    bot.loop.create_task(_supprimer_fil_apres_delai(thread, DELAI_SUPPRESSION_FIL))


async def abandonner_run(interaction: discord.Interaction):
    """Point d'entrée de la commande /roguelike-abandonner."""
    run = database.obtenir_run_roguelike_actif(interaction.user.id)
    if run is None:
        await interaction.response.send_message("Tu n'as aucune run en cours.", ephemeral=True)
        return
    database.terminer_run_roguelike(run["id"])
    await interaction.response.send_message("✅ Run abandonnée — tu peux en relancer une nouvelle avec `/roguelike`.", ephemeral=True)


async def afficher_classement(interaction: discord.Interaction):
    """Point d'entrée de la commande /roguelike-classement."""
    lignes = database.classement_roguelike(10)
    if not lignes:
        await interaction.response.send_message("Aucune run terminée pour l'instant !", ephemeral=True)
        return
    texte = "\n".join(f"**{i+1}.** <@{row['joueur_id']}> — salle {row['meilleur_etage']}" for i, row in enumerate(lignes))
    embed = discord.Embed(title="🏆 Classement Roguelike — meilleur étage atteint", description=texte, color=discord.Color.dark_purple())
    await interaction.response.send_message(embed=embed)
