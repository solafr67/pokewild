"""Sous-module database — domaine récap hebdomadaire (snapshot des stats à la dernière
consultation). Domaine isolé : ne dépend que de get_connexion.

Modèle "depuis ta dernière consultation" plutôt que calé sur un lundi calendaire — plus
simple, pas d'ambiguïté de fuseau horaire ni de semaine ISO, et évite d'avoir besoin
d'une boucle de fond pour poster automatiquement (voir recap_hebdomadaire.py, commande
à la demande /recap).
"""

from . import get_connexion


def obtenir_snapshot_recap(user_id: int) -> dict:
    """Retourne le snapshot précédent, ou None si jamais consulté."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date_snapshot, victoires_pvp, victoires_pve, captures_totales,
               explorations_terminees, shiny_totaux, poke_dollars
        FROM recap_hebdo_snapshot WHERE user_id = ?
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def enregistrer_snapshot_recap(user_id: int, valeurs: dict):
    """Remplace le snapshot par les valeurs actuelles (upsert) — appelé à chaque
    consultation de /recap, pour que la prochaine mesure une nouvelle période."""
    conn = get_connexion()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO recap_hebdo_snapshot
            (user_id, date_snapshot, victoires_pvp, victoires_pve, captures_totales,
             explorations_terminees, shiny_totaux, poke_dollars)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            date_snapshot = excluded.date_snapshot,
            victoires_pvp = excluded.victoires_pvp,
            victoires_pve = excluded.victoires_pve,
            captures_totales = excluded.captures_totales,
            explorations_terminees = excluded.explorations_terminees,
            shiny_totaux = excluded.shiny_totaux,
            poke_dollars = excluded.poke_dollars
        """,
        (
            user_id, valeurs["date_snapshot"], valeurs["victoires_pvp"], valeurs["victoires_pve"],
            valeurs["captures_totales"], valeurs["explorations_terminees"], valeurs["shiny_totaux"],
            valeurs["poke_dollars"],
        ),
    )
    conn.commit()
    conn.close()
