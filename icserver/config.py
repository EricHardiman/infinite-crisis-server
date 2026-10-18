"""Configuration: config.toml next to ic.py, merged over the defaults below.

Every value the old server had hard-coded in its source lives here, so testing
a different champion, spawn point or timing never means editing code.
"""
import copy
import os

try:
    import tomllib
except ImportError:          # Python < 3.11: doctor reports it, nothing else works anyway
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "game": {
        # Folder that contains InfiniteCrisis.exe and the rp\ data packs.
        "dir": r"C:\Program Files (x86)\Steam\steamapps\common\Infinite Crisis Steam",
        "exe": "InfiniteCrisis.exe",
        "patched_exe": "InfiniteCrisis_patched.exe",
        "language": "en",
        "region": "NA",
        # CPU affinity mask for the client ("" = leave alone). The old project
        # always kept the game off CPU 0 (FFFE).
        "cpu_affinity": "FFFE",
    },
    "server": {
        "host": "127.0.0.1",
        "soap_port": 8888,
        "user_port": 9000,
        "game_port": 9001,
        "key": "keys/server_private.pem",
        # champions.json (roster extracted from the packs). Empty = search
        # data\champions.json, then <game dir>\_server\champions.json.
        "champions_json": "",
    },
    "account": {
        # 2026-10-17 21:40 (tester): after a match the Champions and Amplifiers tabs were empty; the
        # client's unanswered 0x21A4 / 0x2116 are answered with the login's champion data, character
        # list and item statuses again (False = ignore them)
        "resend_collections": True,
        "level": 30,            # veteran level: skips the trainee light-pack load
        "player_name": "Player",
        # 2026-10-16 14:02 (tester): every Protector (avatar) icon of the
        # profile is owned (icserver/cosmetics.py, read from the UI pack)
        "unlock_avatar_icons": True,
        # 2026-10-16 14:41: the home header (name + Protector icon slots) at login
        "send_profile_header": True,
        # 2026-10-16 15:31 (tester: the Amplifiers tab is empty): every augment
        # and mod of catalog/data/amplifiers.tsv is owned (0x20B8 content types
        # 12 Augments / 13 Mods)
        "unlock_amplifiers": True,
        # 2026-10-16 15:44 (tester): champions of the install that are not in
        # data/champions.json are found in the packs and added (icserver/roster.py)
        "extra_champions": True,
        # 2026-10-16 16:36 (tester): also the champions that were never released
        # (John Stewart: own graph, skill set and pictures, no sound bank).
        "unreleased_champions": True,
        # 2026-10-16 16:36 (tester: Robin, Arcane Supergirl, Star Sapphire not
        # available): drop costumes that repeat the champion's own variant.
        "skip_base_costumes": True,
    },
    # the companion app (icserver/webapp.py, python ic.py app): the new interface
    # 2026-10-16 15:59 (tester): "redesign the whole interface, modern and nice,
    # one that works for everything" -> the companion app (python ic.py app,
    # icserver/webapp.py). Its Play button starts the game and queues the match.
    "app": {
        "launch_game": True,           # Play starts the game client when it is not running
        "queue_after_login": True,     # ...and queues the chosen encounter right after the login
        "queue_after_login_delay": 1.5,
        "open_window": True,           # ic.py app opens the app (Edge app window, else the browser)
        # 2026-10-16 16:51 (tester): friends list and chat in the app
        # (icserver/social.py). Empty = data/social.json.
        "social_file": "",
        # 2026-10-16 16:58 (tester): legacy interface (the game's menus) on the
        # first start, a switch in each interface, and after a match the chosen
        # one comes back (icserver/interface.py).
        # 2026-10-16 17:29 (tester): Ctrl+1..4 emotes, watched by the server while
        # the game window is in front (icserver/emotes.py)
        "emote_keys": True,
        "default_interface": "legacy",
        "switch_hotkey": "ctrl+shift+u",        # in the game: switch to the new interface
        "return_to_app_after_match": True,       # new interface: minimize the game, show the app
        "return_to_app_delay": 3.0,              # seconds after the end page closes
    },
    "match": {
        # Send the champion's skill ranks as the client's own rank array
        # (property 0x100000AF); needed for the client to allow casting Q.
        "rank_array": True,
        # 2026-10-16 15:44 (tester): queue the player as soon as the encounter's
        # overview movie ends (its preference arrives ~1-1.5 s before JoinQueue)
        # so the loading screen follows the movie without the Launch screen.
        # 2026-10-16 16:23 (tester): rolled back. The movie was cut after half a
        # second, its audio played over the loading screen and no dialogue line
        # had sound in the match. The client must queue by itself.
        "queue_on_movie_end": False,
        # 2026-10-16 17:16 (tester): after the overview movie the client went
        # back to the Launch screen without queuing; when that screen asks for
        # its banners (0x212E) within this many seconds of the movie, the server
        # queues the player (the movie is over by then, nothing is cut).
        # 2026-10-16 18:54 (tester): after Exit Match the tutorial could not be
        # launched again; leaving the world (0x12D) now ends the match too
        "leave_unfinished": True,
        "queue_after_movie": True,
        "queue_after_movie_window": 90,
        # Vitals (0x42): put health / Will in the client's first list instead of
        # the second (the HUD shows their sum). Test for "not enough Will" on Q.
        "vitals_first_list": True,
        "champion": 0x40000086,         # Gaslight Batman variant (Tutorial 1)
        "agent_class": 0x40000086,      # descriptor of the champion object you control
        # Descriptor of the "player object". The original game had a separate,
        # invisible object here; the old server reused Batman (= a second,
        # gliding Batman drawn over the walking one). 0x4000007C is the
        # "Unnamed Player" variant (always-loaded pack 0xa0000037, no model).
        # `python ic.py play --classic` goes back to 0x40000086.
        "player_class": 0x4000007C,
        # Extra packs the match must load (0x20AF). 0xA000024C is the tutorial's
        # zone pack (category 0xd: the client has ONE slot for it, diag 2026-10-14;
        # another zone pack such as 0xA000009A takes the slot and the load hangs).
        # 0xA00000CC: Gaslight Catwoman's heavy pack (she is in cinematic 0x35000034).
        "packs": [0xA0000076, 0xA000024C, 0xA00000CC],
        # 2026-10-16 19:20 (tester: "si intentalo"): zone packs loaded as well when
        # the exe has the two-zone-slot patch (python ic.py patch; checked in the
        # exe, left out otherwise). 0xA000009A holds the meteor event (script
        # template 0x1D00019C: rock with trail, warning, impact, mse_Meteor sounds).
        # [] = off. event_packs_unchecked = send them without checking the exe.
        "event_packs": [0xA000009A],
        # 2026-10-17 08:02 (tester tried six maps, every one hung at 15-25 %): the server sent
        # Tutorial 1's packs for every encounter, so both zone slots were taken and the map's
        # own zone pack could not load. Per encounter: its zone pack (category 0xd; found by
        # the names inside the 5 zone packs of the install) and a start position from its
        # mission layout. Encounters not listed use "packs" + "event_packs" and "spawn".
        # spawn = [region, landblock x, landblock y, cell, x, y, z].
        "maps": {
            # Tutorial 2: zone 0xA00002E5 ("tut_adv_*" pieces, Gaslight), mission 0xA00002E6
            # (lb 0x13C3; GaslightBatman of cinematic 0x3500002C at (25.32, 75.39))
            # 2026-10-17 09:31 (tester, fase3-hb): Tutorial 2 is the model lab ("lab": the tour of
            # [debug] lab_tour next to the start) with the meteor event's zone pack 0xA000009A in
            # the second zone slot (needs python ic.py patch). "lab": False = the plain map.
            "0x40000A81": {"packs": [0xA0000076, 0xA00002E5, 0xA00000CC],
                           "event_packs": [0xA000009A], "lab": True,
                           "spawn": [1, 0x13, 0xC3, 0, 25.32, 75.39, 200.23]},
            # Coast City (+ its v AI and Crisis Labs variants): zone 0xA00000D2 (env_coastcity),
            # mission 0xA0000162 (lb 0x23E3, Player01 of 0x35000013)
            "0x40000270": {"packs": [0xA0000076, 0xA00000D2, 0xA00000CC],
                           "spawn": [1, 0x23, 0xE3, 0, 20.19, 57.44, 250.2]},
            # 2026-10-18 00:13 (tester: start the champion select with Coast City v AI, 1 v 1, the AI
            # being Gaslight Batman): "lobby" = the champion select first (its twin 0x49000B6A has no
            # SkipsLobby 0x10000B0E): 0x204C says `teams` teams of `per_team`; the map loads when a
            # client event in `lock_events` arrives (the lock's id is not known yet: [] = only after
            # `wait` s; every client event in the lobby is in server.log)
            "0x40000B6A": {"packs": [0xA0000076, 0xA00000D2, 0xA00000CC],
                           "spawn": [1, 0x23, 0xE3, 0, 20.19, 57.44, 250.2],
                           # 00:25 (tester: no champion could be locked): "available" = the champions
                           # 0x204C allows ("all" = the roster); the client's 0x20E4 (variant | u8 lock)
                           # gets its slot back locked and the map loads lock_delay s later; wait 120 s
                           # (was 60) as the fallback
                           # 00:35 (tester: "I play the champion I choose, Gaslight Batman on the other side";
                           # the map is very dark): enter_after_lock = 0x20AF (the match's champions) goes
                           # after the lock with the locked champion (play_pick) and the bot's; bot = the AI's
                           # champion standing at the enemy start (mission 0xA0000162, cinematic 0x35000012
                           # Player01); lighting_env 0 = Coast City's own lighting (was Tutorial 1's
                           # 0x10000016)
                           "lighting_env": 0,
                           # 00:44 (tester: "level up in the HUD from level 6, every animation of the
                           # champion, a drone that can be attacked but is indestructible"): free play
                           # (icserver/freeplay.py): start_level / skill_points, Q W E R ranks with the '+'
                           # (max_ranks per slot 0-4; R at levels 6, 11, 16), a level every level_up_seconds
                           # (0 = off) up to max_level, a training drone (drone_class, drone_offset from the
                           # start, never destroyed) and a tour of the champion's graph events (tour_interval s,
                           # labels in the objective)
                           "free": {"start_level": 6, "skill_points": 6, "max_ranks": [0, 5, 5, 5, 3],
                                    "level_up_seconds": 60.0, "max_level": 20, "drone": True,
                                    "drone_class": 0x40000A5C, "drone_offset": [6.0, 0.0], "drone_health": 1000,
                                    "tour": True, "tour_start": 8.0, "tour_interval": 4.0},
                           "lobby": {"teams": 2, "per_team": 1, "lock_events": [], "wait": 120.0,
                                     "available": "all", "lock_ends": True, "lock_delay": 2.0,
                                     "enter_after_lock": True, "play_pick": True,
                                     "bot": {"champion": 0x40000086, "xyz": [137.47, 60.22, 250.19],
                                             "yaw": -1.222, "team": 2, "health": 600}}},
            "0x4000039C": {"packs": [0xA0000076, 0xA00000D2, 0xA00000CC],
                           "spawn": [1, 0x23, 0xE3, 0, 20.19, 57.44, 250.2]},
            # Gotham Divided: mission 0xA0000168 (lb 0x1BD3, Player01 of 0x35000014). Its zone is
            # one of the two Gotham zone packs: 0xA000009A (env_gotham, the meteor event) is
            # tried first; the other is 0xA00000FC.
            "0x40000399": {"packs": [0xA0000076, 0xA000009A, 0xA00000CC],
                           "spawn": [1, 0x1B, 0xD3, 0, 19.61, 137.09, 250.22]},
            # Gotham Heights / Metropolis Skyway: mission not identified yet; 0xA00000FC (no
            # names inside) with the start of mission 0xA000016B (lb 0x1BF3) as a first guess
            "0x4000013E": {"packs": [0xA0000076, 0xA00000FC, 0xA00000CC],
                           "spawn": [1, 0x1B, 0xF3, 0, 18.39, 50.08, 252.5]},
            "0x40000C28": {"packs": [0xA0000076, 0xA00000FC, 0xA00000CC],
                           "spawn": [1, 0x1B, 0xF3, 0, 18.39, 50.08, 252.5]},
        },
        "event_packs_unchecked": False,
        # Other champions the match must load: Gaslight Catwoman (variant 0x40000262)
        # for the cinematic where she breaks the vehicle (2026-10-13: dialogue but no model).
        "extra_champions": [0x40000262],
        "team": 1,
        "room_id": 1,
        # Spawn: region, landblock x, landblock y, cell, x, y, z
        "spawn": [1, 0x13, 0xCB, 0, 18.7, 60.4, 200.3],
        # Ground height of the tutorial street: clicked heights within 3 m are
        # snapped to it (the client's click height creeps up, 2026-10-14). 0 = off.
        "ground_z": 200.0,
        "cinematic": 0x35000026,        # 0 = no intro cinematic
        # Played before it, in order (each one after the previous ends). The
        # tutorial's other cinematics: 0x35000025 (power cores falling from the
        # sky: the meteor?), 0x35000033 (drone vs thugs), 0x35000034 (Catwoman).
        "pre_cinematics": [],
        # Event 0x2053 "match started": the client's game systems (dialog gate bit 4,
        # probably the Advancement scripts that answer the skill "+") start with it.
        # 2026-10-14: sent after the load, the client goes back to the loading
        # screen and connects to the lobby again (= the real match load).
        # false | "reload" (send it with the lobby data, create the objects on the
        # reload) | "lobby" | "in_world" | "after_intro" (these two hang).
        "send_match_start": False,
        # replaying in the same login: the client's own teardown already destroys
        # every object (2026-10-15 static analysis), so removing them (0x3) is off;
        # what the next match needs is 0xEB (set local player) again
        "remove_objects_on_leave": False,
        "resend_local_player": True,
        # 0x20AF + 0x2016(0) before the game welcome (the client's 60 s lobby
        # watchdog), and no room-id 0x2016 with the lobby data. 22:43: with
        # both, the FIRST load stalled at 55 %: back to the old order
        "enter_match_first": False,
        "lobby_room_check": True,
        # Movement speed property (0x100005E4) on the champion: the client derives
        # the walk-animation speed cap from it (0 = Batman slides). 0 = don't send.
        "anim_move_speed": 4.5,
        "lighting_env": 0x10000016,       # property 0x956 (lighting environment); 0 = not sent (test for the dark fog)
        # extra minimap icon on Batman (0 = none). 2026-10-14 19:39: the minimap
        # already draws the local player (yellow ring); 0x13000376 added a 2nd icon
        "champion_map_icon": 0,
        "health": [600, 600],
        "secondary": [100, 100],
    },
    "timing": {
        # Match objects are created once ALL of: the client is in the lobby,
        # at least objects_min_delay s have passed, and the client reported at
        # least objects_min_percent % loading. objects_max_wait is the fallback.
        "objects_min_delay": 4.0,
        "objects_min_percent": 15,      # the client waits for the objects at 15% (log 2026-10-13)
        "objects_max_wait": 10.0,
        "link_delay": 2.0,             # 2nd bundle: links player -> champion
        "cinematic_delay": 5.0,        # after the client's load-complete notice
        "tutorial_start_delay": 0.5,
        "idle_resend": 5.0,            # full object refresh while standing still (0 = off)
        "keepalive": 2.0,              # time packet on the game connection
        "move_hz": 60,
        "move_speed": 4.5,             # 6.0 looked too fast in game (2026-10-13)
        "ping_lifetime": 4.5,             # s a player ping stays (ground + minimap); original ~4-5 s
    },
    "tutorial": {
        # Spacing of the tutorial's dialogue and events, taken from the original's
        # chat log (seconds between lines). 1.0 = like the original, 0 = all at once.
        "pacing": 1.0,
        # Guide points (x, y, z in landblock 0x13,0xcb), in order. Empty = built-in.
        "targets": [[25.0, 60.3, 200.0], [30.5, 59.0, 200.0]],   # old flow (unused)
        "drone_step": 3,                                          # old flow (unused)
        # 2026-10-14 12:08 (as in the original): a marker where Batman must walk;
        # there the big meteor knocks him down; when he is up, the drone and the
        # human are fighting and a second marker points at them.
        "walk_targets": [[25.1, 60.3, 200.0]],     # 23:07: 1.5 m further on (was 23.6, 60.6)
        "drone_appear_delay": 6.0,     # 17:51: 6.0 (was 7.0); s after reaching marker 1 (x pacing): the next marker, 1 s after he is up
        # 2026-10-17 16:24 (original video, frame by frame): Batman fades in at 3:33.5, the first
        # prompt shows at 3:34 and he is walking at 3:36.4, just before the first fire column comes
        # down (3:36.7). Lock 2.8 s (was 3.5).
        "start_lock": 2.8,             # s Batman cannot move at the start (the 3 small meteors)
        # Seconds after the start at which each small meteor is created (its fall then takes
        # stp_meteor_impact s). Original: the fire columns hit 3.4-3.9 s after Batman appears.
        # [] = the old 1.0 / 1.7 / 2.4.
        "small_meteor_times": [2.4, 2.6, 2.9],
        # Original 3:37.4-3:38.4: one big grey dust dome right after the small meteors hit, covering
        # the street for about a second (before the big yellow blast at 3:38.9). One dust cloud
        # 0x2E0007D4 at their centre, small_meteor_cloud_delay s after the last impact (False = off).
        "small_meteor_cloud": True,
        "small_meteor_cloud_scale": 1.5,
        # 18:46 (tester): the dust came after the meteors landed: now from the first impact, -0.2 s
        "small_meteor_cloud_delay": -0.2,
        "small_meteor_cloud_seconds": 3.0,
        # Ground marker / guide arrows: three ways of playing the guide scripts,
        # one every guide_variant_gap seconds after each marker (see tutorial1.ping)
        "guide_variants": ["A", "B", "C"],
        "guide_variant_gap": 4.0,
        # Visible marker: a player ping (retreat class, green) on each guide target, since
        # the guide's own ground circle does not show yet (0 = off)
        # The street vehicle breaks in steps (Destructible_AdvanceState 0x10000063,
        # not accepted by the client yet). vehicle_break_at = seconds into the
        # Catwoman cinematic when she hits it: the vehicle is removed then.
        "vehicle_states": 2,
        "batarang_aim_radius": 1.5,       # m: the cursor must be this close to a drone (or on the throw line)
        "vehicle_break_keys": [0x10000063],
        "vehicle_break_at": 6.0,
        # 2026-10-17 17:08 (tester's video vs the original 5:03): the vehicle blows up when Catwoman
        # hits it (the big meteor's explosion 0x2E0004E7 where it stood); False = it only vanishes
        "vehicle_blast": True,
        # 17:43 (tester's video): at 1.2 with the shockwaves it filled the screen (shockwave, flying
        # rocks, a yellow cloud for 3 s); the original is a fireball about the vehicle's size, gone
        # in ~1 s. 0.45 (was 1.2), removed after vehicle_blast_seconds, no shockwaves.
        "vehicle_blast_scale": 0.45,
        # 17:51 (full video, 0.03 s frames 03:09.65-03:10.5): the fire lasts ~0.85 s: 1.0 (was 1.5)
        "vehicle_blast_seconds": 1.0,
        "vehicle_blast_shockwaves": False,
        # Original 5:08.7 (fire behind, upper right) and 5:11.8 (lower left, then a smoke wave):
        # [s into the Catwoman cinematic, dx, dy] from the vehicle. 17:43 (tester): nothing falls
        # there, the ground blows up and a crater opens: the big meteor's crater + explosion
        # (scale catwoman_blast_scale), no falling rock (was a small falling meteor).
        "catwoman_meteors": [[11.5, 8.0, -6.0], [14.6, -6.0, 1.0]],
        "catwoman_blast_scale": 0.7,
        # 21:40 (tester): the two craters these left (by the gate, where the vehicle stood) must not be
        # there: the blast only (False; True = the crater too)
        "catwoman_blast_crater": False,
        # 2026-10-14 15:52 (diag --scripts): the vehicle's scriptlet table is EMPTY
        # ("0 grupos"), so Destructible_AdvanceState never runs and it stays whole:
        # it is removed after the cinematic again until the destruction works.
        "vehicle_keep_wreck": False,
        "fog_of_war": True,               # hide units out of Batman's sight (radius / walls) with 0x90F
        "vision_radius": 14.0,
        "meteor_objects": True,           # meteor rocks as objects (False = only Batman's knockdown)
        # 2026-10-16 17:29 (tester): the 3 meteors at the start must be bigger,
        # block the way and go away after a while: they fall from the sky as
        # entities and are obstacles once down ("entity"; "prop" = the old
        # static rocks)
        # 17:59 (tester): the game's own meteor effect, with its dust and sound
        # ("effect"; see tutorial1._meteor_effect), then the rock that stays
        # 18:11 (tester): the effect object showed nothing (no sound, no dust) and
        # the rocks popped up: back to the falling rock, plus dust and the effect
        # as the rock's property (below)
        "meteor_mode": "entity",
        # 2026-10-16 19:20 (tester: "si intentalo"): when the match loads the meteor
        # event's pack ([match] event_packs, needs python ic.py patch) the meteors
        # are the game's own event (template 0x1D00019C, key 0x1000092F) instead
        # of the server-made rocks above. False = the old rocks even then.
        # 20:58 (tester's picture): the glowing lava rock (0x2E0005F7 / 0x2E000BB3, .entity
        # 0x2D00048D) is the meteor, but far too big, and the event's pieces do not
        # animate (the rock accepts no scriptlet: 0 groups). Back to the falling rock
        # entities, now with that model and smaller (below). True = the probes again.
        "meteor_event": False,            # the 3 small ones at the start
        "big_meteor_event": False,        # the big one at the first marker
        "meteor_event_table": 0x1D00019C,
        # 20:08 (tester: "water jets" instead of meteors; diag: 0x1000092F rejected,
        # the table allows only 0x5): key 0x5, anchor = the event's ground warning
        # 0x2E0004E5 (0x2E000013 is a water jet). 0x1000092F was the first try.
        # 20:33 (tester: "the same"): the 3 small meteors are now 3 different probes
        # (tutorial1.METEOR_EVENT_PROBES: event object 0x2E0006DA / warning + rock
        # 0x2E0005F7 / rock 0x2E000BB3 + dust); [] = the anchor below for all
        "meteor_event_probes": None,
        "big_meteor_event_probe": True,   # big one: warning + rock 0x2E0005F7 + dust (False = the anchor)
        "meteor_event_keys": [0x5],
        "meteor_event_anchor": 0x2E0004E5,
        "meteor_event_carrier_slot": 0,
        "meteor_event_scale": 1.0,
        "big_meteor_event_scale": 1.0,
        "meteor_event_delay": 0.1,        # s from the anchor's creation to its scriptlet
        "meteor_event_impact": 2.0,       # s until it hits (block / crater + knockdown); a guess
        "meteor_event_block_half": 0.6,   # m: the obstacle box where a small one fell (0 = none)
        "meteor_event_seconds": 0.0,      # anchor removed after this (0 = small: with its block; big: stays)
        "meteor_effect_wstate": 0x2E0002EC,  # 0x2E000013 + effect 0x1EB = 0x170001C4
        "meteor_effect_property": 0x1EB,     # also sent explicitly (0 = not)
        "meteor_effect_script": 0x170001C4,
        "meteor_effect_seconds": 6.0,        # then the effect object is removed
        "meteor_effect_land": 1.0,           # s until the staying rock appears on the ground
        "meteor_effect_rock": True,
        # 18:54 (tester's video): the small ones are burning pieces
        # (env_event_meteor_fragment); the big one at the first marker is the rock
        # 20:58: the lava rock for the small ones too (pack 0xA000024C), scaled down
        "small_meteor_wstate": 0x2E000BB3,
        "big_meteor_wstate": 0x2E000BB3,
        "meteor_scale": 0.35,             # 20:58: 1.0 was as big as the big one (2x Batman)
        "meteor_push_steps": 5,           # the push: small position updates...
        "meteor_push_seconds": 0.3,       # ...over this long
        "meteor_fall_height": 18.0,       # m above the ground they start from
        # 19:11 (tester): "no meteor falls, the crater just appears": a slanted
        # flight, longer, so it is seen from the top-down camera
        # 21:24 (tester): still no fall seen: slower, with more updates
        "meteor_fall_steps": 18,
        "meteor_fall_seconds": 1.6,
        "meteor_fall_from": [-6.0, 4.0],      # start offset (m) from the landing spot
        "big_meteor_fall_steps": 22,
        # 2026-10-17 16:24: 1.0 (was 2.0): the crater, blast and knockdown when the falling stp_meteor
        # lands (big_stp_meteor_impact 1.0), not a second after it
        "big_meteor_fall_seconds": 1.0,
        "big_meteor_fall_from": [-14.0, 10.0],
        "big_meteor_fall_height": 22.0,
        # 18:11 (tester): the blocking square was bigger than the rock, and
        # touching a rock should push it away: no fixed square (0), pushed instead
        # 19:11 (tester): the pieces had no collision: a small square stops Batman
        # at the rock, and touching it pushes it
        # 21:24 (tester): the collision area was much bigger than the rock (the push
        # started 1.1 m from its centre, before Batman touched it): a 0.6 m square,
        # pushed only when he is 0.6 m from its centre
        "meteor_block_half": 0.3,         # > 0 = the meteors block (size: meteor_block_radius)
        # 21:34 (tester): Batman still walked round them far away (the box was grown
        # by his 0.6 m radius): an octagon his centre stops at, this far from the rock
        # 21:47 (tester): at 0.45 Batman walked over the rocks: 0.7 (the rock at scale
        # 0.35 is about 0.5 m across its middle, plus his body)
        # 21:59 (tester): still no collision at 0.7 (pushes were sent, 21:58:08):
        # 0.95 (the rock is about 1.2 m across at scale 0.35, plus his body)
        "meteor_block_radius": 0.95,
        "meteor_push": True,
        "meteor_push_radius": 1.15,       # m from the rock's centre at which Batman pushes it (> meteor_block_radius)
        "meteor_push_extra": 1.2,         # m it slides beyond that (never into a wall); 23:30: was 0.6, longer rolls, fewer
        "meteor_push_speed": 4.0,
        "meteor_push_tick": 0.15,
        # 18:36 (tester): that dust is the big meteor's, not the small ones'
        # 22:11 (tester's video): the small ones have no dust ring, only smoke as they
        # fall (meteor_smoke below)
        "meteor_dust": False,
        # 2026-10-17 19:09 (tester): no meteor falling behind and no rock left in the crater: only the
        # blast and the crater (as the original's 01:30.0). False (was True): crater() + knockdown.
        "big_meteor_falls": False,
        "big_meteor_dust": True,          # ...with the dust cloud
        "big_meteor_dust_scale": 1.0,
        "big_meteor_rock_seconds": 0.6,   # the big rock goes this long after hitting (the crater stays)
        "meteor_dust_scale": 0.5,
        "meteor_dust_seconds": 3.0,
        # 18:36: as the rock's property 0x1EB the effect made no sound: off
        "meteor_land_effect": 0,          # effect set as the rock's property 0x1EB on landing (0x170001C4 = the test)
        "meteor_lifetime_small": 20.0,    # s on the ground before they go (the next marker also removes them)
        "big_meteor_scale": 0.7,          # 20:58: 1.0 (the picture) is too big
        "meteor_scale_property": 0x6B4,   # object scale (render component; may be a list)
        "big_meteor_crater": True,        # the big meteor: a crater instead of a rock
        "crater_mode": "wstate",          # wstate = 0x2E0004BE placed like the rocks | entity = 0x400004FD
        "crater_wstate": 0x2E0004BE,
        # 2026-10-17 10:37 (tester, lab fase3-hd "Model 11/16 key 1/9 0x100003A9"): the crater is
        # 0x2E0004BE on a carrier (slot 0) with its templates and key 0x100003A9 (crater_keys),
        # turned 5 degrees clockwise (crater_yaw, radians; was 0.0; if it turns the wrong way use
        # +0.0873). Was slot 1 (its entity 0x400004FD) with keys tutorial1.CRATER_KEYS.
        "crater_carrier_slot": 0,            # 1 = the crater's own entity 0x400004FD; 0 = a carrier with its templates
        "crater_keys": [0x100003A9],
        "crater_scale": 1.0,
        "crater_yaw": -0.0873,
        "crater_blast": True,             # run the start scripts (VFX) on the crater
        "big_meteor_rock": False,         # also drop a rock there
        "meteor_wstate": 0x2E000BB3,      # the rock (env_event_meteor_a); 0x2E0007D4 = its dust cloud
        "ping_team": -1,                  # PVP_Team on markers/pings (-1 = champion's; 0 also showed red)
        "ping_style": "team",             # minimal | team | full: properties on pings (team = class icon + team colour)
        # PVP_Team per ping class: the colour is the relation to Batman's team
        # (same = blue, 0 = neutral, other = red). Alt 0x4000025B red, Ctrl 0x4000025A neutral
        "ping_class_teams": {"0x4000025B": 2, "0x4000025A": 0},
        # minimap notes: an invisible companion on each ping / marker carries the
        # minimap icon (enemy-team objects never get one)
        "skip_markers": False,            # walking near the drone skips the markers left (off: in order)
        "marker_note_seconds": 5.0,       # s the tutorial marker shows on the minimap (ground marker stays)
        "map_notes": "self",              # self | companion | off: who carries the minimap note
        "map_note_team": 0,
        "map_note_icon": 0,               # extra minimap icon for pings (0x13000A15 = yellow cone; 0 = none)
        "map_note_category": 0x1D,        # 0x1D = player-ping notes (the client special-cases it); 1 drew 2 icons
        "map_note_variants": {"0x4000025B": 0, "0x4000025A": 1},   # icon variant per ping (guess)
        "marker_ping_class": 0x4000025A,   # the green one (2026-10-14 14:26)
        "marker_radius": 1.5,             # m: where Batman STOPS counts as on the marker
        "marker_pass_radius": 0.6,        # m: walking through counts only this close
        # ground ring candidates (property 0x8E = [0x3400053C, 0x34000600]): the
        # client CRASHED when the marker carried them (2026-10-14 15:11), so off
        "marker_vfx": [],
        "marker_category": 0x1D,          # minimap note category of the tutorial marker (as the pings)
        # second marker: on the ground next to the drone and the human ([] = at the drone)
        "drone_marker": [36.9, 57.6, 200.0],
        # 2026-10-17 16:24 (original video): the big blast comes about 0.5 s after Batman reaches the
        # marker (3:38.4 -> 3:38.9); here it came 3 s later (1.0 + big_meteor_fall_seconds 2.0). Was 1.0.
        "knockdown_delay": 0.4,         # s from marker 1 to the big blast (19:09: the blast itself, no fall; was 0.3)
        # ...but never sooner than this after the last small meteor has hit (16:24, original video)
        "big_meteor_after_small": 0.8,
        # 2026-10-17 17:51 (tester's full video, 0.5 s frames): after the big blast (01:30.0) Batman
        # lies ~3.5 s and is up at 01:34.8 (was 5 s on the ground); the next marker comes right
        # then (drone_appear_delay 6.0, was 7.0; knockdown_lock 6.6, was 7.5)
        "knockdown_hold": 3.8,
        # Flaming rocks falling near Batman as set dressing ({hook: [[delay, dx, dy], ...]}, from
        # Batman, x = screen right, y = screen down; hooks "practice" and bridge stages), from the
        # video: 02:41 / 02:43 by the practice targets, 03:37 / 03:38 / 03:44 after the pursuers,
        # 05:38 at the Bat Flight target. {} = off.
        "ambient_meteors": {"practice": [[0.0, -9.0, 0.0], [1.9, 0.0, -6.0]],
                            "unlock_w": [[1.6, -8.0, -8.0], [2.6, -5.4, 0.0], [8.6, -2.0, -1.0]],
                            "e_practice": [[1.0, -2.0, 0.0]]},
        "ambient_meteor_lifetime": 4.0,
        # 20:08 (tester): he slid lying down when moved before getting up: locked
        # from the fall itself for knockdown_hold + this (-1 = only knockdown_lock)
        "knockdown_getup_seconds": 1.5,
        "knockdown_lock": 6.6,         # s from marker 1 until he can move: 1.3 + 3.8 down + 1.5 (17:51; was 7.5)
        # The patched exe (`ic.py patch`) sends the skill "+" to the server (a lone
        # rank query for Q; the HUD's refresh bursts are ignored). As a fallback
        # (old exe) the server unlocks the first skill itself this many seconds
        # after asking (0 = off).
        "auto_rank_seconds": 60,
        # Hide the "+" buttons after that unlock. Off: in game (2026-10-13) the
        # whole skill HUD disappeared with them.
        "hide_upgrade_buttons": False,
        # Falling meteors (PowerCore objects) at the start, when reaching the
        # first marker (Batman knocked down) and after the first drone.
        "meteors": True,
        # Cinematic after the practice drones: Catwoman breaks the vehicle (0 = off).
        "catwoman_cinematic": 0x35000034,
        # Drones that Batman attacks (the wave also when he comes close) walk up
        # to him, hit him and take health (6 per hit, never below 1).
        "drones_fight_back": True,
        # The wave and practice drones "teleport in": [seconds after appearing,
        # script] pairs. Vfx_Spawn, then Vfx_Fade_In twice. [] = off.
        "spawn_sequence": [[0.1, 0x10000032], [0.9, 0x10000033], [1.6, 0x10000033]],
        # 21:59 (tester): no electricity over Batman's suit antennas. Started on him
        # at the tutorial start and after he gets up: SpawnIdle, FX_Spawn ([] = off)
        # 22:22 (tester): accepted (diag) but no electricity: + Vfx_Bmg_Spawn 0x10000181
        # 2026-10-17 00:58 (tester): the rope still showed: it comes from these spawn
        # scriptlets (SpawnIdle / FX_Spawn / Vfx_Bmg_Spawn = Gaslight Batman's grapple
        # spawn). Off.
        # 2026-10-17 18:05 (tester: the electricity on the suit's antennas is still missing): in the
        # scriptlet name table 0x33000000, 0x10000180 is Vfx_Bmg_Active (Gaslight Batman's own
        # "active" effect; his rig has LGun / RGun AntennaA / B bones) and 0x10000183 is
        # Vfx_Bmg_Sonic_Shell_Stop (SpawnIdle is its name in the graph-event table). Vfx_Bmg_Active
        # at the start and after he gets up (was [])
        # 18:25 (tester): nothing showed. 0x10000180 and 0x1000005A are not in Batman's own
        # scriptlet table (data/batman_actions.tsv): the client drops them. Back to [] and the
        # candidates that are in it go through champion_fx_tour.
        "champion_ambient_keys": [],
        # Spawn effect at the start (FX_Spawn / FX_Spawn_End); 18:25: off ([] = off), see the tour
        "champion_spawn_keys": [],
        "champion_spawn_end_keys": [],
        "champion_spawn_seconds": 2.5,
        # 18:25: candidates in Batman's own table, one by one after the start, each labelled in the
        # objective text: [s after the start, key, label]
        # 18:46 (tester): none of Respawn / Echoes / Active State showed anything. The client's own
        # list of what Batman accepts (diag.log 17:06 "allowed scriptlets", named from 0x33000000)
        # has Cinematic_Intro, Vfx_Fade_In, Vfx_Active and the "controlled by player" hooks:
        # 19:09 (tester): test 1 (Cinematic_Intro) put the rope on Batman; 2-5 showed nothing. Next,
        # from the same accepted list: the silver hex shimmer may be an invulnerability shield
        # (Vfx_Stp_Invulnerability_Start / Active, then _Stop = the ring at his feet?) and the
        # antennas' arcs the Supercharge status (his graph has CbtState_SuperCharged; not stopped),
        # then the item protection shield. [s, key or [keys], label]
        # 19:18 (tester): the search moves to the Tutorial 2 champion tour ([debug] lab_tour "batman");
        # off here (was Invulnerability / Supercharge / Protection Shield)
        "champion_fx_tour": [],
        "champion_fx_label_seconds": 4.0,
        # 22:11 (tester): the rocks never moved on screen (a carrier prop ignores the
        # server's later position updates): they appear on the ground after a puff
        # of smoke (the dust cloud's other scriptlet), and a pushed rock is created
        # again where it slid to. meteor_appear False / meteor_push_mode "slide" =
        # the old fall / slide.
        "meteor_appear": True,
        "meteor_appear_delay": 0.5,       # s from the smoke to the rock (small ones)
        # 22:36 (tester): every dust-cloud scriptlet is a dust WAVE; only the big crater
        # makes one (big_meteor_dust at its impact). No smoke column asset found yet.
        "meteor_smoke": False,
        # 22:22 (tester): no smoke seen with 0x10000347 (accepted); 0x1000018E is the
        # dust ring wave: the dust cloud's third scriptlet 0x10000076 now
        "meteor_smoke_keys": [0x10000076],
        "meteor_smoke_scale": 0.6,
        "big_meteor_smoke": False,
        "big_meteor_smoke_keys": [0x10000076],
        "big_meteor_smoke_scale": 1.0,
        "meteor_smoke_seconds": 3.0,
        # 2026-10-16 22:47 (tester: "they disappear and appear a bit further on"):
        # "glide" = re-created once moving away from Batman at meteor_glide_speed
        # m/s (the client moves it) and once more, standing, where it got to.
        # "recreate" = the fase3-gr steps; "slide" = the old position updates.
        # 23:30 (tester: still vanishing and reappearing): "drift" = moving updates
        # along the push (no re-creation), the last one at meteor_stop_speed m/s
        # (a carrier prop ignores speed-0 updates)
        "meteor_push_mode": "drift",
        "meteor_glide_speed": 2.5,
        "meteor_stop_speed": 0.01,
        # 22:36 (tester): pushed rocks should roll, not jump: re-created in steps,
        # turning meteor_roll_turn degrees each time
        "meteor_roll_steps": 4,
        "meteor_roll_seconds": 0.4,
        "meteor_roll_turn": 35.0,
        "champion_ambient_delay": 1.0,
        # 22:47 (tester's frames: Batman beams in with a blue electric glow before his
        # health bar shows): graph event RunScript_FX_Spawn raised at the start ([] = off)
        # 23:45 (tester): the rope it plays (grapple) must not show: off
        # 2026-10-17 20:41 (tester, champion tour "G 2/2 Spawn"): when the graph event Spawn 0x10000154
        # ends, the antennas' electricity comes on. Raised on Batman at the tutorial start (was []); it is
        # the graph event Cinematic_Intro raises (the "rope" of 19:09 came with Cinematic_Intro).
        # 23:02 (tester: nothing may sound, not even on the loading screen; Batman must start the tutorial with
        # the antennas lit, as in the videos): Spawn plays his respawn clip with its voice line, so it is not used.
        # The graph events at the END of his spawn are raised instead at the tutorial start: RunScript_FX_Spawn_End
        # 0x10000031 and RunScript_Vfx_Active 0x100001AE (the graph's own route to the end-of-spawn effects; the
        # scriptlets FX_Spawn_End / Vfx_Bmg_Active are not in his table). Was [0x10000154].
        # 23:09 (tester): they lit nothing: off (was [0x10000031, 0x100001AE]); champion_start_keys instead
        "champion_spawn_events": [],
        # 23:09: scriptlets run on Batman once at the tutorial start (champion_spawn_delay s after it):
        # Cinematic_Hidden 0x100009EB = action type 0x737 with graph event SpawnIdle (the state after Spawn,
        # when the antennas lit at 20:41), without Spawn's respawn clip and voice line. [] = off.
        # 23:19 (tester): Batman vanished until he lifted the car: off (was [0x100009EB])
        "champion_start_keys": [],
        # 20:46 (tester: in the original he is standing with the antennas lit when we get control): the
        # Spawn animation plays right after the intro cinematic and the tutorial starts this long after
        # it (the original: shimmer from 01:20, ring 01:25.3, HUD 01:25). 0 = Spawn with the start.
        # 21:53 (tester: "Batman stands still too long before he can move; play that movement with the
        # scene load"): 0 (was 5.0); the spawn now plays during loading (champion_intro_keys)
        "champion_spawn_hold": 0.0,
        # 21:53: scriptlets run on Batman champion_intro_delay s after the client's load-complete notice
        # (during the intro cinematic): Cinematic_Intro 0x100009EC = 0x737 = 2 + graph event Spawn +
        # Vfx_Bmg_Spawn 0x10000181 (the champion tour: it lit the antennas). [] = off.
        # 22:40 (tester: a Batman voice line plays as the match starts; it must not): Cinematic_Intro is
        # split into its parts without the cinematic action 0x737 = 2: the scriptlet Vfx_Bmg_Spawn
        # 0x10000181 (was [0x100009EC]) and the graph event Spawn (champion_intro_events)
        # 22:51 (tester: with fase3-io's Cinematic_Intro the antennas were lit; with fase3-ip's parts they are
        # not): back to Cinematic_Intro (its record: the graph event Spawn through its own action type 0x737,
        # not the HFSM raise-event scriptlet, + Vfx_Bmg_Spawn). It is sent earlier, champion_intro_at =
        # "link" (when the player is linked to Batman, the client still at its loading screen) instead of
        # "load" (0.5 s after load complete), so its voice line comes during the loading screen.
        # 23:29 (tester, Tutorial 2 tour: only Cinematic_Intro lit the antennas): on again (was []), now run in
        # the game as the tutorial starts (champion_intro_at "start", was "link": the loading screen, where its
        # voice line was heard); Batman stands still champion_intro_lock s meanwhile
        # 23:46 (tester: skipping the intro cinematic shows the spawn's rope anyway; leave Batman without the
        # electricity while he looks for the effect that turns it on): off (was [0x100009EC])
        "champion_intro_keys": [],
        "champion_intro_events": [],
        # 23:38 (tester's video 23:37: with "start" the antennas light, but the spawn's yellow line from the sky
        # down to him (the "rope") shows as the camera reaches him): "cinematic" = champion_intro_delay s after
        # the intro cinematic 0x35000026 is sent (it lasts ~4.7 s; the spawn ~1.5 s), out of the player's view
        "champion_intro_at": "cinematic",
        "champion_intro_lock": 2.8,
        "champion_intro_delay": 1.5,         # 23:38: 1.5 s into the intro cinematic (was 0.5 after the link)
        "champion_spawn_delay": 0.3,         # 23:02: after the refresh that follows the intro (was 0.0)
        # 22:47 (tester's frames: a column of fire, then smoke, then the rock lies
        # there): the rock's own key from the meteor event (Vfx_Spawn), run when it is
        # created; the rock now has its scriptlet table 0x1D0003B5. The rock is made
        # meteor_key_lead s earlier than before so its animation can play ([] = the
        # old probe keys, no lead).
        # 23:30 (diag): 0x10000032 is accepted by the rock and shows nothing: off
        "meteor_land_keys": [],
        "meteor_key_lead": 0.5,
        "big_meteor_key_lead": 1.0,
        # 22:47 (tester: "the crater should have its own model"): "event" = the meteor
        # event's crater 0x2E0004E7 (key 0x10000039) + shockwaves 0x2E0004ED (5 s) and
        # 0x2E0006DE (1 s), when pack 0xA000009A is loaded; "old" = 0x2E0004BE;
        # "lava" = the bank's lava set. The offset puts it where the old crater's mesh
        # showed (that mesh sat ~(3.2, 0.3) m off its origin).
        # 23:30 (tester): with "event" no crater showed and 0x2E0004E7 stayed as a
        # never-ending explosion: it is the explosion, not the crater. Back to "old".
        "crater_set": "old",
        # 23:30: the event's explosion 0x2E0004E7 (fire and smoke) at the big impact, removed
        # after big_meteor_explosion_seconds; smaller as each small meteor's fire column
        # (meteor_fire, meteor_fire_scale, meteor_fire_seconds). Needs pack 0xA000009A.
        "big_meteor_explosion": True,
        "big_meteor_explosion_scale": 1.0,
        # 2026-10-17 17:08 (tester's video): the yellow cloud covered the street ~4.5 s; in the original
        # the blast and its dust ring are gone ~2 s later (3:38.9 -> 3:41). 2.5 (was 4.0)
        "big_meteor_explosion_seconds": 2.5,
        "meteor_fire": True,
        "meteor_fire_scale": 0.35,
        "meteor_fire_seconds": 2.0,
        "event_crater_wstate": 0x2E0004E7,
        # 10:37 (tester, lab "Model 2/16 key 0x10000526"): the big explosion's key (was [];
        # 0x10000039 was rejected, diag 23:27). The small meteors' fire: meteor_fire_keys.
        "event_crater_keys": [0x10000526],
        "meteor_fire_keys": [],
        # 10:37 (tester, lab "Model 8/16b"): the sparks 0x2E0006DA (templates + these keys) at the
        # big impact; meteor_sparks = also at each small meteor (smaller)
        # 10:53 (tester, lab fase3-he "Model 1/6"): the meteors fall as the Stolen Power Meteor Drop's
        # rock stp_meteor 0x2E000928 with its graph; the rest of the impact follows after
        # stp_meteor_impact s (big: big_stp_meteor_impact); it goes after stp_meteor_seconds.
        # stp_meteor = false: as before (smoke and the rock at once)
        "stp_meteor": True,
        "stp_meteor_wstate": 0x2E000928,
        "stp_meteor_scale": 1.0,
        "big_stp_meteor_scale": 1.5,
        "stp_meteor_impact": 1.0,
        "big_stp_meteor_impact": 1.0,
        "stp_meteor_seconds": 3.0,
        "big_meteor_sparks": True,
        "meteor_sparks": False,
        "sparks_wstate": 0x2E0006DA,
        "sparks_keys": [0x1000018E, 0x10000032, 0x10000078],
        "sparks_seconds": 4.0,
        "sparks_scale": 1.0,
        "meteor_sparks_scale": 0.5,
        # 10:37 (tester, lab "Model 14/16"): the Destroyer's crater ring env_pvp_phase_pod
        # 0x2E001157, placed where the sphere lands (0 = off); destroyer_ring_scripts = with its
        # templates (the lab showed it right without)
        # 13:28: 0 = no separate ring: the phase pod (sphere_wstate) is that ring once open (was 0x2E001157)
        # 15:02: the phase pod is the ring again (sphere_wstate is the closed sphere now); was 0
        "destroyer_ring_wstate": 0x2E001157,
        "destroyer_ring_scale": 1.0,
        # 12:32 (tester): turned 90 degrees counter-clockwise (radians; was 0)
        "destroyer_ring_yaw": 1.5708,
        # 11:36 (tester): the ring is centred on the Destroyer (was the sphere's spot (152.5, 28.0));
        # destroyer_ring_offset moves it from there (m)
        "destroyer_ring_at": "destroyer",
        "destroyer_ring_offset": [0.0, 0.0],
        "destroyer_ring_scripts": False,
        # 2026-10-17 18:46 (tester): the big blast was ahead of the crater; it must start in the middle
        # of it (was [3.2, 0.3]), and the crater comes crater_delay s after it so it does not pop up
        "event_crater_offset": [0.0, 0.0],
        "crater_delay": 0.3,
        "event_crater_scale": 1.0,
        "event_crater_carrier_slot": 0,
        "event_crater_shockwaves": [[0x2E0004ED, 5.0, 1.0], [0x2E0006DE, 1.0, 1.0]],
        # Attack scripts the drones use, one swing per hit, in turn; each entry is
        # one key or a list of keys run together. The log names them ("attack
        # scripts 0x...+0x..."): keep the one whose swing shows. [] = built-in
        # (Robot_Minion_Melee_Attack / Combat_Basic_Attack + Vfx_Min_Basic_Melee).
        "drone_attack_keys": [],
        # Drone walk: speed (m/s) and seconds between steps.
        "drone_walk_speed": 1.6,
        "drone_tick": 0.25,
        # Seconds from the last practice drone to the Catwoman cinematic (its own
        # first line is "It appears the path forward is blocked.").
        # 0 = after Superman's last line (~18 s).
        "catwoman_delay": 0,
        # At level 2 restore also the W/E/R/passive upgrade buttons (false: only
        # Q shows the rank-up animation, as in the original).
        "restore_other_upgrades": False,
        # Practice target drones: {name = [x, y, z]} to move them. {} = built-in.
        "practice_positions": {},
        # The yellow target drones only take the Sonic Batarang (Q), not basic attacks.
        "practice_immune": True,
        # Only Q can be ranked in the tutorial: hide the W/E/R/passive "+" buttons
        # while the Q one is highlighted. Off: hiding them makes the whole skill
        # HUD disappear (2026-10-13 and 2026-10-14).
        "lock_other_skills": False,
        # Sonic Batarang: damage per drone it reaches (it ricochets to 2 more within
        # 8 m) and Batman's scripts for the throw ([] = built-in: 0x10000164
        # Batman_Gaslight_Sonic_Batarang + 0x10000171 Vfx_Bmg_Batarang).
        "batarang_damage": 200,
        "batarang_keys": [],
        # Before it, put Batman where the cinematic's own Batman stands, so the
        # two copies overlap instead of showing two Batmen (false = off).
        "cinematic_place_champion": True,
        # ...and hide him during it (property 0x90F, the flag the client's
        # cinematic player uses to hide entities); shown again at the end.
        "cinematic_hide_champion": True,
        # ---- part 2: the bridge (icserver/bridge.py) ------------------------------
        # Skip part 1 and start at a later point, for testing: "" (play it all),
        # "bridge" (Catwoman's pursuers), "camera", "gate_fight", "unlock_e",
        # "e_practice", "vehicle", "scream", "strength", "destroyer".
        "start_at": "",
        # Move any spot of the bridge: { name = [x, y], ... }. Names: pursuer1,
        # pursuer2, w_target, marker1, ambush_melee1, ambush_melee2, ambush_ranged,
        # camera, gate_drones (marker), gate_melee1/2, gate_ranged1/2, e_target,
        # more_melee1/2, more_ranged1/2, vehicle, vehicle_melee1/2,
        # vehicle_ranged1/2, scream1/2/3, and the gates 03GateA, 03GateMid,
        # 03GateB. An Alt+click logs its x, y.
        "bridge_positions": {},
        # The three blue gates block the way while closed.
        "gates_block": True,
        # The middle gate closes again when Batman is this far along the bridge
        # (metres from the first gate; the last gate is at 40.4).
        "gate2_close_at": 27.0,
        # The last gate closes again behind him, this far past it.
        "gate3_reclose": True,
        "gate3_close_after": 6.0,
        # The drones hitting a gate / the vehicle turn on Batman when one of them
        # is attacked; > 0 = also when he comes this close (m).
        "gate_drones_notice": 0.0,
        "vehicle_drones_notice": 0.0,
        # The team given to the gates' light walls ("player" = Batman's, -1 = none):
        # a test, they showed white instead of blue.
        "gate_team": "player",
        "bridge_marker_radius": 2.0,
        # Health of the yellow target drones of W and E (one hit of the skill).
        "bridge_target_health": 100,
        # The D button (surveillance camera): if the client sends no D order, the
        # camera is placed by itself this many seconds after the prompt (0 = never).
        # An Alt / Ctrl + click on the marked spot also places it.
        "camera_auto_seconds": 25.0,
        "camera_spot_radius": 3.5,
        # 2026-10-17 15:26 (tester's video: cameras off the map, in the water, inside vehicles): a D
        # click is moved to the nearest spot outside every obstacle and in Batman's line of sight
        "camera_on_walkable": True,
        # 15:26 (tester's video: the thrown car shot off in a straight line until it hit something):
        # it faces the throw and its last flight update is a crawl (a carrier ignores speed 0)
        "throw_face_target": True,
        "throw_end_speed": 0.01,
        # 15:44 (tester's video: still straight): a carrier keeps its creation height, so the arc is
        # drawn with a copy of the car at each point ("respawn"; "move" = moving updates, flat)
        # 15:57 (tester's video): the copies never showed (each lived 30 ms; a new object fades in
        # longer than that), so the car vanished in flight: back to "move" (was "respawn")
        "throw_mode": "move",
        # The surveillance cameras see this far (fog of war).
        "camera_vision_radius": 10.0,
        # The Bat Scream part: how long to wait for the client's "camera unlocked"
        # / "camera locked" (User.CameraLocked) before going on (s), and the
        # tutorial's R cooldown ([combat] cooldowns overrides it).
        "camera_unlock_wait": 10.0,
        # The Stolen Powers on D / F: "auto" = send each slot's skill definition
        # (needs logs\props.txt from tools\diag.py --props; nothing is sent
        # without it), false = never (place the camera with an Alt+click, lift
        # cars with an Alt+click or by walking into them).
        "stolen_power_property": "auto",
        # W and E aimed at the ground: the drone within this many metres of the
        # cursor is the target.
        "skill_aim_radius": 3.0,
        # Part 3 (icserver/finale.py): Super Strength and the Destroyer.
        # finale_positions = { name = [x, y] }: strength_melee1/2, strength_ranged,
        # car_b, car_b_melee, car_b_ranged, ahead_melee, ahead_ranged, destroyer.
        "finale_positions": {},
        "destroyer_cinematic": 0x35000028,   # the sphere falls and the Destroyer comes out
        "ending_cinematic": 0x35000025,      # "You did it, Protector!", the last gate opens
        "cinematic_timeout": 60.0,           # go on if the client never reports the end
        "lift_range": 4.5,                   # F / Alt+click lifts the car from this close
        "lift_on_touch": 3.0,                # walking this close to the car lifts it (0 = no)
        # Super Strength on Batman: SuperStrength_InitObjectPickup (bends down,
        # grabs), lift_step s later SuperStrength_PickupObject (lifts; then the
        # hands-up carry walk on its own); the car goes up lift_attach s after
        # that, to carry_height m. Nothing is sent to Batman while he carries.
        "lift_keys": [0x100007A2, 0x100007A1],
        "lift_step": 0.5,
        # graph events raised on Batman with the last lift key, through
        # _HFSM_BehaviorRaiseEventAction (0x100001E3, variable 0x780): CarPickup
        # takes him from the crouch to the lift and the hands-up hold
        "lift_events": [0x10000246],
        "raise_event_kind": 8,               # kind of variable 0x780 (8 enum; 0x0A the other enum kind)
        "throw_end_events": [],              # e.g. [0x100000BB] state_to_locomotion after the throw
        "lift_attach": 0.1,
        "carry_height": 2.1,                 # 12:18: 2.7 left a gap above his hands
        "carry_keys": [],
        "throw_keys": [0x100007A0],
        # 2026-10-17 21:28 (tester's pictures of the original): while the car is overhead the yellow range
        # ring around Batman and the ring at the cursor show, and a left click throws. The server presses
        # the aim key (F, virtual key 0x46) in the game window this long after the throw skill is on F
        # (0 = off: the player presses F).
        # 22:40 (tester: still no ring; log: the server's F reached the game, which threw the car at the
        # cursor at once: the client smart-casts F, User.SkillSmartcastOption): off (was 0.4)
        "throw_auto_aim": 0.0,
        "throw_aim_key": 0x46,
        "throw_windup": 0.2,                 # the car leaves his hands 0.20 s into the throw
        "throw_seconds": 0.9,                # then _Combat_GoToLocomotion (normal walking)
        "throw_range": 14.0,
        "throw_min_distance": 5.0,           # 22:51: a target closer than this is pushed out to it (0 = off)
        "blast_radius": 4.5,
        "destroyer_health": 3000,
        "destroyer_hit_range": 7.0,          # Batman's basic attack reaches the Destroyer from here
        "car_b_wstate": 0x2E00034D,          # the second car: 02PaddyWagonA (0x2E000AAB = the street's police wagon)
        "car_b_box": [7.5, 1.6],             # car B blocks the street: [half length, half width] across it
        # scenery near car B Batman walks through: ["Name", [[x, y], ...]] or
        # ["Name", x, y, half_length, half_width, yaw]
        # 13:56: with only car B's box the server walked Batman round its south end,
        # through the wall (the client showed him jumping past). The street's
        # walls at car B, from the clicks the client snapped to their edges:
        "finale_obstacles": [
            # (14:15: on to the building corner and the street turning north-east)
            ["CarBSouthWall", [[117.0, 11.25], [136.0, 11.25], [137.5, 11.6], [139.0, 11.95], [141.5, 13.15],
                               [143.5, 13.9], [143.5, -10.0], [117.0, -10.0]]],
            ["CarBNorthCrates", [[117.0, 18.65], [131.5, 18.65], [135.0, 18.95], [138.0, 20.0], [141.0, 22.0],
                                 [141.0, 45.0], [117.0, 45.0]]],
        ],
        # the car's own scriptlets when it lands: Vfx_OnExplode (as in the
        # original's intro cinematic); it needs the car's script table (0x7D2,
        # [combat] prop_script_tables). [] = none
        "car_explode_keys": [0x10000079],
        # 2026-10-16 14:05 (tester): "the explosion animation is not the right
        # one". The extra blast at the landing point was the meteor's dust cloud
        # (world state 0x2E0007D4 at scale 0.5): a meteor effect, not a car's.
        # Off; the explosion is the car's own Vfx_OnExplode. 0x2E0007D4 = back on.
        "blast_wstate": 0,
        # earlier tries (they do nothing on the client): the behavior property
        # 0x100003F2 set to these one every car_crash_step s, and
        # Destructible_AdvanceState as a property (car_break_property)
        "car_crash_states": [],
        "car_crash_step": 1.0,
        "car_break_property": 0,
        # 2026-10-16 15:31 (tester): after the impact the car "shoots off in
        # another direction" instead of bursting: the wagon's Vfx_OnExplode
        # breaks it apart in the client's physics and launches the body. The
        # wreck now goes 0.25 s after the explosion (its sound stays; the burst
        # on screen is the drones' own explosions). Was 6.0.
        "wreck_seconds": 0.25,
        # the car at the end of the bridge: 0x2E000AAB (police wagon, a static
        # prop: it cannot break) or 0x2E00034D (the paddy wagon, which can)
        # 15:09 (the original's video): the car at the end of the bridge is not
        # the paddy wagon of car B; 02PaddyWagonB (0x2E00034E, model 0x17000BC4,
        # the same breakable behavior graph) is the other wagon of the layout
        "bridge_vehicle_wstate": 0x2E00034E,
        "car_b_behavior_state": 0x10000116,  # car B starts as the graph's IdleState02 (0 = as the world state says)
        # 2026-10-17 11:12 (tester: the sphere that falls, opens and shows the Destroyer is missing;
        # "check the Destroyer's cinematic"): the cinematic 0x35000028 keys its Destroyer actor
        # with 0x100003A6 at frame 115 and Cinematic_Startup 0x100007EB at frame 125 (30 fps).
        # destroyer_cinematic_keys = [[seconds after the cinematic starts, key], ...] run on the
        # Destroyer then ([] = off); destroyer_start_keys no longer has Cinematic_Startup (was
        # [0x100007EB, 0x10000E5B]). destroyer_actor_props: the actor's properties (scale 0.85,
        # 0x954 = 2, 0x100007A2 = 1, templates destroyer_actor_tables) on the spawned Destroyer.
        # 11:36 (tester, fase3-hg): two Destroyers on top of each other in the cinematic: the cinematic
        # brings its own Destroyer actor (and plays its keys itself). The server's Destroyer is now
        # spawned when the cinematic ends (destroyer_in_cinematic false, was true); the keys and the
        # actor properties are off (were on in fase3-hg).
        "destroyer_cinematic_keys": [],
        "destroyer_start_keys": [0x10000E5B],
        "destroyer_actor_props": False,
        "destroyer_actor_scale": 0.85,
        "destroyer_actor_tables": [0x1D0003BA, 0x1D000774, 0x1D000385],
        "destroyer_in_cinematic": False,      # spawn the Destroyer before its cinematic (it opens when it ends)
        # the end of the match (docs/reverse-engineering.md "Ending a match")
        "send_match_end": True,              # notice 0x1000000E (VICTORY) + completed list 0x214B
        "send_match_stats": True,            # 0x2045: completes the end page (then the post-match movie plays)
        "victory_hold": 6.0,                 # seconds of in-world VICTORY before the match-ended notice
        # the VICTORY during the ending cinematic, this long after it starts
        # (after Superman's last line; the cinematic lasts ~23 s); 0 = at its end
        "victory_in_cinematic": 18.5,
        "victory_end_delay": 0.0,            # then the match ends this long after the cinematic ends
        # ...or rather this long after the cinematic starts, just before its end
        # (so the camera does not come back to Batman); 0 = at its end
        "match_end_in_cinematic": 22.6,
        # once the client closes the end page (0x20A6), 0x2190 again (harmless;
        # the reward itself now answers the end page's 0x212E/0x2124 requests)
        "reward_after_scorecard": False,
        "reward_at_match_end": False,        # also send the 0x2125 in the world (it is lost there)
        "reward_with_banners": True,         # 0x2125 right after the 0x211F answer too
        "car_back_shift": -0.8,              # cars 2 and 3 moved this much towards their rear (m); 22:35: -0.8 (from +0.8, 1.6 m the other way)
        # the in-world VICTORY: an announcement (notice 0x100002EB
        # ShowAnnouncement: [text, a, b, c, d, e, flag]; [] = none), the
        # objective banner (victory_banner, "" = none) and, optionally, a
        # timeline banner (notices 0x100002AF / 0x100002B1 / 0x10000424)
        # [text, billboard type (9 MatchWin / 11 Team1Victory: the big box; 2 the
        # strip), b, c, source team, target team, flag]
        "victory_announcement": ["VICTORY", 9, 0, 0, 1, 1, 0],
        "send_match_ended_event": True,      # 0x2038 with the VICTORY (UI event MatchEnded)
        # the scorecard's data (icserver/scorecard.py) with the match end, and
        # again these many seconds later (after the post-match movie)
        "send_scorecard": True,
        # training achievements: their progress at login and, at the end of a
        # tutorial, "newly complete" + its reward (Champion Unlocked)
        "send_achievements": True,
        "scorecard_resend": [5.0, 25.0, 60.0],
        "reward_ribbon_icon": 0,             # 0x2095 "upgrade unlocked" ribbon icon DID (0 = none)
        "victory_banner": "",
        "victory_timeline_banner": False,
        # The reward panels at home ("Champion Unlocked" Gaslight Batman, then
        # "Mission Complete"): Batman's item turns owned (0x20B8 again) and a
        # ribbon "item fulfilled" (0x2095) at the end of the match. With
        # replay_champion_unlock he is shown as not owned when the tutorial
        # starts, so the panel comes every time.
        "reward_champion": 0x40000086,       # 0 = no reward
        "reward_text": "Gaslight Batman",    # the ribbon's text
        "replay_champion_unlock": True,
        "replay_post_match_movie": True,     # reset User.HasSeenPostEncounterVideo@<encounter> (0x216A) each time
        "exit_lobby_delay": -1.0,            # >= 0: also send 0x2021 this long after the notice
        # 13:28 (tester: the PowerCore 0x2E000AC5 on the ground "is another part, not the sphere"):
        # the sphere is the phase pod 0x2E001157 (rig: body, door, plates A-D, thumper) with its graph
        # 0x1A000E0B (entrance, raider_open, OpenIdle; sphere_graph). Was 0x2E000AC5.
        # 15:02 (tester, [debug] model_tour = "pack:0xA0000256"): model 37 0x2E000FC7 is the closed
        # sphere (entity 0x2D000D3F, templates 0x1D0006AC, graph set 0x1C0000B5) and model 38
        # 0x2E00101D the open one (entity 0x2D000D92, template 0x1D000385). The sphere is the closed
        # one (was the phase pod 0x2E001157, which is now the crater ring again), with its graph set
        # and templates; it is swapped for the open one sphere_open_at s after it appears.
        "sphere_wstate": 0x2E000FC7,
        "sphere_templates": [0x1D0006AC],
        "sphere_open_wstate": 0x2E00101D,
        # 15:57 (tester: an animation starts on the closed sphere and is cut by the swap): the swap later,
        # 7.5 s after it appears (was 4.5; 15:26: 5.0; 15:13: 4.0)
        # 16:07 (tester's video): Vfx_Event1 opens the closed sphere itself (the halves part ~1.5 s);
        # the swap to the open model after it only flickered: off (0; was 7.5). sphere_open_at > 0
        # brings the swap back.
        # 16:19 (tester: "it was better before this change"; video: with the 16:07 settings the sphere
        # never opened): back to the fase3-hu settings, swap at 7.5 s (was 0)
        # 23:09 (tester: "a few seconds later the part that opens disappears"; frames of 21:49: the opened
        # halves vanish when the closed sphere is swapped for 0x2E00101D at 7.5 s): no swap (0, was 7.5); the
        # closed sphere, opened by Vfx_Event1, stays
        # 23:19 (tester: "leave the sphere as it was when I said it worked" = fase3-ip): 7.5 again (was 0)
        # 23:34 (videos 21:49 / 23:32: at the swap the sphere vanishes and the open model 0x2E00101D does not
        # show): no swap (0, was 7.5); the closed sphere, opened by Vfx_Event1, stays
        "sphere_open_at": 0.0,
        # 13:41 (tester): the game closed ~4.6 s after the pod was created with 0x5B5 = 0x1A000E0B and
        # the Spawn / OpenIdle events (a 0x5B5 is a graph SET 0x1C..., never a graph 0x1A...: the same
        # ~3 s close as the model tour). Off (0); the pod is sent as before (bare, open: the ring).
        # Test: sphere_graph = 0x1C0000B5 (the only graph set in both phase-pod packs not taken).
        # 13:56 (tester + diag): with 0x1C0000B5 + its templates the game did NOT close; the pod's
        # table allows only Vfx_Spawn 0x10000032 (0x100001E3, the graph-event scriptlet, rejected).
        # 14:05 (tester: "la esfera ni el crater se generan"): with 0x1C0000B5 + templates the pod no
        # longer shows at all. 0x1C0000B5 is the graph set of another world state (0x2E000FC7, packs
        # 168 / 256); every graph set in the pod's packs belongs to some other world state, and the pod's
        # own record has no 0x5B5 (only 0x50F, 0x7D2, 0x7EB, 0x2A4). Back to the bare pod (was 0x1C0000B5 /
        # True), as when the ring showed.
        # 15:02: 0x1C0000B5 is the closed sphere's own graph set (it made the pod invisible: wrong rig)
        "sphere_graph": 0x1C0000B5,
        "sphere_scripts": False,             # its templates 0x1D00078F (allow only 0x10000032)
        # 15:13 (tester + screenshot): the open sphere's doorway faced the top-left corner of the screen,
        # not the street Batman comes along: turned 135 degrees anticlockwise (was 1.5708; positive =
        # anticlockwise on screen, as the crater ring's 90 degrees at 12:32)
        "sphere_yaw": 3.927,
        # 15:26 (tester's video: it appeared as if teleported): it falls sphere_from_height m in
        # sphere_fall_seconds with moving updates ("move": a carrier follows updates with a speed > 0;
        # "recreate" = the old re-creations, which a carrier ignores); the crater ring appears when it
        # lands. Was 2.0 s from 0 m.
        # 22:40 (tester: with fase3-io's overlapping steps the fall looks frame by frame, "horrible"):
        # no fall (0, was 1.0 s from sphere_from_height): the sphere, its dust and the crater ring
        # appear together on the ground and the dust covers its fade-in
        "sphere_fall_seconds": 0.0,
        # 15:44 (tester's video: with "move" it stayed 12 m up: z of a carrier only counts when it is
        # created): "respawn" = a new object one step lower each sphere_fall_step s (was "move")
        "sphere_fall_mode": "respawn",
        # 15:44 (tester: no dust when it lands): the meteors' dust cloud at the landing (0 = off)
        "sphere_dust_wstate": 0x2E0007D4,       # tutorial1.METEOR_DUST_CLASS (also the car blast)
        "sphere_dust_scale": 1.5,
        "sphere_dust_lifetime": 3.0,
        # 21:53 (tester's video: the sphere still pops in on the ground): each new step fades in for a few
        # hundred ms, so the step above stays sphere_step_overlap s longer (was removed at once, 0) and
        # the steps are longer (0.2, was 0.1): the fall shows as a short trail instead of nothing
        "sphere_fall_step": 0.2,
        "sphere_step_overlap": 0.0,          # 22:40: off (was 0.3)
        # 22:51: the dust and the crater ring this long after the sphere appears: Vfx_Spawn_Hit 0x1000087E
        # (its impact) runs 1.05 s after it (sphere_cinematic_keys 1.55 - sphere_cinematic_start 0.5)
        # 23:34 (video 23:32: the crater ring shows on the ground ~1 s before the sphere fades in): the ring with
        # its impact, Vfx_Spawn_Hit 1.05 s after it appears (was 0); the dust stays with the sphere
        # 23:46 (tester: the sphere appears on the ground together with the crater and the dust wave): 0 (was 1.05)
        "sphere_impact_delay": 0.0,
        "sphere_fall_speed": 0.01,
        # 13:21 (tester + diag): the client builds the PowerCore once (at 15 m) and ignores the server's
        # falling re-creations, so it stayed in the sky while its keys 0x100003A6 / 0x100003A7 (both
        # accepted) played up there. Created on the ground now (was 15.0); its keys animate it.
        # 16:07 (tester's video: the fall steps never show, a new object fades in for ~0.3 s; only the
        # last one, on the ground, is seen): created on the ground (was 12.0) with Vfx_Spawn right away,
        # whose drop-pod graph clip entrance_a may be the fall itself
        "sphere_from_height": 0.0,           # 16:19: back to fase3-hu (was 0); 22:40: 0 again (was 12.0)
        # 2026-10-17 12:32 (tester: the sphere crashing is missing from the cinematic; video of the
        # original: it falls 1 s into the cinematic and opens at ~5 s; diag: the PowerCore rejects
        # 0x1000018E / 0x10000347 / 0x10000076 and allows 0x100003A6, the cinematic's frame-115 key).
        # sphere_in_cinematic: the cinematic is sent sphere_cinematic_delay s after the drones die
        # (was 3 s, after the sphere), the sphere starts falling sphere_cinematic_start s into it, and
        # sphere_cinematic_keys [[s into the cinematic, key]] run on it. sphere_keys (at landing) is
        # empty now (was the three rejected keys).
        # 2026-10-17 14:28 (tester: the crater shows, the sphere does not; fase3-ho): the sphere's core.
        # Pack 0xA0000256: the PowerCore actor of cinematic 0x35000025 carries template 0x1D00078A
        # (its 0x954), and a template there spawns the phase pod (the crater ring) and explosion
        # pieces 0x2E0007D4 / 0x2E0004ED on CinematicCharacter_State02 0x10000E5D / State03
        # 0x10000E5E. The PowerCore 0x2E000AC5 is created on the ground at the Destroyer with that
        # template (as 0x7D2) and its graph set 0x1C00006C, and gets State00..03 at these times
        # (s into the cinematic). sphere_core_wstate = 0 turns it off (only the crater ring).
        # 14:44 (tester + diag): it shows, but it is the ending cinematic's piece (0x35000025), not the
        # sphere; with 0x1D00078A it allows 0x1000005A, 0x10000E5B, 0x10000E5C, 0x10000E5F
        # (State02 / State03 rejected). Off (was 0x2E000AC5).
        "sphere_core_wstate": 0,
        "sphere_core_templates": [0x1D00078A],
        "sphere_core_graph": 0x1C00006C,
        "sphere_core_height": 0.0,
        "sphere_core_scale": 1.0,
        "sphere_core_keys": [[0.6, 0x10000E5B], [3.8333, 0x10000E5C], [4.5, 0x10000E5D], [5.2, 0x10000E5E]],
        "sphere_in_cinematic": True,
        "sphere_at": "destroyer",            # "destroyer" = (152.75, 24.0); "sphere" = the layout's (152.5, 28.0)
        "sphere_cinematic_delay": 0.5,
        "sphere_cinematic_start": 0.5,
        # 13:21: + 0x100003A7 at 4.5 s (the tester's test; both accepted, something started to show)
        # 13:56: Vfx_Spawn 0x10000032, the only key the pod allows, as it appears (was []; the
        # PowerCore's 0x100003A6 / 0x100003A7 of 13:21 belong to another model)
        # 14:05: [] again (was [[0.6, 0x10000032]]; accepted, nothing showed; a bare pod has no table)
        # 15:26 (diag --scripts): the closed sphere 0x2E000FC7 (template 0x1D0006AC) allows Vfx_Spawn
        # 0x10000032, Vfx_Active_State0 0x1000005D, Vfx_Fade_Out 0x1000006A, Vfx_Event1 0x10000076,
        # Vfx_Event10 0x100000DC, _HFSM_DestroyEntityAction 0x100001E0, Vfx_SpawnIdle 0x1000087D,
        # Vfx_Spawn_Hit 0x1000087E, Object_Deactivate 0x10000CCD, Object_Activate 0x10000CCE (not the
        # graph-event scriptlet 0x100001E3). Vfx_Spawn as it appears, Vfx_Spawn_Hit as it lands,
        # Object_Activate + Vfx_Event1 just before it opens (s into the cinematic; was [])
        # 15:57: Object_Activate at 2.5 s and Vfx_Event1 at 4.0 s apart (both were at 4.6 s, 0.4 s before
        # the swap), to tell which one starts the opening
        # 16:07 (tester's video): the opening started at ~3.5 s after it appeared = Vfx_Event1 0x10000076
        # (Object_Activate at 2.5 s did nothing visible; times are s after the drones die - 0.5 = s into
        # the cinematic, the sphere appears at 0.5). Vfx_Spawn as it appears (it went to the first
        # fall step before, never to the one on the ground), Vfx_Spawn_Hit at the landing (+1 s, with
        # the dust and the ring), Vfx_Event1 = the opening at 4.0 s (the video of the original opens
        # ~5 s into the cinematic)
        # 16:19 (video: with Vfx_Spawn on the sphere on the ground and no Object_Activate it never opened):
        # the fase3-hu keys again: Object_Activate at 2.5 s, then Vfx_Event1 at 4.0 s opens it
        # 23:34 (tester's video 23:32, fase3-it: the sphere never opened, Vfx_Event1 at 4.0 s showed nothing; in
        # the 21:49 video it opened when Vfx_Spawn had gone to a fall step and never to the sphere on the ground;
        # 16:19 too): no Vfx_Spawn on it (was [0.55, 0x10000032] first)
        "sphere_cinematic_keys": [[1.55, 0x1000087E], [2.5, 0x10000CCE], [4.0, 0x10000076]],
        # graph events on it: Spawn 0x10000154 at 0.6 s, OpenIdle 0x100004A5 at frame 115
        # 15:13 (tester: the sphere appears as if teleported, no fall, no opening): the closed sphere's
        # rig is env_pvp_drop_pod_a (graph 0x1A000CDC: Spawn -> Entrance, Idle, Explode; clips entrance_a,
        # idle_a, explode_a). Graph events Spawn 0x10000154 at 0.6 s and Explode 0x1000041F at 3.5 s
        # (was []; 13:41: off with the pod's borrowed graph)
        "sphere_cinematic_events": [],       # 15:26: 0x100001E3 is not in its table (was Spawn / Explode)
        "sphere_keys": [],
        "camera_lock_wait": 10.0,
        "r_cooldown": 10.0,
        # The passive (Echoes) is ranked automatically after this many seconds if
        # its "+" does not arrive (0 = wait for the click).
        "passive_auto_seconds": 30.0,
        # Ranged drones shoot from this far (m); their attack scripts
        # ([] = the melee drones' ones).
        "ranged_attack_range": 6.0,
        "ranged_attack_keys": [],
        # Batman heals this much per second out of combat; below 25 % the
        # Construct heals him at once (he never dies in the tutorial).
        "regen_per_second": 8.0,
    },
    "combat": {
        "use_variants": True,          # drones as character variants (vitals, attackable)
        "enemy_team": 2,
        "drone_health": 200,
        "basic_attack_damage": 45,
        # 2026-10-17 20:55 (tester: critical hits are not programmed): chance of a critical basic attack
        # (0 = never) and its damage multiplier. Gaslight Batman's real values are not known yet.
        "crit_chance": 0.2,
        "crit_multiplier": 1.5,
        "attack_interval": 1.0,        # seconds between basic attacks
        "attack_range": 2.5,
        "corpse_seconds": 3.0,         # dead drone removed after this
        "stop_on_death": True,         # 2026-10-16 19:11: the dead bundle has speed 0 (pieces slid)
        "spawn_scenery": True,
        # Movement module for props (bare world states: vehicle, meteors).
        # Without the module part (flag 0x20) the client never places an object
        # (old project's notes; diag 2026-10-14: the Door, sent with [1, 1], is
        # placed). "none" or [sequence, type] (types 1 = character replay, 2, 3, 9).
        "scenery_module": [1, 1],
        # Create props as their entity 0x40... (found in the packs at server
        # start: twin 0x49... property 0x510 = world state). false = old way.
        "prop_entities": True,
        # Cell of the position sent for props. Every placement in the encounter
        # layout (landblock 0x13cb) has cell 251; the server sent 0 (2026-10-14).
        "scenery_cell": 251,
        # World states with no entity of their own (vehicle, meteor) are created
        # as this entity (the Door, which the client does place: diag 2026-10-14)
        # with property 0x510 = the world state. 0 = create the bare world state
        # (never placed by the client: no physics placement in the diag).
        # 2026-10-14: the vehicle sent as the Door WAS placed at its spot but
        # stayed invisible (the Door has no model; 0x510 does not swap it). Off.
        "prop_carrier": 0,
        # 2026-10-14: the client only builds an object from an ENTITY (0x40...)
        # and takes its world state from it; the vehicle and meteor world states
        # have none. With the patched exe, class 0x4F + the world state's low
        # bits builds the Door entity with that world state. false = off.
        # 2026-10-14 15:17 (diag): sent as its bare world state (0x2E000AAB) the
        # vehicle builds without errors (.entity 0x2D0008BC, type 4), the meteors
        # too (0x2D000656); through the carriers it failed. So off by default.
        # 2026-10-14 15:35: bare world state = model built but never placed; the
        # carriers are placed. Cave Z (`ic.py patch` again) gives the carrier the
        # world state's model, so back on.
        "prop_override": True,
        # Carrier entities of the patched exe (class prefix 0x4A + index; needs
        # `ic.py patch` again when changed). Door 0x40000B0F failed at component
        # creation (diag 2026-10-14 11:36); the others come from `ic.py carriers`
        # (0x40000289: same creation type 0x50F = 5 as the vehicle; the rest are
        # entities of the loaded tutorial packs).
        # Skill cooldowns per client slot (1 = Q ... 4 = R), seconds; empty = the
        # kit's values (icserver/abilities.py). The client shows them on the buttons
        # (event 0x20F8); a skill on cooldown is not cast.
        "cooldowns": {},
        # 2026-10-18 00:57 (tester: "program John's abilities"): per-champion kits outside the tutorial
        # (icserver/kits.py KITS). Overrides by variant and slot, e.g.
        # kits = {"0x40000E57" = {"1" = {"ticks" = 10}, "base" = {"cooldown" = 8.0}}}. John Stewart's real
        # numbers were never shipped (every skill: 40 damage +40/rank, 30 Will, 14 s -2/rank).
        "kits": {},
        "enforce_cooldowns": True,
        # Batman stops where he casts Q / W and stays this long (s) so the cast
        # shows; R uses r_root (1.0 s)
        "cast_root": 0.35,
        # W (Sonic Shell) and E (Bat Flight), icserver/batman.py: damage, range,
        # projectile / flight speed (m/s) and radius of the hit.
        "w_damage": 120, "w_range": 11.0, "w_speed": 14.0, "w_radius": 3.0,
        "e_damage": 100, "e_range": 9.0, "e_speed": 14.0, "e_radius": 3.0,
        "r_damage": 400, "r_range": 60.0, "r_width": 4.0, "r_speed": 40.0, "r_duration": 1.2,
        "prop_carriers": [0x40000B0F, 0x400004FD, 0x400001BD, 0x4000081B, 0x40000B0A, 0x40000092],
        "prop_carrier_slot": 0,            # the carrier used for the vehicle and meteors
        # Test: also spawn the vehicle with the other 5 carriers (same spot) and
        # cycle the meteors through them.
        "prop_try_all_carriers": False,    # all 6 failed (2026-10-14 13:04)
        # Areas Batman cannot walk into: the server moves him itself, so the
        # map's own collisions do not apply. Each entry is [name, [[x, y], ...]]
        # (a polygon: the line Batman's centre cannot cross) or [name, x, y,
        # half length, half width, yaw] (a box, grown by his radius). The two
        # polygons follow the clicks the client snapped to the edge of the
        # walkable area in every log so far (2026-10-14): "Wagon" = the parked
        # wagon plus the pile of boxes in front of it, "SouthWall" = the wall
        # and the building south of them.
        "vehicle_blocks": True,
        "vehicle_box": [4.0, 1.6],
        "obstacles": [
            # the parked wagon plus the pile of boxes in front of it
            ["Wagon", [[28.85, 55.5], [33.45, 55.5], [33.3, 58.35], [34.3, 58.5], [34.9, 58.65], [35.4, 58.85], [36.0, 59.15], [36.55, 59.4], [37.0, 59.75], [37.25, 60.5], [37.1, 61.5], [36.65, 62.3], [35.6, 62.45], [34.4, 62.0], [33.3, 61.75], [32.3, 61.5], [31.2, 61.2], [30.0, 60.9], [28.85, 60.4], [28.75, 59.6], [28.75, 58.3], [29.0, 57.65]]],
            # the wall and building south of the wagon
            ["SouthWall", [[25.5, 56.55], [28.75, 56.6], [33.45, 56.0], [34.6, 55.6], [35.2, 54.95], [35.7, 54.2], [36.05, 53.0], [36.0, -10], [25.5, -10]]],
            # the building east of the square (2026-10-14 14:55)
            ["EastBuilding", [[45.3, 170], [45.3, 52.6], [45.75, 52.0], [53.15, 52.0], [53.3, 51.3], [170, 51.3], [170, 170]]],
            # the boxes and debris at the end of the street (2026-10-14 13:55)
            ["Boxes2", [[35.9, 52.95], [40.7, 52.85], [41.6, 52.2], [42.05, 51.4], [41.6, 50.4], [41.0, 49.2], [40.3, 48.3], [35.9, 48.3]]],
            # the north edge of the square (clicks stop at y 64.1)
            ["NorthWall", [[-10, 64.3], [170, 64.3], [170, 170], [-10, 170]]],
            # south side of the street past the vehicle
            ["SouthStreet", [[35.9, 48.3], [40.3, 48.3], [40.65, 48.35], [42.2, 46.5], [45.5, 44.85], [52.0, 43.55], [57.7, 41.45], [60.0, 39.0], [64.3, 36.1], [68.7, 34.4], [72.4, 32.5], [75.4, 31.7], [79.4, 30.0], [82.0, 28.5], [89.2, 25.6], [89.2, -10], [35.9, -10]]],
        ],
        # Manual override: {"0x2E000AAB" = 0x40000xxx}
        "prop_classes": {},
        # A right-click on the ground this close to an enemy counts as attacking
        # it (the client does not let you target the drones yet); attack-move (A)
        # picks the nearest enemy within the larger radius.
        "click_attack_radius": 1.6,        # the 2nd marker is 2 m from the drone
        "attack_move_radius": 8.0,         # vehicle and drone gates of the first area
    },
    "scripts": {
        # Event 0x8D runs a script on an entity. The id is NOT the scriptlet DID
        # (0x34...): the client only accepts names from the entity's script tables
        # (class property 0x7D2 -> records 0x1d...; diag 2026-10-13 rejected
        # 0x34000037 with 0x80070057). Names from shared table 0x1d0001f6:
        # Each hit uses the next entry (an id or a list of ids run together):
        # Combat_Basic_Attack_Right + Vfx_Bmg_Basic_Ranged_Right, then the Left pair.
        # [] = off. (2026-10-13: the Combat_Basic_Attack_* names start: Batman moves.)
        "basic_attack_keys": [[0x10000195, 0x10000188], [0x10000196, 0x10000189]],
        # 2026-10-17 20:55 (tester, champion tour): a critical basic attack plays Combat_Critical_Attack
        # 0x100000B8 (the arms) + Vfx_Bmg_Crit 0x1000017E (the shot); the shot ends with Vfx_Bmg_Crit_Stop
        # 0x1000017C. [] = critical hits look like normal ones ([combat] crit_chance / crit_multiplier)
        "crit_keys": [0x100000B8, 0x1000017E],
        "crit_stop_keys": [0x1000017C],
        # Give the attack scripts the target (script variable 0x108) so the shot
        # flies at the drone instead of straight ahead.
        "send_target": True,
        # Pistol shots: where they reach the drone (distance / shot_speed) the shot
        # is ended (Vfx_Bmg_Basic_Stop) and the hit effect plays (Vfx_Bmg_Basic_Hit)
        "shot_speed": 20.0,
        "shot_stop_keys": [0x10000170],
        "shot_hit_keys": [0x10000187],
        # Run on the drone that is hit: VFX_CBT_Hit_Shared + _HFSM_TargetHitAction_PhysicalReaction.
        # [] = off.
        "hit_keys": [0x10000223, 0x10000209],
        # Run on a drone when it dies: _Defeat_OnDead (CbtState_Death_Induce is not
        # in the drones' table). [] = off.
        "death_keys": [0x100001FA],
        # Scriptlets on the champion go this many seconds after the messages of
        # the same moment (a champion bundle sent after them cut the animation).
        "champion_defer": 0.06,
        # Who "started" the script (u64; 0 = the server). The client skips the
        # order if this equals its own local id, because it already predicted it.
        "originator": 0,
    },
    "debug": {
        "hexdump": True,              # full hex dumps in logs\traffic.log
        "dev_send_file": True,         # logs\send.txt: "<player|svc|hexid> <event hex> <body hex>"
        "old_server_dir": "",          # optional: an earlier _server folder whose tracer.py replaces tools\tracer.py
        # Batman action tour: once the tutorial starts, play these scriptlet keys
        # on Batman one by one (server.log names each one). "all" = the keys of
        # data/batman_actions.tsv (see docs/batman_actions.md); "core" = a short list
        # of the actions that matter for Batman's kit (old spelling "nucleo" also
        # accepted); [] = off.
        "tour_keys": [],
        "tour_interval": 3.0,
        "tour_start": 6.0,
        # 2026-10-16 23:46 (tester): the same for models. "candidates" = the meteor /
        # crater / fire candidates (tutorial1.MODEL_TOUR_CANDIDATES), "pack:0xA000024C" =
        # every world state of that pack, or a list of ids; [] = off. One every
        # model_tour_interval s at model_tour_at, numbered in the objective text
        # ("Model n/N 0x2E..."); model_tour_from skips ahead. The keys are tried on each.
        "model_tour": [],
        "model_tour_interval": 4.0,
        "model_tour_start": 6.0,
        # 00:12: 0 = go on after the last model shown (logs/model_tour.json); models that
        # closed the game are skipped (0x2E000F04 and any found later)
        "model_tour_from": 0,
        # 00:58: off the line from Batman to the first marker (25.1, 60.3); was (24, 60)
        "model_tour_at": [23.0, 56.0, 200.0],
        "model_tour_scale": 1.0,
        "model_tour_keys": [0x1000018E, 0x10000032, 0x10000078],
        # 2026-10-17 00:44 (tester): from model 14 on the game closed ~3 s after each model
        # (their scripts running on the carrier): the tour shows bare models; true = with
        # their scriptlet templates and model_tour_keys, as in fase3-gu/gv
        "model_tour_scripts": False,
        # 01:08: the game closed up to 3.3 s after a model appeared: a drop within this many
        # seconds marks that model as closing the game (skipped from then on)
        # 2026-10-17 16:54 (tester, lab fase3-hx): 0x2E000877 closed the game 4.52 s after it appeared and
        # was not marked; 6.0 (was 4.5)
        "model_tour_crash_window": 6.0,
        # 2026-10-17 09:31 (fase3-hb): the Tutorial 2 lab ([match] maps "lab"). lab_tour: "lab" =
        # tutorial1.LAB_CANDIDATES (meteor family from catalog world_states.tsv), "pack:0x..." or a
        # list. Each model is shown once per lab_modes entry ("bare" = no scripts, "scripts" = its
        # scriptlet templates + model_tour_keys), labelled "Model n/N a" / "b", every lab_interval s
        # from lab_start s, at the start point + lab_offset. lab_from: entry to start at (0 = after
        # the last one shown; logs/model_tour.json "lab").
        # 10:37: "sphere" = tutorial1.LAB_SPHERE (the sphere / drop pod / iris candidates and the
        # Stolen Power meteor); "lab" = the meteor pieces of fase3-hb / hd
        # 2026-10-17 16:24: "start" = tutorial1.LAB_START (fire-column candidates: the meteor event
        # object 0x2E00069E with Vfx_Spawn_Event05, the set pieces 0x2E000872-877); was "sphere"
        # 2026-10-17 19:18 (tester): "batman" = every Gaslight Batman animation / effect on the player's
        # champion (icserver/champion_fx.py: graph events, then the scriptlets the client accepts on him),
        # labelled "G n/N name" / "S n/N name" (was "start")
        "lab_tour": "batman",
        "champion_tour_interval": 8.0,     # 19:52: 6 s (was 3) for the short list; 23:19: 8 (Spawn lasts ~5 s)
        "champion_tour_stop_after": 2.4,
        "champion_tour_from": 0,
        # 19:52 (tester: S 37 Cinematic_Intro lit the antennas, and the rope came with it). Its template
        # entry (pack 0xA0000076) does three things: action 0x737 = 2, the graph event Spawn 0x10000154 and
        # the scriptlet Vfx_Bmg_Spawn 0x10000181; Cinematic_Hidden does 0x737 = 2 + graph event SpawnIdle.
        # Only these, one by one, to tell which part is the electricity and which the rope ([] = all).
        # 23:19 (antennas without the voice line): 1 G Spawn alone on a fresh Batman, 2 Vfx_Bmg_Spawn, 3 G Spawn
        # again (the 20:41 order that lit them), 4 Cinematic_Intro (lights them, with the voice line). For each:
        # electricity yes / no, voice yes / no. Was the five-entry list of 19:52.
        "champion_tour_only": ["G Spawn", "S Vfx_Bmg_Spawn", "G Spawn", "S Cinematic_Intro"],
        # 09:59 (tester: the explosion 2b was right; "now the particles"): "keys" = each scriptlet
        # key of the model's templates on its own (the particles it plays); was ["bare", "scripts"]
        "lab_modes": ["keys"],
        "lab_interval": 5.0,
        "lab_start": 6.0,
        # 09:49 (tester): at (+4.3, -4.4) the models stood among the map's own props and could not
        # be told apart; the same distance on the other side of Batman is clear
        "lab_offset": [-4.3, 4.4, 0.0],
        "lab_from": 0,
        "lab_open_keys": [0x1000018E, 0x10000032, 0x10000078, 0x10000E5C],   # "graph+keys" entries
    },
}


def _merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    def __init__(self, data, path=None):
        self.data = data
        self.path = path

    def __getitem__(self, section):
        return self.data[section]

    def resolve(self, relpath):
        """Paths in the config are relative to the folder of ic.py."""
        if not relpath:
            return relpath
        return relpath if os.path.isabs(relpath) else os.path.join(ROOT, relpath)

    @property
    def game_dir(self):
        return self.data["game"]["dir"]

    def game_file(self, name):
        return os.path.join(self.game_dir, name)

    @property
    def key_path(self):
        return self.resolve(self.data["server"]["key"])

    @property
    def log_dir(self):
        return os.path.join(ROOT, "logs")

    def champions_path(self):
        explicit = self.data["server"].get("champions_json")
        candidates = [self.resolve(explicit)] if explicit else []
        candidates += [os.path.join(ROOT, "data", "champions.json"),
                       os.path.join(self.game_dir, "_server", "champions.json")]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None


def load(path=None):
    path = path or os.path.join(ROOT, "config.toml")
    data = copy.deepcopy(DEFAULTS)
    if os.path.isfile(path):
        if tomllib is None:
            raise RuntimeError("Python 3.11 or newer is required (tomllib)")
        with open(path, "rb") as f:
            _merge(data, tomllib.load(f))
    return Config(data, path if os.path.isfile(path) else None)
