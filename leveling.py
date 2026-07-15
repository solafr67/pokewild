def xp_cumulee_pour_niveau(niveau: int) -> int:
    """XP totale nécessaire pour ATTEINDRE ce niveau (niveau 1 = 0 XP)."""
    return 50 * (niveau - 1) * niveau


def barre_progression(actuel: int, requis: int, longueur: int = 10) -> str:
    """Petite barre de progression texte (🟦/⬛), utilisée pour l'XP notamment."""
    ratio = max(0, min(1, actuel / requis)) if requis else 0
    rempli = round(longueur * ratio)
    return "🟦" * rempli + "⬛" * (longueur - rempli)


def niveau_depuis_xp(xp_total: int) -> int:
    niveau = 1
    while xp_cumulee_pour_niveau(niveau + 1) <= xp_total:
        niveau += 1
    return niveau


def progression_niveau(xp_total: int):
    """Retourne (niveau_actuel, xp_dans_le_niveau, xp_requise_pour_ce_niveau)."""
    niveau = niveau_depuis_xp(xp_total)
    xp_debut_niveau = xp_cumulee_pour_niveau(niveau)
    xp_fin_niveau = xp_cumulee_pour_niveau(niveau + 1)
    return niveau, xp_total - xp_debut_niveau, xp_fin_niveau - xp_debut_niveau


def _ball_pour_palier(palier: int) -> str:
    if palier <= 3:
        return "pokeball"
    if palier <= 6:
        return "superball"
    return "hyperball"


def gagner_xp(user_id: int, montant: int):
    """Ajoute de l'XP à un joueur (avec boost XP actif éventuel) et récompense tout
    palier de 5 niveaux franchi (ex: niveau 5, 10, 15...). Retourne (niveau_avant,
    niveau_apres, recompenses_paliers), où recompenses_paliers est une liste de
    (palier, dollars, ball_type) — généralement vide ou avec un seul élément, mais peut
    en contenir plusieurs si un gros gain d'XP fait franchir plusieurs paliers d'un coup."""
    import database

    montant = round(montant * database.multiplicateur_boost(user_id, "xp"))

    xp_avant = database.obtenir_xp(user_id)
    niveau_avant, _, _ = progression_niveau(xp_avant)

    xp_apres = database.ajouter_xp(user_id, montant)
    niveau_apres, _, _ = progression_niveau(xp_apres)

    recompenses_paliers = []
    for niveau in range(niveau_avant + 1, niveau_apres + 1):
        if niveau % 5 == 0:
            palier = niveau // 5
            dollars = palier * 20
            ball_type = _ball_pour_palier(palier)
            database.ajouter_poke_dollars(user_id, dollars)
            database.ajouter_balls(user_id, ball_type, 1)
            recompenses_paliers.append((palier, dollars, ball_type))

    return niveau_avant, niveau_apres, recompenses_paliers
