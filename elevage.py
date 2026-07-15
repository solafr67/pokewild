import random
import time

import discord

import config
import database
import leveling
import quetes_ui
import race_ui
from pokemon_data import (
    EMOJI_OBJETS_DIVERS,
    NOM_OBJETS_DIVERS,
    generer_pc,
    sprite_pokemon,
    tirer_pokemon_par_rarete,
)


def _nom_oeuf(palier: str) -> str:
    return NOM_OBJETS_DIVERS.get(f"oeuf_{palier}", f"Œuf {palier}")


def _emoji_oeuf(palier: str) -> str:
    return EMOJI_OBJETS_DIVERS.get(f"oeuf_{palier}", "🥚")


def _duree_txt(secondes: int) -> str:
    if secondes >= 3600:
        return f"{secondes // 3600}h"
    return f"{secondes // 60}min"


def _oeufs_disponibles(user_id: int) -> list:
    """Liste des (palier, quantité) d'œufs possédés, dans l'ordre des paliers de rareté."""
    inventaire = database.obtenir_inventaire_balls(user_id)
    return [
        (palier, inventaire.get(f"oeuf_{palier}", 0))
        for palier in config.OEUF_PALIERS
        if inventaire.get(f"oeuf_{palier}", 0) > 0
    ]


# ----------------------------------------------------------------------------
# Message fixe du Laboratoire (Race + Incubateur)
# ----------------------------------------------------------------------------

def construire_embed_labo() -> discord.Embed:
    embed = discord.Embed(
        title="🧪 Le Laboratoire",
        description=(
            "Deux choses à faire ici :\n\n"
            "🧬 **Ta Race de dresseur** — bonus permanents, tirés avec un Cristal de Mutation "
            "(obtenu en Exploration).\n\n"
            "🥚 **Ton incubateur** — place un œuf trouvé au PokéStop ou en Exploration pour "
            "le faire éclore. Chaque palier d'œuf garantit un Pokémon de sa rareté (ou "
            "légèrement mieux, sauf Légendaire), avec une chance de shiny doublée par rapport "
            "à un spawn sauvage."
        ),
        color=discord.Color.teal(),
    )
    return embed


class VueLaboratoire(discord.ui.View):
    """Vue persistante attachée au message fixe du Laboratoire."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ma Race", style=discord.ButtonStyle.primary, emoji="🧬", custom_id="labo_race_bouton"
    )
    async def race(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = race_ui.construire_embed_race(interaction.user.id)
        vue = race_ui.VueRace(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(
        label="Mon incubateur", style=discord.ButtonStyle.success, emoji="🥚", custom_id="labo_incubateur_bouton"
    )
    async def incubateur(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, vue = construire_tableau_incubateur(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


# ----------------------------------------------------------------------------
# Incubateur
# ----------------------------------------------------------------------------

def construire_tableau_incubateur(user_id: int):
    row = database.obtenir_incubation_active(user_id)
    maintenant = int(time.time())
    embed = discord.Embed(title="🥚 Ton incubateur", color=discord.Color.teal())

    if row is None or row["palier"] is None:
        embed.add_field(name="Emplacement", value="*Libre*", inline=False)
    else:
        termine = row["date_fin"] <= maintenant
        statut = "✅ Prêt à éclore !" if termine else f"⏳ Éclosion <t:{row['date_fin']}:R>"
        embed.add_field(
            name="Emplacement",
            value=f"{_emoji_oeuf(row['palier'])} {_nom_oeuf(row['palier'])}\n{statut}",
            inline=False,
        )

    oeufs = _oeufs_disponibles(user_id)
    if oeufs:
        lignes = [f"{_emoji_oeuf(p)} {_nom_oeuf(p)} ×{q}" for p, q in oeufs]
        embed.add_field(name="🎒 Œufs en stock", value="\n".join(lignes), inline=False)
    else:
        embed.add_field(
            name="🎒 Œufs en stock",
            value="*Aucun pour l'instant — trouvables au PokéStop ou en Exploration.*",
            inline=False,
        )

    vue = VueTableauIncubateur(user_id, row, oeufs, maintenant)
    return embed, vue


class VueTableauIncubateur(discord.ui.View):
    def __init__(self, user_id: int, row, oeufs: list, maintenant: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        emplacement_libre = row is None or row["palier"] is None
        pret_a_eclore = not emplacement_libre and row["date_fin"] and row["date_fin"] <= maintenant

        if pret_a_eclore:
            bouton = discord.ui.Button(label="Récupérer l'éclosion", style=discord.ButtonStyle.success, emoji="🎉")
            bouton.callback = self._on_recuperer
            self.add_item(bouton)
        elif emplacement_libre and oeufs:
            options = [
                discord.SelectOption(
                    label=f"{_nom_oeuf(p)} (×{q})",
                    value=p,
                    description=f"Éclosion en {_duree_txt(config.OEUF_DUREE_INCUBATION[p])}",
                    emoji=_emoji_oeuf(p),
                )
                for p, q in oeufs
            ]
            select = discord.ui.Select(placeholder="Choisis un œuf à incuber...", options=options)
            select.callback = self._on_choisir
            self.add_item(select)
        # sinon : emplacement occupé mais pas encore prêt — rien à faire, juste attendre

    async def _verifier(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton incubateur !", ephemeral=True)
            return False
        return True

    async def _on_choisir(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        palier = interaction.data["values"][0]
        if not database.retirer_ball(self.user_id, f"oeuf_{palier}"):
            await interaction.response.send_message("Tu n'as plus cet œuf !", ephemeral=True)
            return
        database.demarrer_incubation(self.user_id, 1, palier, config.OEUF_DUREE_INCUBATION[palier])
        embed, vue = construire_tableau_incubateur(self.user_id)
        await interaction.response.edit_message(embed=embed, view=vue)

    async def _on_recuperer(self, interaction: discord.Interaction):
        if not await self._verifier(interaction):
            return
        embed_resultat = eclore_oeuf(self.user_id)
        await interaction.response.edit_message(embed=embed_resultat, view=None)


def eclore_oeuf(user_id: int) -> discord.Embed:
    """Fait éclore l'œuf prêt sur l'emplacement du joueur, crédite la capture, et retourne
    l'embed de résultat. Ne vérifie PAS que l'œuf est vraiment prêt — appelant responsable
    (le bouton "Récupérer" n'apparaît que si c'est le cas)."""
    row = database.obtenir_incubation_active(user_id)
    if row is None or row["palier"] is None:
        return discord.Embed(description="Aucun œuf prêt à éclore.", color=discord.Color.red())

    palier = row["palier"]
    database.terminer_incubation(user_id, 1)

    distribution = config.OEUF_DISTRIBUTION_ECLOSION[palier]
    rarete_resultat = random.choices(list(distribution.keys()), weights=list(distribution.values()))[0]
    pokemon = tirer_pokemon_par_rarete(rarete_resultat)
    pc = generer_pc(pokemon)

    chance_shiny = (
        config.CHANCE_SHINY_BASE
        * config.OEUF_MULTIPLICATEUR_SHINY
        * database.multiplicateur_boost(user_id, "shiny")
    )
    est_shiny = random.random() < chance_shiny

    nouvelle_entree = database.compter_captures_espece(user_id, pokemon["nom"]) == 0
    database.ajouter_capture(user_id, pokemon["nom"], pc, shiny=est_shiny)
    quetes_completees = database.incrementer_progression_quete(user_id, "capture", {"rarete": pokemon["rarete"]})

    xp_gagnee = config.XP_PAR_RARETE[pokemon["rarete"]]
    if est_shiny:
        xp_gagnee += config.XP_BONUS_SHINY
    # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
    # applique son propre multiplicateur en interne, on le reproduit ici pour le texte.
    xp_affichee = round(xp_gagnee * database.multiplicateur_boost(user_id, "xp"))
    leveling.gagner_xp(user_id, xp_gagnee)

    titre = "✨ ÉCLOSION SHINY ! ✨" if est_shiny else "🐣 Éclosion !"
    embed = discord.Embed(
        title=titre,
        description=(
            f"Ton {_emoji_oeuf(palier)} {_nom_oeuf(palier)} a éclos en "
            f"**{pokemon['nom']}**{' shiny' if est_shiny else ''} ({pc} PC) !\n"
            f"✨ +{xp_affichee} XP"
            f"{quetes_ui.texte_notifications_completion(quetes_completees)}"
        ),
        color=discord.Color.gold() if est_shiny else discord.Color.teal(),
    )
    if nouvelle_entree:
        embed.add_field(
            name="📖 Nouvelle entrée !",
            value=f"**{pokemon['nom']}** rejoint ton Pokédex pour la première fois !",
            inline=False,
        )

    sprite_url = sprite_pokemon(pokemon, shiny=est_shiny)
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    return embed
