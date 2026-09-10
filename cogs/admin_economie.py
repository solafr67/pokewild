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

import random

import capacites as capacites_module
import database
import formes_objets as formes_objets_module
import journal
import leveling
import mega_evolutions as mega_evolutions_module
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

# ⚠️ Autocomplete plutôt que @app_commands.choices (limité à 25 valeurs FIXES max —
# dépassement = bot.tree.sync() plante intégralement au démarrage, voir la même mise en
# garde dans cogs/gestion_pokemon.py::_OBJETS_TOUTES_FAMILLES). Catalogue volontairement
# plus large que celui-là : give-objet couvre AUSSI balls/potions/œufs/divers (que les
# admins doivent pouvoir donner), pas seulement les objets équipables sur un Pokémon.
_CATEGORIES_GIVE_OBJET = {
    "balls": NOM_BALL_AFFICHAGE,
    "potions": NOM_SOIN_AFFICHAGE,
    "divers": NOM_OBJETS_DIVERS,
    "objets_tenus": {cle: info["nom"] for cle, info in capacites_module.OBJETS_TENUS.items()},
    "formes": {cle: info["objet_nom"] for cle, info in formes_objets_module.FORMES_OBJETS.items()},
    "gemmes_mega": {
        cle: f"{info['objet_nom']} (Méga-Évolution {info['espece']})"
        for cle, info in mega_evolutions_module.MEGA_EVOLUTIONS.items()
    },
}
_CATALOGUE_GIVE_OBJET = {cle: label for categorie in _CATEGORIES_GIVE_OBJET.values() for cle, label in categorie.items()}


class AdminEconomieCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="give-objet", description="[Admin] Donne un objet (ball, potion, objet tenu, gemme méga...) à un joueur")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(objet="Tape pour chercher — balls, potions, objets tenus, formes spéciales, gemmes méga, œufs...")
    async def give_objet(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        objet: str,
        quantite: int,
    ):
        if objet not in _CATALOGUE_GIVE_OBJET:
            await interaction.response.send_message(
                "❌ Objet inconnu — choisis-en un dans la liste proposée par l'autocomplétion.", ephemeral=True
            )
            return

        noms_objets = {
            **NOM_BALL_AFFICHAGE, **NOM_SOIN_AFFICHAGE, **NOM_OBJETS_DIVERS,
            **{cle: info["objet_nom"] for cle, info in formes_objets_module.FORMES_OBJETS.items()},
            **{cle: info["objet_nom"] for cle, info in mega_evolutions_module.MEGA_EVOLUTIONS.items()},
            **{cle: info["nom"] for cle, info in capacites_module.OBJETS_TENUS.items()},
        }
        emojis_objets = {
            **EMOJI_BALLS, **EMOJI_SOINS, **EMOJI_OBJETS_DIVERS,
            **{cle: info["objet_emoji"] for cle, info in formes_objets_module.FORMES_OBJETS.items()},
            **{cle: info["objet_emoji"] for cle, info in mega_evolutions_module.MEGA_EVOLUTIONS.items()},
            **{cle: info["emoji"] for cle, info in capacites_module.OBJETS_TENUS.items()},
        }
        database.ajouter_balls(membre.id, objet, quantite)
        journal.logger(f"🛠️ <@{interaction.user.id}> a donné {quantite}× {objet} à <@{membre.id}> (/give-objet).")
        await interaction.response.send_message(
            f"✅ **{quantite}× {emojis_objets.get(objet, '')} {noms_objets.get(objet, objet)}** donné(es) à {membre.mention}."
        )

    @give_objet.autocomplete("objet")
    async def _give_objet_autocomplete(self, interaction: discord.Interaction, current: str):
        current_lower = current.lower().strip()

        if not current_lower:
            # Rien de tapé : un select de 25 options tronqué au hasard cachait
            # entièrement les gemmes méga (50 sur 94 objets au total, ajoutées en
            # dernier dans le catalogue) — l'admin n'avait aucun moyen de savoir
            # qu'elles existaient sans déjà connaître leur nom exact à taper. On montre
            # à la place un échantillon de CHAQUE catégorie, gemmes méga incluses.
            apercu = []
            nb_categories = len(_CATEGORIES_GIVE_OBJET)
            part_par_categorie = max(1, 25 // nb_categories)
            for categorie in _CATEGORIES_GIVE_OBJET.values():
                apercu.extend(list(categorie.items())[:part_par_categorie])
            return [app_commands.Choice(name=label[:100], value=cle) for cle, label in apercu[:25]]

        resultats = [
            app_commands.Choice(name=label[:100], value=cle)
            for cle, label in _CATALOGUE_GIVE_OBJET.items()
            if current_lower in label.lower() or current_lower in cle.lower()
        ]
        return resultats[:25]

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
        description="[Admin] Attribue un talent aux captures qui n'en ont pas, et corrige celles devenues incohérentes",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def backfill_talents(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Phase 1 : captures d'avant l'introduction du système talents/objets (jamais
        # touchées depuis, comme avant).
        captures_sans_talent = database.obtenir_captures_sans_talent()
        for capture_id, pokemon_nom in captures_sans_talent:
            database.definir_capacite_capture(capture_id, capacites_module.capacite_pour_espece(pokemon_nom))

        # Phase 2 : captures ayant DÉJÀ un talent, mais qui ne correspond plus aux
        # vraies aptitudes curatées de leur espèce (attribué au hasard AVANT que cette
        # espèce précise ne soit curatée dans capacites.POKEMON_CAPACITES — ex: toutes
        # les curations faites au fil des sessions de talents légendaires/rares/peu
        # communs/communs). Ne touche QUE les espèces désormais curatées dont le talent
        # actuel de la capture n'en fait PLUS partie — jamais une capture déjà cohérente
        # avec sa curation actuelle, même si cette curation a valu plusieurs choix
        # possibles et que ce n'est pas celui qui aurait été tiré aujourd'hui.
        captures_avec_talent = database.obtenir_captures_avec_talent()
        nb_corrigees = 0
        for capture_id, pokemon_nom, capacite_actuelle in captures_avec_talent:
            possibles = capacites_module.POKEMON_CAPACITES.get(pokemon_nom)
            if possibles and capacite_actuelle not in possibles:
                database.definir_capacite_capture(capture_id, random.choice(possibles))
                nb_corrigees += 1

        journal.logger(
            f"🛠️ <@{interaction.user.id}> a lancé /backfill-talents : "
            f"{len(captures_sans_talent)} captures sans talent complétées, {nb_corrigees} captures incohérentes corrigées."
        )
        await interaction.followup.send(
            f"✅ Talent attribué à **{len(captures_sans_talent)}** captures qui n'en avaient pas encore "
            f"(d'avant l'introduction du système talents/objets), et **{nb_corrigees}** captures dont le talent "
            f"ne correspondait plus aux vraies aptitudes curatées de leur espèce ont été corrigées. "
            f"Relançable sans risque, ne touche jamais une capture déjà cohérente avec sa curation actuelle."
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

    @app_commands.command(
        name="reset-classement-roguelike",
        description="[Admin] Remet TOUT le classement Roguelike à zéro (irréversible)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_classement_roguelike(self, interaction: discord.Interaction):
        vue = _VueConfirmationResetRoguelike(interaction.user.id)
        await interaction.response.send_message(
            "⚠️ Ça va effacer **définitivement** le record de TOUS les joueurs au Roguelike "
            "(meilleur étage atteint). Les runs en cours ne sont pas touchées. Confirmer ?",
            view=vue,
            ephemeral=True,
        )


class _VueConfirmationResetRoguelike(discord.ui.View):
    """Confirmation à un clic avant un reset irréversible — même précaution que pour
    toute autre action destructive de ce genre dans le jeu (ex: abandon de combat)."""

    def __init__(self, admin_id: int):
        super().__init__(timeout=60)
        self.admin_id = admin_id

    @discord.ui.button(label="Confirmer le reset", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("Ce n'est pas ta confirmation !", ephemeral=True)
            return
        nb_effaces = database.reinitialiser_classement_roguelike()
        journal.logger(f"🛠️ <@{interaction.user.id}> a réinitialisé le classement Roguelike ({nb_effaces} records effacés).")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Classement Roguelike réinitialisé — **{nb_effaces}** records effacés.", view=self
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("Ce n'est pas ta confirmation !", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Reset annulé — rien n'a été touché.", view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminEconomieCog(bot))
