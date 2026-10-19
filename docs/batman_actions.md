# Gaslight Batman actions (champion scriptlet table)

The keys come from the champion's allowed-scriptlet table (diag `--scripts`,
`batman_keys.txt`, 354 keys). The names come from the game's animation and event
tables. Several names share the same number (hash collision): the most likely one for
Batman is shown, with the alternatives alongside. To play a key
on Batman: `run_scripts(M.CHAMPION_AGENT_ID, [key])` (event 0x8D).

## In-game action tour results (2026-10-15)

The server can play keys on Batman one at a time using these options in the `[debug]`
section of the config:

- `tour_keys`: `"all"`, `"core"`, or a list of keys.
- `tour_interval`: seconds between keys (3.0 s).
- `tour_start`: delay before the first key (6.0 s).

Each key is logged in `logs/server.log` as `tour N/25: <key> <label>`.

Results for the 25 "core" keys:

| Key | Name | Visible on Batman? |
|---|---|---|
| `0x10000164` | Q Sonic Batarang (full ability) | yes (already used by the tutorial) |
| `0x10000163` | W Sonic Shell | yes |
| `0x10000165` | E Bat Flight | yes |
| `0x10000162` | R The Bat Scream | yes |
| `0x10000195` | Basic attack, right | yes |
| `0x10000196` | Basic attack, left | yes |
| `0x10000188` | Shot VFX, right (Vfx_Bmg_Basic_Ranged_Right) | yes |
| `0x10000189` | Shot VFX, left (Vfx_Bmg_Basic_Ranged_Left) | yes |
| `0x1000017e` | Critical VFX (Vfx_Bmg_Crit) | yes |
| `0x10000209` | Hit reaction | yes |
| `0x1000003d` | CbtState_KnockUp (launched into the air) | no |
| `0x100001f9` | _Defeat_StartupIncapacitated | yes |
| `0x100001fb` | _Defeat_OnIncapacitated | yes (used for the tutorial knockdown) |
| `0x10000490` | RunScript_Vfx_GetUp (get up) | no |
| `0x100001fa` | _Defeat_OnDead (death) | no |
| `0x100001fc` | _Defeat_OnRespawn | no |
| `0x100001fd` | _Defeat_OnRevive | no |
| `0x10000999` | Stunned (status VFX) | no |
| `0x10000201` | Level up | no |
| `0x10000181` | Vfx_Bmg_Spawn (spawn) | yes |
| `0x100009fb` | Teleport | no |
| `0x100001d3` | Emote: laugh | no |
| `0x10000641` | Emote: dance | no |
| `0x10000643` | Emote: joke | no |
| `0x1000115e` | Emote: taunt/oath | no |

Notes:

- "No" means nothing visible happened when the key was played alone on an idle Batman.
  Many of these probably need extra script variables, a target, or a state change sent
  by the server (e.g. a life-state change for death/respawn), so "no" does not mean the
  key is useless.
- The remaining 329 keys of the 354-key table have not been checked one by one yet.
- The key list is also available as `data/batman_actions.tsv` (key<TAB>probable name).

## Batman abilities (Q/W/E/R) and their effects (18)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x10000162` | Batman_Gaslight_The_Bat_Scream |  |
| `0x10000163` | Batman_Gaslight_Sonic_Shell | Doomsday_Charge_Grab |
| `0x10000164` | Batman_Gaslight_Sonic_Batarang | Doomsday_Charge_End |
| `0x10000165` | Batman_Gaslight_Bat_Flight | Doomsday_Charge |
| `0x1000016f` | Vfx_Bmg_Flight_Stop | Doomsday_Kryptonian_Rage_Start |
| `0x10000170` | Vfx_Bmg_Basic_Stop | Doomsday_Kryptonian_Rage_End |
| `0x10000171` | Vfx_Bmg_Batarang | InductionChanneling_Start |
| `0x10000173` | Vfx_Bmg_Scream | InductionChanneling |
| `0x10000176` | Vfx_Bmg_Scream_Stop | SuperStrength_InitCarPickup |
| `0x10000177` | Vfx_Bmg_Sonic_Shell | a_MissileInit |
| `0x10000178` | Vfx_Bmg_Flight | CbtState_Cower_Recover |
| `0x1000017b` | Vfx_Bmg_Batarang_Stop |  |
| `0x1000017c` | Vfx_Bmg_Crit_Stop | StopScript_Vfx_Min_Alien_Melee_Basic_Active |
| `0x1000017e` | Vfx_Bmg_Crit | supercharged |
| `0x10000181` | Vfx_Bmg_Spawn | batman |
| `0x10000182` | Vfx_Bmg_Flight_Active |  |
| `0x10000188` | Vfx_Bmg_Basic_Ranged_Right | env |
| `0x10000189` | Vfx_Bmg_Basic_Ranged_Left | StopIvyFidget |

## Basic attacks and criticals (6)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x100000eb` | Combat_Special_Attack_2 | Vfx_Active |
| `0x10000128` | Combat_Basic_Attack | Poison_Ivy_Root_Strike |
| `0x100002fd` | _Combat_GoToLocomotion | Catwoman_WhipStrike_PB_Start |
| `0x100005b4` | Basic_Attack_Range4 | Vfx_Stp_Detonate_Matter_Explosion_Hit |
| `0x100005b5` | Basic_Attack_Range3 | Vfx_Stp_Detonate_Matter_Cast_Hit |
| `0x10000622` | Vfx_Cbt_Hit_Blood_Crit |  |

## Combat states (hits, knockdowns, stun, death) (13)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x100000e9` | CbtState_StrafeRight | Vfx_Event9 |
| `0x100001e3` | _HFSM_BehaviorRaiseEventAction | SuperStrength_Rubble_Pickup |
| `0x100001f3` | Engagement_SideStep_Right | WonderWoman_Protection_Other_Teleport |
| `0x10000209` | _HFSM_TargetHitAction_PhysicalReaction | StopScript_Vfx_WW_Prowess_Streak_Crit |
| `0x10000218` | RunScript_Vfx_Death_A | Vfx_Status_Buff_Monster_Red_Stop |
| `0x1000032a` | RunScript_ArcGreenLantern_Lantern_Knockup_Back | Usage_Induction_Start |
| `0x100003af` | CbtState_DisableHit |  |
| `0x100005b6` | CbtState_ChainSwingActive | Vfx_Stp_Consume_Matter_Healed_Hit |
| `0x10000843` | _CDefeatSystem_DeathOverlay |  |
| `0x10000999` | Vfx_Status_Stun_Active |  |
| `0x10000cde` | Vfx_Ssr_Bonds_Knockback |  |
| `0x10000d61` | CbtState_Aggro |  |
| `0x10000d62` | CbtState_Aggro_Active |  |

## Defeat / respawn / match (22)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x10000119` | FX_Spawn |  |
| `0x10000183` | SpawnIdle | Vfx_Bmg_Sonic_Shell_Stop |
| `0x100001e4` | _Selection_SoftSelection_Valid | SuperStrength_Rubble_Throw |
| `0x100001e6` | _Selection_SoftSelection_Invalid | WonderWoman_AmazonianProwess_Start |
| `0x100001e8` | _Player_OnAgentControlledByPlayer | clip_to_clip |
| `0x100001f9` | _Defeat_StartupIncapacitated | Gaslight_Catwoman_SteamClaws |
| `0x100001fa` | _Defeat_OnDead | StopScript_FX_GlC_Atk_Crit |
| `0x100001fb` | _Defeat_OnIncapacitated | RunScript_Vfx_Glc_Basic_Right_Active |
| `0x100001fc` | _Defeat_OnRespawn | RunScript_FX_Glc_Atk_Crit |
| `0x100001fd` | _Defeat_OnRevive | RunScript_FX_Glc_Atk_Basic |
| `0x100001fe` | _Defeat_OnFade | Gaslight_Catwoman_PredatorsGrace |
| `0x100001ff` | _Team_SetTeamIndicator | Gaslight_Catwoman_BloodHunt |
| `0x10000200` | _Encounter_OnAgentControlledByPlayer | Gaslight_Catwoman_StalkEnd |
| `0x10000201` | _Advancement_LevelUp | Gaslight_Catwoman_StalkStart |
| `0x1000065d` | _Advancement_UltimateUnlocked |  |
| `0x10000764` | Vfx_Cbt_Tgt_Mark_Player_Retreat_Stop |  |
| `0x10000765` | Vfx_Cbt_Tgt_Mark_Player_Retreat_Active |  |
| `0x10000766` | Vfx_Cbt_Tgt_Mark_Player_Alert_Stop |  |
| `0x10000767` | Vfx_Cbt_Tgt_Mark_Player_Alert_Active |  |
| `0x10000809` | _Entity_OnSwap |  |
| `0x100009fb` | Vfx_Item_Time_Anchor_Teleport_Active |  |
| `0x100009fc` | Vfx_Item_Bleed_Tunnel_Teleport_Active |  |

## Emotes and idle animations (26)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x100001d2` | Emote_Taunt_Stop | Vfx_Status_Supercharge_Stop |
| `0x100001d3` | Emote_Laugh_Start | Vfx_Status_Supercharge_Active |
| `0x100001f2` | Emote_Abort | Engagement_SideStep_Left |
| `0x1000020e` | Fidget_D | Vfx_Status_Buff_Monster_White |
| `0x1000020f` | Fidget_C | Vfx_Status_Buff_Monster_Purple |
| `0x10000210` | Fidget_B | Vfx_Status_Buff_Monster_Blue |
| `0x10000211` | Fidget_A_Transition | Vfx_Status_Buff_Monster_Green |
| `0x10000214` | Fidget_E | Vfx_Status_Buff_Monster_Yellow_Stop |
| `0x10000216` | RunScript_Vfx_Fidget_A | Vfx_Status_Buff_Monster_White_Stop |
| `0x10000217` | RunScript_Vfx_Fidget_B | Vfx_Status_Buff_Monster_Green_Stop |
| `0x10000223` | Fidget_F | VFX_CBT_Hit_Shared |
| `0x10000320` | Fidgets_Disable |  |
| `0x10000321` | Fidgets_Enable | ArcGL_Lantern_Thrown |
| `0x10000432` | Vfx_Jkr_Last_Laugh_Active | Siphon_A |
| `0x100004ba` | RunScript_Vfx_Fidget_B_Melee | Vfx_Ivy_Thorn_Shield_Hit |
| `0x100004bd` | RunScript_Vfx_Fidget_A_Ranged | Vfx_Ivy_Thorn_Shield_Active |
| `0x100004c4` | Fidget__F | Vfx_Status_Target_Retreat_Active |
| `0x100004d3` | Vfx_Status_Taunt_Active | WarriorKing_Basic_Attack |
| `0x100004d6` | StopScript_Vfx_Fidget_C_Melee | Vfx_WW_Protect_Target_Stop |
| `0x100004db` | Vfx_Status_Taunt_Stop | Katana_Sheath |
| `0x10000555` | Vfx_Status_Taunt_Hit |  |
| `0x1000058c` | Vfx_WW_Blocking_Bracers_Taunt_Stop |  |
| `0x100005e2` | Cloth_Idle | Vfx_Glc_Predators_Grace_Hit |
| `0x10000641` | Vfx_Chr_Emote_Dance |  |
| `0x10000643` | Vfx_Chr_Emote_Joke |  |
| `0x1000115e` | Emote_Oath_Start |  |

## Movement and footsteps (9)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x10000195` | Footstep_Right_Walk | Combat_Basic_Attack_Right |
| `0x10000196` | Footstep_Left_Walk | Combat_Basic_Attack_Left |
| `0x10000198` | Footstep_Left_Sprint | Vfx_Bmg_Echoes_Active |
| `0x10000329` | RunScript_ArcGreenLantern_Lantern_Recover_Facedown | Usage_Induction_End |
| `0x1000033f` | Footstep_Alt_Back | Vfx_Status_Haste_Stop |
| `0x10000490` | RunScript_Vfx_GetUp |  |
| `0x100004cc` | RunScript_Vfx_Blu_RubbleThrow | SuperStrength_ThrowRubble |
| `0x100004dd` | RunScript_MovingActive | Vfx_Status_Fear_Active |
| `0x1000058e` | RunScript_Vfx_Kta_Show_Blade | Vfx_WW_Blocking_Bracers_Taunt_Hit |

## Status effects (status VFX) (75)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x100001b1` | Vfx_Status_Fire_Stop |  |
| `0x100001b2` | Vfx_Status_Fire_Active | Combat_Special_Attack_4_End |
| `0x100001b3` | Vfx_Status_Fire_Hit |  |
| `0x1000020d` | Vfx_Status_Buff_Monster_Yellow | RunScript_Vfx_WW_Blocking_Bracers_Right_Deflect |
| `0x10000212` | Vfx_Status_Buff_Monster_Red | Unpack |
| `0x10000213` | Vfx_Status_Buff_Monster_Blue_Stop | Unpack_to_State_Wrapper |
| `0x10000215` | Vfx_Status_Buff_Monster_Purple_Stop |  |
| `0x10000291` | Vfx_Status_Heal_Stop | RunScript_Vfx_Glc_Predators_Grace_MeshStreak_2 |
| `0x10000292` | Vfx_Status_Heal_Active | RunScript_Vfx_Glc_Predators_Grace_MeshStreak_1 |
| `0x10000293` | Vfx_Status_Heal_Hit |  |
| `0x10000343` | Vfx_Status_Haste_Active | RunScript_Vfx_Basic_Active_Right_Crit |
| `0x100003cc` | Vfx_Status_Slow_Active | EP_StartSkill_HeatVisionInitial |
| `0x100003cd` | Vfx_Status_Slow_Stop |  |
| `0x100003d5` | Vfx_Status_Poison_Stop |  |
| `0x100003d6` | Vfx_Status_Poison_Hit |  |
| `0x100003d7` | Vfx_Status_Poison_Active |  |
| `0x100004b6` | Vfx_Ivy_Thorn_Shield_Stop |  |
| `0x100004c3` | Vfx_Status_Target_Retreat_Stop | RunScript_Vfx_Chr_Emote_Joke_Alt |
| `0x100004d1` | Husk_Take_Root | Vfx_Status_Blind_Active |
| `0x100004e0` | Vfx_Status_Fear_Stop | GreenArrow_Bullseye_End |
| `0x10000517` | Vfx_Status_Target_Friend_Stop | StopScript_Vfx_Det_SMG_Flash_Active_Right |
| `0x10000518` | Vfx_Status_Target_Friend_Active | RunScript_Vfx_Det_SMG_Flash_Active_Right |
| `0x10000519` | Vfx_Status_Target_Friend_Hit | StopScript_Vfx_Det_Shotgun_Active_Right |
| `0x100005a4` | Vfx_Status_Silence_Active |  |
| `0x1000061c` | Vfx_Status_Bleed_Stop |  |
| `0x1000061e` | Vfx_Status_Bleed_Active |  |
| `0x10000648` | Vfx_Status_Stealth_Active |  |
| `0x100006ad` | Vfx_Status_Supercharge_Hit |  |
| `0x100006b0` | Vfx_Status_Target_Retreat_Friend_Stop |  |
| `0x100006b1` | Vfx_Status_Target_Retreat_Friend_Active |  |
| `0x100006b7` | Vfx_Status_Slow_Hit |  |
| `0x100006b8` | Vfx_Status_Freeze_Active |  |
| `0x100006b9` | Vfx_Status_Freeze_Stop |  |
| `0x100006ba` | Vfx_Status_Haste_Hit |  |
| `0x100006bb` | Vfx_Status_Freeze_Hit |  |
| `0x1000076c` | Vfx_Glt_Missiles_Debuff_3_Active |  |
| `0x1000076d` | Vfx_Glt_Missiles_Debuff_2_Active |  |
| `0x1000076e` | Vfx_Glt_Missiles_Debuff_1_Active |  |
| `0x10000803` | Vfx_Bat_Batarang_Debuff_Active |  |
| `0x1000080f` | Vfx_Bat_Dark_Knight_DeBuff_Active |  |
| `0x10000838` | Vfx_Ivy_Healthy_Glow_Active |  |
| `0x10000851` | Vfx_Arc_Glt_Rooted_Target_Active |  |
| `0x1000086c` | Vfx_Arc_Glt_Shield_Aura_Active |  |
| `0x10000913` | Vfx_Rbn_EmergentLeader_Buff_Active |  |
| `0x10000917` | Vfx_Rbn_ThisGuy_Debuff_Active |  |
| `0x1000093f` | Vfx_Status_Reveal_Active |  |
| `0x1000097e` | Vfx_Atm_Ivy_Toxic_Growth_Debuff_Active |  |
| `0x1000098e` | Vfx_Atm_Ivy_Poison_Tgt_Active |  |
| `0x100009b5` | Vfx_Arc_Glt_Emerald_Light_Heal_Active |  |
| `0x100009bc` | Vfx_Status_Will_Regen_Active |  |
| `0x100009be` | Vfx_Status_Power_Buff_Active |  |
| `0x100009bf` | Vfx_Status_Attack_Buff_Active |  |
| `0x100009c0` | Vfx_Status_Energy_Regen_Active |  |
| `0x10000a02` | Vfx_Item_Response_Shield_Active |  |
| `0x10000a5c` | Vfx_Ssr_Bonds_Debuff_Beam |  |
| `0x10000a5d` | Vfx_Ssr_Bonds_Buff_Beam |  |
| `0x10000a64` | Vfx_Ssr_Harvest_Buff_Active |  |
| `0x10000aa2` | Vfx_Item_Protection_Shield_Active |  |
| `0x10000aa3` | Vfx_Status_Debuff_Monster_EMP |  |
| `0x10000b1f` | Vfx_Status_Armor_Mixed_Debuff |  |
| `0x10000b20` | Vfx_Status_Armor_Attack_Buff |  |
| `0x10000b21` | Vfx_Status_Armor_Power_Buff |  |
| `0x10000b22` | Vfx_Status_Armor_Mixed_Buff |  |
| `0x10000b23` | Vfx_Status_Armor_Attack_Debuff |  |
| `0x10000b24` | Vfx_Status_Armor_Power_Debuff |  |
| `0x10000b5f` | Vfx_Gar_Ballistic_Debuff_Active |  |
| `0x10000bdc` | Vfx_Gar_Foam_Debuff_Active |  |
| `0x10000c18` | Vfx_Status_Wound_Active |  |
| `0x10000d19` | Vfx_Status_MonitorTech_Disabled |  |
| `0x10000d8c` | Vfx_Status_Buff_Monster_Orange_Stop |  |
| `0x10000d8d` | Vfx_Status_Buff_Monster_Orange |  |
| `0x10000d9b` | Vfx_Sto_Parasite_Debuff_Active |  |
| `0x10000e0a` | Vfx_Stg_Star_Debuff_Active |  |
| `0x10000ec0` | Vfx_Test_Krp_Vigilance_Shield_Active |  |
| `0x10000ec8` | Vfx_Krp_Vigilance_Shield_Active |  |

## Items and other (185)

| Key | Probable name | Other names with the same hash |
|---|---|---|
| `0x10000025` | Skill1 | RunScript_Vfx_Sup_FlyingUppercut_Loop_Stop, Vfx_Vbm_Embrace_Stop |
| `0x10000033` | UIBasic_LS | Vfx_Fade_In, Destructible_State0 |
| `0x1000003d` | UIBasic_DRight | CbtState_KnockUp, Basic_Attack_Critical |
| `0x10000050` | Vfx_Env_Rain | State_to_State |
| `0x1000005d` | Vfx_Active_State0 |  |
| `0x1000006a` | Vfx_Fade_Out | RunScript_FX_Sup_Atk_Basic |
| `0x100000b8` | SmartCastItem1 | Combat_Critical_Attack, CbtState_Death_FaceDown |
| `0x10000104` | VariableAnimation00 | Vfx_Vbm_Swarm_Active |
| `0x1000011f` | Vfx_Vbm_Embrace_Active | Poison_Ivy_Rampant_Growth |
| `0x1000012e` | vfx_env_ash |  |
| `0x10000130` | attk | Vfx_Stop |
| `0x100001f4` | SetBehaviorVariable_Float | WonderWoman_LassoGrab_Miss |
| `0x1000026e` | Vfx_Ivy_Deadly_Flora |  |
| `0x10000270` | Vfx_Ivy_Pheromones_Active |  |
| `0x100002a4` | VFX_CBT_Hit_Shared_ClientOnly | StopScript_Vfx_Gjk_Basic_Right_Active |
| `0x100002e3` | Vfx_Zat_Rabbit_Hit | AtomicWonderWoman_Reclaimer |
| `0x1000030f` | Channeling_OnInit | StopScript_Vfx_Aww_Reclaimer_Streaks_Active |
| `0x10000310` | Channeling_OnEnd | RunScript_Vfx_Aww_Reclaimer_Streaks_Active |
| `0x10000315` | Channeling_OnInit_ClientOnly | ArcaneGreenLantern_DenyTheBlack_End |
| `0x1000032e` | VFX_CBT_Hit_Shared_ReplicateOnly | AtomicGreenLantern_Meltdown_Start |
| `0x10000330` | (no name) |  |
| `0x10000331` | AtomicGreenLantern_Grab_Hit |  |
| `0x10000355` | MechaWonderWoman_Afterburn |  |
| `0x100003b0` | Active |  |
| `0x100003d0` | Fissure | Vfx_Dom_Revenge_Stop |
| `0x100003d1` | Drill_Attack | Vfx_Dom_Revenge_Active |
| `0x100003e8` | Start_Banish | Vfx_Zat_Punish_Aoe |
| `0x100003e9` | Vfx_Zat_Protect_Aoe | Superman_Mighty_Blow |
| `0x100003ea` | _ExecuteScriptlet | StopScript_VFX_Sup_Mighty_Blow_Active |
| `0x100003f8` | (no name) |  |
| `0x100003f9` | (no name) |  |
| `0x100003fa` | (no name) |  |
| `0x100003fe` | Stick_And_Move_Right | Vfx_Zat_Status_Punish_Active |
| `0x10000401` | Leathal_Measures | Vfx_Zat_Status_Punish_Stop |
| `0x10000402` | Hypersonics | Vfx_Zat_Status_Protect_Active |
| `0x10000406` | Stick_And_Move | Vfx_Zat_Status_Dash_Active |
| `0x10000407` | Infiltraitor_Deactivate | Vfx_Zat_Status_Protect_Stop |
| `0x10000409` | Enter | Vfx_Zat_Status_Dazzle_Active |
| `0x10000423` | a_SkillHoldHook | Vfx_Status_Target_Enemy_Stop |
| `0x10000424` | a_SkillHold | Vfx_Status_Target_Enemy_Active |
| `0x1000042a` | Entrance | Vfx_Vbm_Swarm_Status_Active |
| `0x1000042c` | NMR_Backstab |  |
| `0x1000042d` | NMR_Arcing_Blades |  |
| `0x1000042f` | VFX_CBT_Hit_Shared_GameReplicate |  |
| `0x10000492` | wildcard_mace_throw_dash |  |
| `0x10000493` | Vfx_Atr_Overwhelm_Rage_GroundHit_Hit4 |  |
| `0x10000497` | (no name) |  |
| `0x100004c6` | _Ping_Alert | SuperStrength_Rubble_End |
| `0x100004c7` | UnSheath_Blade | _Ping_Alert_Enemy |
| `0x100004c8` | Sheath_Blade | _Ping_Retreat_Friendly |
| `0x100004c9` | _Ping_Retreat |  |
| `0x100004ca` | _Ping_Alert_Friendly |  |
| `0x100004cb` | _Ping_Retreat_Enemy | StopScript_Vfx_Blu_RubbleThrow |
| `0x100004cd` | a_SoundEvent | SuperStrength_PickupRubble |
| `0x100004e5` | StopScript_Vfx_Basic_Left | Vfx_WW_Protect_Target_Active |
| `0x100004ec` | Vfx_Glc_Blood_Hunt_Target_Hit |  |
| `0x100004f0` | StopScript_Vfx_Min_OutOfCombat | Vfx_Glc_Blood_Hunt_Target_Active |
| `0x100004f4` | Katana_Thousand_Cuts_2 | Vfx_Glc_Blood_Hunt_Target_Stop |
| `0x100004fa` | Wildcard_QSkill_1 | Vfx_Glc_Stalking_Strike_Target_Hit |
| `0x10000557` | Vfx_WW_Protect_Target_Hit | StopScript_Vfx_Min_Basic_Ranged_Right |
| `0x10000569` | Vfx_Stp_Super_Speed_Stop |  |
| `0x1000056c` | Vfx_Stp_Super_Speed_Hit | RunScript_Vfx_Blu_Mandible_Active |
| `0x1000056f` | Vfx_Stp_Super_Speed_Active |  |
| `0x1000058d` | Cloth_Wind | Vfx_WW_Blocking_Bracers_Taunt_Active |
| `0x100005b0` | _gmSUsageComponent_Proximity_OnChanneling | WildCard_QSkill_KryptoDash |
| `0x100005b1` | _gmSUsageComponent_Proximity_OnInduction |  |
| `0x100005b7` | Vfx_Stp_Consume_Matter_Consume_Hit | MovingActive |
| `0x100005d0` | Vfx_Stp_Detonate_Matter_Damaged_Hit | Wildcard_SkillR_Secondary |
| `0x100005d4` | Vfx_Stp_Bend_Spacetime_Target_Active | RunScript_SuperStrength_Object_Active |
| `0x100005d5` | Vfx_Stp_Bend_Spacetime_Success_Hit | Cloth_State_Wind_Gust |
| `0x100005d6` | Vfx_Stp_Bend_Spacetime_Active |  |
| `0x100005e8` | Staff_Activate | Vfx_Bat_Cape_Sweep_Target_Active |
| `0x100005f0` | Vfx_Bat_Cape_Sweep_Target_Stop | StopScript_Vfx_Ntw_LetsRide_Drive |
| `0x100005f3` | Vfx_Bat_Cape_Sweep_Target_Hit | a_MissileInitHook |
| `0x1000060e` | Vfx_Stp_Bend_Spacetime_Stop |  |
| `0x1000060f` | Vfx_Stp_Detonate_Matter_Opacity_Hit |  |
| `0x10000611` | Vfx_Stp_Bend_Spacetime_Target_Stop |  |
| `0x10000623` | Vfx_Cbt_Hit_Blood |  |
| `0x10000624` | Vfx_Stp_Consume_Matter_Opacity_Hit |  |
| `0x10000626` | Vfx_Stp_Consume_Matter_Beam_Hit |  |
| `0x10000629` | Vfx_Dom_Revenge_Start |  |
| `0x10000658` | Vfx_Zat_Status_Punish_Hit |  |
| `0x10000659` | Vfx_Zat_Status_Protect_Hit |  |
| `0x1000065a` | Vfx_Zat_Status_Dazzle_Hit |  |
| `0x1000065b` | Vfx_Zat_Status_Dash_Hit |  |
| `0x10000665` | Vfx_Glt_Constrict_Target_Active |  |
| `0x10000676` | Vfx_Stp_XRay_Vision_Detected |  |
| `0x10000679` | Vfx_Stp_XRay_Vision_Active |  |
| `0x100006db` | Vfx_Stp_XRay_Vision_Detected_Stop |  |
| `0x100006f4` | Vfx_Stp_Mindlink_Target_Stop |  |
| `0x100006f5` | Vfx_Stp_Mindlink_Target_Active |  |
| `0x100006f6` | Vfx_Stp_Mindlink_Cast_Stop |  |
| `0x100006f7` | Vfx_Stp_Mindlink_Cast_Active |  |
| `0x10000713` | Vfx_Shz_Shazam_Hit |  |
| `0x10000718` | Vfx_Gjk_Filth_Rat_Swarm_Bonus_Active |  |
| `0x1000071c` | Vfx_Gjk_Filth_Active |  |
| `0x10000726` | Vfx_Gjk_Filth_Stop |  |
| `0x10000728` | Vfx_Gjk_Filth_Rat_Swarm_Bonus_Stop |  |
| `0x1000076f` | Vfx_Shz_Lightning_Field_Hit_Stop |  |
| `0x10000770` | Vfx_Shz_Lightning_Field_Hit_Active |  |
| `0x10000781` | Vfx_Cbg_Paralyzing_Shock_Active |  |
| `0x10000783` | Vfx_Cbg_Trace_Energy_Active |  |
| `0x100007a0` | SuperStrength_ThrowObject |  |
| `0x100007a1` | SuperStrength_PickupObject |  |
| `0x100007a2` | SuperStrength_InitObjectPickup |  |
| `0x10000805` | _SUpgradeSystem_OnCurrencyGained |  |
| `0x1000085d` | Vfx_Arc_Glt_Shackles_Target_Active |  |
| `0x1000086e` | Vfx_Arc_Glt_Emerald_Light_Target_Active |  |
| `0x10000889` | Vfx_Atm_Glt_Meltdown_Tgt_Active |  |
| `0x1000088e` | Vfx_Atm_Glt_Rads_Tgt_Active_1 |  |
| `0x1000088f` | Vfx_Atm_Glt_Rads_Tgt_Active_2 |  |
| `0x10000892` | Vfx_Atm_Glt_Rads_Tgt_Sickness_Active |  |
| `0x10000893` | Vfx_Atm_Glt_Rads_Tgt_Active_3 |  |
| `0x100008b2` | Vfx_Stp_Psychic_Assault_Start |  |
| `0x100008b3` | Vfx_Stp_Psychic_Assault_Stop |  |
| `0x100008b4` | Vfx_Stp_Psychic_Assault_Active |  |
| `0x100008b5` | Vfx_Stp_Invulnerability_Active |  |
| `0x100008b6` | Vfx_Stp_Invulnerability_Stop |  |
| `0x100008b7` | Vfx_Stp_Invulnerability_Start |  |
| `0x100008d7` | Vfx_Mec_WW_Judge_Tgt_Active_1 |  |
| `0x100008da` | Vfx_Mec_WW_Judge_Tgt_Active_2 |  |
| `0x100008dd` | Vfx_Mec_WW_Afterburn_Tgt_Active |  |
| `0x100008e6` | Vfx_Arc_Glt_Deny_Target_Active |  |
| `0x100008f6` | Vfx_Aww_Reclaimer_Mark_Active |  |
| `0x10000938` | Vfx_Stp_Trap_Target_Active |  |
| `0x10000946` | Vfx_Har_Bff_Preview_Active |  |
| `0x10000948` | Vfx_Har_Bff_Target_Active |  |
| `0x10000954` | Vfx_Fade_Out_ClientOnly |  |
| `0x10000955` | Vfx_Fade_In_ClientOnly |  |
| `0x1000096d` | Vfx_Glc_Predators_Mark_Active |  |
| `0x10000980` | Vfx_Atm_Ivy_Bramble_Tgt_Active |  |
| `0x10000995` | Vfx_Atm_Ivy_Bramble_Toxic_Tgt_Active |  |
| `0x100009b2` | Vfx_Atm_Ivy_Thorn_Wall_Toxic_Tgt_Active |  |
| `0x100009ba` | Vfx_Item_Store_Aoe_Shrapnel_Active |  |
| `0x100009c1` | Vfx_Item_Sword_of_Beowulf_Active |  |
| `0x100009c2` | Vfx_Item_Shrapnel_Active |  |
| `0x100009eb` | Cinematic_Hidden |  |
| `0x100009ec` | Cinematic_Intro |  |
| `0x100009ed` | Vfx_Item_Mystical_Inversion_Active |  |
| `0x100009ee` | Vfx_Item_Desperate_Endurance_Active |  |
| `0x100009ef` | Vfx_Item_Aura_Pos_Power_Armor_Active |  |
| `0x100009f0` | Vfx_Item_Stasis_Active |  |
| `0x100009f1` | Vfx_Item_Lazarus_Effect_Active |  |
| `0x100009f2` | Vfx_Item_Bastion_Active |  |
| `0x100009f3` | Vfx_Item_Aura_Neg_Power_Armor_Active |  |
| `0x100009f5` | Vfx_Item_Iron_Will_Active |  |
| `0x100009f6` | Vfx_Item_Intensity_Active |  |
| `0x100009f7` | Vfx_Item_Frenzy_Active |  |
| `0x100009f8` | Vfx_Item_Desperate_Speed_Active |  |
| `0x100009fa` | Vfx_Item_Aura_Pos_Attack_Armor_Active |  |
| `0x100009fd` | Vfx_Item_Aura_Pos_Power_Damage_Active |  |
| `0x100009fe` | Vfx_Item_Aura_Neg_Attack_Speed_Active |  |
| `0x100009ff` | Vfx_Item_Aura_Pos_Attack_Speed_Active |  |
| `0x10000a01` | Vfx_Item_Skill_Block_Active |  |
| `0x10000a4c` | Vfx_Item_Disintegration_Active |  |
| `0x10000a92` | Vfx_Ssr_Manifest_Active |  |
| `0x10000a96` | Vfx_Item_Burning_Core_Active |  |
| `0x10000a9e` | Cinematic_Victory |  |
| `0x10000b0c` | Vfx_Mec_Sup_Terraformer_Target_Active |  |
| `0x10000b36` | Vfx_Gar_Thermite_Active |  |
| `0x10000cda` | Vfx_Atr_Plasma_Target_Active |  |
| `0x10000d5f` | Vfx_Atm_Jkr_Acid_Mark_Active |  |
| `0x10000d67` | Vfx_Item_Mystical_Surge_Active |  |
| `0x10000d6e` | Vfx_Item_Blood_Bargain_Active |  |
| `0x10000d9e` | Vfx_Sto_Parasite_Slave_Active |  |
| `0x10000dba` | Vfx_Atr_Overwhelm_Rage_Target_Active |  |
| `0x10000dcc` | Vfx_Arc_Sug_Daughter_Active |  |
| `0x10000e0b` | Vfx_Stg_Conversion_Target_Active |  |
| `0x10000e0c` | Vfx_Stg_Blast_Target_Active |  |
| `0x10000e58` | Cinematic_FadeToBlack_Stop |  |
| `0x10000e59` | Cinematic_FadeToBlack |  |
| `0x10000ead` | Vfx_Test_Krp_Stick_Tgt_Active |  |
| `0x10000eb4` | Vfx_Test_Krp_Friend_Tgt_Active |  |
| `0x10000ec1` | Vfx_Test_Krp_Hunt_Tgt_Active |  |
| `0x10000ec9` | Vfx_Krp_Stick_Tgt_Active |  |
| `0x10000eca` | Vfx_Krp_Hunt_Tgt_Active |  |
| `0x10000ecb` | Vfx_Krp_Friend_Tgt_Active |  |
| `0x10000edd` | Vfx_Sug_Comet_Target_Active |  |
| `0x10000f80` | Vfx_GuideArrow |  |
| `0x10000f86` | Vfx_GuideArrow_Ping |  |
| `0x1000108b` | Vfx_Stp_Detonate_Matter_Beam_Hit |  |
| `0x1000108f` | Vfx_Fade_Out_Instant |  |
| `0x100010c6` | Vfx_Kta_Cuts_Primary_Target_Mark |  |
| `0x100010cf` | Vfx_Kta_Cuts_Primary_Target_Mark_Stop |  |
| `0x100010d0` | Vfx_Kta_Cuts_Primary_Target_Mark_Active |  |
