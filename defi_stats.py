"""Mini-jeu 'Défi Base Stat' — pur fun, aucune récompense. Un Pokémon sauvage apparaît à
chaque round, les deux joueurs choisissent en secret la stat qu'ils pensent la plus haute
pour cette espèce ; celui qui a misé sur la plus haute remporte le round. Le meilleur score
après plusieurs rounds remporte le défi.
"""

import random

import discord

import config
from pokemon_data import EMOJI_RARETE, POKEDEX, sprite_pokemon

STATS_DEFI = [
    ("pv", "PV", "❤️"),
    ("attaque", "Attaque", "⚔️"),
    ("defense", "Défense", "🛡️"),
    ("attaque_spe", "Atq. Spé", "🔮"),
    ("defense_spe", "Déf. Spé", "🔰"),
    ("vitesse", "Vitesse", "💨"),
]


def _nom_stat(cle: str) -> str:
    return next(label for c, label, _ in STATS_DEFI if c == cle)


def tirer_pokemon_avec_stats() -> dict:
    """Tire un Pokémon au hasard parmi ceux qui ont leurs stats détaillées disponibles
    (maj_stats.py déjà lancé) — sinon retombe sur tout le pokédex, au risque d'un round
    sans stats affichables (cas très rare une fois maj_stats.py lancé une fois)."""
    candidats = [p for p in POKEDEX if p.get("stats_detaillees")]
    return random.choice(candidats) if candidats else random.choice(POKEDEX)


class VueDefiStats(discord.ui.View):
    """Vue du duel en cours : un message public partagé par les deux joueurs, dont les
    boutons enregistrent un choix en secret (réponse éphémère à celui qui clique) tant que
    l'autre joueur n'a pas encore choisi pour ce round."""

    def __init__(self, membre1: discord.Member, membre2: discord.Member):
        super().__init__(timeout=300)
        self.id1, self.id2 = membre1.id, membre2.id
        self.noms = {membre1.id: membre1.display_name, membre2.id: membre2.display_name}
        self.score = {membre1.id: 0, membre2.id: 0}
        self.round_actuel = 0
        self.historique = []
        self.termine = False
        self.choix = {}
        self.pokemon_actuel = None
        self._nouveau_round()

    def _nouveau_round(self):
        self.round_actuel += 1
        self.pokemon_actuel = tirer_pokemon_avec_stats()
        self.choix = {}
        self.clear_items()
        for cle, label, emoji in STATS_DEFI:
            bouton = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)
            bouton.callback = self._creer_callback(cle)
            self.add_item(bouton)

    def _creer_callback(self, cle: str):
        async def callback(interaction: discord.Interaction):
            await self._on_choix(interaction, cle)

        return callback

    async def _on_choix(self, interaction: discord.Interaction, cle: str):
        if interaction.user.id not in (self.id1, self.id2):
            await interaction.response.send_message("Ce défi ne te concerne pas !", ephemeral=True)
            return
        if interaction.user.id in self.choix:
            await interaction.response.send_message("Tu as déjà choisi pour ce round !", ephemeral=True)
            return

        self.choix[interaction.user.id] = cle
        autre_id = self.id2 if interaction.user.id == self.id1 else self.id1

        if autre_id not in self.choix:
            await interaction.response.send_message(
                f"Tu as choisi **{_nom_stat(cle)}** pour ce round — en attente de l'adversaire...",
                ephemeral=True,
            )
            return

        # Les deux joueurs ont choisi : on résout le round
        stats = self.pokemon_actuel["stats_detaillees"]
        cle_1, cle_2 = self.choix[self.id1], self.choix[self.id2]
        val_1, val_2 = stats.get(cle_1, 0), stats.get(cle_2, 0)

        if val_1 > val_2:
            self.score[self.id1] += 1
            resultat = f"🏆 {self.noms[self.id1]} gagne le round"
        elif val_2 > val_1:
            self.score[self.id2] += 1
            resultat = f"🏆 {self.noms[self.id2]} gagne le round"
        else:
            resultat = "🤝 Égalité sur ce round"

        self.historique.append(
            f"**{self.pokemon_actuel['nom']}** — {self.noms[self.id1]} : {_nom_stat(cle_1)} ({val_1}) vs "
            f"{self.noms[self.id2]} : {_nom_stat(cle_2)} ({val_2}) → {resultat}"
        )

        if self.round_actuel >= config.DEFI_STATS_NB_ROUNDS:
            self.termine = True
            self.clear_items()
            self.stop()
        else:
            self._nouveau_round()

        await interaction.response.edit_message(embed=self._construire_embed(), view=self)

    def _construire_embed(self) -> discord.Embed:
        embed = discord.Embed(title="⚔️ Défi Base Stat", color=discord.Color.blurple())

        if self.historique:
            # Les 5 derniers rounds suffisent à garder l'embed lisible
            embed.add_field(name="Historique", value="\n".join(self.historique[-5:]), inline=False)

        if self.termine:
            if self.score[self.id1] > self.score[self.id2]:
                gagnant = f"🎉 **{self.noms[self.id1]}** remporte le défi !"
            elif self.score[self.id2] > self.score[self.id1]:
                gagnant = f"🎉 **{self.noms[self.id2]}** remporte le défi !"
            else:
                gagnant = "🤝 Défi terminé à égalité !"
            embed.add_field(name="Résultat final", value=gagnant, inline=False)
        else:
            emoji_rarete = EMOJI_RARETE.get(self.pokemon_actuel["rarete"], "")
            embed.add_field(
                name=f"Round {self.round_actuel}/{config.DEFI_STATS_NB_ROUNDS} — {emoji_rarete} {self.pokemon_actuel['nom']}",
                value="Chacun choisit en secret la stat qu'il pense la plus haute pour ce Pokémon !",
                inline=False,
            )
            sprite = sprite_pokemon(self.pokemon_actuel)
            if sprite:
                embed.set_thumbnail(url=sprite)

        embed.set_footer(
            text=f"Score — {self.noms[self.id1]} : {self.score[self.id1]} | {self.noms[self.id2]} : {self.score[self.id2]}"
        )
        return embed

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class VueInvitationDefiStats(discord.ui.View):
    """Invitation avant de démarrer le duel — évite de lancer un défi non désiré."""

    def __init__(self, challenger: discord.Member, adversaire: discord.Member):
        super().__init__(timeout=120)
        self.challenger = challenger
        self.adversaire = adversaire

        bouton_accepter = discord.ui.Button(label="Accepter", emoji="⚔️", style=discord.ButtonStyle.success)
        bouton_accepter.callback = self._on_accepter
        self.add_item(bouton_accepter)

        bouton_refuser = discord.ui.Button(label="Refuser", emoji="❌", style=discord.ButtonStyle.secondary)
        bouton_refuser.callback = self._on_refuser
        self.add_item(bouton_refuser)

    async def _on_accepter(self, interaction: discord.Interaction):
        if interaction.user.id != self.adversaire.id:
            await interaction.response.send_message("Cette invitation ne t'est pas destinée !", ephemeral=True)
            return
        vue = VueDefiStats(self.challenger, self.adversaire)
        await interaction.response.edit_message(content=None, embed=vue._construire_embed(), view=vue)

    async def _on_refuser(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.adversaire.id, self.challenger.id):
            await interaction.response.send_message("Cette invitation ne te concerne pas !", ephemeral=True)
            return
        self.clear_items()
        await interaction.response.edit_message(
            content=f"❌ {self.adversaire.display_name} n'a pas donné suite au défi.", embed=None, view=None
        )
