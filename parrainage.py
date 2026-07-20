"""Parrainage — récompense les joueurs qui invitent de nouveaux membres sur le serveur.

Discord n'expose pas directement "qui a invité qui" : on le déduit en comparant, à
chaque arrivée, le nombre d'utilisations de chaque invitation avant/après (celle dont le
compteur a augmenté est celle qui vient d'être utilisée). Nécessite la permission
"Gérer le serveur" pour le bot, et l'intent Membres (voir main.py).
"""

import discord

import config
import database
import journal

# Cache en mémoire {guild_id: {code: uses}} — reconstruit au démarrage (voir
# rafraichir_cache), pas besoin de le persister en base.
CACHE_INVITES: dict[int, dict[str, int]] = {}


async def rafraichir_cache(guild: discord.Guild):
    """(Re)construit le cache d'invitations d'un serveur — à appeler au démarrage et à
    chaque création/suppression d'invitation, pour rester synchronisé."""
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        print(
            f"⚠️ Pas la permission 'Gérer le serveur' sur {guild.name} — le parrainage "
            f"ne pourra pas identifier les inviteurs."
        )
        CACHE_INVITES[guild.id] = {}
        return
    CACHE_INVITES[guild.id] = {invite.code: invite.uses for invite in invites}


async def _identifier_inviteur(member: discord.Member):
    """Compare le cache d'invitations avant/après l'arrivée de `member` pour deviner
    quelle invitation a été utilisée. Retourne None si indéterminable (URL vanity,
    invitation à usage unique déjà expirée/supprimée, permissions insuffisantes...)."""
    guild = member.guild
    ancien_cache = CACHE_INVITES.get(guild.id, {})

    try:
        invites_actuelles = await guild.invites()
    except discord.Forbidden:
        return None

    inviteur = None
    for invite in invites_actuelles:
        if invite.uses > ancien_cache.get(invite.code, 0):
            inviteur = invite.inviter
            break

    CACHE_INVITES[guild.id] = {invite.code: invite.uses for invite in invites_actuelles}
    return inviteur


async def traiter_arrivee(member: discord.Member):
    """À appeler depuis on_member_join. Identifie l'inviteur et enregistre le filleul EN
    ATTENTE — ne compte et ne récompense qu'après config.PARRAINAGE_DELAI_JOURS passés
    sans que le filleul ne reparte (voir boucle_confirmation_parrainages)."""
    if member.bot:
        return

    inviteur = await _identifier_inviteur(member)
    if inviteur is None or inviteur.bot or inviteur.id == member.id:
        return

    database.enregistrer_parrainage(member.id, inviteur.id)


async def traiter_depart(member: discord.Member):
    """À appeler depuis on_member_remove. Si ce membre était un filleul pas encore
    confirmé (parti avant le délai minimum), son parrainage est annulé — repartir tôt ne
    doit jamais compter, pour éviter le farming de faux comptes."""
    database.supprimer_parrainage_non_confirme(member.id)


def _accorder_recompense_si_palier(inviteur_id: int, total_confirmes: int):
    palier = total_confirmes // config.PARRAINAGE_PALIER
    if palier == 0:
        return

    deja_recus = database.obtenir_paliers_parrainage_recus(inviteur_id)
    if palier in deja_recus:
        return

    database.marquer_palier_parrainage_recu(inviteur_id, palier)
    database.ajouter_poke_dollars(inviteur_id, config.PARRAINAGE_RECOMPENSE_DOLLARS)
    for ball_type, quantite in config.PARRAINAGE_RECOMPENSE_BALLS:
        database.ajouter_balls(inviteur_id, ball_type, quantite)

    journal.logger(
        f"🎉 <@{inviteur_id}> a atteint {total_confirmes} invitations confirmées (palier {palier}) — "
        f"récompense de parrainage accordée."
    )
    return palier


async def boucle_confirmation_parrainages(bot):
    """Toutes les heures, confirme les parrainages dont le délai minimum est écoulé ET
    dont le filleul est toujours présent sur le serveur (sinon on_member_remove l'aurait
    déjà supprimé — ce filtre de présence est une double sécurité, au cas où le bot était
    hors ligne au moment du départ)."""
    import asyncio

    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            delai_secondes = config.PARRAINAGE_DELAI_JOURS * 86400
            a_verifier = database.obtenir_parrainages_a_confirmer(delai_secondes)

            for filleul_id, inviteur_id in a_verifier:
                present = False
                for guild in bot.guilds:
                    if guild.get_member(filleul_id) is not None:
                        present = True
                        break

                if not present:
                    database.supprimer_parrainage_non_confirme(filleul_id)
                    continue

                database.confirmer_parrainage(filleul_id)
                total = database.compter_parrainages(inviteur_id)
                palier = _accorder_recompense_si_palier(inviteur_id, total)

                if palier:
                    inviteur = bot.get_user(inviteur_id)
                    if inviteur:
                        try:
                            objets_txt = ", ".join(f"{q}× {b}" for b, q in config.PARRAINAGE_RECOMPENSE_BALLS)
                            await inviteur.send(
                                f"🎉 Merci d'avoir fait connaître PokéWild autour de toi ! Tu as "
                                f"maintenant **{total}** invitations confirmées, et tu viens de "
                                f"débloquer une récompense : {config.PARRAINAGE_RECOMPENSE_DOLLARS} "
                                f"Poké Dollars + {objets_txt}. Continue comme ça !"
                            )
                        except (discord.Forbidden, discord.HTTPException):
                            pass  # DM fermés : tant pis, la récompense est bien accordée en jeu
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_confirmation_parrainages (le cycle suivant sera quand même tenté) :")
            traceback.print_exc()
            journal.logger("🔴 Erreur dans `boucle_confirmation_parrainages` — voir les logs serveur.")

        await asyncio.sleep(3600)


def synchroniser_boosters(guild: discord.Guild):
    """Recale le statut booster de TOUS les membres sur la réalité Discord — à appeler au
    démarrage du bot, pour rattraper un boost démarré/arrêté pendant que le bot était hors
    ligne (on_member_update ne se déclenche que pour les changements en direct)."""
    ids_boosters_discord = {m.id for m in guild.premium_subscribers}
    for member in guild.members:
        if member.bot:
            continue
        devrait_etre_booster = member.id in ids_boosters_discord
        if database.est_booster_serveur(member.id) != devrait_etre_booster:
            database.definir_booster_serveur(member.id, devrait_etre_booster)
