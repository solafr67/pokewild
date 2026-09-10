"""Sous-module database — domaine économie entre joueurs : échanges (trading) et
marketplace (annonces de vente). Regroupés car les deux déplacent des ressources
entre joueurs et partagent la même dépendance vers le domaine cœur (Poké Dollars).

Dépendance sortante réelle (pas juste get_connexion, vérifié exhaustivement avant
extraction) : obtenir_poke_dollars/ajouter_poke_dollars restent dans
database/__init__.py (domaine cœur, pas encore extrait) — executer_echange et
executer_achat_marketplace y transfèrent réellement des Poké Dollars entre joueurs.
Aucune fonction ailleurs dans database/ n'appelle une fonction de ce fichier."""

import time

from . import ajouter_poke_dollars, get_connexion, obtenir_poke_dollars


def creer_echange(joueur1_id: int, joueur2_id: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO echanges (joueur1_id, joueur2_id, date_creation) VALUES (?, ?, ?)",
        (joueur1_id, joueur2_id, int(time.time())),
    )
    echange_id = cur.lastrowid
    conn.commit()
    conn.close()
    return echange_id


def obtenir_echange(echange_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM echanges WHERE id = ?", (echange_id,))
    row = cur.fetchone()
    conn.close()
    return row


def echange_en_cours_pour_joueur(user_id: int):
    """Retourne l'échange actif d'un joueur, ou None (un seul échange à la fois)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM echanges WHERE actif = 1 AND (joueur1_id = ? OR joueur2_id = ?) LIMIT 1",
        (user_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row


def definir_offre_echange(echange_id: int, proposant_id: int, capture_ids: list, pd: int):
    """Remplace entièrement l'offre d'un joueur (Pokémon + PD) et RÉINITIALISE les deux
    validations — toute modification de l'offre annule les validations précédentes,
    évite qu'un joueur ne modifie discrètement son offre après que l'autre a validé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM echange_pokemon WHERE echange_id = ? AND proposant_id = ?",
        (echange_id, proposant_id),
    )
    for capture_id in capture_ids:
        cur.execute(
            "INSERT INTO echange_pokemon (echange_id, capture_id, proposant_id) VALUES (?, ?, ?)",
            (echange_id, capture_id, proposant_id),
        )

    echange = obtenir_echange(echange_id)
    if echange["joueur1_id"] == proposant_id:
        cur.execute(
            "UPDATE echanges SET joueur1_pd = ?, joueur1_valide = 0, joueur2_valide = 0 WHERE id = ?",
            (pd, echange_id),
        )
    else:
        cur.execute(
            "UPDATE echanges SET joueur2_pd = ?, joueur1_valide = 0, joueur2_valide = 0 WHERE id = ?",
            (pd, echange_id),
        )
    conn.commit()
    conn.close()


def obtenir_offre_echange(echange_id: int, proposant_id: int) -> list:
    """Retourne les captures proposées par ce joueur, avec leurs détails (nom, pc, shiny)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.pokemon_nom, c.pc, c.shiny
        FROM echange_pokemon e
        JOIN captures c ON c.id = e.capture_id
        WHERE e.echange_id = ? AND e.proposant_id = ?
        """,
        (echange_id, proposant_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def definir_objets_offre_echange(echange_id: int, proposant_id: int, objets: dict):
    """Remplace entièrement les objets proposés par ce joueur (objet_cle -> quantite) et
    RÉINITIALISE les deux validations, comme definir_offre_echange pour les Pokémon/PD —
    étape séparée dans l'UI (bouton dédié), donc fonction séparée plutôt que de forcer à
    repasser le même appel que la sélection Pokémon à chaque changement d'objets."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM echange_objets WHERE echange_id = ? AND proposant_id = ?",
        (echange_id, proposant_id),
    )
    for objet_cle, quantite in objets.items():
        if quantite > 0:
            cur.execute(
                "INSERT INTO echange_objets (echange_id, proposant_id, objet_cle, quantite) VALUES (?, ?, ?, ?)",
                (echange_id, proposant_id, objet_cle, quantite),
            )

    echange = obtenir_echange(echange_id)
    colonnes_validation = "joueur1_valide = 0, joueur2_valide = 0"
    cur.execute(f"UPDATE echanges SET {colonnes_validation} WHERE id = ?", (echange_id,))
    conn.commit()
    conn.close()


def obtenir_objets_offre_echange(echange_id: int, proposant_id: int) -> dict:
    """Retourne les objets proposés par ce joueur : {objet_cle: quantite}."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT objet_cle, quantite FROM echange_objets WHERE echange_id = ? AND proposant_id = ?",
        (echange_id, proposant_id),
    )
    resultats = {row["objet_cle"]: row["quantite"] for row in cur.fetchall()}
    conn.close()
    return resultats


def valider_offre_echange(echange_id: int, proposant_id: int) -> bool:
    """Marque ce joueur comme ayant validé l'offre actuelle. Retourne True si les DEUX
    joueurs ont maintenant validé (échange prêt à être exécuté)."""
    conn = get_connexion()
    cur = conn.cursor()
    echange = obtenir_echange(echange_id)
    colonne = "joueur1_valide" if echange["joueur1_id"] == proposant_id else "joueur2_valide"
    cur.execute(f"UPDATE echanges SET {colonne} = 1 WHERE id = ?", (echange_id,))
    conn.commit()

    cur.execute("SELECT joueur1_valide, joueur2_valide FROM echanges WHERE id = ?", (echange_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row["joueur1_valide"] and row["joueur2_valide"])


def annuler_echange(echange_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE echanges SET actif = 0 WHERE id = ?", (echange_id,))
    conn.commit()
    conn.close()


def executer_echange(echange_id: int) -> tuple:
    """Exécute l'échange de façon atomique : re-vérifie que chaque joueur possède
    toujours ce qu'il a proposé (Pokémon ET objets — au cas où sa collection ou son sac
    aurait changé entre-temps), puis transfère Pokémon, objets et PD des deux côtés.
    Retourne (succes, message_erreur)."""
    echange = obtenir_echange(echange_id)
    if echange is None or not echange["actif"]:
        return False, "Cet échange n'est plus actif."

    j1, j2 = echange["joueur1_id"], echange["joueur2_id"]
    offre_j1 = obtenir_offre_echange(echange_id, j1)
    offre_j2 = obtenir_offre_echange(echange_id, j2)
    objets_j1 = obtenir_objets_offre_echange(echange_id, j1)
    objets_j2 = obtenir_objets_offre_echange(echange_id, j2)

    conn = get_connexion()
    cur = conn.cursor()

    # Re-vérification : chaque Pokémon proposé appartient toujours bien à son proposant
    for offre, proposant in ((offre_j1, j1), (offre_j2, j2)):
        for row in offre:
            cur.execute("SELECT user_id FROM captures WHERE id = ?", (row["id"],))
            capture = cur.fetchone()
            if capture is None or capture["user_id"] != proposant:
                conn.close()
                return False, f"Un Pokémon proposé par <@{proposant}> n'est plus disponible (déjà échangé, relâché...)."

    # Re-vérification : chaque objet proposé est toujours en stock, en quantité suffisante
    for objets, proposant in ((objets_j1, j1), (objets_j2, j2)):
        for objet_cle, quantite_requise in objets.items():
            cur.execute(
                "SELECT quantite FROM inventaire_balls WHERE user_id = ? AND ball_type = ?",
                (proposant, objet_cle),
            )
            row = cur.fetchone()
            if row is None or row["quantite"] < quantite_requise:
                conn.close()
                return False, f"<@{proposant}> n'a plus assez d'un objet proposé (utilisé ou dépensé entre-temps)."

    # Re-vérification des soldes
    solde_j1 = obtenir_poke_dollars(j1)
    solde_j2 = obtenir_poke_dollars(j2)

    if solde_j1 < echange["joueur1_pd"]:
        conn.close()
        return False, f"<@{j1}> n'a plus assez de Poké Dollars pour honorer son offre."
    if solde_j2 < echange["joueur2_pd"]:
        conn.close()
        return False, f"<@{j2}> n'a plus assez de Poké Dollars pour honorer son offre."

    # Transfert des Pokémon (changement de propriétaire, id/historique conservés)
    for row in offre_j1:
        cur.execute("UPDATE captures SET user_id = ? WHERE id = ?", (j2, row["id"]))
    for row in offre_j2:
        cur.execute("UPDATE captures SET user_id = ? WHERE id = ?", (j1, row["id"]))

    # Transfert des objets (retire côté proposant, ajoute côté receveur — même table
    # inventaire_balls des deux côtés, upsert si le receveur en avait déjà)
    for objets, proposant, receveur in ((objets_j1, j1, j2), (objets_j2, j2, j1)):
        for objet_cle, quantite in objets.items():
            cur.execute(
                "UPDATE inventaire_balls SET quantite = quantite - ? WHERE user_id = ? AND ball_type = ?",
                (quantite, proposant, objet_cle),
            )
            cur.execute(
                """
                INSERT INTO inventaire_balls (user_id, ball_type, quantite) VALUES (?, ?, ?)
                ON CONFLICT(user_id, ball_type) DO UPDATE SET quantite = quantite + excluded.quantite
                """,
                (receveur, objet_cle, quantite),
            )

    # Transfert des Poké Dollars
    cur.execute("UPDATE users SET poke_dollars = poke_dollars - ? WHERE user_id = ?", (echange["joueur1_pd"], j1))
    cur.execute("UPDATE users SET poke_dollars = poke_dollars + ? WHERE user_id = ?", (echange["joueur1_pd"], j2))
    cur.execute("UPDATE users SET poke_dollars = poke_dollars - ? WHERE user_id = ?", (echange["joueur2_pd"], j2))
    cur.execute("UPDATE users SET poke_dollars = poke_dollars + ? WHERE user_id = ?", (echange["joueur2_pd"], j1))

    cur.execute("UPDATE echanges SET actif = 0 WHERE id = ?", (echange_id,))
    conn.commit()
    conn.close()
    return True, None


# Domaine roguelike (creer_run_roguelike, obtenir_equipe_roguelike, etc.) déplacé
# dans database/roguelike.py — voir le `from .roguelike import *` en fin de fichier.


def creer_annonce_marketplace(vendeur_id: int, capture_id: int, prix: int, duree_secondes: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    maintenant = int(time.time())
    cur.execute(
        """
        INSERT INTO marketplace_annonces (vendeur_id, capture_id, prix, date_creation, date_expiration, statut)
        VALUES (?, ?, ?, ?, ?, 'active')
        """,
        (vendeur_id, capture_id, prix, maintenant, maintenant + duree_secondes),
    )
    annonce_id = cur.lastrowid
    conn.commit()
    conn.close()
    return annonce_id


def creer_annonce_enchere(vendeur_id: int, capture_id: int, prix_depart: int, duree_secondes: int) -> int:
    """Comme creer_annonce_marketplace, mais type_annonce='enchere' — "prix" sert de MISE
    À PRIX (jamais modifiée ensuite), prix_actuel/enchereur_actuel_id restent NULL tant
    qu'aucune enchère n'a été placée (voir placer_enchere)."""
    conn = get_connexion()
    cur = conn.cursor()
    maintenant = int(time.time())
    cur.execute(
        """
        INSERT INTO marketplace_annonces
            (vendeur_id, capture_id, prix, date_creation, date_expiration, statut, type_annonce)
        VALUES (?, ?, ?, ?, ?, 'active', 'enchere')
        """,
        (vendeur_id, capture_id, prix_depart, maintenant, maintenant + duree_secondes),
    )
    annonce_id = cur.lastrowid
    conn.commit()
    conn.close()
    return annonce_id


def placer_enchere(annonce_id: int, encherisseur_id: int, montant: int) -> tuple:
    """Place une enchère de façon atomique : re-vérifie l'annonce, le montant minimum
    valide, et les fonds — puis DÉBITE IMMÉDIATEMENT l'enchérisseur (fonds retenus en
    escrow, jamais un simple engagement) et REMBOURSE l'ancien plus offrant s'il y en
    avait un. Retourne (succes: bool, message_erreur: str | None)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marketplace_annonces WHERE id = ?", (annonce_id,))
    annonce = cur.fetchone()
    conn.close()

    if annonce is None or annonce["statut"] != "active" or annonce["type_annonce"] != "enchere":
        return False, "Cette enchère n'est plus disponible (déjà terminée ou retirée)."
    if annonce["date_expiration"] <= int(time.time()):
        return False, "Cette enchère est déjà terminée, la résolution est en cours."
    if annonce["vendeur_id"] == encherisseur_id:
        return False, "Tu ne peux pas enchérir sur ton propre Pokémon !"

    montant_minimum = annonce["prix_actuel"] + 1 if annonce["prix_actuel"] else annonce["prix"]
    if montant < montant_minimum:
        return False, f"Ton enchère doit être d'au moins {montant_minimum} Poké Dollars."

    ancien_enchereur_id = annonce["enchereur_actuel_id"]
    ancien_montant = annonce["prix_actuel"]

    solde = obtenir_poke_dollars(encherisseur_id)
    if solde < montant:
        return False, f"Il te manque des Poké Dollars pour cette enchère ({solde}/{montant})."

    conn = get_connexion()
    cur = conn.cursor()
    # Re-vérifie qu'aucune enchère concurrente n'a été acceptée entre-temps (deux joueurs
    # enchérissant à la même seconde) — la condition sur prix_actuel dans le WHERE rend
    # cette mise à jour atomique : si elle échoue, quelqu'un d'autre est passé devant.
    cur.execute(
        """
        UPDATE marketplace_annonces SET prix_actuel = ?, enchereur_actuel_id = ?
        WHERE id = ? AND statut = 'active'
        AND (prix_actuel IS ? OR prix_actuel < ?)
        """,
        (montant, encherisseur_id, annonce_id, ancien_montant, montant),
    )
    a_reussi = cur.rowcount > 0
    conn.commit()
    conn.close()

    if not a_reussi:
        return False, "Quelqu'un d'autre vient d'enchérir en même temps — réessaie avec un montant plus élevé."

    ajouter_poke_dollars(encherisseur_id, -montant)
    if ancien_enchereur_id is not None:
        ajouter_poke_dollars(ancien_enchereur_id, ancien_montant)
    return True, None


def resoudre_enchere_expiree(annonce_id: int) -> dict:
    """À appeler UNE SEULE FOIS par annonce expirée (voir marketplace.purger_annonces_expirees) :
    si un enchérisseur existe, lui transfère le Pokémon (ses fonds sont DÉJÀ débités
    depuis placer_enchere) et crédite le vendeur ; sinon, l'annonce expire normalement
    (Pokémon jamais déplacé, personne n'a jamais rien payé). Retourne
    {vendu: bool, vendeur_id, enchereur_id ou None, prix_final ou None, capture_id,
    pokemon_nom} pour que l'appelant construise l'annonce de résultat."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT m.*, c.pokemon_nom FROM marketplace_annonces m JOIN captures c ON c.id = m.capture_id WHERE m.id = ?",
        (annonce_id,),
    )
    annonce = cur.fetchone()
    if annonce is None:
        conn.close()
        return {"vendu": False}

    resultat = {
        "vendeur_id": annonce["vendeur_id"], "capture_id": annonce["capture_id"],
        "pokemon_nom": annonce["pokemon_nom"], "enchereur_id": annonce["enchereur_actuel_id"],
        "prix_final": annonce["prix_actuel"],
    }

    if annonce["enchereur_actuel_id"] is None:
        cur.execute("UPDATE marketplace_annonces SET statut = 'expiree' WHERE id = ?", (annonce_id,))
        conn.commit()
        conn.close()
        resultat["vendu"] = False
        return resultat

    cur.execute("UPDATE captures SET user_id = ? WHERE id = ?", (annonce["enchereur_actuel_id"], annonce["capture_id"]))
    cur.execute(
        "UPDATE marketplace_annonces SET statut = 'vendue', acheteur_id = ? WHERE id = ?",
        (annonce["enchereur_actuel_id"], annonce_id),
    )
    conn.commit()
    conn.close()

    # Les fonds de l'enchérisseur sont déjà débités depuis placer_enchere — reste
    # seulement à créditer le vendeur.
    ajouter_poke_dollars(annonce["vendeur_id"], annonce["prix_actuel"])
    resultat["vendu"] = True
    return resultat


def definir_message_annonce_marketplace(annonce_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE marketplace_annonces SET message_id = ? WHERE id = ?", (str(message_id), annonce_id))
    conn.commit()
    conn.close()


def obtenir_annonce_marketplace(annonce_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marketplace_annonces WHERE id = ?", (annonce_id,))
    row = cur.fetchone()
    conn.close()
    return row


def capture_deja_en_vente(capture_id: int) -> bool:
    """Empêche de mettre en vente un Pokémon déjà listé activement ailleurs."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM marketplace_annonces WHERE capture_id = ? AND statut = 'active' LIMIT 1",
        (capture_id,),
    )
    trouve = cur.fetchone() is not None
    conn.close()
    return trouve


def obtenir_annonces_marketplace_joueur(vendeur_id: int, actives_seulement: bool = True):
    conn = get_connexion()
    cur = conn.cursor()
    if actives_seulement:
        cur.execute(
            "SELECT * FROM marketplace_annonces WHERE vendeur_id = ? AND statut = 'active' ORDER BY date_creation DESC",
            (vendeur_id,),
        )
    else:
        cur.execute(
            "SELECT * FROM marketplace_annonces WHERE vendeur_id = ? ORDER BY date_creation DESC",
            (vendeur_id,),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def obtenir_annonces_marketplace_expirees(maintenant: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM marketplace_annonces WHERE statut = 'active' AND date_expiration <= ?",
        (maintenant,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def marquer_annonce_marketplace(annonce_id: int, statut: str):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE marketplace_annonces SET statut = ? WHERE id = ?", (statut, annonce_id))
    conn.commit()
    conn.close()


def executer_achat_marketplace(annonce_id: int, acheteur_id: int) -> tuple:
    """Exécute l'achat de façon atomique : re-vérifie que l'annonce est toujours active,
    que le vendeur possède toujours le Pokémon, et que l'acheteur a les fonds — puis
    transfère le Pokémon et les Poké Dollars. Retourne (succes, message_erreur)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marketplace_annonces WHERE id = ?", (annonce_id,))
    annonce = cur.fetchone()
    if annonce is None or annonce["statut"] != "active":
        conn.close()
        return False, "Cette annonce n'est plus disponible (déjà vendue, retirée ou expirée)."
    if annonce["vendeur_id"] == acheteur_id:
        conn.close()
        return False, "Tu ne peux pas acheter ton propre Pokémon !"

    cur.execute("SELECT user_id FROM captures WHERE id = ?", (annonce["capture_id"],))
    capture = cur.fetchone()
    if capture is None or capture["user_id"] != annonce["vendeur_id"]:
        cur.execute("UPDATE marketplace_annonces SET statut = 'annulee' WHERE id = ?", (annonce_id,))
        conn.commit()
        conn.close()
        return False, "Le vendeur ne possède plus ce Pokémon (déjà échangé, relâché...) — annonce annulée."
    conn.close()

    # Solde vérifié via une connexion séparée (même convention que executer_echange).
    solde_acheteur = obtenir_poke_dollars(acheteur_id)
    if solde_acheteur < annonce["prix"]:
        return False, f"Il te manque des Poké Dollars pour cet achat ({solde_acheteur}/{annonce['prix']})."

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE captures SET user_id = ? WHERE id = ?", (acheteur_id, annonce["capture_id"]))
    cur.execute(
        "UPDATE marketplace_annonces SET statut = 'vendue', acheteur_id = ? WHERE id = ?",
        (acheteur_id, annonce_id),
    )
    conn.commit()
    conn.close()

    ajouter_poke_dollars(acheteur_id, -annonce["prix"])
    ajouter_poke_dollars(annonce["vendeur_id"], annonce["prix"])
    return True, None


def rechercher_annonces_marketplace_actives(terme: str, limite: int = 15):
    """Recherche par nom d'espèce parmi les annonces ACTIVES uniquement — insensible à la
    casse ET aux accents (filtrage en Python : peu d'annonces actives à la fois, pas
    besoin d'une recherche SQL, et ça évite les faux "aucun résultat" quand l'accent
    n'est pas tapé — ex: chercher "ecremeuh" doit trouver "Écrémeuh")."""
    import pokemon_data

    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.*, c.pokemon_nom, c.pc, c.shiny
        FROM marketplace_annonces m
        JOIN captures c ON c.id = m.capture_id
        WHERE m.statut = 'active'
        ORDER BY m.date_creation DESC
        """,
    )
    toutes = cur.fetchall()
    conn.close()

    terme_normalise = pokemon_data.cle_tri_alphabetique_fr(terme)
    resultats = [row for row in toutes if terme_normalise in pokemon_data.cle_tri_alphabetique_fr(row["pokemon_nom"])]
    return resultats[:limite]


def obtenir_historique_marketplace_joueur(user_id: int, limite: int = 15):
    """Toutes les annonces où le joueur est vendeur OU acheteur (tous statuts confondus),
    les plus récentes d'abord. LEFT JOIN : reste correct même si la capture a depuis été
    relâchée/re-échangée (pokemon_nom devient None dans ce cas plutôt qu'une ligne perdue)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.*, c.pokemon_nom
        FROM marketplace_annonces m
        LEFT JOIN captures c ON c.id = m.capture_id
        WHERE m.vendeur_id = ? OR m.acheteur_id = ?
        ORDER BY m.date_creation DESC
        LIMIT ?
        """,
        (user_id, user_id, limite),
    )
    rows = cur.fetchall()
    conn.close()
    return rows
