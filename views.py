import random

import discord

import config
import database
import etat_jeu
import leveling
import quetes_ui as quetes_ui_module
from pokemon_data import (
    ASTUCE_RARETE,
    EMOJI_BALLS,
    EMOJI_OBJETS_DIVERS,
    EMOJI_POKEDOLLAR,
    NOM_BALL_AFFICHAGE,
    NOM_OBJETS_DIVERS,
    TAUX_CAPTURE,
    sprite_pokemon,
)


class SelectionBallView(discord.ui.View):
    """Vue éphémère (visible seulement par le joueur) proposant son inventaire de balls.

    Un gros bouton par ball, chacun sur sa propre ligne, plutôt qu'un menu déroulant :
    sur mobile, les lignes denses d'un select (nom + quantité + taux sur une seule ligne)
    sont trop faciles à mal viser. Des boutons pleine largeur, bien séparés, réduisent
    nettement les mauvais clics."""

    def __init__(self, pokemon: dict, pc: int, vue_spawn: "VueSpawn", user_id: int):
        super().__init__(timeout=20)
        self.pokemon = pokemon
        self.pc = pc
        self.vue_spawn = vue_spawn
        self.user_id = user_id

        inventaire = database.obtenir_inventaire_balls(user_id)
        balls_disponibles = [
            (ball_type, inventaire.get(ball_type, 0))
            for ball_type in config.PRIX_BALLS
            if inventaire.get(ball_type, 0) > 0
        ]
        balls_disponibles.reverse()  # meilleure ball en dernier (en bas), pour limiter les clics accidentels

        if not balls_disponibles:
            bouton_vide = discord.ui.Button(
                label="Aucune ball disponible", style=discord.ButtonStyle.secondary, disabled=True
            )
            self.add_item(bouton_vide)
        else:
            for i, (ball_type, quantite) in enumerate(balls_disponibles):
                taux = min(
                    1.0,
                    TAUX_CAPTURE[pokemon["rarete"]][ball_type] * database.multiplicateur_boost(user_id, "capture"),
                )
                bouton = discord.ui.Button(
                    label=f"{NOM_BALL_AFFICHAGE[ball_type]} (x{quantite}) — {taux:.0%} de réussite",
                    emoji=EMOJI_BALLS.get(ball_type),
                    style=discord.ButtonStyle.primary,
                    row=i,
                )
                bouton.callback = self._creer_callback(ball_type)
                self.add_item(bouton)

    def _creer_callback(self, ball_type: str):
        async def callback(interaction: discord.Interaction):
            await self._traiter_capture(interaction, ball_type)

        return callback

    async def _traiter_capture(self, interaction: discord.Interaction, ball_type: str):
        user_id = interaction.user.id

        succes_retrait = database.retirer_ball(user_id, ball_type)
        if not succes_retrait:
            try:
                await interaction.response.edit_message(
                    content="Il semble que tu n'aies plus cette ball, réessaie.", view=None
                )
            except (discord.NotFound, discord.HTTPException):
                pass  # interaction expirée, rien de plus à faire
            return

        taux = min(1.0, TAUX_CAPTURE[self.pokemon["rarete"]][ball_type] * database.multiplicateur_boost(user_id, "capture"))
        reussite = random.random() < taux

        if reussite:
            # Vérifié AVANT l'ajout pour savoir si c'est une toute première capture de cette espèce
            nouvelle_entree = database.compter_captures_espece(user_id, self.pokemon["nom"]) == 0

            # Chance de shiny propre à CE joueur, indépendante des autres tentatives sur ce spawn
            chance_shiny = (
                config.CHANCE_SHINY_BASE
                * etat_jeu.obtenir_multiplicateur_shiny()
                * database.multiplicateur_boost(user_id, "shiny")
            )
            est_shiny = self.vue_spawn.force_shiny or (random.random() < chance_shiny)

            database.ajouter_capture(user_id, self.pokemon["nom"], self.pc, shiny=est_shiny)
            dollars_gagnes = round(10 * database.multiplicateur_boost(user_id, "argent"))
            database.ajouter_poke_dollars(user_id, dollars_gagnes)
            quetes_completees = database.incrementer_progression_quete(user_id, "capture", {"rarete": self.pokemon["rarete"]})

            # "Le Pokémon tenait quelque chose dans ses mains" — petite chance de Cristal de
            # Mutation ou d'Œuf, bien plus basse qu'au PokéStop (voir commentaire config.py :
            # les captures sont trop fréquentes pour réutiliser les mêmes probabilités).
            objet_trouve = None
            if random.random() < config.CHANCE_CRISTAL_CAPTURE:
                objet_trouve = "cristal_mutation"
            else:
                tirage_objet = random.random()
                seuil = 0.0
                for palier_oeuf, poids in config.OEUF_POIDS_CAPTURE.items():
                    seuil += poids
                    if tirage_objet < seuil:
                        objet_trouve = f"oeuf_{palier_oeuf}"
                        break
            if objet_trouve:
                database.ajouter_balls(user_id, objet_trouve, 1)

            xp_gagnee = config.XP_PAR_RARETE[self.pokemon["rarete"]]
            if est_shiny:
                xp_gagnee += config.XP_BONUS_SHINY
            # Affichage = montant RÉELLEMENT crédité (boost XP de Race/temporaire inclus), pas
            # le montant de base — gagner_xp() applique son propre multiplicateur en interne,
            # donc on le reproduit ici seulement pour le texte, sans le compter deux fois en base.
            xp_affichee = round(xp_gagnee * database.multiplicateur_boost(user_id, "xp"))
            niveau_avant, niveau_apres, recompenses_paliers = leveling.gagner_xp(user_id, xp_gagnee)

            if est_shiny:
                embed = discord.Embed(
                    title="✨ CAPTURE SHINY ! ✨",
                    description=(
                        f"Incroyable ! Tu as capturé un **{self.pokemon['nom']} shiny** "
                        f"({self.pc} PC) !\n+{dollars_gagnes} {EMOJI_POKEDOLLAR} Poké Dollars, +{xp_affichee} XP"
                        f"{quetes_ui_module.texte_notifications_completion(quetes_completees)}"
                    ),
                    color=discord.Color.gold(),
                )
                sprite_url = sprite_pokemon(self.pokemon, shiny=True)
            else:
                embed = discord.Embed(
                    title="🎉 Capture réussie !",
                    description=(
                        f"Tu as capturé **{self.pokemon['nom']}** "
                        f"({self.pc} PC) !\n+{dollars_gagnes} {EMOJI_POKEDOLLAR} Poké Dollars, +{xp_affichee} XP"
                        f"{quetes_ui_module.texte_notifications_completion(quetes_completees)}"
                    ),
                    color=discord.Color.green(),
                )
                sprite_url = sprite_pokemon(self.pokemon)

            if nouvelle_entree:
                embed.add_field(
                    name="📖 Nouvelle entrée !",
                    value=f"**{self.pokemon['nom']}** rejoint ton Pokédex pour la première fois !",
                    inline=False,
                )

            if objet_trouve:
                embed.add_field(
                    name=f"{EMOJI_OBJETS_DIVERS[objet_trouve]} Trouvaille !",
                    value=(
                        f"Le **{self.pokemon['nom']}** tenait un(e) {NOM_OBJETS_DIVERS[objet_trouve]} "
                        f"dans ses mains, tu l'obtiens donc !"
                    ),
                    inline=False,
                )

            for palier, dollars, ball_type in recompenses_paliers:
                embed.add_field(
                    name=f"🆙 Palier {palier} atteint (niveau {palier * 5}) !",
                    value=(
                        f"+{dollars} {EMOJI_POKEDOLLAR} Poké Dollars, "
                        f"+1× {EMOJI_BALLS[ball_type]} {NOM_BALL_AFFICHAGE[ball_type]}"
                    ),
                    inline=False,
                )

            if sprite_url:
                embed.set_thumbnail(url=sprite_url)
        else:
            embed = discord.Embed(
                title="💨 Il s'est échappé !",
                description=f"**{self.pokemon['nom']}** a fui malgré ta {NOM_BALL_AFFICHAGE[ball_type]}.",
                color=discord.Color.red(),
            )

        for item in self.children:
            item.disabled = True

        try:
            await interaction.response.edit_message(embed=embed, content=None, view=self)
        except (discord.NotFound, discord.HTTPException):
            # L'interaction a expiré (ex: clic trop tardif) — le résultat est déjà
            # appliqué en base (capture/ball déjà traitées), on tente juste de prévenir
            # le joueur autrement, sans planter le bot.
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                print(
                    f"⚠️ Interaction expirée : impossible de notifier {user_id} du résultat "
                    f"de sa capture, mais l'action a bien été appliquée en base."
                )
        self.stop()


class VueSpawn(discord.ui.View):
    """Vue attachée au message de spawn public. Chaque joueur peut tenter une seule capture."""

    def __init__(self, pokemon: dict, pc: int, force_shiny: bool = False):
        super().__init__(timeout=None)  # le spawn suivant remplacera celui-ci, pas de timeout fixe
        self.pokemon = pokemon
        self.pc = pc
        self.tentatives = set()
        self.force_shiny = force_shiny

    @discord.ui.button(label="Capturer", style=discord.ButtonStyle.primary, emoji="🎯")
    async def capturer(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id

        if user_id in self.tentatives:
            await interaction.response.send_message(
                "Tu as déjà tenté ta chance sur ce Pokémon !", ephemeral=True
            )
            return

        inventaire = database.obtenir_inventaire_balls(user_id)
        if not any(inventaire.get(ball_type, 0) > 0 for ball_type in config.PRIX_BALLS):
            await interaction.response.send_message(
                "Tu n'as plus aucune ball ! Va au PokéStop ou en boutique.", ephemeral=True
            )
            return  # pas de balls = pas de vraie tentative, on ne verrouille pas ce spawn pour lui

        limite_pokemon = database.limite_stockage_pokemon(user_id)
        if database.compter_captures_totales(user_id) >= limite_pokemon:
            await interaction.response.send_message(
                f"📦 Ton stockage est plein ({limite_pokemon}/{limite_pokemon}) ! "
                f"Utilise `/relacher` ou achète une extension en boutique.",
                ephemeral=True,
            )
            return  # stockage plein = pas de vraie tentative, on ne verrouille pas ce spawn pour lui

        # Verrouillé immédiatement : plusieurs clics rapides ne peuvent plus ouvrir
        # plusieurs menus de sélection en parallèle pour tenter plusieurs fois.
        self.tentatives.add(user_id)

        vue_selection = SelectionBallView(self.pokemon, self.pc, self, user_id)

        nb_possedes = database.compter_captures_espece(user_id, self.pokemon["nom"])
        if nb_possedes > 0:
            indication = f"📖 Tu en possèdes déjà **{nb_possedes}**."
        else:
            indication = "🆕 Tu n'as encore jamais capturé ce Pokémon !"

        await interaction.response.send_message(
            f"Quelle ball veux-tu utiliser pour **{self.pokemon['nom']}** ?\n{indication}",
            view=vue_selection,
            ephemeral=True,
        )


def construire_embed_spawn(pokemon: dict, pc: int, force_shiny: bool = False) -> discord.Embed:
    from pokemon_data import COULEUR_RARETE, EMOJI_RARETE, affichage_types

    emoji_rarete = EMOJI_RARETE[pokemon["rarete"]]
    types_affiches = affichage_types(pokemon["types"])

    titre = f"✨ {pokemon['nom'].upper()} SHINY SAUVAGE APPARAÎT ! ✨" if force_shiny else f"{pokemon['nom'].upper()} SAUVAGE APPARAÎT !"

    embed = discord.Embed(
        title=titre,
        color=discord.Color.gold() if force_shiny else COULEUR_RARETE[pokemon["rarete"]],
    )
    embed.add_field(name="Type", value=types_affiches, inline=True)
    embed.add_field(name="PC", value=f"💪 {pc}", inline=True)
    embed.add_field(
        name="Rareté", value=f"{emoji_rarete} {pokemon['rarete'].replace('_', ' ').upper()}", inline=False
    )
    if force_shiny:
        embed.add_field(name="✨ Événement spécial", value="Ce Pokémon est garanti shiny pour qui le capture !", inline=False)
    else:
        embed.add_field(name="💡 Astuce", value=ASTUCE_RARETE[pokemon["rarete"]], inline=False)

    sprite_url = sprite_pokemon(pokemon, shiny=force_shiny)
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    return embed
