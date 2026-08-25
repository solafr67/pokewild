"""Cog : codes promo (création/gestion admin + utilisation joueur). Deuxième lot extrait
de main.py dans le cadre du découpage en Cogs — voir cogs/admin_economie.py pour le
contexte général et cogs/README.md (à venir) pour le suivi des lots.

Groupe cohérent et autonome : les 4 commandes ne touchent qu'à database.creer_code_promo/
desactiver_code_promo/lister_codes_promo/utiliser_code_promo + journal/leveling, aucune
boucle de fond ni état global partagé.
"""

import time

import discord
from discord import app_commands
from discord.ext import commands

import database
import journal
import leveling
from pokemon_data import (
    EMOJI_POKEDOLLAR,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
)

OBJETS_CODE_CHOICES = [
    app_commands.Choice(name="Poké Ball", value="pokeball"),
    app_commands.Choice(name="Super Ball", value="superball"),
    app_commands.Choice(name="Hyper Ball", value="hyperball"),
    app_commands.Choice(name="Master Ball", value="masterball"),
    app_commands.Choice(name="Potion", value="potion"),
    app_commands.Choice(name="Super Potion", value="superpotion"),
    app_commands.Choice(name="Hyper Potion", value="hyperpotion"),
    app_commands.Choice(name="Total Soin", value="totalsoin"),
    app_commands.Choice(name="Cristal de Mutation", value="cristal_mutation"),
    app_commands.Choice(name="Œuf Commun", value="oeuf_commun"),
    app_commands.Choice(name="Œuf Peu Commun", value="oeuf_peu_commun"),
    app_commands.Choice(name="Œuf Rare", value="oeuf_rare"),
    app_commands.Choice(name="Œuf Hyper Rare", value="oeuf_hyper_rare"),
    app_commands.Choice(name="Œuf Légendaire", value="oeuf_legendaire"),
]


class CodesPromoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="creer-code", description="[Admin] Crée un code promo à distribuer aux joueurs")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(objet=OBJETS_CODE_CHOICES)
    @app_commands.describe(
        code="Le code que les joueurs devront taper (insensible à la casse)",
        dollars="Poké Dollars offerts (0 si aucun)",
        xp="XP offerte (0 si aucune)",
        objet="Objet offert en plus (optionnel)",
        quantite_objet="Quantité de l'objet ci-dessus (ignoré si aucun objet choisi)",
        max_utilisations="Nombre max de joueurs pouvant l'utiliser (laisse vide = illimité)",
        duree_jours="Le code expire après ce nombre de jours (laisse vide = jamais)",
    )
    async def creer_code(
        self,
        interaction: discord.Interaction,
        code: str,
        dollars: int = 0,
        xp: int = 0,
        objet: app_commands.Choice[str] | None = None,
        quantite_objet: int = 0,
        max_utilisations: int | None = None,
        duree_jours: int | None = None,
    ):
        if dollars <= 0 and xp <= 0 and (objet is None or quantite_objet <= 0):
            await interaction.response.send_message(
                "❌ Il faut au moins une récompense (Poké Dollars, XP, ou un objet avec une quantité > 0).",
                ephemeral=True,
            )
            return

        date_expiration = int(time.time()) + duree_jours * 86400 if duree_jours else None
        succes = database.creer_code_promo(
            code, dollars, xp,
            objet.value if objet else None, quantite_objet,
            max_utilisations, date_expiration, interaction.user.id,
        )
        if not succes:
            await interaction.response.send_message(
                f"❌ Le code **{code.strip().upper()}** existe déjà.", ephemeral=True
            )
            return

        recap = []
        if dollars > 0:
            recap.append(f"{dollars} {EMOJI_POKEDOLLAR} Poké Dollars")
        if xp > 0:
            recap.append(f"{xp} XP")
        if objet and quantite_objet > 0:
            noms_objets = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
            recap.append(f"{quantite_objet}× {noms_objets.get(objet.value, objet.value)}")

        texte = f"✅ Code **{code.strip().upper()}** créé — donne : {', '.join(recap)}."
        texte += f"\nLimite d'utilisations : {max_utilisations if max_utilisations else 'illimitée'}."
        texte += f"\nExpiration : {'jamais' if not duree_jours else f'dans {duree_jours} jour(s)'}."
        journal.logger(f"🛠️ <@{interaction.user.id}> a créé le code promo **{code.strip().upper()}** ({', '.join(recap)}).")
        await interaction.response.send_message(texte, ephemeral=True)

    @app_commands.command(name="desactiver-code", description="[Admin] Désactive un code promo avant son expiration")
    @app_commands.checks.has_permissions(administrator=True)
    async def desactiver_code(self, interaction: discord.Interaction, code: str):
        succes = database.desactiver_code_promo(code)
        if succes:
            journal.logger(f"🛠️ <@{interaction.user.id}> a désactivé le code promo **{code.strip().upper()}**.")
            await interaction.response.send_message(f"✅ Code **{code.strip().upper()}** désactivé.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Le code **{code.strip().upper()}** n'existe pas.", ephemeral=True)

    @app_commands.command(name="liste-codes", description="[Admin] Liste tous les codes promo créés")
    @app_commands.checks.has_permissions(administrator=True)
    async def liste_codes(self, interaction: discord.Interaction):
        codes = database.lister_codes_promo()
        if not codes:
            await interaction.response.send_message("Aucun code promo créé pour l'instant.", ephemeral=True)
            return

        noms_objets = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
        maintenant = int(time.time())
        lignes = []
        for c in codes[:25]:
            recap = []
            if c["dollars"] > 0:
                recap.append(f"{c['dollars']} PD")
            if c["xp"] > 0:
                recap.append(f"{c['xp']} XP")
            if c["objet"] and c["quantite_objet"] > 0:
                recap.append(f"{c['quantite_objet']}× {noms_objets.get(c['objet'], c['objet'])}")

            if not c["actif"]:
                statut = "🔴 désactivé"
            elif c["date_expiration"] and c["date_expiration"] < maintenant:
                statut = "⏳ expiré"
            elif c["max_utilisations"] and c["utilisations_actuelles"] >= c["max_utilisations"]:
                statut = "🔴 épuisé"
            else:
                statut = "🟢 actif"

            limite = f"{c['utilisations_actuelles']}/{c['max_utilisations']}" if c["max_utilisations"] else f"{c['utilisations_actuelles']}/∞"
            lignes.append(f"**{c['code']}** {statut} — {', '.join(recap)} — {limite} utilisations")

        embed = discord.Embed(title="🎟️ Codes promo", description="\n".join(lignes), color=discord.Color.blurple())
        if len(codes) > 25:
            embed.set_footer(text=f"25 plus récents affichés sur {len(codes)} au total.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="code", description="Utilise un code promo pour recevoir une récompense")
    async def utiliser_code(self, interaction: discord.Interaction, code: str):
        succes, resultat = database.utiliser_code_promo(code, interaction.user.id)
        if not succes:
            await interaction.response.send_message(f"❌ {resultat}", ephemeral=True)
            return

        ligne = resultat
        recap = []
        if ligne["dollars"] > 0:
            dollars_reels = round(ligne["dollars"] * database.multiplicateur_boost(interaction.user.id, "argent"))
            database.ajouter_poke_dollars(interaction.user.id, dollars_reels)
            recap.append(f"{dollars_reels} {EMOJI_POKEDOLLAR} Poké Dollars")
        if ligne["xp"] > 0:
            leveling.gagner_xp(interaction.user.id, ligne["xp"])
            xp_affichee = round(ligne["xp"] * database.multiplicateur_boost(interaction.user.id, "xp"))
            recap.append(f"{xp_affichee} XP")
        if ligne["objet"] and ligne["quantite_objet"] > 0:
            database.ajouter_balls(interaction.user.id, ligne["objet"], ligne["quantite_objet"])
            noms_objets = {**NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS}
            recap.append(f"{ligne['quantite_objet']}× {noms_objets.get(ligne['objet'], ligne['objet'])}")

        journal.logger(f"🎟️ <@{interaction.user.id}> a utilisé le code **{ligne['code']}** ({', '.join(recap)}).")
        await interaction.response.send_message(
            f"🎉 Code **{ligne['code']}** utilisé avec succès ! Tu as reçu : {', '.join(recap)}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CodesPromoCog(bot))
