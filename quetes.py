"""Catalogue des quêtes : journalières, hebdomadaires, et accomplissements à paliers.

Les quêtes journalières/hebdomadaires sont suivies via des compteurs qui se
réinitialisent à période fixe (voir database.py). Les accomplissements sont calculés
directement depuis les données réelles du joueur (captures, XP, victoires...) — pas de
compteur séparé à maintenir, donc aucun risque de désynchronisation.
"""

QUETES_JOUR = [
    {"id": "jour_capture", "nom": "Capturer 3 Pokémon", "evenement": "capture", "cible": 3, "emoji": "🎯"},
    {"id": "jour_pokestop", "nom": "Faire tourner le PokéStop", "evenement": "pokestop", "cible": 1, "emoji": "🔵"},
    {"id": "jour_raid", "nom": "Gagner 1 raid", "evenement": "raid_victoire", "cible": 1, "emoji": "⚔️"},
    {"id": "jour_pvp", "nom": "Gagner 1 combat PvP", "evenement": "pvp_victoire", "cible": 1, "emoji": "🥊"},
    {"id": "jour_pve", "nom": "Battre 1 dresseur", "evenement": "pve_victoire", "cible": 1, "emoji": "🥾"},
]

QUETES_SEMAINE = [
    {"id": "semaine_raids", "nom": "Gagner 5 raids", "evenement": "raid_victoire", "cible": 5, "emoji": "⚔️"},
    {"id": "semaine_pvp", "nom": "Gagner 3 combats PvP", "evenement": "pvp_victoire", "cible": 3, "emoji": "🥊"},
    {"id": "semaine_legendaire", "nom": "Capturer un Légendaire", "evenement": "capture", "cible": 1, "emoji": "🟠",
     "filtre": {"rarete": "legendaire"}},
    {"id": "semaine_exploration", "nom": "Récupérer 3 explorations", "evenement": "exploration_collectee", "cible": 3, "emoji": "🗺️"},
]

QUETES_PAR_ID = {q["id"]: q for q in QUETES_JOUR + QUETES_SEMAINE}

# --- Accomplissements à paliers ---
# valeur = fonction qui calcule la progression actuelle du joueur pour cette catégorie,
# à partir des stats déjà stockées ailleurs (pas de compteur dédié à maintenir).
ACCOMPLISSEMENTS = {
    "shiny": {
        "nom_categorie": "Chasseur de Chromatiques",
        "emoji": "🌟",
        "paliers": [1, 3, 10, 25],
    },
    "legendaire": {
        "nom_categorie": "Légende en devenir",
        "emoji": "👑",
        "paliers": [1, 3, 6, 10],
    },
    "pvp": {
        "nom_categorie": "Champion",
        "emoji": "🥊",
        "paliers": [1, 10, 50, 100],
    },
    "niveau": {
        "nom_categorie": "Vétéran",
        "emoji": "⭐",
        "paliers": [10, 25, 50, 75],
    },
    "pokedex": {
        "nom_categorie": "Collectionneur",
        "emoji": "📖",
        "paliers": [50, 150, 300, 1025],
    },
}

CHIFFRES_ROMAINS = {1: "I", 2: "II", 3: "III", 4: "IV"}


def palier_atteint(categorie: str, valeur_actuelle: int) -> int:
    """Retourne le palier atteint (0 à 4) pour cette valeur dans cette catégorie."""
    paliers = ACCOMPLISSEMENTS[categorie]["paliers"]
    palier = 0
    for i, seuil in enumerate(paliers, start=1):
        if valeur_actuelle >= seuil:
            palier = i
    return palier


def titre_complet(categorie: str, palier: int) -> str:
    """Ex: 'Chasseur de Chromatiques II'."""
    if palier == 0:
        return None
    nom = ACCOMPLISSEMENTS[categorie]["nom_categorie"]
    return f"{nom} {CHIFFRES_ROMAINS[palier]}"
