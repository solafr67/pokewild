"""notifications_service.py — Cloche de notifications du site.

Les événements ponctuels (vente, défi, échange, niveau…) sont écrits par le jeu au moment
où ils se produisent (database.notifier). Les rappels qui dépendent du temps (récompense
quotidienne disponible, expédition terminée) sont générés ici à la lecture, une seule fois
chacun grâce à leur clé."""

import time

import database
import quetes_service


def _rappels(uid: int):
    try:
        if not quetes_service.etat_connexion(uid)["deja_reclame"]:
            database.notifier(uid, "quete", "Récompense quotidienne disponible", "Réclame-la pour garder ta série.", "quetes",
                              cle=f"daily:{int(time.time() // 86400)}")
    except Exception:
        pass
    try:
        maintenant = int(time.time())
        for r in database.obtenir_explorations_actives(uid):
            if r["date_fin"] <= maintenant:
                database.notifier(uid, "expedition", "Expédition terminée", "Tes Pokémon sont revenus avec du butin.", "explorations",
                                  cle=f"exped:{r['slot']}:{r['date_fin']}")
    except Exception:
        pass


def _depuis(t: int) -> str:
    s = max(0, int(time.time()) - t)
    if s < 60:
        return "à l'instant"
    if s < 3600:
        return f"il y a {s // 60} min"
    if s < 86400:
        return f"il y a {s // 3600} h"
    return f"il y a {s // 86400} j"


def etat(uid: int, avec_liste: bool = True) -> dict:
    _rappels(uid)
    out = {"non_lues": database.compter_notifications_non_lues(uid)}
    if avec_liste:
        out["notifications"] = [
            {"id": n["id"], "type": n["type"], "titre": n["titre"], "texte": n["texte"], "lien": n["lien"],
             "lu": bool(n["lu"]), "depuis": _depuis(n["cree_a"])}
            for n in database.lister_notifications(uid)]
    return out


def marquer_lu(uid: int, notif_id: int | None = None) -> dict:
    database.marquer_notifications_lues(uid, notif_id)
    return etat(uid)


def vider(uid: int) -> dict:
    database.vider_notifications(uid)
    return etat(uid)
