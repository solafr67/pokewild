"""Cog : commandes joueur en libre-service sur les Pokémon (pokedex-info, equiper-objet,
objets-disponibles, verrouiller-pokemon, favoris, surnommer) + deux mini-jeux annexes
sandwichés entre elles dans l'original (defi-stats, plus-ou-moins). Sixième lot du
découpage en Cogs — voir cogs/admin_economie.py pour le contexte général.
"""

import discord
from discord import app_commands
from discord.ext import commands

import capacites as capacites_module
import config
import database
import defi_stats as defi_stats_module
import formes_objets as formes_objets_module
import mega_evolutions as mega_evolutions_module
import plus_ou_moins as plus_ou_moins_module
import pokedex as pokedex_module
from pokemon_data import obtenir_pokemon_par_nom
from profil import (
    construire_embed_favoris,
    construire_embed_surnoms,
    construire_embed_verrouillage,
    url_avatar_fiable,
    VueFavoris,
    VueSurnoms,
    VueVerrouillage,
)

# ⚠️ PAS de @app_commands.choices ici : Discord plafonne une liste de choix fixe à 25
# valeurs MAXIMUM (dépassement = bot.tree.sync() plante intégralement au démarrage,
# bloquant TOUT le reste de l'initialisation, spawns compris — vécu le 08/08/2026 en
# passant de 24 à 29 objets après l'ajout de 5 nouvelles formes par objet). Autocomplete
# n'a pas cette limite (juste ≤25 SUGGESTIONS affichées par frappe), donc résistant à
# n'importe quelle croissance future du nombre d'objets.
_OBJETS_TOUTES_FAMILLES = {
    **{cle: f"{info['nom']} — {info['description']}" for cle, info in capacites_module.OBJETS_TENUS.items()},
    **{
        cle: f"{info['objet_nom']} — Transforme {info['espece']} en {info['forme_nom']}"
        for cle, info in formes_objets_module.FORMES_OBJETS.items()
    },
    **{
        cle: f"{info['objet_nom']} — Méga-Évolue {info['espece']} en {info['forme_nom']} (combat uniquement)"
        for cle, info in mega_evolutions_module.MEGA_EVOLUTIONS.items()
    },
}


def _infos_objet_tenu_ou_forme(cle: str) -> dict | None:
    """Cherche une clé d'objet dans les 3 familles équipables : objets de combat
    classiques (capacites.OBJETS_TENUS), objets de transformation PERMANENTE
    (formes_objets.py), et Pierres Méga TEMPORAIRES limitées au combat
    (mega_evolutions.py) — trois dicts séparés avec des noms de champs légèrement
    différents, uniformisés ici en {emoji, nom, description}."""
    info_combat = capacites_module.infos_objet(cle)
    if info_combat:
        return info_combat
    info_forme = formes_objets_module.FORMES_OBJETS.get(cle)
    if info_forme:
        return {
            "emoji": info_forme["objet_emoji"],
            "nom": info_forme["objet_nom"],
            "description": f"Transforme {info_forme['espece']} en {info_forme['forme_nom']} tant qu'il le tient.",
        }
    info_mega = mega_evolutions_module.MEGA_EVOLUTIONS.get(cle)
    if info_mega:
        return {
            "emoji": info_mega["objet_emoji"],
            "nom": info_mega["objet_nom"],
            "description": (
                f"Permet à {info_mega['espece']} de Méga-Évoluer en {info_mega['forme_nom']} — "
                f"active-le avec le bouton dédié en combat (une fois par combat, dure jusqu'à la fin)."
            ),
        }
    return None


class GestionPokemonCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pokedex-info", description="Affiche la fiche détaillée d'un Pokémon précis")
    @app_commands.describe(membre="Voir la fiche chez un autre joueur (pratique pour les échanges) — toi par défaut")
    async def pokedex_info(self, interaction: discord.Interaction, nom: str, membre: discord.Member = None):
        cible = membre or interaction.user
        embed = pokedex_module.construire_embed_fiche(cible.id, nom)
        if embed is None:
            await interaction.response.send_message(f"❌ Pokémon **{nom}** introuvable dans la base.", ephemeral=True)
            return
        if membre:
            embed.set_author(name=f"Fiche consultée chez {membre.display_name}", icon_url=url_avatar_fiable(membre))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="equiper-objet", description="Équipe (ou retire) l'objet tenu d'un de tes Pokémon pour le combat")
    @app_commands.describe(
        pokemon="Nom de l'espèce (le meilleur exemplaire que tu possèdes la représente en combat)",
        objet="Objet à équiper — laisse vide pour retirer l'objet actuel",
    )
    async def equiper_objet(self, interaction: discord.Interaction, pokemon: str, objet: str = None):
        especes_possedees = {row["pokemon_nom"] for row in database.obtenir_pokedex_joueur(interaction.user.id)}
        pokemon_info = obtenir_pokemon_par_nom(pokemon)
        if pokemon_info is None or pokemon_info["nom"] not in especes_possedees:
            await interaction.response.send_message(f"❌ Tu ne possèdes aucun **{pokemon}**.", ephemeral=True)
            return

        ancien_objet = database.obtenir_objet_tenu_reel(interaction.user.id, pokemon_info["nom"])

        if objet is None:
            if ancien_objet is None:
                await interaction.response.send_message(f"**{pokemon_info['nom']}** ne tenait déjà aucun objet.", ephemeral=True)
                return
            database.definir_objet_tenu_reel(interaction.user.id, pokemon_info["nom"], None)
            database.ajouter_balls(interaction.user.id, ancien_objet, 1)  # rendu au sac, jamais perdu
            await interaction.response.send_message(f"✅ **{pokemon_info['nom']}** ne tient plus aucun objet — il est retourné dans ton sac.", ephemeral=True)
            return

        if objet not in _OBJETS_TOUTES_FAMILLES:
            await interaction.response.send_message(
                "❌ Objet inconnu — choisis-en un dans la liste proposée par l'autocomplétion.", ephemeral=True
            )
            return

        if objet == ancien_objet:
            await interaction.response.send_message(f"**{pokemon_info['nom']}** tient déjà cet objet.", ephemeral=True)
            return

        inventaire = database.obtenir_inventaire_balls(interaction.user.id)
        if inventaire.get(objet, 0) < 1:
            info_manquant = _infos_objet_tenu_ou_forme(objet)
            await interaction.response.send_message(
                f"❌ Tu n'as aucun(e) **{info_manquant['nom']}** dans ton sac — achète-le en boutique (onglet 🎒 Objets) "
                f"ou trouve-le en jeu si c'est un objet rarissime.",
                ephemeral=True,
            )
            return

        database.retirer_ball(interaction.user.id, objet)
        if ancien_objet:
            database.ajouter_balls(interaction.user.id, ancien_objet, 1)  # l'objet précédent revient au sac, jamais perdu

        info_objet = _infos_objet_tenu_ou_forme(objet)
        database.definir_objet_tenu_reel(interaction.user.id, pokemon_info["nom"], objet)
        await interaction.response.send_message(
            f"✅ **{pokemon_info['nom']}** tient maintenant {info_objet['emoji']} **{info_objet['nom']}** — {info_objet['description']}",
            ephemeral=True,
        )

    @equiper_objet.autocomplete("objet")
    async def _equiper_objet_autocomplete(self, interaction: discord.Interaction, current: str):
        current_lower = current.lower()
        resultats = [
            app_commands.Choice(name=label[:100], value=cle)
            for cle, label in _OBJETS_TOUTES_FAMILLES.items()
            if current_lower in label.lower() or current_lower in cle.lower()
        ]
        return resultats[:25]

    @app_commands.command(name="objets-disponibles", description="Liste tous les objets tenus équipables en combat")
    async def objets_disponibles_cmd(self, interaction: discord.Interaction):
        lignes = [
            f"{info['emoji']} **{info['nom']}** — {info['description']}"
            for info in capacites_module.OBJETS_TENUS.values()
        ]
        embed = discord.Embed(
            title="🎒 Objets tenus disponibles",
            description="\n".join(lignes) + "\n\nÉquipe-les avec `/equiper-objet`.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="defi-stats",
        description="Défie un joueur au Défi Base Stat — devinez la meilleure stat d'un Pokémon, pur fun sans récompense",
    )
    async def defi_stats_cmd(self, interaction: discord.Interaction, adversaire: discord.Member):
        if adversaire.id == interaction.user.id:
            await interaction.response.send_message("Tu ne peux pas te défier toi-même !", ephemeral=True)
            return
        if adversaire.bot:
            await interaction.response.send_message("Tu ne peux pas défier un bot !", ephemeral=True)
            return

        if not isinstance(interaction.channel, (discord.TextChannel, discord.VoiceChannel)):
            await interaction.response.send_message(
                "Cette commande doit être utilisée dans un channel classique (pas un fil).", ephemeral=True
            )
            return

        try:
            thread = await interaction.channel.create_thread(
                name=f"⚔️ Défi Base Stat : {interaction.user.display_name} vs {adversaire.display_name}",
                type=discord.ChannelType.public_thread,
            )
            await thread.add_user(interaction.user)
            await thread.add_user(adversaire)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Impossible de créer le fil : {e}", ephemeral=True)
            return

        vue = defi_stats_module.VueInvitationDefiStats(interaction.user, adversaire, self.bot, thread)
        await thread.send(
            f"⚔️ {adversaire.mention}, **{interaction.user.display_name}** te défie au **Défi Base Stat** ! "
            f"({config.DEFI_STATS_NB_ROUNDS} rounds — pur fun, aucune récompense). Tu acceptes ?",
            view=vue,
        )
        await interaction.response.send_message(f"Défi envoyé dans {thread.mention} !", ephemeral=True)

    @app_commands.command(
        name="plus-ou-moins",
        description="Mini-jeu solo : devine si le PC du prochain Pokémon est plus haut ou plus bas, enchaîne ta série !",
    )
    async def plus_ou_moins_cmd(self, interaction: discord.Interaction):
        actuel = plus_ou_moins_module.tirer_pokemon_pc()
        mystere = plus_ou_moins_module.tirer_pokemon_pc()
        embed = plus_ou_moins_module.construire_embed_manche(actuel, mystere, 0)
        vue = plus_ou_moins_module.VuePlusOuMoins(interaction.user.id, actuel, mystere, 0)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @app_commands.command(name="verrouiller-pokemon", description="Protège des doublons du relâcher automatique (/relacher) — plus besoin de les décocher à chaque fois")
    async def verrouiller_pokemon(self, interaction: discord.Interaction):
        vue = VueVerrouillage(interaction.user.id)
        if not vue.toutes_captures:
            await interaction.response.send_message("Tu n'as aucun Pokémon à verrouiller !", ephemeral=True)
            return
        await interaction.response.send_message(embed=construire_embed_verrouillage(interaction.user.id), view=vue, ephemeral=True)

    @app_commands.command(name="favoris", description="Épingle tes Pokémon préférés pour les retrouver vite dans tes listes")
    async def favoris_cmd(self, interaction: discord.Interaction):
        vue = VueFavoris(interaction.user.id)
        if not vue.toutes_captures:
            await interaction.response.send_message("Tu n'as aucun Pokémon à épingler en favori !", ephemeral=True)
            return
        await interaction.response.send_message(embed=construire_embed_favoris(interaction.user.id), view=vue, ephemeral=True)

    @app_commands.command(name="surnommer", description="Donne un surnom à un de tes Pokémon (pure personnalisation)")
    async def surnommer_cmd(self, interaction: discord.Interaction):
        vue = VueSurnoms(interaction.user.id)
        if not vue.toutes_captures:
            await interaction.response.send_message("Tu n'as aucun Pokémon à surnommer !", ephemeral=True)
            return
        await interaction.response.send_message(embed=construire_embed_surnoms(interaction.user.id), view=vue, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GestionPokemonCog(bot))
