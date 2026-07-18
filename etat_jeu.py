"""État global de la météo en cours. Modifié par main.py, lu par views.py."""

meteo_actuelle = None  # None = beau temps (neutre), sinon un dict issu de meteo.METEOS
heure_de_pointe_pokestop_active = False  # modifié par boucle_evenement_pokestop dans main.py


def obtenir_multiplicateurs_types() -> dict:
    if meteo_actuelle is None:
        return {}
    return meteo_actuelle.get("types_boostes", {})


def obtenir_multiplicateur_shiny() -> float:
    if meteo_actuelle is None:
        return 1.0
    return meteo_actuelle.get("multiplicateur_shiny", 1.0)
