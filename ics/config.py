"""Settings of the new server (python -m ics). Read from config.toml: [game] dir and [server] are shared with the
old server; everything else is in [ics]. Every value here is either plumbing (ports, paths) or something the
game data does not hold (or that has not been found in it yet); each one says which.
"""
import copy
import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "game": {
        "dir": r"C:\Program Files (x86)\Steam\steamapps\common\Infinite Crisis Steam",
        "exe": "InfiniteCrisis.exe",
        "patched_exe": "InfiniteCrisis_patched.exe",    # made by python ic.py patch (login key, client fixes)
        "language": "en",
        "region": "NA",
        "cpu_affinity": "FFFE",
    },
    "server": {
        "host": "127.0.0.1",
        "soap_port": 8888,
        "user_port": 9000,
        "game_port": 9001,
        "key": "keys/server_private.pem",
    },
    "ics": {
        "player_name": "Player",
        "account_level": 30,             # 30 = veteran: skips the trainee pack load
        # The champion every match uses for now (no champion select yet): Gaslight Batman, the tutorial's.
        "champion": 0x40000086,
        "player_class": 0x4000007C,      # the invisible "player object" (always-loaded pack 0xa0000037)
        "team": 1,
        "enemy_team": 2,
        "room_id": 1,
        # Per encounter: where the champion starts and what else it needs. The packs the match loads (0x20AF)
        # come from the data (2026-10-21: encounter template 0x10000406 = the map pack, which lists its packs;
        # ics/gamedata.py encounter); "packs" here is only added to them. "extra_champions": champions that act
        # in the encounter's cinematics (Gaslight Catwoman 0x40000262 breaks the vehicle in 0x35000034).
        "encounters": {
            "0x40000991": {
                # Added to the map pack's list (0x20AF). 2026-10-21 21:46 (tester: not every map element loads):
                # 17 statics of 0x2E0005D6 need .entity 0x2D0002E4, only in 0xA00000B3; 0xA00000DF holds 13 other
                # missing assets (movement-collision-fog-map.md 3.2). Next to try: 0xA00000FC, 0xA000009A.
                # 2026-10-23: both are start-up packs, already loaded; [ics] resident_packs leaves them out of 0x20AF.
                "packs": [0xA00000B3, 0xA00000DF],
                "extra_champions": [0x40000262],
                # Intro cinematic after the load (0 = none). Not found in the encounter's data yet; 0x35000026 is
                # what the earlier server played. 2026-10-21 (tester: walking forward goes down instead of right):
                # the client sets the map camera when a cinematic ends.
                "intro_cinematic": 0x35000026,
                "spawn": [1, 0x13, 0xCB, 0, 18.7, 60.4, 200.3],
                "ground_z": 200.0,
                # 2026-10-21 (master plan step 3): the encounter's flow, ics/encounters/<director>.py. The data has
                # the objectives (0x48000D3F), conversations (0x40000CB7) and cinematics, not when each happens.
                # "" = no flow (every layout placement at once, every skill at skill_rank).
                "director": "tutorial1",
                # D and F (2026-10-21, master plan): Gaslight Batman's Surveillance Camera and Superman's Super
                # Strength, as the original's tutorial gave them; elsewhere the champion's default pair (loadout
                # 0x1000064E). F as a ground target: the client's picker refused the car (2026-10-16).
                "stolen_powers": [0x48000808, 0x48000A3B],
                "stolen_targeting": {"8": 1},
            },
            "0x40000C82": {
                # Crime Alley vs AI. 2026-10-23 (tester: elements on the ground do not load): its statics reference
                # 108 DIDs only in the Gotham Heights zone pack 0xA000009A (street pieces 0x2E0005D6, the roof
                # 0x2E000375; movement-collision-fog-map.md 3.2). 2026-10-23 12:07 (tester: with it the load stopped
                # at 15 %): a second zone pack in 0x20AF hangs the level load, so it is not named. 2026-10-23 15:20: the
                # small packs that hold a few of the missing statics' DIDs instead (not zone packs).
                "packs": [0xA0000116, 0xA0000073, 0xA000022E],
            },
        },
        # Champion vitals: the champion records' base health / Will are not read yet (2026-10-21).
        "health": 600,
        "will": 100,
        "will_regen": 2.0,               # Will per second
        "unit_health": 300,              # layout units (drones) until their stats are read from the data
        "move_speed": 4.5,               # m/s; also sent as property 0x100005E4 (walk animation cap)
        # 2026-10-24 00:40 (tester: champions move too fast for their animations): a champion with a stats record moves at
        # its own 0x100005E4 (base + growth x (level - 1), items included); move_speed stays for one without.
        "champion_move_speed_from_data": True,
        "skill_rank": 1,                 # every skill starts at this rank when the encounter has no flow
        # Highest rank per skill slot (1-4 Q/W/E/R, 5 passive): the champions' build records (0x10000CEB) spend 19
        # points as 4 / 4 / 4 / 4 / 3 (champions-all.md, progression-meta.md, 2026-10-21)
        "max_skill_ranks": {"0": 1, "1": 4, "2": 4, "3": 4, "4": 4, "5": 3},
        # 2026-10-23 14:02 (tester: R could be ranked at level 1; it opens at 6): the level each rank needs, by slot;
        # other slots follow rank r -> level 2r - 1 (rank_level_rule; false = any level).
        "match_start_ranks": {"0": 1, "6": 1, "7": 1, "8": 1},   # lobby matches: other slots start at 0 (2026-10-23)
        "match_start_skill_points": 1,
        "rank_min_levels": {"4": [6, 11, 16, 20]},      # 4th R rank at 20: P (19 points spent 4/4/4/4/3)
        "rank_level_rule": True,
        # 2026-10-30 tester report ("at level 19 the level-up prompt shows, the '+' stays in Recommended and on the HUD,
        # but neither the '+' nor Ctrl + key ranks up"; docs/re-notes/skill-rank-levels.md): the level cap is 19 (19
        # points), but rank_min_levels put the 4th R rank at 20, so the 19th point could never be spent while the
        # client's own rule (WLib InqCanRankSkill 0x926C -> 0x94E4) offered it from level 18 and the server dropped the
        # request silently. True = the client's rule: the skill block's array 0x1000099C (Green Arrow's R, Starro's E),
        # else rank_level_table by slot ("default" = every other slot). False = rank_min_levels / rank_level_rule.
        "rank_levels_from_client": True,
        "rank_level_table": {"4": [6, 10, 14, 18], "default": [1, 3, 6, 9]},
        # a refused rank request is logged with its reason and the champion's rank state is sent again (2026-10-30)
        "rank_refused_refresh": True,
        "lobby_stolen_powers": True,     # the Stolen Powers picked in champion select go to the match (2026-10-23)
        "basic_attack_range": 5.35,      # used when the basic attack has no stat 18
        # 2026-10-23 23:06 (tester: Atomic Green Lantern could not attack the turrets, Batman could): the basic attack's
        # reach and the scripts' hit / range checks count to a structure's edge (its navmesh footprint radius,
        # match_structure_radius) instead of its centre, which a short-range champion can never reach.
        "attack_reach_to_edge": True,
        # 2026-10-29 tester report of 18:31 ("if the enemy champion runs away inside my basic-attack area, my champion
        # runs after it and never stops to attack"; docs/re-notes/basic-attack-chase-range.md): a champion's basic-attack
        # reach was centre to centre (stat 18), while the client's attack validator 0x9d01d0 (step 11) counts the skill
        # range + both collision radii (0x5897a0 = template radius x scale + 0.05) and its range ring adds the caster's:
        # a target fleeing at the same speed stayed ~1 m past the server's reach, inside the ring, forever.
        # attack_range_radii: a champion's reach = stat 18 + its radius + the target's (structures / minions: their
        # match radius; replaces attack_reach_to_edge for champions); false = as before. attack_body_radius: radius by
        # kind (champion 0.575 = the champion navmesh agent 0.525 + 0.05, P; unit 0.5)
        "attack_range_radii": True,
        "attack_body_radius": {"champion": 0.575, "unit": 0.5},
        # 2026-10-23 23:18 (tester: emotes worked on the old server with Ctrl+number): the client's keymap binds them to
        # Alt+Numpad1-5 (Ctrl+1-4 = DoNothing) and sends 0x9F 0x81970006 with the emote record DID (docs/re-notes/
        # emotes.md); the server raises the champion graph's emote event (scriptlet 0x100001E3 + 0x780), or plays a
        # scriptlet when the value is a name. Oath has no graph event: its Emote_Oath_Start scriptlet (guess).
        # 2026-10-23 23:30 (tester: AGL's skills play only their start: Grab never pulls, Scorched Earth's circle stays,
        # Meltdown's throw is cut; docs/re-notes/skill-second-stages.md): the cast's end (2) waits up to this many s for
        # the cast's tethered missile; the tethered missile's own script gets 0x10000005 when back; SetSkillAttached
        # raises 0x10000022 / 0x10000014 on its script; StopScriptletKey signals the live run (0x8D with the run's
        # instance and this signal bit; None = only logged).
        # 2026-10-24 23:30 (tester: Atomic Wonder Woman: W never empowers the next basic, E always does the 2-charge
        # slash, Q recasts at once; docs/re-notes/aww-kit.md): script_owner_block = source-2 operands shared by every
        # script of an entity; spend_by_vital = SpendCost adds its signed amount to its own vital (Rev +1);
        # champion_resource_from_data = each champion's resource vital type (twin 0x1000000C: Will 5, Rev 6, ...), a
        # non-Will one starts empty without will_regen; basic_hit_event = a basic attack's hit raises 0x1000008B.
        # 2026-10-25 (tester: skills start their animation and never finish; animation-deep-scan.md, C): the cast signals
        # 3 / 5 / 6 at the times of the champion's graph triggers and 2 at the state's exit trigger (data/skill_hooks.tsv
        # from tools/graph_hooks.py); a state with no self-ending trigger ends after graph_exit_fallback s. False = the
        # old fixed 0.25 / 0.40 s.
        # 2026-10-25 10:40 (tester's video: Grab moves AGL to the enemy instead of pulling the enemy to him): a tethered
        # missile that hits flies back to its shooter (tether_return) dragging the target to 1.5 m in front of him
        # (tether_drag, a forced movement); back at the shooter it ends (0x10000005).
        # 2026-10-25 13:15 (tester's log: AGL's passive repeated its chain ~24 times per hit): a script instance that gets
        # the same event more than this many times within 20 ms drops the rest (runaway loop guard; 0 = off).
        "event_loop_limit": 4,
        # 2026-10-25 (skill-mechanics-recipes.md 1, C: a re-sent 0x10000006 switches 189 status scripts back to idle;
        # Flash's passive grew to 10 instances on its decay): a status that counts stacks (waits for 0x100000D7 /
        # 0x100000A8) or does not stack keeps one instance with a stack count; AddStacks sets the absolute count.
        # false = one instance per use and a re-sent 0x10000006 (fase3-hs).
        "status_stack_model": True,
        # 2026-10-25 (map-objectives-recipes.md 6, C from VM runs): a polled transition is tried once per tick per graph
        # (the Doomsday pad livelocked S0 -> S7 -> S0); a RaiseEvent on the raising instance itself arrives after the
        # current chain (the GH cannon skipped its 65 s neutral phase)
        "script_poll_once_per_tick": True,
        # 2026-10-25 (stolen-powers-audit.md 5.2): spawned objects that run the thrown-object scripts get the thrown /
        # launch / collision / flight-end events (Meteor Drop's meteor); class -> fallback {fall s, radius m}
        "thrown_spawn_classes": {"0x4000044F": {"fall": 2.0, "radius": 3.0}},
        # Super Strength's lift end (0x100000BB after the pickup 0x10000037; 1.2 s as icserver/finale.py's lift)
        "raise_event_follow": {"0x10000037": ["0x100000BB", 1.2]},
        # a second press while the skill's script waits for it in a nested state (Super Strength's throw) is its next
        # stage, not refused by the cooldown the first stage started
        "recast_while_waiting": True,
        # 2026-10-25 (skill-mechanics-recipes.md 2): SetSlotSkill swaps a slot's skill (record's slot 0x100000E6, stats
        # over the base's), ClearSkillStatOverride brings the base back (Aquaman R, Blue Beetle R, Grundy E, Catwoman R)
        "set_slot_skill": True,
        # skill-mechanics-recipes.md 3 (C offsets): a script's local frame is +Y forward (Arcane Supergirl Q, Swamp
        # Thing Q, Dex-Starr R hit where they aim); false = +X forward (fase3-hs)
        "local_y_forward": True,
        # skill-mechanics-recipes.md 4 (C layout): skill stats add their scaling block (Mod x attack / power / health /
        # Will by the 0x3B formula): Atomic Joker Q, item-scaled skills; false = the plain base value
        "skill_stat_scaling": True,
        # skill-mechanics-recipes.md 5 (C): chains (Shazam Q, Nightmare Superman E) run every hop: DamageSuccess is set
        # before the damage events, and a state's own locals start fresh on each entry
        # skill-mechanics-recipes.md 7: spawned skill objects whose class no template links to a script, with the
        # orphan script that matches them (Swamp Thing E 0x40000BCA: all 8 stats of E, C; Nightmare Robin Q, P)
        # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; kit-audit-3.md, skill-mechanics-recipes.md
        # 7.2: every Star Sapphire order (Q, R Manifest, passive) is a RaiseEvent to script 0x340003D1 on her Predator
        # 0x400005D2, which no template lists; P: the server started it on the Predator): 0x400005D2 runs it too
        "spawned_class_scripts": {"0x40000BCA": ["0x340005CB"], "0x40000CA4": ["0x340004E3"],
                                  "0x400005D2": ["0x340001A6", "0x340003D1"],
                                  # 2026-10-28 (same report): Arcane Supergirl's Rao's Wrath 0x3400054D spawns and launches the
                                  # scriptless 0x40000AE5; orphan 0x34000562 loads slot 4's stats 5 / 18 from its shooter,
                                  # explodes on the flight's end and raises 0x10000141 on script 0x3400054D itself (C)
                                  "0x40000AE5": ["0x34000562"]},
        # 2026-10-28 (same report): a spawned unit with an attack (template 0x10000328: the Predator, The Joker's teeth)
        # starts its attack script like any unit; false = its kit never runs ("Attack: its script is not running").
        "spawned_unit_kit": True,
        # skill-mechanics-recipes.md 6: events scripts wait for that the server now raises (damage family 0x100000E7 /
        # 0x10000145, team members 0x1000007B, respawn 0x10000016, takedown / assist 0x10000097)
        "damage_family_events": True,
        "team_member_events": True,
        "respawn_script_event": True,
        "takedown_script_event": True,
        "damage_success_first": True,
        "reset_state_locals": True,
        # 2026-10-25 19:28 (agl-e-r.md, C): a graph fires no transition while its own exit chain runs
        "exit_chain_reentry_guard": True,
        # 2026-11-02 (tester report 2026-11-02 01:43: Atomic Joker's R never stops, it kept hitting after his death and
        # respawn): a sub-graph its parent leaves stops; its pending polls / timers kept firing it (false = as before)
        "stop_left_subgraphs": True,
        # 2026-11-02 (tester report 2026-11-02 02:20: Superman's E does not push the enemy back): a graph state's enter
        # chain runs before its sub-graph starts (the knockback status 0x340003F8 set its distance after its sub-state
        # had already dashed 0 m). false = the sub-graph first, as before
        "graph_enter_before_children": True,
        # 2026-11-02 (tester report 2026-11-02 01:45: Superman's W roots nobody in its inner cone): a status record's own
        # flag attributes (list 0x1000046F, op 6: Rooted, Stunned, Crippled ...) hold while the status lasts; the root
        # 0x48000A06 has nothing else that roots (false = only what the status scripts add, as before)
        "status_record_flags": True,
        # 2026-11-03 (tester report 2026-11-03 00:32: Superman's E punch hit the enemy the dash only touched): a name used
        # in two local frames (operand source 3, 4, 5 ...) is two variables, as the original's frames are separate
        # memory (Heat Vision's target vs the dash's collider, both "TargetIID"; 95 scripts). false = one per name
        "local_frames": True,
        # 2026-11-03 (tester report 2026-11-03 00:32: Superman's E punch had no animation, a basic attack cut it): the
        # basic attack a skill queues (QueueOrder 0x100000DB) waits while one of the champion's skills is in its cast, as
        # the client buffers orders during an action (full-combat-skills.md 1.4, C). false = at once, as before
        "attack_waits_for_action_lock": True,
        # 2026-11-03 (tester report 14:40: the punch still cut): the queued attack also waits while the champion's
        # animation graph is in a state a slot skill hooks (false = the cast only)
        "queued_attack_waits_graph": True,
        "queued_attack_lock_wait": 2.0,   # s at most a queued attack waits (ours, a safety; 0 = no wait)
        # 2026-11-03 (tester report 2026-11-03 00:34: Blue Beetle's ranged and melee Q / W / E share cooldowns; they must
        # be independent): the owner block's 0x20 + 8 x slot reads that slot's cooldown end (the engine's; no script
        # writes it) and StartCooldown with an explicit slot sets that slot to the given remaining time, 0 = ready (the
        # form swap puts back the other form's). false = as before
        "slot_cooldown_vars": True,
        # 2026-11-03 (tester: Blue Beetle's melee basic attack has the ranged reach): the basic attack's reach takes the
        # slot-0 stat 18 override its script sets (SetSkillStatOverride 0x10000153). false = the record's stat 18
        "attack_range_override": True,
        # 2026-11-03 (tester report 2026-11-03 14:4x: Superman's E pushes the target in a fixed direction; the original
        # pushes it on, away from Superman): a "with heading" expression (0x41) given a vector takes its direction (the
        # knockback 0x340003F8 passes Offset(source, target)); P. false = the vector read as 0 degrees, as before
        "heading_from_vector": True,
        # 2026-11-03 (tester report 14:40: Superman's E punch never shows): a state that raises its own animation and
        # waits for OnCastSignal 2 waits for that animation's end (the graph's code 2), not for its chain's end (also 2).
        # false = the chain's end fires it, as before
        "graph_done_waits": True,
        # 2026-11-03 (tester report 14:43: Blue Beetle's E shots never fly, each destroyed 77 ms after its creation): a
        # script-spawned entity's 0x10000049 comes after the spawning chain, and LaunchMissile of an entity gives its
        # scripts TargetIID before its events (P: the client evaluates once per update). false = at once, as before
        "spawn_event_after_chain": True,
        # 2026-11-03 (tester: Blue Beetle's E shots hit for 0): a skill's spawned object reads LoadSkillStats' "this slot"
        # as the slot of the skill that spawned it (P; false = no slot, stats 0)
        "spawned_entity_skill_slot": True,
        # 2026-11-03 (tester: Blue Beetle's form effects stay after a swap): a deferred scriptlet stop takes the run live
        # at the call, not at the send (a restart in between kept its run). false = at the send, as before
        "stop_takes_run_at_call": True,
        # 2026-11-03 (tester report 15:27: Superman's E beacon missing, Blue Beetle's form effects stay; the run: a
        # StopScriptlet(handle) stopped the key's newest run on the entity, not the handle's): a StartScriptlet handle
        # keeps its run and StopScriptlet stops that run. false = the key's newest run, as before
        "scriptlet_handle_runs": True,
        # 2026-11-03 (tester report 2026-11-03 16:11: Blue Beetle's passive does not start on his melee E / W): SkillEcho
        # 0x10000195, called by 221 skill scripts after their cast point, raises "skill used" 0x10000196 {Slot} (P); the
        # activation's broadcast stays for the scripts without it. false = the activation's broadcast only, as before
        "skill_echo_node": True,
        # 2026-11-03 (tester report 23:24: in the original the ranged W starts Blue Beetle's passive when launched or
        # detonated; the detonation is a second press with no SkillEcho): every taken use raises "skill used" 0x10000196
        # at its activation again; SkillEcho raises it only when the use's activation did not (false = anim-22)
        "skill_used_every_use": True,
        # 2026-11-03 (tester report 2026-11-03 22:16-22:20: Blue Beetle's passive particles gone in ranged form, his
        # yellow blaster stayed after the buff until he fired; C: every 0x8D order first stops every run earlier orders
        # started on the object, 0x627E4D -> 0x57CB60, and an 0x8D "stop" of a dead run starts it again): one 0x8D per
        # object and moment, StartScriptlet runs ride along in the object's later orders until stopped (P), and stops
        # go as event 0x11F (the client's own stop, mode 1). ics/scriptlet_orders.py. false = one order per scriptlet
        # and 0x8D signal stops, as before
        "scriptlet_orders": True,
        "scriptlet_orders_skip_encounters": ["0x40000991"],   # Tutorial 1 keeps its own orders
        # 2026-11-04 (tester report 01:59: Superman's beam middle missing sometimes; vitals / modifier / status icon
        # messages between two steps of Heat Vision split them into two 0x8D, the second ended the beam): those messages
        # no longer send a champion's waiting orders (false = any message, anim-23..26)
        "scriptlet_orders_quiet_messages": True,
        # 2026-11-04 (tester report 03:15: a knockback looked like a teleport; motion states are unlabelled): a forced
        # movement's (knockback / dash) motion states get a label, so traffic.log shows them (same bytes; false = not)
        "log_forced_motion": True,
        # 2026-11-04 (tester report 15:25: the first Heat Vision knockback of the match looked like a teleport; its
        # status started 0.13 s late, while its script was looked up in the packs for the first time): the statuses a
        # champion's kit can apply are read at its creation (loading screen) (false = at their first use, as before)
        "prewarm_statuses": True,
        # 2026-11-05 (tester report: Blue Beetle's Q explosion missing at the first cast only; the first SpawnEntity of
        # 0x40000CD8 read its class data for 69 ms, the script's collision delay ran out meanwhile): the object classes
        # the kit's scripts create, and their scripts, are read at the champion's creation too (false = on first use)
        "prewarm_spawn_classes": True,
        # 2026-11-04 (tester report 15:23: Blue Beetle's Q explosion in 2 of 16 casts; its emitter started on the client
        # before the explosion object was placed: the client replays movement states >= 0.1 s old, client-movement.md
        # 0, C): a standing spawned skill object's creation state is stamped this many s earlier (0 = now, as before)
        "spawn_state_backdate": 0.1,
        "scriptlet_orders_scope": "champions",                 # "all" = every object (units, props: a later PR)
        # 2026-11-03 (tester report 23:22: Superman's punch sound still missing, Blue Beetle's melee wing glow missing; the
        # run: the next order 0.25 s later (a basic attack) ended the punch's Vfx_Sup_Heat_Vision_Dash_Stop): "0x2073"
        # sends a champion's orders with the client's additive start (no stop-all, live runs skipped), so nothing ends a
        # run before its time. 2026-11-04 (diag --orders 00:51-00:56, C: the champion's +0x110 = 0x1B759EC = 0, so
        # 0xA883F0 takes the direct path 0xA22DA0): the default. 2026-11-04 (tester report 01:32: with it the heat vision
        # eyes and the basic attacks' streaks never went away, and the punch sound, the Q explosion and the wing glow
        # still missing; 0x11F stops softly, 0x52D790 with x = 0, while the 0x8D's stop-all ends at once): back to
        # "0x8D" (anim-23, held runs ride along); "0x2073" = the anim-25 experiment
        "scriptlet_orders_event": "0x8D",
        # 2026-11-02 (tester report 2026-11-02 01:43: Atomic Joker's passive did not start when a turret killed him): a
        # type-0 defeat guard (0x10000162) also stops the direct hits of turrets / minions / bosses / objectives
        # (World.damage) and raises 0x1000011B, as script damage does (false = only script damage, as before)
        "defeat_guard_all_damage": True,
        # 2026-10-29 tester report 2026-10-29 14:40 (R: the first pulse fires at once, the detonation is hardly seen;
        # docs/re-notes/agl-qer-lift.md 3, C log 14:28:21.105-.239 + original video 61.0-66.0 s: pulses ~1 s apart, the
        # first ~1 s after the impact): in these status scripts a timer the update chain tests before it was ever started
        # starts at that first test with the duration of the script's own StartTimer of the same variable (Meltdown's
        # PulseTimer = PulseDuration), instead of counting as expired. [] = unset timers expire at once everywhere
        "status_timer_first_wait": ["0x340002BF"],
        # 2026-10-29 tester report 2026-10-29 14:40 (R: "the target is not slowed"; agl-qer-lift.md 3.3, C traffic
        # 14:28:21.233: the -0.4 move-speed modifier reached the client but the walking bot kept the speed of its last
        # movement state): a move-speed change on a walking entity sends its movement state at once with the new speed.
        # false = the next throttled update carries it (up to 1 s later)
        "slow_motion_update": True,
        # flag attributes the original server set by unit role (Teleport T4 reads 0x10000B4A on the ally, C; P minions)
        "validate_protector_icons": True,      # 0x2093: only icons of record 0x48000803 (profile-icons.md, C)
        "champion_min_level": 5,               # 0x209D level floor: Stolen Power versions unlock at 5 (0x10000922, P)
        "role_flag_attributes": {"0x10000B4A": ["minion"]},
        # 2026-10-25 (map-objectives-recipes.md 4 / 6 gap 5, C): jungle and boss units run their own entity scripts
        # (drops on 0x10000007 {KillerIID}, start on 0x10000149); roles whose units do
        "run_jungle_scripts": True,
        "run_jungle_scripts_roles": ["camp", "boss"],
        "raise_event_self_deferred": True,
        "tether_return": True,
        # 2026-10-25 22:07 (tester: Grab's arm is never seen): a tether with no hit retracts to its shooter before it
        # ends, instead of vanishing at the end of its range after 0.4 s
        "tether_retract": True,
        # 2026-10-26 (grab-arm-carry.md 1, C: the return leg failed the range check and ended at once): a returning tether
        # flies back to its shooter however far it has flown
        "tether_return_unlimited": True,
        # 2026-10-26: Grab's arm beam at once. 2026-10-30 tester report 15:30 (R: "sometimes the projectile's animation is
        # lost"; docs/re-notes/agl-r-impact-q-e.md 3.1, C traffic 11:22:32.685-.792: Meltdown's orb 0x40000484 hit an
        # adjacent target 85 ms after its creation, before its Vfx_Active (0.1 s) went, so it flew with no effect): the
        # orb's Vfx_Active at once too. Remove the "0x40000484" entry = 0.1 s as before
        "spawned_effect_delays_by_class": {"0x40000485": {"Vfx_Active": 0.0}, "0x40000484": {"Vfx_Active": 0.0}},
        # 2026-10-30 tester report 15:30 (R: "sometimes only one impact and it disappears"; agl-r-impact-q-e.md 3.2, C
        # traffic: every Meltdown orb was removed ~20 ms after its Vfx_OnCollision 0x10000016 although its script
        # 0x340002BE ends with DestroyEntity(SELF, 0.5 s), so the impact effect on the orb was cut): missile scripts whose
        # own delayed DestroyEntity removes a homing missile that reached its target (fallback 2 s). [] = removed at once
        "missile_destroy_delay_scripts": ["0x340002BE"],
        # 2026-10-30 tester report 15:30 (R "should only be castable on enemy champions"; agl-r-impact-q-e.md 3.3): a
        # unit-target order of these skills ("skill set:slot") is refused (error 0x1000003C Skill_InvalidTarget) unless
        # the target's kind flags share a bit with the mask (8 = Character). P: the client's own filter for Meltdown is
        # the default 0x450109 (champions, minions, neutral bosses; C 0x85F97C, no 0x1000068D in the slot block), so
        # this is the tester's rule, not the data's. {} = the data's filter only
        # 2026-10-30 (tester, later: "I was wrong, Meltdown can be cast on minions too; if the minion / champion dies it
        # jumps to the nearest enemy for the remaining hits"): {} = the data's own filter (champions, minions, bosses)
        "cast_target_kind_mask": {},
        # 2026-10-25 23:22 (tester: the game closed after killing the middle camp; diag: access violation the moment the
        # jungle heavy drop took damage / a status icon): drops and pads spawned by scripts are inert objects
        "spawned_inert_classes": ["0x400005E1", "0x40000C49"],
        # 2026-10-29 tester report 19:55 (the game froze and closed; diag: access violation at rva 0x6B1BD9 = 0xAB1BD9 in
        # the 0x42 vitals handler 0xAB2880 -> 0xAB1BD0 with [entity+0x80] = 0, right after Arcane Supergirl's Firewall
        # 0x40000BEF took AGL's Scorched Earth and got "vitals 0/1"): the client builds the vitals / floaty / status icon
        # components only for PerceivedType 0x1000019D & 0x7F59FB (full-entities-engine.md 4); 0x42 and status icons go
        # only to objects whose template or creation bundle has such a PerceivedType (false = by client_vitals as before)
        "vitals_need_perceived_type": True,
        # same report: a spawned skill object with health but no attack and no client vitals component (the Firewall)
        # becomes an inert prop, not hit or killed (false = hittable, health kept server-side only)
        "spawned_need_vitals_component": True,
        # tester report 2026-10-29 15:30 (the jungle camps "leave icons like a reward that they should not leave"): the
        # Heavy Tripod's death script 0x3400007D spawns the heavy drop 0x400005E1 (template: icon 0x10000083 0x130006D3,
        # minimap category 0x100004DA 5, world state 0x2E000FBB = loot tables _Upgrade_Loot / Vfx_Item_*; no script
        # of its own), which nothing ever collected or removed, so its icon stayed on the ground and the minimap. The
        # original Clash recording shows only "+credits" pops and wreckage there. Classes listed here are not spawned by
        # SpawnEntity (logged). [] = spawned as before
        "spawned_skip_classes": ["0x400005E1"],
        # 2026-10-26 14:48 (tester: a red lantern follows the champion: Zatanna's companion had no team): script-spawned
        # objects carry their creator's team (bundle + change)
        "spawned_entity_team": True,
        # 2026-10-26 (tester: buying an item must change the stats: attack speed, lifesteal, damage, armor, regen...;
        # measured headless): the item attributes a champion record does not hold start at 0, not at World.attribute's
        # 1.0 fallback (lifesteal, CDR, resilience, crit chance, penetration)
        "attribute_zero_defaults": ["0x10000B7C", "0x10000B7F", "0x10000B7B", "0x100004AA", "0x10000B46",
                                    "0x10000B83", "0x10000B7E", "0x10000B7D", "0x10000B82"],
        # 2026-10-26 (measured: +50 attack damage / +50 % attack speed changed nothing in the attacks): a skill whose
        # owner's stats changed (item, level) reloads its stats (0x10000008) at its next use
        "stats_reinit_skills": True,
        # 2026-10-26 (deep-scan-animations.md 3, C: speed-bound attack clips play at the attack speed): their hook times
        # are scaled by the clip's speed / attacks per second
        "hooks_attack_speed": True,
        # 2026-10-26 (tester: Bat Scream cast while moving slides the champion; it should stay put): while a skill (not the
        # basic attack) is in its cast, move orders wait and the last one runs at the cast's end
        "cast_holds_movement": True,
        # 2026-11-04 (tester report 00:56: he walks before the basic attack's animation ends; the graph's attack states
        # have no movement early-out, their Cosmetic tails do): a move ordered while the graph is in the basic attack's
        # state waits for its exit (P; false = moves at once, as before)
        "basic_attack_holds_movement": True,
        # 2026-11-04 (tester report 00:56: he shoots with his back to the target): a champion's attack step no longer
        # turns him on the server first; his basic attack script's FaceTarget does, and sends it (false = as before)
        "attack_face_by_script": True,
        # 2026-10-26 (deep-scan-s2c.md 1, C: floating damage / heal numbers and the shield layer come only from 0x42's
        # third / second lists, which were always empty): damage and heals queued per target, sent with its next vitals
        "vitals_floaty_numbers": True,
        "vitals_shield_layer": True,
        # CC attribute -> floaty status type (deep-scan-s2c.md 2: 1 Silence, 2 Stun, 5 Slow, 10 Root, 16 Crippled; map P)
        # 2026-11-03 (tester report 2026-11-03 00:32, from the original game: "Slow" / "Root" / "Wounded" show only over
        # the player's own champion; ics showed them over every champion hit): the CC floaty goes for the local
        # champion only (false = every entity, as before)
        "cc_floaty_local_only": True,
        "cc_floaty_status": {"0x100003F3": 2, "0x100005A3": 1, "0x100007FE": 10, "0x10000B39": 16, "0x100005E4": 5},
        # 2026-10-26 (deep-scan-s2c.md 3: _Advancement_LevelUp 0x10000201 was never sent): the level-up effect
        "level_up_scriptlet": 0x10000201,
        # 2026-10-26 (tester: Bat Scream's scaling looks off; measured: 0.9 x bonus attack damage read 0): the items' part
        # of a stat counts as bonus (GetAttribute mode 1), not as base (mode 2)
        "item_bonus_split": True,
        "cooldown_reduction_cap": 0.4,         # skills' cooldowns x (1 - CDR) (0 = off; the cap is G)
        "resilience_cap": 0.6,                 # an enemy's status on a champion lasts x (1 - resilience) (0 = off)
        # 2026-10-25 23:45 (tester: a tour over the map's elements to name what does not load): /tour in the match chat
        "tour_command": True,
        "tour_lane_step": 12.0,                # m between lane stops (0 = only objects and camps)
        "tour_group_radius": 3.0,              # objects within this many m are one stop
        "tour_stand_off": 2.5,                 # m south of the stop where the champion stands
        # 2026-10-26 13:00 (tester: the tour only moves the champion; show the elements one by one as the old server's
        # tour did with Batman's actions): "vitrina" in the chat creates each placeable world state of the map's packs
        # (creation types below) 5 m in front of the champion, the previous one removed
        "showroom_creation_types": [3, 7, 8, 9],
        "showroom_prefetch": True,             # 2026-10-26 14:49: the list read in a background thread (it froze 28 s)
        # 2026-10-26 16:18 (tester: "disconnected" for seconds while the match loaded): the thread starts this many match
        # seconds after the start and pauses after each record; the list is kept for later matches on the map
        "showroom_prefetch_delay": 30.0,
        "showroom_prefetch_pause": 0.03,
        # 2026-10-26 14:50 (diag --create: a carrier vehicle crashed on a null destruction record): "vitrina N pK" sends
        # the world state's own destruction record 0x800
        "carrier_destruction_record": True,
        # 2026-10-26 15:54 (tester: the carrier vehicle no longer crashes but does not draw): the carrier object in the
        # layout's cell 0xFB and sent again 1 s / 3 s later, as Tutorial 1's carrier props that showed
        "carrier_cell": 0xFB,
        "carrier_resend": [1.0, 3.0],
        "showroom_packs": {},                  # map key -> packs (default: the encounter's own packs)
        "showroom_distance": 5.0,
        "showroom_scriptlets": ["Vfx_Startup", "Object_Closed", "Vfx_Active"],
        # 2026-10-25 22:07 (tester: Grab does not pull enemy champions): each drag step of a bot champion bumps its
        # teleport sequence so the client places it
        "pulled_champion_snaps": True,
        "tether_drag": True,
        # 2026-10-25 11:30 (tester: Grab's hit swaps the drone and AGL): AttachEntity of a missile attaches the missile,
        # not its shooter.
        "attach_missile_itself": True,
        # 2026-10-25 (tester: animations still missing; champion-animation-matrix.md, C client facts): cast_stop_state = a
        # stop state before a champion's cast (the client kept replaying the walk: Propel > 0 ends skill states);
        # graph_hook_offset = s added to the champion's hook times (its graph event and states arrive later);
        # keep_cosmetic_tail = s during which a script's skill_to_locomotion after a cosmetic-leaving state is dropped;
        # attach_parent_first = AttachEntity is (parent, child).
        "cast_stop_state": True,
        "graph_hook_offset": 0.13,
        "keep_cosmetic_tail": 0.8,
        "attach_parent_first": True,
        "graph_cast_timing": True,
        "graph_exit_fallback": 3.0,
        # 2026-10-27 (tester's logs 2026-10-26: Zod R cut mid-channel by a timed code 2, Katana's Thousand Cuts and 20
        # multi-state basic attacks on fixed timings, Batflight ending late; skill-execution-model.md 6): graph_runtime =
        # each champion (local and bots) runs its own behaviour graph on the server (ics/graph.py, data from
        # tools/skill_graphs.py -> data/skill_graphs.json) and the skill scripts get their cast signals (0x1000000F)
        # from its hooks: code 2 when the graph leaves the skill's state (its own end, a gate, CC, death, another
        # skill), stage hooks only once the stage is entered, clip times scaled by attack speed where bound. False =
        # the timed signals above (graph_cast_timing / graph_hook_offset / graph_exit_fallback / cast_waits_tether).
        # graph_start_grace = s the graph has to enter the casting script's state before the timed signals run anyway
        # (a start event ics does not raise); graph_clip_seconds = assumed clip length for end-relative triggers (clip
        # durations are not in the data, 6.4); graph_state_timeout = s with no transition / trigger inside a hooked
        # skill state before the graph goes back to its start state (0 = never; for a gate whose raiser ics lacks, e.g.
        # Grapple Bolt's missile events); graph_fast_forward = a gate the state cannot take yet completes a pending
        # estimated self-transition first; graph_lua_early_out = moving fires the active states' Lua early-outs.
        # 2026-10-28 (skill-execution-model.md; validation: suites identical, champion_check 0 slots worse / 17 better,
        # sequence OK 440 -> 518): on for the tester's next build (false = the timed signals as before)
        "graph_runtime": True,
        "graph_start_grace": 0.15,
        "graph_clip_seconds": 0.5,
        "graph_state_timeout": 5.0,
        "graph_fast_forward": True,
        "graph_lua_early_out": True,
        # graph_self_debounce = s in which the event that just entered a state does not re-enter it (2026-10-27,
        # champion_check: Mecha Superman's W raises Sunstone_Erruption and runs a scriptlet raising it again in the same
        # tick; the self-transition sent code 2 at once and ended the skill).
        "graph_self_debounce": 0.05,
        # tester report 2026-10-29 12:45 (AGL's skill animations still incomplete, "and every champion's";
        # docs/re-notes/skill-animations-vs-original.md 2). graph_feed_at_send = the server's copy of the local champion's
        # graph is fed when the 0x8D goes to the client (champion_scriptlet_delay later), not when the script runs it:
        # the hooks ran 0.13-0.17 s ahead of the client's clip (Meltdown's missile created before the client got
        # Meltdown_Start; false = fed at once as in fase3-ig). graph_cosmetic_tail = a script's skill_to_locomotion
        # (0x10000002) is dropped while the graph plays the _Cosmetic tail its skill state handed over to (Meltdown's
        # throw was cut 0.18 s into its 1.0 s clip; false = the event goes and cuts it). graph_cosmetic_hold = s that tail
        # is held when its clip length is not in the data (0 = off).
        "graph_feed_at_send": True,
        "graph_cosmetic_tail": True,
        "graph_cosmetic_hold": 0.8,
        # champion_stop_deferred = the local champion's scriptlet stops (StopScriptletKey) wait champion_scriptlet_delay
        # like its starts (Scorched Earth's smash VFX was stopped 2 ms after it started on the client; false = at once).
        "champion_stop_deferred": True,
        # graph_missile_release = s after every missile of a cast is gone before the graph leaves the script's state when
        # nothing else ends it (2026-10-27, champion_check: Grapple Bolt waited 5 s for its missile script's 0x10000140,
        # which ics does not deliver when the bolt ends; 0 = off).
        "graph_missile_release": 0.5,
        # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Green Arrow's Bullseye
        # cancelled itself in the tick it started): a graph hook raised while a script instance runs a state's chain is
        # delivered once that chain has run (the client's graph answers on its own update), not in the middle of it.
        "defer_graph_hooks_in_chain": True,
        # 2026-10-28 (same report; Green Arrow's Bullseye arrow hit for 5e-31): RaiseEvent's slot 3 number reaches the
        # receiver as parameter 0xD358722 (Damage, BonusShield, HealthDelta of 5 scripts), slot 2 only as Position.
        "raise_event_float_param": True,
        # 2026-10-28 (same report; Bullseye's arrow hit a champion with its minion branch): IsKind bit 0x100 means the
        # non-champion units (0x108 / 0x10108 add champions with bit 8); off = champions match 0x100 too, as before.
        "kind_unit_excludes_champion": True,
        # 2026-10-28 (same report; Bullseye's arrow probes the target with ApplyDamage(0) and hits only on DamageSuccess):
        # a zero ApplyDamage on a live, damageable target reports success (4 scripts); off = 0 damage always fails.
        "zero_damage_probe": True,
        # 2026-10-28 (same report; Dex-Starr's R cat hit a minion and skipped the enemy champion it met one tick later):
        # the once-per-tick guard of a polled transition is lifted when an event moved its graph since it fired.
        "poll_guard_event_reset": True,
        # 2026-10-28 (same report; Mecha Wonder Woman's Tempest box began 5 m past her): a box hotspot (shape 2) is
        # centred on its position (every script that makes one places it at length * 0.5); off = it starts there.
        "hotspot_box_centered": True,
        # 2026-10-28 (same report, with the centred boxes): node 0x10000025 whose operand 3 is a hotspot moves that hotspot
        # to the point (Mecha Wonder Woman's W drags its dash box along); off = the node never moves a hotspot.
        "hotspot_follows_position": True,
        # 2026-10-28 (same report; Mecha Wonder Woman's W dash box stopped 1 m short): a state with an update chain that an
        # event leaves runs that update once more first when it has not run in this tick.
        "update_before_event_exit": True,
        # 2026-10-28 (same report; The Joker's Last Laugh balloon explodes 0.5 s after it lands, but the missile and its
        # script were removed at the landing): s a missile whose script is still busy after its expiry stays (no more
        # hits) until its own DestroyEntity; 0 = removed at the expiry as before.
        "missile_expire_linger": 5.0,
        # 2026-10-28 (same report; Arcane Zatanna's R aura status divides its damage by EffectDuration, which was 0): the
        # status a hotspot holds on the units inside gets the hotspot's remaining time as EffectDuration; off = 0.
        "hotspot_status_duration": True,
        # 2026-10-28 (same report; Arcane Supergirl's R compares its 4294967295 default with the signed constant -1): ==
        # / != on two integers compare their 32 bits; off = Python equality (the R never gets its charges).
        "int_compare_32bit": True,
        # 2026-10-28 (same report; Atomic Wonder Woman's Reclaimer runs at its target with AIMoveTo and strikes on
        # 0x1000009D): AIMoveTo on a champion runs it at the target and raises 0x1000009D when in reach; off = ignored.
        "ai_move_champion": True,
        # 2026-10-28 (same report; Star Sapphire's Predator brain never learnt who its owner was): a top-level graph's own
        # enter chain runs when the script starts (its exit chain when it stops), 69 scripts; off = never run.
        "top_graph_chains": True,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: AGL's R must slow and keep hitting a moving target; its waves
        # stopped and it never slowed; docs/re-notes/meltdown-moving-target.md 6). missile_reaim_from_current = a homing
        # missile re-aimed in mid-flight (SetMissileVelocity) starts from where it is, not from its launch point (the orb
        # landed 4.9 s late on a still target, never on a walking one; false = from the launch point).
        # status_acts_for_source = a status acts for its applier: FindTargets' relation side, ApplyDamage's unset source
        # (credit, K/D/A), DoTs, the statuses it applies, its auras' side and a new missile's shooter (from the status'
        # owner) (Meltdown hit AGL's side, credited the victim, and its jump missile was the victim's; false = the
        # victim). status_skill_hit_event = the damage of a status a champion's Q/W/E/R applied raises that skill hit
        # 0x1000008A on him after the current chain (only nodes that trigger on-hit effects; AGL's passive stacks Rads
        # and Radiation Sickness slows -40 %). event_loop_per_target = the 20 ms event loop guard counts per event
        # target (the 5th unit hit by one pulse got no stack). status_self_remove_after_chain = a status that removes
        # itself does so after the rest of its chain (Meltdown's jump decrements the pulses left: 6 in all, not 7).
        "missile_reaim_from_current": True,
        "status_acts_for_source": True,
        "status_skill_hit_event": True,
        "event_loop_per_target": True,
        "status_self_remove_after_chain": True,
        # 2026-10-27 (skill-execution-model.md 0.7 / 6.5, C: the client VM drops events not in the record's accept list,
        # 0x461430, and every list equals its triggers' events): an instance only gets the events its record accepts.
        "script_accept_filter": True,
        "script_owner_block": True,
        "spend_by_vital": True,
        "champion_resource_from_data": True,
        "basic_hit_event": True,
        # 2026-10-25 (kit audit, docs/re-notes/kit-audit-1.md): skill_hit_event = a Q/W/E/R hit raises 0x1000008A on the
        # attacker (7 champions' passives); owner_damaged_event = damage raises 0x100000ED on the victim (6 champions).
        "skill_hit_event": True,
        "owner_damaged_event": True,
        # 2026-10-25 (kit-audit-2.md): skill_used_broadcast = a Q/W/E/R use raises 0x10000196 {Slot} on the owner's scripts;
        # carried_arrive_collision = a launched entity collides at its target; death_script_events = 0x10000012 /
        # 0x10000007 on the dead entity and its statuses, 0x10000098 on the killer.
        "skill_used_broadcast": True,
        "carried_arrive_collision": True,
        "death_script_events": True,
        # 2026-10-30 (tester: Meltdown may be cast on minions too, and when its target dies the remaining hits go on the
        # nearest enemy; docs/re-notes/agl-r-impact-q-e.md 3.5): the data already does it (status 0x340002BF's exit
        # chain: NOT IsAlive(SELF) -> the jump search within JumpRange 4 m + LaunchMissile 0x40000484). When the death
        # comes from one of the status' own nodes (a Meltdown pulse that kills its target), that status gets 0x10000007
        # and ends once its current chain has run, as the client VM queues events: the pulse's own PulsesRemaining - 1
        # is counted first, so the next target gets only the pulses left (it got one too many). False = at once.
        "death_status_end_after_chain": True,
        # 2026-10-25 (kit-audit-3.md): predicate_first_in_conditions = HasFlagAttribute 0x1000006A is a predicate inside
        # AnyOf / NOT / triggers (it ran as the missile Mark action: always true; 40 scripts); damage_pipeline_events =
        # 0x1000008C when a shield drains, 0x1000011B when a defeat guard stops a lethal hit (Nightmare Superman /
        # Grundy could not die); any_reenter_on_code = a polled "any -> X" also re-enters X on a result code (false =
        # not: Starro sent ~700 scriptlets every 3 s).
        "predicate_first_in_conditions": True,
        "damage_pipeline_events": True,
        "any_reenter_on_code": False,
        "cast_waits_tether": 4.0,
        # 2026-10-23 23:40 (same report: no crater, no Grab arm, no Meltdown marker): missiles and spawned skill objects
        # (Grab 0x40000485, Meltdown 0x40000484, Scorched Earth's crater 0x40000487) were sent as bare classes; they now
        # carry their world state's 0x7D2 tables, and these effect keys of theirs are played (a spawned object only
        # when it has no script of its own).
        "spawned_object_tables": True,
        # 2026-10-25 (agl-visuals.md 2, C): a crater's Vfx_OnInit schedules its own Vfx_OnExplode 1.5 s later (timed group
        # in table 0x1D0003D8); sending OnExplode too made the blast early: only Vfx_Active / Vfx_OnInit now.
        "spawned_effect_scriptlets": ["Vfx_Active", "Vfx_OnInit"],
        # 2026-10-25 10:40 (tester: the crater explodes before it shows): Vfx_OnExplode 1 s after the object appears.
        "spawned_effect_delays": {"Vfx_OnExplode": 1.0},
        # scriptless skill objects removed after s (Fizzle, then 0x3): Scorched Earth's crater 0x40000487.
        "scriptless_spawn_lifetime": {"0x40000487": 3.0},
        # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"): scriptless skill objects whose damage
        # nothing in the decoded data deals (P, a stand-in until their class records are decoded): after the spawning
        # skill's stat delay_stat s, hostile units within stat radius_stat m take stat damage_stat. Green Lantern's Light
        # 0x40000359 (175 + 125/rank, 3.5 m, 1 s), Nightmare Catwoman's Inevitability 0x40000D2B (100 + 50/rank, 4 m, 2 s).
        "scriptless_spawn_blast": {"0x40000359": {"damage_stat": 5, "radius_stat": 18, "delay_stat": 14},
                                   "0x40000D2B": {"damage_stat": 5, "radius_stat": 18, "delay_stat": 14}},
        # missiles and spawned objects carry their creator 0x100004E2 (the beam end of tethers / lassos, agl-visuals.md 1)
        "missile_creator_property": True,
        # scriptlet key -> {variable: minimum}: Shards of Will's sphere shells gate on 0x1000033E (agl-visuals.md 3, P).
        "scriptlet_variable_floors": {"0x10000886": {"0x1000033E": 0.01}, "0x1000088C": {"0x1000033E": 0.01}},
        # 2026-10-25 11:00 (tester: no Shards of Will sphere; dialog-shield-disconnect.md 2, P): scriptlet key -> extra s
        # (Shards_Active after Shards_Start, which replaced it when both came in one tick).
        "scriptlet_delays": {"0x10000886": 0.15},
        # 2026-10-25 (stubborn-visuals.md 2, P: Shards_Start chains Shards_Active itself; the extra copy replaced the
        # first and dropped the sphere): key -> chaining key; ours is dropped when the chaining key just ran. {} = off
        # 2026-10-25 22:07 (diag --escudo, C: after Shards_Start the 0x17 run of 0x10000886 ends at once, flags 0x28000000,
        # and the sphere 0x2E000C89 is never spawned (no 0x0C execute for it): Start does not reach Active): ours is sent
        "scriptlet_chained": {},
        # 2026-10-25 23:13 (tester: the sphere shows now but goes before the shield ends; agl-e-r.md 1.5.1): Shards_Active
        # again every 1 s until Shards_Stop 0x1000088B (at most 10 s). key -> [interval s, stop key, max s]; {} = off
        "scriptlet_restart": {"0x10000886": [1.0, "0x1000088B", 10.0]},
        # 2026-10-28 09:36 (tester: the shield sphere vanishes while the champion attacks and comes back after): every
        # basic attack's facing bundle re-creates the champion and drops the sphere; a scriptlet_restart key still running
        # goes again resend_looping_delay s after any bundle of its object
        # 2026-10-28 10:35 (tester: the match froze after an error in the stealth reveal): mode-layer tick errors are
        # logged with a traceback; the layer stops only after this many (0 = at the first, as before)
        "mode_error_limit": 50,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 3 / 6.1, C: a bundle drops no run,
        # this starts a second one beside it): with object_update_mode "delta" it follows only the remaining full bundles
        # (creation, retries, life changes, array / table changes), so it is nearly inert; kept for "bundle"
        "resend_looping_after_bundle": True,
        # 2026-10-28 09:36 (tester: Grab pulls, but AGL's stretched arm is missing; grab-beam.md, C): a moving missile got a
        # full bundle every tick, which re-created it and dropped its Vfx_Active beam (the arm's particles). Now a bundle
        # goes only when its heading turns by missile_turn_radians or it stops, and these keys play again after it.
        # false = a bundle every tick as before
        # 2026-10-28 15:00 (object-update-bundles.md 6.1; grab-beam.md ranks the bundle only as a P suspect): with
        # object_update_mode "delta" the turn goes as a motion-only state and missile_rebundle_scriptlets is not played
        # (it would start a second beam); the throttle stays
        "missile_bundle_on_turn": True,
        "missile_turn_radians": 0.12,
        # 2026-10-29 11:00 (tester: Grab shows only a projectile, not the arm; agl-grab-arm.md 3.4, C traffic 10:51:12: the
        # Grab missile got Vfx_Active three times in 0.43 s, at creation and after each turn bundle; a bundle drops no run,
        # so every replay stacked another beam + streak on the same missile): no replay in "bundle" mode either.
        # ["Vfx_Active"] = as before
        "missile_rebundle_scriptlets": [],
        "resend_looping_delay": 0.05,
        # 2026-10-28 10:19 (tester: the shield still vanishes when attacking): no facing bundle for a standing champion
        # already within this many degrees of its target (0 = a bundle on every FaceTarget as before)
        "face_min_turn_degrees": 20.0,
        # 2026-11-02 (tester report 2026-11-02 01:48: Blue Beetle's E goes facing the dash; its script 0x34000455 faces
        # the point behind his start and frees it with ReleaseFacing at the landing): FaceTarget with an out handle holds
        # the model's yaw on its target until ReleaseFacing 0x10000057; while moving only the model turns
        # (facing_offset), and the scripts' facing (FindTargets' box) is the model's. false = one turn, as before
        "facing_locks": True,
        "facing_lock_max_seconds": 6.0,   # a lock nobody frees runs out (safety; 0 = never)
        # 2026-11-02 (same report: Blue Beetle's E shots never left; 0x34000455 asks CanSee(-, $LoopingIID)): CanSee
        # 0x1000003C with an unset observer looks from SELF (false = never sees, as before)
        "can_see_default_self": True,
        # 2026-11-02 (tester report 2026-11-02: AGL's Q teleport, Superman's E punch and Blue Beetle's W detonation
        # waited for a click instead of the key; Blue Beetle's Infiltrator Mode kept the ranged buttons): SetSlotSkill
        # 0x10000089 and SetSkillStatOverride 0x100000FA (name / description / icon / targeting type) change the local
        # champion's slot table (0x100008E3 / E8 / EA / EC / E6) the HUD reads; ClearSkillStatOverride puts it back
        # (ics/skill_slots.py). false = server only, as before
        "slot_tables": True,
        # 2026-11-03 (tester: the swapped buttons were drawn only when the slot's cooldown ended; P): a slot table change
        # also toggles the rank property the HUD re-reads (false = the table alone)
        "slot_table_hud_refresh": True,
        # 2026-11-03 (tester report 23:26: after R the buttons still waited ~2-3 s; six slot refreshes toggled the rank
        # property six times, back to its value): one toggle when the tables stop changing (false = per slot, anim-19)
        "slot_table_hud_refresh_once": True,
        "slot_table_hud_refresh_delay": 0.1,   # s after the last table change (P: our value)
        # 2026-10-28 13:5x (tester: an emote while moving slides the champion to the point): the emote stops the champion
        "emote_stops_movement": True,
        # 2026-10-28 13:52 (tester: back in the lobby after a match the champions, the last played champion and its
        # background did not load): the menu refresh after a match also re-sends 0x20B8, 0x209D, 0x2081 and 0x214B
        "menu_refresh_account_data": True,
        # 2026-10-28 12:27 (tester: the shield still disappears when attacking): a running scriptlet_restart key (the Shards
        # sphere) goes again this many s after any other scriptlet on the same object (0 = off)
        "resend_looping_after_scriptlet": 0.35,
        # 2026-10-29 tester report 2026-10-29 14:40 (AGL's E sphere never shows its whole animation; docs/re-notes/
        # agl-qer-lift.md 2, C traffic 14:22:44-49: Shards_Active 0x10000886 went 7 times in 5 s, each with a NEW run
        # number, and the client starts a new run (a new shard burst) for every unknown run number; client-scriptlets-
        # graphs.md 1.2 step 4, C: an 0x8D whose run number is alive on the object is only a signal to that run): every
        # re-send of a looping key (scriptlet_restart, resend_looping_after_bundle / _after_scriptlet, the camps'
        # phase-in) reuses the run number of the key's last start, so it does nothing while the run lives and restarts
        # it only when the client ended it. false = a new run number per re-send (fase3-ih)
        "looping_resend_same_run": True,
        # 2026-10-28 12:5x (tester: Grab does not always catch the enemy champion): a missile hits when its line passes
        # within its width + the target's body radius (by kind; minions / structures use their own radius); {} = centre
        "missile_target_radius": {"champion": 0.6, "unit": 0.5},
        # 2026-10-29 11:00 (tester: Grab pulls minions but never the enemy champion; agl-grab-arm.md 2, C: the bot Robin's
        # Vault Kick ends with DisableCollision, which left him out of every missile's collision for the rest of the
        # match, and every Grab hit's DisableCollision landed on AGL, the shooter): DisableCollision / EnableCollision act
        # on the script's own entity (the missile for a missile script) ...
        "collision_toggle_own_entity": True,
        # ... and keep the client's holder list (0x976990): a run's Disable removes only its own Enable; champions, units,
        # structures and props stay in collision by their template (P). false = one flag, the last toggle wins (as before)
        "collision_holders": True,
        # 2026-10-29 11:00 (same report; agl-grab-arm.md 2.3, P): IsMoving 0x100000E1 with r1 = 0 is a forced movement only
        # (knockback / dash / pull), r1 = 1 walking too; Grab pulls only a target that is not IsMoving[0], so a walking
        # champion got damage and no pull. false = r1 0 walking only, r1 1 walking or forced (as before)
        "is_moving_flag_walks": True,
        # 2026-10-28 (tester: attacking an enemy champion must turn its towers and minions on the attacker): they re-think
        # at once (not at their next retarget); a missile's / spawned object's champion counts as the attacker
        "match_call_for_help_now": True,
        "missile_own_return_event": True,
        "attached_skill_events": True,
        "stop_scriptlet_signal": 1,
        "emotes": True,
        # 2026-10-24 00:40 (tester: Alt+Numpad emotes did nothing for any champion, no 0x9F arrived): /dance /joke /laugh
        # /taunt /oath (also bailar broma reir provocar juramento) typed in the match chat play the emote.
        "emote_chat_commands": True,
        # 2026-10-24 23:20 (tester: the Recommended panel should disappear once the recommended starting item is
        # bought): 0x2078 is re-sent after every purchase without the items the champion holds.
        "recommended_follow_inventory": True,
        # 2026-10-25 (tester's video compare: the original Crime Alley is darker and bluer; map-loading-deep-scan.md 3):
        # lighting key 0x956 per encounter (region table 0x04000000): 0x10000002 -> Crime Alley's outdoor environment
        # 0x08000003; everything else keeps the cinematic 0x10000016 sent so far. Never 0 (fase3-cf: black scene).
        # 2026-10-25 09:00 (tester: fog drawn in Crime Alley now, the other maps almost black): each map's own key from
        # its victory script (map-loading-deep-scan.md 1): Coast City 0x1000001B -> 0x0800001B (pack 0xA00000D2),
        # Gotham Divided 0x1000001C -> 0x0800001C (0xA00000FC), Gotham Heights 0x1000000A -> 0x08000008 (of A/B/D).
        "lighting_env": {"0x40000C82": 0x10000002, "0x40000CA6": 0x10000002, "0x40000E68": 0x10000002,
                         "0x40000E74": 0x10000002,
                         "0x40000270": 0x1000001B, "0x4000039C": 0x1000001B, "0x40000B6A": 0x1000001B,
                         "0x40000399": 0x1000001C, "0x40000B6B": 0x1000001C, "0x40000E62": 0x1000001C,
                         # Gotham Heights: its cannon script sets 0x1000000D at the start (env 0x0800000A), 0x1000000B
                         # for the final charge, 0x1000000A after it (map-gaps-gotham-heights.md 5, P)
                         "0x4000013E": 0x1000000D, "0x40000B6C": 0x1000000D, "default": 0x10000016},
        # 2026-10-24 00:55 (tester: the match closed as soon as an emote arrived, a bug in its handler): an error in a
        # client event handler is logged and the connection stays up (false = the old behaviour: the connection closes).
        "handler_errors_keep_connection": True,
        # 2026-10-25 (tester: the player profile icons cannot be customized; profile-icons.md): the 134 protector icons of
        # record 0x48000803 go in 0x20B8 (type 3); own_all_icons = all choosable (false: locked unless owned).
        # 2026-10-25 (stolen-powers-audit.md 1: 50 of 65 Stolen Power versions had no damage / range / cooldown): a
        # version's stat list is merged into its base power's stat by stat instead of replacing it.
        "stolen_stat_merge": True,
        # 2026-10-25 (skin-overlay-fix.md 3, C): an object bundle's descriptor u32 after the class is a world-state override
        # (compared with entity+0x110, ChangeWorldState 0x54D5C0 when different), not a sequence; 0 now (false = the old
        # counter 1, 2, 3 ... that asked for a world-state switch on every bundle; P: may also have cut animations).
        # 2026-10-28 (object-update-bundles.md 0.4 / 11): it must stay true; the update path below sends no 0xF2 at all.
        "descriptor_world_state_zero": True,
        # ---- 2026-10-28 15:00 (tester report 2026-10-28 15:00: animations cut by the object updates; docs/re-notes/
        # object-update-bundles.md 3 / 7 / 10-13, C): how an object the client already has is updated. A full bundle
        # (0x4 = 0xF2 + 0xB0 + 0xBC) re-creates nothing, but its 0xBC is a diff that REMOVES every own id of network mode
        # 1 / 3 it leaves out (0x62AFD0): the unit flags 0x1000019D, tags 0x10000029 / 0x10000249, CC flags 0x100003F3 /
        # 0x100007FE / 0x10000B39 / 0x100005A3, the order lock 0x10000B2D and the turret target 0x10000C66 that ics sets by
        # 0x6 only (champion, bots, CC'd units, turrets). "delta" = after an object's creation bundle, its movement goes as
        # 0x4 batches with only the 0xB0 (at the cadence each path had), each changed property by 0x6 and each net-1/3 id
        # that left its list by 0x86 (World.delta); "bundle" = a full bundle per update, the champion's with the player
        # object and 0x42, as in fase3-ie.
        # 2026-10-29 10:28 (tester, first game run of "delta": enemy drones and champions in sight stayed invisible yet
        # could hit and be hit; on a 5v5 map the champion stopped moving after a few seconds, then the game closed at
        # exit): back to "bundle" until the delta path is checked against the client; "delta" stays available
        "object_update_mode": "bundle",
        # delta: 0x86 for an id of network mode 1 / 3 (the client's MasterProperty 0x32000000, read from the install) that
        # left the object's list, i.e. what a full bundle removed; false = left on the client (as a net-0 id)
        "delta_remove_missing": True,
        # delta: also 0x86 for a net-0 id that left the list (a sold item's 0x100008E5.., the pad's 0x100008F2, 0x90F): a
        # full bundle left those on the client, so this would be a new HUD path (P); false = left, as a bundle did
        "delta_remove_net0": False,
        # delta: an update in which an array / table changed (the rank array 0x100000AF, the Stolen Power / item / pad
        # tables, 0x7D2) goes as a full bundle, followed for the champion by vital_notices_on: those values have only
        # ever reached the client in bundles (a 0x6 reads its value with the same entry reader 0x509740 as the 0xBC
        # table, C, but ics never sent one); false = by 0x6 too (no full bundle after the creation at all)
        "delta_complex_as_bundle": True,
        # delta: the champion's and the bots' death and respawn stay full bundles (11.3: the grey screen and the
        # respawn snap with the delta form are untested); false = deltas there too (LifeState by 0x6, the stop / the
        # teleport as a motion-only state)
        "delta_full_on_life_change": True,
        # delta: the first update in the world of an object last sent while the client loaded (second_seq 0) is a full
        # bundle, as the bots' "(in world)" re-send was; false = a delta
        "delta_full_after_load": True,
        # delta: s after an object's creation bundle during which its updates stay full bundles (12.2.2: an event that
        # reaches an object whose creation is still running may be dropped; a bundle repeats everything). Below
        # unit_flags_delay (0.8 s), the first 0x6-only id; 0 = deltas at once
        "delta_create_window": 0.5,
        # delta: the champion's per-tick update with the player object's bundle (true = as _objects() sent it each tick)
        "delta_player_object": False,
        # delta: the champion's per-tick update with the short 0x42 (true = as before; World.vitals sends each change)
        "delta_vitals_with_motion": False,
        # delta: [timing] idle_resend's full bundle becomes a resync every this many s without any update: the
        # champion's movement state (the client drops one that did not change) and its listed properties by 0x6 (an
        # equal value notifies nothing, 0x578DE0); never a 0xBC. 0 = nothing
        "delta_resync_seconds": 5.0,
        # delta (P, 7): s subtracted from the stamp of a motion-only state that stops or only turns the object (the client
        # applies a state 0.1 s after its stamp, an 0x8D at once), never before the object's previous state; 0 = now
        "motion_state_backdate": 0.0,
        "send_protector_icons": True,
        "own_all_icons": True,
        "default_protector_icon": "0x40000AE3",   # slot 0 for an account without one (0 = none)
        # 2026-10-25 (sweep-c2s.md, P): a networked scriptlet the client asks for on an object it does not own (0x00DA:
        # minions' 0x1000005D / 0x1000006B, 0x100000EB at load) is played by the server on that object (0x8D).
        "remote_scriptlets": True,
        "emote_graph_events": {"0x40000241": "0x1000022E", "0x40000240": "0x1000022C", "0x40000242": "0x1000022D",
                               "0x4000023F": "0x100001F1", "0x40000EE6": "Emote_Oath_Start"},
        # The basic attack's damage is the champion's attack damage attribute (its skill has no stat 5); the
        # champion records' attributes are not read yet (2026-10-21).
        "basic_attack_damage": 40,
        "corpse_seconds": 4.0,
        "respawn_seconds": 5.0,          # the champion comes back at the start after dying
        "spawn_layout": True,            # create the encounter layout's units from the packs
        # Variants created as another one. 2026-10-13 (earlier server): the tutorial's own Soldier Drone 0x40000C72
        # could not be targeted by the client, the generic Soldier Drone 0x40000A5C could; the property that
        # makes 0x40000C72 targetable is not known yet. {} = every unit as the layout says.
        # 2026-10-21: off now that the encounter's variants pack 0xA0000257 is loaded (the client could not target
        # 0x40000C72 when that pack was not sent, which is the likely cause).
        "variant_overrides": {},
        # Units fight with their own attack script (template property 0x10000328); when to attack is not in the
        # data (the original server's AI): the champion within unit_aggro_radius m (2026-10-21, tester: drones idle)
        "unit_ai": True,
        "unit_aggro_radius": 8.0,
        # 2026-10-21 21:46 (tester: Batman walks through buildings): walks follow A* paths on the map pack's NavMesh
        # (ics/navmesh.py); false = straight lines as before
        "pathing": True,
        # Fog of war: the champion as a vision source of this radius (0x10000133; Gaslight Batman's world state
        # has 12.0 in the survey). 0 = not sent.
        "champion_vision_radius": 12.0,
        # Props that block paths (not in the navmesh): world state -> [half length, half width (, angle offset)],
        # the length along the placement's yaw. The earlier server's boxes: street vehicle 4.0 x 1.6, gates 7.0 x
        # 0.5 (2026-10-21 22:52, tester: Batman walks through the first vehicle). A gate stops blocking when it
        # plays Object_Open.
        "prop_blockers": {"0x2E000AAB": [4.0, 1.6], "0x2E0010F3": [7.0, 0.5], "0x2E000CD7": [7.0, 0.5],
                          "0x2E00034D": [3.75, 1.6], "0x2E00034E": [3.75, 1.6]},
        # Enemies farther than this or behind a wall (no clear line on the navmesh) are hidden (0x90F), as the
        # earlier server's fog_of_war (14 m). 0 = off.
        # 2026-10-29 17:45 (tester: "the champions' field of vision must be reduced a little"): 14 -> 12 m (the server's
        # fog and the champion's client vision radius 0x10000133 both read it unless champion_vision_radius is set)
        "fog_vision_radius": 12.0,
        # tester report 2026-10-29 17:45 (black strip between the lane and the fence by the blue turret, a black wedge
        # from AGL to the parked SUV; ca-fog-ring-announcer.md 1, C mechanism, P cause): the fog draw 0xAAE0E0 runs an
        # occluder pass per vision source against map statics with 0x7EB 7 / 8 and entities with 0x10000623 (the
        # liftable vehicles), and on this client it blackens the ground BETWEEN the source and the blocker. true =
        # every allied vision source (champion, allied bots, structures, minions) gets attribute 0x100008CE (the
        # foundries' "vision ignores blockers") by a set modifier, so no occluder pass runs; the server's own fog
        # still hides enemies behind walls. false = as before
        "vision_through_blockers": True,
        # 2026-10-29 (tester report 2026-10-29 18:31: the strip between the lane and the fence is still black;
        # ca-fog-stealth-hover.md 1, C 0x973730 / 0x970B80): the attribute read ignores modifiers when the entity has
        # no base value, and no champion / turret / minion template has 0x100008CE, so the fase3-il modifier did
        # nothing. true = vision_through_blockers also sets the property 0x100008CE = true by 0x6 (the base value the
        # foundries carry in their templates); false = the modifier alone, as in fase3-il
        "vision_through_blockers_property": True,
        # 2026-10-29 (tester report 19:55: the fence strip still black; ca-ring-fog-bundles.md 2, C): 0x100008CE is net 1
        # and no champion / minion template has it, so a full bundle (every tick for a moving object in "bundle" mode)
        # removed the 0x6 base value again. true = it also rides in the object's own bundles (only while
        # vision_through_blockers_property is on); false = by 0x6 only, as fase3-im
        "vision_through_blockers_in_bundle": True,
        # 2026-10-29 (tester report 2026-10-29 21:10: the fence strip is still black; ca-fog-minimap-ring.md 1, C diag
        # --fog 21:04-21:10): AGL's circle now skips the occluder pass (al 1 from 21:05:00), but our core / core turret /
        # inner and lane turrets (0x101 / 0x103 / 0x105 / 0x10B) ran it all match long (al 0, 430 times each) against
        # the map static 0x01113BB0000000B8, although each got 0x100008CE = true by 0x6 at 21:04:58 and was never
        # re-bundled. The foundry, whose TEMPLATE holds the value, skipped it. true = an allied structure's creation
        # bundle carries 0x100008CE = true (merged into the creation desc like a template value, 0x64CA10 -> 0x502B00);
        # false = by 0x6 after creation only, as fase3-in
        "vision_through_blockers_at_creation": True,
        # 2026-10-29 (tester report 2026-10-29 21:10, 78.png: on the original's minimap enemy normal minions and the
        # enemy champion show only inside our team's vision, super minions always; ca-fog-minimap-ring.md 3, C 0xA4BD80
        # / 0xA5B190): the minimap note needs 0x2A1 true and its watcher adds / removes the note on a change; 0x90F only
        # hides the model. true = an enemy (team 1 / 2) unit or champion out of sight also gets 0x2A1 = false, except a
        # unit whose unit flags hold a bit of fog_minimap_always_flags (0x400000 elite: the super minions 0x40000C9C /
        # 0x40000C9B, 0x410000); false = 0x90F only, as fase3-in (every enemy stays on the minimap)
        "fog_hide_minimap": True,
        "fog_minimap_always_flags": 0x400000,
        # 2026-10-30 (tester report 2026-10-30 15:30: enemy minions and the enemy champion still on the minimap out of
        # our vision; ca-fog-minimap-category.md 1, C 0xAAA670 / 0xA6A8E0 / 0xA4C030): 0x2A1 is a client-local id that
        # the client's own visibility evaluator 0xAAA670 rewrites to true for every entity about every 0.4 s, so the
        # server's false was undone and the note came back. How fog_hide_minimap takes the note off: "category" = the
        # minimap note category 0x100004DA (net 1, nothing in the client writes it) = 0 while out of sight (its watcher
        # removes the note, 0xA4C030) and the template's category again in sight (the watcher adds it, 0xA4BD80); 0x2A1
        # is not sent. "on_map" = 0x2A1 = false, as fase3-io
        "fog_minimap_lever": "category",
        # the category put back when the class template has none (by entity kind; 9 = MINION, 2 = champion)
        "fog_minimap_categories": {"unit": 9, "champion": 2},
        # 2026-10-30 (tester report 2026-10-30 15:30: "sometimes the enemy champion inside my champion's or my minions'
        # vision range is not drawn until I am right next to it or it attacks me"; ca-fog-minimap-category.md 2): with
        # vision_through_blockers every allied source draws a full circle on the client (no occluder pass), but the
        # server still hid an enemy whose navmesh line to the source crossed a hole (a building corner at a jungle
        # mouth) until it came within 3 m. false = an enemy inside a source's radius is seen (the circle the client
        # lights), stealth strips still apply; true = the navmesh line is needed too, as before. "auto" = the line only
        # when vision_through_blockers is off (the client then clips its circles at the occluders as well)
        "fog_sight_line": "auto",
        # log every change of an enemy champion's fog state in server.log (positions, nearest source, the reason), so
        # a report like the one above can be matched to the match (false = no lines)
        "fog_log_champions": True,
        # 2026-10-29 (tester report 2026-10-29 18:31: hovering enemy minions / champions draws no outline and several
        # right clicks are needed to attack; ca-fog-stealth-hover.md 3, C traffic): the client's hover pick returned
        # our own champion or an allied minion (107 move orders) or nothing (1 356) next to enemies. A move order whose
        # ground point is within this many metres (by entity kind) of a visible enemy unit / champion, and whose pick
        # was not an enemy, attacks the nearest one. {} = off (every move order moves, as before)
        "click_assist_radius": {"unit": 1.0, "champion": 1.4},
        "fog_allied_vision": True,
        "fog_neutral_by_range": True,          # 2026-10-25 16:12: jungle units in pits were hidden behind the line test
        # 2026-10-23 17:40 (fog-vision-runtime.md): vision radius 0x10000133 (allied units / structures, champion) and the
        # champion's unit flags 0x1000019D = 8 go again as changes by 0x6 after creation
        "vision_as_change": True,
        # 2026-10-25 (tester: black octagon on the dampener, black rectangles on the Gotham Divided gates;
        # stubborn-visuals.md 1, C: their team tint is _Entity_OnSetClientRelationship 0x100003A6, which the client
        # runs only when 0x1000009C CHANGES): structures and base gates get team 0, then their team, by 0x6
        "team_as_change": True,
        # 2026-10-25 (tester: "+" and streaks on the stealth tiles; stubborn-visuals.md 3, P): the hex mesh 0x2E000D37
        # spawned as a prop instead of running Vfx_Active (its particle draws the streaks); 0 = Vfx_Active
        "stealth_tile_direct": "0x2E000D37",
        # 2026-10-23 17:50 (tester: the lane runs diagonally across the screen; the original video shows it straight,
        # blue base left; pvp-camera-yaw.md): champion f32 0x1000011E = camera yaw (degrees) per encounter and team, in
        # its creation and again after load. Crime Alley's intro ends on heading 0; team 2's 180 is a guess.
        "camera_yaw": {"0x40000C82": {"1": 0.0, "2": 180.0}},
        # 2026-10-23 18:00 (tools/champion_check.py over the 54 champions, champion-kits-status.md): script VM / data
        # fixes. RaiseEvent [event, script] reaches only that script (Cyborg's basic attack fired every skill); a missile
        # template's script list is searched past false record starts (25 projectiles got their damage); a cone check
        # without a max range has no distance limit (Katana Q, Superman W...); the champion's scripts get the init
        # event 0x10000088 (Arcane Green Lantern's Lantern; 0 = not); a polled "any -> X" transition does not re-enter
        # X (Starro's scriptlet flood)
        "raise_event_script_target": True,
        "missile_scripts_past_starts": True,
        "range_angle_needs_max": True,
        "champion_init_event": 0x10000088,
        "polled_any_no_reenter": True,
        # 2026-10-23 18:40 (tester: items do not change health / attack speed / damage on the HUD): each item bonus goes
        # to the client as an attribute modifier (0x20F0 op 9 / 10); the server's stats already hold them
        "item_client_modifiers": True,
        "ground_from_navmesh": True,     # 2026-10-23 18:40: walkers take the navmesh's height (they floated up to 0.6 m)
        # 2026-10-30 (tester report 14:51 video: "AGL is very far off the floor"; agl-floor-raider-pad-pct-prow.md 1):
        # the champion's bundles carried z 200.13 -> 201.52 over a 200.08 / 200.15 navmesh, each its last click height
        # (the client picks the click on a plane at the champion's drawn height, so it crept up). Path corners take the
        # navmesh's height (not the click's), a standing champion is put back on it every tick, and the champion +
        # player bundle snaps it first; a fix is logged ("off the navmesh ... put back"). false = as before
        "ground_path_from_navmesh": True,
        "ground_snap_standing_champion": True,
        "champion_bundle_snap": True,        # 2026-10-23 17:40: allied units / structures (MatchUnit.vision) reveal enemies too
        # 2026-10-22 09:30 (tester: the drones should only attack when attacked): 0 = a unit the flow keeps quiet
        # fights only once it is hit (the original's first drone); groups the flow sends at Batman have their aggro
        "unit_close_aggro": 0.0,
        # 2026-10-21 (tutorial-data-inventory.md section 7): no template names the tutorial's ranged drone 0x2E001168,
        # so it has no attack; it borrows the Trooper Drone's (0x40000B23: 150 health, 10 damage, range 5, shots)
        "unit_attack_from": {"0x2E001168": 0x40000B23},
        # 2026-10-21 21:46 (tester: enemies cannot be targeted): hostile units get their template's unit flags
        # 0x1000019D, targetable 0x10000AA7 and 0x100001C3 / 0x1000034C (targeting-and-relations.md)
        "unit_target_properties": True,
        # 2026-10-21 23:30 (diag --target: every drone refused at "unit flags = 0"): the flags go as a change this
        # many seconds after the unit is created (the client caches them only on a change). 0 = in the creation table.
        "unit_flags_delay": 0.8,
        # 2026-10-22 08:13 (diag --target: flags still 0 after a second bundle): the late flags go as event 0x6 (set one
        # property through the client's change path) instead of a full bundle
        "unit_flags_event": True,
        # 2026-10-22 08:57 (diag --target: drone refused at "status tag check B", 0x974940 with 0x10000029): bools the
        # validator needs true on the target, sent like the unit flags (in the creation table and as event 0x6)
        "unit_targetable_tags": ["0x10000029", "0x10000249"],
        # 2026-10-22 08:13 (tester: red drones, the original's are purple): colour override 0x10000CF0 on hostile units,
        # as the generic drone template 0x49000A5C has it (1); 0 = the client's relative colour (enemy = red)
        "unit_colour_override": 1,
        # 2026-10-22 08:13 (tester: Superman still repeats lines): a scene script's conversation (the intro's 441)
        # holds the director's next line until it ends; lines not timed in conversations.tsv count this long
        "queue_scene_conversations": True,
        # 2026-10-22 08:56 (tester's video): the cinematic plays its scene's conversations itself; sending them as well
        # (true) made each intro line go by twice
        "scene_conversations": False,
        # 2026-10-22 08:39 (tester: Superman still repeats lines): each conversation (0x2001) gets its own instance id
        # instead of 0xFFFFFFFF for all
        "conversation_instances": True,
        # 2026-10-22 09:13 (logs: the client sends 0x2140 | u32 instance when a conversation has played): the next
        # conversation starts then; false = after the catalog length only
        "conversation_done_event": True,
        # 2026-10-22 (original's videos: each objective's text, with its counter, at the top centre): the objective
        # also goes as the banner (field 0x1000000), as the earlier server sent it
        "objective_banner": True,
        # 2026-10-22 (decompiled, docs/re-notes/client-status-effects.md): bools set on the champion while knocked
        # down: 0x10000B2D blocks every order client-side, 0x100003F3 = Stunned; cleared this long after get-up
        "knockdown_flags": ["0x10000B2D", "0x100003F3"],
        "knockdown_free_after": 0.5,
        # 2026-10-22 (decompiled, docs/re-notes/client-cinematics-matchend.md; the earlier server's fase3-ff sequence):
        # VICTORY billboard, then (victory_hold s later) the match-ended notice with completed encounters, stats,
        # trainee achievement and the MISSION COMPLETE scorecard (re-sent scorecard_resend s later); false = the bare
        # notice. Progress is kept in data/progress.json (progress_file)
        # 2026-10-22 13:59 (tester: the second login hung, nothing more in the logs): switch off the console's
        # QuickEdit, whose selection (one click in the window) freezes the server on its next print
        "console_no_quick_edit": True,
        # 2026-10-22 14:02 (tester: the second login hung at "Retrieving encounters" once 5 stored preferences were
        # sent back in 0x216A; the earlier server always sent it empty): send them back only when true
        "send_stored_preferences": False,
        "tutorial_end_sequence": True,
        "victory_hold": 4.0,
        "scorecard_resend": [5.0, 25.0, 60.0],
        "victory_voice_lines": [0x250],
        "reward_champion": 0x40000086,
        "scene_conversation_seconds": 6.0,
        "unit_stats": True,              # units' health / damage / speeds from their stat block (0x10000165)
        "unit_attack_damage": 10,        # units' attack damage until their attributes are read (no stat 5 either)
        "spawn_world_states": True,      # placements with no entity class: created as their bare world state
        # 2026-10-21 (tester: no doors, car, Destroyer sphere, crates ...; static analysis: the client places a
        # network object only through its movement component, created for creation types 7 / 8 and fed by the
        # movement module). Props now get the module and 0x50F = 8 (UniqueDynamicMobile) unless their world
        # state is already 7 / 8. Back to fase3-fx: prop_movement_module = false, static_creation_type = 6.
        "prop_movement_module": True,
        "static_creation_type": 8,
        # Scriptlets played on each prop once it exists, when its own tables (0x7D2 + bases) hold them: the door's
        # Object_Closed spawns its light wall (child world state 0x2E0010F4 / 0x2E000CD8) (2026-10-21, tester: no doors)
        "prop_initial_scriptlets": ["Vfx_OnInit", "Object_Closed"],
        # 2026-10-21 21:46 (tester: the drones are purple, not red): their team colour comes from their base table
        # 0x1D000385's _Entity_OnSetClientRelationship (the Destroyer's cinematic plays it by hand)
        "unit_initial_scriptlets": ["_Entity_OnSetClientRelationship"],
        # 2026-10-22 (tester after fase3-gp: the drones appear abruptly; original Part 1 video 1:18.4: a purple ring /
        # glow where each one appears): a unit plays the first of these its tables hold this long after its creation
        # (drones: table 0x1D0002F8 _Entity_OnEnterWorld_Default -> Vfx_Spawn: particles 0x18000B56 / B58, colour
        # fade, ring mesh 0x1700142A). [] = no spawn-in effect (fase3-gp).
        "unit_spawn_scriptlets": ["_Entity_OnEnterWorld_Default", "Vfx_Spawn"],
        "unit_spawn_delay": 0.1,
        # 2026-10-22 (tester after fase3-gp: only the first big meteor leaves the lava crater; original Part 1 video
        # 0:44 and 1:15): the walk's and the wave's meteors are small strikes (rock, fire column, dust; no crater) and
        # the wave's lands beside Batman. False = fase3-gp (the walk's rock alone, the wave's a big crater at 24, 66).
        "tutorial_small_strikes": True,
        # 2026-10-22 (original Part 1 video 3:55: the bridge ambush's drones spawn in at the closed gate 03GateA behind
        # Batman). False = fase3-gp (ahead of him, 14.8-16.3 m along the bridge).
        "tutorial_ambush_from_gate": True,
        # s between two conversations (the director plays them one at a time: overlapping ones repeated)
        "conversation_gap": 0.4,
        "run_unit_scripts": False,       # start each unit's own server scripts (0x8E) when it spawns
        "missile_objects": True,         # a missile is a real object of its class, flying to its target
        "trace_scripts": True,           # script states in server.log
        # 2026-10-21 (tester: no animations since the scriptlets carried the script's own variables 0x10000030 /
        # 0x100009EB; with only the target as 0x108, as the earlier server sent, they played). False = 0x108 only.
        # 2026-10-23 20:20 (tester: other champions' skill animations / FX incomplete; skill-animations-and-skins.md):
        # the scripts pass variables to 124 scriptlet keys (target IID 0x10000030, speed 0x100009EB, fx 0x1000050A ...)
        # that the tables bind; only 7 keys got them. Every scriptlet now goes with its variables, typed by kind (the
        # 2026-10-21 regression came before the typed encoding). False = 0x108 only, except shot_scriptlet_variables.
        "scriptlet_variables": True,
        # 2026-10-23 20:20 (skill-animations-and-skins.md 5.4, probable): the champion carries 0x7D2 = its template's
        # scriptlet tables + its world state's, so keys only in the world state's tables play (AGL's passive)
        "champion_script_tables": True,
        # 2026-10-23 22:10 (tester: still no skill animations although the client accepted every 0x8D): the champion's
        # skill scripts mirrored to the client (0x200F) at load complete. 2026-10-23 22:24 (tester: the game closed at
        # load complete): access violation at rva 0x48be3 (stack 0x44bd95, the script instance ctor area) right after
        # the eight 0x200F; off until the client's skill-instance creation is understood
        "skill_script_mirror": False,
        # 2026-10-23 22:34 (tester: the second match of a client session stuck at 35 %; second-match-load-hang.md): the
        # world teardown clears the client's local player IID; 0xEB goes again before every later match
        "resend_local_player": True,
        # 2026-10-23 16:20 (tester: shots fly straight instead of to their target; projectiles-homing.md): these shot
        # scriptlets always get the script's variables (0x10000030 target IID, 0x100009EB speed): turret 0x100002E0 /
        # 0x1000029D, ranged minion 0x10000326, Gaslight Batman's basic attack 0x10000188 / 0x10000189 / 0x1000017E
        # 2026-10-23 18:40 (tester: Atomic Green Lantern's skills have no animations): his scripts animate through
        # _HFSM_BehaviorRaiseEventAction 0x100001E3 with variable 0x780 = the graph event, which was dropped (36-byte
        # 0x8D without a table): 0x100001E3 always gets its variables too
        "shot_scriptlet_variables": [0x100002E0, 0x1000029D, 0x10000326, 0x10000188, 0x10000189, 0x1000017E, 0x100001E3],
        # Matches without an encounter flow: every element of catalog hud_elements.tsv is shown at the start (0x213D).
        "show_hud": True,
        # 2026-10-22 14:43 (tester: the whole HUD and every skill button were there from the start; the original's
        # videos reveal them as Superman explains them; client: a Tutorial_Basic encounter starts with only the
        # objective tracker and the hints): the flow's ("hud", [elements]) / ("skill_button", slot) reveal them, and a
        # slot whose button is not shown cannot be used. False = every element at the first "hud", every slot usable.
        "tutorial_progressive_hud": True,
        # 2026-10-22 (original's videos 1:41, 9:57): a yellow arrow over each "+" the flow lets be clicked (0x213D
        # ShowArrowHighlight on the upgrade button; HideHighlight on the skill panel when done)
        "tutorial_rank_arrows": True,
        # 2026-10-22 14:45 (tester: two Batmans in the cinematics; the scene's "player" actor stood beside ours):
        # 0x20F5 binds the champion to the scene's player actor (flags bit 1 + bindings {0, champion}) ...
        "cinematic_bind_champion": True,
        # 2026-10-29 (tester report 2026-10-29 15:30: on Gotham Heights only the player's champion plays the intro
        # line-up animation; gh-ca-floor-spawn.md 4): the allied bots are bound too, as actors 0x10000001..4 of the PvP
        # intros (Player01..04, "needs binding"; 0xa9c610 keeps the keys the server sends). false = the champion only
        "cinematic_bind_allies": True,
        # ... and asks the client to hide the world's entities of these PerceivedType bits while it plays (bit-3
        # field; 8 = Character: the champion); 0 = none (the old 0x20F5 with the DID only)
        "cinematic_hide_types": 0x8,
        # Frames per second of a cinematic scene's timeline (its 0x10000060 events at frames 10, 200, 390 ...);
        # not found in the data yet (2026-10-21)
        "scene_fps": 30.0,
        # The guide marker of an encounter flow (ics/director.py): the tutorial's marker entity 0x40000A9C (its
        # tables hold Vfx_GuideArrow; its ping set runs script 0x34000600, which plays Vfx_GuideArrow_Ping on the
        # marker and Vfx_GuideArrow on the player's agent aimed at it). [on, scriptlet]: on = "marker" / "champion"
        "marker_class": 0x40000A9C,
        # 2026-10-22 (tester after fase3-gp: no ground marker, only the arrows at Batman's feet): [on, scriptlet, FX];
        # the FX template goes as script variable 0x1000050A, as 0x34000600 does (its Group ping 0x1E00055E on the
        # marker through the marker's own Vfx_GuideArrow, its Group arrow 0x1E000510 on the champion). Back to
        # fase3-gp: [["marker", "Vfx_GuideArrow_Ping"], ["marker", "Vfx_GuideArrow"], ["champion", "Vfx_GuideArrow"]]
        "marker_scriptlets": [["marker", "Vfx_GuideArrow", "0x1E00055E"],
                              ["champion", "Vfx_GuideArrow", "0x1E000510"]],
        # 2026-10-22 (original Part 1 video 1:55-2:05: a green ring on each practice target and green chevrons at
        # Batman's feet pointing at them; the target template 0x49000BA9 runs 0x34000600 with IsActive 0x10000B94 = 1):
        # the flow's ("guide", group) puts a guide ring on each and aims the arrow at the first living one. False = off.
        "guide_targets": True,
        "director_start": "",
        # 2026-10-21 (tester: show every champion, also the disabled ones): data/champions.json now lists all 54
        # champions (tools/roster.py). The pack manager may have 16 slots per category (old note); if the login
        # breaks with the full list, roster_limit = 43 sends only the first ones (0 = all).
        "roster_limit": 0,
        # The play menu's encounters (0x2024) from the master list 0x48000001, only those whose map is installed
        # (2026-10-21: Metropolis Skyway and Apokolips Causeway have none). False = the fixed list of fase3-fx.
        "encounters_from_data": True,
        # 2026-10-22 14:11 (tester: after Tutorial 1, Play -> VS Player / VS A.I. map tiles named 'undefined', type
        # Unknown, "Queues are currently unavailable", JoinQueue with encounter 0 and a dropped game connection).
        # The play menu's query 0xA68030 loads each encounter's template (0x49......) on the client; it did not load
        # in the menu shown after the match, so names / type / QueueKey (0x86E060) came out empty.
        # queue_flags: the 0x2024 / 0x20FF per-encounter queue flag word by category (0x200000 blind pick, 0x20000
        # draft, 0x10000 ranked; ics/messages.py QUEUE_*): {} = the defaults (0x220000, tutorials 0).
        "queue_flags": {},
        # queue_eligibility: 0x2101 at login and with the menu refresh (ranked / draft eligibility, level); the
        # client had no answer for GM_UI.InqQueueEligibility before. ranked_min_level: the level ranked needs.
        "queue_eligibility": True,
        "ranked_min_level": 1,
        # menu_refresh_after_match: seconds after the client leaves a match world (0x12D) to send 0x20FF (the
        # encounter list again: Encounter.ResetMapSelectionList, the menu queries the encounters once more) and
        # 0x2101; 0 = off.
        "menu_refresh_after_match": 3.0,
        # reject_unknown_encounters: a JoinQueue (0x20EB) for encounter 0 or one with no map pack is answered with
        # 0x20E0 (removed from queue) and a menu refresh, not a referral to a match that cannot load.
        "reject_unknown_encounters": True,
        # Champion stats from its stats record (0x100008E2: Gaslight Batman 455 health, 350 Will, 47 attack damage at
        # level 1, + growth per level), sent as its stat properties (2026-10-21, master plan steps 5-6).
        "champion_stats_from_data": True,
        "send_stat_properties": True,
        # The shop (ics/shop.py). Credits are server rules, not client data (shop-items-inventory.md 2): these are
        # starting values to be tuned. shop_anywhere sends 0x10000A23 = true (no fountain yet).
        "shop_anywhere": True,
        "start_credits": 500,
        "credits_per_second": 2.0,
        "credits_per_kill": {"unit": 25, "champion": 300},
        # XP and levels outside a scripted flow. The curve is not in the client data (progression-meta.md 1.4); the
        # champions' build records spend 19 points, so the cap is 20. xp_levels[i] = total XP for level i + 2.
        "xp_per_kill": {"unit": 60, "champion": 300},
        # 2026-10-26 (hud-xp-ring.md, C: the game's own table, array 0x10000067 of 0x49000010 in pack 0xA00000B3, the
        # one the HUD's ring reads through InqXPForLevel; cap 19 = InqLevelCap's default): total XP for level i + 2
        "xp_levels": [300, 700, 1200, 1800, 2500, 3300, 4200, 5200, 6300, 7500, 8800, 10200, 11700, 13300, 15000,
                      16800, 18700, 20700],
        "level_cap": 19,
        # register the player's advancement handlers at the link (0x9F 0x81A1000B), so the ring gets its thresholds
        "advancement_handlers": True,
        "advancement_rpc_leading_u8": True,
        "advancement_rpc_blob4": False,
        # The dead panel's countdown: notices 0x10000090 / 0x100000BC (layouts from static analysis, 2026-10-21; never
        # seen in a log). False if the client misbehaves when Batman dies.
        "respawn_notices": True,            # start the flow at this step (testing), e.g. "pursuers"
        # 2026-10-25 (champion-animation-matrix.md cause 3): 0.06 -> 0.13 s, so the stop / facing state (replayed 0.1 s
        # late by the client) lands before the cast's graph event
        "champion_scriptlet_delay": 0.13,   # s after a champion bundle (earlier server: [scripts] champion_defer)
        # ---- PvP flow and account ----
        # 2026-10-22 (task: login -> queue -> champion select -> match -> rewards -> menu; full-account-social.md 10):
        # one JSON file per account (name = player_name) in account_dir ("" = data/accounts, gitignored). A new
        # account takes the completed tutorials of data/progress.json.
        "account_dir": "",
        "start_merits": 0,               # a new account's wallet (amounts are not in the client data)
        "start_crisis_coins": 0,
        "amplifier_set_slots": 6,        # amplifier set slots of a new account (0x2090 "total" since fase3-ie)
        # 2026-10-28 ~13:52 (tester: no amplifier set can be created; store-amplifiers.md, C: the client's
        # NotifyListAmplifierSets builds `total` rows, server sets first and empty client-only sets after them, and
        # offers to buy a slot while total < max): 0x2090 total = the account's slots (was len(saved sets) = 0, so
        # the screen had no set to edit), max = amplifier_set_max (set slots that can be bought in the store).
        # amplifier_sets_total_slots = false: the earlier total = number of saved sets.
        "amplifier_sets_total_slots": True,
        "amplifier_set_max": 12,
        "amplifier_slot_for_sale": True,  # list the set slot item (0x20B8 type 5) so the "buy a set slot" row shows
        # 2026-10-28 ~13:52 (tester request): the champion's chosen set (lobby 0x2098, else the last one saved for it)
        # gives its augments' stats (0x10000950: op 9 add / 10 percent) in the match, kept apart from the items'
        # (World.recompute_stats amp_add / amp_pct). Mods change artifacts and are not applied yet.
        "amplifier_stats_in_match": True,
        # 2026-10-28 ~13:52 (tester: the SHOP button does nothing; store-amplifiers.md, C: the store screen is a CEF
        # page at the login's URL.Store pair, loaded after the client's own web-ticket notice; the server sent no
        # URL.Store): AuthSelect sends URL.Store = store_url ("" = this server's page http://host:soap_port/store,
        # "none" = not sent, the earlier behaviour). The page lists the store and buys with the account's wallet.
        "store_url": "",
        "store_web_page": True,
        # 2026-10-29 (user: a nice, modern store page with the champions' portraits and backgrounds, for champions and
        # skins): "cards" = card grid with tabs, search and a detail dialog (ics/store_web.py render_cards);
        # "table" = the fase3-ie plain table. The pictures (portrait grid_icon, wallpaper per champion / skin) are
        # converted from the installed packs at run time and cached in data/uesrv_cache/store (git-ignored);
        # store_page_images false = cards without pictures; store_card_mip = the wallpaper mip for a card (1 = 512 px);
        # store_prewarm_images converts every card once in the background at the first visit
        # 2026-10-30 (tester: remove the STORE / INFINITE CRISIS title and the Merits / Crisis Coins pills at the top
        # of the store page; the client header already shows them): false = no title row; true = as before
        "store_page_header": False,
        "store_page_style": "cards",
        "store_page_images": True,
        "store_card_mip": 1,
        "store_prewarm_images": True,
        # 2026-10-29 (user: "extract all the images of the amplifiers and augments so they can be seen in the store;
        # right now only a few have images": only 17 of 334 had a template 0x10000302): compose each augment / mod
        # icon the way the client's amplifier screen does (augment = brand background + two stat corner icons of
        # 0x48000AAD; mod = target artifact icon 0x10000436 + brand badge of 0x48000A34; docs/re-notes/amplifier-icons.md);
        # false = only 0x10000302 (the earlier behaviour)
        "store_amp_composed_icons": True,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: SHOP showed the browser's chrome://version page and no
        # GET /store reached the server; store-fix.md 2.3, C): the client reads AuthSelect's nameValuePairs as a gSOAP
        # NameValuePairArray whose items are child elements named nameValuePairs (0xADE2D0 -> 0xADE0F0 name / value);
        # the flat fase3-ie pair parsed as an empty array, URL.Store stayed "" and NavigateByInfo dropped the request
        # (0x8308C0). true = nested <nameValuePairs><nameValuePairs><name>..; false = the fase3-ie flat pair.
        "auth_pairs_nested": True,
        # Ownership. True = what fase3-fy did (every champion and skin owned); false = starter_champions + bought /
        # rewarded ones. Amplifiers and Stolen Power versions are listed in 0x20B8 (types 12/13/2) so the pickers
        # have them; ownables_extra_types = false sends only champions / skins as before.
        "own_all_champions": True,
        "own_all_skins": True,
        # TEMPORARY (store test; afterwards back to [] until accounts are worked on, tester 2026-10-29 22:35).
        # 2026-10-29 22:30 (tester: "make Blue Beetle and his 2 skins buyable to test the store; they must show as not
        # owned and be enabled after I buy them"): these champions / skins are NOT owned under own_all_champions /
        # own_all_skins until bought (Blue Beetle 0x400007FA, skins Jaime Reyes 0x40000999 and 0x40000CA8). [] = all owned.
        # 22:40: store test done (purchases at 22:37 in the server log): back to [] as asked
        "own_all_except": [],
        # 2026-10-29 22:30 (same report: "give me coins to buy those 3 items"): one-time wallet grants applied at login,
        # each id once per account (recorded in the account's wallet "grants"). Blue Beetle 4000 + 2 skins 2000 each
        # in Merits, 400 + 200 + 200 in Crisis Coins. [] = none.
        "account_grants": [],
        "starter_champions": ["0x40000086"],
        "ownables_extra_types": True,
        "grant_all_amplifiers": True,
        "grant_all_stolen_powers": True,
        # Curves and rewards (account-systems-data.md 3.7 / 4: none of it is in the client data): XP to the next
        # level = base + per_level x (level - 1); caps from the achievement records (protector 100, champion 20).
        "account_xp_curve": [1000, 100],
        "champion_xp_curve": [600, 120],
        "account_level_cap": 100,
        "champion_level_cap": 20,
        "account_xp_item_flat": 100,     # XP of one flat account-XP reward item 0x48000F31
        # tester report 2026-10-29 12:45 (end screen: the "Champion Level Up!" popup's portrait box is empty;
        # docs/re-notes/unit-death-slide-levelup.md 3, C 0xA7E0A0: the 0x2104 field after the champion DID is the
        # character icon the client stores at +0x150 and passes first to Ribbon_CharLevelChanged and to the summary's
        # champion portrait; ics sent 0): which data/champions.json picture goes there: "tex384" (the kill card's
        # portrait), "grid_icon", "tex799", or "" / 0 = none (fase3-ig).
        # tester report 2026-10-30 15:30 (screenshot: the popup on the home screen still had an empty portrait box with
        # tex384 0x13001650 in 0x2104; docs/re-notes/levelup-ribbon-portrait.md): tex384 / tex799 live only in the
        # champion's light pack (AGL 0xA000014F), which is not loaded in the menus, so utils.Icon.SetBgImage drew
        # nothing; grid_icon (AGL 0x13001652) is in the always-loaded UI pack 0xA00000D0 (52 of 54) / 0xA0000103 (54
        # of 54), the champion grid's picture. "tex384" = fase3-ih..fase3-ir.
        "level_up_icon": "grid_icon",
        # same report (screenshot: the summary's champion XP read "720 / 1061997773" = 0.8f bits; C 0xA7E0A0 stores
        # field 3 as total XP, field 8 as XP to next): "client" = u32 level | prev | total | earned | bonus | f32 pct |
        # f32 prev pct | u32 to next; "old" = the fase3-ig order (to next, total, earned, bonus, pct, prev pct).
        "character_level_layout": "client",
        # tester report 2026-10-29 21:10 (the score screen's rewards panel; aggro-recall-scorepanel.md 3, C: handler
        # 0xA7DFB0 hands the 0x2080 words to Flash as level, prev, w5 = to next, w2 = total, w3 = earned, w4 = bonus, and
        # the header gets total = w2, to next = w5): "client" = level | prev | total | earned | bonus | to next | pct |
        # prev pct; "old" = level | prev | to next | total | earned | bonus (to fase3-in)
        "account_level_layout": "client",
        # same report (the original's panel reads "247793 / 273500" and "6625 / 7200" with the bars far from full): the
        # XP text of 0x2080 / 0x2104 is cumulative XP / cumulative XP of the next level ("cumulative"); "remainder" = XP
        # inside the level / XP still missing (to fase3-in)
        "xp_numbers": "cumulative",
        # 2026-10-29 tester report 23:03 (the rewards panel still missing; scorecard-accolades-meteor-aura.md 1, C Flash):
        # the panel is the scorecard's first tab ("Summary" = m_btnTabAccolades, opened by the UI state machine
        # 0x34000000 after ScorecardLoadComplete). Its AccoladesDisplay listens only to ACCOLADES_RECVD, which
        # ScorecardManager raises only when the accolades notice comes after every other piece; the scorecard asks for
        # the accolades before the header (Init), so with 0x2188 cached at the match end the animation chain stops at
        # its first step and the tab stays empty. 0x2188 again this many s after the scorecard's 0x212E (its screen
        # load), when everything else is in; 0 = only the match-end copy (to fase3-io)
        "scorecard_accolades_resend": 1.5,
        # same: when no 0x212E comes, the late 0x2188 this many s after the end messages (0 = none)
        "scorecard_accolades_resend_fallback": 8.0,
        # 2026-10-30 tester report 11:23 (the rewards panel still empty after the fase3-ip resend; traffic 11:23:17.193
        # shows the late 0x2188 went; scorecard-panel-turret-head.md 1, C exe): 0x2188's handler 0xA61DA0 returns
        # before Flash when its accolade list is empty, so an empty 0x2188 never raises ACCOLADES_RECVD. 0x2104's
        # handler 0xA7E0A0 hands its own (empty) accolade lists to the same Flash notice (0x8CEE70) when its trailing
        # u32 is a valid encounter record. True = 0x2104 carries the match's encounter there (false = 0, to fase3-ip)
        "scorecard_level_encounter": True,
        # same: which message the late resend repeats: "0x2104" (the one that reaches Flash with no accolades) or
        # "0x2188" (fase3-ip; only useful once 0x2188 carries real accolades)
        "scorecard_accolades_resend_event": "0x2104",
        # 2026-10-30 tester report 14:51 (the original's end screen, screenshot 79, has a "Victory / Match Duration /
        # Rewards: Protector XP, Merit, Champion XP" panel to the right of the team tables on the Scorecard view;
        # scorecard-rewards-side-panel.md, C Flash): this client's Scorecard view (movie 0x2000008C, SummaryTab) has no
        # such panel, only the two team tables and the chat window on the right; the same parts are its "Summary" tab
        # (ScorecardAccolades, movie 0x200000AD). True = those four lines also go to the chat window as chat lines
        # (0x2183) once the scorecard is up; false = none (to fase3-ir)
        "scorecard_chat_summary": True,
        # same: the chat channel name the lines carry (the echo's form; the scorecard shows the "All" log)
        "scorecard_chat_summary_channel": "All",
        # same: s after the scorecard's 0x212E (after the late 0x2104), and the fallback after the end messages
        "scorecard_chat_summary_delay": 2.5,
        "scorecard_chat_summary_fallback": 9.0,
        "pvp_rewards": {"account_xp_win": 150, "account_xp_loss": 100, "champion_xp_win": 200,
                        "champion_xp_loss": 120, "merits_win": 50, "merits_loss": 25, "first_win_merits": 100},
        # Boutique (0x2106 -> 0x2107, purchases 0x210E / 0x2110 / 0x2111): store_prices in Merits ("SC", soft),
        # store_prices_hc in Crisis Coins ("HC", hard); 0 = not sold in that currency. The original prices are not in
        # the client data (store-fix.md 4). store_currency: the currency name of the fase3-ie 0x2107 / charge, used
        # only with store_boutique_currency_keys = false.
        "store_currency": "Merits",
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00, wallet 800 Merits / 50 Crisis Coins): amp_slot 1000 -> 500,
        # a set slot both currencies can buy (store_prices_hc 50); original prices unknown (store-fix.md 4).
        "store_prices": {"augment": 300, "mod": 300, "champion": 4000, "skin": 2000, "amp_slot": 500},
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: buying a set slot sent 0x210E "for 4294967295" four times
        # and nothing happened; store-fix.md 3, C): BoutiqueDataManager keeps a price only for the currency names "SC"
        # (Merits) and "HC" (Crisis Coins), case ignored (AS2 l.69 / l.73); "Merits" left every cost at -1. true =
        # 0x2107 sends one "SC" entry (store_prices) and one "HC" entry (store_prices_hc) per item with the same
        # boutique id, and a purchase is paid from the wallet of the currency the client chose; false = the fase3-ie
        # 0x2107 (store_currency name, Merit prices), charge (store_currency's wallet) and 0x210F on a wrong price.
        "store_boutique_currency_keys": True,
        # Crisis Coin prices (0 = not sold for Crisis Coins). The set slot's dialog (DualCurrencyPurchaseDialog) shows
        # both prices and its Crisis Coin button stays clickable at -1, so the slot needs both; augments / mods buy
        # with "SC" only (AmplifierPurchaseDialog). Values: O (store-fix.md 4).
        # 2026-10-29 10:30 (user: every store item must also be buyable with Crisis Coins, the currency a match gives):
        # a Crisis Coin price for every kind, a tenth of the Merit price as for the set slot (G; 0 = not sold for them)
        "store_prices_hc": {"augment": 30, "mod": 30, "champion": 400, "skin": 200, "amp_slot": 50},
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; store-fix.md 3.3, C: no AS2 package listens to 0x210F, so
        # the fase3-ie answer to a wrong price did nothing): a 0x210E whose price is not the server's (0xFFFFFFFF when
        # the client had none): "error" = 0x210D general error + a fresh 0x2107 (repairs the client's prices),
        # "changed" = the fase3-ie 0x210F (+ 0x2110 / 0x2111), "accept" = charge the server's price. Only with
        # store_boutique_currency_keys = true (false always answers 0x210F, as fase3-ie).
        "store_price_mismatch": "error",
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; store-fix.md 6 correction 6 and 7.2, C: 0x2095's second u32
        # is the ribbon's icon DID and its StringInfo the item name (0x8AAF60 -> 0xA7EA00 -> 0xA26B50 -> 0x88F040 ->
        # UpgradeUnlockRibbon.SetData); the store sent the item's own DID and "" = an empty ribbon after the client's
        # own purchase dialog): false = no 0x2095 after a store purchase; true = the fase3-ie ribbon.
        "store_purchase_ribbon": False,
        # Login: after the account data (0x2080 last), these follow login_extras_delay s later: currencies 0x2081,
        # header 0x2190, best accolades 0x2186, the login calendar's reward 0x2197 (or 0x219D), contacts 0x203B.
        "login_extras": True,
        "login_extras_delay": 0.5,
        "login_calendar": True,
        # Queue and champion select. queue_pop_seconds: JoinQueue -> match found (lobby encounters; the tutorials
        # pop at once as before). select_seconds: champion select time (-1 = the encounter's 0x100004A1, e.g. 60 s).
        # launch_delay: launch warning 0x204B -> match started 0x2053. Bots fill every free slot from the pools.
        "queue_pop_seconds": 2.0,
        "accept_seconds": 30,
        "select_seconds": -1,
        # 2026-10-23 09:21 (tester: after the lock no skin list / countdown, then the load hung): launch_delay is
        # the costume countdown of 0x204B (LaunchWarning.as needs >= 10 s for all its callbacks); was 3.0.
        "launch_delay": 15.0,
        # 2026-10-23 09:21: 0x2053 (handler 0xaba390) switches the client to view-match (spectator) mode: no more
        # 0x20D5, no load-complete notice, the loading screen without cards. Only for spectators; false = not sent.
        "send_match_started": False,
        # 0x2031: the bots' loading percent (the loading screen's cards; display only). -1 = only my own slot.
        "bot_loading_percent": 100,
        # 2026-10-23 09:44 (tester: the map's camera is turned 90 degrees): the mode layer's intro cinematic was sent
        # while the client was still loading and ended at once (state 4); the client sets the map camera when a
        # cinematic ends (2026-10-21, Tutorial 1). Now it plays [timing] cinematic_delay s after load complete.
        "cinematic_after_load": True,
        # 2026-10-23 09:45 (tester: turrets took health with no shot seen; minions' shots not seen either): the
        # match units' attack scripts get their init event at spawn and level-up (0x10000088 loads range and stats;
        # 0 = not raised), and the direct-damage fallback sends the shot's scriptlet by role (0 = none), then deals
        # the damage after distance / match_shot_speed.
        "match_unit_init_event": 0x10000088,
        "match_attack_scriptlets": {"turret": 0x100002E0, "inner_turret": 0x100002E0, "core_turret": 0x100002E0,
                                    "dampener": 0x100002E0, "foundry": 0x100002E0, "ranged": 0x10000326,
                                    "melee": 0},
        "match_shot_speed": 20.0,
        # 2026-10-23 17:30 (tester: the turret shots are no longer seen at all after it was emptied at 16:20): back to
        # the body's Vfx_Basic_Ranged 0x1000029D, now with the target / speed variables (shot_scriptlet_variables)
        "match_turret_shot_extra": ["0x1000029D"],
        # 2026-10-23 09:45 (tester: at death the game froze for a few seconds, then the champion was at the base): tried
        # LifeState 0x100000FA = 2 alone (event 0x6) instead of the full creation bundle; 2026-10-23 11:28 (tester: then
        # the grey screen did not come): back to the bundle (false). true = the 0x6 form.
        "death_as_property": False,
        # the respawn: graph events that leave the death machine (CbtState_Death_Recover 0x10000034), then the first
        # of these scriptlets the champion's tables hold (the enter-world). [] = none.
        # 2026-10-26 (deep-scan-animations.md 1, C: 0x10000034 is in no champion's main state machine, the client dropped
        # it; _Entity_OnEnterWorld_Default is in no champion's tables but Deathstroke's): _Defeat_OnRespawn 0x100001FC
        # (every champion, raises Global_Locomotion 0x100000AA, a wildcard to Locomotion) is the get-up
        "respawn_graph_events": [],
        "respawn_teleport": True,        # the respawn as a teleport (seq A + 1) with the player links (2026-10-23 14:01)
        "respawn_scriptlets": ["_Defeat_OnRespawn", "_Entity_OnEnterWorld_Default"],
        # the champion's death animation: graph event CbtState_Death_Induce 0x100000AD (0 = none). 2026-10-23 10:17.
        "death_graph_event": 0x100000AD,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: the fall to the ground does not play when the player kills or
        # is killed; docs/re-notes/death-animation.md 2 / 9, C: the client never starts it itself, the graph's Death
        # state is entered only on CbtState_Death_Induce): a champion's fall is the 0x8D of the first of these
        # scriptlets (_Defeat_OnDead 0x100001FA, in all 156 champion variants: that graph event + the death cue), sent
        # right after the message that carries LifeState 2; none sent = the bare death_graph_event. [] = the bare event
        # (the fase3-ie bots).
        "death_scriptlets": ["_Defeat_OnDead"],
        # same report (traffic 14:45:56.404 / 14:53:25.927: the local champion's death sent only its LifeState 2 bundle,
        # the fall sat in the death_as_property branch, off since fase3-gv): the local champion falls too. false = no
        # fall (fase3-ie).
        "death_fall_local": True,
        # same report (death-animation.md 10.4, P): s from the local champion's death bundle to its fall. A movement state
        # is applied 0.1 s after its stamp and a 0x8D at once, and the champion's script 0x8Ds (the statuses' exits at
        # death) go champion_scriptlet_delay (0.13 s) late: above both, the stop and the exits land before the fall
        # (fase3-gu: "slid while falling"). 0 = at once. A bot's fall goes at once, as before.
        "death_fall_delay": 0.15,
        # same report (death-animation.md 6, C code): the local champion's death bundle goes even while a carry holds its
        # bundles (liftable_hold_champion_bundles), so LifeState 2 reaches the client before the fall. false = held until
        # the carry's drop (fase3-ie).
        "death_bundle_force": True,
        # same report (death-animation.md 3 / 10.2): the original's grey death screen is _CDefeatSystem_DeathOverlay
        # 0x10000843 (a Colorize at saturation -100 + a smoke texture, held while its run lives); our client already runs
        # it by itself on the local death (C by video, trigger O), so the server sends nothing ([]): a second run would
        # stack a second smoke texture. ["_CDefeatSystem_DeathOverlay"] = opt-in, if the screen is no longer grey while
        # lying dead: sent to the local champion only (no local-player filter: never for a bot) after the fall.
        "death_overlay_scriptlets": [],
        # same report (death-animation.md 4, C: event 0x11F stops a scriptlet run, a 0x8D signal does not): a sent
        # overlay's run is stopped by 0x11F (u8 0 | u32 key | u32 run | u8 0) at the respawn and at the match end (the
        # original's grey ended when its end cinematic started). false = no stop (the grey would stay).
        "death_overlay_stop": True,
        # 2026-10-29 (fase3-if review of the tester report 2026-10-28 15:00 fix, C ics: in Clash the local death that takes
        # the last 20 team health ends the match inside World.damage's "killed" event, before the fall is scheduled, so
        # Match.end's stop found no run and the fall's opt-in death screen started 0.15 s later and stayed through the
        # end cinematic and the result, with no 0x11F): once Match.end ran, no death screen starts (the fall still
        # plays: a dead champion falls during the end hold). false = a pending fall may still start it.
        "death_overlay_skip_after_end": True,
        # tester report 2026-10-29 12:45 ("the drones' destruction animations do not play: when their health runs out
        # they stand still a moment and disappear"; docs/re-notes/unit-death-slide-levelup.md 1, C traffic 12:15:02.416:
        # a dead drone got only its LifeState 2 bundle, then 0x3 corpse_seconds later): a dead unit (lane drone, camp
        # creature) plays the first of these scriptlets its tables hold (_Defeat_OnDead 0x100001FA: the fall
        # CbtState_Death_Induce + Vfx_OnExplode in the minion tables; the old server sent it on the tutorial drones and
        # they fell, CHANGELOG 2026-10-13) unit_death_fall_delay s after the death bundle (its stop state applies 0.1 s
        # after its stamp; the killing hit's 0x8D goes 1 ms after the bundle). [] = none (fase3-ig).
        "unit_death_scriptlets": ["_Defeat_OnDead"],
        "unit_death_fall_delay": 0.15,
        # same report (P: the minion tables hold _Defeat_OnFade 0x100001FE, a timed fade of the body): played
        # unit_fade_delay s after the death bundle, before the corpse goes (corpse_seconds). [] = none (fase3-ig).
        "unit_fade_scriptlets": ["_Defeat_OnFade"],
        "unit_fade_delay": 2.0,
        # tester report 2026-10-29 12:45 ("my first death made AGL slide a little across the map while falling"; C run
        # 12:16:14.938 death bundle, 15.002 / 15.013 two 0x20EE moves accepted, World.tick walked the dead body until
        # the fall at 15.101): a dead champion's orders are ignored (dead_orders_ignored) and a dead champion / unit
        # never walks (dead_hold_still: walk_to refuses, a destination left on a dead body is cleared with a stop).
        # false = as fase3-ig.
        "dead_orders_ignored": True,
        "dead_hold_still": True,
        # 2026-10-23 10:23 (tester: only the first turret can be attacked): a structure that stops being protected gets
        # bool 0x100007D9 = true, which the dampener / core turret / core templates link to the targetable status
        # 0x10000249 (0 = not sent). match_unit_vision: allied minions are fog vision sources (0x10000133).
        # skill_client_events: client 0x20EA (slot | events) goes to that slot's skill script.
        "match_unlock_property": 0x100007D9,
        "match_unlock_modifiers": True,  # 2026-10-23 17:40: and 0x10000249 / 0x10000029 by a set modifier (op 6, 0x20F0)
        "skill_used_event": True,        # 2026-10-23 17:40: 0x20C9 'skill used' / 'interrupt' to the client's skill script
        # 2026-10-23 14:49 (diag --target: dampener, core turret and core refused with cached unit flags 0): each
        # structure's flags go again as a change (0, then the value) when the HUD is ready and when it is unlocked.
        "match_refresh_flags": True,
        # 2026-10-24 00:45 (tester: only the first turret can be attacked, still): an unlocked structure is also sent again
        # as a full bundle carrying 0x100007D9 = true (the client links status 0x10000249 to it when it builds the object).
        "match_unlock_bundle": True,
        # 2026-10-24 00:55 (tester: the zones where a champion turns invisible are missing; crime-alley-missing-elements.md
        # 1.3): stealth strips from the map spec ("stealth"), world state / tile size / status below; match_stealth_hides:
        # the AI ignores a champion inside one unless it stands in the same strip, or for match_stealth_reveal s after the
        # champion hits an enemy minion / champion (2026-10-24 23:05, tester's description of the original).
        "match_stealth": True,
        "match_stealth_world_state": 0x2E000D36,
        # 2026-10-25 (crime-alley-visuals.md): the stealth tiles as the hotspot entity 0x4000039D (0 = the world state
        # above); the base gates' side 0x100007A2 per team (3 blue, 5 red: lights the wall); the dampener's activation
        # scriptlets; the nook's pad (superpad 0x40000CB5, P; {} = none).
        # 2026-10-25 23:22 (tester: inside a stealth zone the champion loses its vision; only its tint should change):
        # the hotspot entity's template (unit flags 0x2000, collision polygon 0x57A) is P what the client's fog treats
        # as a sight blocker; the tiles go as the bare world state again (the hex mesh stays: stealth_tile_direct)
        "match_stealth_class": 0,
        "match_stealth_class_tried": 0x4000039D,
        "match_base_sides": {"1": 3, "2": 5},
        # 2026-10-25 (crime-alley-still-missing.md 1, C: the core showed no team-colour cylinder; it got no scriptlet):
        # the core's start keys and its team colour ("active" = Vfx_Active_Blue / _Red by side).
        # 2026-10-25 (map-manifests.md, C tables): the core world states have no Vfx_Startup / Vfx_Active_Blue / _Red (they
        # were dropped) but Vfx_AI_Active (v AI; P: the core turret "prow" hologram); the core turret and the lane turret
        # bodies have Vfx_Active + Vfx_AI_Active; the foundry Vfx_Startup + Vfx_Active. Keys a table lacks are not sent.
        # 2026-10-25 (stubborn-visuals.md 1, P: the dampener table 0x1D00063A has Vfx_AI_Active, the stacked hologram 0x2E000AA8 of the original)
        "match_structure_scriptlets": {"dampener": ["Object_Activate", "Vfx_Active", "Vfx_AI_Active"],
                                       "core": ["Vfx_Active", "Vfx_AI_Active"],
                                       # 2026-10-29 (tester report 21:10, frame 71: the Power Core Turret's hologram
                                       # stands with no body under it; power-core-turret.md 8.1, C table): its base
                                       # table 0x1D000374 is the only turret table with Vfx_Fade_In 0x10000033 (a
                                       # type-35 render action + stop of Vfx_Fade_Out); P its body starts faded out.
                                       # Sent first. Was ["Vfx_Active", "Vfx_AI_Active"]
                                       # 2026-10-30 tester report 12:05 ("the tower's base is not the correct one";
                                       # turret-head-pct-look.md 2, C tables, P look): Object_Reset last. Its type-0x17
                                       # run of Vfx_Object_Reset (base 0x1D000374: a timeline of Vfx_Object_Phase keys)
                                       # reaches the Vfx_Active child cylinder 0x2E000A9A, whose only keys besides its
                                       # hologram Vfx_Startup are those phases (type-0x2E actions on group 0x10000002):
                                       # P the opaque fill of the original's cylinder. Drop it = fase3-io..ir
                                       # 2026-10-30 tester report 13:00 (screenshot 89: only a white ghost cylinder;
                                       # turret-pct-composite.md): with the lane body (match_structure_classes) the
                                       # body plays Vfx_Active only, as on a lane turret; no Vfx_AI_Active (its child
                                       # is the lane's ring head 0x2E000AA8; the flag head 0x2E000AC3 comes from
                                       # match_turret_heads), no Object_Reset (on 0x2E000AC4 it turned the A9A
                                       # cylinder white and the flag head went: 71 / 82 vs 89), no Vfx_Fade_In (not
                                       # in the lane tables). Was ["Vfx_Fade_In", "Vfx_Active", "Vfx_AI_Active",
                                       # "Object_Reset"] (fase3-is)
                                       "core_turret": ["Vfx_Active"],
                                       "turret": ["Vfx_Active", "Vfx_AI_Active"],
                                       "foundry": ["Vfx_Startup", "Vfx_Active"]},
        # 2026-10-25 19:28 (tester's frames of the original: a round steel pad with a padlock hologram in the middle;
        # crime-alley-jungle.md, C object / position: world state 0x2E00101D, as Tutorial 2 places it at the same
        # nook; the superpad 0x40000CB5 was the small "+" plate)
        # 2026-10-25 23:11 (tester: the floor under the Raider is not the right one): none for now (the spec stays as
        # match_nook_pad_tried)
        # 2026-10-25 23:30 (tester's frame of the original: the steel pad with the padlock IS the Raider's floor): on again
        # 2026-10-26 13:40 (tester's vitrina 121: the bare world state 0x2E00101D does not draw): sent on the carrier class
        # 2026-10-26 14:20 (tester: vitrina 121 = 0x2E00101D draws, but it is the Raider capsule of other modes, not the
        # vs-AI pad with the padlock): none until the right piece is found
        # 2026-10-26 (deep-scan-maps.md 1.2, C class / keys: the padlocked plate is the Power Relay 0x4000089D, ws
        # 0x2E000D12, the only Crime Alley class of minimap category 26 = the v AI tracker's pip; P position / lock
        # polarity, G unlock time = the Raider's arrival): locked at the start, unlocked when the Raider comes
        "match_nook_pad": {"class": 0x4000089D, "world_state": 0x2E000D12, "pos": [80.0, 97.25], "yaw": 180.0,
                           "props": {"0x100004FF": 2, "0x100006BD": True, "0x100006BC": True},
                           "scriptlets": ["_Entity_OnEnterWorld_Default", "Vfx_Fade_In", "Vfx_Locked"],
                           "unlock_props": ["0x100006BD", "0x100006BC"], "unlock_scriptlets": ["Vfx_Unlocked"],
                           # 2026-10-29 12:45 (tester report 2026-10-29 12:45: the padlock stays when the Raider
                           # appears; throw-truck-padlock.md 4): event 0x11F stops these runs at the unlock ([] = none)
                           "unlock_stop": ["Vfx_Locked", "_Selection_Usage_Locked"],
                           # tester report 2026-10-29 15:30 (the padlock still stays at the Raider; run 14:26:01 sent
                           # the fase3-ih stop; throw-padlock-coredeath.md 2, C 0x57C4B0): the client's own key stop
                           # (0x588A80, used for _Selection_Usage_Locked when the team's lock bool turns false) passes
                           # mode 1 to 0x57C4B0, the 0x11F u8 is that mode and fase3-ih sent 0; unlock_stop_flag = the
                           # 0x11F u8 (0 = fase3-ih), unlock_stop_again = s after the unlock to stop them once more
                           "unlock_stop_flag": 1, "unlock_stop_again": [0.5, 2.0]},
        # camp units play their table's spawn-in on every (re)spawn (Vfx_Spawn_Event02: the yellow phase-in, P key)
        # 2026-10-28 12:56 (tester: the jungle creatures still appear with no spawn animation; the original's is a sparkling
        # yellow translucent wireframe; liftables-camps-animations.md 3, C data / P effect): table 0x1D000674's
        # Vfx_Spawn_Event02 holds only the yellow overlay render effect (type 8, mesh 0x17001445, colour 0xFFF5EC04),
        # never seen in three tests; Vfx_Spawn_Alt01 holds that overlay AND the sparkle particles 0x18000D90 (type 0x11).
        # Sent match_camp_spawn_delay s after the bundle (0.1 = the drones' spawn-in timing that shows; was 0.4)
        "match_camp_spawn_scriptlets": ["Vfx_Spawn_Alt01"],
        "match_camp_spawn_delay": 0.1,
        # 2026-10-28 13:52 (tester: the camps stay in their yellow phase-in forever and lose it at once when attacked;
        # jungle-camps-spawn.md, C data / code, P timing): the phase-in's render effect is persistent (0x375 = 1), so
        # it lasts until its run stops. A camp unit phases for match_camp_phase_seconds (G: the 2v2 video's 10:57 ->
        # 11:00 respawn; 0 = the fase3-id behaviour), invulnerable and untargetable (match_camp_phase_untargetable);
        # the run is re-sent after a full bundle of the unit (match_camp_phase_resend), then signalled to stop
        # (match_camp_phase_stop) and one bundle follows (match_camp_phase_end_bundle). The first camps start
        # match_camp_phase_seconds early so the phase completes on the "Phasing Complete" line (match_camp_phase_lead).
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 6.1): with object_update_mode "delta"
        # a camp's chase / phase-end updates are deltas, so match_camp_phase_resend (after full bundles only) is inert and
        # the phase-end "bundle" is a delta (its late flags / FloatyVitals again by 0x6, an equal value: no change)
        "match_camp_phase_seconds": 3.0,
        "match_camp_phase_untargetable": True,
        "match_camp_phase_resend": True,
        "match_camp_phase_stop": True,
        "match_camp_phase_end_bundle": True,
        "match_camp_phase_lead": True,
        # 2026-10-30 (tester report 13:18: "the jungle creatures' spawn effect must show from the 30-seconds announcement
        # and, with about one second left, the creatures appear"; timeline-tooltip-camp-prespawn.md 2): the first camps
        # (the only spawn the announcer counts down; respawns have no line and keep match_camp_phase_seconds) spawn in
        # their phase-in (Vfx_Spawn_Alt01's yellow wireframe, invulnerable, untargetable) at match_camp_prespawn_from s
        # of the jungle time (-30 = the "Online in 30 seconds" line) and complete it match_camp_prespawn_appear_before s
        # before that time (the creatures become solid / attackable). 0 = off (match_camp_phase_lead's 3 s phase).
        "match_camp_prespawn_from": -30.0,
        "match_camp_prespawn_appear_before": 1.0,
        # 2026-10-25 23:11 (tester: the camps appear, but not with the transparent vortex): no generic
        # _Entity_OnEnterWorld_Default before the camp's own phase-in (it went 3 ms earlier and the phase-in did not show)
        "match_camp_skip_enter_world": True,
        "match_camps_first_by_map": {"crime_alley": 45.0},     # both original videos: the camps at 0:45
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: the jungle drones are grey / metallic, the original's yellow;
        # camps-colour-bar-positions.md 1, C): the client tints PVP_Team 0..2 only (0xA7B0D0: cmp edi, 2 / ja at
        # 0xA7B143), so the neutral team 3 gave colour index 0 = TeamColor Null. A camp unit (bosses included) is sent as
        # this team: 0 = neutral -> colour 6 -> appearance 0x19000A61 value 0x1000011F -> material 0x16000E7B (yellow), and
        # Flash's neutral bar tint 0xCCCC33. The server keeps match_neutral_team (fog, AI, rewards, script relations).
        # None = the fase3-ie team 3 on the wire
        "match_camp_wire_team": 0,
        # 2026-10-28 15:00 (same report; camps-colour-bar-positions.md 1.3 / 8.2.9, P strong): a camp unit's 0x100007A2
        # (PROP_SIDE, in every bundle) = the colour index the client computes for team 0; the persistent 0x22 container of
        # _Entity_OnSetClientRelationship (table 0x1D000385) follows it, and 0 (fase3-ie) switched it back to Null
        "match_camp_side": 6,
        # 2026-10-28 15:00 (same report; camps-colour-bar-positions.md 1.3 / 8.2.7, C: the unit component's team cache
        # [comp+0x4C] is the change-only watcher that missed the PerceivedType / vision creation values in fase3-gd): the
        # team also goes as a CHANGE, match_neutral_team then the wire team (0x6), unit_flags_delay + 0.1 s after the
        # spawn, so the listener 0xA813F0 tints with team 0. false = the team in bundles only (fase3-ie)
        "match_camp_team_as_change": True,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: no overhead health bar over the drones; camps-colour-bar-
        # positions.md 8.2-8.3, C: 0xA50A70 pushes a bar to Flash only while the status tag FloatyVitals 0x1000072C is
        # true, tag list 0x16016AC checked at 0xA50C3B; every jungle creature template, CA 0x49000CA0 / CA1 / CA2, GD and
        # CC, declares it with no value = false, the lane minions and structures carry 1): bools sent = 1 by 0x6 to every
        # camp unit (bosses included) after its unit flags 0x1000019D, held with the targeting flags while it phases in
        # (the bar shows at "Phasing Complete", as in the original), kept in every later bundle (a bundle that omits an
        # id removes it), never in the creation bundle (a push before the flags carries PerceivedType 0 and Flash keeps
        # that blank bar). [] = none (fase3-ie: no bar)
        "match_camp_vitals_tags": ["0x1000072C"],
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: the side camps stand in the wrong places; camps-colour-bar-
        # positions.md 3, P +-0.3 m): a camp with "slots" (maps.py) puts unit i on slots[i], all moved with the camp's
        # "pos" (so match_camp_overrides still moves a whole camp); false = the fase3-ie ring (the first unit on "pos",
        # the others 2 m around it)
        "match_camp_slots": True,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: there must be no camp in the centre of Crime Alley;
        # camps-colour-bar-positions.md 3.3, C: the original's nook pad stands empty at "Phasing Complete"): true = also
        # the map's "camps_centre" (Crime Alley: the fase3-ie middle camp on the Raider pad, first in the list as then,
        # so match_camp_overrides indices are fase3-ie's; the Raider then waits for it to be cleared)
        "match_camp_centre": False,
        # 2026-10-29 (tester report 2026-10-29 21:10, 78.png: the original v AI minimap marks every living camp with one
        # small icon; ours sent no 0x100004DA for camps, so they had none; ca-fog-minimap-ring.md 4, C 0xA4BD80 + Flash
        # MapNote.UpdateForPerceivedType): the listed creature class carries a minimap note [category, icon] (9 MINION
        # with the minion icon 0x13000141, tinted by the wire team: neutral 0 = yellow 0xCCCC33). Only the heavy
        # creature, so one icon per camp; it goes with the heavy's death (G: no camp-marker icon is in the data; the
        # original's diamond texture is O). {} or match_camp_map_note false = none, as fase3-in
        "match_camp_map_note": True,
        "match_camp_map_notes": {"0x40000CA1": [9, "0x13000141"]},
        # 2026-10-29 (tester report 2026-10-29 21:10: at the centre our minimap shows "that big yellow circle and dot",
        # the original a camp icon; ca-fog-minimap-ring.md 4, C Flash MapNote: category 26 SMALL_CAPTURABLE without an
        # icon draws the capture-point border's default art, neutral = yellow): the nook pad 0x4000089D's template has
        # 0x100004DA = 26 and 0x100007D8 = 1. false = the pad's creation bundle carries 0x100004DA = 0 (no minimap note);
        # true = its template's capturable circle, as fase3-in. 2026-10-29 (tester, after fase3-io: "the centre camp is
        # the Raider: first the pad with the padlock, then the padlock goes and the Raider appears; leave it with the
        # circular icon on the minimap"): true
        "match_nook_pad_map_note": True,
        # 2026-10-30 (tester report 13:18: "the pad where the Raider appears looks separated from the ground, floating";
        # docs/re-notes/ca-strip-static-shadow.md 3, C data): the pad 0x4000089D (.entity 0x2D000ADC) is a 9.2 cm plate
        # whose model starts at its origin (box z 0 .. 0.092); it went at the map's z 200.3, so it floated 0.32 m over
        # the terrain at (80, 97.25) (199.98 m, flat; the navmesh there is 200.08, the markers 0x2E000944 / 945 200.085).
        # At 199.98 its top is at 200.07, level with the walk height. 0 = the map's z (match_maps "z"), as before
        # 2026-10-30 (tester report 14:51 video, 5:44-5:48 = 14:57:43-47: "when the pad was put on the floor half of it
        # disappeared, raise it a bit"; agl-floor-raider-pad-pct-prow.md 2, G frames): at 199.98 the plate's north third
        # (~2.4 m of its 7 m) goes under the paved floor north of the nook, whose straight edge crosses it at y ~98.4,
        # while the south part lies on the gravel; at 200.3 it showed whole (floating over the gravel). 200.2 = the
        # nook's own marker height (statics 0x2E001117 / 0x2E001120 at (79.96, 97.13, 200.20 / 200.22), the original's
        # placement, P): top at 200.29, 0.22 m over the gravel's edge
        "match_nook_pad_z": 200.2,
        "match_stealth_size": [4.0, 2.0],
        # 2026-10-29 (tester report 2026-10-29 18:31: the stealth fields at both ends are still too far from the edge;
        # their edge must sit against the collision of the central block; ca-fog-stealth-hover.md 2, C statics):
        # the jungle-mouth tiles with a maps.py "render" spec lie on the drawn wall faces (west pillar x 52.90, east
        # chain-link panels x 106.95 and their 157 deg fence) instead of the navmesh faces 0.18-0.37 m in front of
        # them. false = the fase3-if positions (navmesh faces, mirrored about x 80)
        "match_stealth_render_faces": True,
        # 2026-10-29 (tester report 19:55, screenshot 63: "at both ends move this section a little further down, toward
        # the lane"; ca-ring-fog-bundles.md 4): metres the jungle-mouth vertical tiles (maps.py "lane_dir") move toward
        # the lane: 1.0 = centre y 85.2 -> 84.2, south end on the curb's lane edge (y ~82.1). 0 = where maps.py puts them
        "match_stealth_lane_shift": 1.0,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: the side stealth fields are off; the vertical one back as it
        # was, lined up with the corner's collision edge; stealth-alignment.md): per map key and tile index
        # {"pos": [x, y], "yaw": deg} over maps.py "stealth" ({} = the map's list: the original's L at each jungle
        # mouth, Crime Alley tiles 4-7). The vertical tiles where they were before 12:5x:
        # {"crime_alley": {"4": {"pos": [51.7, 84.0]}, "5": {"pos": [108.3, 84.0]}}}; the 13:5x layout (fase3-ie):
        # {"crime_alley": {"4": {"pos": [51.7, 84.0], "yaw": 98.0}, "5": {"pos": [108.3, 84.0], "yaw": 82.0},
        #  "6": {"pos": [53.7, 87.0], "yaw": 50.0}, "7": {"pos": [106.3, 87.0], "yaw": 130.0}}};
        # the east L flush with its own corner instead of the mirror:
        # {"crime_alley": {"5": {"pos": [108.1, 85.2]}, "7": {"pos": [105.62, 87.5], "yaw": 157.25}}}
        "match_stealth_overrides": {},
        # 2026-10-26 (tester: the stealth fields should lie flat on the ground, they showed stuck to the curbs): tiles at
        # the navmesh height + this lift (m) instead of the map's base height
        "stealth_on_ground": True,
        "stealth_margin": 0.5,                 # 2026-10-26: m around each tile's rotated 4 x 2 box that still hides
        "stealth_ground_lift": 0.03,
        # 2026-10-28 (tester: the stealth fields still do nothing; stealth-rendering.md, C): the client ignores the status's
        # IsHidden 0x100007BF and node 0x1000011E; its script started the shimmer for 3 of 6 entries and stopped it within
        # 0.5-2 s. The server plays the shimmer itself (stealth_shimmer_key) and no longer applies the status (0 = none;
        # 0x4800028C = as before). AI blindness stays server-side (match_stealth_hides)
        "match_stealth_status": 0,
        "stealth_shimmer_key": "0x10000648",
        # the tiles keep the hex mesh (stealth_tile_direct) and also play Vfx_Active, whose particle is the purple
        "stealth_tile_vfx": True,
        "match_stealth_hides": True,
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00, the L layout above; stealth-alignment.md 6, the original's
        # rule for overlapping hotspots is O): the two tiles of a jungle mouth's L overlap at the bend; an enemy sees a
        # hidden champion when it stands in any strip that holds the champion (False = the first strip holding each must
        # be the same, as before: a champion in the bend stayed hidden from an enemy a metre away in the diagonal tile)
        "match_stealth_any_shared": True,
        "match_stealth_reveal": 2.0,
        "match_unit_vision": True,
        # 2026-10-25 (map-gaps-*.md, C): objective state scriptlets per role (Gotham Heights' points and Coast City's
        # relays: contention / neutral colours only; the device the CapturePoint states); relay beams on the holder's core.
        "match_capture_scriptlets": {"capture": {"contest": ["0x100008C4"], "captured": [], "lost": ["0x10000B0D"]},
                                     "relay": {"contest": ["0x100008C4"], "captured": [], "lost": ["0x10000B0D"]},
                                     "beacon": {"contest": ["0x1000032F"], "captured": ["0x100002A9"],
                                                "lost": ["0x100002A8"]}},
        "match_relay_beams": True,
        # 2026-10-25 (map-gaps-gotham-divided.md 3, map-gaps-coast-city.md 2, C from each set's captions; north = "top",
        # south = "bottom", P): per-map announcer ids over announcer_events (0 = that line does not exist on the map).
        "announcer_events_by_map": {
            "gotham_divided": {"core_75": 0, "core_50": 0, "core_25": 0, "dampener": 0, "turret_north": 36, "turret_mid": 37, "turret_south": 33,
                               "dampener_north": 38, "dampener_mid": 40, "dampener_south": 48, "core_turret": 55,
                               "dampener_reactivating": 64, "dampener_reactivated": 63, "first_blood": 18,
                               "victory": 29, "dampener_north_attack": 47, "dampener_mid_attack": 41,
                               "dampener_south_attack": 39, "dampener_attack": 0},
            "coast_city": {"relay_captured": 50, "relay_neutralized": 59, "relay_capturing": 57, "relays_unlocked": 49,
                           "relays_unlock_soon": 58, "relays_locked": 66},
        },
        # 2026-10-25 09:00 (tester: with the fog now drawn, the minions' vision is too wide): "min" = the smaller of the
        # minion template's two vision radii (3.0), "max" = the larger (6 / 7 / 8, the earlier choice).
        "match_minion_vision": "min",
        # 2026-10-23 12:14 (tester: Batman lost animations, e.g. the batarang's bounce): 0x20EA's event 0x10000023 was
        # raised on the slot's skill script (47 times) without knowing what it means; off until it is traced.
        "skill_client_events": False,
        # 2026-10-27 (skill-execution-model.md 1.2, C: 0x20EA carries only 0x10000023 "targeting begun", from 0xA26420 for
        # every non-instant slot, and 0x10000009 "targeting cancelled" for Green Arrow R): with script_accept_filter on,
        # 0x20EA goes to the slot's script and only scripts accepting the event see it (GA R 0x3400040C, Deadshot R
        # 0x34000694, Dex-Starr W 0x340006B7, Flash R 0x34000217); skill_client_events = true sends it unfiltered.
        "skill_client_events_filtered": True,
        # 2026-10-23 11:30 (tester: Bat Scream does no damage and shows no wave): a missile aimed at a point flies on
        # after a hit while its script has not destroyed it (Bat Scream 0x34000043 hits everyone on its line, less
        # each time); World._missile_hits checks the whole stretch flown in a tick. false = it ends at the first hit.
        "skillshot_pierce": True,
        # 2026-10-23 (tester: no announcer voice): the announcer is server-driven (0x2039 with a match event id); which
        # id means what is not in the client. Test in the match chat: "/anunciador 31" or "/anunciador todos" (one
        # every announcer_test_gap s). announcer_events maps the match's events to ids once known by ear ({} = none):
        # keys structure_lost, structure_destroyed, wave_soon, wave, first_blood, kill, victory, defeat.
        "chat_commands": True,
        "announcer_test_gap": 7.0,
        # 2026-10-23 12:31 (tester: none of the 16 announcer events played): the dialog system needs notice 0x10000205
        # (dialog_enable_notice) and the events go on channel 1 (shared set) / 2 (the encounter's), not 0. announcer_mode:
        # "2039" (the event), "2001" (its line as a conversation, the way 0x250 plays) or "both". The test plays each
        # event by 0x2039, then its line by 0x2001 announcer_test_fallback s later (0 = not).
        "dialog_enable_notice": True,
        "encounter_property_event": True,      # 0x100001D3 by event 0x6 after load complete (the shop catalogue)
        # 2026-10-23 15:01 (diag --shop: the listeners never ran): in a lobby match the player bundle goes again
        # player_rebind_delay s after the match-start notice, then the property ("bundle" / "recreate" / "none")
        "last_played_at_match": True,    # 0x214B "last played" = the match's encounter with each 0x20AF (the minimap)
        # 2026-10-23 15:30 (diag: a bundle on the existing player did not re-broadcast; the shop's manager registers
        # at match start): first pass (player_rebind_delay s) only the 0x100001D3 events, second pass
        # (player_recreate_delay s, after the 13 s pre-start) re-creates the player ("recreate") then the events.
        # 2026-10-23 15:40 (diag: neither pass reached a listener; the minimap / shop now come from the exe's HUD
        # cave, `ic.py patch`): no re-creation of the player mid-match (0 = no second pass).
        "player_rebind": "none",
        "player_rebind_delay": 1.0,
        "player_recreate_delay": 0.0,
        # 2026-10-23 15:40 (tester: a costume without its mask): 0x20AF also names each champion's parent pack
        "champion_shared_packs": True,
        # 2026-10-23 16:20: variants' model packs share DIDs (0x36000009) with different content and the last loaded
        # wins: the local champion's model pack goes last in 0x20AF
        "local_champion_pack_last": True,
        "encounter_cleared_at_end": True,   # 0x100001D3 = 0 on the player when the client leaves a match
        "lobby_slot_resend": 0.5,        # my 0x2029 again this long after a pick (a costume's portrait packs)
        "lobby_hud_extra": [8, 10, 11, 13, 16, 24, 29, 33, 36, 37, 38, 41, 44],
        "ping_echo": True,               # 2026-10-23: 0x2137 echoes each ping (the client's fields)
        "announcer_mode": "2039",
        "announcer_test_fallback": 3.0,
        # seconds after load complete at which every announcer event plays once, one every announcer_test_gap s, each
        # logged in server.log as "announcer test: event N" (0 = off; the 2026-10-23 13:14 run named them).
        "announcer_test_on_start": 0.0,
        # 2026-10-23 13:14 (tester's announcer test, each event's line and on-screen text named by ear; events 55, 56,
        # 58, 61, 63, 64 said nothing): match event -> announcer event id. The line's own / enemy form follows the
        # team sent (the destroyer's / killer's). 37 said "Shutdown" too.
        # 2026-10-25 (announcer-and-map-elements.md, C from the captions): the 2026-10-23 ear test skipped the six silent
        # "under attack" events, so every name after them was shifted; corrected ids (was_shutdown 52 added), plus
        # champion_kill 30 and the "under attack" events (lane turrets top / mid / bottom 31 / 35 / 34, core 32, core turret
        # 56, mid dampener 41).
        "announcer_events": {"annihilated": 8, "core_25": 10, "core_75": 15, "core_50": 17, "first_blood": 18,
                             "relentless": 19, "furious": 20, "dominated": 21, "unstoppable": 22, "double_kill": 23,
                             "shutdown": 24, "invincible": 25, "triple_kill": 26, "quadra_kill": 27, "penta_kill": 28,
                             "victory": 29, "champion_kill": 30, "enemy_defeated": 30, "was_shutdown": 52,
                             "turret_south": 33, "turret_bot": 33, "turret_north": 36, "turret_top": 36,
                             "turret_mid": 37, "dampener": 40, "relays_unlocked": 49, "relay_captured": 50,
                             "core_turret": 55, "relays_unlock_soon": 58, "raider_defeated": 61,
                             "dampener_reactivated": 63, "dampener_reactivating": 64,
                             "turret_north_attack": 31, "turret_mid_attack": 35, "turret_south_attack": 34,
                             "core_attack": 32, "core_turret_attack": 56, "dampener_mid_attack": 41,
                             "dampener_attack": 41},
        "match_multikill_window": 10.0,
        # tester report 2026-10-29 17:45 ("the announcer's voice seems to overlap other notices"; traffic 17:35:02 /
        # 17:35:22 / 17:35:32: the wave and the jungle lines 0x2A0 + 0x2A1, 0x29E + 0x29D, 0x29C + 0x29F in the same
        # millisecond; 17:39:42 GH 0x196 + 0xAE; ca-fog-ring-announcer.md 3): heard together, so the server
        # queues them. true = one announcer item at a time, kills first, then structure / objective events,
        # then timeline lines; the next starts announcer_queue_gaps[group] s after the previous one; a non-kill item
        # waiting more than announcer_queue_max_wait s is dropped. false = sent at once as before
        "announcer_queue": True,
        "announcer_queue_gaps": {"kill": 2.5, "event": 3.0, "line": 2.5, "default": 3.0},
        "announcer_queue_max_wait": 8.0,
        "announcer_queue_kill_events": [18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 30, 52],
        # 0x2039's source / target: "champion" (the local one), "event" (killer, victim), "champions_real" (2026-10-25
        # 16:12, empty strip at every kill: the killer / victim when both are champions in the world, else the local one)
        "announcer_iids": "champions_real",
        # 2026-10-23 (tester: turret shots unseen and silent): turret heads (role -> head world state, created with the
        # body) and the body's Target_Acquired / Target_Lost scriptlets when the target changes.
        # 2026-10-24 23:50 (crime-alley-video-compare.md 3 / 5): in the original only the lane turret has the gear plate
        # 0x2E000A9F; the dampener stands on its own ring base and the core turret's template is world state 0x2E000AC4
        # (not the lane turret's body), with no plate: the fase3-hm head / plates on them are taken back.
        # 2026-10-30 tester report 13:00 (screenshot 89: next to the blue core only a small translucent white cylinder
        # with the health bar, no turret body and no flag head; turret-pct-composite.md): the Power Core Turret is now
        # the lane body (match_structure_classes) and the server makes its flag head 0x2E000AC3 (the original's head
        # in frames 66 / 67, graph env_pvp_powercore_a_turret_head_behavior) as it made the lane heads up to fase3-io:
        # side colour, Vfx_Startup, Vfx_Targeting while it has a target. Drop "core_turret" = no head on it
        "match_turret_heads": {"turret": 0x2E000AA8, "inner_turret": 0x2E000AA8, "core_turret": 0x2E000AC3},
        # 2026-10-30 tester report 13:00 (same; turret-pct-composite.md): role -> extra world states the server spawns
        # with a structure as objects of their own (side, team, Vfx_Startup; removed with the head when it falls).
        # Entry = world state or [world state, dz]. The Power Core Turret gets its own cylinder 0x2E000A9A (its data's
        # Vfx_Active child, z -0.25 in table 0x1D000374) round the lane body: the blue / red hologram skin of frames 71
        # / 82 over a solid body, the closest the data gets to the glossy cylinder of frames 66 / 67. {} = none
        "match_structure_parts": {"core_turret": [[0x2E000A9A, -0.25]]},
        # 2026-10-23 15:40 (tester: the turrets have no base): role -> base plate world state under it ({} = none)
        # 2026-10-30 tester report 11:23 ("the base of the turret near the core is missing"; scorecard-panel-turret-
        # head.md 3, C traffic: the lane turrets got "plate (0x2e000a9f)" at 11:06:21.549 / .681, the Power Core Turrets
        # none): since fase3-ip the blue Power Core Turret is the lane body 0x2E000AA0 (0x40000C8E, as the red 0x40000C8D
        # by data), which stands on this gear plate everywhere else; the original's prow piece is not in this client's
        # data (crime-alley-still-missing.md 8). core_turret gets the plate too (drop the key = fase3-ip)
        # 2026-10-30 tester report 12:05 ("the tower's base is not the correct one"; screenshot of fase3-ir: the Power
        # Core Turret on the gear plate; original frames 66 / 67 / 70: it stands in a round socket on the core
        # platform's prow, no gear plate; turret-head-pct-look.md 2): the plate goes again; add "core_turret":
        # 0x2E000A9F to have it back (fase3-ir)
        "match_turret_plates": {"turret": 0x2E000A9F, "inner_turret": 0x2E000A9F},
        # 2026-10-30 (tester report 14:51 video: "the turret next to the core still lacks its platform; I think I saw it
        # in the last showroom"; original frames 66 / 67 / 70: a pointed prow from the core platform toward the lane;
        # agl-floor-raider-pad-pct-prow.md 3, P): map -> role -> a static piece the server places under the structure
        # once per match (it stays when the structure falls). 0x2E000A8E (.entity 0x2D0008A6, ctype 8) is the only
        # unplaced piece of the base-statics family: same table 0x1D000385 as the core pedestal 0x2E000A3B and the
        # gear plate 0x2E000A9F, the same 0x303 / 0x57A as that plate, its id between the core's pieces and the
        # turret's, referenced by no static, cinematic or table in any pack. forward = m along the team's lane (team 2
        # mirrored), yaw = deg added to the lane heading (the model's front is not known: try 90 / 180 / 270 if the
        # point faces the wrong way), dz = height over the turret's spot. {} = none (as before)
        # 2026-10-30 (tester, after fase3-iw: "yes, that is the tower's base, but turn it 180 degrees in the same
        # position"): yaw 180 (confirms 0x2E000A8E is the Power Core Turret's platform)
        "match_structure_platforms": {"crime_alley": {"core_turret": {"world_state": 0x2E000A8E, "forward": 0.0,
                                                                      "yaw": 180.0, "dz": 0.0}}},
        # 2026-10-30 (tester report 15:30: "the blue core must be rotated 170 degrees to the right"; core-door-regen.md
        # 1): map -> role -> {"1" / "2": deg} added to the map spec's yaw. Yaw is counter-clockwise seen from above (+y is
        # up on the game camera's screen; the 2026-10-24 camp turn 180 -> 90 was clockwise on screen), so "right" =
        # -170: the blue core 90 -> -80 (its data markers 0x2E0011A7 / A6 say -90 / 90, map-audit-all.md 7.2: the
        # tester's 170 is within 10 deg of them). {} = the spec's 90 / -90 (as before)
        # 2026-10-30 (tester report 19:46, screenshot 96.webp: "the blue core must end in the same orientation as the
        # red one, turn it about 190 degrees clockwise"; ca-strip-two-bit-candidates.md 3): at -80 the core's prow (the
        # dark ramp, the model's local -y) points west-south-west, away from the lane. The red core (yaw -90) points
        # its prow west, at the lane; the map's left / right mirror sends that to east, i.e. yaw 90 for blue = -80 +
        # 170 (counter-clockwise) = -80 - 190 (clockwise), the tester's "about 190 clockwise". So blue adds 0: the map
        # spec's 90, the 180-degree turn of red's -90 (the pedestal 0x2E000A3B's yaws). -170 = fase3-ix
        "match_structure_yaw_add": {"crime_alley": {"core": {"1": 0.0}}},
        # 2026-10-30 (tester report 15:30: "the core must not attack, it must not have that invisible turret on top";
        # core-door-regen.md 2, C data: the core templates 0x40000C8A / C89 carry the turret attack 0x10000328 =
        # 0x34000014, 185 damage and the warning-ring flag 0x10000C5D = 1, which ics used as for a turret): these roles
        # never pick a target or shoot, and go with 0x10000C5D = false (no warning ring). [] = they shoot as before
        "match_unarmed_roles": ["core"],
        # 2026-10-30 (tester report 15:30: "the enemy minions cannot attack my core" / "the enemy champion cannot either";
        # core-door-regen.md 3, C traffic 16:55:15-16:58:43: the core was unlocked at 16:55:15 and never took a hit; the
        # minions and the bot spent their swings on the blue minions spawning at the core and died to the core's 185-
        # damage shots, item 2; and a melee minion that reached the core's rim stood idle there: its sight 3 m was
        # measured to the core's centre 3 m inside the blocked footprint): a minion's sight to a structure counts to its
        # edge (match_structure_radius). false = to the centre, as before
        "match_structure_sight_to_edge": True,
        # 2026-10-30 (tester report 15:30: "my dampener does not regenerate even though time passes"; core-door-regen.md
        # 5: in the 16:36 run the dampener sat at 504 / 3000 from 16:50:20 to 16:52:20 with nobody hitting it; its
        # respawn after match_dampener_respawn did happen, 16:57:43, with lines 64 / 63): a damaged structure of these
        # roles not hit for "after" s heals "per_second" HP per second (G values; the dampener template has no regen
        # property, the core / PCT ones carry 0x10000140 = 10 / 50, meaning unknown). {} = no regen (as before)
        "match_structure_regen": {"dampener": {"per_second": 15.0, "after": 10.0}},
        # 2026-10-30 (tester report 15:30: "roughly in this section, near the blue base exit next to the fence, there
        # should always be an activated blue door; aesthetic, but part of the original map"; core-door-regen.md 4): no
        # Crime Alley static, layout entry or marker places a door (map-object-census.md 1.1, C), so these are server
        # props: the base-gate wall's world state 0x2E000CD7 (no class: no collision polygon), lit by side 3 / 5 with
        # Vfx_OnInit + Object_Closed (the blue wall the countdown gate already draws) and never opened. Positions G (the
        # tester's screenshot with the red rectangle did not reach the session): just past the base exit on the north
        # side, a wall along x at the curb; "scale" = 0x6B4 (the gate model is 21.8 m wide). map -> list of {world_state,
        # pos, yaw, team, side, scale, scriptlets}; {} = none
        "match_decor_doors": {"crime_alley": [
            {"world_state": "0x2E000CD7", "pos": [33.0, 83.2, 200.08], "yaw": 0.0, "team": 1, "side": 3, "scale": 0.4,
             "scriptlets": ["Vfx_OnInit", "Object_Closed"]},
            {"world_state": "0x2E000CD7", "pos": [127.0, 83.2, 200.08], "yaw": 0.0, "team": 2, "side": 5, "scale": 0.4,
             "scriptlets": ["Vfx_OnInit", "Object_Closed"]}]},
        # 2026-10-29 (tester report 2026-10-29 12:45: "the firing head does not look right, something usually rotates
        # around them"; ca-holes-pedestal-turrets.md O2, P): the turret head's colour keys switch on side 0x100007A2;
        # it gets the body's side and the team as a change. false = the fase3-ig head (no side: white, Null colour)
        "match_turret_head_side": True,
        # 2026-10-29 (tester report 23:03: "the turrets appear with 2 heads; the white one is wrong, only the blue one";
        # turret-heads-coredeath.md 1, C table 0x1D000372): when a role's match_structure_scriptlets play the body's own
        # Vfx_AI_Active, the client spawns the head 0x2E000AA8 itself (scale 0.9, Vfx_Startup, blue / red), so no
        # server-made head (it was the white second one). false = the server head too (fase3-io)
        "match_turret_head_skip_own_child": True,
        # 2026-10-30 tester report 12:05 ("when the enemy tower targeted me, the tower's head disappeared"; the 11:23 fix
        # match_turret_pick_in_reach did not cure it; turret-head-pct-look.md 1, C data / decompiled, P cause): the
        # head is the client child of the body's Vfx_AI_Active; Target_Acquired / Target_Lost (table 0x1D00035D) run
        # Vfx_Targeting client-side, which the client forwards to that child (0x57B9D0); the turret's attack script
        # 0x34000014 never runs them (C) and the head first vanished in the build that made it the client child. true =
        # no Target_Acquired / Target_Lost for a structure whose head is its own child (0x10000C66 and the shots stay);
        # false = as before
        "match_turret_own_head_no_target_keys": True,
        # 2026-10-30 tester report 18:12 ("the heads of the towers got lost" again, with diag --heads running;
        # docs/re-notes/turret-death-head-rearm.md 1): the --heads probe attached at 18:03:38, 13 s after the blue lane
        # turret's first fight (18:03:08-25, no probe then); while it ran the turret fought four more times and no
        # spawned-child / render-effect end, run removal or 0x8D touched any structure (IIDs 0x103-0x112), so the head
        # was already gone and what ended it is still not named. A structure whose head is its own client child (the
        # body's Vfx_AI_Active, no server head) gets it back after each fight: "after" s after its target drops to none
        # (still no target, alive) the server stops every Vfx_AI_Active run on the body (0x11F, instance 0xFFFFFFFF:
        # the old head ends if it is still there, so never two) and "gap" s later starts a new one (the head
        # materialises again with its Vfx_Startup); at most once per "min_gap" s per structure. {} = off (as before)
        "match_turret_head_rearm": {"after": 3.0, "gap": 0.2, "min_gap": 20.0},
        # 2026-10-23 16:20 (tester: the minions walk through the turrets): each lane leg that crosses a blocked
        # footprint goes round on the navmesh (False = only the first leg, as before)
        "match_lane_pathing": True,
        # 2026-10-23 18:50 (tester: no blue gate at the start, no white zone that protects a champion;
        # crime-alley-missing-elements.md): the map's base gates (closed until the start) and base auras; inside its own
        # aura a champion gets status base_aura_status (regen, in-base, may shop) and, with base_aura_invulnerable, no
        # damage; leaving gives base_aura_leave_status
        "match_base_gates": True,
        "match_base_auras": True,
        "base_gate_remove_after": 1.5,   # 2026-10-23 19:22: s after Object_Open the gate object is removed (its client collision stayed)
        # 2026-10-29 (tester report 2026-10-29 14:40: on Gotham Heights the champion takes one move order and then never
        # again, skills still cast; traffic: no 0x20EE command 4 after 14:35:54, while Gotham Divided / Crime Alley, whose
        # gates go base_gate_remove_after s after Object_Open, kept hundreds; gh-freeze-holes-picking.md F1, P): a map
        # gate marked "keep" (GH's 20 x 37 x 11 m Door 0x4000026B / 0x40000269 at the G position (26, 54)) stayed for
        # the whole match, and its client collision catches the ground pick, so the clicked point lies on the door, out
        # of the 2.5 m navmesh snap of the order API 0xa70030 (0x4fb400), and the client drops the order unsent. false =
        # every gate goes after the start (GH's ramps / doors are seen only during the countdown); true = fase3-ih
        "base_gate_keep_after_open": False,
        # 2026-10-29 (tester report 2026-10-29 15:30: GH: no move until the start, then a hole at the power core's exit
        # and no ramps to the lanes; gh-ca-floor-spawn.md 1-2, C timing: the first move of the 15:21 run came 0.23 s
        # after "base gate t1 gone"): the Door's world state holds a Kynapse obstruction BOX (0x83C = 1, 0x8C1 = 2,
        # 0x8AA (-30, -30, 0)..(30, 7.93, 4) at yaw 0x856 248.41; 0x555E20 / 0x554EB0), not a pick surface: at (26, 54)
        # yaw 180 it covers both base exits and the core platform but not the base pocket (x 2-12), so clicks outside
        # the pocket are dropped. A "keep" gate is replaced at the start by a copy with these bundle properties (no
        # obstruction component / shape: P that a bundle value wins over the world state's) and these scriptlets, so
        # the floor and ramps stay. {} = the door just goes (fase3-ii)
        "base_gate_floor_copy": {"props": {"0x83C": 0, "0x8C1": 0}, "scriptlets": ["Vfx_OnInit", "Object_Open"],
                                 "same_class": True},
        "base_aura_status": 0x48001109,
        "base_aura_leave_status": 0x48001107,
        "base_aura_invulnerable": True,
        # 2026-10-23 16:20 (tester: Bat Scream must hit every enemy its wave touches): a missile's hit radius is its
        # skill's stat 22 (3.0 on Bat Scream), at least missile_hit_radius m
        # 2026-10-23 16:20 (tester: skill buttons never dim without Will; skill-button-will.md): the champion's
        # secondary vital type 0x1000000C (5 = Will, 0 = not sent) and 0x100000CE = true after its creation
        "champion_secondary_vital": 5,
        "vital_notices": True,
        "unit_death_in_place": True,          # 2026-10-23 16:20: a dead unit's movement is cleared (drones walked away)
        "missile_radius_from_skill": True,
        "missile_hit_radius": 1.0,
        # 2026-10-23 16:20: per camp index ("0", ...) {"pos": [x, y], "yaw": deg} over the map's camp spec ({} = none)
        "match_camp_overrides": {},
        "match_turret_target_scriptlets": True,
        # 2026-10-25 (tester's screenshots of the original: a green / yellow / red ring around an enemy turret;
        # crime-alley-props.md C, decompiled): the client draws it for structures with 0x10000C5D in the create bundle,
        # armed by 0x10000C5B; the turret's target goes as 0x10000C66 (red when it is the local champion)
        "turret_warning": True,
        "turret_warning_armed_at_start": True,
        # tester report 2026-10-29 15:30 (no green / yellow / red ring; decompiled 0xA7CA20, C): the ring registers a
        # structure only at entity add and only with the Turret bit of 0x1000019D, which our creation bundle lacked (it
        # came as a change 6-10 s later). The structures' unit flags ride in the creation bundle and go again as a change
        # (0, then the value); an enemy structure's range 0x10000133 goes as a change too. false = as before
        "turret_warning_flags_in_bundle": True,
        # tester report 2026-10-29 17:45 (ring still not shown; diag --ring 17:33: the enemy turrets 0x106 / 0x10c and
        # core 0x102 DID register; ca-fog-ring-announcer.md 2, C): each frame 0xA84FB0 hides the ring (state 6) until
        # entry +0x4C is set, and only the ring's phantom callback 0xA3A5F0 sets it, for an entity whose PerceivedType
        # has Player 0x200000 and whose IID is the local champion. Ours had Character 8 only. true = the player's
        # champion gets unit flags 8 | 0x200000 (Character | Player); false = 8 as before
        "champion_player_flag": True,
        # 2026-10-29 (tester report 19:55: still no turret ring; ca-ring-fog-bundles.md 1, C object-update-bundles.md 0.3):
        # in "bundle" mode every champion update is a full bundle whose 0xBC turns the 0x6-only unit flags back to the
        # template's 8, so the Player bit lasted until the next bundle (7 s after it was set in that run). true = the
        # flags also ride in the champion's bundles; false = by 0x6 only, as before
        "champion_flags_in_bundle": True,
        # 2026-10-23 23:10 (tester's screenshot: the turret's targeting line stays on a champion until it dies or the
        # turret falls): a target dropped out of range now sends Target_Lost too, and the head plays these scriptlets
        # ("active" = its team's Vfx_Active_Blue / _Red); [] = only Target_Lost.
        "match_turret_lost_on_drop": True,
        # 2026-10-30 tester report 11:23 ("when the turrets are attacked their top part disappears; they keep shooting
        # but the head is no longer visible"; scorecard-panel-turret-head.md 2, C traffic): a structure picked targets
        # out to range + 1 m and act() dropped them at range + their radius in the same tick: Target_Acquired +
        # Target_Lost 1 ms apart (135 / 127 on the lane turrets), each pair starting and stopping Vfx_Targeting on the
        # body and on the client-made head. true = pick only targets within that reach (false = fase3-ip)
        "match_turret_pick_in_reach": True,
        "match_turret_lost_head": ["Vfx_Stop", "active"],
        # 2026-10-29 (tester report 21:10: "the heads of the first 2 turrets look almost transparent; they should be a bit
        # more solid"; power-core-turret.md 8.7, C tables, P effect): the original's head is the body's Vfx_AI_Active
        # child, whose spawn action (field 0x325) runs only Vfx_Startup 0x1000018E on it; the head's Vfx_Active_Blue /
        # _Red (base table 0x1D00038B) switch appearance 0x19001299 group 0x10000002 to materials 0x16002112 / 13 / 0x16002289,
        # which the original never did. false = the server-made heads get Vfx_Startup only (also when a target is
        # lost: "active" in match_turret_lost_head is skipped); true = Vfx_Startup + Vfx_Active_Blue / _Red as before
        "match_turret_head_team_keys": False,
        # 2026-10-23 09:44 (tester: no skin list, no portraits on the loading screen): 0x204C lists every owned
        # champion (type 1) and costume (type 4); and in a lobby match 0x20AF waits for the countdown's end, since it
        # sets lobby+0x4CB (m_bForceOverrideNoLoading, 0xa99f00) and the lobby's costume / portrait packs were cut
        # short when it came at the game connection's hello. false = as before.
        "lobby_owned_costumes": True,
        "lobby_enter_match_at_launch": True,
        "lobby_players_per_team": 0,     # 0 = the encounter's 0x10000BCB
        "lobby_unique_picks": True,
        "lobby_slot_stolen_powers": True,   # Stolen Powers in each 0x2029 (the last two u32, [P])
        "lobby_slot_amplifiers": True,      # the slot's amplifier set in each 0x2029 (else the earlier empty tail)
        "lobby_send_level": False,          # the 0x2029 u32 after the champion as the level ([P]; 0 as before)
        # 2026-10-23 17:30 (tester: test every champion vs AI): the bots draw from every champion with a kit (False =
        # the encounter's own pool); the player may already pick any champion (own_all_champions)
        "bot_pool_all_champions": True,
        "bots_avoid_my_champion": True,   # 2026-10-23 17:30: no bot plays a variant of my champion (packs collide)
        # 2026-10-29 23:30 (tester: "whenever we play against bots, they use a random skin of the champion, never the
        # base look"): each bot plays one of its champion's costumes at random (7 champions have none and keep the base);
        # false = the base variant as before
        "bot_random_skin": True,
        "bot_champions": [],             # force the bots' pool (variant DIDs); [] = the encounter's / every vs-AI pool
        "bot_seed": 0,                   # 0 = random picks
        "resend_enter_match_on_pick": True,  # 0x20AF again at launch when the pick changed (its champion's packs)
        # 2026-10-23 00:05 (Crime Alley vs AI went straight to the loading screen, no champion select): 0x2016 is
        # Lobby.HideBackButton = SetLobbyTransition (handler 0xab9080 -> 0xab8ec0 "Sending CheckTransitionToWorldLoad",
        # UI event 0x23) and 0x206D marks everyone loaded (0xab84f0 -> 0xa964b0, UI event 0x33). With a champion
        # select both wait for the launch (the countdown's end); false = sent with the lobby state as before.
        "lobby_transition_at_launch": True,
        # 2026-10-23 (tester: after a match the menu's maps are empty, queueing sends encounter 0, the client looks
        # disconnected): the packs the exe loads at start-up (install-inventory.md, loader 0x9DD580) stay resident,
        # but a pack named in 0x20AF joins the match-data list that the end-of-match wrapper load unloads
        # (0xa08ed0 -> 0x9e3e20 -> 0x9dd930), and 0xA00000B3 holds every encounter's 0x49 / 0x48 records. So those are
        # never named in 0x20AF. [] = name whatever the data / [ics.encounters] list says, as before.
        "resident_packs": [0xA0000039, 0xA0000038, 0xA000011A, 0xA0000037, 0xA00000DF, 0xA00000B3, 0xA0000103,
                           0xA0000351, 0xA00000D0],
        "custom_match_qflags": (1 << 21) | (1 << 17),
        # The match itself is the mode layer's (ics/match, start_match / tick; pvp_mode_layer = false: not used).
        # Without it a lobby match is a free walk on the map that ends after pvp_stub_seconds (0 = never; a
        # surrender vote ends it as a loss).
        "pvp_mode_layer": True,
        "pvp_stub_seconds": 0,
        "pvp_stub_winner": "me",         # "me" / "enemy": who wins a stub match
        # 0x2021 when the client leaves a lobby match's world (0x12D). 2026-10-28 13:52 (tester: the score screen showed no
        # data, then an empty HOME; diag: the 0x2021 handler ran a second world teardown while the end page was being
        # built; client-cinematics-matchend.md 2.1 step 6, C in game: not needed, the client already left): off
        "exit_lobby_after_match": False,
        # 2026-10-28 13:52 (same report, P): s after the end page closes (0x20A6) to send 0x20FF + 0x2101 again; 0 = off
        "menu_refresh_on_end_page_closed": 1.0,
        # 2026-10-28 13:52 (same report): no objects / HUD re-send when the end cinematic finishes after the match end
        "restore_after_end_cinematic": False,
        # Chat (ics/chat.py): the event that echoes a line (0x2183 / 0x20B0 are the candidates, [G]); 0 = none.
        "chat_echo_event": 0x2183,
        # ---- PvP maps and mechanics ----
        # 2026-10-22 (task: every PvP map with its elements and mechanics; ics/match). Positions, classes, stats,
        # level-by-time, XP / credit / bounty formulas come from the data (ics/match/maps.py, unitdata.py); what is
        # below is NOT in the client data (full-match-mechanics.md 15) and is authored, each with its basis.
        # Clock: the HUD counts down during the intro (13.0 s, the intro cinematics' length, data) and up from 0 after;
        # end = start + match_clock_length (the client needs end > start; no match length exists in the data).
        "match_pre_start": 60.0,
        # 2026-10-24 23:40 (tester: the gate must stay until the countdown reaches 0; crime-alley-2v2-video.md: 00:42 on the
        # clock when the intro hands over control, then 30 / 10 s notices, gate at 0): match_pre_start (was 13) only
        # bounds the wait for the intro; when it ends the clock is set to this many s before the start (0 = not).
        "match_pre_start_after_intro": 42.0,
        # 2026-10-25 (tester: no countdown voice / captions; countdown-keymap-gaps.md 1 / 3): announcer line keys (table
        # 0x2B000093) sent as conversation 0x2001: 0x9C "begins in 60 s", 0xBB 30 s, 0x97 10 s, 0xAE "Match: Initiating",
        # 0xAD "The match has begun!"; first wave: 231 "Drones in 30 s", 247 "in 10 s", 233 "Drones operational!".
        "match_countdown_lines": {"-60": 0x9C, "-30": 0xBB, "-10": 0x97, "0": 0xAE, "2": 0xAD},
        # 2026-10-25 (announcer-and-map-elements.md A3 / A5): per map (the line keys live in each map's layout pack):
        # Crime Alley / Gotham Divided 672 / 670 / 668, Coast City 231 / 247 / 233, Gotham Heights none; jungle online
        # 673 / 669 / 671 before the first camps (match_camps first).
        "match_wave_lines": {"crime_alley": {"-30": 672, "-10": 670, "0": 668},
                             "gotham_divided": {"-30": 672, "-10": 670, "0": 668},
                             "coast_city": {"-30": 231, "-10": 247, "0": 233}},
        "match_jungle_lines": {"crime_alley": {"-30": 673, "-10": 669, "0": 671},
                               "gotham_divided": {"-30": 673, "-10": 669, "0": 671},
                               "coast_city": {"-30": 673, "-10": 669, "0": 671}},
        "match_under_attack_gap": 15.0,
        # 2026-10-25 (coverage sweep): StopProcessingNewBillboards 0x100002BC before the result billboard; units carry
        # Attribute_AttackSpeed 0x100006FE (their graphs scale the attack clips by it).
        "match_stop_billboards": True,
        # 2026-10-25 (coverage sweep: the death screen's "killed by" card is server-driven): notice 0x1000021C to the victim.
        "match_kill_card": True,
        # 2026-10-25 (bot-champions.md, C): the lobby's human row is bound to the local champion (it had no agent: his
        # kills, deaths, assists and credits never counted on the scoreboard).
        "match_attach_human": True,
        # 2026-10-25 (tester: the bots are only names on the scoreboard; bot-champions.md, C path / P result): every
        # bot slot gets a champion on the map (World.create_bot_champion) driven by ics/match/bots.py. Its movement goes
        # as motion-only states (0x4 with only 0xB0) unless bot_motion_only = false (full bundles, as before).
        "bot_champions_in_world": True,
        "champion_map_icon": True,
        # 2026-10-25 16:12 (tester: the back-to-base button does nothing): a recall skill in slot 6 (script 0x3400000A,
        # its block as 0x100008E4); channel seconds G (stat 14), icon unknown (0 = none)
        # 0x2029 shows the base champion for a costume pick (portrait kept). 2026-10-25 17:52 (tester: the second map's
        # load stuck at 10 % after a costume pick of Atomic Green Lantern): the client then expected the base champion
        # while the match carried the costume; off. The portrait comes from the client's variant -> base map
        # (0xabd0a0 -> 0xa25430, value +0x20 of a hash entry, filled by a message not found yet)
        "lobby_slot_base_for_costume": False,
        # 2026-10-25 (match-load-sequence.md, C reads): 0x20ED entries carry the champion's parent pack in f0 (it was
        # 0xFFFFFFFF, which can keep LoadMatchData from finishing: the 10 % hang) and each costume its own grid icon in
        # f9 (it was 0: the champion select portrait went blank after a skin pick, P)
        "champion_data_match_pack": True,
        "enter_match_check_packs": True,
        "objects_on_level_loaded": True,       # lobby matches: objects at 0xCC / 35 % (not at 10 % after 10 s)
        "objects_level_max_wait": 30.0,       # 0x20AF: drop 0 / unknown pack ids (one unknown id fails the client's load)
        "champion_data_costume_icon": True,
        "pre_start_leash": 12.0,               # m from the start point before the match begins, on maps with no gates
        "usable_objects": True,                # 0x20EE command 1: use a pad (its template's 0x100009BC skill -> slot 9)
        "usable_reach": 3.0,
        "script_teleport_snaps": True,
        "stealth_reveal_attribute": True,      # 2026-10-25 19:28: a revealed stealth champion gets 0x100006F3 (its effect stops)
        "cast_repeat_guard": 0.4,              # s: a second order of one slot this soon after a cast is ignored
        "item_skill_blocks": True,             # 2026-10-25 19:28: an item's active skill block in 0x100008E5.. (its button)         # 2026-10-25 19:28: a script teleport bumps the teleport sequence
        "recall_skill": True,
        "recall_script": "0x3400000A",
        # tester report 2026-10-29 15:30 (recall: "it sounds and teleports but the animation does not show"; traffic
        # 14:31:53.788: the channel fx 0x10000223 (fx 0x1E00009C, 8 s) went with Fidgets_Disable 0x10000320 and, 30 ms
        # later, Emote_Abort 0x100001F2 on the champion, which end its run): a StartScriptlet of these scripts is held
        # for its duration variable as a looping key (re-sent with its own run number after the scriptlets that follow
        # it, resend_looping_after_scriptlet) until its StopScriptlet. [] = as before
        "start_scriptlet_hold": ["0x3400000A"],
        # 2026-10-30 (tester report 15:30: "the 6 lights around the champion in the recall animation don't appear";
        # core-door-regen.md 6, C traffic 16:39:25.962-16:39:31.324: the fx went at once, then four "again" re-sends
        # with the SAME run number at +0.03 / +0.28 / +0.31 / +5.36 s; client-scriptlets-graphs.md 1.4, C: a live run's
        # number is a signal to it, its list-2 handlers run, and nothing on the client replaces a run; the streaks are
        # the fx's type-3 spawn, a timed client object built by 0xA847E0 from 0x10000940-0x10000945 / 0x100008D7, P
        # ended by those signals, while the glow lives on): "defer" = the held key goes ONCE, start_scriptlet_hold_defer
        # s after the scriptlets of its own tick (Fidgets_Disable, Emote_Abort), never re-sent; its StopScriptlet ends it
        # as before. "resend" = the fase3-ij hold (glow seen, no streaks)
        "start_scriptlet_hold_mode": "defer",
        "start_scriptlet_hold_defer": 0.12,
        "recall_seconds": 8.0,
        "recall_icon": 0,             # 2026-10-25 16:12: the local champion carries its template's 0x10000083
        # 2026-10-25 (map-objectives-recipes.md 1 / 4 / 5, tester: no Raider, Leviathan or cannon on the maps): the bosses
        # and scheduled objectives of ics/match/bosses.py. Classes, radii, kill buffs, line keys and the cannon's
        # 65 / 120 s and 4 impacts are data (C); the spawn times and positions are authored (G). {} on a map = none.
        "match_raider": {"crime_alley": {"cls": "0x40000CA2", "at": 300.0, "respawn": 300.0, "pos": [80.0, 97.66],
                                         "yaw": 180.0, "warn": {"-30": 696, "-10": 699}, "spawned": 698,
                                         "killed_event": 61, "other_line": 701,
                                         "scriptlets": ["Vfx_Spawn_Event01", "Vfx_Active"]}},
        # 2026-10-29 (tester report 23:03: "when I killed the Raider the announcer said the enemy had also killed it";
        # traffic 22:49:46.463 event 61, 22:49:49.383 line 0x2BD = 701 to the same player; turret-heads-coredeath.md 3,
        # C sets): a boss's killed_event (61: only the acting team's line 697) goes when the local team killed it, its
        # other_line (701 "the enemy defeated the Raider") when the other team did; never both. false = both (fase3-io)
        "match_boss_kill_voice_by_team": True,
        "match_pods": {"gotham_divided": {
            "cls": "0x40000A79", "at": 600.0, "warn": {"-60": 685, "-30": 683, "-10": 684}, "landed": 681,
            "pods": [[105.0, 105.0], [55.0, 55.0]], "capture_radius": 6.0, "capture_seconds": 10.0,
            "raider": {"cls": "0x40000938", "after": 60.0, "warn": {"-30": 696, "-10": 699}, "spawned": 698,
                       "killed_event": 61, "other_line": 701,
                       "scriptlets": ["Vfx_Spawn_Event01", "Vfx_Spawn_PhasingComplete", "Vfx_Active"]},
            "seismic": {"upper": [686, 690, 688, 689], "lower": [691, 687, 692, 693]},
            "leviathan": {"cls": "0x40000937", "pos": [80.0, 80.0], "lines": [660, 653, 662, 652], "killed_event": 60,
                          "respawn": 360.0, "respawn_warn": {"-60": 658, "-30": 659, "-10": 663}}}},
        "match_cannon": {"gotham_heights": {"cls": "0x40000511", "at": 0.0, "pos": [80.0, 74.0], "radius": 4.1,
                                            "seconds": 10.0, "neutral": 65.0, "lock": 120.0, "impacts": 4,
                                            "strike_delay": 5.0, "final_delay": 31.0, "small_radius": 4.5,
                                            "large_radius": 13.1, "strike_damage": 400.0, "tier_team_health": 125.0,
                                            "detected": 406, "online": 419, "massive": 418, "fired_event": 54,
                                            "tracker_slot": 1, "tracker_category": 27}},
        # 2026-10-25 (tester's video 16:12: black shapes on the ground at Crime Alley's team-1 dampener, Gotham Divided's
        # gates and pits, Coast City's middle; black-ground-shapes.md, C: terrain sockets with no model in them): the
        # cover models the server places (CA: the structure socket 0x2E00119F, as Tutorial 2 fills the same socket, P;
        # GD pits: the lid 0x2E0003F0 as a server object with 0x2A1 = true, P; Coast City still open)
        "match_socket_covers": {
            # 2026-10-25 17:47 (tester: the octagon stayed with 0x2E00119F, an attach point with no geometry;
            # map-object-census.md fix 1, P): the zone pack's 10 x 20 x 2 m box 0x2E0000E3, which nothing places
            # 2026-10-25 19:28 (tester: what was placed at the towers' base is not right): none on Crime Alley for now
            # 2026-10-25 (crime-alley-props.md B.1, P): once more, the 0x2E0000E3 box flush with the street (top at
            # 200 m: z 198), yaw 0, no team, 0x2A1 = true; it also closes the funnel's north end (tester's image 10)
            # 2026-10-25 22:07 (test-2026-10-25-2207.md CA-1: a pale untextured slab): not the right piece; none again
            # 2026-10-28 (crime-alley-structures.md recipe 2b, G look: the textured core pedestal 0x2E000A3B, about 21 x
            # 20 m, the only textured piece big enough for the 10 x 15 m socket; the pale box 0x2E0000E3 was rejected)
            # 2026-10-28 (tester: the pedestal is not it either): none
            "crime_alley": [],
            # Gotham Divided: the pit box 0x2E0003F0 (10 x 10 x 2.5 m, pack 0xA00000FC) on both pits and the six base
            # lane-exit sockets (map-object-census.md fix 2 / 3, P)
            # 2026-10-28 (tester report 2026-10-28 15:00; map-audit-all.md 9.2 / 11): each lid names the terrain site
            # under it ("terrain_site", icserver/terrainfix.py); with [ics] match_socket_covers_skip_flat a lid whose
            # socket python ic.py patch has flattened is left out (its top, 249.97, would be coplanar with the street)
            "gotham_divided": [{"world_state": "0x2E0003F0", "pos": [x, y, z], "yaw": 0.0, "props": {"0x2A1": True},
                                "team_by_side": False, "terrain_site": site}
                               for x, y, z, site in (
                                   (55.0, 55.0, 247.5, "gotham_divided_pits"), (105.0, 105.0, 247.5, "gotham_divided_pits"),
                                   (40.0, 150.0, 247.47, "gotham_divided_lane_exits_team1"),
                                   (35.0, 125.0, 247.47, "gotham_divided_lane_exits_team1"),
                                   (10.0, 120.0, 247.47, "gotham_divided_lane_exits_team1"),
                                   (150.0, 40.0, 247.47, "gotham_divided_lane_exits_team2"),
                                   (125.0, 35.0, 247.47, "gotham_divided_lane_exits_team2"),
                                   (120.0, 10.0, 247.47, "gotham_divided_lane_exits_team2"))],
            "coast_city": []},
        # 2026-10-28 (tester report 2026-10-28 15:00; map-audit-all.md 9.2 / 11, C: [game] terrain_sockets now flattens
        # team 1's Gotham Divided lane exits in the pack, and a lid there would z-fight with the street): a socket cover
        # whose "terrain_site" is flattened in the installed pack is not placed (read-only probe of the pack, cached;
        # a pack that cannot be read counts as not flattened). false = every cover as before
        "match_socket_covers_skip_flat": True,
        # 2026-10-25 (tester's screenshots of the original: meteorites in the craters and parked vehicles that Super
        # Strength lifts, carries and throws, then a yellow phase-in respawn; crime-alley-props.md A): no client data
        # places them (C), so the server spawns them (classes / packs C, positions G from the frames; z 0 = navmesh).
        # The lift plays the sub-skill's sequence natively (ics/match/liftables.py): damage / status / range per kind C.
        "liftable_props": True,
        "liftable_props_by_map": {"crime_alley": [
            # 2026-10-26 (tester: the meteorite sits at the same height as its base 0x2E000D25, both look merged): 0.5 m up
            {"kind": "rock", "class": "0x400005C9", "world_state": "0x2E000D22", "pos": [x, y, 200.5], "yaw": 0.0}
            for x, y in ((80.1, 72.8), (54.7, 82.9), (105.0, 82.7), (72.0, 92.5), (88.0, 92.5))] + [
            # 2026-10-26 (tester's gallery screenshots: modern set south to north = sports car 0x2E000559, police car
            # 0x2E0008B8, white SUV 0x2E000795; gaslight = arrow cart EFE, lamp pickup F03, van F04, convertible F05): the
            # white SUV by the right camp, the gaslight van by the left one
            # 2026-10-26 18:3x (tester's frames, ours vs the original's, measured from the stealth tiles): the SUV lies
            # east-west (nose east) ~2 m east / 2 m south of where it stood; the van along the building west of the left
            # jungle mouth, east-west (G from frames)
            # 2026-10-28 (tester's frames of the original, left and right jungle mouths: the SUV stands up-left of the right
            # mouth's field, its long axis tilted ~25 deg down to the east; the gaslight truck up-right of the left field,
            # tilted ~25 deg up to the east, i.e. the SUV's mirror image; G from the frames, screen x = +x, up = +y)
            # 2026-10-28 15:00 (tester report: "without turning that vehicle, just move it a little closer to the wall";
            # vehicle-lift-and-position.md 1, C navmesh edges + .entity box 0x2D00061C): 0.33 m along the wall's normal
            # (0.41, 0.91), same yaw; its long side is ~0.21 / 0.26 / 0.32 m (rear / middle / front) from the raised wall
            # north of it, was 0.54 / 0.59 / 0.64 m. Was [102.3, 93.6, 0.0]. (Frames 35 / 37: the original's SUV faces
            # the other way, yaw ~65; kept at 245 as asked.)
            {"kind": "vehicle", "class": "0x4000045D", "world_state": "0x2E000795", "pos": [102.43, 93.90, 0.0], "yaw": 245.0},
            # 2026-10-29 12:45 (tester report 2026-10-29 12:45: "this vehicle is still a little away from the wall" = the
            # gaslight truck; throw-truck-padlock.md 3, C navmesh edges): 0.45 m along the wall's normal (-0.42, 0.91),
            # same yaw; its long side is 0.18 / 0.21 / 0.27 m (rear / middle / front) from the wall north of it, was
            # 0.62 / 0.65 / 0.71 m. Was [57.7, 93.6, 0.0]
            {"kind": "vehicle", "class": "0x4000081B", "world_state": "0x2E000F04", "pos": [57.52, 94.01, 0.0], "yaw": 115.0}]},
        # 2026-10-29 (tester report from the original-game video, frames 64 / 65 / 68 / 70; power-core-turret.md 6): more
        # parked vehicles. No pack places a vehicle on Crime Alley (crime-alley-props.md A.1, C; checked again), so the
        # positions are G from the frames (57 px/m across, ~47 px/m up, calibrated on the turrets / rocks / stealth
        # tiles), each long side ~0.23 m off the navmesh's curb (edge + agent radius 0.525), as the others; yaw = nose
        # heading - 90 (the model's +y is its nose). Police car by the red base's north curb, nose west (64 / 70); the
        # gaslight pickup on the south curb west of the blue middle turret, nose east (68 / 69); the red modern vehicle
        # (P: the sports-car class, the only modern one left) on the south curb between the red turrets, nose west
        # (65; the pickup's mirror); the blue-base mirror of the police car is G only (no frame), off.
        # {} = only liftable_props_by_map
        "liftable_props_added_by_map": {"crime_alley": [
            {"kind": "vehicle", "class": "0x40000459", "world_state": "0x2E0008B8", "pos": [124.5, 81.9, 0.0], "yaw": 90.0},
            {"kind": "vehicle", "class": "0x4000081A", "world_state": "0x2E000F03", "pos": [52.4, 72.8, 0.0], "yaw": 270.0},
            # 2026-10-29 (tester report 21:10, frame 76 of the original: "this is the vehicle that must appear; the one
            # that appears is white"; power-core-turret.md 8.4): the red car with the white top is not the sports car
            # 0x2E000559 (white in game) but, G, the gaslight convertible 0x4000081C / 0x2E000F05 (red body, white soft
            # top; the only Crime Alley vehicle class left whose colour the tester has not named). Same spot and yaw.
            # Was {"class": "0x40000454", "world_state": "0x2E000559"}
            {"kind": "vehicle", "class": "0x4000081C", "world_state": "0x2E000F05", "pos": [107.4, 72.8, 0.0], "yaw": 90.0},
            # 2026-10-29 (tester report 21:10, frame 72 of the original at 00:02: "here goes the first vehicle"; a dark
            # old truck parked on the north curb above the blue x 40 turret; power-core-turret.md 8.3): G the gaslight
            # truck 0x4000081B / 0x2E000F04 (the left camp's), centre 4.6 m west of the x 40 ring (frames 72 / 66 / 67:
            # x 35.4-36.7), long side 0.7 m inside the north edge (82.55), as the police car; nose east (G). Was the
            # disabled police-car mirror 0x4000081C at (35.5, 81.9)
            {"kind": "vehicle", "class": "0x4000081B", "world_state": "0x2E000F04", "pos": [35.5, 81.85, 0.0], "yaw": 270.0}]},
        # sent as changes after creation (Super Strength's target check 0x9d01d0: flags & 0x82, 0x10000AA7, 0x10000029)
        "liftable_props_extra": {"rock": {"0x1000019D": 0x22}, "vehicle": {"0x1000019D": 0x1080},
                                 "all": {"0x10000AA7": True, "0x10000029": True}},
        "liftable_spawn_scriptlets": {"vehicle": ["Vfx_Spawn_Event01"], "rock": ["_Entity_OnEnterWorld_Default", "Vfx_Active"]},
        "liftable_respawn_scriptlets": {"vehicle": ["Vfx_Spawn_Event01"], "rock": ["Vfx_Fade_In", "Vfx_Active"]},
        "liftable_respawn_seconds": 60.0,      # G (tester: "every so often")
        # 2026-10-28 09:36 (tester: Consume on a vehicle / meteorite does not make it vanish and it can still be lifted):
        # IsKind reads an object's own kind flags (0x1000019D); Consume's IsKind [0x82] then destroys the rock / vehicle,
        # which fades out and respawns after liftable_respawn_seconds
        "kind_flags_from_entity": True,
        # 2026-10-29 10:23 (tester: a consumed vehicle / meteorite vanished about a second after Consume's animation and
        # with no effect): its _HFSM_DestroyEntityAction plays when DestroyEntity runs and it goes at the script's own
        # delay + liftable_consume_remove_after s (0.6 before, with only Vfx_Fade_Out, which vehicles lack)
        # 2026-10-29 11:00 (tester: turrets attack but give no vision): allied structures reveal by range only (their
        # centre is in a navmesh hole, so the line-of-sight check from it always failed); false = as before
        "fog_structure_by_range": True,
        # 2026-10-29 (tester report 19:55: "sometimes the enemy champion inside our vision range is not drawn until it
        # attacks me"; ca-ring-fog-bundles.md 3): the server's sight line ignores the squares objects block on the match
        # navmesh (structures 3.2 m in the middle of the lane, liftable vehicles, closed gates): the client's fog does
        # not stop at a turret either. false = those squares block the line, as before
        "fog_line_through_objects": True,
        # 2026-10-29 14:40 (tester: the stealth look stays seconds after leaving a field; and inside a field enemies must
        # lose sight unless I attack them or they enter it): stealth_stop_hard = on leaving, event 0x11F stops the
        # shimmer at once (besides the signal); stealth_reveal_when_hit false = taking damage no longer reveals
        "stealth_stop_hard": True,
        "stealth_reveal_when_hit": False,
        "liftable_consume_destroy_action": True,
        "liftable_consume_remove_after": 0.0,
        # 2026-10-25 23:40 (tester: no vehicle seen, not even the gallery's seven; the meteorites, creation type 7, show):
        # the vehicles go with creation type 7 and are sent again 1 s and 3 s later (Tutorial 1's DestVehicle rule)
        "liftable_creation_type": {},          # 2026-10-26: off again (the world-state form below is Tutorial 1's)
        # 2026-10-26 12:51 (tester's /tour: still no vehicle): vehicles go as their bare world state, as Tutorial 1's
        # vehicles that show ("entity" = the 0x40... class as before)
        # 2026-10-26 13:40 (tester's vitrina: no vehicle drew in either form): the exe patch's carrier class 0x4A + low
        # bits ("carrier"; needs python ic.py patch, as Tutorial 1's street vehicle)
        # 2026-10-26 14:05 (tester: with the carrier vehicles the game closed while loading the map): off again; the
        # carrier is tried one object at a time in a match with "vitrina N p"
        "liftable_class_mode": {},
        "liftable_resend": {"vehicle": [1.0, 3.0]},
        # 2026-10-26 (destructible-vehicles.md, C cause: a destructible (0x800) is drawn only through its pieces, built by
        # the client itself only for creation types 6 / 9; the original server sent 0x8B): event 0x8B to the vehicle
        # (rebuild intact) at these s after its creation, while it is whole; layout cell 0xFB for the vehicles
        "destruction_reset_event": True,
        "destruction_reset_delays": [0.3, 1.1, 3.1],
        "liftable_cell": {"vehicle": 0xFB},
        # 2026-10-25 22:07 (tester: the meteorites have no crater under them; crime-alley-still-missing.md 8, P
        # substitute): the Tutorial's lava crater world state under each meteorite
        # 2026-10-25 23:03: off (its pack 0xA000024C hung the load at 10 %); {} = no crater
        # 2026-10-26 13:40 (tester's vitrina 114: world state 0x2E000D25 is the base under the liftable meteorites)
        # 2026-10-29 tester report 21:10 ("the meteorites lack a red aura"; liftable-aura-lift-throw-break.md 1, C data):
        # the base's table 0x1D0004AA holds only Vfx_Active_State1-3 / Vfx_Stop, so the three names below were never
        # sent (World.scriptlet drops a key the object lacks); its idle state is Vfx_Active_State1 (particle 0x18000A31,
        # P meaning). ["Vfx_Startup", "Object_Closed", "Vfx_Active"] = as before (nothing sent)
        "liftable_bases": {"rock": {"world_state": "0x2E000D25", "scriptlets": ["Vfx_Active_State1"],
                                    "z_offset": -0.5}},   # 2026-10-26: on the ground, the meteorite 0.5 m above it
        # 2026-10-29 tester report 21:10 (same; liftable-aura-lift-throw-break.md 1, C 0xA7B0D0 / table 0x1D000385, P that
        # the original's red is this tint): kind -> {colour, base_on, base_off}: the object's team colour while it lies
        # pickable (override 0x10000CF0 = colour, then a PVP_Team change 3 -> 0 so the client runs
        # _Entity_OnSetClientRelationship: 5 = red 0x16000E7D), team 3 (TeamColor Null) once lifted, again on respawn;
        # base_on / base_off = the crater's keys at those moments. {} = no tint (as before)
        "liftable_aura": {"rock": {"colour": 5, "base_on": [], "base_off": []}},
        # 2026-10-29 tester report 23:03 ("the meteorites' red aura is not the correct one", 73 / 83;
        # scorecard-accolades-meteor-aura.md 2): the tint above recolours the rock's team-colour parts (red lines); the
        # original's floating red halo is not reached by any key of the rock's own tables (C), and the "orb children"
        # 0x2E000D13 / D14 are the relay's 7 m capture plate (C bbox, spawned by the relay table 0x1D0004A1). A logged
        # sequence of candidates on a lying object for one test run: [{"at": s, "kind": "rock", "target": "object" |
        # "base", "key": name, "force": bool, "colour": n}, ...]; [] = none (the docs note lists a ready probe)
        "liftable_aura_probe": [],
        "liftable_bases_tutorial_crater": {"rock": {"world_state": "0x2E0004BE", "scriptlets": ["Vfx_Active"],
                                    "offset": [-3.2, -0.3]}},   # the crater mesh sits ~(3.2, 0.3) m off its origin (catalog)
        # m from the champion to the object for the lift (2026-10-26, grab-arm-carry.md 2: from 6 m it jumped onto him)
        "liftable_reach": 4.5,
        "liftable_carry_speed": 3.5,           # m/s while carrying (icserver: the hands-up walk is slower)
        "liftable_carry_height": 2.1,          # m above the champion's feet
        "liftable_throw_arc": 3.0,             # m, a vehicle's lob
        "liftable_throw_steps": 8,
        # 2026-10-29 12:45 (tester report 2026-10-29 12:45: "the throw still looks as if thrown straight"; G frames of
        # the run: the vehicle crossed ~6 m in 0.4 s near hand height and vanished before it came down;
        # throw-truck-padlock.md 2): liftable_throw_speed = m/s along the ground per kind (vehicle = 0x34000161's
        # MissileVelocity 15.0, C; was KINDS' 16 / 15.5); liftable_throw_min_seconds = the shortest flight per kind
        # (0 = dist / speed, as before); liftable_throw_step_seconds = one state per this many s (0 = liftable_throw_steps
        # states, as before); liftable_land_delay = s between the last state and the landing (explosion / fade) per
        # kind, the client draws a state ~0.1 s late (C 0x552130; {} = at the last state, as before)
        "liftable_throw_speed": {"vehicle": 15.0, "rock": 15.5},
        # 2026-10-29 tester report 21:10 ("the throw also looks slow, like frame by frame"; liftable-aura-lift-throw-
        # break.md 3): the vehicle's shortest flight 0.5 s (was 0.8; 0x34000161 MissileVelocity 15 m/s gives 0.6 s at its
        # 9 m range) and a state every tick (0.033 s, was 0.05: the 0.05 s steps went on the 30 Hz tick as 33 / 66 ms)
        "liftable_throw_min_seconds": {"vehicle": 0.5},
        "liftable_throw_step_seconds": 0.033,
        # same report (C 0x57E530 / 0x57DA90 / 0x552130): kinds whose flight states are the curve at their own send time
        # with its 3D velocity (heading, |v|, motion pitch bit 0x40), so the client dead-reckons along the arc between
        # states; [] = the fixed steps with the horizontal speed only (as before)
        "liftable_throw_velocity": ["vehicle", "rock"],
        "liftable_land_delay": {"vehicle": 0.15},
        # 2026-10-29 12:45 (same report: "the throw range and the target area are not shown"; throw-truck-padlock.md 1,
        # C client script 0x340001A3 / handler 0xa2a1b0): 0x20F9(slot, 0) shows the throw sub-skill's range ring and
        # target area for the whole carry, 0x20F9(slot, 1) hides it at the throw / drop; false = never sent (as before).
        # liftable_throw_indicator_delay = s after the carry is ready (the slot table must be on the client first)
        "liftable_throw_indicator": True,
        "liftable_throw_indicator_delay": 0.05,
        # tester report 2026-10-29 15:30 (the range and the target area still do not show; throw-padlock-coredeath.md 1,
        # C client 0xa5dab0): the 0x20F9 path draws only while the client is already targeting that slot (its gate
        # slot == HUD controller +0x90 +0xEC; node 0x10000056's flag is 0 in 0x340001A3), never during a carry. S->C
        # 0x2180 (u8 0 | u32 slot, handler 0xa6d800) starts the slot's indicator with no gate (0xa39360: range ring,
        # stat-23 ring, cursor area, kept on the cursor by 0xa29680) and 0x217F (u8 0 | u32 slot | u8, 0xa5d070 ->
        # 0xa4f0c0) ends it. liftable_throw_indicator_messages: which of "0x2180" / "0x20F9" go (["0x20F9"] = fase3-ih)
        "liftable_throw_indicator_messages": ["0x2180", "0x20F9"],
        # 2026-10-29 tester report 19:55 ("I lifted a meteorite but could not throw it; only after casting a Q";
        # liftable-carry-throw-press.md 1, C traffic 19:52:23.369 / 24.096): the throw indicator waits for the slot's
        # "kept ready" 0x20F8 (Super Strength's own cooldown start, 1.2 s into the lift), as in the vehicle carry that
        # threw normally; at most this many s (0 = liftable_throw_indicator_delay after the hold, as before)
        "liftable_indicator_after_cooldown": 1.5,
        # same report (C traffic 19:52:29.131-44.831: 13 presses of slot 7 as 0x20EA 0x10000023, no 0x20EE): the n-th
        # press in a row of the carry slot that no throw order follows within liftable_throw_press_window s throws
        # toward the champion's facing (0 = only the client's order throws, as before)
        # 2026-10-30 tester report 11:23 ("with Super Strength the throw button does not work directly: I have to click
        # and press"; liftable-softlock.md 4, C traffic 11:07:38.732 / 41.925 and 11:13:24.694 / 26.569: every
        # unanswered press waited for a second one, 3.2 / 1.9 s later): the first unanswered press throws (every answered
        # press of the run had its 0x20EE 34-66 ms after the 0x20EA, well inside the 0.35 s window); 2 = as before
        "liftable_throw_on_press": 1,
        "liftable_throw_press_window": 0.35,
        # 2026-10-30 tester report 15:30 ("the vehicle must land where I aim while carrying it; when that zone is out of
        # range the champion must walk until it is in reach and then throw; now it is thrown straight ahead";
        # liftable-throw-walk-to-range.md, C traffic 16:38-16:57: every carry slot press of the run was an unanswered
        # 0x20EA and thrown toward the facing by liftable_throw_on_press; C 0xa25d80: the vehicle throw skill
        # 0x480003C9 has skill bool 0x100006D5, with which the client refuses a point farther than its range (stat 23,
        # 9 m) + 0.5 m with Skill_InvalidTarget 0x1000003C and sends no order):
        # liftable_throw_far_order: the throw table sent in the carry slot has 0x100006D5 = 0, so the client sends the
        # far point (false = the data's 1, as before)
        "liftable_throw_far_order": True,
        # liftable_throw_walk: kinds whose throw order beyond the range walks the carrier (carry speed, navmesh path)
        # until the point is within range, then throws at that point, as an out-of-range skill does; any other order
        # (move, stop, attack, another skill) cancels the walk and keeps the carry. [] = thrown at once, clamped to the
        # range along the line (as before). The rock's rubble throw is a line (targeting 13): it always flies its range
        "liftable_throw_walk": ["vehicle"],
        # the walk gives up after this many s (and when no path exists): thrown toward the point, clamped to the range
        "liftable_throw_walk_timeout": 8.0,
        # the unanswered-press throw (liftable_throw_on_press) goes at the last point a throw order of this carry named
        # (the aimed zone, walking to it if needed) instead of the facing; false = always the facing, as before
        "liftable_press_aim": True,
        # tester report 2026-10-29 15:30 (the thrown vehicle "still flies in a straight line and disappears";
        # throw-padlock-coredeath.md 1.3, C 0x60B5F0 / P effect): a state within 2 m is only steered (0x5C9FE0, a
        # displacement on the character body), and the arc never showed in two runs; each flight state now carries a
        # newer teleport sequence (seq A), which makes the client place it exactly (0x5C9E90 snap), so the lob is drawn
        # state by state ([ics] liftable_throw_snap: kinds; [] = steered, as before)
        # 2026-10-29 tester report 21:10 (liftable-aura-lift-throw-break.md 3): the rock too (its carry states were
        # already snapped, liftable_carry_snap; its flight was steered); ["vehicle"] = as before
        "liftable_throw_snap": ["vehicle", "rock"],
        # tester report 2026-10-29 15:30 (the vehicle does not explode; throw-padlock-coredeath.md 1.4, C script
        # 0x3400015F S2 / S4): the original's landing ran Vfx_OnInit, Vfx_OnExplode, Destructible_IgnoreAOI on the
        # vehicle and DestructionImpulse (sphere, DestructionRange 4.0, DestructionMagnitude 10, level 3) at once and
        # again DestructionDelayDuration 0.15 s later, which breaks the vehicle's destruction pieces (0x8A, sent to the
        # vehicle). liftable_land_scriptlets: kind -> keys at the landing (fase3-ih: Vfx_OnExplode only);
        # liftable_land_impulse: kind -> {radius, magnitude, level, again} ({} = none, as before)
        # (Vfx_OnInit is in none of the vehicles' tables 0x1D000612 / 34B / 111: left out)
        # 2026-10-29 tester report 21:10 ("on impact the vehicles disappear and you hear the explosion";
        # liftable-aura-lift-throw-break.md 4, C 0x530FA0 / 0x62ED00 / 0x62EBF0 + diag 21:08:27): the vehicles'
        # Vfx_OnExplode deletes every intact piece's render instance and physics body (a destructible vehicle is drawn
        # only through them) before the 0x8A impulse looks for the bodies: it is no longer sent at the landing
        # (liftable_land_explode sends it later if wanted). ["Vfx_OnExplode", "Destructible_IgnoreAOI"] = as before
        "liftable_land_scriptlets": {"vehicle": ["Destructible_IgnoreAOI"]},
        # same report: kind -> s after the landing for Vfx_OnExplode (after the impulse; {} = never)
        # 2026-10-30 tester report 12:05 ("the vehicle simulates crashing but does not disappear: the explosion sounds,
        # then it stays there a few seconds"; liftable-lift-throw-wreck.md 2, C traffic 12:01:37.475-47.996: the break
        # keys at +0.2 s, nothing removed the pieces, the 0x3 at +10.5 s): Vfx_OnExplode goes 0.55 s after the break
        # keys, so the crash and its fire play on the intact wreck first, then every piece (and the effects on it, C
        # 0x62EBF0 -> 0x62E6E0 on piece+0x50) is removed: the wreck goes with the explosion, and the client runs the
        # destruction record's "all pieces gone" scriptlet itself (record+0x70, C 0x62EBF0; P = Destructible_On
        # CompletelyDestroyed 0x10000290, the record's only non-piece key). {} = never (the wreck stays until the 0x3)
        "liftable_land_explode": {"vehicle": 0.75},
        "liftable_land_impulse": {"vehicle": {"radius": 4.0, "magnitude": 10.0, "level": 3, "again": 0.15,
                                              "after_rebuild": 0.05}},
        # 2026-10-29 tester report of 18:31 ("the vehicle's destruction animation is not generated";
        # docs/re-notes/liftable-throw-destruction.md 3 / 4): liftable_land_rebuild = kinds whose pieces are rebuilt by
        # 0x8B on the landing frame before the impulse (C 0x630FC0 / 0x62DBA0: the piece bodies are made at the entity's
        # frame when built, the last build was at the launch; 0x8A's sphere query 0x631C50 must find them at the landing),
        # the impulse liftable_land_impulse "after_rebuild" s later ([] / 0 = as before); liftable_land_destroy_after =
        # kind -> s after the landing for DestroyEntity's actions (0x3400015F S4 after DestructionDelayDuration 0.15, C),
        # liftable_destroy_actions = the keys its client execute plays (script-nodes-names.md 0x10000010, C; the
        # vehicles' table 0x1D00034B holds only the Optional one; also played on Consume); {} / [] = none, as before.
        # liftable_detach_rebuild_attached_only: the launch's 0x8B only for an object that rode the containment attach
        # (a vehicle carried by its own states was rebuilt in mid-air at the launch; false = always, as before)
        "liftable_land_rebuild": ["vehicle"],
        "liftable_land_destroy_after": {"vehicle": 0.15},
        "liftable_destroy_actions": ["_HFSM_DestroyEntityAction", "_HFSM_DestroyEntityAction_Optional"],
        "liftable_detach_rebuild_attached_only": True,
        # 2026-10-29 tester report 19:55 ("on impact the vehicle does not do its exploding animation"; liftable-carry-
        # throw-press.md 3, C traffic 19:49:48.879-49.109: every landing key went, nothing showed): the pieces' own break
        # keys (the client plays them only when 0x8A breaks a piece, never seen) go to the landed object
        # liftable_land_break_after s after the landing ({} = none, as before; P: doubled if the impulse breaks too)
        "liftable_land_break_keys": {"vehicle": ["Destructible_OnBreak_Front_T1", "Destructible_OnBreak_Back_T1",
                                                 "Destructible_OnBreak_Left_T1", "Destructible_OnBreak_Right_T1",
                                                 "Destructible_OnBreak_Middle_T1",
                                                 "Destructible_OnCompletelyDestroyed"]},
        "liftable_land_break_after": 0.2,
        # 2026-10-29 tester report of 18:31 ("throwing the vehicle looks as if animations were skipped";
        # liftable-throw-destruction.md 2, C traffic 18:33:34.340): the throw's turn went as a full champion bundle (a
        # slot table changed during the carry) 0.13 s before ThrowObject; now the movement state alone, the tables follow
        # with the slot restore after the clip. Delta mode only (object_update_mode "delta"); in "bundle" mode every
        # champion update is a full bundle anyway and stays so. false = World.update as before
        "liftable_throw_face_motion_only": True,
        # OnCastSignal 3 / 5 / 2 of the sub-skills (s; icserver lift_step / throw_windup)
        # 2026-10-26 (grab-arm-carry.md 2, C clips): per kind "<kind>_grab / _hold / _release / _end" override the clip
        # times in ics/match/liftables.py KINDS; locomotion_after = s after the throw's end for _Combat_GoToLocomotion
        "super_strength_cast_signals": {"locomotion_after": 0.6},
        # the object rides the champion's hand (parent block of its movement state, C format, P values); {} = bundles
        "liftable_attach": {"mode": 16, "point": "0x100000B0", "b1": 0, "b2": 1},
        "liftable_hit_events": True,           # CbtState_DisableHit / EnableHit around the carry
        # 2026-10-28 12:56 (tester: a lifted vehicle vanishes over the champion; liftables-camps-animations.md 1, C code /
        # P result): a destructible's pieces get render instances only through 0x8B; 0x8B again after the attach builds
        # them under the champion (0x630FC0's contained branch) and after the detach in the world for the flight.
        # kind -> s after the attach / detach bundle; {} = none (as before)
        "liftable_attach_rebuild": {"vehicle": [0.05]},
        "liftable_detach_rebuild": {"vehicle": [0.0]},
        # 2026-10-30 (tester reports 2026-10-30 11:23 / 12:05: the vehicle lift "robotic, as if animations were skipped";
        # docs/re-notes/vehicle-lift-old-vs-ics.md 3.1, old icserver vs ics message streams): the catch's 0x8B (above)
        # only for an object that rides the containment attach. 0x8B clears and rebuilds the pieces (0x631050, C) and a
        # vehicle carried by its own states (liftable_attach_kinds []) moves its pieces with its frame (C), so the
        # rebuild re-made the vehicle 0.07 s into the catch clip; Tutorial 1's lift never sent one (as the launch's,
        # liftable_detach_rebuild_attached_only). false = always, as before
        "liftable_attach_rebuild_attached_only": True,
        # 2026-10-28 13:52 (tester: a lifted vehicle sits merged with the champion's body at ground level instead of over
        # his head, vanishes while he walks and shows again when he stops; vehicles-carry-collision.md 1):
        # liftable_attach_kinds: kinds carried through the containment attach (it puts the child at the champion's
        # origin: the script's AttachmentOffset is not on the wire); the others ride over the head by their own
        # bundles (["rock", "vehicle"] = the fase3-ie behaviour; 2026-10-29: with liftable_vehicle_toss the vehicle is
        # then attached at the catch, as at the old grab frame);
        # liftable_carry_offset: kind -> [right, forward, up] m from the champion's feet (vehicle = 0x34000161's
        # AttachmentOffset (0, 0, 2.5), C; the rock script 0x34000177's is (0, 1.4, 1.4), the rock keeps 2.1 up);
        # liftable_no_dest: a carried / flying object gets no destination of its own (it was walked by World.tick and
        # re-sent as a full bundle every tick, with the attach block when attached; false = as before);
        # liftable_carry_resend: s between carry bundles while walking (a turn > liftable_carry_turn rad or a speed
        # change goes at once; it was one per 0.3 m)
        # 2026-10-29 10:53 (tester: a lifted meteorite stays on its spot; the champion takes it but is not seen
        # carrying it): the client attach block does not move it either; rocks are carried by server bundles over the
        # head like the vehicles (["rock"] = the client attach as before)
        "liftable_attach_kinds": [],
        # 2026-10-29 14:40 (tester: the meteorite must sit in the palm of AGL's green arm, not over his head): the rock
        # script 0x34000177's own AttachmentOffset (0, 1.4, 1.4) = in front of the chest (forward = local y, P)
        # 2026-10-29 tester report 2026-10-29 17:45 ("the meteorite must go higher, like in the palm of AGL's hand";
        # agl-arm-meteor-vehicle-tilt.md 2.2, C: AGL's attach point 0x100000B0 is on bone 31 RWeapon; in the six
        # 0x1A001131-0x1A001136 hold clips (P: SM_SuperStrength_Rubble's Hold blend) that bone sits at right 0.5-0.85,
        # forward 0.1-1.0, up 2.2-2.6 m): the rock on the palm = the hand + ~0.45 m (G: the rock's half height).
        # [0.0, 1.4, 1.4] = fase3-ik
        "liftable_carry_offset": {"vehicle": [0.0, 0.0, 2.5], "rock": [0.7, 0.4, 2.75]},
        # 2026-10-29 tester report 2026-10-29 17:45 ("usually it has an animation spinning in the palm"): kind -> [deg/s,
        # step s] the held rock turns about its vertical axis (facing offset, one movement state per step; it keeps
        # turning in the throw); P: nothing in the rock's own tables turns it. {} = no spin (as before)
        "liftable_hold_spin": {"rock": [180.0, 0.1]},
        # 2026-10-29 tester report 2026-10-29 17:45 ("the vehicle falls lying flat, not with the front tilting down to hit
        # and explode"): kind -> {sign, max, land} the thrown object's facing pitch (0xB0 motion bit 0x400) along its curve
        # (rad, clamped to +-max; the last state = land, nose down; sign -1 if the client's pitch turns the other way, P).
        # {} = flat as before
        "liftable_throw_pitch": {"vehicle": {"sign": 1.0, "max": 0.9, "land": -0.6}},
        "liftable_no_dest": True,
        # 2026-10-29 tester report 19:55 ("the carry and walking with the vehicle are still not smooth";
        # liftable-carry-throw-press.md 2): 0.05 s (was 0.5) while walking, each state snapped (liftable_carry_snap)
        "liftable_carry_resend": 0.05,
        # 2026-10-29 tester report 19:55 (same; liftable-carry-throw-press.md 2, C 0x60B5F0: a state within 2 m is
        # only steered by the character body, which loses the height over the head): kinds whose carry states carry
        # a newer teleport sequence ([] = steered, as before)
        "liftable_carry_snap": ["vehicle", "rock"],
        "liftable_carry_turn": 0.1,
        # 2026-10-28 15:00 (tester report: the vehicle lift "starts lifting and then cuts to already holding it";
        # vehicle-lift-and-position.md 2, C log bytes + graph data + script 0x34000161): fase3-ie put the vehicle over
        # the head in ONE state 3.4-4.2 m away 0.1 s into the lift (the client places a state > 2 m away at once) and
        # sent PickupObject 0x100007A1 while the graph was in Car_Pickup, which has no transition for its PickupCar
        # (only Hold has, to Car_Catch): the catch never played. Now 0x34000161's own order (ics/match/liftables.py):
        # liftable_vehicle_toss: the vehicle is lobbed onto the champion and caught (false = the fase3-ie order);
        # liftable_car_pickup_at: s after the lift for graph event CarPickup (Pickup_Start -> Car_Pickup); 0.05 = the
        # original's Vfx_Event9 0x100000E9 (its type-0x23 group at 0.05 s); "graph" (or < 0) = Car_Pickup's start frame
        # from the champion's graph (0.45 s for AGL: the whole bend-and-grab, a 0.4 s longer lift);
        # liftable_toss_seconds: Car_Pickup's grab hook (code 3) -> the catch = 0x34000161 TossDuration 0.3 +
        # CatchDuration 0.35 (C defaults; never before the graph's Hold);
        # liftable_toss_steps / liftable_toss_arc: states of the flight (each well under 2 m) / m above the straight line
        # (G: a 70 deg lob over ~2.3 m rises ~1.6 m);
        # liftable_attach_seconds: catch -> ready to throw (AttachmentDuration 0.1, C);
        # liftable_toss_scriptlet: S7's RunScriptlet on the vehicle (VFX_CBT_Hit_Shared, variable 0x100002F8 =
        # ObjectPickupScriptlet 0x1E0000BE; C script, P effect); {} = none
        # 2026-10-29 tester report of 18:31 ("picking up the vehicle looks as if animations were skipped";
        # liftable-throw-destruction.md 1, C graph data): CarPickup at 0.05 s cut Pickup_Start (the bend and grab, clip
        # 0 -> 0.45 s, cropEnd 0.783 of a 1.233 s clip = it ends exactly on Car_Pickup's start frame 0.45) through an
        # Instant transition: the clip jumped 0.05 -> 0.45. "graph" = Car_Pickup's start frame from the champion's own
        # graph (AGL 0.45, chr_batman 0.4103): the whole bend, no jump, ready to throw at 1.21 s instead of 0.81 s.
        # 0.05 = fase3-if .. fase3-il (the original's Vfx_Event9 timing, P)
        "liftable_vehicle_toss": True,
        # 2026-10-29 tester report 21:10 (liftable-aura-lift-throw-break.md 2, C scripts 0x34000161 S7 / 0x34000177 S3):
        # Super Strength's 0x100000BB (its input back, the slot's "kept ready" 0x20F8 that the throw indicator waits for)
        # at the toss / the rock's grab, as the sub-skills raised it, not raise_event_follow's 1.2 s; false = as before
        "liftable_input_back": True,
        # same report (C traffic 21:10:08.328: a throw order 0.35 s into a vehicle lift was dropped and the client sent
        # no order for the next press): an order during the lift throws once the carry is ready; false = dropped
        "liftable_throw_early_queue": True,
        "liftable_car_pickup_at": "graph",
        # 2026-10-29 tester report 21:10 ("lifting meteorites and vehicles still looks a bit slow"; liftable-aura-lift-
        # throw-break.md 2, C script 0x34000161: S7 -> S8 on TossTimer 0.3, S8 -> S9 on CatchTimer 0.35, and S7 / S8 ->
        # S9 at once on 0x10000002, the lob's landing raised by its script 0x34000160): the lob flies TossDuration 0.3 s
        # and is caught when it lands (never before the graph's Hold + 0.05 s, so AGL's catch moves 1.11 -> 0.875 s and
        # the carry is ready at 0.975 s). 0.65 / 12 = as before (the timers' upper bound)
        "liftable_toss_seconds": 0.3,
        "liftable_toss_steps": 9,
        "liftable_toss_arc": 1.5,
        "liftable_attach_seconds": 0.1,
        "liftable_toss_scriptlet": {"key": "0x10000223", "vars": {"0x100002F8": "0x1E0000BE"}},
        # 2026-10-28 13:52 (tester: champions and minions walk through the parked vehicles; in the original they block;
        # vehicles-carry-collision.md 2): a parked vehicle's footprint is blocked on the match's navmesh (server paths go
        # round it; the client has no movement prediction of its own). World state -> [half length, half width (,
        # angle offset from the heading)], G sizes from the frames; + liftable_blocker_margin m (a walker's radius);
        # {} = off
        # 2026-10-28 15:00 (tester report: move the SUV closer to the wall; vehicle-lift-and-position.md 1.2 / 1.4): the
        # SUV's is its .entity box 0x2D00061C (half 1.0 x 2.5, centred 0.177 m forward = the optional 4th element,
        # forward offset; C data, P footprint: every vehicle box is 1.0 x 2.5); was [2.5, 1.05]
        # 2026-10-29 12:45 (tester report 2026-10-29 12:45, the truck moved to the wall; throw-truck-padlock.md 3): the
        # truck's is its .entity box 0x2D000C8F (half 1.0 x 2.5, centre 0, C), as the SUV's; was [2.8, 1.15] (G)
        "liftable_blockers": {"0x2E000795": [2.5, 1.0, 0.0, 0.177], "0x2E000F04": [2.5, 1.0, 0.0, 0.0], "0x2E000559": [2.25, 0.95],
                              "0x2E0008B8": [2.4, 1.0], "0x2E000EFE": [2.2, 1.0], "0x2E000F03": [2.5, 1.0],
                              "0x2E000F05": [2.4, 1.0]},
        "liftable_blocker_margin": 0.35,
        # 2026-10-29 tester report 2026-10-29 14:40 (the lift of vehicles and meteorites looks as if animations were
        # skipped; docs/re-notes/agl-qer-lift.md 4, C traffic 14:21:34.997 / 39.093): the "faces the object" / "throws"
        # bundle and the pickup / throw 0x8D went in the same millisecond, and the client applies a movement state 0.1 s
        # after its stamp (0x60B5F0) but an 0x8D at once, so the turn landed 0.1 s into the 0.30 s rubble pickup (and the
        # throw) clip. The pickup / throw key and its whole timeline now go this many s after the facing bundle (as
        # champion_scriptlet_delay does for skills); 0 = in the same tick as before
        "liftable_face_lead": 0.13,
        # 2026-10-28 12:56 (tester: the meteorite lift / throw has no proper animation; liftables-camps-animations.md 2,
        # C log): full champion bundles went in the middle of the clips (the throw-skill slot table 0.27 s into the
        # rock's pickup, credits / XP bundles during the carry, Super Strength back 0.29 s into the throw).
        # liftable_throw_skill_at_lift: the throw skill rides in the lift's facing bundle (false = at the Hold state);
        # liftable_hold_champion_bundles: other champion bundles wait until the carry ends (false = sent at once);
        # liftable_slot_restore_delay: s after the throw's end for Super Strength's slot table + held bundles (0 = at once)
        "liftable_throw_skill_at_lift": True,
        "liftable_hold_champion_bundles": True,
        "liftable_slot_restore_delay": 0.9,
        # ---- 2026-10-30 tester report 11:23 (the Super Strength soft-lock: "after the first vehicle, a lifted car or
        # meteorite kept me from moving until I threw it, and it would not let me throw; then Super Strength never worked
        # again"; docs/re-notes/liftable-softlock.md, C server.log / traffic.log 11:07-11:17)
        # liftable_input_back_per_lift: Super Strength's input back 0x100000BB once per LIFT (fase3-io kept its "sent" mark
        # on the slot's script instance, which lives for the whole match, so only the first lift of the match ever sent
        # it: from the second on 0x34000164 stayed in S4 with its input hold (22 / 16 / 24 "move refused (crowd
        # control)" in the carries of 11:10:20, 11:10:48, 11:13:19) and never ran StartCooldown (no 90 s cooldown, the
        # throw indicator 1.5 s late); false = once per instance, as before
        "liftable_input_back_per_lift": True,
        # liftable_lift_guard: Super Strength lifts only a lying object that is the order's own target: not one in flight,
        # landed (broken) or gone, and not through a stale TargetIID (the VM keeps the last one when an order has none:
        # 11:16:33.659, a slot-7 order with target 0x0 0.68 s after a throw re-lifted the rock in flight, which landed and
        # was removed in the champion's hands); a refused lift ends 0x34000164 (0x10000009) so it never keeps its input
        # hold. false = only "in props and not carried", as before
        "liftable_lift_guard": True,
        # liftable_keep_base_block: the throw skill's slot table is built over the slot's REAL Super Strength table; a
        # lift whose previous carry's restore was still pending (liftable_slot_restore_delay) took the throw table as
        # the "Super Strength" one, so the end of that carry put the throw table back for good (11:16:59.425: a 1432-byte
        # "Super Strength again" = the rubble throw's table; every later press sent target 0x0 and 0x34000164 went S2 ->
        # S0). false = as before
        "liftable_keep_base_block": True,
        # liftable_watchdog: every tick, a carrier whose object is gone / removed is released at once; a lift not ready
        # after liftable_lift_timeout s is made ready; a throw not ended after liftable_throw_timeout s is ended; a ready
        # carry longer than liftable_carry_timeout s is thrown toward the champion's facing (liftable_carry_timeout_action
        # "throw") or dropped where he stands ("drop"); 0 = no limit; and a slot table still the throw skill's
        # liftable_restore_timeout s after the carry ended is set back to Super Strength. false = none, as before
        "liftable_watchdog": True,
        "liftable_lift_timeout": 3.0,
        "liftable_throw_timeout": 3.0,
        "liftable_carry_timeout": 20.0,
        "liftable_carry_timeout_action": "throw",
        "liftable_restore_timeout": 2.5,
        # 2026-10-30 tester report 11:23 ("lifting and throwing the vehicle still looks robotic, in parts, as if
        # animations were skipped"; liftable-softlock.md 6): fase3-im's motion-only throw turn (liftable_throw_face_motion
        # _only) works only in "delta" mode, and object_update_mode went back to "bundle" on 2026-10-29 10:28, so every
        # throw since sent a FULL 1450-byte champion bundle 0.13 s before ThrowObject, in the middle of the Hold clip
        # (C traffic 11:07:42.267, 11:10:27.564, 11:10:54.726). The client applies a 0xB0-only state in bundle mode too
        # (object-update-bundles.md 0.5 / 11.2, C): the turn now goes as the movement state alone; false = as before
        "liftable_throw_face_motion_bundle": True,
        # same report: the vehicle's toss onto the champion went as liftable_toss_steps states precomputed at fixed
        # fractions but sent on the match tick (~68 ms), two of them in one tick (C traffic 11:07:36.758 / .759,
        # .897 / .897), so it hopped; now one state per liftable_throw_step_seconds at the curve's own send time, as the
        # throw flight (liftable_throw_velocity); false = the fixed states, as before
        "liftable_toss_timed": True,
        # 2026-10-30 tester report 12:05 ("the vehicle lift animation still looks weird, and the throw too";
        # liftable-lift-throw-wreck.md 1, C traffic 12:01:35.114-.424): the timed toss states went with speed 0 and no
        # newer teleport sequence, so the client steered toward a target that stood still between states, 0.1 s behind,
        # dropping the height (throw-padlock-coredeath.md 1.3); kinds whose toss states are snapped and carry the curve's
        # 3D velocity (as liftable_throw_velocity), from the toss's first frame ([] = as before)
        "liftable_toss_velocity": ["vehicle"],
        # same report (C server code): at the throw the carried object turns and stops with the champion (one carry
        # state on the hold point) instead of keeping its last carry state until the launch frame; false = as before
        "liftable_throw_turn_object": True,
        # 2026-10-25 22:07 (tester: lifted, never thrown: the client sent no second press): while carrying, the slot's
        # client skill table is the sub-skill's (ground target + range ring), as icserver's Tutorial 1 throw skill
        "liftable_throw_skills": {"vehicle": "0x480003C9", "rock": "0x480004A2"},
        # test aid: every Crime Alley vehicle class in a row behind the blue base (x 8), to name the SUV and the truck
        "liftable_gallery": False,
        "liftable_gallery_classes": [["0x40000454", "0x2E000559"], ["0x40000459", "0x2E0008B8"],
                                     ["0x4000045D", "0x2E000795"], ["0x40000C40", "0x2E000EFE"],
                                     ["0x4000081A", "0x2E000F03"], ["0x4000081B", "0x2E000F04"],
                                     ["0x4000081C", "0x2E000F05"]],
        # Gotham Divided's dampeners stand on the base lane-exit sockets (team 1; mirrored); the gates step back
        "match_dampener_sockets": {"gotham_divided": {"north": [40.0, 150.0], "mid": [35.0, 125.0],
                                                      "south": [10.0, 120.0]}},
        "gd_gate_setback": 8.0,
        # map key -> extra 0x20AF packs. 2026-10-25 22:07: Crime Alley loads the Tutorial pack 0xA000024C for the lava
        # crater 0x2E0004BE under the meteorites (liftable_bases)
        # 2026-10-25 23:03 (tester: the load hung at 10 % with the Tutorial pack 0xA000024C in Crime Alley's 0x20AF): none
        "match_extra_packs": {},
        # 2026-10-26 (deep-scan-maps.md 1.5, C graph 0x1A000B15): the dampener's graph Death on its death (Respawn
        # 0x100003FD when it comes back)
        "dampener_graph_events": {"death": "0x100001C0", "respawn": "0x100003FD"},
        # 2026-10-28 (tester: three towers a side, the original has two; crime-alley-structures.md, C): structure roles a
        # map does not spawn (Crime Alley has no core turret: core, dampener at x 40 / 120, lane turret at 65 / 95)
        # 2026-10-29 (tester report from the original-game video, frames 66 / 67 / 70: "there is another turret before the
        # core"; the original announces "The enemy's Power Core Turret has been destroyed!" = event 55; power-core-turret.md
        # 1-2): Crime Alley has a third tower a side, the Power Core Turret (v AI 0x40000C8F, ws 0x2E000AC4, 3500 HP / team 2
        # 0x40000C8D, 3000 HP, C classes) on the core platform's prow; it is spawned again. {"crime_alley": ["core_turret"]}
        # = the 2026-10-28 two-tower layout
        "match_skip_roles": {},
        # 2026-10-29 (same report; power-core-turret.md 2, G +-1 m from frames 66 / 67 / 70 at the camera's 57 px/m and the
        # minimap of frame 66: ~9.5 m east of the core, where the prow leaves the round platform; was the map spec's
        # Tutorial 2 spot 25.5 / 134.5): map -> role -> {"1" / "2": [x, y]} ({} = the map spec's positions)
        "match_structure_pos": {"crime_alley": {"core_turret": {"1": [27.0, 77.5], "2": [133.0, 77.5]}}},
        # 2026-10-29 (tester report 23:03: "the turret near the core has neither the body nor the base, only the blue
        # transparent effects"; fase3-io's Vfx_Fade_In did not help; turret-heads-coredeath.md 2, C data / P look): the
        # blue Power Core Turret's world state 0x2E000AC4 (rig env_pvp_powercore_turret_a_body) has the lane turret's
        # bones but no body mesh node (the lane body 0x2E000AA0 has Lane_Turret_A), so only its hologram parts draw. Its
        # twin 0x40000C8E (same template: 3500 HP, 35 / 185, regen 50, range 9) uses the lane body 0x2E000AA0, as the red
        # Power Core Turret 0x40000C8D already does by data. map -> role -> {"1" / "2": class}; {} = the map spec's
        # 2026-10-30 tester report 12:05 ("the tower's base is not the correct one"; original frames 66 / 67: a glossy
        # blue cylinder under the flag hologram, not the lane turret's dark body and ring head; turret-head-pct-look.md
        # 2, C data): the blue one is the data's 0x40000C8F / 0x2E000AC4 again: its own parts are the cylinder
        # 0x2E000A9A (Vfx_Active child) and the flag head 0x2E000AC3 (Vfx_AI_Active child), the original's shapes;
        # Object_Reset (match_structure_scriptlets) for the cylinder's fill (P). Was {"crime_alley": {"core_turret":
        # {"1": "0x40000C8E"}}} (fase3-ip..ir)
        # 2026-10-30 tester report 13:00 (screenshot 89: the blue Power Core Turret vanished, only the translucent
        # cylinder 0x2E000A9A and the health bar; turret-pct-composite.md, C data / G frames): 0x2E000AC4 has no mesh
        # node of its own, so on it only the hologram children ever drew (frames 71 / 82 / 89, three builds). Back to
        # the twin 0x40000C8E (same stats, the lane body 0x2E000AA0 that drew solid in 88), now without the gear plate
        # and with the PCT's own parts made by the server (match_turret_heads: flag 0x2E000AC3, match_structure_parts:
        # cylinder 0x2E000A9A). The red one is 0x40000C8D = the same lane body by data, so both sides match.
        # {} = the data's 0x40000C8F (fase3-is, with "core_turret" scriptlets ["Vfx_Fade_In", "Vfx_Active",
        # "Vfx_AI_Active", "Object_Reset"], no core_turret head / parts)
        "match_structure_classes": {"crime_alley": {"core_turret": {"1": "0x40000C8E"}}},
        # 2026-10-29 (same report, frame 70: the destroyed Power Core Turret leaves its base with the team's dot and the two
        # fallen rings; power-core-turret.md 4, C table 0x1D00035F): roles whose body stays when destroyed (until it
        # respawns), and the scriptlets played on it at its death (its _Defeat_OnDead raises graph event Death
        # 0x100001C0 and plays Vfx_Destruct_State0), match_structure_death_delay s after the death bundle.
        # [] / {} = the body goes after corpse_seconds with no scriptlet, as before
        # 2026-10-30 tester report 18:12 ("the first 2 towers have no destruction animation: at 0 HP they stay there and
        # disappear a few seconds later"; docs/re-notes/turret-death-head-rearm.md 2; traffic 18:11:11.741 "turret mid
        # t1 dead", 18:11:15.751 removed, nothing between): the lane turret (0x2E000AA0, the same body as the Power Core
        # Turret's 0x40000C8E) got no death key and went after corpse_seconds. Its world-state table 0x1D00035D holds
        # _Defeat_OnDead = run Vfx_OnExplode (the blast) + a type-9 branch + graph event Death 0x100001C0; its graph
        # env_pvp_lane_turret_a_body_behavior's Death state plays the 0.1 s die_a pose under a rigid-body / powered
        # ragdoll modifier (the rings fall by physics; no end state, no fade, no clip but die / idle 5.98 s), as the
        # Power Core Turret's that the tester saw fall (frame 70 of the original keeps its fallen rings). So lane
        # turrets keep their wreck for the rest of the match (they never respawn), and Vfx_Stop (base table 0x1D000372:
        # stops Vfx_Active, Vfx_Targeting, Vfx_Event1 and Vfx_AI_Active = its client-made head and hum) follows the
        # death. Was ["core_turret"] / {"core_turret": ["_Defeat_OnDead"]} (fase3-in)
        "match_keep_body_roles": ["core_turret", "turret", "inner_turret"],
        "match_structure_death_scriptlets": {"core_turret": ["_Defeat_OnDead"],
                                             "turret": ["_Defeat_OnDead", "Vfx_Stop"],
                                             "inner_turret": ["_Defeat_OnDead", "Vfx_Stop"]},
        "match_structure_death_delay": 0.3,
        # 2026-10-29 (same report, frames 66 / 67: a blue rotating ring around the core; frame 70: none round the red core
        # once its Power Core Turret fell; power-core-turret.md 3, C table 0x1D00098A: Vfx_Indestructible 0x1000008E spawns
        # child 0x2E000A3A, Vfx_Indestructible_Stop 0x1000013D stops it): the core plays "on" while a structure of
        # "roles" of its team lives (delay s after the core's own keys), "off" when the last one falls; {} = off
        "match_core_shield": {"roles": ["core_turret"], "on": ["Vfx_Indestructible"], "off": ["Vfx_Indestructible_Stop"],
                              "delay": 1.2},
        # 2026-10-29 (same report: "super minions until it respawns"; no respawn time in the data, G = the dampener's
        # match_dampener_respawn): s until a destroyed Power Core Turret comes back (0 = stays down)
        "match_core_turret_respawn": 300.0,
        # 2026-10-29 (same report; power-core-turret.md 5, C classes in the CA pack 0xA00002E7): while a team's Power Core
        # Turret is down, the enemy's waves bring the v AI family's elites (flag 0x400000, as GD's Destroyer / elites):
        # Elite Soldier 0x40000C9C for the melee pair, Elite Trooper 0x40000C9B for the ranged pair. {} = off
        # 2026-10-29 (tester report 21:10: "the super minions appear when the second turret is destroyed, not the third";
        # power-core-turret.md 8.6): off; they come with the second structure (match_supers_on_structure_down). Was
        # {"crime_alley": {"melee": "0x40000C9C", "ranged": "0x40000C9B"}}
        "match_core_turret_supers": {},
        # same report: while the enemy's second structure of a lane (Crime Alley: the x 40 / 120 dampener; "inner_turret"
        # when match_role_swaps turns it into one) is down, this team's waves on that lane bring the elites (Elite
        # Soldier 0x40000C9C for the melee pair, Elite Trooper 0x40000C9B for the ranged pair, C classes); they stop when it
        # respawns (match_dampener_respawn, 300 s; the same structure's own data rule: dampener down -> elites).
        # map -> {"roles", "melee", "ranged"}; {} = off
        "match_supers_on_structure_down": {"crime_alley": {"roles": ["dampener", "inner_turret"],
                                                           "melee": "0x40000C9C", "ranged": "0x40000C9B"}},
        # 2026-10-28 (tester's screenshot of x 40: "that tower is not it either; the one there is the same as at the start
        # of the lane"): Crime Alley's x 40 / 120 structure is a second lane turret (inner, with plate and head)
        # 2026-10-29 (tester report 21:10, frames 72 / 77 of the original: the x 40 / 120 turret stands on a round ring
        # pedestal with a dark legged body and the stacked hologram head, not on the lane turret's gear plate;
        # power-core-turret.md 8.2): that is the dampener class 0x40000C88 / 0x40000C87 itself (C: world state 0x2E000E04,
        # rig env_pvp_dampener_a = ring, body, six legs; table 0x1D00063A: Vfx_AI_Active spawns the head 0x2E000AA8; attack
        # 0x34000014, 3000 HP), on the socket the terrain patch now flattens (crime_alley_dampeners). No swap any more.
        # {"crime_alley": {"dampener": ["inner_turret", "turret"]}} = the 2026-10-28 lane turret there
        "match_role_swaps": {},
        # 2026-10-26 (deep-scan-maps.md 1.7, C keys / Tutorial 2 positions, P in PvP): the minion spawner on each lane mouth
        "match_map_objects": {"crime_alley": [
            {"world_state": "0x2E000D03", "pos": [21.75, 77.5, 200.23], "yaw": -90.0, "team": 1, "side": 3,
             "scriptlets": ["Vfx_Active_State0", "Vfx_Spawner_Tier01"]},
            {"world_state": "0x2E000D03", "pos": [138.3, 77.5, 200.41], "yaw": 90.0, "team": 2, "side": 5,
             "scriptlets": ["Vfx_Active_State0", "Vfx_Spawner_Tier01"]},
            # 2026-10-29 (tester report 2026-10-29 12:45 + frame of the original at 00:28: the base hologram stands on a
            # stone pedestal with a glowing disc; ca-holes-pedestal-turrets.md P1, C data): Tutorial 1's statics place
            # the hologram pedestal 0x2E000A36 (ctype 8, mesh 0x1700142A, team-colour table 0x1D00038B) 6.30 m west of
            # its base platform, yaw 90 (block 0x13CB (159.2, 37.5) vs 0x2E000A35 at (5.5, 37.5)); Crime Alley's statics
            # have the same neighbours (0x2E00121A, 0x2E00081F) but no pedestal. Placed the same distance from Crime
            # Alley's platforms 0x2E000CA5 (5.5 / 154.5, 77.5); remove these two entries to go back
            # 2026-10-29 14:40 (tester's screenshot: the disc sits about 1.3 m west of the hologram's feet): x +1.3 / -1.3; 16:40 (tester: "a little more forward"): +0.5 more; 18:45 (tester: "move the base a little down"): y -0.6
            {"world_state": "0x2E000A36", "pos": [1.0, 76.9, 200.21], "yaw": 90.0, "team": 1, "side": 3,
             "scriptlets": ["Vfx_Startup", "Vfx_Active_Blue"]},
            {"world_state": "0x2E000A36", "pos": [159.0, 76.9, 200.21], "yaw": -90.0, "team": 2, "side": 5,
             "scriptlets": ["Vfx_Startup", "Vfx_Active_Red"]}]},
        "match_dampener_keep_body": True,      # map-objectives-recipes.md 5.4 (Object_Deactivate, C keys)
        "match_point_attack": True,            # owned GH points / held Device shoot (0x340000D5, range 9, C)
        "match_point_attack_range": 9.0,                 # m (SkillRange of 0x340000D5)
        # 2026-10-25 (map-objectives-recipes.md 5.3; lines C, kill rule P, leaders' camps / effects G): Gotham Divided's
        # beacons are tracker slots won by killing a buff destroyer (Regen 0x40000940 slot 1, Haste 0x4000093D slot 2,
        # Heavy Mauler 0x4000093E -> Pulse slot 3, Surveillance 0x4000093F slot 4); first kill = activated, second =
        # upgraded; status (G) on the team's champions for `seconds`. {} = the earlier captured beacons 0x400003AF.
        "match_beacons": {"gotham_divided": {
            "seconds": 180.0, "category": 29, "decoration": 9, "player_slots": {"3": 1, "4": 2},
            "camp_leaders": {"0": "0x40000940", "1": "0x4000093D", "3": "0x4000093F"},
            "by_class": {"0x40000940": {"name": "regen", "slot": 1, "icon": "0x1300256D", "lines": [674, 677],
                                        "status": "0x4800028B"},
                         "0x4000093D": {"name": "speed", "slot": 2, "icon": "0x1300256A", "lines": [676, 675],
                                        "status": "0x4800082E"},
                         "0x4000093E": {"name": "pulse", "slot": 3, "icon": "0x1300256D", "lines": [679, 678]},
                         "0x4000093F": {"name": "vision", "slot": 4, "icon": "0x1300256A", "lines": [680, 680]}}}},
        # 2026-10-25 (map-runtime-state.md 1, C: the sector tracker draws a padlock for lock 3 and has no animation for
        # contender 3): lock 0 while capturable, the last capturing team as contender when both are on the point
        "match_victory_voice_skip": ["gotham_divided", "coast_city"],   # their end cinematics voice it
        "match_tracker_initial": {"crime_alley": [{"slot": 1, "category": 26}]},
        "match_structure_ping": 5.0,           # s between 0x2008 under-attack pings of one allied structure (0 = off)
        # 2026-10-25 (hud-shop-timeline-kills.md, C): the shop's Recommended row at the link; timeline start = f64 now and
        # the strip's events; the pre-start clock counts down to the match start
        "recommended_at_link": True,
        "announcer_entity_fields": True,
        # 2026-10-25 (hud-shop-timeline-kills.md 5.3, C reader 0x9326C0): the kill card in the client's layout with the
        # damage of this life by attacker / slot / type ("old" = the fase3-hs layout)
        "kill_card_layout": "reader",
        # 2026-10-25 (hud-shop-timeline-kills.md 6): per-champion match stats (damage by type, healing, kills by target
        # type, credits / XP by source) filling the end page's 0x2045 rows
        "match_stats_ledger": True,
        # 2026-10-26 19:53 (tester: the game froze and closed at the end of a match, before the stats screen; the filled
        # 0x2045 rows went for the first time): empty rows again until their layout is checked against the reader
        # 2026-10-28 13:52 (tester: the end cinematic plays, then the score screen shows no data; timeline-kda-endscreen.md
        # 3): the 19:53 crash was the 0x219E standings handler (end-screen-crash.md, fixed in fase3-id), so the filled
        # rows go again; false = the empty rows (team 0, no upgrades: the Flash scorecard never gets all its data)
        "end_stats_from_ledger": True,
        # 2026-10-28 13:52 (same report; C: 0xA795E0 -> 0xA3AC70 sends Flash UpdateCurrentUpgrades / UpdatePowerGraphValues
        # per row, keyed by the row's account IID, only when the row's upgrade list +0x2FC is not empty, and
        # ScorecardManager waits for one of each per row): each row gets its own account IID and its 6 artifact slots,
        # plus the champion DID (+0x1C) and level (+0x20). false = account 0 / empty list (the fase3-ie rows)
        "end_stats_unique_accounts": True,
        "end_stats_upgrades": True,
        # 2026-10-26 (end-stats-2045.md: our bytes parse to the end; the crash is P in the client's team grid 0xA72860,
        # which runs only for rows of team 1 / 2): false = filled rows with team 0, to tell the two apart in a test
        "end_stats_team": True,
        # 2026-10-28 12:56 (tester: "the match ended (I surrendered), the score screen should appear" - the game crashed
        # instead; end-screen-crash.md, C): 0x219E carried the encounter DID in the rank slot and the client indexes a
        # byte table by rank with no bounds check (0xA37DEE). "reader" = the handler's order; "old" = fase3-ic order
        "standings_layout": "reader",
        "kill_card_damage_ledger": True,
        "bot_name_prefix": "AI: ",              # the original's bot names ("AI: Gaslight Batman"); "" = "<champion> Bot"       # 0x2039 carries both champions' class / icon / name / voice id (kill banner)
        "timeline_start_time": True,
        # 2026-10-28 13:52 (tester: the match starts and the strip's first red mark comes seconds later;
        # timeline-kda-endscreen.md 1, C): the 'now' of the strip's notices is the wall clock (clock() stood 5.35 s
        # behind during the load) and an event's time is now + (its match time - the match time now)
        "timeline_wall_now": True,
        # same report: when the intro's end moves the start, the strip's marks are removed (0x100002AC) and placed again
        "timeline_rebase": True,
        # same report (C log: jungle lines at 60 s, the camps and the mark at 45 s on Crime Alley): the jungle lines
        # count from the camps' real first time (match_camps_first_by_map)
        "match_jungle_lines_follow_camps": True,
        # 2026-10-30 (tester report 13:18: hovering a strip mark shows a black box with only the countdown; the original
        # also shows the picture of what comes; timeline-tooltip-camp-prespawn.md 1, C): per event "icon" = the tooltip's
        # picture (didExaminationIcon: an image DID, or "melee" / "camps" / "raider" / a class DID whose
        # Character_Billboard_Icon 0x100001FC is read from the data: CA drones 0x13000F9D, Tripods / Raider 0x13001A37),
        # "strip_icon" = the strip's own icon (absent = the default marker in its colour, as before), "title" = the
        # tooltip's title (our words; "" = none). The Raider ("at": "raider" = match_raider[map].at) is new on the strip.
        # match_timeline_icons false = icons 0 (fase3-ir).
        "match_timeline": {"start": {"at": 0, "severity": 1, "title": "Match start"},
                           "drones": {"at": "waves", "severity": 2, "icon": "melee", "title": "Drones"},
                           "jungle": {"at": "camps", "severity": 3, "icon": "camps", "title": "Jungle Creatures"},
                           "raider": {"at": "raider", "severity": 2, "icon": "raider", "title": "Raider"}},
        "match_timeline_icons": True,
        "match_clock_prestart_countdown": True,
        "match_tracker_lock": True,
        "match_tracker_contested": True,
        "match_kill_buffs": True,              # template 0x10000AC2 of a boss -> every champion of the killer's team
        "match_kill_buff_seconds": 120.0,      # not in the buff records (O)
        "match_boss_kill_events": {"0x40000430": 62},   # Doomsday Guardian (Coast City) -> 0x2039 event 62
        "bot_brains": True,
        # 2026-10-25 22:07 (tester: a dead bot slides until it respawns, walks back lying down, is invisible until it
        # attacks): the 0xB0-only state is not applied by the client; the throttled updates go as full bundles
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 0.5 / 11.2, C: it is applied; the
        # bot stayed hidden because its fog flag 0x90F went only in full bundles): superseded by object_update_mode
        # "delta" (the throttled state + every changed property, the fog flip included); read only in "bundle" mode
        "bot_motion_only": False,
        # 2026-10-25 22:07 (server.log: AI: Katana cast Super Strength on the champion, which lifts only map objects)
        # 0x3400019D (2026-10-26 19:25, tester: "many red lanterns chase my champion"): AI: Zod cast Surveillance Camera
        # 0x48000523 on the champion at every cooldown, 32 cameras on top of him
        "bot_skip_scripts": ["0x34000164", "0x3400019D"],
        "bot_attack_speed_actual": True,       # 2026-10-26: bots' 0x100006FE = the attack rate the server uses
        "bot_cast_stop_state": True,           # 2026-10-26: a stop state before a bot's cast, as the local champion's
        # 2026-10-26 19:51 (tester: a respawned bot still walks to its lane lying down): the get-up graph event at these
        # s after the respawn bundle, the later ones with these scriptlets (back to locomotion)
        "bot_getup_delays": [0.0, 0.6],
        # 2026-10-26: _Defeat_OnRespawn, the real get-up (deep-scan-animations.md 1). 2026-10-28 15:00 (tester report
        # 2026-10-28 15:00, traffic 14:49:57.564-58.188: a bot's respawn sent _Defeat_OnRespawn four times, twice at each
        # get-up delay, as World.get_up already sends it; death-animation.md 7): [] = get_up's one per delay.
        # ["_Defeat_OnRespawn"] = fase3-ie.
        "bot_getup_scriptlets": [],
        "bot_shop_in_base_only": True,         # 2026-10-25 22:07: a bot bought in mid lane after a cut recall
        "bot_player_objects": False,           # (not built yet) a player object per bot if the nameplate has no name
        "bot_retreat_health": 0.3,             # health share that sends a bot back to base
        "bot_decision_interval": [0.5, 0.8],   # s between decisions (0x3A000026 GetBestPerceivedTargetInterval, C)
        "bot_reaction": 1.0,                   # x the decision interval (higher = slower bots)
        "bot_skill_chance": 1.0,               # chance a decision tries a skill before the basic attack
        "bot_aggression": 1.0,                 # x own health share an enemy champion's must be under to be chased
        "bot_sight": 9.0,                      # m a bot looks for targets in
        "bot_behind_minions": 3.0,             # m a bot keeps behind its lane's leading minion
        "bot_vision_radius": 12.0,             # allied bot's fog vision source (template 0x10000133 = 12.0, C)
        "bot_vitals_hz": 4,                    # a regenerating bot's vitals at most this often
        "bot_shopping": True,
        # 2026-10-25 16:12 (tester: bots buy nothing, get stuck): start credits, shopping while dead, recall (slot 6)
        # when retreating farther than this from base, re-route after this long without moving
        "bot_recall_distance": 25.0,
        "bot_inventory_messages": True,        # 2026-10-25 17:47: a bot's 0x20E2 inventory after each buy
        "bot_stuck_seconds": 3.0,                  # buys its loadout's recommended artifacts in order at base
        "bot_lanes": {"gotham_divided": ["north", "north", "mid", "south", "south"]},
        # ---- 2026-10-28 15:00 (tester report 2026-10-28 15:00; docs/re-notes/test-2026-10-28-1439-sweep.md, the log sweep
        # of the Crime Alley v AI run against AI Atomic Wonder Woman, items S1-S10; each key below dates from that report).
        # false / 0 = the fase3-ie behaviour of each.
        # 2026-10-28 15:00 (S1: the match froze 2.77 s at AWW's first Savage Sweep while creation_type(0x2E0009F0) built
        # the 22 MB pack 0xA00000DF's record list on the game thread): a lookup that reads a window from a record's start
        # builds no record list (Data.prepare builds the skipped ones off the game thread)
        "record_start_only": True,
        # 2026-10-28 15:00 (S3: AWW's sweep helper 0x40000CD6 took her basic attack 0x34000257 from record 0x480006D4,
        # 32 KB past its template, and "attacked" GL x7; 7 of the 78 skill-spawned classes): unit_attack / unit_stats
        # stop at the template's end
        "template_window_bounded": True,
        # 2026-10-28 15:00 (S2: Match.tick clamped dt to 1 s, so after the freeze waves, camps, lines, the Raider and the
        # end ran 1.8 s behind the HUD clock and the timeline): the match clock follows the wall clock (up to 10 s a tick)
        "match_clock_follows_wall": True,
        # 2026-10-28 15:00 (S4: AWW's basic attack started inside her Savage Sweep and cut it: no damage, no cooldown,
        # recast at once): a bot's / unit's basic attack (and its chase) waits while one of its skills is in its cast, and
        # a bot's skill order clears its attack target first, as the player's does
        "attack_waits_for_cast": True,
        "bot_cast_clears_attack": True,
        # 2026-10-28 15:00 (S4: the bot's Vault cut its empowered basic attack SmitingStrike): a bot casts no skill while
        # its basic attack (slot 0) is in its cast, for at most this many s (0 = off)
        "bot_skill_waits_basic": 1.5,
        # 2026-10-28 15:00 (S4, same family; tests/test_match.py: the AI AWW's brain cast Vault 0.5 s into Savage Sweep's
        # 1 s cast): a bot casts no skill while another of its skills is in its cast (World.casting_skill); false = it
        # may (fase3-ie)
        "bot_skill_waits_cast": True,
        # 2026-10-28 15:00 (S5: 10 of 16 "casts Smite" did nothing, the Smite buff waited for a basic attack the bot never
        # made, and the bot stuttered 4.5 s next to GL): a bot's skill use its script does not take fails, and the bot
        # leaves that slot alone for bot_untaken_skill_backoff s, so it attacks
        "bot_cast_needs_taker": True,
        "bot_untaken_skill_backoff": 1.0,
        # 2026-10-28 15:00 (S5): the "skill used" broadcast 0x10000196 {Slot} (passives counting uses, kit-audit-2.md 4)
        # only for a use the skill's script took
        "skill_used_broadcast_taken": True,
        # 2026-10-28 15:00 (S6: 4 of 4 bot deaths under GL's turret, 5-7 shots each, retreat only at 22-28 % health): a bot
        # an enemy turret targets drops its target, walks back along its lane out of that turret's range (+3 m; no lane:
        # home) and keeps out until the turret has not targeted it for 2 s; an enemy champion under an enemy turret
        # (allied minions there or not) is chased only at bot_dive_health or more of the bot's health
        "bot_turret_aggro_retreat": True,
        "bot_dive_health": 0.7,
        # tester report 2026-10-29 15:30 ("the AI champions should not follow me completely behind my tower"): a bot
        # takes an enemy champion under an enemy shooter only while that shooter is busy with one of the bot's minions
        # (bot_dive_needs_tank), drops a champion more than bot_leash m from where the chase began or more than
        # bot_sight + bot_chase_margin m away, and ignores it bot_leash_ignore s (back to its lane). false = as before
        "bot_leash_rules": True,
        "bot_dive_needs_tank": True,
        "bot_leash": 10.0,
        "bot_chase_margin": 2.0,
        "bot_leash_ignore": 3.0,
        "bot_trace": False,                    # 2026-10-28 15:00 (S6): one server.log line per bot decision (state, target)
        # 2026-10-28 15:00 (S7: the trait (slot 5) was not counted, so AWW ranked it at levels 5, 6 and 7 and got her R at
        # 8): the bot follows its loadout's skill_order counting every slot, retrying an entry the rank gates refused
        "bot_rank_order_all_slots": True,
        # ---- 2026-10-30, tester report 15:30 (docs/re-notes/bot-shop-towers-end.md) ----
        # 1. "the AI buys one item at a time as it can upgrade it": a dead bot shopped every second wherever it lay, so
        # each tier went the moment the trickle paid for it. The original's bot script 0x340007E2 runs its shopping node
        # 0x10000186 only while HasFlagAttribute 0x10000A23, the base aura's may-shop attribute (C data, P meaning), so a
        # bot shops only inside its base aura (bot_shop_when_dead false = not while dead outside it). Each visit spends as
        # much as it can along its loadout's recommended list 0x10000478 in order (owned lines' next tier first when
        # bot_shop_upgrades_first), stopping at the first step it cannot pay (it saves for it: no skipping ahead);
        # bot_shop_plan false = the fase3-ir one-buy-per-second walk of the list
        "bot_shop_plan": True,
        "bot_shop_when_dead": False,
        "bot_shop_upgrades_first": True,
        # ... and it goes home (walk / Recall) to shop when the purchases it can pay add up to bot_shop_recall_value
        # credits or more, with no enemy champion within bot_shop_recall_safe m, at most once per bot_shop_recall_gap s
        # (0 = never for shopping; low health still sends it home as before)
        "bot_shop_recall_value": 1250.0,
        "bot_shop_recall_safe": 12.0,
        "bot_shop_recall_gap": 45.0,
        # 2. "they dive into the towers chasing minions": with bot_tower_awareness a bot takes a minion or a structure only
        # when the point it would attack from is out of every enemy shooter's range + bot_tower_margin m, or that shooter
        # is busy with one of the bot's minions and at least bot_tower_min_tanks of its minions stand in that range; an
        # enemy champion under an enemy shooter only while that shooter is busy with the bot's minions and the bot has
        # bot_dive_health, or for a near-certain kill (its health share <= bot_dive_kill_share and its health <= the bot's
        # attack damage x bot_dive_kill_hits, within reach + 2 m; hitting a champion turns the turret on the hitter); a bot
        # standing in such an unsafe range walks out of it before being targeted, and its push point stays out of it
        "bot_tower_awareness": True,
        "bot_tower_margin": 1.5,
        "bot_tower_min_tanks": 2,
        "bot_dive_kill_share": 0.2,
        "bot_dive_kill_hits": 2.0,
        # 2026-10-30 tester report 18:12 ("now it doesn't go in to attack the tower ... if it can attack me and get out
        # without the tower hitting it, it should; if it can go under the tower because there are minions, it should and
        # attack the tower; if the tower targets it, it should leave its range"; docs/re-notes/bot-shop-towers-end.md 4):
        # the 15:30 rule wanted 2 tanks and the turret's target on a live minion at that instant, so every minion death
        # (0.1-0.6 s with no target, 13 "steps out" in the run) and every one-minion wave sent it out, and minions came
        # before structures. bot_tower_tactics: an enemy shooter is held while it is not on the bot, the bot hit no enemy
        # champion in the last match_call_for_help s, and at least bot_siege_min_tanks of its minions stand in its range
        # with more health together than bot_siege_tank_shots of its shots; the bot then attacks the held structure
        # (bot_siege_first: before minions, structures within bot_siege_sight m), leaves when it is not held and comes
        # back as soon as it is again; an enemy champion near a shooter only when the point it hits from is out of the
        # shooter's range + bot_tower_margin, or in a short trade (shooters held, bot health >= bot_trade_health, the
        # point at most bot_trade_depth m inside range + 1, the shooter's next shot later than bot_trade_windup s + the
        # walk out), or a near-certain kill; near a shooter it re-decides every bot_tower_react s (0 = the usual
        # 0.5-0.8 s). false = the 15:30 rules
        "bot_tower_tactics": True,
        "bot_siege_min_tanks": 1,
        "bot_siege_tank_shots": 1.0,
        # (same report; headless lane: a melee bot sieging 3 m from the turret's centre needs ~2 s to get out and one shot
        # was 36 % of its level-1 health): the tanks must also outlast the shots fired while the bot walks out of range
        "bot_siege_escape": True,
        "bot_siege_first": True,
        "bot_siege_sight": 14.0,
        "bot_trade_health": 0.5,
        "bot_trade_depth": 2.0,
        "bot_trade_windup": 0.4,
        "bot_tower_react": 0.2,
        # 3. (tester's video: after the surrender passed the bot kept casting and attacking ~9 s and "killed" the player):
        # Match.end stops every bot (no target, no path, a stop state) and, with match_end_freeze_combat, World refuses
        # damage, casts of any entity but the local champion, and every basic-attack step once the match is over
        "match_end_freeze_combat": True,
        # 2026-10-28 15:00 (S8: the player earned ~120 credits during the intro and the countdown, the bot none): passive
        # credits start with the match
        "match_income_from_start": True,
        # 2026-10-28 15:00 (S9: a bot finished by GL's turret was GL's kill, but the kill feed showed the turret and the
        # announcer had no portraits): the kill feed and the announcer name the credited champion
        "kill_feed_shows_credit": True,
        # 2026-10-28 15:00 (S10: the Raider warnings played at 270 / 290 s, the middle camp stood on its pad, no Raider came):
        # the warnings and the spawn wait until the pad is free, then play their lead times from then
        "raider_warn_when_free": True,
        "unit_attack_speed_property": True,
        # 2026-10-25 11:00 (tester: the countdown voice is still silent; dialog-shield-disconnect.md 1, C): announcer lines
        # by 0x2039 + 0x100003BD on a dialog channel (0x2001 needs a conversation catalogue PvP templates lack): the
        # shared set's lines (0x9C / 0xBB / 0x97 / 0xAE / 0xAD) on channel 1, or channel 3 after 0x202A loads set
        # 0x4000047A where the template does not name it (Crime Alley v AI); other keys on channel 2.
        "announcer_line_mode": "2039",
        "announcer_shared_lines": ["0x9C", "0xBB", "0x97", "0xAE", "0xAD"],
        "announcer_load_shared_set": {"0x40000C82": "0x4000047A"},
        "match_clock_length": 3600.0,
        "match_play_intro": True,        # the map's intro line-up cinematic (CA 0x3500003C, GH 23, GD 24, CC 20)
        "match_end_cinematic": True,     # the losing core's end cinematic first (P which one plays)
        # tester report 2026-10-29 15:30 (the power core's destruction is incomplete: the central part falls but stays
        # duplicated in its place; throw-padlock-coredeath.md 3, C cinematic data): the end cinematics 0x3500003A / 3B
        # (Crime Alley), 0x3500000D / 0E (Gotham Heights) and the others create their own PowerCore actor at the
        # losing core's spot and play its destruction (Vfx_Destruct_State0 ...), while the networked core stayed whole
        # under it. The losing core (and its head / plate if any) is removed match_end_core_remove_delay s after the
        # cinematic starts (false = kept, as before)
        "match_end_cinematic_removes_core": True,
        "match_end_core_remove_delay": 0.0,
        "match_end_hold": 4.0,           # s between the WIN / LOSS billboard and the match-ended notice 0x1000000E
        # 2026-10-29 (tester report 23:03: the core's destruction is cut when VICTORY / DEFEAT appears, the explosion from
        # the hole never shows, no Victory / Defeat voice; traffic 22:51:45.909 cinematic 0x3500003A, 45.910 billboard 9,
        # 49.877 0x1000000E leaves the world; turret-heads-coredeath.md 4, C cinematic data): with the end cinematic, the
        # VICTORY / DEFEAT billboard and the victory voice come at its Cinematic_Announcement / event-29 frame ("announce",
        # s after the core's death: CA / GD / CC frame 225 = 7.5 s, GH 210 = 7.0 s at 30 fps) and 0x1000000E after the
        # cinematic ("notice": 11.5 s / 10.5 s + 0.5). {} = the fase3-io timing (billboard at once, notice match_end_hold s later)
        "match_end_timing": {"crime_alley": {"announce": 7.5, "notice": 12.0},
                             "gotham_divided": {"announce": 7.5, "notice": 12.0},
                             "coast_city": {"announce": 7.5, "notice": 12.0},
                             "gotham_heights": {"announce": 7.0, "notice": 11.0}},
        "match_place_champions": True,   # champions start at their team's type-16 start points
        # Waves (prototype sistema_suiditos_moba.py + full-match-mechanics.md 6 proposal, G): first wave 45 s after
        # the start, every 30 s, 2 melee + 2 ranged, a siege minion every 3rd wave, the super minion (Destroyer
        # Drone) after 15 min; elites replace the pair on a lane whose enemy dampener is down. max_alive 0 = no cap.
        "match_waves": {"first": 45.0, "interval": 30.0, "melee": 2, "ranged": 2, "siege_every": 3,
                        "super_after": 900.0, "spacing": 1.5, "max_alive": 0,
                        # 2026-10-23 10:11 (tester: the minions must come out one behind the other, each with its
                        # teleport-in): seconds between the wave's minions at the mouth (0 = all at once in rows)
                        "stagger": 1.0},
        # AI: retarget every 0.5-0.8 s (data: 0x3A000026 GetBestPerceivedTargetInterval_Min / _Max); leash distances
        # are authored (the prototype's 1200 LoL units ~ 12 m); a champion who hit an allied champion in the last
        # match_call_for_help s is the first target of minions and turrets (prototype, Starro script 0x3400053A).
        "match_retarget_interval": [0.5, 0.8],
        "match_minion_leash": 12.0,
        "match_camp_leash": 10.0,
        # tester report 2026-10-29 15:30 ("in Crime Alley I can pull a wave around and bring it behind my tower; minions
        # should chase me while I am within an attack range and go back to their lane if I leave it"; units-and-ai.md
        # 5.1, C: no leash / chase distance in the data, 0x3A000026 has only the retarget interval): a lane minion keeps
        # a non-structure target only while it is within its acquisition range (vision / reach + 1) + chase_margin m
        # and while the minion is within leash_anchor m of the lane point where it left; then it ignores that target for
        # leash_ignore s and walks back, taking no target until it is within lane_rejoin m of its lane (at most
        # return_max s). false = match_minion_leash (12 m from the target, no anchor) as before
        "match_leash_rules": True,
        # tester report 2026-10-29 21:10 (screenshot of the original: minions that turn on the player after he hits an
        # enemy champion show golden chevrons over their heads; aggro-recall-scorepanel.md 1): while a unit of these
        # roles targets the local champion it runs CbtState_Aggro (onset) + CbtState_Aggro_Active (held until it drops
        # him, then stopped by 0x11F). Both keys sit in 0x22 containers gated on 0x100000CE == 1; match_aggro_flag_mode
        # "variable" passes 0x100000CE = 1 as a run variable, "property" sets it on the unit by 0x6 (it is also the
        # controlled agent's vitals-notify flag: the minion's vitals may then reach the HUD), "none" = not sent.
        # [] roles = no indicator (as before)
        "match_aggro_roles": ["minion"],
        "match_aggro_flag": "0x100000CE",
        "match_aggro_flag_mode": "variable",
        "match_aggro_scriptlets": ["CbtState_Aggro", "CbtState_Aggro_Active"],
        "match_minion_chase_margin": 1.5,
        "match_minion_leash_anchor": 8.0,
        "match_minion_leash_ignore": 4.0,
        "match_minion_return_max": 6.0,
        "match_minion_lane_rejoin": 2.0,
        "match_call_for_help": 2.0,
        "match_snap_to_navmesh": True,   # G positions are moved onto the nearest walkable point (within 6 m)
        # 2026-10-22: an attack script that deals no damage in this many swings (a node the runtime lacks) is
        # replaced by the unit's Attack Damage dealt by the AI. 0 = never.
        "match_attack_fallback_after": 3,
        # Movement: one state per corner / start / stop (client-movement.md 1.4), refreshed every match_move_refresh
        # s while walking. "bundle" = a full object bundle (the tested path); "b0" = the 0xB0 block alone (P strong).
        "match_move_message": "bundle",
        "match_move_refresh": 1.0,
        # 2026-10-29 tester report 19:55 ("the minions attack me but never turn toward me"; minion-attack-facing.md):
        # a unit in reach sends a stop state with the facing toward its target when that facing is more than this many
        # rad from the one last sent (the stop state at the end of a walk carries it too); 0 = never, as before
        "match_attack_face_turn": 0.15,
        # 2026-10-30 tester report 13:18 ("the minions pass through each other, they have no collisions";
        # unit-separation-pick-body.md 1): server-side separation of the units of match_separation_roles from each other,
        # champions / bots and structures (radii = the attack radii: match_unit.radius / attack_body_radius), on a grid
        # every tick. A walking unit is moved aside at most match_separation_push x its step (a new state only when the
        # client's dead reckoning is match_separation_resync m off); a standing one at least match_separation_shuffle_min
        # m deep slides to its free spot (start + stop state), kept within its reach of its target; overlaps under
        # match_separation_slack m are left. false = units overlap (as before)
        "match_unit_separation": True,
        "match_separation_roles": ["minion", "camp"],
        "match_separation_push": 0.75,
        "match_separation_resync": 0.4,
        "match_separation_shuffle_min": 0.15,
        "match_separation_slack": 0.05,
        # 2026-10-30 (test_match "around the target they keep apart / no oscillation" failed once the Power Core Turret's
        # parts and platform shifted every later entity id: the spread hung on the id-seeded directions; unit-separation-
        # pick-body.md 4): the crowd shoved its own target (half of each attacker's overlap), so the target slid away,
        # the attackers walked after it and sent states all the time. target_holds: a unit is not pushed by the units
        # attacking it (the attacker takes the whole overlap; mutual targets keep half each). unpin: a standing unit
        # whose pushes cancel (between its target and the minion behind it) while one alone is >= shuffle_min steps
        # sideways out of the line. false / false = the 13:18 behaviour
        "match_separation_target_holds": True,
        "match_separation_unpin": True,
        # Structures: footprint half size on the navmesh (they are not cut out of it: maps-complete.md 2.3); 0x42
        # vitals to structures (they show health bars; set false if the client closes when a structure spawns).
        "match_structure_radius": {"core": 3.0, "core_turret": 1.6, "turret": 1.6, "inner_turret": 1.6,
                                   "dampener": 2.0, "foundry": 2.0},
        "match_structure_vitals": True,
        "match_structure_order": True,   # outer before inner per lane, core turret after an inner one, then the core
        "match_dampener_respawn": 300.0,  # s (G: LoL's inhibitor); 0 = stays down
        "match_colour_override": False,  # keep the tutorial's purple override 0x10000CF0 on match units
        # Camps (G: full-match-mechanics.md 8 proposal): first spawn, respawn per camp kind; team of the neutrals
        # (hostile to both teams; the template's 0x1000046E neutral is a reference the original server resolved)
        "match_camps": {"first": 60.0, "first_boss": 300.0, "respawn_small": 75.0, "respawn_big": 300.0,
                        "respawn_boss": 300.0},
        "match_neutral_team": 3,
        # Rewards from the data's formulas (XP 0x10000224, credits 0x10000689, team bounty 0x10000362, champion
        # bounty 0x3B0000B7's description); World's flat credits_per_kill / xp_per_kill are switched off in a match.
        # Who shares (authored): champions of the killing team within match_reward_radius m; minion credits to the
        # last hitter; assists = damage in the last match_assist_window s, sharing match_assist_share of the bounty.
        "match_rewards_from_data": True,
        "match_reward_radius": 15.0,
        "match_assist_window": 10.0,
        "match_assist_share": 0.5,
        # 2026-10-28 13:52 (tester: the K/D/A counter top right is wrong; timeline-kda-endscreen.md 2): damage and kills
        # by a skill's missile / spawned object count for its champion (score_hit_owner, score_kill_owner), and a
        # champion finished by a turret / minion / creature is the kill of the last enemy champion who hit it within
        # match_assist_window s (score_kill_credit_last_champion). false = only the champion's own blows (fase3-ie)
        "score_hit_owner": True,
        "score_kill_owner": True,
        "score_kill_credit_last_champion": True,
        "match_bounty_base": 400.0,      # Bounty_Base of 0x3B0000B7 (data)
        # Respawn time by champion level 1..20 (O: not in the client; authored, ~LoL's curve scaled down)
        "match_respawn_seconds": [6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 35, 38, 41, 44, 47, 50],
        "match_scoreboard_interval": 1.0,   # s between two 0x1000005B rosters (sent only after a change)
        # Team health (GH, Clash): the start value is the UI record's 0x10000463 (data); this only when it is missing
        "match_team_health": 500,
        # Gotham Heights (P: holding more points drains the enemy's team health; rate authored): per second and per
        # point of difference; capture_cost = team health a team loses each time the enemy captures a point
        "match_domination": {"drain_per_point": 1.0, "capture_cost": 0.0},
        # 2026-10-29 (tester report 2026-10-29 15:30: GH, the point he stood on seemed "a few degrees to the left";
        # gh-ca-floor-spawn.md 3, C data): a capture point stands on its pad static (0x2E0008D5, maps.py "pad"; the SW
        # one was 1.4 m off, the N one 0.13 m) instead of the waypoint markers' centre. false = the markers (fase3-ii)
        "match_capture_on_pads": True,
        # Clash (team health 200 / 300 from the data; what drains it is authored): per death / structure lost
        "match_clash_health_loss": {"champion": 20.0, "turret": 40.0, "core_turret": 40.0, "dampener": 40.0,
                                    "core": 1000.0},
        # Captures by presence (GH points, CC relays, GD beacons): seconds from neutral to owned for one champion
        # (more champions up to max_bonus go faster); radius 0 = the point's vision radius (GH 4.25 m, data);
        # a held beacon gives its owner vision of beacon_vision m.
        "match_capture": {"seconds": 10.0, "max_bonus": 3, "radius": 0.0, "beacon_vision": 12.0},
        # The Doomsday Device (CC; P: relays charge it, it fires at the enemy core): charge per relay per second up
        # to 100, fire_delay s after full, damage = damage_fraction x the core's maximum health; can_kill false
        # leaves the core at 1 health.
        "match_device": {"charge_per_relay": 0.5, "fire_delay": 5.0, "damage_fraction": 0.2, "can_kill": False,
                         # 2026-10-25 (map-objectives-recipes.md 3.2, map-gaps-coast-city.md 2.5): mode "capture" =
                         # the Device unlocks at `unlock` s (lines 238 / 442 / 244 before, 234 at it, C keys), is
                         # captured by presence (radius 5.0, C), auto-fires `fire_after` s later (line 440 before) at
                         # the enemy core with the pad strike 0x4000035D: within 7.5 m champions 100 + 60 x level,
                         # structures 750 + 100 x level (0x340001FA defaults, C; level = 1 + t / 90 s, 0x3B0001E7),
                         # then neutral and locked for `relock` s (G). "relays" = the fase3-hs charge rule.
                         "mode": "capture", "unlock": 180.0, "warn": {"-60": 238, "-30": 442, "-10": 244},
                         "unlocked_line": 234, "radius": 5.0, "seconds": 10.0, "fire_after": 10.0, "fire_line": 440,
                         "captured_event": 51, "strike_class": "0x4000035D", "strike_radius": 7.5,
                         "champion_damage": [100.0, 60.0], "building_damage": [750.0, 100.0], "relock": 60.0},
        # Map events (G schedule; assets in the data: banks mse_MeteorStorm, Meteor Fragment 0x400006F1 in pack
        # 0xA0000164): warning s before, impacts near the camps, a fragment pickup worth pickup_credits at each.
        "match_events": {"meteor_storm": {"enabled": True, "first": 480.0, "every": 360.0, "until": 3600.0,
                                          "warning": 60.0, "impacts": 4, "radius": 5.0, "damage": 0.0,
                                          "pickup": 0x400006F1, "pickup_credits": 50.0, "icon": 0}},
        # Surrender (full-match-mechanics.md 12.1; thresholds authored): earliest 0 = the template's 0x1000021C
        # (600 s), vote length, fraction of the team's human players needed, cooldown after a failed vote
        "match_surrender": {"earliest": 0, "vote_seconds": 60.0, "fraction": 0.8, "cooldown": 180.0},
        # ---- combat (script VM) ----
        # 2026-10-22 (full-combat-skills.md, static analysis; no tester report yet): the champions' skills run from the
        # game's own scripts with attributes, modifiers, statuses, CC, hotspots and forced movement (ics/combat.py,
        # ics/script_nodes.py). Each switch below turns one new behaviour off again.
        # Armor / penetration mitigation raw x 100 / (100 + armor x (1 - pen%) - pen) (2 A.5: server-only, P)
        "damage_mitigation": True,
        # Attribute modifiers sent to the client as 0x20F0 / 0x20E8 (2 A.3, C): HUD, stats panel, CanActivate read them
        "attribute_modifier_messages": True,
        # CC flags (Stunned, cannot-act, Silenced, Rooted, Crippled) also set as properties with event 0x6
        # (client-status-effects.md 4: the order gate reads the base value)
        "cc_property_events": True,
        # While stunned / disabled / dashing the champion also gets 0x10000B2D = 1 so the client stops sending moves
        "cc_cannot_act": True,
        # Server-side CanActivate (1.3): refuse a cast in cooldown / stunned / silenced ... and send 0x20DC
        "validate_casts": True,
        # Status icons (0x20C8 / 0x20A8 / 0x20E9 / 0x20D0 / 0x2127; byte layout C, field mapping P)
        "status_icons": True,
        # Mirror status scripts to the client as effects (0x200F / 0x202B). Off: the variable store's Value payload
        # is not mapped (client-status-effects.md 4, "higher risk"); the attributes / icons carry the effect instead
        "status_mirror": False,
        # Cast bar (Usage 0x2077 / 0x20CE / 0x2096) for casts at least this long (s); casts take 0.25 s today
        "cast_bar_min_seconds": 0.5,
        # 0x42 values with the client serializer's long form above 16383 (was masked with 0x7FFF)
        "vitals_long_form": True,
        # CheckRelation / FindTargets / hotspots: the client's masks (3 = enemy or neutral). False: team 0 (the
        # tutorial's neutral thugs, doors) is never a target of hostile effects (the tutorial's behaviour so far)
        "neutral_hittable": False,
        # 2026-10-22 14:10 (tester: Sonic Batarang went through the tutorial's practice targets): the server's
        # missile collision test used "hostile", which no neutral (team 0) entity passes; now a missile collides
        # with anything not on its shooter's team and not DisableCollision'd, neutrals only when hittable (above,
        # or marked by the flow: the practice targets). False: the old hostile-only test
        "missile_hits_neutral_targets": True,
        # 2026-10-22 14:10 (same report; original objective "press Q to destroy it with Sonic Batarang", catalog
        # 0x40000BA9): a practice target only takes the skill its step teaches (Director only_skill); other hits do
        # nothing and play Superman's 0x1CD / 0x1DB / 0x1B2 once. False: any damage kills it (1 health)
        "practice_target_only_skill": True,
        # 2026-10-22 (tutorial practice_w: Sonic Shell never exploded): an entity SpawnEntity creates gets event
        # 0x10000049 (and again when LaunchMissile launches it, with 0x10000035 at the end of its flight); a launched
        # entity stays where it lands until its script destroys it (at most launched_entity_linger s). False: the
        # old behaviour (no events, removed on landing)
        "spawned_entity_events": True,
        "launched_entity_linger": 5.0,
        # Transitions guarded by a condition are re-checked every update while their state is active (client VM)
        "script_poll_conditions": True,
        # Spawned entities (SpawnEntity) and hotspot ground effects are created as objects of their class
        "spawn_script_entities": True,
        # DestructionImpulse broadcast as 0x8A (sphere) / 0x1 (box) (4.6: the client serializers exist, P that the
        # original sent them; only cosmetic debris): off until tested
        "destruction_events": False,
        # Runaway guard: at most this many script timers per second per caster (was 5000 in total, which stopped
        # long-lived skill scripts after a few minutes)
        "script_timers_per_second": 2000,
    },
    "timing": {
        "objects_min_delay": 4.0,        # client protocol: objects only after the lobby + this delay ...
        "objects_min_percent": 15,       # ... and this much loading (it waits for them at 15 %)
        "objects_max_wait": 10.0,
        "link_delay": 2.0,               # second bundle: player -> champion link
        "keepalive": 2.0,
        "tick_hz": 30,
        # s without any update before the champion + player bundles go again; [ics] object_update_mode "delta" uses
        # [ics] delta_resync_seconds instead (2026-10-28 15:00, object-update-bundles.md 12.3 c)
        "idle_resend": 5.0,
        "cinematic_delay": 5.0,          # s after load complete before the intro cinematic (earlier server)
        "units_delay": 3.0,              # s after load complete before the layout's units (2026-10-21: during the
                                         # load they broke it)
        "prop_scriptlet_delay": 1.0,     # s after the props are created before their initial scriptlets
    },
    "debug": {"hexdump": True},
}


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    def __init__(self, data, path):
        self.data, self.path = data, path

    def __getitem__(self, k):
        return self.data[k]

    @property
    def game_dir(self):
        return self.data["game"]["dir"]

    @property
    def key_path(self):
        p = self.data["server"]["key"]
        return p if os.path.isabs(p) else os.path.join(ROOT, p)

    @property
    def log_dir(self):
        return os.path.join(ROOT, "logs")

    def encounter(self, did):
        enc = self.data["ics"]["encounters"]
        return enc.get(f"0x{did:08X}") or enc.get(f"{did:#x}") or enc.get(f"0x{did:08x}")


def load(path=None):
    path = path or os.path.join(ROOT, "config.toml")
    data = copy.deepcopy(DEFAULTS)
    if os.path.isfile(path):
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        for section in ("game", "server", "ics", "timing", "debug"):
            if isinstance(raw.get(section), dict):
                _merge(data[section], raw[section])
    return Config(data, path)
