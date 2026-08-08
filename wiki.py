"""Wiki interactif de PokéWild — un message fixe (config.CHANNEL_WIKI_ID) avec un menu
déroulant listant chaque système du jeu ; sélectionner une catégorie affiche son
explication. Accessible aussi partout via /wiki (vue éphémère identique).

Le contenu vit dans PAGES, un simple dict {clé: {titre, emoji, texte}} — pour ajouter ou
retoucher une section, il suffit de modifier ce dict, rien d'autre à toucher.
"""

import discord

PAGES = {
    "demarrage": {
        "titre": "Démarrer",
        "emoji": "🐣",
        "texte": (
            "**Bienvenue dans PokéWild !**\n\n"
            "Les Pokémon apparaissent automatiquement dans les channels de spawn "
            "(Classique et VIP) — clique sur **Capturer** et choisis ta ball. Chaque "
            "capture donne de l'XP de dresseur et, si le Pokémon fait partie de ton "
            "équipe de combat, de l'XP pour lui aussi.\n\n"
            "**Premiers réflexes utiles :**\n"
            "• `/equipe-combat` — compose ton équipe de 6 Pokémon max\n"
            "• `/pokedex` — vois ce que tu as déjà capturé\n"
            "• `/profil` — ton niveau de dresseur, tes Poké Dollars, tes objets\n"
            "• `/equipe` — choisis ton clan\n\n"
            "Consulte les autres pages de ce wiki pour approfondir chaque système."
        ),
    },
    "capture": {
        "titre": "Capture & Spawns",
        "emoji": "🎯",
        "texte": (
            "Des Pokémon sauvages apparaissent régulièrement dans les channels de spawn "
            "**Classique** et **VIP** (le VIP a de meilleures chances de rareté). Chaque "
            "spawn affiche son PC et son **niveau** — plus la rareté est haute, plus la "
            "fourchette de niveau au spawn est élevée.\n\n"
            "**Balls disponibles** : Poké Ball, Super Ball, Hyper Ball, Master Ball — "
            "plus la ball est bonne, plus la chance de capture est haute. Les balls "
            "s'obtiennent au PokéStop, en quêtes, en récompense de raid...\n\n"
            "Chaque Pokémon capturé a de vrais **IV individuels** (6 stats tirées "
            "indépendamment) — deux individus de la même espèce ne sont jamais "
            "identiques. Ton meilleur exemplaire d'une espèce est celui utilisé partout "
            "(équipe, combat, Pokédex).\n\n"
            "**Formes régionales** (Alola, Galar, Hisui, Paldea) — de vraies entrées de "
            "Pokédex à part entière, capturables comme n'importe quel autre Pokémon, "
            "juste regroupées avec leur forme de base une fois attrapées."
        ),
    },
    "niveau_stats": {
        "titre": "Niveau & Statistiques",
        "emoji": "⭐",
        "texte": (
            "Chaque Pokémon a un **niveau** (jusqu'à 100) et de vraies **statistiques** "
            "(PV, Attaque, Défense, Attaque Spé, Défense Spé, Vitesse), calculées avec "
            "les formules officielles des jeux à partir de ses IV et de son niveau.\n\n"
            "**Seuls les Pokémon de ton équipe de combat active gagnent de l'XP**, via "
            "capture, PokéStop, quêtes, raids, dresseurs, PvP... Équipe vide = XP perdue, "
            "alors garde toujours une équipe configurée (`/equipe-combat`) !\n\n"
            "Le **PC** reste affiché (façon Pokémon GO) mais n'est plus qu'un résumé "
            "pratique — ce sont les vraies stats qui comptent en combat.\n\n"
            "Consulte `/pokedex-info <nom>` pour voir le détail complet d'un Pokémon "
            "(niveau, stats, hexagone)."
        ),
    },
    "combat_pvp": {
        "titre": "Combat PvP",
        "emoji": "⚔️",
        "texte": (
            "Défie un autre joueur en duel — combat au tour par tour dans un fil dédié, "
            "avec PP à gérer, statuts (poison, brûlure...), boosts de stats, et des "
            "attaques à 2 tours pour les plus puissantes. Les dégâts suivent la vraie "
            "formule officielle des jeux (type, STAB, stats réelles, niveau).\n\n"
            "**Attaques** : à équiper au Maître des Types (voir cette page) — 4 "
            "emplacements par Pokémon, débloquées par niveau ou par CT.\n\n"
            "**Trois formats disponibles :**\n"
            "• `/defier` — 1v1 classique, 1 Pokémon actif chacun\n"
            "• `/combat-2v2` — 1v1 en **double combat** : équipe complète (jusqu'à 6), "
            "2 Pokémon actifs simultanément chacun\n"
            "• `/combat-2v2-equipe` — lobby à 4 joueurs, 2 équipes de 2, 3 Pokémon chacun\n\n"
            "Enchaîne les victoires pour faire grimper ta **série de victoires PvP** "
            "(visible au classement, et Gladio le remarque)."
        ),
    },
    "raids": {
        "titre": "Raids",
        "emoji": "🐉",
        "texte": (
            "Un boss sauvage (1 à 5 étoiles) apparaît, une salle d'attente s'ouvre — "
            "rejoins-la avant le lancement du combat. Une fois lancé, ton équipe "
            "attaque automatiquement toutes les 5 secondes pendant 15 minutes max, et le "
            "boss riposte à chaque tour.\n\n"
            "**Coopératif** : plusieurs joueurs peuvent affronter le même boss en même "
            "temps, les dégâts de chacun s'additionnent sur le même total de PV. "
            "Vaincu, il devient capturable pour chaque participant (plusieurs tentatives "
            "possibles).\n\n"
            "Plus il y a d'étoiles, plus le boss est costaud et les récompenses "
            "généreuses.\n\n"
            "Envie d'être prévenu à chaque nouveau raid ? Clique sur **🔔 Notifications "
            "Raid** dans le channel dédié pour (dés)activer le rôle de ping."
        ),
    },
    "dresseurs_gladio": {
        "titre": "Dresseurs & Gladio",
        "emoji": "🥾",
        "texte": (
            "Des **dresseurs PNJ** apparaissent spontanément dans certains channels — "
            "clique sur **Défier** pour un combat contre une équipe calibrée sur la "
            "puissance actuelle de la tienne.\n\n"
            "Environ 1 apparition sur 5 est un **Duo** (Duo Cyclone, Duo Belladone...) "
            "— deux dresseurs affrontés en même temps, en double combat : tu contrôles "
            "alors 2 Pokémon actifs simultanément face à leurs 6 Pokémon chacun.\n\n"
            "**Gladio, ton rival**, est différent : \n"
            "• `/defi-gladio` — un vrai combat, une fois par jour, équipe de 6 Pokémon "
            "Rare et au-dessus, légèrement plus forte que la tienne, récompense fixe de "
            "400 à 600 Poké Dollars\n"
            "• `/gladio` — voir où tu en es avec lui (il se souvient de vos échanges et "
            "son ton évolue avec le temps — distant, puis familier, puis un vrai respect)\n\n"
            "Il commente aussi certains de tes exploits (capture shiny, légendaire, "
            "victoire de raid, série PvP...) directement dans le fil concerné."
        ),
    },
    "maitre_types": {
        "titre": "Maître des Types (CT)",
        "emoji": "🧙",
        "texte": (
            "Le PNJ qui gère les **attaques** de tes Pokémon — 4 emplacements par "
            "Pokémon, 1 par 1.\n\n"
            "**Gratuit** : toute attaque que ton Pokémon connaît déjà naturellement à "
            "son niveau actuel.\n"
            "**CT (payante)** : pour apprendre une attaque avant d'avoir le niveau "
            "requis, achète sa CT à la **Boutique CT** — une fois achetée, elle est à "
            "toi pour toujours, utilisable sur n'importe lequel de tes Pokémon, sans "
            "limite. Filtrable par type et catégorie (Physique/Spécial/Statut)."
        ),
    },
    "maitre_capacites": {
        "titre": "Maître des Capacités (talents & objets tenus)",
        "emoji": "🎒",
        "texte": (
            "Le PNJ qui gère le **talent** et l'**objet tenu** de tes Pokémon (en plus "
            "de leurs attaques, voir \"Maître des Types\").\n\n"
            "🧬 **Talent** — attribué automatiquement à la capture, fidèle à sa vraie "
            "capacité dans les jeux quand elle est connue (ex : Salamèche → Brasier).\n\n"
            "🎒 **Objet tenu** — bouton \"Objets tenus\" pour équiper un objet de ton "
            "sac à un Pokémon (Reste, Orbe Vie, objets Choix...) — achetables à la "
            "**Boutique**, onglet Objets.\n\n"
            "💎 **Objets de transformation** — une poignée d'objets rarissimes (jamais "
            "en boutique, uniquement trouvables en Exploration ou à la capture) "
            "transforment certaines légendaires tant qu'elles les tiennent (Dialga + "
            "Orbe Adamant → Dialga Origine, Kyogre + Orbe Bleue → Primo-Kyogre...) — "
            "stats et types changent, le PC affiché ne bouge jamais."
        ),
    },
    "exploration": {
        "titre": "Centre des Explorations",
        "emoji": "🗺️",
        "texte": (
            "Envoie une équipe de 3 Pokémon explorer pendant 1h, 6h ou 24h — ils sont "
            "indisponibles en combat/raid pendant ce temps, mais rapportent Poké "
            "Dollars, XP, une chance de Cristal de Mutation et une chance d'Œuf à leur "
            "retour.\n\n"
            "Plus ton équipe envoyée est puissante (PC cumulé), meilleure est la "
            "récompense, jusqu'à un plafond. Le rendement par heure augmente aussi avec "
            "la durée choisie — une expédition de 24h rapporte proportionnellement plus "
            "qu'enchaîner des 1h."
        ),
    },
    "laboratoire": {
        "titre": "Laboratoire (Œufs)",
        "emoji": "🥚",
        "texte": (
            "Fais éclore les Œufs trouvés en exploration ou au PokéStop — un incubateur "
            "à la fois. Le Pokémon obtenu dépend du palier de l'œuf (Commun à "
            "Légendaire), et éclot directement à un niveau cohérent avec sa rareté "
            "(comme un spawn sauvage).\n\n"
            "Le Laboratoire abrite aussi la **Race de dresseur** — utilise un Cristal de "
            "Mutation (obtenu en exploration, PokéStop, ou en Passe Saisonnier) pour "
            "tenter ta chance."
        ),
    },
    "quetes": {
        "titre": "Quêtes",
        "emoji": "📜",
        "texte": (
            "Des objectifs **journaliers** et **hebdomadaires**, reset à heure fixe "
            "pour tout le monde. Les termine pour des Poké Dollars, de l'XP, et une "
            "chance d'objet bonus (plus rare sur les quêtes hebdomadaires).\n\n"
            "Consulte `/quetes` pour voir ta progression actuelle."
        ),
    },
    "echanges": {
        "titre": "Échanges",
        "emoji": "🔄",
        "texte": (
            "Propose un échange à un autre joueur — une grille visuelle avec les "
            "sprites de vos Pokémon respectifs pour choisir facilement quoi donner et "
            "recevoir, avec un bouton de recherche pour retrouver vite un Pokémon "
            "précis dans une grosse collection. Les deux joueurs doivent confirmer "
            "avant que l'échange soit définitif.\n\n"
            "`/pokedex membre:@quelqu'un` et `/pokedex-info ... membre:@quelqu'un` "
            "permettent de vérifier ce que possède un autre joueur avant de proposer un "
            "échange."
        ),
    },
    "marketplace": {
        "titre": "Marketplace",
        "emoji": "🛒",
        "texte": (
            "Vends un de tes Pokémon à **prix fixe** (pas d'enchères) — `/vendre-pokemon` "
            "pour choisir lequel et fixer ton prix, l'annonce est postée automatiquement "
            "dans le channel marketplace avec son sprite, son prix et un compte à "
            "rebours.\n\n"
            "N'importe qui peut l'acheter en un clic (confirmation demandée avant "
            "l'achat définitif). Tu peux retirer ton annonce à tout moment tant qu'elle "
            "n'est pas vendue — ton Pokémon ne bouge jamais avant une vente effective. "
            "Sans acheteur, une annonce disparaît automatiquement au bout de **7 jours**.\n\n"
            "`/marketplace-recherche <nom>` pour retrouver vite une annonce active, "
            "`/marketplace-historique` pour revoir tes ventes et achats passés."
        ),
    },
    "roguelike": {
        "titre": "Mini-jeu Roguelike",
        "emoji": "🎲",
        "texte": (
            "Un mini-jeu **indépendant** du reste de PokéWild (aucune récompense liée à "
            "ton profil, ton Pokédex ou ton économie) — `/roguelike` lance une run dans "
            "un fil privé.\n\n"
            "Tu choisis un **starter** parmi 6 Pokémon génériques proposés au hasard, "
            "puis avances dans un chemin de 8 à 12 salles (combats, salles élite, "
            "trésors, repos, événements, recrutement) jusqu'à un boss final. Les "
            "salles de **recrutement** te permettent d'ajouter jusqu'à 2 coéquipiers "
            "supplémentaires en cours de route (3 Pokémon max).\n\n"
            "Tes PV **ne se restaurent pas automatiquement** entre les combats — gère "
            "tes ressources ! Les trésors offrent des **reliques** (bonus propres à la "
            "run : dégâts, résistance, soin après victoire...). **Mort = run perdue "
            "intégralement**, retour à zéro pour la suivante. Accès illimité, aucun "
            "cooldown.\n\n"
            "Seule trace qui reste : `/roguelike-classement`, le meilleur étage jamais "
            "atteint. `/roguelike-abandonner` pour repartir de zéro à tout moment."
        ),
    },
    "classements_clans": {
        "titre": "Classements & Clans",
        "emoji": "🏆",
        "texte": (
            "`/classement` — le classement général des dresseurs du serveur. "
            "`/mon-classement` — ta position personnelle, en privé.\n\n"
            "**Clans** : 3 équipes fixes façon Pokémon GO (Bleu/Rouge/Jaune) — bouton "
            "\"Clan\" dans ton profil pour ouvrir le tableau de bord (1 changement "
            "gratuit par semaine). Chaque clan a sa couleur de rôle Discord.\n\n"
            "🎯 **Objectif hebdomadaire** — un nouveau but tiré au sort chaque lundi "
            "(captures ou combats), suivi séparément par équipe. Toute équipe qui "
            "l'atteint récompense ses membres, et la **première des 3** touche un "
            "bonus en plus.\n\n"
            "🔹 **Rang de contribution** — tes captures/combats font monter ton titre "
            "au sein de ton clan (Recrue → ... → Légende de l'équipe), remis à 0 si "
            "tu changes d'équipe.\n\n"
            "📜 **Historique des saisons** — chaque mois, le classement des 3 clans "
            "est archivé pour toujours, façon palmarès."
        ),
    },
    "pokestop": {
        "titre": "PokéStop",
        "emoji": "🔵",
        "texte": (
            "Fais tourner le disque toutes les X minutes pour des Poké Dollars "
            "garantis, plus une chance de balls, potions, Cristal de Mutation ou Œuf.\n\n"
            "**Heure de pointe** : chaque jour, un créneau de 30 minutes tiré "
            "aléatoirement entre 9h et 22h30 double toutes les récompenses — annoncé "
            "dans le channel, avec l'horaire affiché sur le message fixe pendant que "
            "c'est actif."
        ),
    },
    "passe_saison": {
        "titre": "Passe Saisonnier",
        "emoji": "🎫",
        "texte": (
            "Une progression sur toute la saison (30 jours, la première exceptionnellement "
            "plus longue), alimentée **automatiquement** par toute XP de dresseur gagnée "
            "dans le jeu — rien à activer.\n\n"
            "30 paliers, chacun donnant des récompenses (Poké Dollars + objets variés), "
            "avec un gros lot au palier final (Cristal de Mutation + Master Ball).\n\n"
            "`/passe-saison` — ta progression actuelle, la prochaine récompense, et le "
            "temps restant avant la fin de la saison."
        ),
    },
    "mini_jeux": {
        "titre": "Mini-jeux",
        "emoji": "🎮",
        "texte": (
            "Pur fun, sans récompense :\n\n"
            "• `/defi-stats` — défie un joueur : un Pokémon apparaît, vous devinez en "
            "secret sa stat la plus haute, meilleur score sur 5 rounds gagne\n"
            "• `/plus-ou-moins` — solo, devine si le PC du prochain Pokémon est plus "
            "haut ou plus bas, enchaîne ta série\n"
            "• **Quiz communautaire** (channel dédié) — Qui est-ce, Anagramme, Quiz de "
            "types, Trivia PokéWild, une question à la fois, premier qui trouve gagne\n"
            "• `/roguelike` — mini-jeu à part entière avec sa propre page dans ce "
            "wiki (voir \"Mini-jeu Roguelike\"), permadeath et classement dédié"
        ),
    },
    "arene": {
        "titre": "Arène",
        "emoji": "🏟️",
        "texte": (
            "Une arène d'un type aléatoire ouvre régulièrement dans le channel Aventure. "
            "Clique sur **Défier l'Arène** pour enchaîner 3 combats : 2 Apprentis puis le "
            "**Champion** (Rare et au-dessus, tous du type de l'arène).\n\n"
            "Entre chaque combat, tu peux soigner ton équipe (coûte une potion) ou "
            "enchaîner directement. **Une défaite met fin à ta tentative** — retente ta "
            "chance à la prochaine ouverture. Plusieurs joueurs peuvent tenter la même "
            "arène en parallèle, chacun son run.\n\n"
            "Vaincre un Champion pour la première fois débloque son **badge**, "
            "définitif — `/badges-arene` pour voir ta collection (18 possibles). Chaque "
            "badge donne un petit bonus de dégâts permanent avec les attaques de ce type, "
            "et aussi une CT au hasard de ce type à chaque victoire (jamais une déjà possédée)."
        ),
    },
    "repaires": {
        "titre": "Repaires de méchants",
        "emoji": "🕵️",
        "texte": (
            "Même principe que l'Arène, mais contre les équipes méchantes des jeux "
            "(Team Rocket, Aqua, Magma, Galactic...) — un repaire ouvre régulièrement "
            "dans le channel Aventure. Clique sur **Infiltrer le repaire** pour "
            "enchaîner 2 sbires puis le **boss** de l'équipe (Giovanni, Arthur, Max, "
            "Hélio...).\n\n"
            "Entre chaque combat, tu peux soigner ton équipe ou enchaîner directement. "
            "**Une défaite met fin à ta tentative** — retente ta chance au prochain "
            "repaire. Plusieurs joueurs peuvent s'y essayer en parallèle.\n\n"
            "Vaincre un boss pour la première fois débloque son **badge**, définitif — "
            "chaque équipe donne un bonus permanent différent (capture, shiny, Poké "
            "Dollars ou XP selon l'équipe).\n\n"
            "💎 À chaque victoire de boss, **chacun** des objets de transformation "
            "rarissimes (Orbe Adamant, Fleur Gracidea, Orbe Bleue...) a une petite "
            "chance indépendante de tomber, peu importe l'équipe affrontée."
        ),
    },
    "draft_pvp": {
        "titre": "Draft PvP",
        "emoji": "🎯",
        "texte": (
            "Un mode de combat **compétitif équitable**, indépendant de ta collection.\n\n"
            "`/defi-draft @adversaire` — chaque joueur reçoit son **propre pool privé** "
            "de 12 Pokémon aléatoires (jamais les mêmes des deux côtés) dans un message "
            "visible de lui seul, et choisit 6 Pokémon dedans en toute confidentialité. "
            "Le combat démarre automatiquement dès que les deux ont validé — pas besoin "
            "d'attendre son tour.\n\n"
            "Tous les Pokémon draftés sont au **même niveau** (peu importe votre "
            "progression réelle), avec des IV neutres, un **talent tiré au hasard**, et "
            "**4 attaques tirées au hasard** dans tout leur movepool possible — sans "
            "tenir compte du niveau requis ni d'une CT possédée.\n\n"
            "Seule la lecture du plateau compte : qui a le plus farmé ne joue aucun rôle ici."
        ),
    },
    "parrainage": {
        "titre": "Parrainage & Boost du serveur",
        "emoji": "🤝",
        "texte": (
            "**Parrainage** : invite du monde sur le serveur avec ton lien Discord "
            "habituel — le bot détecte automatiquement qui a invité qui. Un filleul "
            "doit rester au moins 7 jours sur le serveur pour compter (anti-abus). Tous "
            "les 3 filleuls confirmés, tu débloques une récompense en Poké Dollars et "
            "objets. `/parrainage` pour suivre ta progression.\n\n"
            "**Booster le serveur** (Nitro) : si tu boostes le serveur Discord, tu "
            "reçois automatiquement un bonus permanent sur l'argent, l'XP et les "
            "chances de shiny — pas besoin de commande, c'est détecté tout seul dès que "
            "ton boost est actif."
        ),
    },
}

ORDRE_PAGES = list(PAGES.keys())


def construire_embed_accueil() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Wiki PokéWild",
        description=(
            "Toutes les infos sur le jeu, classées par thème. Choisis une catégorie "
            "dans le menu ci-dessous pour l'afficher."
        ),
        color=discord.Color.blurple(),
    )
    sommaire = "\n".join(f"{PAGES[cle]['emoji']} {PAGES[cle]['titre']}" for cle in ORDRE_PAGES)
    embed.add_field(name="Sommaire", value=sommaire, inline=False)
    return embed


def construire_embed_page(cle: str) -> discord.Embed:
    page = PAGES.get(cle)
    if not page:
        return construire_embed_accueil()
    embed = discord.Embed(
        title=f"{page['emoji']} {page['titre']}",
        description=page["texte"],
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="Wiki PokéWild — choisis une autre catégorie dans le menu pour naviguer.")
    return embed


class VueWiki(discord.ui.View):
    """Vue persistante (menu déroulant de navigation) — utilisée aussi bien pour le
    message fixe du channel wiki que pour /wiki en éphémère ailleurs."""

    def __init__(self):
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(label=page["titre"], value=cle, emoji=page["emoji"])
            for cle, page in PAGES.items()
        ]
        select = discord.ui.Select(
            placeholder="Choisis une catégorie...",
            options=options,
            custom_id="wiki_select_categorie",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        cle = interaction.data["values"][0]
        embed = construire_embed_page(cle)

        # Le message fixe du channel #wiki est PUBLIC et PARTAGÉ par tout le monde — si on
        # l'éditait directement, un joueur qui clique écraserait ce que regardait un autre
        # au même moment. On répond donc par un nouveau message éphémère à la place, pour
        # que chacun puisse naviguer indépendamment. Si l'interaction vient déjà d'un
        # message éphémère (ex: /wiki), on continue à l'éditer sur place comme avant —
        # pas de raison d'en spammer un nouveau à chaque clic dans ce cas-là.
        deja_ephemere = interaction.message is not None and interaction.message.flags.ephemeral
        if deja_ephemere:
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message(embed=embed, view=VueWiki(), ephemeral=True)
