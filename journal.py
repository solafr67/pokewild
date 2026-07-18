"""Journal des logs (bot + joueurs), envoyé dans un channel Discord dédié.

Usage : `journal.logger("texte du log")` n'importe où dans le code (synchrone, pas
besoin d'await) — le message est mis en file d'attente et envoyé par lot toutes les
5 secondes par boucle_envoi_logs, pour éviter de spammer/de se faire rate-limit par
Discord si plusieurs événements arrivent d'un coup.
"""

import time

FILE_ATTENTE_LOGS: list[str] = []
LIMITE_FILE = 500  # sécurité : évite une croissance infinie si le channel est mal configuré


def logger(message: str):
    """Ajoute une ligne à la file d'attente des logs. Synchrone, utilisable partout."""
    horodatage = time.strftime("%H:%M:%S")
    FILE_ATTENTE_LOGS.append(f"`{horodatage}` {message}")
    if len(FILE_ATTENTE_LOGS) > LIMITE_FILE:
        del FILE_ATTENTE_LOGS[: len(FILE_ATTENTE_LOGS) - LIMITE_FILE]


async def boucle_envoi_logs(bot, channel_id: int, derniere_activite: dict):
    """Vide la file d'attente toutes les 5 secondes vers le channel de logs, par blocs
    de sous 2000 caractères (limite Discord par message)."""
    import asyncio

    import discord

    await bot.wait_until_ready()

    while not bot.is_closed():
        await asyncio.sleep(5)
        derniere_activite["logs"] = time.time()

        if not FILE_ATTENTE_LOGS:
            continue

        try:
            channel = bot.get_channel(channel_id)
            if channel is None:
                continue  # channel pas configuré ou introuvable — on vide quand même la file plus bas

            lignes = list(FILE_ATTENTE_LOGS)
            FILE_ATTENTE_LOGS.clear()

            bloc = ""
            for ligne in lignes:
                if len(bloc) + len(ligne) + 1 > 1900:
                    await channel.send(bloc, allowed_mentions=discord.AllowedMentions.none())
                    bloc = ""
                bloc += ligne + "\n"
            if bloc:
                await channel.send(bloc, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            import traceback

            print("⚠️ Erreur dans boucle_envoi_logs (les prochains logs seront quand même tentés) :")
            traceback.print_exc()
            FILE_ATTENTE_LOGS.clear()  # évite de re-tenter en boucle les mêmes lignes en échec
