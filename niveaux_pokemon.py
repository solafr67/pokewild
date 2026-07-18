"""Système de niveau PAR POKÉMON — coexiste avec le PC (qui reste la mesure de
potentiel/IV d'un individu). Seuls les Pokémon de l'équipe de combat active gagnent
de l'XP via les actions du joueur (capture, PokéStop...) ; une équipe vide au moment
de l'action fait perdre cette XP. Le niveau est plafonné selon la rareté de l'espèce
(voir config.NIVEAU_MAX_PAR_RARETE) ; au plafond, plus aucune XP n'est engrangée.
"""

import config
import database
from pokemon_data import obtenir_pokemon_par_nom


def xp_cumulee_pour_niveau(niveau: int) -> int:
    """XP totale nécessaire pour ATTEINDRE ce niveau (niveau 1 = 0 XP)."""
    return config.COEFFICIENT_COURBE_NIVEAU_POKEMON * (niveau - 1) ** 2


def niveau_max_pour_rarete(rarete: str) -> int:
    return config.NIVEAU_MAX_PAR_RARETE.get(rarete, 100)


def niveau_depuis_xp(xp_total: int, niveau_max: int) -> int:
    niveau = 1
    while niveau < niveau_max and xp_cumulee_pour_niveau(niveau + 1) <= xp_total:
        niveau += 1
    return niveau


def progression_niveau(xp_total: int, niveau_max: int):
    """Retourne (niveau_actuel, xp_dans_le_niveau, xp_requise_pour_ce_niveau). Au
    plafond, les deux derniers éléments valent 0 (pas de barre à remplir)."""
    niveau = niveau_depuis_xp(xp_total, niveau_max)
    if niveau >= niveau_max:
        return niveau, 0, 0
    xp_debut_niveau = xp_cumulee_pour_niveau(niveau)
    xp_fin_niveau = xp_cumulee_pour_niveau(niveau + 1)
    return niveau, xp_total - xp_debut_niveau, xp_fin_niveau - xp_debut_niveau


def gagner_xp_equipe(user_id: int, montant: int) -> list:
    """Ajoute `montant` XP à CHAQUE Pokémon de l'équipe de combat active (pas divisé
    entre eux). Un Pokémon déjà à son niveau plafond (selon la rareté de son espèce)
    n'engrange plus rien. Retourne la liste des montées de niveau survenues (dicts avec
    nom/niveau_avant/niveau_apres/niveau_max), pour notifier le joueur."""
    montees = []
    noms_equipe = database.obtenir_equipe_combat(user_id)

    for nom in noms_equipe:
        pokemon = obtenir_pokemon_par_nom(nom)
        if not pokemon:
            continue
        niveau_max = niveau_max_pour_rarete(pokemon["rarete"])

        niveau_avant, xp_avant = database.obtenir_niveau_pokemon(user_id, nom)
        if niveau_avant >= niveau_max:
            continue  # au plafond : plus d'XP ni de récompense bonus

        xp_apres = xp_avant + montant
        niveau_apres = niveau_depuis_xp(xp_apres, niveau_max)

        if niveau_apres >= niveau_max:
            # Au plafond : on n'accumule pas d'XP au-delà de ce qu'il faut pour l'atteindre,
            # il n'y a plus de barre de progression à afficher ensuite.
            niveau_apres = niveau_max
            xp_apres = xp_cumulee_pour_niveau(niveau_max)

        database.definir_niveau_xp_pokemon(user_id, nom, niveau_apres, xp_apres)

        if niveau_apres > niveau_avant:
            montees.append(
                {
                    "nom": nom,
                    "niveau_avant": niveau_avant,
                    "niveau_apres": niveau_apres,
                    "niveau_max": niveau_max,
                }
            )

    return montees


def texte_montees_niveau(montees: list) -> str:
    """Texte prêt à afficher (embed/DM) pour une liste de montées de niveau."""
    lignes = []
    for m in montees:
        plafond_txt = " (niveau MAX !)" if m["niveau_apres"] >= m["niveau_max"] else ""
        lignes.append(f"🆙 **{m['nom']}** passe niveau {m['niveau_avant']} → {m['niveau_apres']}{plafond_txt} !")
    return "\n".join(lignes)
