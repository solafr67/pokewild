"""Méga-Évolution — transformation TEMPORAIRE et limitée au combat (contrairement aux
formes obtenues par objet dans formes_objets.py, qui sont permanentes tant que l'objet
est équipé). Un joueur équipe une Pierre Méga sur un Pokémon via /equiper-objet (même
système que les autres objets tenus), puis active la transformation UNE FOIS PAR COMBAT
avec le bouton dédié dans le panneau d'action — elle dure jusqu'à la fin du combat (pas
de retour en arrière, comme dans les vrais jeux), et ne persiste jamais d'un combat à
l'autre.

Stats vérifiées contre la table officielle Bulbapedia (List of Mega Evolution
characteristics) le 28/08/2026. Sélection volontairement restreinte à 21 Méga-Évolutions
bien connues plutôt que les ~93 existantes, pour garantir l'exactitude de chaque entrée —
liste extensible plus tard.

⚠️ LIMITE CONNUE : seules les STATS changent en combat (attaque/défense/attaque
spéciale/défense spéciale/vitesse — jamais les PV, comme dans les vrais jeux). Les
CHANGEMENTS DE TYPE (Méga-Dracaufeu X devient Feu/Dragon, Méga-Jungko devient
Plante/Dragon, Méga-Galeking devient Acier pur, Méga-Léviator devient Eau/Ténèbres,
Méga-Mewtwo X devient Psy/Combat) ne sont PAS encore reflétés dans le calcul
d'efficacité des types en combat — l'infrastructure actuelle (combat.py::resoudre_tour)
lit les types via une recherche Pokédex classique par nom, pas une colonne stockée par
combat, donc appliquer le changement de type demanderait un chantier supplémentaire.
Les stats, elles, s'appliquent intégralement et correctement.
"""

MEGA_EVOLUTIONS = {
    "alakazamite": {
        "espece": "Alakazam", "objet_nom": "Alakazamite", "objet_emoji": "💠",
        "forme_nom": "Méga-Alakazam", "types": ["psy"],
        "stats_detaillees": {"pv": 55, "attaque": 50, "defense": 65, "attaque_spe": 175, "defense_spe": 105, "vitesse": 150},
        "hauteur_dm": 12,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/alakazam-mega.gif",
    },
    "ectoplasmite": {
        "espece": "Ectoplasma", "objet_nom": "Ectoplasmite", "objet_emoji": "💠",
        "forme_nom": "Méga-Ectoplasma", "types": ["spectre", "poison"],
        "stats_detaillees": {"pv": 60, "attaque": 65, "defense": 80, "attaque_spe": 170, "defense_spe": 95, "vitesse": 130},
        "hauteur_dm": 14,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/gengar-mega.gif",
    },
    "kangourexite": {
        "espece": "Kangourex", "objet_nom": "Kangourexite", "objet_emoji": "💠",
        "forme_nom": "Méga-Kangourex", "types": ["normal"],
        "stats_detaillees": {"pv": 105, "attaque": 125, "defense": 100, "attaque_spe": 60, "defense_spe": 100, "vitesse": 100},
        "hauteur_dm": 22,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/kangaskhan-mega.gif",
    },
    "leviatordite": {
        "espece": "Léviator", "objet_nom": "Léviatordite", "objet_emoji": "💠",
        "forme_nom": "Méga-Léviator", "types": ["eau", "tenebres"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 95, "attaque": 155, "defense": 109, "attaque_spe": 70, "defense_spe": 130, "vitesse": 81},
        "hauteur_dm": 65,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/gyarados-mega.gif",
    },
    "absolite": {
        "espece": "Absol", "objet_nom": "Absolite", "objet_emoji": "💠",
        "forme_nom": "Méga-Absol", "types": ["tenebres"],
        "stats_detaillees": {"pv": 65, "attaque": 150, "defense": 60, "attaque_spe": 115, "defense_spe": 60, "vitesse": 115},
        "hauteur_dm": 12,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/absol-mega.gif",
    },
    "tyranocifite": {
        "espece": "Tyranocif", "objet_nom": "Tyranocifite", "objet_emoji": "💠",
        "forme_nom": "Méga-Tyranocif", "types": ["roche", "tenebres"],
        "stats_detaillees": {"pv": 100, "attaque": 164, "defense": 150, "attaque_spe": 95, "defense_spe": 120, "vitesse": 71},
        "hauteur_dm": 25,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/tyranitar-mega.gif",
    },
    "carchacrokite": {
        "espece": "Carchacrok", "objet_nom": "Carchacrokite", "objet_emoji": "💠",
        "forme_nom": "Méga-Carchacrok", "types": ["dragon", "sol"],
        "stats_detaillees": {"pv": 108, "attaque": 170, "defense": 115, "attaque_spe": 120, "defense_spe": 95, "vitesse": 92},
        "hauteur_dm": 19,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/garchomp-mega.gif",
    },
    "gardevoirite": {
        "espece": "Gardevoir", "objet_nom": "Gardevoirite", "objet_emoji": "💠",
        "forme_nom": "Méga-Gardevoir", "types": ["psy", "fee"],
        "stats_detaillees": {"pv": 68, "attaque": 85, "defense": 65, "attaque_spe": 165, "defense_spe": 135, "vitesse": 100},
        "hauteur_dm": 16,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/gardevoir-mega.gif",
    },
    "lucarionite": {
        "espece": "Lucario", "objet_nom": "Lucarionite", "objet_emoji": "💠",
        "forme_nom": "Méga-Lucario", "types": ["combat", "acier"],
        "stats_detaillees": {"pv": 70, "attaque": 145, "defense": 88, "attaque_spe": 140, "defense_spe": 70, "vitesse": 112},
        "hauteur_dm": 13,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/lucario-mega.gif",
    },
    "metalossite": {
        "espece": "Métalosse", "objet_nom": "Métalossite", "objet_emoji": "💠",
        "forme_nom": "Méga-Métalosse", "types": ["acier", "psy"],
        "stats_detaillees": {"pv": 80, "attaque": 145, "defense": 150, "attaque_spe": 105, "defense_spe": 110, "vitesse": 110},
        "hauteur_dm": 25,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/metagross-mega.gif",
    },
    "drattakite": {
        "espece": "Drattak", "objet_nom": "Drattakite", "objet_emoji": "💠",
        "forme_nom": "Méga-Drattak", "types": ["dragon", "vol"],
        "stats_detaillees": {"pv": 95, "attaque": 145, "defense": 130, "attaque_spe": 120, "defense_spe": 90, "vitesse": 120},
        "hauteur_dm": 18,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/salamence-mega.gif",
    },
    "brasegalite": {
        "espece": "Braségali", "objet_nom": "Brasegalite", "objet_emoji": "💠",
        "forme_nom": "Méga-Braségali", "types": ["feu", "combat"],
        "stats_detaillees": {"pv": 80, "attaque": 160, "defense": 80, "attaque_spe": 130, "defense_spe": 80, "vitesse": 100},
        "hauteur_dm": 19,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/blaziken-mega.gif",
    },
    "laggronite": {
        "espece": "Laggron", "objet_nom": "Laggronite", "objet_emoji": "💠",
        "forme_nom": "Méga-Laggron", "types": ["eau", "sol"],
        "stats_detaillees": {"pv": 100, "attaque": 150, "defense": 110, "attaque_spe": 95, "defense_spe": 110, "vitesse": 70},
        "hauteur_dm": 19,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/swampert-mega.gif",
    },
    "jungkoite": {
        "espece": "Jungko", "objet_nom": "Jungkoite", "objet_emoji": "💠",
        "forme_nom": "Méga-Jungko", "types": ["plante", "dragon"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 70, "attaque": 110, "defense": 75, "attaque_spe": 145, "defense_spe": 85, "vitesse": 145},
        "hauteur_dm": 19,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/sceptile-mega.gif",
    },
    "dracaufeuite_x": {
        "espece": "Dracaufeu", "objet_nom": "Dracaufeuite X", "objet_emoji": "💠",
        "forme_nom": "Méga-Dracaufeu X", "types": ["feu", "dragon"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 78, "attaque": 130, "defense": 111, "attaque_spe": 130, "defense_spe": 85, "vitesse": 100},
        "hauteur_dm": 17,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/charizard-megax.gif",
    },
    "dracaufeuite_y": {
        "espece": "Dracaufeu", "objet_nom": "Dracaufeuite Y", "objet_emoji": "💠",
        "forme_nom": "Méga-Dracaufeu Y", "types": ["feu", "vol"],
        "stats_detaillees": {"pv": 78, "attaque": 104, "defense": 78, "attaque_spe": 159, "defense_spe": 115, "vitesse": 100},
        "hauteur_dm": 17,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/charizard-megay.gif",
    },
    "florizarrite": {
        "espece": "Florizarre", "objet_nom": "Florizarrite", "objet_emoji": "💠",
        "forme_nom": "Méga-Florizarre", "types": ["plante", "poison"],
        "stats_detaillees": {"pv": 80, "attaque": 100, "defense": 123, "attaque_spe": 122, "defense_spe": 120, "vitesse": 80},
        "hauteur_dm": 24,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/venusaur-mega.gif",
    },
    "tortankite": {
        "espece": "Tortank", "objet_nom": "Tortankite", "objet_emoji": "💠",
        "forme_nom": "Méga-Tortank", "types": ["eau"],
        "stats_detaillees": {"pv": 79, "attaque": 103, "defense": 120, "attaque_spe": 135, "defense_spe": 115, "vitesse": 78},
        "hauteur_dm": 16,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/blastoise-mega.gif",
    },
    "galekingite": {
        "espece": "Galeking", "objet_nom": "Galekingite", "objet_emoji": "💠",
        "forme_nom": "Méga-Galeking", "types": ["acier"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 70, "attaque": 140, "defense": 230, "attaque_spe": 60, "defense_spe": 80, "vitesse": 50},
        "hauteur_dm": 22,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/aggron-mega.gif",
    },
    "mewtwoite_x": {
        "espece": "Mewtwo", "objet_nom": "Mewtwoïte X", "objet_emoji": "💠",
        "forme_nom": "Méga-Mewtwo X", "types": ["psy", "combat"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 106, "attaque": 190, "defense": 100, "attaque_spe": 154, "defense_spe": 100, "vitesse": 130},
        "hauteur_dm": 23,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/mewtwo-megax.gif",
    },
    "mewtwoite_y": {
        "espece": "Mewtwo", "objet_nom": "Mewtwoïte Y", "objet_emoji": "💠",
        "forme_nom": "Méga-Mewtwo Y", "types": ["psy"],
        "stats_detaillees": {"pv": 106, "attaque": 150, "defense": 70, "attaque_spe": 194, "defense_spe": 120, "vitesse": 140},
        "hauteur_dm": 15,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/mewtwo-megay.gif",
    },

    # --- Lot 2 (extension du 01/09/2026) — 27 Méga-Évolutions supplémentaires,
    # toujours vérifiées contre la table officielle Bulbapedia à la même date ---
    "dardargnanite": {
        "espece": "Dardargnan", "objet_nom": "Dardargnanite", "objet_emoji": "💠",
        "forme_nom": "Méga-Dardargnan", "types": ["insecte", "poison"],
        "stats_detaillees": {"pv": 65, "attaque": 150, "defense": 40, "attaque_spe": 15, "defense_spe": 80, "vitesse": 145},
        "hauteur_dm": 14,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/beedrill-mega.gif",
    },
    "roucarnageite": {
        "espece": "Roucarnage", "objet_nom": "Roucarnageite", "objet_emoji": "💠",
        "forme_nom": "Méga-Roucarnage", "types": ["normal", "vol"],
        "stats_detaillees": {"pv": 83, "attaque": 80, "defense": 80, "attaque_spe": 135, "defense_spe": 80, "vitesse": 121},
        "hauteur_dm": 22,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/pidgeot-mega.gif",
    },
    "melodelfite": {
        "espece": "Mélodelfe", "objet_nom": "Mélodelfite", "objet_emoji": "💠",
        "forme_nom": "Méga-Mélodelfe", "types": ["fee"],
        "stats_detaillees": {"pv": 95, "attaque": 80, "defense": 93, "attaque_spe": 135, "defense_spe": 110, "vitesse": 70},
        "hauteur_dm": 17,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/clefable-mega.gif",
    },
    "empiflorite": {
        "espece": "Empiflor", "objet_nom": "Empiflorite", "objet_emoji": "💠",
        "forme_nom": "Méga-Empiflor", "types": ["plante", "poison"],
        "stats_detaillees": {"pv": 80, "attaque": 125, "defense": 85, "attaque_spe": 135, "defense_spe": 95, "vitesse": 70},
        "hauteur_dm": 45,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/victreebel-mega.gif",
    },
    "flagadossite": {
        "espece": "Flagadoss", "objet_nom": "Flagadossite", "objet_emoji": "💠",
        "forme_nom": "Méga-Flagadoss", "types": ["eau", "psy"],
        "stats_detaillees": {"pv": 95, "attaque": 75, "defense": 180, "attaque_spe": 130, "defense_spe": 80, "vitesse": 30},
        "hauteur_dm": 20,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/slowbro-mega.gif",
    },
    "starossite": {
        "espece": "Staross", "objet_nom": "Starossite", "objet_emoji": "💠",
        "forme_nom": "Méga-Staross", "types": ["eau", "psy"],
        "stats_detaillees": {"pv": 60, "attaque": 100, "defense": 105, "attaque_spe": 130, "defense_spe": 105, "vitesse": 120},
        "hauteur_dm": 23,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/starmie-mega.gif",
    },
    "scarabruteite": {
        "espece": "Scarabrute", "objet_nom": "Scarabruteite", "objet_emoji": "💠",
        "forme_nom": "Méga-Scarabrute", "types": ["insecte", "vol"],
        "stats_detaillees": {"pv": 65, "attaque": 155, "defense": 120, "attaque_spe": 65, "defense_spe": 90, "vitesse": 105},
        "hauteur_dm": 17,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/pinsir-mega.gif",
    },
    "pterite": {
        "espece": "Ptéra", "objet_nom": "Ptérite", "objet_emoji": "💠",
        "forme_nom": "Méga-Ptéra", "types": ["roche", "vol"],
        "stats_detaillees": {"pv": 80, "attaque": 135, "defense": 85, "attaque_spe": 70, "defense_spe": 95, "vitesse": 150},
        "hauteur_dm": 21,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/aerodactyl-mega.gif",
    },
    "dracolosseite": {
        "espece": "Dracolosse", "objet_nom": "Dracolosseite", "objet_emoji": "💠",
        "forme_nom": "Méga-Dracolosse", "types": ["dragon", "vol"],
        "stats_detaillees": {"pv": 91, "attaque": 124, "defense": 115, "attaque_spe": 145, "defense_spe": 125, "vitesse": 100},
        "hauteur_dm": 22,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/dragonite-mega.gif",
    },
    "meganiumite": {
        "espece": "Méganium", "objet_nom": "Méganiumite", "objet_emoji": "💠",
        "forme_nom": "Méga-Méganium", "types": ["plante", "fee"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 80, "attaque": 92, "defense": 115, "attaque_spe": 143, "defense_spe": 115, "vitesse": 80},
        "hauteur_dm": 24,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/meganium-mega.gif",
    },
    "aligatueurite": {
        "espece": "Aligatueur", "objet_nom": "Aligatueurite", "objet_emoji": "💠",
        "forme_nom": "Méga-Aligatueur", "types": ["eau"],
        "stats_detaillees": {"pv": 85, "attaque": 160, "defense": 125, "attaque_spe": 89, "defense_spe": 93, "vitesse": 78},
        "hauteur_dm": 23,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/feraligatr-mega.gif",
    },
    "pharampite": {
        "espece": "Pharamp", "objet_nom": "Pharampite", "objet_emoji": "💠",
        "forme_nom": "Méga-Pharamp", "types": ["electrik", "dragon"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 90, "attaque": 95, "defense": 105, "attaque_spe": 165, "defense_spe": 110, "vitesse": 45},
        "hauteur_dm": 14,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/ampharos-mega.gif",
    },
    "steelixite": {
        "espece": "Steelix", "objet_nom": "Steelixite", "objet_emoji": "💠",
        "forme_nom": "Méga-Steelix", "types": ["acier", "sol"],
        "stats_detaillees": {"pv": 75, "attaque": 125, "defense": 230, "attaque_spe": 55, "defense_spe": 95, "vitesse": 30},
        "hauteur_dm": 105,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/steelix-mega.gif",
    },
    "cizayoxite": {
        "espece": "Cizayox", "objet_nom": "Cizayoxite", "objet_emoji": "💠",
        "forme_nom": "Méga-Cizayox", "types": ["insecte", "acier"],
        "stats_detaillees": {"pv": 70, "attaque": 150, "defense": 140, "attaque_spe": 65, "defense_spe": 100, "vitesse": 75},
        "hauteur_dm": 20,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/scizor-mega.gif",
    },
    "scarhinoite": {
        "espece": "Scarhino", "objet_nom": "Scarhinoite", "objet_emoji": "💠",
        "forme_nom": "Méga-Scarhino", "types": ["insecte", "combat"],
        "stats_detaillees": {"pv": 80, "attaque": 185, "defense": 115, "attaque_spe": 40, "defense_spe": 105, "vitesse": 75},
        "hauteur_dm": 17,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/heracross-mega.gif",
    },
    "airmureite": {
        "espece": "Airmure", "objet_nom": "Airmureite", "objet_emoji": "💠",
        "forme_nom": "Méga-Airmure", "types": ["acier", "vol"],
        "stats_detaillees": {"pv": 65, "attaque": 140, "defense": 110, "attaque_spe": 40, "defense_spe": 100, "vitesse": 110},
        "hauteur_dm": 17,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/skarmory-mega.gif",
    },
    "demolosseite": {
        "espece": "Démolosse", "objet_nom": "Démolosseite", "objet_emoji": "💠",
        "forme_nom": "Méga-Démolosse", "types": ["tenebres", "feu"],
        "stats_detaillees": {"pv": 75, "attaque": 90, "defense": 90, "attaque_spe": 140, "defense_spe": 90, "vitesse": 115},
        "hauteur_dm": 19,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/houndoom-mega.gif",
    },
    "elecsprintite": {
        "espece": "Élecsprint", "objet_nom": "Élecsprintite", "objet_emoji": "💠",
        "forme_nom": "Méga-Élecsprint", "types": ["electrik"],
        "stats_detaillees": {"pv": 70, "attaque": 75, "defense": 80, "attaque_spe": 135, "defense_spe": 80, "vitesse": 135},
        "hauteur_dm": 18,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/manectric-mega.gif",
    },
    "sharpedoite": {
        "espece": "Sharpedo", "objet_nom": "Sharpedoïte", "objet_emoji": "💠",
        "forme_nom": "Méga-Sharpedo", "types": ["eau", "tenebres"],
        "stats_detaillees": {"pv": 70, "attaque": 140, "defense": 70, "attaque_spe": 110, "defense_spe": 65, "vitesse": 105},
        "hauteur_dm": 25,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/sharpedo-mega.gif",
    },
    "cameruptite": {
        "espece": "Camérupt", "objet_nom": "Cameruptite", "objet_emoji": "💠",
        "forme_nom": "Méga-Camérupt", "types": ["feu", "sol"],
        "stats_detaillees": {"pv": 70, "attaque": 120, "defense": 100, "attaque_spe": 145, "defense_spe": 105, "vitesse": 20},
        "hauteur_dm": 25,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/camerupt-mega.gif",
    },
    "altariaite": {
        "espece": "Altaria", "objet_nom": "Altarianite", "objet_emoji": "💠",
        "forme_nom": "Méga-Altaria", "types": ["dragon", "fee"],  # ⚠️ changement de type non reflété, voir en-tête
        "stats_detaillees": {"pv": 75, "attaque": 110, "defense": 110, "attaque_spe": 110, "defense_spe": 105, "vitesse": 80},
        "hauteur_dm": 15,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/altaria-mega.gif",
    },
    "branetteite": {
        "espece": "Branette", "objet_nom": "Branetteite", "objet_emoji": "💠",
        "forme_nom": "Méga-Branette", "types": ["spectre"],
        "stats_detaillees": {"pv": 64, "attaque": 165, "defense": 75, "attaque_spe": 93, "defense_spe": 83, "vitesse": 75},
        "hauteur_dm": 12,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/banette-mega.gif",
    },
    "tenefixite": {
        "espece": "Ténéfix", "objet_nom": "Ténéfixite", "objet_emoji": "💠",
        "forme_nom": "Méga-Ténéfix", "types": ["tenebres", "spectre"],
        "stats_detaillees": {"pv": 50, "attaque": 85, "defense": 125, "attaque_spe": 85, "defense_spe": 115, "vitesse": 20},
        "hauteur_dm": 5,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/sableye-mega.gif",
    },
    "mysdibuleite": {
        "espece": "Mysdibule", "objet_nom": "Mysdibuleite", "objet_emoji": "💠",
        "forme_nom": "Méga-Mysdibule", "types": ["acier", "fee"],
        "stats_detaillees": {"pv": 50, "attaque": 105, "defense": 125, "attaque_spe": 55, "defense_spe": 95, "vitesse": 50},
        "hauteur_dm": 10,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/mawile-mega.gif",
    },
    "charminaite": {
        "espece": "Charmina", "objet_nom": "Charminaite", "objet_emoji": "💠",
        "forme_nom": "Méga-Charmina", "types": ["combat", "psy"],
        "stats_detaillees": {"pv": 60, "attaque": 100, "defense": 85, "attaque_spe": 80, "defense_spe": 85, "vitesse": 100},
        "hauteur_dm": 13,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/medicham-mega.gif",
    },
    "oniglaliite": {
        "espece": "Oniglali", "objet_nom": "Oniglaliite", "objet_emoji": "💠",
        "forme_nom": "Méga-Oniglali", "types": ["glace"],
        "stats_detaillees": {"pv": 80, "attaque": 120, "defense": 80, "attaque_spe": 120, "defense_spe": 80, "vitesse": 100},
        "hauteur_dm": 21,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/glalie-mega.gif",
    },
    "latiasite": {
        "espece": "Latias", "objet_nom": "Latiasite", "objet_emoji": "💠",
        "forme_nom": "Méga-Latias", "types": ["dragon", "psy"],
        "stats_detaillees": {"pv": 80, "attaque": 100, "defense": 120, "attaque_spe": 140, "defense_spe": 150, "vitesse": 110},
        "hauteur_dm": 18,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/latias-mega.gif",
    },
    "latiosite": {
        "espece": "Latios", "objet_nom": "Latiosite", "objet_emoji": "💠",
        "forme_nom": "Méga-Latios", "types": ["dragon", "psy"],
        "stats_detaillees": {"pv": 80, "attaque": 130, "defense": 100, "attaque_spe": 160, "defense_spe": 120, "vitesse": 110},
        "hauteur_dm": 23,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/latios-mega.gif",
    },
    "gallameite": {
        "espece": "Gallame", "objet_nom": "Gallameite", "objet_emoji": "💠",
        "forme_nom": "Méga-Gallame", "types": ["psy", "combat"],
        "stats_detaillees": {"pv": 68, "attaque": 165, "defense": 95, "attaque_spe": 65, "defense_spe": 115, "vitesse": 110},
        "hauteur_dm": 16,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/gallade-mega.gif",
    },
}

# --- Cas spécial : Méga-Rayquaza ---
# Contrairement à toutes les autres Méga-Évolutions, Rayquaza n'a besoin d'AUCUNE
# Pierre Méga — juste de connaître l'attaque Draco-Ascension (vérifiable via
# database.obtenir_attaques_equipees). Défini à part car il ne correspond pas au modèle
# "un objet tenu" des autres entrées de MEGA_EVOLUTIONS ci-dessus.
MEGA_RAYQUAZA = {
    "espece": "Rayquaza",
    "forme_nom": "Méga-Rayquaza",
    "types": ["dragon", "vol"],
    "attaque_requise": "Draco-Ascension",
    "stats_detaillees": {"pv": 105, "attaque": 180, "defense": 100, "attaque_spe": 180, "defense_spe": 100, "vitesse": 115},
    "hauteur_dm": 108,
    "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/rayquaza-mega.gif",
}


def pokemon_effectif_mega(pokemon: dict, mega_actif) -> dict:
    """Applique le SPRITE d'une Méga-Évolution active à un dict Pokémon déjà construit
    (typiquement après formes_objets_module.pokemon_effectif) — pour le rendu visuel
    UNIQUEMENT (combat_visuel.py). Ne touche ni les stats de combat (déjà appliquées à
    l'activation, voir database.activer_mega_evolution_combat) ni les types utilisés en
    combat (voir la limite connue en en-tête de ce fichier).

    mega_actif = résultat de database.obtenir_mega_actif(combat_id, user_id) : soit
    None (personne n'a activé sa Méga ce combat), soit (pokemon_nom, cle_stone).
    cle_stone distingue les variantes X/Y (Dracaufeu, Mewtwo) ; vaut None pour
    Rayquaza, qui n'a qu'une seule Méga et pas de pierre."""
    if not mega_actif:
        return pokemon
    pokemon_nom_mega, cle_stone = mega_actif
    if pokemon.get("nom") != pokemon_nom_mega:
        return pokemon  # ce n'est pas CE Pokémon qui est Méga-Évolué en ce moment

    info = MEGA_RAYQUAZA if (pokemon_nom_mega == "Rayquaza" and not cle_stone) else MEGA_EVOLUTIONS.get(cle_stone)
    if not info:
        return pokemon
    return {**pokemon, "sprite_gif_url_showdown": info["sprite_gif_url_showdown"], "hauteur_dm": info["hauteur_dm"]}


def stone_pour_espece(nom_espece: str) -> dict | None:
    """Retourne l'entrée MEGA_EVOLUTIONS correspondant à cette espèce (avec sa clé
    ajoutée sous 'cle'), ou None si elle n'a pas de Méga-Évolution disponible ici. Ne
    gère qu'UNE mega par espèce dans la liste actuelle (Dracaufeu et Mewtwo font
    exception avec 2 clés, X/Y — cette fonction retourne alors la PREMIÈRE trouvée ;
    utiliser directement la clé si les deux variantes doivent être distinguées, par
    exemple pour lister les deux pierres au joueur plutôt que d'en choisir une seule)."""
    for cle, info in MEGA_EVOLUTIONS.items():
        if info["espece"] == nom_espece:
            return {**info, "cle": cle}
    return None


def stones_pour_espece(nom_espece: str) -> list:
    """Comme stone_pour_espece, mais retourne TOUTES les variantes (utile pour
    Dracaufeu X/Y et Mewtwo X/Y, qui ont chacun 2 pierres distinctes)."""
    return [{**info, "cle": cle} for cle, info in MEGA_EVOLUTIONS.items() if info["espece"] == nom_espece]
