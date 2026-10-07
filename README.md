# Infinite Crisis private server

A work-in-progress server emulator for **Infinite Crisis**, Turbine's DC Comics MOBA
(Steam app 345520, shut down in August 2015). The goal is to make the game playable again
against your own machine: login, menus, champion roster, and matches. Right now the first
tutorial mission loads and is partly playable.

Everything here was recovered by reverse engineering the Steam client. Nothing from
Turbine's servers survived, so every message the server sends was worked out from the
client's own code. The repository contains the server, the tooling used to trace the client,
and detailed notes. It does **not** contain any game files; you need the client from Steam.

## What works

- Launcher-free login through a local stand-in for Turbine's SOAP login service
  (any user name and password are accepted).
- The encrypted "user server" connection (RSA-1024 handshake, 3DES-CTR stream cipher)
  and the game-message layer on top of it.
- Landing screen, account data, champion roster with portraits and skills, encounter lists
  (Tutorial, VS A.I., PvP map lists), featured maps.
- Queue, match found, lobby, loading screen and world entry for **Tutorial 1,
  "A Champion in Peril"** (Gaslight Batman).
- In the world: intro cinematic with Superman's voiced conversation and captions, correct
  lighting, right-click movement at 60 Hz with walk animation and facing, guide arrows to
  scripted waypoints, the top-centre objective banner, tutorial hint panels, the champion's
  overhead nameplate (name, health, level), minimap notes, and player pings (Alt+click).

## What is being worked on

In rough order:

1. The green ground marker at the guide-arrow target (the minimap note already shows).
2. The minimap background image (the HUD loads it when asked; the native trigger is missing).
3. The first drone and basic attacks, then the rest of the Tutorial 1 script
   (skills, level-up, Catwoman, the base).
4. Tutorials 2 and 3, then real matches with AI.

`HANDOFF.md` is the running engineering log: what was tried, what failed, exact addresses in
the client, and the open questions. Read its top section first if you want to contribute.

## Requirements

- Windows. The client is a 32-bit Windows game; the server is plain Python but the tracing
  tools use the Windows debug API.
- The Infinite Crisis client from Steam. The game is delisted but still downloadable if it
  is in your library: press **Win+R** and run `steam://install/345520`. The default install
  path is `C:\Program Files (x86)\Steam\steamapps\common\Infinite Crisis Steam`.
- Python 3.11 or newer (64-bit) with `pycryptodome`. The analysis tools additionally use
  `pefile` and `capstone`.

```
pip install pycryptodome pefile capstone
```

## Setup

1. Clone this repository **into the game folder** as `_server`, so that
   `InfiniteCrisis.exe` and `_server\login_server.py` are siblings. The server and tools
   use relative paths to the game's `rp` data packs and executable.

2. Generate your login key pair, then build the patched client. Four small byte patches are
   applied to a copy of `InfiniteCrisis.exe` (the Steam file is left untouched):

   ```
   cd _server
   python tools\patch_client.py --newkey
   python tools\patch_client.py
   ```

   This writes `InfiniteCrisis_patched.exe` next to the original. The script verifies the
   original bytes first and aborts on an unknown build. The patches are:

   | File offset | Purpose |
   |---|---|
   | `0x11a1f5f` (128 bytes) | Replace the built-in RSA-1024 login key with the modulus of `keys/server_private.pem`, so the server can decrypt the session key. |
   | `0xbe3862` | Disable Oodle compression of outgoing game packets so the server can read them. |
   | `0x67ef34` | Let in-game conversations play without the "match started" state, which currently crashes the client. |
   | `0x11db16c` | Re-evaluate the lighting environment every 0.2 s instead of 2.5 s (removes a dark flash after the intro). |

   The key is written to `keys\server_private.pem`, which is ignored by git: the client only
   trusts the key baked into its own exe, so the server and the patched exe must be built
   from the same key.

3. Start the server:

   ```
   cd _server
   python login_server.py
   ```

   It listens on `127.0.0.1` only: SOAP login on port 8888, the user server on 9000 and the
   game server on 9001. Every request and reply is logged to `logs\requests.log`.

4. Start the game, bypassing Turbine's launcher:

   ```
   start "" /affinity FFFE InfiniteCrisis_patched.exe --loginurl http://127.0.0.1:8888/WebLoginApp-1.3/AuthenticateWS --loginregion NA --reportingurl http://127.0.0.1:8888/WebLoginApp-1.3/Metrics --language en
   ```

   `restart_test.ps1` does steps 3 and 4 together (and attaches the tracer, see below).
   You can also add `InfiniteCrisis_patched.exe` to Steam as a non-Steam game with those
   launch options.

5. Log in with any user name and password, then **Play Now → VS A.I. → Tutorial →
   Tutorial 1 → Select → Launch**. Press Esc to skip the intro movie.

## Repository layout

| Path | What it is |
|---|---|
| `login_server.py` | The whole server: SOAP login, user-server crypto, game messages, match flow, tutorial script. Heavily commented with the client addresses each message was derived from. |
| `check.py` | Syntax check plus a dump of the outgoing messages. Run it after every edit. |
| `restart_test.ps1` | Kills server, tracer and game; starts all three. |
| `tracer.py` | A logging debugger (no pausing) that attaches to the running client and logs breakpoint hits, script calls and exceptions to `logs\trace.log`. Add an address to `BREAKPOINTS` to trace a new function. |
| `peek.py`, `propdef.py`, `flashcall.py`, `fowdump.py`, `scenesnap.py`, `physdump.py`, ... | Live inspection tools: read client memory, look up property definitions, call into the Flash HUD, dump fog-of-war and scene state. |
| `tools/` | Data-pack reader (`rplib.py`, `rp_get.py`, `recdump.py`), string and entity tables extracted from the packs, the AS2 disassembly of the UI, and `analysis/` with the static analysis scripts (`icdis.py`, `xref.py`, `callers.py`, `vt.py`, ...). |
| `keys/` | Turbine's original public key, and your generated `server_private.pem` (not committed). |
| `HANDOFF.md` | Engineering log and open questions. |

The static analysis scripts expect a linear disassembly of the client in
`tools/analysis/full.asm`; it is 160 MB and not in the repository. Generate it with
`python tools/analysis/fulldis.py` (needs `pefile` and `capstone`).

## How the client is studied

The client is traced with `tracer.py`, which plants software breakpoints and logs register
and memory values without ever stopping the game, so a test is: edit the server, relaunch,
play, read the log. Property kinds, record contents and UI state are read live with the
`peek`/`propdef`/`flashcall` tools; static questions go through the disassembly and the AS2
dump of the Scaleform UI. Original gameplay is compared against
[a 2015 recording of Tutorial 1](https://www.youtube.com/watch?v=PL78fWMWceo).

## Contributing

Pick an item from "What is being worked on" or any open question in `HANDOFF.md`. Keep the
rules that have kept this stable: run `python check.py` before launching, never restart
`tracer.py` while the game is running (it crashes the client), and note the client addresses
you relied on in comments so the next person can verify them.

## Legal

Infinite Crisis is a trademark of Warner Bros. Entertainment / DC Comics; the game was
developed by Turbine. This project is an unofficial preservation effort. It ships no game
assets or executables; you must own the client. The patched executable is produced on your
machine from your own copy.
