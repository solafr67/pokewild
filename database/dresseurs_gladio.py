"""Sous-module database — domaine dresseurs (PvE dresseurs solo/duo) + Gladio (rival)
+ famille "dégression quotidienne" arène/dresseur (multiplicateur qui décroît à
chaque victoire répétée le même jour, partagé avec le domaine arène).

Domaine isolé (vérifié exhaustivement avant extraction) : aucune fonction ailleurs
dans database/ n'appelle une fonction de ce fichier, et ce fichier ne dépend que
de get_connexion."""

import time

import config

from . import get_connexion


def marquer_runs_arene_en_cours_defaite() -> int:
    """Marque perdus tous les runs d'arène encore 'en_cours' (nettoyage au démarrage :
    leur combat a été clôturé en forfait, le run ne peut plus continuer). Retourne le
    nombre de runs concernés."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE arene_runs SET statut = 'defaite' WHERE statut = 'en_cours'")
    nb = cur.rowcount
    conn.commit()
    conn.close()
    return nb


def multiplicateur_arene_du_jour(user_id: int) -> float:
    """Multiplicateur de dégression économique d'arène applicable MAINTENANT, sans rien
    incrémenter — utilisé pour les récompenses d'Apprentis en cours de run (le compteur
    ne monte qu'au run complété, voir enregistrer_victoire_arene_repetition)."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM arene_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    conn.close()
    compteur = row["compteur"] if row else 0
    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    return paliers[min(compteur, len(paliers) - 1)]


def enregistrer_victoire_arene_repetition(user_id: int) -> float:
    """Enregistre un run d'arène COMPLÉTÉ (champion battu) pour la journée en cours, et
    retourne le multiplicateur à appliquer sur la récompense économique de CE run —
    dégression progressive au fil des runs du jour (config.MULTIPLICATEURS_REPETITION_JOUR_ECO).
    Un run perdu avant le champion n'incrémente rien : on peut retenter au plein tarif."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM arene_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0

    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    multiplicateur = paliers[min(compteur_avant, len(paliers) - 1)]

    cur.execute(
        """
        INSERT INTO arene_victoires_jour (user_id, jour_id, compteur)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (user_id, jour_id),
    )
    conn.commit()
    conn.close()
    return multiplicateur


def enregistrer_victoire_dresseur_repetition(user_id: int) -> float:
    """Enregistre une victoire PvE contre dresseur pour la journée en cours (TOUS
    archétypes confondus), et retourne le multiplicateur à appliquer sur la récompense
    ÉCONOMIQUE (PD + XP) de CETTE victoire — dégression progressive au fil des victoires
    du jour, voir config.MULTIPLICATEURS_REPETITION_JOUR_ECO."""
    import config

    jour_id = int(time.time()) // 86400
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT compteur FROM pve_victoires_jour WHERE user_id = ? AND jour_id = ?",
        (user_id, jour_id),
    )
    row = cur.fetchone()
    compteur_avant = row["compteur"] if row else 0

    paliers = config.MULTIPLICATEURS_REPETITION_JOUR_ECO
    multiplicateur = paliers[min(compteur_avant, len(paliers) - 1)]

    cur.execute(
        """
        INSERT INTO pve_victoires_jour (user_id, jour_id, compteur)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, jour_id) DO UPDATE SET compteur = compteur + 1
        """,
        (user_id, jour_id),
    )
    conn.commit()
    conn.close()
    return multiplicateur


# --- Échanges entre joueurs ---

# Domaine échanges + marketplace (creer_echange, executer_echange,
# creer_annonce_marketplace, executer_achat_marketplace, etc.) déplacé dans
# database/echanges_marketplace.py — voir le `from .echanges_marketplace import *`
# en fin de fichier.



def obtenir_relation_gladio(user_id: int) -> int:
    """Compteur de familiarité effectif — décroît lentement si le joueur n'a pas
    interagi avec Gladio depuis longtemps (config.GLADIO_JOURS_PAR_PALIER_DECAY)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT compteur, derniere_interaction FROM gladio_relation WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0

    compteur = row["compteur"]
    derniere = row["derniere_interaction"] or 0
    if derniere:
        jours_inactif = (time.time() - derniere) / 86400
        paliers_perdus = int(jours_inactif // config.GLADIO_JOURS_PAR_PALIER_DECAY)
        compteur = max(0, compteur - paliers_perdus)
    return compteur


def incrementer_relation_gladio(user_id: int):
    effectif = obtenir_relation_gladio(user_id)  # applique la décroissance avant d'incrémenter
    maintenant = int(time.time())
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gladio_relation (user_id, compteur, derniere_interaction) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET compteur = ?, derniere_interaction = ?
        """,
        (user_id, effectif + 1, maintenant, effectif + 1, maintenant),
    )
    conn.commit()
    conn.close()


def temps_restant_defi_gladio(user_id: int) -> int:
    """Secondes restantes avant de pouvoir redéfier Gladio (0 = disponible tout de suite)."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT dernier_defi FROM gladio_defis WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0
    ecoule = time.time() - row["dernier_defi"]
    restant = config.GLADIO_COOLDOWN_DEFI - ecoule
    return max(0, round(restant))


def marquer_defi_gladio(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gladio_defis (user_id, dernier_defi) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET dernier_defi = excluded.dernier_defi
        """,
        (user_id, int(time.time())),
    )
    conn.commit()
    conn.close()


def reinitialiser_defi_gladio(user_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM gladio_defis WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def creer_dresseur_actif(archetype_nom: str, channel_id: int, date_expiration: int) -> int:
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO dresseurs_actifs (archetype_nom, channel_id, date_expiration) VALUES (?, ?, ?)",
        (archetype_nom, str(channel_id), date_expiration),
    )
    dresseur_id = cur.lastrowid
    conn.commit()
    conn.close()
    return dresseur_id


def obtenir_dresseur_actif(dresseur_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM dresseurs_actifs WHERE id = ?", (dresseur_id,))
    row = cur.fetchone()
    conn.close()
    return row


def dresseur_actif_dans_channel(channel_id: int):
    """Vrai s'il y a un dresseur actif ET non expiré dans ce channel. Nettoie au passage
    tout dresseur resté actif=1 en base alors que sa fenêtre est dépassée (arrive si le
    bot a redémarré entre-temps et a perdu la tâche asyncio qui gère l'expiration) —
    sans ce nettoyage, un dresseur fantôme bloquerait indéfiniment le channel."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE dresseurs_actifs SET actif = 0 WHERE channel_id = ? AND actif = 1 AND date_expiration < ?",
        (str(channel_id), int(time.time())),
    )
    conn.commit()
    cur.execute(
        "SELECT * FROM dresseurs_actifs WHERE channel_id = ? AND actif = 1 LIMIT 1",
        (str(channel_id),),
    )
    row = cur.fetchone()
    conn.close()
    return row


def marquer_dresseur_message(dresseur_id: int, message_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE dresseurs_actifs SET message_id = ? WHERE id = ?", (str(message_id), dresseur_id))
    conn.commit()
    conn.close()


def a_deja_defie_dresseur(dresseur_id: int, user_id: int) -> bool:
    """Indique si ce joueur a déjà affronté ce spawn de dresseur précis (peu importe
    l'issue), pour éviter qu'il le re-défie en boucle tant qu'il est actif."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM dresseur_defis WHERE dresseur_id = ? AND user_id = ?",
        (dresseur_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def enregistrer_defi_dresseur(dresseur_id: int, user_id: int):
    """Marque ce joueur comme ayant défié ce spawn — n'empêche PAS les autres joueurs
    de le défier aussi, contrairement à l'ancien verrou premier-arrivé."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO dresseur_defis (dresseur_id, user_id) VALUES (?, ?)",
        (dresseur_id, user_id),
    )
    conn.commit()
    conn.close()


def terminer_dresseur(dresseur_id: int):
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("UPDATE dresseurs_actifs SET actif = 0 WHERE id = ?", (dresseur_id,))
    conn.commit()
    conn.close()


def obtenir_dresseurs_actifs_toutes() -> list:
    """Retourne tous les dresseurs marqués actifs, tous channels confondus — utilisé
    uniquement par le nettoyage des messages orphelins au démarrage du bot."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute("SELECT * FROM dresseurs_actifs WHERE actif = 1")
    resultats = cur.fetchall()
    conn.close()
    return resultats


