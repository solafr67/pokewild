"""Wiki interactif de PokéWild — un message fixe (config.CHANNEL_WIKI_ID) avec un menu
déroulant listant chaque MÉGA-CATÉGORIE du jeu ; sélectionner une catégorie affiche son
explication, avec pagination ◀️▶️ si elle regroupe plusieurs sujets. Aucune commande
/wiki n'existe — accès uniquement via ce message fixe.

Le contenu vit dans PAGES, {clé: {titre, emoji, sous_pages: [{sous_titre, texte}, ...]}}
— une catégorie à sujet unique n'a qu'un seul élément dans sous_pages (sous_titre=None,
pas de pagination affichée) ; une catégorie qui en regroupe plusieurs (ex: "Combat PvP"
qui inclut aussi "Draft PvP") a plusieurs éléments, navigables avec ◀️▶️ sans avoir
besoin d'une entrée séparée dans le menu déroulant principal — nécessaire pour rester
sous la limite de 25 options d'un select Discord tout en pouvant continuer à ajouter du
contenu au fil des mises à jour du jeu.
"""

import discord

PAGES = {
    "demarrage": {
        "titre": 'Démarrer',
        "emoji": '🐣',
        "sous_pages": [
            {"sous_titre": None, "texte": "**Bienvenue dans PokéWild !**\n\nLes Pokémon apparaissent automatiquement dans les channels de spawn (Classique et VIP) — clique sur **Capturer** et choisis ta ball. Chaque capture donne de l'XP de dresseur et, si le Pokémon fait partie de ton équipe de combat, de l'XP pour lui aussi.\n\n**Premiers réflexes utiles :**\nTout se passe via le message fixe du channel profil — clique sur **Voir mon profil**, puis :\n• **Équipe de combat** — compose ton équipe de 6 Pokémon max\n• **Voir mon Pokédex** — vois ce que tu as déjà capturé\n• **Clan** — rejoins une des 3 équipes (Bleu/Rouge/Jaune)\n\nConsulte les autres pages de ce wiki pour approfondir chaque système."},
        ],
    },
    "capture_progression": {
        "titre": 'Capture & Progression',
        "emoji": '🎯',
        "sous_pages": [
            {"sous_titre": 'Capture & Spawns', "texte": "Des Pokémon sauvages apparaissent régulièrement dans les channels de spawn **Classique** et **VIP** (le VIP a de meilleures chances de rareté). Chaque spawn affiche son PC et son **niveau** — plus la rareté est haute, plus la fourchette de niveau au spawn est élevée.\n\n**Balls disponibles** : Poké Ball, Super Ball, Hyper Ball, Master Ball — plus la ball est bonne, plus la chance de capture est haute. Les balls s'obtiennent au PokéStop, en quêtes, en récompense de raid...\n\nChaque Pokémon capturé a de vrais **IV individuels** (6 stats tirées indépendamment) — deux individus de la même espèce ne sont jamais identiques. Ton meilleur exemplaire d'une espèce est celui utilisé partout (équipe, combat, Pokédex).\n\n**Formes régionales** (Alola, Galar, Hisui, Paldea) — de vraies entrées de Pokédex à part entière, capturables comme n'importe quel autre Pokémon, juste regroupées avec leur forme de base une fois attrapées."},
            {"sous_titre": 'Niveau & Statistiques', "texte": "Chaque Pokémon a un **niveau** (jusqu'à 100) et de vraies **statistiques** (PV, Attaque, Défense, Attaque Spé, Défense Spé, Vitesse), calculées avec les formules officielles des jeux à partir de ses IV et de son niveau.\n\n**Seuls les Pokémon de ton équipe de combat active gagnent de l'XP**, via capture, PokéStop, quêtes, raids, dresseurs, PvP... Équipe vide = XP perdue, alors garde toujours une équipe configurée (bouton **Équipe de combat** sur ton profil) !\n\nLe **PC** reste affiché (façon Pokémon GO) mais n'est plus qu'un résumé pratique — ce sont les vraies stats qui comptent en combat.\n\nConsulte `/pokedex-info <nom>` pour voir le détail complet d'un Pokémon (niveau, stats, hexagone)."},
        ],
    },
    "combat_pvp_groupe": {
        "titre": 'Combat PvP',
        "emoji": '⚔️',
        "sous_pages": [
            {"sous_titre": 'Combat PvP', "texte": "Défie un autre joueur en duel — combat au tour par tour dans un fil dédié, avec PP à gérer, statuts (poison, brûlure...), boosts de stats, et des attaques à 2 tours pour les plus puissantes. Les dégâts suivent la vraie formule officielle des jeux (type, STAB, stats réelles, niveau).\n\n**Attaques** : à équiper au Maître des Types (voir cette page) — 4 emplacements par Pokémon, débloquées par niveau ou par CT.\n\n**Trois formats disponibles :**\n• `/defier` — 1v1 classique, 1 Pokémon actif chacun\n• `/combat-2v2` — 1v1 en **double combat** : équipe complète (jusqu'à 6), 2 Pokémon actifs simultanément chacun\n• `/combat-2v2-equipe` — lobby à 4 joueurs, 2 équipes de 2, 3 Pokémon chacun\n\nEnchaîne les victoires pour faire grimper ta **série de victoires PvP** (visible au classement, et Gladio le remarque).\n\nÀ la fin d'un combat, un bouton **🔄 Revanche** permet de relancer immédiatement un défi identique — les 2 joueurs doivent valider avant que le combat ne reparte réellement. Et n'importe qui d'autre peut cliquer sur **👁️ Regarder** pour rejoindre le fil en spectateur, sans y participer."},
            {"sous_titre": 'Draft PvP', "texte": "Un mode de combat **compétitif équitable**, indépendant de ta collection.\n\n`/defi-draft @adversaire` — chaque joueur reçoit son **propre pool privé** de 12 Pokémon aléatoires (jamais les mêmes des deux côtés) dans un message visible de lui seul, et choisit 6 Pokémon dedans en toute confidentialité. Le combat démarre automatiquement dès que les deux ont validé — pas besoin d'attendre son tour.\n\nTous les Pokémon draftés sont au **même niveau** (peu importe votre progression réelle), avec des IV neutres, un **talent tiré au hasard**, et **4 attaques tirées au hasard** dans tout leur movepool possible — sans tenir compte du niveau requis ni d'une CT possédée.\n\nSeule la lecture du plateau compte : qui a le plus farmé ne joue aucun rôle ici."},
        ],
    },
    "pve_rivaux": {
        "titre": 'PvE & Rivaux',
        "emoji": '🥾',
        "sous_pages": [
            {"sous_titre": 'Dresseurs & Gladio', "texte": 'Des **dresseurs PNJ** apparaissent spontanément dans certains channels — clique sur **Défier** pour un combat contre une équipe calibrée sur la puissance actuelle de la tienne.\n\nEnviron 1 apparition sur 5 est un **Duo** (Duo Cyclone, Duo Belladone...) — deux dresseurs affrontés en même temps, en double combat : tu contrôles alors 2 Pokémon actifs simultanément face à leurs 6 Pokémon chacun.\n\n**Gladio, ton rival**, est différent : \n• `/defi-gladio` — un vrai combat, une fois par jour, équipe de 6 Pokémon Rare et au-dessus, légèrement plus forte que la tienne, récompense fixe de 400 à 600 Poké Dollars\n• `/gladio` — voir où tu en es avec lui (il se souvient de vos échanges et son ton évolue avec le temps — distant, puis familier, puis un vrai respect)\n\nIl commente aussi certains de tes exploits (capture shiny, légendaire, victoire de raid, série PvP...) directement dans le fil concerné.\n\nUn bouton **⚔️ Défier Gladio** fixe est aussi posté en permanence dans le channel dresseur — pas besoin de retenir la commande, un clic suffit (même cooldown quotidien que `/defi-gladio`).'},
            {"sous_titre": 'Arène', "texte": "Une arène d'un type aléatoire ouvre régulièrement dans le channel Aventure. Clique sur **Défier l'Arène** pour enchaîner 3 combats : 2 Apprentis puis le **Champion** (Rare et au-dessus, tous du type de l'arène).\n\nEntre chaque combat, tu peux soigner ton équipe (coûte une potion) ou enchaîner directement. **Une défaite met fin à ta tentative** — retente ta chance à la prochaine ouverture. Plusieurs joueurs peuvent tenter la même arène en parallèle, chacun son run.\n\nVaincre un Champion pour la première fois débloque son **badge**, définitif — `/badges-arene` pour voir ta collection (18 possibles). Chaque badge donne un petit bonus de dégâts permanent avec les attaques de ce type, et aussi une CT au hasard de ce type à chaque victoire (jamais une déjà possédée)."},
            {"sous_titre": 'Repaires de méchants', "texte": "Même principe que l'Arène, mais contre les équipes méchantes des jeux (Team Rocket, Aqua, Magma, Galactic...) — un repaire ouvre régulièrement dans le channel Aventure. Clique sur **Infiltrer le repaire** pour enchaîner 2 sbires puis le **boss** de l'équipe (Giovanni, Arthur, Max, Hélio...).\n\nEntre chaque combat, tu peux soigner ton équipe ou enchaîner directement. **Une défaite met fin à ta tentative** — retente ta chance au prochain repaire. Plusieurs joueurs peuvent s'y essayer en parallèle.\n\nVaincre un boss pour la première fois débloque son **badge**, définitif — chaque équipe donne un bonus permanent différent (capture, shiny, Poké Dollars ou XP selon l'équipe).\n\n💎 À chaque victoire de boss, **chacun** des objets de transformation rarissimes (Orbe Adamant, Fleur Gracidea, Orbe Bleue...) a une petite chance indépendante de tomber, peu importe l'équipe affrontée."},
        ],
    },
    "raids": {
        "titre": 'Raids',
        "emoji": '🐉',
        "sous_pages": [
            {"sous_titre": None, "texte": "Un boss sauvage (1 à 5 étoiles) apparaît, une salle d'attente s'ouvre — rejoins-la avant le lancement du combat. Une fois lancé, ton équipe attaque automatiquement toutes les 5 secondes pendant 15 minutes max, et le boss riposte à chaque tour.\n\n**Coopératif** : plusieurs joueurs peuvent affronter le même boss en même temps, les dégâts de chacun s'additionnent sur le même total de PV. Vaincu, il devient capturable pour chaque participant (plusieurs tentatives possibles).\n\nPlus il y a d'étoiles, plus le boss est costaud et les récompenses généreuses.\n\nEnvie d'être prévenu à chaque nouveau raid ? Clique sur **🔔 Notifications Raid** dans le channel dédié pour (dés)activer le rôle de ping."},
        ],
    },
    "attaques_talents": {
        "titre": 'Attaques & Talents',
        "emoji": '🧙',
        "sous_pages": [
            {"sous_titre": 'Maître des Types (CT)', "texte": "Le PNJ qui gère les **attaques** de tes Pokémon — 4 emplacements par Pokémon, 1 par 1.\n\n**Gratuit** : toute attaque que ton Pokémon connaît déjà naturellement à son niveau actuel.\n**CT (payante)** : pour apprendre une attaque avant d'avoir le niveau requis, achète sa CT à la **Boutique CT** — une fois achetée, elle est à toi pour toujours, utilisable sur n'importe lequel de tes Pokémon, sans limite. Filtrable par type et catégorie (Physique/Spécial/Statut)."},
            {"sous_titre": 'Maître des Capacités (talents & objets tenus)', "texte": 'Le PNJ qui gère le **talent** et l\'**objet tenu** de tes Pokémon (en plus de leurs attaques, voir "Maître des Types").\n\n🧬 **Talent** — attribué automatiquement à la capture, fidèle à sa vraie capacité dans les jeux quand elle est connue (ex : Salamèche → Brasier).\n\n🎒 **Objet tenu** — bouton "Objets tenus" pour équiper un objet de ton sac à un Pokémon (Reste, Orbe Vie, objets Choix...) — achetables à la **Boutique**, onglet Objets.\n\n💎 **Objets de transformation** — une poignée d\'objets rarissimes (jamais en boutique, uniquement trouvables en Exploration ou à la capture) transforment certaines légendaires tant qu\'elles les tiennent (Dialga + Orbe Adamant → Dialga Origine, Kyogre + Orbe Bleue → Primo-Kyogre...) — stats et types changent, le PC affiché ne bouge jamais.'},
        ],
    },
    "exploration_labo": {
        "titre": 'Exploration & Laboratoire',
        "emoji": '🗺️',
        "sous_pages": [
            {"sous_titre": 'Centre des Explorations', "texte": "Envoie une équipe de 3 Pokémon explorer pendant 1h, 6h ou 24h — ils sont indisponibles en combat/raid pendant ce temps, mais rapportent Poké Dollars, XP, une chance de Cristal de Mutation et une chance d'Œuf à leur retour.\n\nPlus ton équipe envoyée est puissante (PC cumulé), meilleure est la récompense, jusqu'à un plafond. Le rendement par heure augmente aussi avec la durée choisie — une expédition de 24h rapporte proportionnellement plus qu'enchaîner des 1h."},
            {"sous_titre": 'Laboratoire (Œufs & Caisson de Croissance)', "texte": "Fais éclore les Œufs trouvés en exploration ou au PokéStop — un incubateur à la fois. Le Pokémon obtenu dépend du palier de l'œuf (Commun à Légendaire), et éclot directement à un niveau cohérent avec sa rareté (comme un spawn sauvage).\n\nLe Laboratoire abrite aussi la **Race de dresseur** — utilise un Cristal de Mutation (obtenu en exploration, PokéStop, ou en Passe Saisonnier) pour tenter ta chance.\n\n**🧫 Caisson de Croissance** : place jusqu'à 3 Pokémon possédés dedans — ils gagnent de l'XP passivement au fil du temps (200 XP/heure chacun), même sans jouer. Récupère l'XP à tout moment en les retirant."},
            {"sous_titre": 'PokéStop', "texte": "Fais tourner le disque toutes les X minutes pour des Poké Dollars garantis, plus une chance de balls, potions, Cristal de Mutation ou Œuf.\n\n**Heure de pointe** : chaque jour, un créneau de 30 minutes tiré aléatoirement entre 9h et 22h30 double toutes les récompenses — annoncé dans le channel, avec l'horaire affiché sur le message fixe pendant que c'est actif."},
        ],
    },
    "quetes_progression": {
        "titre": 'Quêtes & Progression perso',
        "emoji": '📜',
        "sous_pages": [
            {"sous_titre": 'Quêtes', "texte": "Des objectifs **journaliers** et **hebdomadaires**, reset à heure fixe pour tout le monde. Les termine pour des Poké Dollars, de l'XP, et une chance d'objet bonus (plus rare sur les quêtes hebdomadaires).\n\n**📃 Contrats** : un PNJ te propose en plus 3 missions tirées au sort chaque jour (capture ciblée, combats...), personnelles et différentes de celles des autres joueurs. Payées automatiquement dès qu'elles sont remplies, mais elles disparaissent si tu ne les termines pas avant le reset du lendemain.\n\n**📖 Quête principale** : une vraie narration en chapitres, qui suit ta progression naturelle (capture, dresseurs, arène, repaires, PvP, raids, Gladio). Une **Partie 2 — Les Terres Cendrées** prend le relais après la victoire contre Gladio, nettement plus longue et difficile : la Partie 1 n'était qu'un tutoriel en comparaison.\n\nClique sur **Voir mes quêtes**, sur le message fixe de ce channel, pour voir ta progression actuelle."},
            {"sous_titre": 'Connexion quotidienne', "texte": "`/recompense-quotidienne` — une récompense chaque jour, qui grandit de façon exponentielle avec ta série de jours consécutifs (plafonnée au jour 30). Poké Ball et Potion dès le jour 1, avec des bonus d'objets plus généreux (Super Ball, Hyper Ball) aux paliers 7/14/21/28, puis un Cristal de Mutation tous les 7 jours passé le plafond.\n\nUn jour sauté remet la série à zéro — reviens tous les jours pour ne pas perdre ta progression."},
            {"sous_titre": 'Récap personnel', "texte": '`/recap` — ta progression depuis la dernière fois que tu as consulté cette commande (pas calé sur un jour ou une semaine fixe, juste "depuis ta dernière visite") : captures, shiny, victoires PvP, victoires contre un dresseur, explorations terminées, et variation nette de tes Poké Dollars.\n\nPratique pour voir d\'un coup d\'œil ce que tu as accompli sans avoir à farfouiller dans plusieurs commandes.'},
            {"sous_titre": 'Passe Saisonnier', "texte": 'Une progression sur toute la saison (30 jours, la première exceptionnellement plus longue), alimentée **automatiquement** par toute XP de dresseur gagnée dans le jeu — rien à activer.\n\n30 paliers, chacun donnant des récompenses (Poké Dollars + objets variés), avec un gros lot au palier final (Cristal de Mutation + Master Ball).\n\n`/passe-saison` — ta progression actuelle, la prochaine récompense, et le temps restant avant la fin de la saison.'},
        ],
    },
    "economie_social": {
        "titre": 'Économie & Social',
        "emoji": '🔄',
        "sous_pages": [
            {"sous_titre": 'Échanges', "texte": "Propose un échange à un autre joueur — une grille visuelle avec les sprites de vos Pokémon respectifs pour choisir facilement quoi donner et recevoir, avec un bouton de recherche pour retrouver vite un Pokémon précis dans une grosse collection. Les deux joueurs doivent confirmer avant que l'échange soit définitif.\n\nUn bouton **🎒 Objets** permet en plus d'ajouter des objets du sac à l'offre (balls, potions, Cristal de Mutation, objets tenus...) — pas seulement des Pokémon et des Poké Dollars.\n\n`/pokedex-info nom:... membre:@quelqu'un` permet de vérifier si un autre joueur possède un Pokémon précis avant de proposer un échange."},
            {"sous_titre": 'Marketplace', "texte": "Vends un de tes Pokémon à **prix fixe** (pas d'enchères) — `/vendre-pokemon` pour choisir lequel et fixer ton prix, l'annonce est postée automatiquement dans le channel marketplace avec son sprite, son prix et un compte à rebours.\n\nN'importe qui peut l'acheter en un clic (confirmation demandée avant l'achat définitif). Tu peux retirer ton annonce à tout moment tant qu'elle n'est pas vendue — ton Pokémon ne bouge jamais avant une vente effective. Sans acheteur, une annonce disparaît automatiquement au bout de **7 jours**.\n\n`/marketplace-recherche <nom>` pour retrouver vite une annonce active, `/marketplace-historique` pour revoir tes ventes et achats passés."},
            {"sous_titre": 'Parrainage & Boost du serveur', "texte": "**Parrainage** : invite du monde sur le serveur avec ton lien Discord habituel — le bot détecte automatiquement qui a invité qui. Un filleul doit rester au moins 7 jours sur le serveur pour compter (anti-abus). Tous les 3 filleuls confirmés, tu débloques une récompense en Poké Dollars et objets. `/parrainage` pour suivre ta progression.\n\n**Booster le serveur** (Nitro) : si tu boostes le serveur Discord, tu reçois automatiquement un bonus permanent sur l'argent, l'XP et les chances de shiny — pas besoin de commande, c'est détecté tout seul dès que ton boost est actif."},
        ],
    },
    "mini_jeux_groupe": {
        "titre": 'Mini-jeux',
        "emoji": '🎮',
        "sous_pages": [
            {"sous_titre": 'Mini-jeux', "texte": 'Pur fun, sans récompense :\n\n• `/defi-stats` — défie un joueur : un Pokémon apparaît, vous devinez en secret sa stat la plus haute, meilleur score sur 5 rounds gagne\n• `/plus-ou-moins` — solo, devine si le PC du prochain Pokémon est plus haut ou plus bas, enchaîne ta série\n• **Quiz communautaire** (channel dédié) — Qui est-ce, Anagramme, Quiz de types, Trivia PokéWild, une question à la fois, premier qui trouve gagne\n• `/roguelike` — mini-jeu à part entière avec sa propre page dans ce wiki (voir "Mini-jeu Roguelike"), permadeath et classement dédié'},
            {"sous_titre": 'Mini-jeu Roguelike', "texte": "Un mini-jeu **indépendant** du reste de PokéWild (aucune récompense liée à ton profil, ton Pokédex ou ton économie) — `/roguelike` lance une run dans un fil privé.\n\nTu choisis un **starter** parmi 6 Pokémon génériques proposés au hasard, puis avances dans un chemin de 8 à 12 salles (combats, salles élite, trésors, repos, événements, recrutement) jusqu'à un boss final. Les salles de **recrutement** te permettent d'ajouter jusqu'à 2 coéquipiers supplémentaires en cours de route (3 Pokémon max).\n\nTon équipe **monte en niveau à chaque salle** pour suivre exactement la même courbe que les ennemis (plus de risque de rester à la traîne), et peut carrément **évoluer** en cours de route si le niveau atteint le seuil d'évolution de l'espèce — jusqu'à 2 évolutions d'affilée si un gros saut de niveau franchit 2 paliers d'un coup.\n\nTes PV **ne se restaurent pas automatiquement** entre les combats — gère tes ressources ! Les trésors offrent des **reliques** (bonus propres à la run : dégâts, résistance, soin après victoire...). **Mort = run perdue intégralement**, retour à zéro pour la suivante. Accès illimité, aucun cooldown.\n\nSeule trace qui reste : `/roguelike-classement`, le meilleur étage jamais atteint. `/roguelike-abandonner` pour repartir de zéro à tout moment."},
        ],
    },
    "classements_clans": {
        "titre": 'Classements & Clans',
        "emoji": '🏆',
        "sous_pages": [
            {"sous_titre": None, "texte": 'Le classement général des dresseurs du serveur est affiché en message fixe dans son channel dédié (rafraîchi automatiquement). `/mon-classement` donne ta position personnelle, en privé.\n\n**Clans** : 3 équipes fixes façon Pokémon GO (Bleu/Rouge/Jaune) — bouton "Clan" dans ton profil pour ouvrir le tableau de bord (1 changement gratuit par semaine). Chaque clan a sa couleur de rôle Discord.\n\n🎯 **Objectif hebdomadaire** — un nouveau but tiré au sort chaque lundi (captures ou combats), suivi séparément par équipe. Toute équipe qui l\'atteint récompense ses membres, et la **première des 3** touche un bonus en plus.\n\n🔹 **Rang de contribution** — tes captures/combats font monter ton titre au sein de ton clan (Recrue → ... → Légende de l\'équipe), remis à 0 si tu changes d\'équipe.\n\n📜 **Historique des saisons** — chaque mois, le classement des 3 clans est archivé pour toujours, façon palmarès.'},
        ],
    },
}

ORDRE_PAGES = list(PAGES.keys())


def construire_embed_accueil() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Wiki PokéWild",
        description=(
            "Toutes les infos sur le jeu, classées par thème. Choisis une catégorie "
            "dans le menu ci-dessous pour l'afficher — certaines catégories "
            "regroupent plusieurs sujets, navigables avec ◀️ ▶️."
        ),
        color=discord.Color.blurple(),
    )
    sommaire = "\n".join(f"{PAGES[cle]['emoji']} {PAGES[cle]['titre']}" for cle in ORDRE_PAGES)
    embed.add_field(name="Sommaire", value=sommaire, inline=False)
    return embed


def construire_embed_page(cle: str, sous_index: int = 0) -> discord.Embed:
    """Construit l'embed d'une sous-page précise d'une méga-catégorie. `sous_index`
    est bordé (jamais hors limites) pour ne jamais planter sur un clic tardif après
    une modification du contenu."""
    page = PAGES.get(cle)
    if not page:
        return construire_embed_accueil()

    sous_pages = page["sous_pages"]
    sous_index = max(0, min(sous_index, len(sous_pages) - 1))
    sous_page = sous_pages[sous_index]

    titre_complet = f"{page['emoji']} {page['titre']}"
    if sous_page["sous_titre"] and sous_page["sous_titre"] != page["titre"]:
        titre_complet += f" — {sous_page['sous_titre']}"

    embed = discord.Embed(title=titre_complet, description=sous_page["texte"], color=discord.Color.blurple())

    if len(sous_pages) > 1:
        embed.set_footer(text=f"Page {sous_index + 1}/{len(sous_pages)} — ◀️ ▶️ pour naviguer, ou choisis une autre catégorie dans le menu.")
    else:
        embed.set_footer(text="Wiki PokéWild — choisis une autre catégorie dans le menu pour naviguer.")
    return embed


class VuePageWiki(discord.ui.View):
    """Vue affichée pour UNE méga-catégorie précise — menu déroulant (toutes les
    catégories, pour changer directement) + pagination ◀️▶️ si la catégorie a
    plusieurs sous-pages. Toujours éphémère (voir VueWiki._on_select pour le
    raisonnement complet sur le message fixe partagé)."""

    def __init__(self, cle: str, sous_index: int = 0):
        super().__init__(timeout=300)
        self.cle = cle
        self.sous_index = sous_index
        self._construire_composants()

    def _construire_composants(self):
        self.clear_items()

        options = [
            discord.SelectOption(label=page["titre"], value=cle, emoji=page["emoji"], default=(cle == self.cle))
            for cle, page in PAGES.items()
        ]
        select = discord.ui.Select(placeholder="Choisis une catégorie...", options=options, row=0)
        select.callback = self._on_select_categorie
        self.add_item(select)

        nb_sous_pages = len(PAGES[self.cle]["sous_pages"])
        if nb_sous_pages > 1:
            bouton_prec = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1, disabled=self.sous_index == 0)
            bouton_prec.callback = self._page_prec
            self.add_item(bouton_prec)
            bouton_suiv = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=1, disabled=self.sous_index >= nb_sous_pages - 1)
            bouton_suiv.callback = self._page_suiv
            self.add_item(bouton_suiv)

    async def _on_select_categorie(self, interaction: discord.Interaction):
        nouvelle_cle = interaction.data["values"][0]
        self.cle = nouvelle_cle
        self.sous_index = 0
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_page(self.cle, self.sous_index), view=self)

    async def _page_prec(self, interaction: discord.Interaction):
        self.sous_index = max(0, self.sous_index - 1)
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_page(self.cle, self.sous_index), view=self)

    async def _page_suiv(self, interaction: discord.Interaction):
        nb_sous_pages = len(PAGES[self.cle]["sous_pages"])
        self.sous_index = min(nb_sous_pages - 1, self.sous_index + 1)
        self._construire_composants()
        await interaction.response.edit_message(embed=construire_embed_page(self.cle, self.sous_index), view=self)


class VueWiki(discord.ui.View):
    """Vue persistante (menu déroulant de navigation) attachée au message fixe du
    channel wiki — aucune commande équivalente n'existe, seul ce message y donne accès."""

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
        vue = VuePageWiki(cle, sous_index=0)
        embed = construire_embed_page(cle, 0)

        # Le message fixe du channel #wiki est PUBLIC et PARTAGÉ par tout le monde — si on
        # l'éditait directement, un joueur qui clique écraserait ce que regardait un autre
        # au même moment. On répond donc par un nouveau message éphémère à la place, pour
        # que chacun puisse naviguer indépendamment (avec sa propre pagination/sélection).
        await interaction.response.send_message(embed=embed, view=vue, ephemeral=True)
