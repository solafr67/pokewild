import random

import discord

import config
import database
import quetes as quetes_module
from pokemon_data import EMOJI_POKEDOLLAR, EMOJI_SOINS, NOM_OBJETS_DIVERS, NOM_SOIN_AFFICHAGE

OBJETS_BONUS_JOUR = ["hyperball", "totalsoin"]


def _guide_pour_evenement(evenement: str) -> str:
    """Petit texte pratique pointant vers où aller / quelle commande utiliser pour cet
    objectif — un nouveau joueur ne sait pas forcément où trouver "l'Arène" ou comment
    défier Gladio juste en lisant le nom de l'objectif. Mentions de channel dynamiques
    (pas de texte codé en dur avec le nom du channel, qui pourrait changer)."""
    spawn = f"<#{config.CHANNEL_SPAWN_CLASSIQUE_ID}> ou <#{config.CHANNEL_SPAWN_VIP_ID}>"
    aventure = f"<#{config.CHANNEL_AVENTURE_ID}>"
    guides = {
        "capture": f"💡 Capture des Pokémon sauvages dans {spawn}.",
        "pve_victoire": f"💡 Défie un Dresseur, dans {aventure}.",
        "badge_arene": f"💡 Affronte l'Arène (Apprenti puis Champion) dans {aventure}.",
        "badge_repaire": f"💡 Infiltre un Repaire de méchants dans {aventure}.",
        "pvp_victoire": "💡 Défie un autre joueur avec `/defier`, dans n'importe quel channel.",
        "raid_victoire": f"💡 Rejoins un Raid — ils apparaissent périodiquement dans {spawn}.",
        "gladio_victoire": "💡 Utilise `/gladio` pour voir où en est ton rival et le défier.",
    }
    return guides.get(evenement, "")


def construire_embed_quete_principale(user_id: int) -> discord.Embed:
    """Fiche de la quête principale (narration) — chapitre en cours avec son texte
    d'intro et la progression, ou l'écran de fin si tous les chapitres sont complétés."""
    progression = database.obtenir_progression_quete_principale(user_id)
    chapitres = config.QUETE_PRINCIPALE_CHAPITRES

    if progression["termine"]:
        return discord.Embed(
            title="🏅 Quête principale — Terminée !",
            description=(
                "Tu as vécu tous les chapitres de ton histoire de dresseur — Gladio "
                "lui-même reconnaît ta force. Le reste de l'aventure PokéWild continue, "
                "bien sûr, mais ce fil narratif s'arrête ici pour toi.\n\n"
                "Merci d'avoir suivi l'histoire jusqu'au bout !"
            ),
            color=discord.Color.gold(),
        )

    index = progression["chapitre"] - 1
    chapitre = chapitres[index]
    barre = "🟩" * progression["compteur"] + "⬜" * (chapitre["cible"] - progression["compteur"])

    description = chapitre["intro"]
    guide = _guide_pour_evenement(chapitre["evenement"])
    if guide:
        description += f"\n\n{guide}"

    embed = discord.Embed(
        title=f"📖 Quête principale — Chapitre {progression['chapitre']}/{len(chapitres)} : {chapitre['titre']}",
        description=description,
        color=discord.Color.purple(),
    )
    embed.add_field(
        name="Progression",
        value=f"{barre}\n{progression['compteur']}/{chapitre['cible']}",
        inline=False,
    )
    recompense = chapitre["recompense"]
    lignes_recompense = [f"{EMOJI_POKEDOLLAR} {recompense['dollars']} PD", f"✨ {recompense['xp']} XP"]
    if recompense.get("objet"):
        lignes_recompense.append(f"🎁 {recompense['objet'].replace('_', ' ').title()}")
    embed.add_field(name="Récompense du chapitre", value=" · ".join(lignes_recompense), inline=False)
    embed.set_footer(text="Cette quête suit ce que tu fais déjà dans le jeu — rien à faire de spécial, continue de jouer !")
    return embed


def texte_notifications_completion(completions: list) -> str:
    """Formate un texte court à afficher juste après une action qui vient de compléter
    une ou plusieurs quêtes (jour/semaine), pour prévenir le joueur immédiatement plutôt
    que de le laisser découvrir ça en allant checker /quetes plus tard."""
    if not completions:
        return ""
    if len(completions) == 1:
        q = completions[0]
        return f"\n\n📜 Quête complétée : {q['emoji']} **{q['nom']}** — va la réclamer avec `/quetes` !"
    lignes = "\n".join(f"{q['emoji']} **{q['nom']}**" for q in completions)
    return f"\n\n📜 Quêtes complétées :\n{lignes}\nVa les réclamer avec `/quetes` !"


def construire_embed_centre() -> discord.Embed:
    embed = discord.Embed(
        title="📜 Quêtes",
        description=(
            "Des objectifs journaliers et hebdomadaires pour te récompenser de ce que tu "
            "fais déjà — capturer, raider, combattre, explorer. Reset chaque jour à minuit "
            "(UTC), et chaque semaine.\n\n"
            "Des **accomplissements** à paliers existent aussi, avec un titre cosmétique "
            "à afficher sur ton profil.\n\n"
            "📃 Un PNJ te propose aussi 3 **Contrats** tirés au sort chaque jour — des "
            "missions ponctuelles (capture ciblée, combats...) payées sur le champ dès "
            "qu'elles sont remplies, mais qui disparaissent si tu ne les termines pas "
            "avant le reset du lendemain."
        ),
        color=discord.Color.dark_teal(),
    )
    return embed


class VueCentreQuetes(discord.ui.View):
    """Vue persistante attachée au message fixe du channel Quêtes."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Voir mes quêtes", style=discord.ButtonStyle.primary, emoji="📜", custom_id="quetes_voir")
    async def voir(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, vue = construire_tableau_de_bord(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)

    @discord.ui.button(label="Quête principale", style=discord.ButtonStyle.secondary, emoji="📖", custom_id="quetes_principale_voir")
    async def voir_principale(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = construire_embed_quete_principale(interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Contrats", style=discord.ButtonStyle.secondary, emoji="📃", custom_id="quetes_contrats_voir")
    async def voir_contrats(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = construire_embed_contrats(interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)


def construire_embed_contrats(user_id: int) -> discord.Embed:
    contrats = database.obtenir_contrats_du_jour(user_id)
    embed = discord.Embed(
        title="📃 Contrats du jour",
        description="Payés automatiquement dès qu'ils sont remplis — mais ils disparaissent au reset de demain si tu ne les termines pas à temps.",
        color=discord.Color.dark_gold(),
    )
    for contrat in contrats:
        if contrat["complete"]:
            statut = "✅ Remplie !"
        else:
            statut = f"{contrat['compteur']}/{contrat['cible']}"
        recompense = contrat["recompense"]
        morceaux_recompense = [f"{recompense['dollars']} {EMOJI_POKEDOLLAR}", f"{recompense['xp']} XP"]
        if recompense.get("objet"):
            cle_objet, quantite = recompense["objet"]
            morceaux_recompense.append(f"{quantite}× {NOM_OBJETS_DIVERS.get(cle_objet, cle_objet)}")
        embed.add_field(
            name=f"{contrat['emoji']} {contrat['nom']}",
            value=f"{statut}\n💰 {', '.join(morceaux_recompense)}",
            inline=False,
        )
    return embed


def _ligne_quete(user_id: int, quete: dict, type_quete: str) -> str:
    compteur, reclamee = database.obtenir_progression_quete(user_id, quete["id"], type_quete)
    if reclamee:
        return f"{quete['emoji']} ~~{quete['nom']}~~ ✅ Réclamée"
    statut = "✅ Complète !" if compteur >= quete["cible"] else f"{compteur}/{quete['cible']}"
    return f"{quete['emoji']} **{quete['nom']}** — {statut}"


def construire_tableau_de_bord(user_id: int):
    embed = discord.Embed(title="📜 Tes quêtes", color=discord.Color.dark_teal())

    lignes_jour = [_ligne_quete(user_id, q, "jour") for q in quetes_module.QUETES_JOUR]
    embed.add_field(name="🔄 Journalières", value="\n".join(lignes_jour), inline=False)

    lignes_semaine = [_ligne_quete(user_id, q, "semaine") for q in quetes_module.QUETES_SEMAINE]
    embed.add_field(name="📅 Hebdomadaires", value="\n".join(lignes_semaine), inline=False)

    nb_completes = sum(
        1 for q, t in [(q, "jour") for q in quetes_module.QUETES_JOUR] + [(q, "semaine") for q in quetes_module.QUETES_SEMAINE]
        if database.obtenir_progression_quete(user_id, q["id"], t)[0] >= q["cible"]
        and not database.obtenir_progression_quete(user_id, q["id"], t)[1]
    )
    if nb_completes:
        embed.set_footer(text=f"🎁 {nb_completes} quête(s) prête(s) à réclamer !")

    vue = VueTableauDeBordQuetes(user_id)
    return embed, vue


class VueTableauDeBordQuetes(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="Réclamer tout", emoji="🎁", style=discord.ButtonStyle.success, row=0)
    async def reclamer_tout(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton tableau de bord !", ephemeral=True)
            return
        embed = reclamer_toutes_quetes_pretes(self.user_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Accomplissements", emoji="🏆", style=discord.ButtonStyle.secondary, row=0)
    async def accomplissements(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ton tableau de bord !", ephemeral=True)
            return
        embed = construire_embed_accomplissements(self.user_id)
        vue = VueAccomplissements(self.user_id)
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)


def reclamer_toutes_quetes_pretes(user_id: int) -> discord.Embed:
    total_dollars = 0
    total_xp = 0
    total_cristaux = 0
    objets_bonus = {}  # nom_objet -> quantité, affiché groupé sous l'argent/XP
    lignes = []

    for type_quete, catalogue, recompense_base, chance_bonus in (
        ("jour", quetes_module.QUETES_JOUR, config.QUETE_RECOMPENSE_JOUR, config.QUETE_CHANCE_OBJET_BONUS_JOUR),
        ("semaine", quetes_module.QUETES_SEMAINE, config.QUETE_RECOMPENSE_SEMAINE, config.QUETE_CHANCE_CRISTAL_SEMAINE),
    ):
        for quete in catalogue:
            if not database.reclamer_quete(user_id, quete["id"], type_quete):
                continue

            dollars = round(recompense_base["dollars"] * database.multiplicateur_boost(user_id, "argent"))
            xp = recompense_base["xp"]
            # Affichage = XP réellement créditée (boost de Race/temporaire inclus) — gagner_xp()
            # applique son propre multiplicateur en interne, on le reproduit ici pour le texte.
            xp_affichee = round(xp * database.multiplicateur_boost(user_id, "xp"))
            database.ajouter_poke_dollars(user_id, dollars)
            import leveling
            leveling.gagner_xp(user_id, xp)
            total_dollars += dollars
            total_xp += xp_affichee

            if type_quete == "jour" and random.random() < chance_bonus:
                objet = random.choice(OBJETS_BONUS_JOUR)
                database.ajouter_balls(user_id, objet, 1)
                objets_bonus[objet] = objets_bonus.get(objet, 0) + 1
            elif type_quete == "semaine" and random.random() < chance_bonus:
                database.ajouter_balls(user_id, "cristal_mutation", 1)
                total_cristaux += 1

            lignes.append(f"{quete['emoji']} {quete['nom']}")

    if not lignes:
        return discord.Embed(
            description="Aucune quête prête à être réclamée pour le moment.",
            color=discord.Color.dark_grey(),
        )

    description = (
        "\n".join(lignes)
        + f"\n\n{EMOJI_POKEDOLLAR} **+{total_dollars}** Poké Dollars\n"
        f"✨ **+{total_xp}** XP"
    )
    for objet, quantite in objets_bonus.items():
        emoji = EMOJI_SOINS.get(objet, "")
        nom = NOM_SOIN_AFFICHAGE.get(objet, objet)
        description += f"\n{emoji} **+{quantite}** {nom} *(bonus)*"
    if total_cristaux:
        description += f"\n🔮 **+{total_cristaux}** Cristal(aux) de Mutation !"

    return discord.Embed(title=f"🎁 {len(lignes)} quête(s) réclamée(s) !", description=description, color=discord.Color.gold())


# ----------------------------------------------------------------------------
# Accomplissements
# ----------------------------------------------------------------------------

def valeurs_accomplissements(user_id: int) -> dict:
    """Calcule la valeur actuelle du joueur pour chaque catégorie d'accomplissement,
    à partir des données déjà existantes (aucun compteur dédié à maintenir)."""
    import leveling
    from pokemon_data import obtenir_pokemon_par_nom

    captures = database.obtenir_pokedex_joueur(user_id)
    nb_shiny = sum(row["quantite"] for row in captures if row["shiny"])
    nb_legendaire = sum(
        1 for row in captures
        if (obtenir_pokemon_par_nom(row["pokemon_nom"]) or {}).get("rarete") == "legendaire"
    )
    nb_especes = len({row["pokemon_nom"] for row in captures})
    niveau, _, _ = leveling.progression_niveau(database.obtenir_xp(user_id))
    victoires_pvp = database.obtenir_victoires_pvp(user_id)

    return {
        "shiny": nb_shiny,
        "legendaire": nb_legendaire,
        "pvp": victoires_pvp,
        "niveau": niveau,
        "pokedex": nb_especes,
    }


def construire_embed_accomplissements(user_id: int) -> discord.Embed:
    valeurs = valeurs_accomplissements(user_id)
    titre_actif = database.obtenir_titre_actif(user_id)

    embed = discord.Embed(title="🏆 Tes accomplissements", color=discord.Color.gold())
    if titre_actif:
        palier = quetes_module.palier_atteint(titre_actif, valeurs[titre_actif])
        embed.description = f"Titre affiché : **{quetes_module.titre_complet(titre_actif, palier)}**"
    else:
        embed.description = "Aucun titre affiché pour l'instant."

    for categorie, info in quetes_module.ACCOMPLISSEMENTS.items():
        valeur = valeurs[categorie]
        palier = quetes_module.palier_atteint(categorie, valeur)
        paliers = info["paliers"]

        if palier >= len(paliers):
            statut = f"✅ Maximum atteint ({paliers[-1]})"
        else:
            prochain = paliers[palier]
            statut = f"{valeur}/{prochain} pour le palier {palier + 1}"

        titre_actuel = quetes_module.titre_complet(categorie, palier) or "*Aucun palier atteint*"
        embed.add_field(
            name=f"{info['emoji']} {info['nom_categorie']}",
            value=f"{titre_actuel}\n{statut}",
            inline=False,
        )

    return embed


class VueAccomplissements(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

        valeurs = valeurs_accomplissements(user_id)
        options = []
        for categorie, info in quetes_module.ACCOMPLISSEMENTS.items():
            palier = quetes_module.palier_atteint(categorie, valeurs[categorie])
            if palier > 0:
                options.append(
                    discord.SelectOption(
                        label=quetes_module.titre_complet(categorie, palier),
                        value=categorie,
                        emoji=info["emoji"],
                    )
                )

        select = discord.ui.Select(
            placeholder="Choisir le titre à afficher sur ton profil..." if options else "Aucun titre débloqué pour l'instant",
            options=options if options else [discord.SelectOption(label="Aucun", value="none")],
            disabled=not options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas ta sélection !", ephemeral=True)
            return
        categorie = interaction.data["values"][0]
        database.definir_titre_actif(self.user_id, categorie)
        embed = construire_embed_accomplissements(self.user_id)
        await interaction.response.edit_message(embed=embed, view=self)
