"""Builders for the post-match (tutorial) scorecard data (fase3-ew), decoded statically from
InfiniteCrisis.exe (MD5 950afb82...) and the UI pack 0xA00000D0 ActionScript.

Conventions match icserver/messages.py: every function returns a full game message
(build_message(dest, event_id, body)); bodies start with the u8 0 "base" byte read by
VA 0xb0d380. All events below are executed through the player-system resolver
(VA 0x882a80), i.e. they go to SVC_PLAYER_SYSTEM like the lobby events.

Readers referenced as "ser" are the event serializers (read path), "exec" the
handler; field order is the wire order of the read path.

Sub-encodings used here (all verified on the read paths):
  u32list   (VA 0x4e4530)  u32 count | count x u32
  bytelist  (VA 0x53f350)  u32 count | count x u8          (0x844230 wrapper)
  table     (VA 0x847550 / 0x583dd0 / 0x8473d0)  u8 size class | compact count | entries
            -> empty table = b"\\x00\\x00"
  StringInfo (VA 0x5a9580) string_info(text)  (empty = 01 00 00 00)

The ScorecardManager (AS2, gameplay.singleton.ScorecardManager.CheckForAllDataReceived)
raises ALL_DATA_RECVD only when ALL of these flags are set:
  bRecvdHeaderNameAndProtectorIcons      <- 0x2190 / 0x2154            (always required)
  bRecvdEndOfMatchStats                  <- 0x2045                     (always required)
  bRecvdEndOfMatchStatsHeader            <- (built by the client)      (skipped for tutorials)
  bRecvdPowerGraphValues                 <- in-match upgrade data      (skipped for tutorials)
  bRecvdCurrentUpgrades                  <- in-match upgrade data      (skipped for tutorials)
  bRecvdAccoladesEarned                  <- 0x2188 (or 0x2104)         (always required)
  bRecvdAccountEndOfMatchLevelAndXP      <- 0x2080                     (always required)
  bRecvdAccountCurrencyBalance           <- 0x2081                     (always required)
  bRecvdAccountEndOfMatchSoftCurrencyReward <- 0x20B9                  (always required)
  bRecvdAccountEndOfMatchCharacterLevelAndXP <- 0x2104                 (always required)
  bRecvdAmpliferSetManagerData           <- AmplifierSetManager loaded (0x2090; preset True
                                            if the manager already had its data)
  RankedManager.bStaticRankDataLoaded    <- 0x219F (static standings come from client data)
  RankedManager.bAccountStandingsLoaded  <- 0x219F / 0x219E
"m_bIsTutorial" is EncounterManager.IsTutorial(didEncounter of the 0x2045-driven
SendEndOfMatchStats), so the encounter DID the client has for the match must be
0x40000991.

The client's four "Request..." notices (0x100003F1 char level/XP, 0x100003F2 soft
currency, 0x100003FA account level/XP, 0x100004E6 accolades) are Flash->C++ notices
(writers VA 0x931440/0x9314b0/0x9313d0/0x931360 -> listener slots +0x44/+0x48/+0x40/+0x3c);
the C++ side answers them from its cache (VA 0xa1a100) of the last 0x2104/0x20B9/0x2080/
0x2188 it received. They are NOT sent to the server: just send the events (before or
after the scorecard loads; resending is harmless).
"""
import struct

from .messages import SVC_PLAYER_SYSTEM
from .wire import build_message, pack_compact, string_info

EMPTY_TABLE = b"\x00\x00"           # u8 size class 0 | compact count 0


def _u32(*vals):
    return struct.pack("<%dI" % len(vals), *[v & 0xFFFFFFFF for v in vals])


def _f32(v):
    return struct.pack("<f", float(v))


def _u32list(vals=()):
    vals = list(vals)
    return _u32(len(vals)) + b"".join(_u32(v) for v in vals)


def _bytelist(vals=()):
    vals = list(vals)
    return _u32(len(vals)) + bytes(int(v) & 0xFF for v in vals)


# ---- 0x2038 match ended (UI event MatchEnded 0x12) -----------------------------------

def match_ended(room_id, force=1):
    """0x2038 (ser VA 0x68f240, exec 0x8b2ab0 -> 0xa79170): u8 0 | u32 roomId | u32 force.
    force != 0 skips the 'roomId == current lobby room' check; fires
    UIStateMachineEvent 0x12 (MatchEnded). Confidence: high (layout), medium (effect)."""
    return build_message(SVC_PLAYER_SYSTEM, 0x2038, b"\x00" + _u32(room_id, force))


# ---- header name + protector icons ------------------------------------------------------

def header_and_protector_icons(icon_dids=(0, 0, 0, 0, 0), unk1=0, unk2=0,
                               header_name="", sub_name="", unk3=0, flag=0):
    """0x2190 (ser VA 0x83f230, exec 0x8aaa00 -> 0xa57200 -> Flash
    GM_UI.RecvNotice_SendHeaderNameAndProtectorIcons):
    u8 0 | 5 x u32 icon DID (slots 0..4) | u32 | u32 | StringInfo | StringInfo | u32 | u8.
    Confidence: high (layout), medium (field meaning: icons 0x13... or 0)."""
    icons = (list(icon_dids) + [0] * 5)[:5]
    body = (b"\x00" + _u32(*icons) + _u32(unk1, unk2) + string_info(header_name)
            + string_info(sub_name) + _u32(unk3) + bytes([1 if flag else 0]))
    return build_message(SVC_PLAYER_SYSTEM, 0x2190, body)


def protector_icon_slot(icon_did, slot):
    """0x2154 (ser VA 0x68f240, exec 0x8ab190 -> 0xa571a0): u8 0 | u32 icon DID | u32 slot.
    Sets one header icon and re-sends the header to Flash. Confidence: high."""
    return build_message(SVC_PLAYER_SYSTEM, 0x2154, b"\x00" + _u32(icon_did, slot))


# ---- accolades -----------------------------------------------------------------------------

def accolades_earned(encounter_did=0x40000991, ranked=0, champion_did=0x40000086, title=""):
    """0x2188 (ser VA 0x845000, exec 0x8ab220 -> 0xa61da0 -> Flash
    SendAccountEndOfMatchAccoladesEarned(didEncounter, bRanked, didChampion, names[],
    descriptions[], summaries[], icons[], medalTypes[], isAllTimeBest[])):
    u8 0 | u32 didEncounter | u8 bRanked | u32 didChampion | StringInfo |
    u32list | u32list | u32list | bytelist | u32list | u32list   (all empty = no accolades).
    Confidence: high (layout)."""
    body = (b"\x00" + _u32(encounter_did) + bytes([1 if ranked else 0]) + _u32(champion_did)
            + string_info(title) + _u32list() + _u32list() + _u32list() + _bytelist()
            + _u32list() + _u32list())
    return build_message(SVC_PLAYER_SYSTEM, 0x2188, body)


# ---- account level / XP ----------------------------------------------------------------------

def account_level_xp(level=1, prev_level=1, xp_to_next=100, xp_total=0, xp_earned=0, xp_bonus=0,
                     pct=0.0, prev_pct=0.0):
    """0x2080 (ser VA 0x8392f0, exec 0x8aaac0 -> 0xa7dfb0 -> Flash
    SendAccountEndOfMatchLevelAndXP(level, prevLevel, xpToNext, xpTotal, xpEarned, xpBonus,
    pct, prevPct)): u8 0 | 6 x u32 | f32 | f32. Same as messages.initial_events' 0x2080
    (also feeds the landing/advancement code; safe to resend at match end).
    Confidence: high."""
    body = (b"\x00" + _u32(level, prev_level, xp_to_next, xp_total, xp_earned, xp_bonus)
            + _f32(pct) + _f32(prev_pct))
    return build_message(SVC_PLAYER_SYSTEM, 0x2080, body)


def currency_balance(hard=0, soft=0):
    """0x2081 (ser VA 0x68f240, exec 0x8aa970 -> 0xa1ab40 -> Flash
    SendAccountCurrencyBalance(hard, soft)): u8 0 | u32 hard | u32 soft. Confidence: high."""
    return build_message(SVC_PLAYER_SYSTEM, 0x2081, b"\x00" + _u32(hard, soft))


def soft_currency_reward(base=0, daily=0, time_till_next_daily=0.0, streak=0, potential_daily=0,
                         potential_streak=0, streak_tooltip="", queue_tooltip="", unk=0):
    """0x20B9 (ser VA 0x83bb90, exec 0x8aaeb0 -> 0xa1aa50 -> Flash
    SendAccountEndOfMatchSoftCurrencyReward(base, daily, fTimeTillNextDaily, streak,
    potentialDaily, potentialStreak, siStreakTooltip, siQueueTooltip)):
    u8 0 | u32 | u32 | f32 | u32 | u32 | u32 | StringInfo | StringInfo | u32.
    Confidence: high (layout; the third value is used as a float by Flash)."""
    body = (b"\x00" + _u32(base, daily) + _f32(time_till_next_daily)
            + _u32(streak, potential_daily, potential_streak)
            + string_info(streak_tooltip) + string_info(queue_tooltip) + _u32(unk))
    return build_message(SVC_PLAYER_SYSTEM, 0x20B9, body)


def character_level_xp(champion_did=0x40000086, icon_did=0, name="Gaslight Batman", level=7,
                       prev_level=7, xp_to_next=0, xp_total=0, xp_earned=0, xp_bonus=0,
                       pct=0.0, prev_pct=0.0, unk=0, flag=0):
    """0x2104 (ser VA 0x849680, exec 0x8aadb0 -> 0xa7e0a0 -> Flash
    SendAccountEndOfMatchCharacterLevelAndXP(didCharacter, didCharIcon, sCharName, level,
    prevLevel, xpToNext, totalXP, xpEarned, xpBonus, pct, prevPct) and, from the trailing
    lists, SendAccountEndOfMatchAccoladesEarned):
    u8 0 | u32 didCharacter | u32 didIcon | StringInfo name |
    u32 level | u32 prevLevel | u32 xpToNext | u32 totalXP | u32 xpEarned | u32 xpBonus |
    f32 pct | f32 prevPct | table (empty 00 00) | u32list | u32list | u32list | bytelist |
    u32list | u32list | u32 | u8.
    Confidence: high (layout), medium (meaning of the trailing u32/u8)."""
    body = (b"\x00" + _u32(champion_did, icon_did) + string_info(name)
            + _u32(level, prev_level, xp_to_next, xp_total, xp_earned, xp_bonus)
            + _f32(pct) + _f32(prev_pct) + EMPTY_TABLE
            + _u32list() + _u32list() + _u32list() + _bytelist() + _u32list() + _u32list()
            + _u32(unk) + bytes([1 if flag else 0]))
    return build_message(SVC_PLAYER_SYSTEM, 0x2104, body)


# ---- amplifier sets --------------------------------------------------------------------------

def amplifier_sets(unk1=0, unk2=0):
    """0x2090 (ser VA 0x8481a0, exec 0x8aa0c0 -> 0xa64520 -> Flash NotifyListAmplifierSets):
    u8 0 | u32 | u32 | u32 count | count x amplifier set (VA 0x86fb20, 0x50 bytes in memory;
    wire: u32 | u64 | u32 | StringInfo | wstring | u32 | compact-count list).
    Empty list. Confidence: high (layout), medium (whether an empty list sets
    AmplifierSetManager.hasAllAmplifierData)."""
    return build_message(SVC_PLAYER_SYSTEM, 0x2090, b"\x00" + _u32(unk1, unk2) + _u32(0))


# ---- ranked standings ------------------------------------------------------------------------

def account_standings(values=(0,) * 10):
    """0x219E (ser VA 0x83feb0, exec 0x8bad90 -> 0xa37dc0 -> Flash
    UI_DeliverAccountStandingsData): u8 0 | 10 x u32. Confidence: high (layout)."""
    vals = (list(values) + [0] * 10)[:10]
    return build_message(SVC_PLAYER_SYSTEM, 0x219E, b"\x00" + _u32(*vals))


def standings_full(values=(0,) * 5):
    """0x219F (ser VA 0x848b80, exec 0x8ba560 -> 0xa5c840): u8 0 |
    struct (VA 0x847780): 9 x u32list | u32 count list (VA 0x8448e0, empty) |
    5 x u32.  The handler rebuilds the STATIC standings from client data (VA 0xa4ca10,
    table 0x100000FA) and calls Flash UI_DeliverStaticStandingsData (VA 0xa0da80), then the
    account standings (UI_DeliverAccountStandingsData). Confidence: high (layout), medium
    (that empty lists are accepted)."""
    vals = (list(values) + [0] * 5)[:5]
    body = b"\x00" + b"".join(_u32list() for _ in range(9)) + _u32(0) + _u32(*vals)
    return build_message(SVC_PLAYER_SYSTEM, 0x219F, body)


# ---- achievements (low confidence) -----------------------------------------------------------

def achievements(progress=(), completed_dids=()):
    """0x2120 (ser VA 0x849540, exec 0x8a9bb0 -> 0xa870e0 -> 0xa839e0):
    u8 0 | table (u8 size class 0 | compact n | n x entry) | u32list completed?
    entry (VA 0x846800): u32 achievementDID | progress (VA 0x8717c0):
        u32 a | u32 b | u64 c | u32 count | count x objective (VA 0x860da0):
            u32 | u32 | u32 | u32 | u64 | u8
    `progress` = list of (did, a, b, c, [objective tuples (u32,u32,u32,u32,u64,u8)]).
    The meaning of a/b/c and of the trailing u32 list is NOT decoded; the Training
    achievement definitions (category Training_AchievementCategoryType = 2) are not in any
    local pack, so the DID for "complete Tutorial 1" is unknown. Confidence: medium (layout),
    low (semantics)."""
    entries = b""
    for did, a, b, c, objs in progress:
        entries += _u32(did, a, b) + struct.pack("<Q", c) + _u32(len(objs))
        for o1, o2, o3, o4, o5, o6 in objs:
            entries += _u32(o1, o2, o3, o4) + struct.pack("<Q", o5) + bytes([o6 & 0xFF])
    body = b"\x00" + b"\x00" + pack_compact(len(progress)) + entries + _u32list(completed_dids)
    return build_message(SVC_PLAYER_SYSTEM, 0x2120, body)


# ---- suggested sequence ----------------------------------------------------------------------

def scorecard_bundle(player_name="", hard=0, soft=0, account_level=1, encounter=0x40000991,
                     champion=0x40000086, champion_name="Gaslight Batman", level=7):
    """Everything the tutorial scorecard waits for, in a safe order (send right after
    NotifyMatchEnded + 0x2045; resend after the post-encounter movie if needed)."""
    return [
        ("header + protector icons (0x2190)", header_and_protector_icons(header_name=player_name)),
        ("currency balance (0x2081)", currency_balance(hard, soft)),
        ("account level/XP (0x2080)", account_level_xp(account_level, account_level, 0, 100)),
        ("soft currency reward (0x20b9)", soft_currency_reward()),
        ("character level/XP (0x2104)", character_level_xp(champion, name=champion_name, level=level,
                                                             prev_level=level)),
        ("accolades (0x2188)", accolades_earned(encounter, champion_did=champion)),
        ("amplifier sets (0x2090)", amplifier_sets()),
        ("standings (0x219f)", standings_full()),
        ("account standings (0x219e)", account_standings()),
    ]



# ==== training achievements (fase3-ex) ====================================================
# Training-achievement (Tutorial 1/2/3) messages, decoded statically from
# InfiniteCrisis.exe and the uploaded achievement records (scratchpad/achz/achievements,
# read with python -I) + UI pack 0xA00000D0 ActionScript.  Same conventions as
# scorecard_msgs.py: each builder returns a full message, body starts with u8 0, both
# events run through the player-system resolver (0x882a80) -> SVC_PLAYER_SYSTEM.
# 
# Client pipeline (all client-side, nothing else is needed from the server):
#   0x2120 (ser 0x849540, exec 0xa870e0 -> 0xa839e0): stores progress table at
#     AchMgr+0x1c, u32list at +0x30, sets +0x40=0 / +0x41=1 (= "server data received"),
#     then a42430 -> Flash SetAchievementObjectiveData per entry (+ SetDeprecatedAchievements
#     from the u32list), then a70db0 (ProtectorAdvancementStatus), then 0x90e000.
#   Achievement *definitions* (SetAchievementData: name, reward names, promotion images)
#     come from client data (0x100000B7 / 0x1000099F master list, a428b0) - not the server.
#   Flash OverallProgress = avg over objectives of min(cur/target,1)*100, Previous the same
#     with `previous`; target = objective struct prop 0x10000A2F (=1 for all 3 tutorials).
#   Trainee list AchMgr+0x54 is filled lazily (a21ac0) from game setting
#     "Client_Trainee_AchievementList" or config 0x100000C2 -> prop 0x10000BAC =
#     [0x40000B08, 0x40000BD5, 0x40000C59, 0x40000EB9, 0x40000EBA]  (no server data).
#   a43530 -> Flash TraineeAchievements(DIDs, turntable movies (achievement 0x10000A5C reward
#     set -> character -> heavy rec prop 0x10000C58), Queue=0x10000BAE, UITransition=0x10000BAD,
#     StepsOnRails = setting "Client_Trainee_StepsOnRails" default 3).
#   ProtectorAdvancementStatus (a70db0, ecx = account a12d50()+0x54), only when
#     AchMgr+0x41 (0x2120 seen), account+0x8c != 0, account+0x88 != 0, a12d50()+0x68 obj+0xc != 0
#     and global byte 0x1b758d3 are set.  If session override account+0x48 == 0:
#       TimesCompleted(list[0]=0x40000B08)==0 and account+0x8c==1 and account+0x44==0
#             -> 3 FirstTimePlayer (+ intro movie unless user pref 0x15a2980 already set)
#       elif TimesCompleted(list[-1]=0x40000EBA)==0 and account+0x8c < 5 -> 2 Trainee
#       else -> 1 Player.
#     Status 2/3 -> a630c0 loads light packs, then a630a0 -> a43530 (TraineeAchievements).
#   Training-missions screen (AS2 TraineeAchievements class) unlocks button i when all
#     previous have OverallProgress==100 (and i < StepsOnRails); NextChallenge (Mission
#     Complete page) shows the first trainee achievement with OverallProgress < 100.
#   "Champion Unlocked" = RibbonManager.ShowSuperRewardRibbon, driven by Flash notice
#     RewardSetsData (0x10000402) which C++ (a41300) sends from its pending-reward list
#     (account+0x10), filled by event 0x2125 (exec a7ebb0 -> a7ea80); passed to Flash ONLY on arrival (fase3-fe: not re-sent on
#     0x2190).  bSuperReward = item type 7 (Character) or 0xA, item type is computed by the
#     client from the item DID (0x86e830).  On dismiss Flash sends ClaimPostMatchReward
#     (0x100003F5, setDID) and queries InqSuperBannerVideoForAchievement(sourceDID) ->
#     ShowMovieDialog = the turntable/abilities showcase.


# trainee achievements (client config 0x48000E76 / prop 0x10000BAC), with record values
TRAINEE_LIST = (0x40000B08, 0x40000BD5, 0x40000C59, 0x40000EB9, 0x40000EBA)
TUTORIALS = {
    # n: (achievement, encounter 0x10000B0A (=Queue 0x10000BAE), reward set 0x10000A5C, step 0x10000C1E)
    1: (0x40000B08, 0x40000991, 0x40000B07, 1),
    2: (0x40000BD5, 0x40000A81, 0x40000C57, 2),
    3: (0x40000C59, 0x40000CA6, 0x40000C55, 5),
}
OBJECTIVE_ID = 1          # 1-based index into the record's objective array 0x10000A2D (0x864df0)
OBJECTIVE_TARGET = 1      # 0x10000A2F in the single objective struct of all 3 tutorials
GASLIGHT_BATMAN = 0x40000086   # Character DID used by the tutorial (heavy rec 0x49000086 has 0x10000C58)
REWARD_GRANT = 2          # RewardBestowalTypeList.Grant
REWARD_SOURCE_ACHIEVEMENT = 1  # hard-coded by the 0x2125 handler


# ---- 0x2120 achievement progress ---------------------------------------------------------

def objective(obj_id=OBJECTIVE_ID, current=0, previous=0, unk=0, last_updated=0, has_progress=0):
    """Objective (ser 0x860da0, 0x20 bytes in memory):
    u32 objective index (1-based) | u32 current | u32 previous | u32 unk(+0xc, unused by UI)
    | u64 last-updated unix seconds (max -> LastUpdatedInUnixSeconds) | u8 HasProgress."""
    return (_u32(obj_id, current, previous, unk) + struct.pack("<Q", last_updated)
            + bytes([has_progress & 0xFF]))


def progress_entry(achievement_did, times_completed=0, time_valid=0, objectives=()):
    """Table entry: u32 key DID (0x846800) | value (0x8717c0):
    u32 achievement DID | u32 TimesCompleted (a26d80; drives ProtectorAdvancementStatus)
    | u64 TimeValid unix seconds (IsInFuture = > now; 0 is fine) | u32 n | n x objective."""
    objectives = list(objectives)
    return (_u32(achievement_did, achievement_did, times_completed) + struct.pack("<Q", time_valid)
            + _u32(len(objectives)) + b"".join(objectives))


def achievement_progress(entries=(), deprecated=()):
    """0x2120: u8 0 | hashtable (u8 size class | compact n | entries) | u32list
    deprecated achievement DIDs (-> Flash SetDeprecatedAchievements; NOT 'completed')."""
    entries = list(entries)
    body = b"\x00" + b"\x00" + pack_compact(len(entries)) + b"".join(entries) + _u32list(deprecated)
    return build_message(SVC_PLAYER_SYSTEM, 0x2120, body)


def trainee_progress(completed=0, just_completed=None, now=0):
    """0x2120 for the 5 trainee achievements.  `completed` = number of tutorials already
    done before this message (their objective current=previous=1, TimesCompleted=1).
    `just_completed` = tutorial number completed by this match (current=1, previous=0 ->
    OverallProgress 100 / OverallPreviousProgress 0 = 'newly completed')."""
    entries = []
    for i, did in enumerate(TRAINEE_LIST, 1):
        if i <= completed:
            cur, prev, times = 1, 1, 1
        elif just_completed == i:
            cur, prev, times = 1, 0, 1
        else:
            cur, prev, times = 0, 0, 0
        entries.append(progress_entry(did, times, 0, [
            objective(OBJECTIVE_ID, cur, prev, 0, now if cur != prev else 0, 1 if cur else 0)]))
    return achievement_progress(entries)


def login_achievements():
    """Replacement for initial_events' empty 0x2120: Tutorial 1 not done."""
    return trainee_progress(completed=0)


def tutorial_completed(n, now=0):
    """Match-end 0x2120 after tutorial n (1..3)."""
    return trainee_progress(completed=n - 1, just_completed=n, now=now)


# ---- 0x2125 pending reward sets (Champion Unlocked super ribbon) -------------------------

def reward_item(reward_set_did, source_did, item_did, quantity=1, bestowal=REWARD_GRANT,
                instance_id=1, icon_did=0, name="", unk=0):
    """Element (ser 0x867fb0, 0x48 bytes): u32 rewardSetDID | u32 sourceDID |
    u32 unk(+8, unused) | u32 itemDID | u32 quantity | u32 bestowalType | u64 pending-reward
    instance id (dedup via 0xa1aba0: use a fresh non-zero id) | u32 icon DID | StringInfo
    name (empty -> client default token 0x0A3A2149).  Consecutive elements with the same
    rewardSetDID form one set."""
    return (_u32(reward_set_did, source_did, unk, item_did, quantity, bestowal)
            + struct.pack("<Q", instance_id) + _u32(icon_did) + string_info(name))


def pending_reward_sets(items):
    """0x2125 (ser 0x846680 -> list 0x841e40, exec 0x8ab080 -> a7ebb0): u8 0 | u32 n | items."""
    items = list(items)
    body = b"\x00" + _u32(len(items)) + b"".join(items)
    return build_message(SVC_PLAYER_SYSTEM, 0x2125, body)


def tutorial_reward(n=1, instance_id=1, champion_did=GASLIGHT_BATMAN, name=""):
    ach, _enc, reward_set, _step = TUTORIALS[n]
    return pending_reward_sets([reward_item(reward_set, ach, champion_did, 1, REWARD_GRANT,
                                            instance_id, 0, name)])


def tutorial1_end_sequence(now=0, instance_id=1):
    """Order relative to scorecard_msgs: ... in-world ShowAnnouncement(VICTORY) -> delay ->
    NotifyMatchEnded/0x2038 -> 0x2045 -> [these two] -> scorecard_bundle (its 0x2190 also
    re-flushes the pending reward set to Flash)."""
    return [
        ("achievement progress, T1 newly complete (0x2120)", tutorial_completed(1, now)),
        ("pending reward: Gaslight Batman (0x2125)", tutorial_reward(1, instance_id)),
    ]

