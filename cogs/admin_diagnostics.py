"""Cog : diagnostics et administration joueur (status-bot, stats-economie, voir-joueur,
reset-joueur, reset-pokestop, annuler-raid, annuler-combat). Troisième lot du découpage
en Cogs — voir cogs/admin_economie.py pour le contexte général.

⚠️ status_bot lit DERNIERE_ACTIVITE_BOUCLES, un dict mis à jour par les boucles de fond
(spawn/raid/dresseurs/...) qui vivent encore dans main.py (pas encore extraites — ce
sera un lot à part, plus risqué car couplé aux tasks.loop). D'où l'import de `main` ici :
sûr dans ce sens précis, car ce Cog n'est chargé (bot.load_extension, dans on_ready)
qu'une fois main.py entièrement exécuté — pas un vrai import circulaire.
"""

import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import database
import leveling
import quetes as quetes_module
import quetes_ui as quetes_ui_module
import races
from pokemon_data import EMOJI_POKEDOLLAR, EMOJI_RARETE
from profil import url_avatar_fiable


class AdminDiagnosticsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="reset-pokestop", description="[Admin] Réinitialise le cooldown PokéStop d'un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_pokestop(self, interaction: discord.Interaction, membre: discord.Member):
        database.reinitialiser_pokestop(membre.id)
        await interaction.response.send_message(
            f"✅ Cooldown PokéStop réinitialisé pour {membre.mention}.", ephemeral=True
        )

    @app_commands.command(name="status-bot", description="[Admin] État des boucles de fond et des combats/dresseurs/raids en cours")
    @app_commands.checks.has_permissions(administrator=True)
    async def status_bot(self, interaction: discord.Interaction):
        import sys
        main_module = sys.modules["__main__"]

        maintenant = time.time()

        def _ligne_boucle(nom_affiche: str, cle: str, intervalle_attendu: int) -> str:
            derniere = main_module.DERNIERE_ACTIVITE_BOUCLES.get(cle)
            if derniere is None:
                return f"❓ **{nom_affiche}** — aucune activité enregistrée depuis le démarrage"
            ecart = int(maintenant - derniere)
            if ecart > intervalle_attendu * 3:
                statut = "🔴 possiblement bloquée"
            elif ecart > intervalle_attendu * 1.5:
                statut = "🟡 en retard"
            else:
                statut = "🟢 OK"
            minutes = ecart // 60
            secondes = ecart % 60
            return f"{statut} **{nom_affiche}** — dernière activité il y a {minutes}m {secondes}s"

        lignes_boucles = [
            _ligne_boucle("Spawn classique", "spawn_classique", config.INTERVALLE_SPAWN_CLASSIQUE),
            _ligne_boucle("Spawn VIP", "spawn_vip", config.INTERVALLE_SPAWN_VIP),
            _ligne_boucle("Raids", "raid", 60),
            _ligne_boucle("Dresseurs", "dresseurs", 60),
            _ligne_boucle("Classement", "classement", config.INTERVALLE_CLASSEMENT),
            _ligne_boucle("Météo", "meteo", 30 * 60),
            _ligne_boucle("Gladio (spontané)", "gladio", 3 * 3600),
            _ligne_boucle("Notifications MP", "notifications", 30),
            _ligne_boucle("Envoi des logs", "logs", 5),
            _ligne_boucle("Snapshot économie", "snapshot_economie", 24 * 3600),
            _ligne_boucle("Marketplace (purge)", "marketplace", config.MARKETPLACE_INTERVALLE_VERIFICATION_SECONDES),
        ]

        compteurs = database.obtenir_compteurs_activite()

        embed = discord.Embed(title="🩺 État du bot", color=discord.Color.blurple())
        embed.add_field(name="Boucles de fond", value="\n".join(lignes_boucles), inline=False)
        embed.add_field(
            name="En cours actuellement",
            value=(
                f"⚔️ Combats actifs (PvP + dresseurs) : {compteurs['combats_actifs']}\n"
                f"🧑‍🏫 Dresseurs actifs : {compteurs['dresseurs_actifs']}\n"
                f"👹 Raids actifs : {compteurs['raids_actifs']}"
            ),
            inline=False,
        )
        embed.add_field(name="📶 Latence Discord", value=f"{round(self.bot.latency * 1000)} ms", inline=False)
        embed.set_footer(text="Les boucles @tasks.loop dont l'activité n'avance plus ont probablement planté silencieusement — un redémarrage du bot les relance.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="stats-economie", description="[Admin] Vue d'ensemble de la masse de Poké Dollars en circulation")
    @app_commands.checks.has_permissions(administrator=True)
    async def stats_economie(self, interaction: discord.Interaction):
        nb_joueurs, total_pd, moyenne_pd = database.obtenir_stats_economie_actuelles()
        historique = database.obtenir_historique_economie(14)  # jusqu'à 14 derniers instantanés (14 jours)

        embed = discord.Embed(title="📊 Économie du serveur", color=discord.Color.blurple())
        embed.add_field(name="👥 Joueurs actifs", value=str(nb_joueurs), inline=True)
        embed.add_field(name=f"{EMOJI_POKEDOLLAR} Total en circulation", value=f"{total_pd:,}".replace(",", " "), inline=True)
        embed.add_field(name="📈 Moyenne / joueur", value=f"{moyenne_pd:,.0f}".replace(",", " "), inline=True)

        if len(historique) >= 2:
            plus_recent = historique[0]
            plus_ancien = historique[-1]
            variation = plus_recent["total_pd"] - plus_ancien["total_pd"]
            jours_ecart = max(1, (plus_recent["date"] - plus_ancien["date"]) // 86400)
            pourcentage = (variation / plus_ancien["total_pd"] * 100) if plus_ancien["total_pd"] else 0
            fleche = "📈" if variation > 0 else ("📉" if variation < 0 else "➡️")
            embed.add_field(
                name=f"{fleche} Tendance (sur {jours_ecart}j, {len(historique)} instantanés)",
                value=f"{'+' if variation >= 0 else ''}{variation:,} PD ({pourcentage:+.1f}%)".replace(",", " "),
                inline=False,
            )
        else:
            embed.add_field(
                name="📈 Tendance",
                value="Pas encore assez d'instantanés (1 par jour) pour calculer une tendance.",
                inline=False,
            )

        embed.set_footer(text="Instantané enregistré automatiquement une fois par jour")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="voir-joueur", description="[Admin] Fiche de diagnostic complète d'un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    async def voir_joueur(self, interaction: discord.Interaction, membre: discord.Member):
        dollars = database.obtenir_poke_dollars(membre.id)
        xp_totale = database.obtenir_xp(membre.id)
        niveau, xp_dans_niveau, xp_requise = leveling.progression_niveau(xp_totale)
        barre_xp = leveling.barre_progression(xp_dans_niveau, xp_requise)
        captures = database.obtenir_pokedex_joueur(membre.id)
        nb_especes = len({row["pokemon_nom"] for row in captures})
        nb_total = sum(row["quantite"] for row in captures)
        equipe = database.obtenir_equipe_combat(membre.id)
        combat_actif = database.combat_en_cours_pour_joueur(membre.id)
        boosts_actifs = database.obtenir_tous_boosts_actifs(membre.id)
        race_nom, pity = database.obtenir_race(membre.id)
        explorations = database.obtenir_explorations_actives(membre.id)
        titre_categorie = database.obtenir_titre_actif(membre.id)
        titre_txt = None
        if titre_categorie:
            valeurs = quetes_ui_module.valeurs_accomplissements(membre.id)
            palier = quetes_module.palier_atteint(titre_categorie, valeurs[titre_categorie])
            titre_txt = quetes_module.titre_complet(titre_categorie, palier)

        embed = discord.Embed(
            title=f"🔍 {membre.display_name}",
            description=(
                (f"🏅 *{titre_txt}*\n" if titre_txt else "")
                + f"**Niveau {niveau}**\n{barre_xp} `{xp_dans_niveau}/{xp_requise} XP` (total : {xp_totale})"
            ),
            color=discord.Color.blurple(),
        )
        # Toujours en pièce jointe classique (pas attachment://) : cette fiche reste
        # éphémère volontairement (infos d'un autre joueur, réservées à l'admin qui consulte)
        # — hors, un message éphémère n'affiche jamais une image attachée via attachment://
        # (bug Discord confirmé, voir fichier_avatar_fiable/voir_profil pour le détail). On
        # se rabat donc directement sur l'URL fiable plutôt que de générer un fichier inutile.
        embed.set_thumbnail(url=url_avatar_fiable(membre))

        embed.add_field(name="Poké Dollars", value=f"{EMOJI_POKEDOLLAR} {dollars}", inline=True)
        embed.add_field(name="📖 Pokédex", value=f"{nb_especes} espèces • {nb_total} captures", inline=True)
        embed.add_field(name="⚔️ Équipe de combat", value=", ".join(equipe) if equipe else "*Non configurée*", inline=False)

        if race_nom:
            race = races.obtenir_race_par_nom(race_nom)
            embed.add_field(
                name="🧬 Mutation",
                value=f"{EMOJI_RARETE[race['palier']]} **{race['nom']}** — {races.texte_bonus(race['bonus'])}\n*Pity : {pity}/{config.PITY_SEUIL}*",
                inline=False,
            )
        else:
            embed.add_field(name="🧬 Mutation", value=f"*Aucune — Pity : {pity}/{config.PITY_SEUIL}*", inline=False)

        if explorations:
            maintenant = int(time.time())
            lignes = []
            for row in explorations:
                statut = "✅ prête" if row["date_fin"] <= maintenant else f"⏳ <t:{row['date_fin']}:R>"
                lignes.append(f"Emplacement {row['slot']} : {row['pokemon1']}, {row['pokemon2']}, {row['pokemon3']} — {statut}")
            embed.add_field(name="🗺️ Explorations en cours", value="\n".join(lignes), inline=False)

        combat_txt = "Aucun"
        if combat_actif:
            adversaire_id = combat_actif["joueur2_id"] if combat_actif["joueur1_id"] == membre.id else combat_actif["joueur1_id"]
            combat_txt = f"En cours (id {combat_actif['id']}) contre <@{adversaire_id}>"
        embed.add_field(name="🥊 Combat PvP", value=combat_txt, inline=True)

        boosts_txt = (
            "\n".join(f"• {type_b} — <t:{exp}:R>" for type_b, exp in boosts_actifs.items())
            if boosts_actifs else "Aucun"
        )
        embed.add_field(name="🚀 Boost temporaire", value=boosts_txt, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="reset-joueur", description="[Admin] Réinitialise complètement le profil d'un joueur (irréversible)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_joueur(self, interaction: discord.Interaction, membre: discord.Member, confirmation: str):
        if confirmation != membre.name:
            await interaction.response.send_message(
                f"❌ Confirmation invalide. Pour réinitialiser {membre.mention}, "
                f"tape exactement son nom d'utilisateur (`{membre.name}`) dans le paramètre `confirmation`.",
                ephemeral=True,
            )
            return

        database.reinitialiser_joueur(membre.id)
        await interaction.response.send_message(
            f"✅ Profil de {membre.mention} entièrement réinitialisé (PD, XP, captures, inventaire, équipe, boosts).",
            ephemeral=True,
        )

    @app_commands.command(name="annuler-raid", description="[Admin] Force l'annulation du raid actif dans un channel (débloque un raid fantôme)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        channel=[
            app_commands.Choice(name="Classique", value="classique"),
            app_commands.Choice(name="VIP", value="vip"),
        ]
    )
    async def annuler_raid(self, interaction: discord.Interaction, channel: app_commands.Choice[str]):
        channel_id = (
            config.CHANNEL_SPAWN_CLASSIQUE_ID if channel.value == "classique" else config.CHANNEL_SPAWN_VIP_ID
        )
        conn = database.get_connexion()
        cur = conn.cursor()
        cur.execute(
            "UPDATE raid_actuel SET actif = 0 WHERE channel_id = ? AND actif = 1",
            (str(channel_id),),
        )
        nb_annules = cur.rowcount
        conn.commit()
        conn.close()

        if nb_annules > 0:
            await interaction.response.send_message(
                f"✅ Raid annulé dans le channel **{channel.name}**. Un nouveau pourra démarrer normalement.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ Aucun raid actif trouvé dans le channel **{channel.name}**.", ephemeral=True
            )

    @app_commands.command(name="annuler-combat", description="[Admin] Force la fin du combat PvP en cours d'un joueur (débloque un combat fantôme)")
    @app_commands.checks.has_permissions(administrator=True)
    async def annuler_combat(self, interaction: discord.Interaction, membre: discord.Member):
        combat = database.combat_en_cours_pour_joueur(membre.id)
        if combat is None:
            await interaction.response.send_message(
                f"ℹ️ {membre.mention} n'a aucun combat en cours.", ephemeral=True
            )
            return

        database.terminer_combat_pvp(combat["id"])

        if combat["thread_id"]:
            try:
                thread = self.bot.get_channel(int(combat["thread_id"]))
                if thread:
                    await thread.send("🛑 Ce combat a été annulé par un administrateur.")
            except Exception:
                pass

        await interaction.response.send_message(
            f"✅ Combat annulé (aucun vainqueur, aucune récompense distribuée). "
            f"<@{combat['joueur1_id']}> et <@{combat['joueur2_id']}> peuvent relancer un défi.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminDiagnosticsCog(bot))
