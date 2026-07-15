import random

# Chaque météo peut booster certains types de Pokémon à l'apparition, et/ou la chance de shiny.
# "poids" détermine la probabilité relative d'être tirée quand un événement météo se déclenche.

METEOS = [
    {
        "nom": "Pluie",
        "emoji": "🌧️",
        "types_boostes": {"eau": 2.0},
        "multiplicateur_shiny": 1.0,
        "duree_min_minutes": 15,
        "duree_max_minutes": 20,
        "poids": 30,
    },
    {
        "nom": "Orage",
        "emoji": "⛈️",
        "types_boostes": {"electrik": 2.0},
        "multiplicateur_shiny": 1.0,
        "duree_min_minutes": 15,
        "duree_max_minutes": 20,
        "poids": 20,
    },
    {
        "nom": "Neige",
        "emoji": "❄️",
        "types_boostes": {"glace": 2.0},
        "multiplicateur_shiny": 1.0,
        "duree_min_minutes": 15,
        "duree_max_minutes": 20,
        "poids": 20,
    },
    {
        "nom": "Brouillard",
        "emoji": "🌫️",
        "types_boostes": {"spectre": 2.0, "poison": 1.5},
        "multiplicateur_shiny": 1.0,
        "duree_min_minutes": 15,
        "duree_max_minutes": 20,
        "poids": 20,
    },
    {
        "nom": "Aurore Scintillante",
        "emoji": "🌈",
        "types_boostes": {},
        "multiplicateur_shiny": 5.0,
        "duree_min_minutes": 5,
        "duree_max_minutes": 10,
        "poids": 5,  # rare, exprès pour que ce soit un événement excitant
    },
]

# Probabilité qu'un événement météo se déclenche à chaque vérification périodique
PROBABILITE_DECLENCHEMENT = 0.25


def choisir_meteo_aleatoire() -> dict:
    """Tire une météo au hasard parmi celles disponibles, pondérée par 'poids'."""
    pool = []
    for meteo in METEOS:
        pool.extend([meteo] * meteo["poids"])
    return random.choice(pool)
