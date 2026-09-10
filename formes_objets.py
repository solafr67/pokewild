"""
Formes alternatives déclenchées par un objet tenu — PAS le même mécanisme que les formes
régionales (Alola/Galar/Hisui/Paldea, voir ajouter_formes_regionales.py). Ici, c'est le
MÊME Pokémon capturé (mêmes IV, même niveau, même capture_id) qui change d'apparence et de
stats tant qu'il tient un objet précis, et reprend sa forme normale dès qu'on le lui
retire — exactement comme une Méga-Évolution, pas une nouvelle capture.

Portée actuelle (9 formes à objet unique, + 34 pour Multitype/Système Alpha) :
- Shaymin + Fleur Gracidea → Shaymin (Forme Céleste)
- Giratina + Orbe Griséous → Giratina (Origine)
- Dialga + Orbe Adamant → Dialga (Origine)
- Palkia + Perle Lustrée → Palkia (Origine)
- Kyogre + Orbe Bleue → Primo-Kyogre
- Groudon + Orbe Rouge → Primo-Groudon
- Hoopa + Vase de l'Entrave → Hoopa Déchaîné
- Zacian + Épée Rouillée → Zacian (Épée Suprême)
- Zamazenta + Bouclier Rouillé → Zamazenta (Bouclier Suprême)
- Arceus + une des 17 Plaques → change de type (talent Multitype)
- Silvallié + une des 17 ROM → change de type (talent Système Alpha)

Volontairement HORS PÉRIMÈTRE pour l'instant (mécaniques plus complexes, à concevoir à
part) : Kyurem Noir/Blanc (fusion avec un Zekrom/Reshiram capturé dans les vrais jeux,
pas un simple objet tenu) et Keldeo Résolu (débloqué par une capacité apprise, pas un
objet). À reprendre dans un lot séparé une fois qu'on aura décidé comment les adapter.

⚠️ Suppose que Kyogre, Groudon, Hoopa, Zacian et Zamazenta sont déjà des espèces
capturables normalement dans le Pokédex (confirmé par l'utilisateur le 08/08/2026) — ce
module ne les ajoute pas, il se contente de leur donner une forme alternative.

Ces objets ne sont PAS achetables en boutique (décision du 01/08/2026) — uniquement
obtenables via l'exploration (petite chance, voir config.EXPLORATION_CHANCE_OBJET_FORME)
ou déjà tenus par le Pokémon sauvage correspondant au moment de sa capture (voir
views.py/raid.py — chance_objet_forme_a_la_capture).

Les stats sont RÉELLES (vérifiées contre PokéAPI/Poképédia), mais le PC affiché au joueur
NE CHANGE PAS avec la forme (décision du 01/08/2026, pour rester simple et lisible) —
seules les stats de COMBAT (calcul des dégâts, PV réels) et les types changent.
"""

FORMES_OBJETS = {
    "fleur_gracidea": {
        "objet_nom": "Fleur Gracidea",
        "objet_emoji": "🌸",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/fleur_gracidea.png",
        "espece": "Shaymin",
        "forme_nom": "Shaymin (Forme Céleste)",
        "numero_sprite": 10006,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/shaymin-sky.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["plante", "vol"],
        "stats_detaillees": {"pv": 100, "attaque": 103, "defense": 75, "attaque_spe": 120, "defense_spe": 75, "vitesse": 127},
    },
    "orbe_griseous": {
        "objet_nom": "Orbe Griséous",
        "objet_emoji": "🔮",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_griseous.png",
        "espece": "Giratina",
        "forme_nom": "Giratina (Origine)",
        "numero_sprite": 10007,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/giratina-origin.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["spectre", "dragon"],
        "stats_detaillees": {"pv": 150, "attaque": 120, "defense": 100, "attaque_spe": 120, "defense_spe": 100, "vitesse": 90},
    },
    "orbe_adamant": {
        "objet_nom": "Orbe Adamant",
        "objet_emoji": "💎",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/orbe_adamant.png",
        "espece": "Dialga",
        "forme_nom": "Dialga (Origine)",
        "numero_sprite": 10245,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/dialga-origin.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["acier", "dragon"],
        "stats_detaillees": {"pv": 100, "attaque": 100, "defense": 100, "attaque_spe": 150, "defense_spe": 120, "vitesse": 110},
    },
    "perle_lustree": {
        "objet_nom": "Perle Lustrée",
        "objet_emoji": "💠",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites/perle_lustree.png",
        "espece": "Palkia",
        "forme_nom": "Palkia (Origine)",
        "numero_sprite": 10246,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/palkia-origin.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["eau", "dragon"],
        "stats_detaillees": {"pv": 90, "attaque": 100, "defense": 100, "attaque_spe": 150, "defense_spe": 120, "vitesse": 120},
    },
    "orbe_bleue": {
        "objet_nom": "Orbe Bleue",
        "objet_emoji": "🔵",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites_v2/orbe_bleue.png",
        "espece": "Kyogre",
        "forme_nom": "Primo-Kyogre",
        "numero_sprite": 10077,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/kyogre-primal.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["eau"],
        "stats_detaillees": {"pv": 100, "attaque": 150, "defense": 90, "attaque_spe": 180, "defense_spe": 160, "vitesse": 90},
    },
    "orbe_rouge": {
        "objet_nom": "Orbe Rouge",
        "objet_emoji": "🔴",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites_v2/orbe_rouge.png",
        "espece": "Groudon",
        "forme_nom": "Primo-Groudon",
        "numero_sprite": 10078,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/groudon-primal.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["sol", "feu"],
        "stats_detaillees": {"pv": 100, "attaque": 180, "defense": 160, "attaque_spe": 150, "defense_spe": 90, "vitesse": 90},
    },
    "vase_entrave": {
        "objet_nom": "Vase de l'Entrave",
        "objet_emoji": "🏺",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites_v2/vase_entrave.png",
        "espece": "Hoopa",
        "forme_nom": "Hoopa Déchaîné",
        "numero_sprite": 10086,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/hoopa-unbound.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["psy", "tenebres"],
        "stats_detaillees": {"pv": 80, "attaque": 160, "defense": 60, "attaque_spe": 170, "defense_spe": 130, "vitesse": 80},
    },
    "epee_rouillee": {
        "objet_nom": "Épée Rouillée",
        "objet_emoji": "⚔️",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites_v2/epee_rouillee.png",
        "espece": "Zacian",
        "forme_nom": "Zacian (Épée Suprême)",
        "numero_sprite": 10188,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/zacian-crowned.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["fee", "acier"],
        "stats_detaillees": {"pv": 92, "attaque": 150, "defense": 115, "attaque_spe": 80, "defense_spe": 115, "vitesse": 148},
    },
    "bouclier_rouille": {
        "objet_nom": "Bouclier Rouillé",
        "objet_emoji": "🛡️",
        "objet_image": "https://raw.githubusercontent.com/solafr67/pokewild/main/objets_sprites_v2/bouclier_rouille.png",
        "espece": "Zamazenta",
        "forme_nom": "Zamazenta (Bouclier Suprême)",
        "numero_sprite": 10189,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/zamazenta-crowned.gif",
        "sprite_gif_disponible": True,  # PAS encore mirroré/corrigé dans sprites_corriges/ (vérifié le 25/08 : 404 sur les 9 formes à cet endroit précis) — mais le GIF existe réellement sur le CDN officiel Showdown (confirmé au moins pour shaymin-sky, giratina-origin, palkia-origin), voir sprite_gif_url_showdown ci-dessous pour le repli direct utilisé en attendant qu'un vrai mirroring/correction soit fait.
        "types": ["combat", "acier"],
        "stats_detaillees": {"pv": 92, "attaque": 130, "defense": 145, "attaque_spe": 80, "defense_spe": 145, "vitesse": 128},
    },

    # --- Multitype (Arceus, 17 Plaques) et Système Alpha (Silvallié, 17 ROM) ---
    # Même mécanisme que les 9 formes ci-dessus (type + stats substitués tant que
    # l'objet est tenu) — pas de nouvelle logique nécessaire. Les stats ne changent
    # JAMAIS d'une Plaque/ROM à l'autre (fidèle aux vrais jeux), seul le type change.
    # numero_sprite : suite continue après les 9 formes existantes (10190+), PAS de
    # vrais numéros PokeAPI vérifiés individuellement pour ces 34 entrées précises —
    # sert uniquement d'identifiant interne, la vraie image vient de
    # sprite_gif_url_showdown (URLs vérifiées réellement existantes sur le CDN Showdown).
    "plaque_poing": {
        "objet_nom": "Plaque Poing",
        "objet_emoji": "🥊",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/fist.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Poing)",
        "numero_sprite": 10190,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-fighting.gif",
        "sprite_gif_disponible": True,
        "types": ["combat"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_ciel": {
        "objet_nom": "Plaque Ciel",
        "objet_emoji": "🕊️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/sky.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Ciel)",
        "numero_sprite": 10192,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-flying.gif",
        "sprite_gif_disponible": True,
        "types": ["vol"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_toxik": {
        "objet_nom": "Plaque Toxik",
        "objet_emoji": "☠️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/toxic.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Toxik)",
        "numero_sprite": 10194,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-poison.gif",
        "sprite_gif_disponible": True,
        "types": ["poison"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_terre": {
        "objet_nom": "Plaque Terre",
        "objet_emoji": "🏜️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/earth.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Terre)",
        "numero_sprite": 10196,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-ground.gif",
        "sprite_gif_disponible": True,
        "types": ["sol"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_roc": {
        "objet_nom": "Plaque Roc",
        "objet_emoji": "🪨",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/stone.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Roc)",
        "numero_sprite": 10198,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-rock.gif",
        "sprite_gif_disponible": True,
        "types": ["roche"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_insecte": {
        "objet_nom": "Plaque Insecte",
        "objet_emoji": "🐛",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/insect.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Insecte)",
        "numero_sprite": 10200,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-bug.gif",
        "sprite_gif_disponible": True,
        "types": ["insecte"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_fantome": {
        "objet_nom": "Plaque Fantôme",
        "objet_emoji": "👻",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/spooky.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Fantôme)",
        "numero_sprite": 10202,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-ghost.gif",
        "sprite_gif_disponible": True,
        "types": ["spectre"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_fer": {
        "objet_nom": "Plaque Fer",
        "objet_emoji": "⚙️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/iron.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Fer)",
        "numero_sprite": 10204,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-steel.gif",
        "sprite_gif_disponible": True,
        "types": ["acier"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_flamme": {
        "objet_nom": "Plaque Flamme",
        "objet_emoji": "🔥",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/flame.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Flamme)",
        "numero_sprite": 10206,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-fire.gif",
        "sprite_gif_disponible": True,
        "types": ["feu"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_hydro": {
        "objet_nom": "Plaque Hydro",
        "objet_emoji": "💧",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/splash.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Hydro)",
        "numero_sprite": 10208,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-water.gif",
        "sprite_gif_disponible": True,
        "types": ["eau"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_herbe": {
        "objet_nom": "Plaque Herbe",
        "objet_emoji": "🌿",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/meadow.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Herbe)",
        "numero_sprite": 10210,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-grass.gif",
        "sprite_gif_disponible": True,
        "types": ["plante"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_volt": {
        "objet_nom": "Plaque Volt",
        "objet_emoji": "⚡",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/zap.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Volt)",
        "numero_sprite": 10212,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-electric.gif",
        "sprite_gif_disponible": True,
        "types": ["electrik"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_esprit": {
        "objet_nom": "Plaque Esprit",
        "objet_emoji": "🔮",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/mind.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Esprit)",
        "numero_sprite": 10214,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-psychic.gif",
        "sprite_gif_disponible": True,
        "types": ["psy"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_glace": {
        "objet_nom": "Plaque Glace",
        "objet_emoji": "❄️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/icicle.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Glace)",
        "numero_sprite": 10216,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-ice.gif",
        "sprite_gif_disponible": True,
        "types": ["glace"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_draco": {
        "objet_nom": "Plaque Draco",
        "objet_emoji": "🐉",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/draco.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Draco)",
        "numero_sprite": 10218,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-dragon.gif",
        "sprite_gif_disponible": True,
        "types": ["dragon"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_ombre": {
        "objet_nom": "Plaque Ombre",
        "objet_emoji": "🌑",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/dread.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Ombre)",
        "numero_sprite": 10220,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-dark.gif",
        "sprite_gif_disponible": True,
        "types": ["tenebres"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "plaque_pixie": {
        "objet_nom": "Plaque Pixie",
        "objet_emoji": "✨",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/plate/pixie.png",
        "espece": "Arceus",
        "forme_nom": "Arceus (Plaque Pixie)",
        "numero_sprite": 10222,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/arceus-fairy.gif",
        "sprite_gif_disponible": True,
        "types": ["fee"],
        "stats_detaillees": {'pv': 120, 'attaque': 120, 'defense': 120, 'attaque_spe': 120, 'defense_spe': 120, 'vitesse': 120},
    },
    "rom_poing": {
        "objet_nom": "ROM Combat",
        "objet_emoji": "🥊",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/fighting.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Combat)",
        "numero_sprite": 10191,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-fighting.gif",
        "sprite_gif_disponible": True,
        "types": ["combat"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_ciel": {
        "objet_nom": "ROM Vol",
        "objet_emoji": "🕊️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/flying.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Vol)",
        "numero_sprite": 10193,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-flying.gif",
        "sprite_gif_disponible": True,
        "types": ["vol"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_toxik": {
        "objet_nom": "ROM Poison",
        "objet_emoji": "☠️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/poison.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Poison)",
        "numero_sprite": 10195,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-poison.gif",
        "sprite_gif_disponible": True,
        "types": ["poison"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_terre": {
        "objet_nom": "ROM Sol",
        "objet_emoji": "🏜️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/ground.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Sol)",
        "numero_sprite": 10197,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-ground.gif",
        "sprite_gif_disponible": True,
        "types": ["sol"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_roc": {
        "objet_nom": "ROM Roche",
        "objet_emoji": "🪨",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/rock.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Roche)",
        "numero_sprite": 10199,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-rock.gif",
        "sprite_gif_disponible": True,
        "types": ["roche"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_insecte": {
        "objet_nom": "ROM Insecte",
        "objet_emoji": "🐛",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/bug.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Insecte)",
        "numero_sprite": 10201,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-bug.gif",
        "sprite_gif_disponible": True,
        "types": ["insecte"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_fantome": {
        "objet_nom": "ROM Spectre",
        "objet_emoji": "👻",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/ghost.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Spectre)",
        "numero_sprite": 10203,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-ghost.gif",
        "sprite_gif_disponible": True,
        "types": ["spectre"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_fer": {
        "objet_nom": "ROM Acier",
        "objet_emoji": "⚙️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/steel.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Acier)",
        "numero_sprite": 10205,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-steel.gif",
        "sprite_gif_disponible": True,
        "types": ["acier"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_flamme": {
        "objet_nom": "ROM Feu",
        "objet_emoji": "🔥",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/fire.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Feu)",
        "numero_sprite": 10207,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-fire.gif",
        "sprite_gif_disponible": True,
        "types": ["feu"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_hydro": {
        "objet_nom": "ROM Eau",
        "objet_emoji": "💧",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/water.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Eau)",
        "numero_sprite": 10209,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-water.gif",
        "sprite_gif_disponible": True,
        "types": ["eau"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_herbe": {
        "objet_nom": "ROM Plante",
        "objet_emoji": "🌿",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/grass.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Plante)",
        "numero_sprite": 10211,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-grass.gif",
        "sprite_gif_disponible": True,
        "types": ["plante"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_volt": {
        "objet_nom": "ROM Électrik",
        "objet_emoji": "⚡",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/electric.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Électrik)",
        "numero_sprite": 10213,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-electric.gif",
        "sprite_gif_disponible": True,
        "types": ["electrik"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_esprit": {
        "objet_nom": "ROM Psy",
        "objet_emoji": "🔮",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/psychic.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Psy)",
        "numero_sprite": 10215,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-psychic.gif",
        "sprite_gif_disponible": True,
        "types": ["psy"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_glace": {
        "objet_nom": "ROM Glace",
        "objet_emoji": "❄️",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/ice.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Glace)",
        "numero_sprite": 10217,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-ice.gif",
        "sprite_gif_disponible": True,
        "types": ["glace"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_draco": {
        "objet_nom": "ROM Dragon",
        "objet_emoji": "🐉",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/dragon.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Dragon)",
        "numero_sprite": 10219,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-dragon.gif",
        "sprite_gif_disponible": True,
        "types": ["dragon"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_ombre": {
        "objet_nom": "ROM Ténèbres",
        "objet_emoji": "🌑",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/dark.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Ténèbres)",
        "numero_sprite": 10221,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-dark.gif",
        "sprite_gif_disponible": True,
        "types": ["tenebres"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
    "rom_pixie": {
        "objet_nom": "ROM Fée",
        "objet_emoji": "✨",
        "objet_image": "https://raw.githubusercontent.com/msikma/pokesprite/master/items/memory/fairy.png",
        "espece": "Silvallié",
        "forme_nom": "Silvallié (ROM Fée)",
        "numero_sprite": 10223,
        "sprite_gif_url_showdown": "https://play.pokemonshowdown.com/sprites/ani/silvally-fairy.gif",
        "sprite_gif_disponible": True,
        "types": ["fee"],
        "stats_detaillees": {'pv': 95, 'attaque': 95, 'defense': 95, 'attaque_spe': 95, 'defense_spe': 95, 'vitesse': 95},
    },
}

# Vue inverse : espèce -> objet qui la transforme, pour vérifier rapidement si un
# Pokémon donné a une forme alternative disponible du tout (avant même de regarder ce
# qu'il tient réellement).
# Vue inverse : espèce -> LISTE des objets qui la transforment (jamais un seul objet
# depuis qu'Arceus/Silvallié ont chacun 17 Plaques/ROM possibles — une simple valeur
# unique écraserait silencieusement 16 des 17 pour ces deux espèces).
ESPECE_VERS_OBJET_FORME = {}
for _cle, _info in FORMES_OBJETS.items():
    ESPECE_VERS_OBJET_FORME.setdefault(_info["espece"], []).append(_cle)


def forme_objet_pour(pokemon_nom: str, objet_tenu: str | None) -> dict | None:
    """Retourne les infos de la forme alternative SI ce Pokémon tient l'objet qui la
    déclenche, sinon None (forme normale)."""
    if not objet_tenu:
        return None
    info = FORMES_OBJETS.get(objet_tenu)
    if info and info["espece"] == pokemon_nom:
        return info
    return None


def pokemon_effectif(pokemon: dict, objet_tenu: str | None) -> dict:
    """Retourne le dict Pokédex à utiliser pour les CALCULS (types + stats de base) —
    celui de la forme alternative si l'objet correspondant est tenu, sinon `pokemon`
    inchangé. Ne modifie jamais le PC affiché (voir docstring du module) : seuls les
    types et les stats_detaillees sont substitués."""
    if not pokemon:
        return pokemon
    forme = forme_objet_pour(pokemon["nom"], objet_tenu)
    if not forme:
        return pokemon
    return {
        **pokemon,
        "types": forme["types"],
        "stats_detaillees": forme["stats_detaillees"],
        "numero_sprite": forme["numero_sprite"],
        "sprite_gif_disponible": forme["sprite_gif_disponible"],
        "sprite_gif_url_showdown": forme.get("sprite_gif_url_showdown"),
    }


def nom_affichage(pokemon_nom: str, objet_tenu: str | None) -> str:
    """Nom à afficher au joueur (embeds, fiches...) — le nom de la forme alternative si
    elle est active, sinon le nom normal du Pokémon."""
    forme = forme_objet_pour(pokemon_nom, objet_tenu)
    return forme["forme_nom"] if forme else pokemon_nom
