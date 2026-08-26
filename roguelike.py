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
    evoluer_si_possible,
    obtenir_pokemon_par_nom,
    sprite_pokemon,
)

DELAI_SUPPRESSION_FIL = 300  # 5 min après la fin d'une run (victoire ou mort), comme ailleurs

# Pool des Pokémon "génériques" pouvant être tirés comme starter — volontairement varié en
# types et modeste en puissance (pas de légendaires) pour que chaque run parte sur un pied
# d'égalité, peu importe le vrai Pokédex du joueur.
# Les 27 vrais starters de départ des jeux principaux, 3 par génération (gens 1 à 9) —
# remplace l'ancien pool générique STARTER_POOL, qui servait AUSSI (par erreur de
# conception, corrigée ici) de vivier pour les ennemis faibles de début de run — voir
# ENNEMIS_FAIBLE ci-dessous, maintenant sa propre liste indépendante et inchangée.
STARTERS_9_GENERATIONS = [
    "Bulbizarre", "Salamèche", "Carapuce",  # Gen 1
    "Germignon", "Héricendre", "Kaiminus",  # Gen 2
    "Arcko", "Poussifeu", "Gobou",  # Gen 3
    "Tortipouss", "Ouisticram", "Tiplouf",  # Gen 4
    "Vipélierre", "Gruikui", "Moustillon",  # Gen 5
    "Marisson", "Feunnec", "Grenousse",  # Gen 6
    "Brindibou", "Flamiaou", "Otaquin",  # Gen 7
    "Ouistempo", "Flambino", "Larméléon",  # Gen 8
    "Poussacha", "Chochodile", "Coiffeton",  # Gen 9
]

# --- Pools d'ennemis ÉCHELONNÉS par palier de progression ---
# La "rareté" du Pokédex principal reflète la fréquence de CAPTURE, pas sa force réelle
# en combat — piocher au hasard parmi "commun/peu_commun/rare" pouvait donc sortir un
# Pokémon bien plus costaud que prévu dès l'étage 2 (ex: un Bétochef, aux stats de
# combat élevées malgré une rareté "commune"), écrasant une équipe encore faible sans
# que ce soit un choix injuste du joueur. On utilise donc des pools CURATÉS, dont la
# force monte avec la progression, plutôt que la rareté brute.
ENNEMIS_FAIBLE = [
    "Salamèche", "Carapuce", "Bulbizarre", "Racaillou", "Nosferapti", "Ponyta",
    "Machoc", "Magicarpe", "Abo", "Chenipan", "Rondoudou", "Goupix", "Psykokwak",
    "Tadmorv", "Griknot", "Mimigal", "Coxy", "Motisma",
]
ENNEMIS_MOYEN = [
    "Roucoups", "Arbok", "Dardargnan", "Nosferalto", "Feunard",
    "Simiabraz", "Colhomard", "Galopa", "Akwakwak", "Papilusion", "Fouinar", "Pharamp",
]
ENNEMIS_FORT = [
    "Ronflex", "Léviator", "Dracaufeu", "Tortank", "Florizarre", "Alakazam",
    "Mackogneur", "Ptéra", "Scarabrute", "Tyranocif",
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
    "sol":      [{"nom": "Jet de Roc", "type": "sol", "puissance": 55, "precision": 100}, {"nom": "Séisme éclair", "type": "sol", "puissance": 80, "precision": 95}],
    "vol":      [{"nom": "Tornade", "type": "vol", "puissance": 55, "precision": 100}, {"nom": "Ouragan éclair", "type": "vol", "puissance": 80, "precision": 90}],
    "psy":      [{"nom": "Choc Mental", "type": "psy", "puissance": 55, "precision": 100}, {"nom": "Psyko", "type": "psy", "puissance": 80, "precision": 95}],
    "insecte":  [{"nom": "Dard-Choc", "type": "insecte", "puissance": 55, "precision": 100}, {"nom": "Lame-Cutter", "type": "insecte", "puissance": 80, "precision": 95}],
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

TYPES_ROOM = [
    "combat", "elite", "tresor", "repos", "evenement", "recrutement",
    "marchand", "mutation", "rencontre_scintillante", "carrefour", "arene_clandestine", "chambre_evolution",
    "centre_pokemon", "dresseur",
]
POIDS_ROOM = [0.20, 0.10, 0.10, 0.06, 0.06, 0.07, 0.08, 0.05, 0.05, 0.06, 0.04, 0.03, 0.05, 0.05]

NOMS_DRESSEURS = [
    "Dresseur Hugo", "Dresseuse Lina", "Randonneur Max", "Camping-Pro Éva",
    "Skateur Théo", "Cadette Mila", "Ouvrier Sam", "Nageuse Zoé",
    "Pêcheur Léo", "Botaniste Anna", "Cadet Noé", "Skieuse Iris",
]

# --- Types de salle utilisables comme options d'un Carrefour (exclut "carrefour"
# lui-même pour éviter une chaîne de carrefours en rafale, et "elite"/"boss" pour ne
# jamais laisser le joueur choisir sciemment un combat difficile sans le savoir à
# l'avance de la même façon qu'un tirage aléatoire classique) ---
TYPES_CARREFOUR = ["combat", "tresor", "repos", "evenement", "recrutement", "marchand", "mutation", "centre_pokemon"]

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
    """Retourne au maximum 4 attaques (comme dans les vrais jeux) — ATTAQUE_NEUTRE
    systématiquement en premier, puis une sélection parmi celles des 1-2 types du
    Pokémon. Bug corrigé : avant, un Pokémon bi-type cumulait TOUTES les attaques des
    deux pools de type sans aucun plafond (un Pokémon Plante/Poison pouvait se retrouver
    avec 5 attaques ou plus au lieu de 4 maximum).

    Sélection STABLE par espèce (graine = nom du Pokémon, pas le générateur aléatoire
    global) — sinon, comme cette fonction est rappelée à chaque nouveau combat (chaque
    salle), un même Pokémon se retrouvait avec des attaques DIFFÉRENTES d'un combat à
    l'autre, rendant toute planification stratégique impossible pour le joueur. Reste
    varié ENTRE espèces différentes (chaque nom donne une graine différente), juste
    fixe pour UNE espèce donnée."""
    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    if not pokemon:
        return [ATTAQUE_NEUTRE]
    pool_types = []
    for t in pokemon.get("types", [])[:2]:
        pool_types.extend(MOUVEPOOL_PAR_TYPE.get(t, []))
    nb_a_tirer = min(3, len(pool_types))
    return [ATTAQUE_NEUTRE] + random.Random(pokemon_nom).sample(pool_types, nb_a_tirer)


def _niveau_pour_etage(salle_index: int) -> int:
    """Plafonné à 100 (comme les vrais jeux) — important depuis que le roguelike ne
    s'arrête plus après un boss (voir avancer_salle) : sans plafond, cette formule
    grandirait indéfiniment sur une run assez longue."""
    return min(100, config.ROGUELIKE_NIVEAU_DEPART + salle_index * config.ROGUELIKE_NIVEAU_PAR_ETAGE)


def _generer_stats(pokemon_nom: str, niveau: int) -> dict:
    pokemon = obtenir_pokemon_par_nom(pokemon_nom)
    return calculer_toutes_stats(pokemon, IV_DEFAUT, niveau)


def _appliquer_bonus_mutation(stats: dict, bonus_mutation: float) -> dict:
    """Multiplie toutes les stats (PV inclus) par le bonus de mutation d'un membre —
    voir database.definir_mutation_membre_roguelike (salle Autel de Mutation). bonus=1.0
    (valeur par défaut, aucune mutation) laisse les stats parfaitement inchangées."""
    if bonus_mutation == 1.0:
        return stats
    return {cle: max(1, round(valeur * bonus_mutation)) for cle, valeur in stats.items()}


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
    rejoindre son équipe (jusqu'à config.ROGUELIKE_TAILLE_EQUIPE_MAX) — ou passe son
    tour s'il préfère garder son équipe actuelle telle quelle."""

    def __init__(self, run_id: int, candidats: list, salle_index: int):
        super().__init__(timeout=None)
        self.run_id = run_id
        self.salle_index = salle_index
        for nom in candidats:
            bouton = discord.ui.Button(label=nom, emoji="🔹", style=discord.ButtonStyle.success)
            bouton.callback = self._creer_callback(nom)
            self.add_item(bouton)
        bouton_passer = discord.ui.Button(label="Passer", emoji="➡️", style=discord.ButtonStyle.secondary)
        bouton_passer.callback = self._passer
        self.add_item(bouton_passer)

    async def _passer(self, interaction: discord.Interaction):
        run = database.obtenir_run_roguelike(self.run_id)
        if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
            await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
            return
        await interaction.response.defer()
        embed = discord.Embed(
            title="🧭 Recrutement décliné",
            description="Tu gardes ton équipe actuelle telle quelle.",
            color=discord.Color.teal(),
        )
        await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))

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


def _accorder_relique(run_id: int, relique_id: str) -> discord.Embed:
    """Octroie une relique (effet immédiat pour carapace_solide inclus) et retourne
    l'embed de confirmation — factorisé pour être réutilisé par VueChoixRelique (Trésor)
    ET VueMarchand (relique aléatoire)."""
    database.ajouter_relique_roguelike(run_id, relique_id)
    if relique_id == "carapace_solide":
        for mon in database.obtenir_equipe_roguelike(run_id):
            nouveau_max = round(mon["pv_max"] * 1.2)
            conn = database.get_connexion()
            cur = conn.cursor()
            cur.execute(
                "UPDATE roguelike_equipe SET pv_max = ?, pv_actuels = pv_actuels + ? WHERE run_id = ? AND position = ?",
                (nouveau_max, nouveau_max - mon["pv_max"], run_id, mon["position"]),
            )
            conn.commit()
            conn.close()
    info = RELIQUES[relique_id]
    return discord.Embed(
        title=f"{info['emoji']} Relique obtenue : {info['nom']}",
        description=info["description"],
        color=discord.Color.gold(),
    )


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
            embed = _accorder_relique(self.run_id, relique_id)
            vue = VueRoom(self.run_id)
            await interaction.message.edit(embed=embed, view=vue)
        return callback


class VueMarchand(discord.ui.View):
    """Salle marchand : le roguelike ne génère aucun vrai Poké Dollar (mode autonome),
    donc pas de vraie boutique — un choix entre un soin généreux ou une relique tirée au
    sort (même mécanique que le Trésor, juste sans laisser le joueur choisir LAQUELLE)."""

    def __init__(self, run_id: int):
        super().__init__(timeout=None)
        self.run_id = run_id

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        run = database.obtenir_run_roguelike(self.run_id)
        if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
            await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Soin (+40% PV)", emoji="💊", style=discord.ButtonStyle.success)
    async def soin(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.defer()
        database.soigner_equipe_roguelike(self.run_id, 0.40)
        embed = discord.Embed(
            title="🛍️ Marchand", description="Ton équipe récupère 40% de ses PV.", color=discord.Color.dark_gold()
        )
        await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))

    @discord.ui.button(label="Relique aléatoire", emoji="💎", style=discord.ButtonStyle.primary)
    async def relique(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.defer()
        run = database.obtenir_run_roguelike(self.run_id)
        import json as json_module
        deja = json_module.loads(run["reliques"])
        disponibles = [r for r in RELIQUES if r not in deja]
        if not disponibles:
            embed = discord.Embed(
                title="🛍️ Marchand", description="Tu as déjà toutes les reliques disponibles ! Rien à t'offrir ici.",
                color=discord.Color.dark_gold(),
            )
        else:
            embed = _accorder_relique(self.run_id, random.choice(disponibles))
        await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))


class VueMutation(discord.ui.View):
    """Autel de Mutation : choisis UN membre d'équipe (parmi ceux vivants et pas déjà
    mutés) pour +20% à toutes ses stats, PV inclus, pour le reste de la run."""

    def __init__(self, run_id: int, candidats: list):
        super().__init__(timeout=None)
        self.run_id = run_id
        for membre in candidats:
            bouton = discord.ui.Button(
                label=f"{membre['pokemon_nom']} (Niv. {membre['niveau']})", emoji="🔮", style=discord.ButtonStyle.success
            )
            bouton.callback = self._creer_callback(membre["position"], membre["pokemon_nom"])
            self.add_item(bouton)

    def _creer_callback(self, position: int, nom: str):
        async def callback(interaction: discord.Interaction):
            run = database.obtenir_run_roguelike(self.run_id)
            if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
                await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
                return
            await interaction.response.defer()

            database.definir_mutation_membre_roguelike(self.run_id, position, 1.20)
            membre = next(m for m in database.obtenir_equipe_roguelike(self.run_id) if m["position"] == position)
            nouvelles_stats = _appliquer_bonus_mutation(_generer_stats(nom, membre["niveau"]), 1.20)
            ratio_pv = membre["pv_actuels"] / membre["pv_max"] if membre["pv_max"] > 0 else 0
            nouveaux_pv_actuels = max(1, round(nouvelles_stats["pv"] * ratio_pv))
            database.mettre_a_jour_niveau_membre_roguelike(
                self.run_id, position, membre["niveau"], nouvelles_stats["pv"], nouveaux_pv_actuels
            )

            embed = discord.Embed(
                title="🔮 Mutation accomplie !",
                description=f"**{nom}** reçoit +20% à toutes ses statistiques pour le reste de la run !",
                color=discord.Color.dark_purple(),
            )
            await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))
        return callback


class VueCarrefour(discord.ui.View):
    """Carrefour : le joueur choisit lui-même le TYPE de la salle suivante (parmi 3
    options tirées de TYPES_CARREFOUR), plutôt que de le subir par tirage aléatoire —
    remplace directement la case correspondante du chemin stocké en base."""

    NOMS_LISIBLES = {
        "combat": "⚔️ Combat", "tresor": "💰 Trésor", "repos": "🏕️ Repos",
        "evenement": "❓ Événement", "recrutement": "🧭 Recrutement",
        "marchand": "🛍️ Marchand", "mutation": "🔮 Autel de Mutation",
    }

    def __init__(self, run_id: int, options: list, salle_index: int):
        super().__init__(timeout=None)
        self.run_id = run_id
        self.salle_index = salle_index
        for type_salle in options:
            bouton = discord.ui.Button(label=self.NOMS_LISIBLES.get(type_salle, type_salle), style=discord.ButtonStyle.primary)
            bouton.callback = self._creer_callback(type_salle)
            self.add_item(bouton)

    def _creer_callback(self, type_choisi: str):
        async def callback(interaction: discord.Interaction):
            run = database.obtenir_run_roguelike(self.run_id)
            if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
                await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
                return
            await interaction.response.defer()

            import json as json_module
            chemin = json_module.loads(run["chemin"])
            index_suivant = self.salle_index + 1
            if index_suivant < len(chemin):
                chemin[index_suivant] = type_choisi
            else:
                # Le carrefour était la toute dernière salle générée avant un boss déjà
                # placé plus loin (rare mais possible selon la génération aléatoire) —
                # insère la salle choisie juste avant plutôt que de dépasser le chemin.
                chemin.insert(index_suivant, type_choisi)
            database.mettre_a_jour_chemin_roguelike(self.run_id, chemin)

            embed = discord.Embed(
                title="🧭 Chemin choisi !",
                description=f"Tu t'engages vers : **{self.NOMS_LISIBLES.get(type_choisi, type_choisi)}**",
                color=discord.Color.blurple(),
            )
            await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))
        return callback


class VueChambreEvolution(discord.ui.View):
    """Chambre d'Évolution : +5 niveaux immédiats à UN membre choisi, évolution
    déclenchée sur le champ si le seuil est atteint (réutilise evoluer_si_possible,
    même logique que la montée de niveau normale entre 2 salles)."""

    def __init__(self, run_id: int, candidats: list, salle_index: int):
        super().__init__(timeout=None)
        self.run_id = run_id
        self.salle_index = salle_index
        for membre in candidats:
            bouton = discord.ui.Button(
                label=f"{membre['pokemon_nom']} (Niv. {membre['niveau']})", emoji="🧬", style=discord.ButtonStyle.success
            )
            bouton.callback = self._creer_callback(membre["position"])
            self.add_item(bouton)

    def _creer_callback(self, position: int):
        async def callback(interaction: discord.Interaction):
            run = database.obtenir_run_roguelike(self.run_id)
            if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
                await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
                return
            await interaction.response.defer()

            membre = next(m for m in database.obtenir_equipe_roguelike(self.run_id) if m["position"] == position)
            nouveau_niveau = min(100, membre["niveau"] + 5)
            nom_final, chaine = evoluer_si_possible(membre["pokemon_nom"], nouveau_niveau)
            nouvelles_stats = _appliquer_bonus_mutation(_generer_stats(nom_final, nouveau_niveau), membre["bonus_mutation"])
            ratio_pv = membre["pv_actuels"] / membre["pv_max"] if membre["pv_max"] > 0 else 0
            nouveaux_pv_actuels = max(1, round(nouvelles_stats["pv"] * ratio_pv))
            database.mettre_a_jour_niveau_membre_roguelike(
                self.run_id, position, nouveau_niveau, nouvelles_stats["pv"], nouveaux_pv_actuels,
                pokemon_nom=nom_final if chaine else None,
            )

            texte = f"**{membre['pokemon_nom']}** grimpe à Niv. {nouveau_niveau} !"
            if chaine:
                texte += f"\n✨ Il évolue en **{nom_final}** !"
            embed = discord.Embed(title="🧬 Chambre d'Évolution", description=texte, color=discord.Color.teal())
            await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))
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

        attaques_disponibles = _attaques_disponibles(actif["pokemon_nom"])
        options = [
            discord.SelectOption(label=f"{a['nom']} — {a['puissance']} pcs", value=str(i), emoji=EMOJI_TYPES.get(a["type"]))
            for i, a in enumerate(attaques_disponibles)
        ]
        select = discord.ui.Select(placeholder="Choisis ton attaque…", options=options)

        async def on_select(inter: discord.Interaction):
            await inter.response.defer()
            index = int(select.values[0])
            attaque = attaques_disponibles[index]
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
        embed.description = (
            f"**{nom}** rejoint l'aventure ! Le chemin s'étend indéfiniment, salle après "
            f"salle, avec un boss à intervalles réguliers — jusqu'à ce que ton équipe "
            f"tombe. Combien d'étages peux-tu atteindre ?\n"
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

        candidats = random.sample(STARTERS_9_GENERATIONS, 6)
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

    # La run ne s'arrête plus après le boss — dès qu'on dépasse la fin du chemin ET que
    # la dernière salle passée était bien un boss (toujours vrai, boss est systématiquement
    # ajouté en dernière position d'un segment, voir _generer_chemin), on ÉTEND le chemin
    # avec un nouveau segment plutôt que de conclure. Le roguelike est donc maintenant
    # "sans fin" — seule une défaite en combat termine la run (voir plus bas dans le
    # fichier, résolution de combat perdu).
    if nouvel_index >= len(chemin):
        if chemin and chemin[-1] == "boss":
            chemin = chemin + _generer_chemin()
            database.mettre_a_jour_chemin_roguelike(run_id, chemin)
        else:
            # Filet de sécurité : ne devrait plus jamais arriver (boss toujours en fin de
            # segment), mais on garde ce cas pour ne jamais planter si la génération du
            # chemin change un jour.
            await _conclure_run(bot, run_id, victoire=True)
            return

    # Fait monter l'équipe du joueur au niveau attendu de CETTE salle — sans ça, l'équipe
    # restait figée au niveau où elle a rejoint (souvent le niveau de départ) alors que
    # les ennemis montent en niveau à chaque salle via _niveau_pour_etage, créant un
    # déséquilibre de plus en plus injuste au fil de la run. On ne fait JAMAIS redescendre
    # un niveau (un membre recruté en avance sur la courbe reste tel quel tant que la
    # formule ne l'a pas rattrapé), et on préserve le POURCENTAGE de vie actuel plutôt que
    # de soigner gratuitement à chaque montée.
    #
    # bonus_boss : +1 niveau PERMANENT par boss déjà vaincu (compte tous les "boss" déjà
    # traversés dans le chemin, y compris celui qui vient d'être battu si c'est lui qui a
    # déclenché l'extension ci-dessus) — combiné aux +2 normaux de la progression par
    # salle, ça donne bien le ressenti "+3 au lieu de +2" pour la transition qui suit
    # immédiatement un boss, et ce bonus reste acquis pour toujours sur les salles
    # suivantes (jamais retiré), contrairement au niveau brut qui, lui, ne redescend
    # jamais non plus grâce au garde-fou existant plus bas dans la boucle.
    bonus_boss = chemin[:nouvel_index].count("boss")
    niveau_attendu = min(100, _niveau_pour_etage(nouvel_index) + bonus_boss)
    annonces_evolution = []
    for membre in database.obtenir_equipe_roguelike(run_id):
        if membre["niveau"] >= niveau_attendu:
            continue
        # Applique la chaîne d'évolution AVANT de calculer les nouvelles stats — sans ça,
        # les PV/attaque seraient calculés sur l'ancienne espèce alors que le Pokémon a
        # déjà changé de forme à ce niveau (voir evoluer_si_possible, gère aussi le cas
        # d'un saut de plusieurs niveaux qui franchit 2 seuils d'évolution d'un coup).
        nom_final, chaine = evoluer_si_possible(membre["pokemon_nom"], niveau_attendu)
        if chaine:
            annonces_evolution.append(f"✨ **{membre['pokemon_nom']}** a évolué en **{nom_final}** !")

        nouvelles_stats = _appliquer_bonus_mutation(_generer_stats(nom_final, niveau_attendu), membre["bonus_mutation"])
        ratio_pv = membre["pv_actuels"] / membre["pv_max"] if membre["pv_max"] > 0 else 0
        nouveaux_pv_actuels = max(1, round(nouvelles_stats["pv"] * ratio_pv)) if membre["pv_actuels"] > 0 else 0
        database.mettre_a_jour_niveau_membre_roguelike(
            run_id, membre["position"], niveau_attendu, nouvelles_stats["pv"], nouveaux_pv_actuels,
            pokemon_nom=nom_final if chaine else None,
        )

    if annonces_evolution:
        thread_pour_annonce = bot.get_channel(int(run["thread_id"])) or await bot.fetch_channel(int(run["thread_id"]))
        try:
            await thread_pour_annonce.send("\n".join(annonces_evolution))
        except discord.HTTPException:
            pass  # purement informatif, ne doit jamais bloquer la suite de la run

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
        elif type_salle == "marchand":
            embed = discord.Embed(
                title=f"🛍️ Salle {nouvel_index + 1} — Marchand",
                description="Un marchand itinérant te propose un choix :",
                color=discord.Color.dark_gold(),
            )
            await thread.send(embed=embed, view=VueMarchand(run_id))
        elif type_salle == "mutation":
            equipe_actuelle = database.obtenir_equipe_roguelike(run_id)
            candidats = [m for m in equipe_actuelle if m["bonus_mutation"] == 1.0 and m["pv_actuels"] > 0]
            if not candidats:
                database.soigner_equipe_roguelike(run_id, 0.20)
                embed = discord.Embed(
                    title=f"🔮 Salle {nouvel_index + 1} — Autel de Mutation",
                    description="Tous tes Pokémon vivants ont déjà été mutés ! Un peu de soin à la place (+20% PV).",
                    color=discord.Color.dark_purple(),
                )
                await thread.send(embed=embed, view=VueRoom(run_id))
            else:
                embed = discord.Embed(
                    title=f"🔮 Salle {nouvel_index + 1} — Autel de Mutation",
                    description=(
                        "Un Cristal de Mutation instable flotte au-dessus d'un autel. Choisis "
                        "UN Pokémon de ton équipe pour recevoir **+20% à toutes ses "
                        "statistiques, PV inclus, pour le reste de la run** (irréversible, "
                        "et ne peut être appliqué qu'une seule fois par Pokémon) :"
                    ),
                    color=discord.Color.dark_purple(),
                )
                await thread.send(embed=embed, view=VueMutation(run_id, candidats))
        elif type_salle == "rencontre_scintillante":
            await _demarrer_rencontre_scintillante(bot, thread, run_id, nouvel_index)
        elif type_salle == "carrefour":
            options = random.sample(TYPES_CARREFOUR, 3)
            noms_lisibles = {
                "combat": "⚔️ Combat", "tresor": "💰 Trésor", "repos": "🏕️ Repos",
                "evenement": "❓ Événement", "recrutement": "🧭 Recrutement",
                "marchand": "🛍️ Marchand", "mutation": "🔮 Autel de Mutation",
            }
            embed = discord.Embed(
                title=f"🧭 Salle {nouvel_index + 1} — Carrefour",
                description="Trois chemins s'offrent à toi. Lequel empruntes-tu ?\n\n"
                + "\n".join(f"🔹 {noms_lisibles.get(t, t)}" for t in options),
                color=discord.Color.blurple(),
            )
            await thread.send(embed=embed, view=VueCarrefour(run_id, options, nouvel_index))
        elif type_salle == "arene_clandestine":
            await _demarrer_arene_clandestine(bot, thread, run_id, nouvel_index)
        elif type_salle == "chambre_evolution":
            equipe_actuelle = database.obtenir_equipe_roguelike(run_id)
            candidats = [m for m in equipe_actuelle if m["pv_actuels"] > 0]
            embed = discord.Embed(
                title=f"🧬 Salle {nouvel_index + 1} — Chambre d'Évolution",
                description=(
                    "Une pierre d'évolution unique repose ici. Choisis UN Pokémon pour lui "
                    "accorder immédiatement **+5 niveaux** (évolue sur le champ si le seuil "
                    "est atteint) :"
                ),
                color=discord.Color.teal(),
            )
            await thread.send(embed=embed, view=VueChambreEvolution(run_id, candidats, nouvel_index))
        elif type_salle == "centre_pokemon":
            database.soigner_equipe_roguelike(run_id, 1.0)
            embed = discord.Embed(
                title=f"🏥 Salle {nouvel_index + 1} — Centre Pokémon",
                description="Ton équipe est soignée **intégralement** — tous tes Pokémon retrouvent 100% de leurs PV, **K.O. inclus** : ils sont ranimés comme neufs.",
                color=discord.Color.green(),
            )
            embed2 = construire_embed_run(run_id)
            await thread.send(embeds=[embed, embed2], view=VueRoom(run_id))
        elif type_salle == "dresseur":
            await _demarrer_combat_dresseur(bot, thread, run_id, nouvel_index)
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


async def _demarrer_rencontre_scintillante(bot, thread, run_id: int, salle_index: int):
    embed = discord.Embed(
        title=f"✨ Salle {salle_index + 1} — Rencontre scintillante",
        description=(
            "Un Pokémon aux couleurs éclatantes te fixe, nettement plus fort que la "
            "normale de cet étage. L'affronter est risqué, mais une victoire garantit "
            "une relique bonus. Tu peux aussi repartir sans prendre aucun risque."
        ),
        color=discord.Color.gold(),
    )
    await thread.send(embed=embed, view=VueChoixRencontreScintillante(run_id, salle_index))


class VueChoixRencontreScintillante(discord.ui.View):
    def __init__(self, run_id: int, salle_index: int):
        super().__init__(timeout=None)
        self.run_id = run_id
        self.salle_index = salle_index

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        run = database.obtenir_run_roguelike(self.run_id)
        if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
            await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Combattre", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def combattre(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.defer()
        embed = discord.Embed(title="✨ Tu choisis de combattre !", color=discord.Color.gold())
        await interaction.message.edit(embed=embed, view=None)
        await _demarrer_combat(
            interaction.client, interaction.channel, self.run_id, self.salle_index,
            elite=True, rencontre_speciale=True,
        )

    @discord.ui.button(label="Fuir", emoji="🏃", style=discord.ButtonStyle.secondary)
    async def fuir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._verifier(interaction):
            return
        await interaction.response.defer()
        embed = discord.Embed(
            title="🏃 Tu t'éloignes prudemment...",
            description="Aucun risque, aucune récompense — le Pokémon scintillant disparaît dans les fourrés.",
            color=discord.Color.light_grey(),
        )
        await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))


async def _demarrer_combat_dresseur(bot, thread, run_id: int, salle_index: int):
    """Combat de Dresseur : 2 Pokémon (3 passé la salle 7) enchaînés SANS interruption
    ni soin entre chacun — une vraie difficulté distincte d'un combat sauvage classique,
    où l'adversaire n'a qu'un seul Pokémon à gérer."""
    nom_dresseur = random.choice(NOMS_DRESSEURS)
    taille_equipe = 2 if salle_index <= 7 else 3
    pool = _pool_ennemis_pour_etage(salle_index)
    noms_equipe = random.sample(pool, min(taille_equipe, len(pool)))
    niveau = _niveau_pour_etage(salle_index)

    equipe = database.obtenir_equipe_roguelike(run_id)
    premier_vivant = next((m for m in equipe if m["pv_actuels"] > 0), None)
    if premier_vivant is None:
        await _conclure_run(bot, run_id, victoire=False)
        return

    premieres_stats = _generer_stats(noms_equipe[0], niveau)
    reste = [{"nom": nom, "niveau": niveau, "pv_max": _generer_stats(nom, niveau)["pv"]} for nom in noms_equipe[1:]]

    database.creer_combat_roguelike(
        run_id, noms_equipe[0], niveau, premieres_stats["pv"], premier_vivant["position"],
        equipe_restante=reste, est_dresseur=True,
    )

    pokemon = obtenir_pokemon_par_nom(noms_equipe[0])
    embed = discord.Embed(
        title=f"🥊 {nom_dresseur} veut se battre ! ({len(noms_equipe)} Pokémon)",
        description=(
            f"Envoie **{noms_equipe[0]}** ! (Niv. {niveau})\n{_emoji_types_pokemon(pokemon)}\n"
            f"❤️ {premieres_stats['pv']}/{premieres_stats['pv']} PV"
        ),
        color=discord.Color.orange(),
    )
    url_sprite = sprite_pokemon(pokemon)
    if url_sprite:
        embed.set_thumbnail(url=url_sprite)
    embed2 = construire_embed_run(run_id)
    await thread.send(embeds=[embed, embed2], view=VueCombatRoguelike(run_id))


async def _demarrer_arene_clandestine(bot, thread, run_id: int, salle_index: int):
    pool = _pool_ennemis_pour_etage(salle_index)
    nom_a, nom_b = random.sample(pool, 2) if len(pool) >= 2 else (pool[0], pool[0])
    embed = discord.Embed(
        title=f"🎤 Salle {salle_index + 1} — Arène clandestine",
        description=(
            f"**{nom_a}** affronte **{nom_b}** dans un combat organisé, sans risque pour "
            f"toi. Parie sur le vainqueur — s'il te reste une place, il rejoindra ton "
            f"équipe."
        ),
        color=discord.Color.dark_teal(),
    )
    await thread.send(embed=embed, view=VueAreneClandestine(run_id, nom_a, nom_b, salle_index))


class VueAreneClandestine(discord.ui.View):
    def __init__(self, run_id: int, nom_a: str, nom_b: str, salle_index: int):
        super().__init__(timeout=None)
        self.run_id = run_id
        self.nom_a = nom_a
        self.nom_b = nom_b
        self.salle_index = salle_index
        for nom in (nom_a, nom_b):
            bouton = discord.ui.Button(label=f"Parier sur {nom}", emoji="🎲", style=discord.ButtonStyle.primary)
            bouton.callback = self._creer_callback(nom)
            self.add_item(bouton)

    def _creer_callback(self, pari: str):
        async def callback(interaction: discord.Interaction):
            run = database.obtenir_run_roguelike(self.run_id)
            if run is None or not run["actif"] or run["joueur_id"] != interaction.user.id:
                await interaction.response.send_message("Cette run n'est plus active.", ephemeral=True)
                return
            await interaction.response.defer()

            vainqueur = random.choice([self.nom_a, self.nom_b])
            equipe_actuelle = database.obtenir_equipe_roguelike(self.run_id)

            if pari == vainqueur and len(equipe_actuelle) < config.ROGUELIKE_TAILLE_EQUIPE_MAX:
                niveau = _niveau_pour_etage(self.salle_index)
                stats = _generer_stats(vainqueur, niveau)
                database.ajouter_membre_equipe_roguelike(self.run_id, vainqueur, niveau, stats["pv"])
                texte = f"🎉 **{vainqueur}** l'emporte, exactement comme tu l'avais parié ! Il rejoint ton équipe."
            elif pari == vainqueur:
                texte = f"🎉 **{vainqueur}** l'emporte comme prévu, mais ton équipe est déjà complète — il s'éloigne."
            else:
                texte = f"😬 **{vainqueur}** l'emporte finalement, pas **{pari}**. Ton pari ne paie pas cette fois."

            embed = discord.Embed(title="🎤 Arène clandestine — Résultat", description=texte, color=discord.Color.dark_teal())
            await interaction.message.edit(embed=embed, view=VueRoom(self.run_id))
        return callback


async def _demarrer_combat(
    bot, thread, run_id: int, salle_index: int, elite: bool = False, boss: bool = False,
    rencontre_speciale: bool = False,
):
    ennemi = _tirer_ennemi(salle_index, elite=elite, boss=boss)
    equipe = database.obtenir_equipe_roguelike(run_id)
    premier_vivant = next((m for m in equipe if m["pv_actuels"] > 0), None)
    if premier_vivant is None:
        await _conclure_run(bot, run_id, victoire=False)
        return

    database.creer_combat_roguelike(
        run_id, ennemi["nom"], ennemi["niveau"], ennemi["pv_max"], premier_vivant["position"],
        est_rencontre_speciale=rencontre_speciale,
    )

    pokemon = obtenir_pokemon_par_nom(ennemi["nom"])
    prefixe = "👑 BOSS" if boss else ("✨ Scintillant" if rencontre_speciale else ("⭐ Élite" if elite else "⚔️"))
    embed = discord.Embed(
        title=f"{prefixe} — {ennemi['nom']} sauvage ! (Niv. {ennemi['niveau']})",
        description=f"{_emoji_types_pokemon(pokemon)}\n❤️ {ennemi['pv_max']}/{ennemi['pv_max']} PV",
        color=discord.Color.gold() if rencontre_speciale else (discord.Color.red() if not boss else discord.Color.dark_gold()),
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

    stats_joueur = _appliquer_bonus_mutation(_generer_stats(actif["pokemon_nom"], actif["niveau"]), actif["bonus_mutation"])
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
        equipe_restante = json_module.loads(combat["equipe_restante"]) if combat["equipe_restante"] else []
        if equipe_restante:
            # Combat de Dresseur : enchaîne le Pokémon suivant SANS terminer le combat ni
            # laisser le joueur se soigner entre deux — précisément ce qui rend un
            # dresseur plus difficile qu'un combat sauvage classique (un seul adversaire).
            prochain = equipe_restante.pop(0)
            database.avancer_ennemi_suivant_roguelike(
                run_id, prochain["nom"], prochain["niveau"], prochain["pv_max"], equipe_restante
            )
            pokemon_suivant = obtenir_pokemon_par_nom(prochain["nom"])
            embed_victoire_partielle = discord.Embed(
                title="🥊 Pokémon vaincu !", description="\n".join(log), color=discord.Color.orange()
            )
            embed_suivant = discord.Embed(
                title=f"Le dresseur envoie **{prochain['nom']}** ! (Niv. {prochain['niveau']})",
                description=f"{_emoji_types_pokemon(pokemon_suivant)}\n❤️ {prochain['pv_max']}/{prochain['pv_max']} PV",
                color=discord.Color.orange(),
            )
            url_sprite_suivant = sprite_pokemon(pokemon_suivant)
            if url_sprite_suivant:
                embed_suivant.set_thumbnail(url=url_sprite_suivant)
            await thread.send(embed=embed_victoire_partielle)
            await thread.send(embed=embed_suivant, view=VueCombatRoguelike(run_id))
            return

        database.terminer_combat_roguelike(run_id)
        if "regeneration" in reliques:
            database.soigner_equipe_roguelike(run_id, 0.08)
        if combat["est_dresseur"]:
            database.soigner_equipe_roguelike(run_id, 0.15)  # petite récompense d'avoir vaincu toute l'équipe
        embed = discord.Embed(title="🏆 Victoire !", description="\n".join(log), color=discord.Color.green())
        vue_suivante = VueRoom(run_id)
        if combat["est_rencontre_speciale"]:
            disponibles = [r for r in RELIQUES if r not in reliques]
            if disponibles:
                embed_relique = _accorder_relique(run_id, random.choice(disponibles))
                await thread.send(embed=embed)
                await thread.send(embed=embed_relique, view=vue_suivante)
                return
        await thread.send(embed=embed, view=vue_suivante)
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
