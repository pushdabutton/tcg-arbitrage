"""Seed list of top 50 most-traded Pokemon cards for MVP scraping.

Each entry maps to a PriceCharting URL slug.
URL pattern: https://www.pricecharting.com/game/pokemon-{set_slug}/{card_slug}
"""

from __future__ import annotations

from scraper.models import Card

# fmt: off
TOP_50_CARDS: list[Card] = [
    # --- Base Set Classics ---
    Card(name="Charizard",          set_name="Base Set",           pricecharting_id="pokemon-base-set/charizard-4"),
    Card(name="Blastoise",          set_name="Base Set",           pricecharting_id="pokemon-base-set/blastoise-2"),
    Card(name="Venusaur",           set_name="Base Set",           pricecharting_id="pokemon-base-set/venusaur-15"),
    Card(name="Pikachu",            set_name="Base Set",           pricecharting_id="pokemon-base-set/pikachu-58"),
    Card(name="Mewtwo",             set_name="Base Set",           pricecharting_id="pokemon-base-set/mewtwo-10"),
    Card(name="Alakazam",           set_name="Base Set",           pricecharting_id="pokemon-base-set/alakazam-1"),
    Card(name="Gyarados",           set_name="Base Set",           pricecharting_id="pokemon-base-set/gyarados-6"),
    Card(name="Chansey",            set_name="Base Set",           pricecharting_id="pokemon-base-set/chansey-3"),
    Card(name="Ninetales",          set_name="Base Set",           pricecharting_id="pokemon-base-set/ninetales-12"),
    Card(name="Zapdos",             set_name="Base Set",           pricecharting_id="pokemon-base-set/zapdos-16"),

    # --- Jungle ---
    Card(name="Flareon",            set_name="Jungle",             pricecharting_id="pokemon-jungle/flareon-3"),
    Card(name="Jolteon",            set_name="Jungle",             pricecharting_id="pokemon-jungle/jolteon-4"),
    Card(name="Vaporeon",           set_name="Jungle",             pricecharting_id="pokemon-jungle/vaporeon-12"),

    # --- Fossil ---
    Card(name="Gengar",             set_name="Fossil",             pricecharting_id="pokemon-fossil/gengar-5"),
    Card(name="Dragonite",          set_name="Fossil",             pricecharting_id="pokemon-fossil/dragonite-4"),
    Card(name="Moltres",            set_name="Fossil",             pricecharting_id="pokemon-fossil/moltres-12"),

    # --- Team Rocket ---
    Card(name="Dark Charizard",     set_name="Team Rocket",        pricecharting_id="pokemon-team-rocket/dark-charizard-4"),
    Card(name="Dark Blastoise",     set_name="Team Rocket",        pricecharting_id="pokemon-team-rocket/dark-blastoise-3"),

    # --- Base Set 2 ---
    Card(name="Charizard",          set_name="Base Set 2",         pricecharting_id="pokemon-base-set-2/charizard-4"),

    # --- Neo Genesis ---
    Card(name="Lugia",              set_name="Neo Genesis",        pricecharting_id="pokemon-neo-genesis/lugia-9"),
    Card(name="Typhlosion",         set_name="Neo Genesis",        pricecharting_id="pokemon-neo-genesis/typhlosion-17"),

    # --- Neo Discovery ---
    Card(name="Umbreon",            set_name="Neo Discovery",      pricecharting_id="pokemon-neo-discovery/umbreon-13"),
    Card(name="Espeon",             set_name="Neo Discovery",      pricecharting_id="pokemon-neo-discovery/espeon-1"),

    # --- Legendary Collection ---
    Card(name="Charizard",          set_name="Legendary Collection", pricecharting_id="pokemon-legendary-collection/charizard-3"),

    # --- Skyridge ---
    Card(name="Charizard",          set_name="Skyridge",           pricecharting_id="pokemon-skyridge/charizard-146"),
    Card(name="Crystal Charizard",  set_name="Skyridge",           pricecharting_id="pokemon-skyridge/charizard-h9"),

    # --- EX Era ---
    Card(name="Charizard ex",       set_name="EX Fire Red Leaf Green", pricecharting_id="pokemon-ex-firered-&-leafgreen/charizard-ex-105"),
    Card(name="Rayquaza ex",        set_name="EX Deoxys",         pricecharting_id="pokemon-ex-deoxys/rayquaza-ex-102"),

    # --- Diamond & Pearl ---
    Card(name="Charizard",          set_name="Stormfront",         pricecharting_id="pokemon-stormfront/charizard-103"),

    # --- HGSS ---
    Card(name="Lugia LEGEND",       set_name="HeartGold SoulSilver", pricecharting_id="pokemon-heartgold-soulsilver/lugia-legend-113"),

    # --- Black & White ---
    Card(name="Mewtwo EX",          set_name="Next Destinies",     pricecharting_id="pokemon-next-destinies/mewtwo-ex-98"),
    Card(name="Charizard",          set_name="Boundaries Crossed",  pricecharting_id="pokemon-boundaries-crossed/charizard-20"),

    # --- XY Era ---
    Card(name="Charizard EX",       set_name="Flashfire",          pricecharting_id="pokemon-flashfire/charizard-ex-11"),
    Card(name="Mega Charizard EX",  set_name="Flashfire",          pricecharting_id="pokemon-flashfire/mega-charizard-ex-13"),

    # --- Sun & Moon ---
    Card(name="Charizard GX",       set_name="Burning Shadows",    pricecharting_id="pokemon-burning-shadows/charizard-gx-20"),
    Card(name="Umbreon GX",         set_name="Sun & Moon",         pricecharting_id="pokemon-sun-&-moon-base-set/umbreon-gx-80"),
    Card(name="Pikachu GX",         set_name="SM Promo",           pricecharting_id="pokemon-sm-promos/pikachu-gx-sm232"),

    # --- Sword & Shield ---
    Card(name="Charizard VMAX",     set_name="Champions Path",     pricecharting_id="pokemon-champions-path/charizard-vmax-74"),
    Card(name="Charizard V",        set_name="Champions Path",     pricecharting_id="pokemon-champions-path/charizard-v-79"),
    Card(name="Pikachu VMAX",       set_name="Vivid Voltage",      pricecharting_id="pokemon-vivid-voltage/pikachu-vmax-44"),
    Card(name="Umbreon VMAX",       set_name="Evolving Skies",     pricecharting_id="pokemon-evolving-skies/umbreon-vmax-215"),
    Card(name="Rayquaza VMAX",      set_name="Evolving Skies",     pricecharting_id="pokemon-evolving-skies/rayquaza-vmax-218"),
    Card(name="Charizard VSTAR",    set_name="Brilliant Stars",    pricecharting_id="pokemon-brilliant-stars/charizard-vstar-18"),
    Card(name="Giratina VSTAR",     set_name="Lost Origin",        pricecharting_id="pokemon-lost-origin/giratina-vstar-131"),

    # --- Scarlet & Violet ---
    Card(name="Charizard ex",       set_name="Obsidian Flames",    pricecharting_id="pokemon-obsidian-flames/charizard-ex-215"),
    Card(name="Mew ex",             set_name="Paldea Evolved",     pricecharting_id="pokemon-paldea-evolved/mew-ex-232"),
    Card(name="Miraidon ex",        set_name="Scarlet & Violet",   pricecharting_id="pokemon-scarlet-&-violet/miraidon-ex-253"),

    # --- Crown Zenith / Special ---
    Card(name="Charizard VSTAR",    set_name="Crown Zenith",       pricecharting_id="pokemon-crown-zenith/charizard-vstar-gg70"),
    Card(name="Pikachu VMAX",       set_name="Crown Zenith",       pricecharting_id="pokemon-crown-zenith/pikachu-vmax-gg30"),
    Card(name="Mewtwo VSTAR",       set_name="Pokemon Go",         pricecharting_id="pokemon-go/mewtwo-vstar-079"),
]
# fmt: on
