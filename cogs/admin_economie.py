"""Cog : commandes admin d'économie et de rattrapage de données (give-*, niveau-pokemon,
backfill-*). Premier morceau extrait de main.py dans le cadre du découpage en Cogs —
voir la note dans main.py au niveau du chargement des extensions pour le contexte.

Choisi comme premier lot car ces commandes sont les plus AUTONOMES du fichier : elles ne
touchent à aucune boucle de fond (spawn/raid/météo...) ni à un état global partagé
(etat_jeu, etc.) — seulement à database/journal/leveling, directement. C'est le lot à
plus faible risque pour valider le pattern d'extraction en Cog avant de s'attaquer aux
commandes plus couplées au reste de main.py.
"""

import discord
from discord import app_commands
from discord.ext import commands

import capacites as capacites_module
import database
import formes_objets as formes_objets_module
import journal
import leveling
import niveaux_pokemon
from pokemon_data import (
    ATTAQUES,
    EMOJI_BALLS,
    EMOJI_OBJETS_DIVERS,
    EMOJI_SOINS,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    NOM_SOIN_AFFICHAGE,
    obtenir_pokemon_par_nom,
    tirer_ivs,
    tirer_niveau_spawn,
)


class AdminEconomieCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="give-objet", description="[Admin] Donne un objet (ball ou potion) à un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        objet=[
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
            app_commands.Choice(name="🌸 Fleur Gracidea (Shaymin)", value="fleur_gracidea"),
            app_commands.Choice(name="🔮 Orbe Griséous (Giratina)", value="orbe_griseous"),
            app_commands.Choice(name="💎 Orbe Adamant (Dialga)", value="orbe_adamant"),
            app_commands.Choice(name="💠 Perle Lustrée (Palkia)", value="perle_lustree"),
        ]
    )
    async def give_objet(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        objet: app_commands.Choice[str],
        quantite: int,
    ):
        noms_objets = {
            **NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS,
            **{cle: info["objet_nom"] for cle, info in formes_objets_module.FORMES_OBJETS.items()},
        }
        emojis_objets = {
            **EMOJI_BALLS, **EMOJI_SOINS, **EMOJI_OBJETS_DIVERS,
            **{cle: info["objet_emoji"] for cle, info in formes_objets_module.FORMES_OBJETS.items()},
        }
        database.ajouter_balls(membre.id, objet.value, quantite)
        journal.logger(f"🛠️ <@{interaction.user.id}> a donné {quantite}× {objet.value} à <@{membre.id}> (/give-objet).")
        await interaction.response.send_message(
            f"✅ **{quantite}× {emojis_objets.get(objet.value, '')} {noms_objets.get(objet.value, objet.value)}** donné(es) à {membre.mention}."
        )

    @app_commands.command(name="give-dollars", description="[Admin] Donne des Poké Dollars à un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    async def give_dollars(self, interaction: discord.Interaction, membre: discord.Member, montant: int):
        from pokemon_data import EMOJI_POKEDOLLAR

        database.ajouter_poke_dollars(membre.id, montant)
        journal.logger(f"🛠️ <@{interaction.user.id}> a donné {montant} PD à <@{membre.id}> (/give-dollars).")
        await interaction.response.send_message(f"✅ **{montant} {EMOJI_POKEDOLLAR} Poké Dollars** donnés à {membre.mention}.")

    @app_commands.command(name="give-xp", description="[Admin] Donne de l'XP à un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    async def give_xp(self, interaction: discord.Interaction, membre: discord.Member, montant: int):
        niveau_avant, niveau_apres, recompenses_paliers = leveling.gagner_xp(membre.id, montant)
        journal.logger(f"🛠️ <@{interaction.user.id}> a donné {montant} XP à <@{membre.id}> (/give-xp).")
        texte = f"✅ **{montant} XP** donnés à {membre.mention}."
        if niveau_apres > niveau_avant:
            texte += f" (niveau {niveau_avant} → {niveau_apres})"
        await interaction.response.send_message(texte)

    @app_commands.command(name="niveau-pokemon", description="[Admin] Définit le niveau d'un Pokémon précis chez un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        membre="Le joueur concerné",
        pokemon="Nom de l'espèce (doit être dans son Pokédex)",
        niveau="Niveau à définir",
    )
    async def niveau_pokemon(self, interaction: discord.Interaction, membre: discord.Member, pokemon: str, niveau: int):
        pokemon_info = obtenir_pokemon_par_nom(pokemon)
        if pokemon_info is None:
            await interaction.response.send_message(f"❌ Pokémon **{pokemon}** introuvable dans la base.", ephemeral=True)
            return

        especes_possedees = {row["pokemon_nom"] for row in database.obtenir_pokedex_joueur(membre.id)}
        if pokemon_info["nom"] not in especes_possedees:
            await interaction.response.send_message(
                f"❌ {membre.mention} ne possède aucun **{pokemon_info['nom']}** dans son Pokédex.", ephemeral=True
            )
            return

        niveau_max = niveaux_pokemon.niveau_max_pour_rarete(pokemon_info["rarete"])
        if not (1 <= niveau <= niveau_max):
            await interaction.response.send_message(
                f"❌ Niveau invalide : doit être compris entre 1 et {niveau_max} pour un Pokémon "
                f"**{pokemon_info['rarete']}**.",
                ephemeral=True,
            )
            return

        ancien_niveau, _ = database.obtenir_niveau_pokemon(membre.id, pokemon_info["nom"])
        database.definir_niveau_xp_pokemon(
            membre.id, pokemon_info["nom"], niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau)
        )
        journal.logger(
            f"🛠️ <@{interaction.user.id}> a mis **{pokemon_info['nom']}** de <@{membre.id}> au niveau {niveau} "
            f"(était {ancien_niveau}) via /niveau-pokemon."
        )
        await interaction.response.send_message(
            f"✅ **{pokemon_info['nom']}** de {membre.mention} est maintenant **niveau {niveau}** (était niveau {ancien_niveau})."
        )

    @app_commands.command(
        name="backfill-niveaux",
        description="[Admin] Attribue un niveau (grille de rareté) aux Pokémon capturés avant le système de niveau",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        forcer="Écrase aussi le niveau des Pokémon qui en ont déjà un (nouveau tirage aléatoire). Par défaut, seuls ceux sans niveau sont touchés."
    )
    async def backfill_niveaux(self, interaction: discord.Interaction, forcer: bool = False):
        await interaction.response.defer()

        paires = database.obtenir_toutes_paires_capturees() if forcer else database.obtenir_paires_sans_niveau()
        compte = 0
        for user_id, nom in paires:
            pokemon = obtenir_pokemon_par_nom(nom)
            if not pokemon:
                continue
            niveau = tirer_niveau_spawn(pokemon["rarete"])
            database.definir_niveau_xp_pokemon(user_id, nom, niveau, niveaux_pokemon.xp_cumulee_pour_niveau(niveau))
            compte += 1

        journal.logger(
            f"🛠️ <@{interaction.user.id}> a lancé /backfill-niveaux"
            f"{' --forcer' if forcer else ''} : {compte} Pokémon mis à jour."
        )
        if forcer:
            await interaction.followup.send(
                f"✅ **{compte}** Pokémon (espèce × joueur) ont reçu un nouveau niveau aléatoire "
                f"selon la grille de rareté — y compris ceux qui en avaient déjà un (XP remise à "
                f"zéro pour ce nouveau niveau)."
            )
        else:
            await interaction.followup.send(
                f"✅ Niveau attribué (selon la grille de spawn par rareté) à **{compte}** Pokémon "
                f"(espèce × joueur) qui n'en avaient pas encore. Sans effet sur ceux qui ont déjà "
                f"un niveau — relançable sans risque."
            )

    @app_commands.command(
        name="backfill-ivs",
        description="[Admin] Attribue des IV aléatoires aux captures d'avant la refonte du système de combat/stats",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def backfill_ivs(self, interaction: discord.Interaction):
        await interaction.response.defer()

        ids = database.obtenir_captures_sans_ivs()
        for capture_id in ids:
            database.definir_ivs_capture(capture_id, tirer_ivs())

        journal.logger(f"🛠️ <@{interaction.user.id}> a lancé /backfill-ivs : {len(ids)} captures mises à jour.")
        await interaction.followup.send(
            f"✅ IV tirées aléatoirement pour **{len(ids)}** captures qui n'en avaient pas encore "
            f"(d'avant la refonte du combat). Relançable sans risque, ne touche jamais une capture "
            f"qui a déjà des IV."
        )

    @app_commands.command(
        name="backfill-talents",
        description="[Admin] Attribue un talent aux captures d'avant l'introduction du système talents/objets",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def backfill_talents(self, interaction: discord.Interaction):
        await interaction.response.defer()

        captures = database.obtenir_captures_sans_talent()
        for capture_id, pokemon_nom in captures:
            database.definir_capacite_capture(capture_id, capacites_module.capacite_pour_espece(pokemon_nom))

        journal.logger(f"🛠️ <@{interaction.user.id}> a lancé /backfill-talents : {len(captures)} captures mises à jour.")
        await interaction.followup.send(
            f"✅ Talent attribué à **{len(captures)}** captures qui n'en avaient pas encore "
            f"(d'avant l'introduction du système talents/objets). Relançable sans risque, ne "
            f"touche jamais une capture qui a déjà un talent."
        )

    @app_commands.command(name="give-ct", description="[Admin] Donne la CT d'une attaque à un joueur (possédée pour toujours)")
    @app_commands.checks.has_permissions(administrator=True)
    async def give_ct(self, interaction: discord.Interaction, membre: discord.Member, attaque: str):
        if attaque not in ATTAQUES:
            await interaction.response.send_message(f"❌ Attaque **{attaque}** introuvable.", ephemeral=True)
            return

        if database.possede_ct(membre.id, attaque):
            await interaction.response.send_message(
                f"{membre.mention} possède déjà la CT de **{attaque}**.", ephemeral=True
            )
            return

        database.acheter_ct(membre.id, attaque)
        journal.logger(f"🛠️ <@{interaction.user.id}> a donné la CT de {attaque} à <@{membre.id}> (/give-ct).")
        await interaction.response.send_message(f"✅ CT **{attaque}** donnée à {membre.mention} — utilisable pour toujours.")


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminEconomieCog(bot))
