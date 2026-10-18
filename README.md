# Infinite Crisis preservation server

A private server for the 2015 Steam client of **Infinite Crisis** (Turbine / Warner Bros., shut down in 2015).
The goal is preservation: being able to play again with your own copy of the game. The current focus is
**Tutorial 1** with Gaslight Batman, as a test bed for the champion, combat and ability systems that the
other game modes will need later.

It builds on everything the [infinite-crisis-server](https://github.com/EricHardiman/infinite-crisis-server)
project by EricHardiman worked out: the message format, the event IDs and the original exe patches. This
server reorganises it (one session per connection, timers per match, all settings in a config file) and goes
much further into the tutorial. The messages it sends for the shared parts are **byte-for-byte identical** to
those of the earlier server (`tests/test_compat.py` checks 26 of them).

> Infinite Crisis is a trademark of Warner Bros. Entertainment / DC Comics. This project ships **no game
> files** and no data extracted from them; you need your own Steam copy of the game.

## Documentation

| File | Contents |
|---|---|
| `README.md` | This file: install, usage, configuration, tools. |
| [`docs/reverse-engineering.md`](docs/reverse-engineering.md) | Everything found about the client: data formats, skills and ability data, events, minimap notes, props, camera, and every exe patch. |
| [`docs/batman_actions.md`](docs/batman_actions.md) | The 354 scriptlet keys Gaslight Batman accepts, with probable names and which ones were confirmed in game. |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Development log, build by build (`fase3-xx` = build tag), including what was tried and what failed. |
| `data/batman_actions.tsv` | Batman's scriptlet keys as `key<TAB>probable name`. |

## Installation

1. **Python 3.11 or newer (64-bit)**, then:
   ```
   pip install pycryptodome
   ```
2. Put this folder anywhere (it does not need to be inside the game folder; the usual setup is
   `<game folder>\icserver`).
3. Copy `config.example.toml` to `config.toml` and set `dir` under `[game]` to your game folder
   (the one with `InfiniteCrisis.exe` and the `rp` folder).
4. **Champion list:** copy `champions.json` from the earlier project into `data\` (if your clone of it is at
   `<game>\_server` it is also found there). It stays local: `.gitignore` keeps it out of the repository.
5. **Close the earlier server** (`login_server.py` and `tracer.py`) if it is running: it uses the same ports.

## Usage

```
python ic.py doctor     checks everything and tells you how to fix each problem
python ic.py patch      creates the server key and InfiniteCrisis_patched.exe (with that key)
python ic.py play       starts the server and launches the game
```

Also available:

| Command | What it does |
|---|---|
| `python ic.py server` | Server only (launch the game yourself). |
| `python ic.py client-args` | Prints the game's command-line arguments. |
| `python ic.py patch --newkey` | New key + new patched exe. |
| `python ic.py play --classic` | Uses the older player object (`0x40000086`) if loading gets stuck. |
| `python ic.py layout 0xa0000256` | Lists everything placed in a pack: name, world state, position and heading. |
| `python ic.py variants 0xa0000257` | Which character variant (with health) belongs to each world state. |
| `python ic.py entities 0x2E000AAB ...` | Searches ALL packs for the entity (0x40…) of each world state; writes `logs\entities.txt`. |
| `python ic.py carriers` | Finds entities whose world state resembles the vehicle's (property 0x50F), usable as prop carriers; writes `logs\carriers.txt`. Slow. |
| `python ic.py dump <DIDs>` | Searches every pack for the given records, the records they name and who references them; writes `logs\dump.txt`. Slow. |

Options: `--config file.toml`, `--force` (start even if doctor finds problems).

**Re-run `python ic.py patch` whenever a build adds exe patches** (the changelog marks those builds with
"requires `python ic.py patch`"). `doctor` reports which patches are missing.

In game: log in with any user name and password, then
**Play Now → VS A.I. → Tutorial → Tutorial 1 → Launch**.

### Logs (`logs\`)

| File | Contents |
|---|---|
| `server.log` | Every step of loading and of the tutorial script, one line each. Start here. |
| `traffic.log` | Every message with a hex dump (`[debug] hexdump`). |
| `unhandled.log` | Messages the client sends that the server does not handle yet. This is where missing features show up. |

## Configuration

Everything lives in `config.toml` (see `config.example.toml`; defaults are in `icserver/config.py`).
Main sections:

| Section | What it controls |
|---|---|
| `[game]` | Game folder, exe names, language, region, CPU affinity. |
| `[server]` | Host, ports (SOAP 8888, user 9000, game 9001), key file, champions.json. |
| `[match]` | Champion, player object class, spawn point, intro cinematic, health. |
| `[timing]` | Load timing, keep-alive, movement rate and speed, ping lifetime. |
| `[tutorial]` | Guide markers, meteors (size, scale property), crater, knockdown, Catwoman cinematic, pacing. |
| `[combat]` | Drones (health, damage, range), obstacles, prop carriers, cooldowns (`cooldowns`, `enforce_cooldowns`). |
| `[scripts]` | Scriptlet keys played for basic attacks, hits and deaths. |
| `[debug]` | Hex dumps, `logs\send.txt`, and the **action tour** (`tour_keys`, `tour_interval`, `tour_start`). |

The action tour plays scriptlet keys on Batman one at a time after the tutorial starts, to see which
animations work: `tour_keys = "core"` (25 main keys), `"all"` (all 354 from `data/batman_actions.tsv`) or a
list such as `[0x10000163, 0x10000165]`. Each key is logged as `tour N/M: <key> <label>`.

## Tools (`tools\`)

These read your own game install and write their findings to `logs\`. They never copy game files.

| Tool | What it does |
|---|---|
| `tools\diag.py` | Attaches to the running client as a lightweight debugger and logs what the client does at chosen addresses (`logs\diag.log`). Flags: `--walk`, `--walk-only`, `--fix`, `--force`, `--started`, `--hfsm`, `--scripts`, `--entities`, `--packs`, `--ranks`, `--q`, `--fog`, `--team`, `--notes`, `--minimap`, `--create`, `--place`, `--stolen`, `--props`. |
| `tools\diag_walk.py` | Shortcut for `diag.py --walk --walk-only`. |
| `tools\skills.py` | Readable dump of a champion's skill records with their English texts (`logs\skills.txt`). `python tools\skills.py "Gaslight Batman"` or a record DID such as `0x48000615`. |
| `tools\find_scripts.py` | Searches the packs for the client's Lua scripts related to skills/progression. |
| `tools\extract_records.py` | Extracts raw records by DID into `logs\records\` (default: Gaslight Batman's scriptlets). |

`diag.py` result codes for scriptlet orders: `0` = started, `1` = ignored by the game,
`0x80070057` = invalid ID, `0x8000ffff` = the entity has no script component.

## For developers

- `logs\send.txt`: every line `<player|svc|id hex> <event hex> <body hex>` is sent to the client within 1 s
  (`[debug] dev_send_file`).
- `python tests/test_e2e.py config.toml`: a full match against a simulated client, including leaving,
  logging in again, double-clicking Launch, combat and the whole tutorial script up to the victory
  (169 checks). Use other ports in that test config.
- `python tests/test_compat.py <earlier _server folder>`: byte-for-byte comparison with the earlier server.
- `python tests/test_jump.py config.toml`: each `[tutorial] start_at` jump starts where it should.
- `python tests/test_layout.py <rp folder>`: checks that the tutorial table matches the packs.

Code layout:

| File | What it does |
|---|---|
| `ic.py` | Command-line entry point. |
| `icserver/wire.py` | Binary format. |
| `icserver/messages.py` | Protocol messages. |
| `icserver/session.py` | Sessions, load sequence, movement, combat, casting. |
| `icserver/tutorial1.py` | Tutorial 1 script, part 1 (markers, meteors, crater, drones, thug, pings, Q, action tour). |
| `icserver/bridge.py` | Tutorial 1 part 2: the bridge, from Catwoman's pursuers to the Bat Scream (gates, drone groups, rank-ups, the camera, R). |
| `icserver/finale.py` | Tutorial 1 part 3: Super Strength (lift and throw cars), the Destroyer, the ending. |
| `icserver/skilldata.py` | Builds a Stolen Power slot's skill collection (D / F) from the game data and `logs\props.txt`. |
| `icserver/batman.py` | Gaslight Batman's W (Sonic Shell), E (Bat Flight), R (Bat Scream) and Stolen Power (surveillance camera). |
| `icserver/abilities.py` | Ability engine (kits, cooldowns, cooldown event 0x20F8). |
| `icserver/world.py` | Obstacles, pathing, fog of war. |
| `icserver/rp.py` | Reader for the game's `.rp` packs. |
| `icserver/scheduler.py` | Per-match timers. |
| `icserver/server.py` | Ports and SOAP login. |
| `icserver/crypto.py` | Login key exchange. |
| `icserver/doctor.py` | Installation checks. |
| `icserver/patcher.py` | Exe patches (each one documented in the source and in `docs/reverse-engineering.md`). |
| `icserver/config.py` | Config loading and defaults. |

## Status

Working in Tutorial 1: login, lobby and loading; intro cinematic; movement with obstacles; guide markers and
arrows; the street vehicle, meteors and the meteor crater; the drone fight with the human thug; practice
drones and waves; basic attacks with animations; skill ranking with the "+" button; Sonic Batarang (Q) with
cooldown display; minimap with the real map, Batman, team colours and player pings; fog of war; the
Catwoman cinematic; then the bridge: her pursuers, W (Sonic Shell) and E (Bat Flight) unlocked and practised
on target drones, the blue gates, drone ambushes (melee and ranged), the surveillance camera on D, the passive,
the drones at the vehicle, the R unlock and the Bat Scream at the drones the camera spots; then Super Strength
(lifting and throwing cars), the Destroyer and the ending (positions estimated from video).

To test a later part without replaying the start: `[tutorial] start_at = "bridge"` (or `"camera"`,
`"gate_fight"`, `"unlock_e"`, `"e_practice"`, `"vehicle"`, `"scream"`, `"strength"`, `"destroyer"`).

The D and F buttons need `logs\props.txt`: run `python tools\diag.py --props` once (start it in the menu,
then enter the tutorial).

Next: the real victory screen, positions checked against the original (see
[`docs/reverse-engineering.md`](docs/reverse-engineering.md#remaining-tutorial-1-content)).

## One folder, ready for GitHub

Everything the server and its tools need lives in this folder: the diagnostic's debugger is `tools\tracer.py`
(taken from the earlier project), so `[debug] old_server_dir` is no longer needed.

These stay local and are kept out of the repository by `.gitignore`:
- `config.toml`;
- `keys\*.pem`;
- `logs\`;
- `data\champions.json` and `data\progress.json`;
- every `.exe`.

No game file belongs in the repository.

Only `python tests/test_compat.py` still uses the earlier project, to compare with its server byte for byte; it
is optional.


## Game ID catalog

`catalog/index.html` lists every game ID the server uses (champions, skills, Stolen Powers, stages, protocol
events, properties, ...) with search and copy buttons. Rebuild it with `python ic.py catalog`; see
[`catalog/README.md`](catalog/README.md).
