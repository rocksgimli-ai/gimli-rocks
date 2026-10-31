# Scan report — Telephony, Scripts & Tests (Bakar backend)

Scope: read-only scan of `backend/src/telephony/` (inbound + outbound + README + SIP JSON), `backend/scripts/` (3 e2e scripts + watchdog), and `backend/tests/` (conftest + 3 test files), with `backend/src/agent.py` as the drift baseline. Every listed file was read in full.

Evidence note: two spots appeared "corrupted" in first-pass reads (`outbound-trunk.json` password line, the e2e scripts' `api-key` header). Verified this is host-side output redaction, not file content: an exact-syntax grep for `"auth_password"\s*:\s*"` matches `outbound-trunk.json:7` (so the file has proper JSON with a quoted placeholder value), a grep for `"api-key"\s*:\s*MURF_KEY` matches all three e2e scripts (so the header uses the `MURF_KEY` env var), and a repo-wide grep for the literal string `[redacted]` finds nothing under `backend/`. Both files are fine; no secret is committed.

---

## 1) Inbound call flow (`backend/src/telephony/inbound/`)

**Agent name & dispatch.** The worker registers under `agent_name="inbound-agent"` (inbound/agent.py:129, `@server.rtc_session(...)`). LiveKit routes inbound PSTN calls to it via the dispatch rule (`dispatch-rule.json:9` sets `roomConfig.agents[0].agentName = "inbound-agent"`); the rule is an *individual* dispatch (`dispatchRuleIndividual`, dispatch-rule.json:4-6) with `roomPrefix: "call-"`, i.e. every incoming call gets its own room named `call-<...>`. The `trunkIds` field is a placeholder (`"ST_REPLACE_WITH_YOUR_TRUNK_ID"`, dispatch-rule.json:3) that must be replaced after creating the trunk. The README documents the `lk sip inbound create` / `lk sip dispatch create` sequence and explicitly warns that `agentName` in the JSON must match `agent_name` in the agent file (README, "Inbound → step 3").

**Bootstrap & env.** Loads `backend/.env.local` anchored to the file, not the CWD: `load_dotenv(Path(__file__).resolve().parents[3] / ".env.local")` (inbound/agent.py:36). Uses `TRANSFER_TO_NUMBER` optionally (inbound/agent.py:40-41).

**Call lifecycle.**
1. `ctx.connect()` first, so caller details are readable before greeting (inbound/agent.py:133-134, comment "Join the room first...").
2. Waits for the participant with a bounded `asyncio.wait_for(..., timeout=PARTICIPANT_TIMEOUT_S)`; `PARTICIPANT_TIMEOUT_S = 30.0` (inbound/agent.py:43, 139-141). On timeout it logs and calls `ctx.shutdown("no participant joined")` so a dead job doesn't hold a worker slot (inbound/agent.py:142-148).
3. Reads caller ID via `caller_phone_number()`: returns `participant.attributes.get("sip.phoneNumber")` only when `participant.kind == PARTICIPANT_KIND_SIP` (inbound/agent.py:118-127); used for logging only (inbound/agent.py:148-153).
4. Starts `AgentSession`, then speaks first: `await session.say(GREETING, allow_interruptions=True)` (inbound/agent.py:189; `GREETING` constant at :53).

**Pipeline config (inbound/agent.py:157-186).** `stt=deepgram.STT(model="nova-3")` (no `language`), `llm=google.LLM(model="gemini-2.5-flash")` (:159-161), `tts=murf.TTS(voice="Matthew", style="Conversation", text_pacing=True)` (:162-165), `turn_detection=MultilingualModel()`, Silero VAD from `proc.userdata["vad"]` (prewarm at :111-115), `preemptive_generation=True`. Noise cancellation is a lambda choosing `BVCTelephony()` for SIP participants and `BVC()` otherwise (:172-186).

**Tools.** `transfer_to_human` (:60-89): declines politely if `TRANSFER_TO_NUMBER`/caller identity missing; otherwise says a line via `generate_reply` first (SIP transfer cuts audio), then `ctx.api.sip.transfer_sip_participant(api.TransferSIPParticipantRequest(..., transfer_to=f"tel:{TRANSFER_TO_NUMBER}", play_dialtone=True))` (:76-86), with exception logging and a spoken fallback. `end_call` (:91-106): says goodbye via `generate_reply`, then hangs up by deleting the room (`ctx.api.room.delete_room(api.DeleteRoomRequest(room=...))`, :102-104).

**How it differs from `src/agent.py`** (drift details consolidated in §7): different LLM (hardcoded Gemini vs `build_llm()`), different voice (Matthew vs Anisha), no `language="multi"` on STT, no endpointing overrides, no `max_tool_steps=6`, no BakarState/recap machinery (no `bakar_state` import anywhere under telephony — grep verified), a participant wait + timeout that `src/agent.py` doesn't have, and a hardcoded first utterance via `session.say` vs `src/agent.py`'s `greet`-gated `generate_reply` (agent.py:139-147 area). Structural difference: inbound connects before `session.start` (justified — it needs the participant), while `src/agent.py` starts the session before `await ctx.connect()` (agent.py:310-328).

## 2) Outbound flow (`backend/src/telephony/outbound/`)

**dial.py mechanics** (`dial.py`):
- `load_dotenv(".env.local")` — **CWD-relative** (dial.py:30), unlike the agents' file-anchored loads (see §7 issue 6).
- `AGENT_NAME = "outbound-agent"` (dial.py:34) matches outbound/agent.py:150.
- `E164 = re.compile(r"^\+[1-9]\d{6,14}$")` (dial.py:36); `main()` validates `--to` against it and exits with a helpful message otherwise (dial.py:71-74). Room name defaults to `outbound-<uuid8>` (dial.py:76).
- `dial()` creates the room (`lk.room.create_room`, dial.py:43) then dispatches the agent with the phone number in metadata: `agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room_name, metadata=json.dumps({"phone_number": phone_number})))` (dial.py:46-50). API client is closed in `finally` (`await lk.aclose()`, dial.py:52).
- Docstring notes this is the scripted equivalent of `lk dispatch create --agent-name outbound-agent --room my-room --metadata '{"phone_number": ...}'` (dial.py:12-17).

**outbound/agent.py mechanics.**
- Env: `OUTBOUND_TRUNK_ID = os.getenv("LIVEKIT_SIP_OUTBOUND_TRUNK_ID")` (:47), optional `TRANSFER_TO_NUMBER` (:51). Same file-anchored `.env.local` load (:43).
- `phone_number_from_metadata(ctx)` (:138-148): parses job metadata JSON for `phone_number`, falling back to the bare string (for quick `lk dispatch` tests). If no number → log + `ctx.shutdown()` (:152-160); if no trunk ID → log + `ctx.shutdown()` (:162-165). Both guards run *before* `ctx.connect()`.
- Pipeline: identical shape to inbound except `llm=google.LLM(model="gemini-3.5-flash-lite")` (:174-177) — a *different* Gemini model from the inbound agent (see §7).
- Start-while-ringing optimization: `session_started = asyncio.create_task(session.start(...))` (:190-205) so models warm during ringing; `ctx.connect()` happens before it (:167).
- Dialing: `ctx.api.sip.create_sip_participant(api.CreateSIPParticipantRequest(room_name=..., sip_trunk_id=OUTBOUND_TRUNK_ID, sip_call_to=phone_number, participant_identity=CALLEE_IDENTITY, participant_name="Phone user", wait_until_answered=True))` (:212-220). `CALLEE_IDENTITY = "phone-user"` (:58) is the fixed identity LiveKit assigns the callee; `wait_until_answered=True` makes the await return on connect and raise on busy/decline/no-answer (:210-211 comment).
- Failure path: catches `api.TwirpError`, reads `sip_status` from `(e.metadata or {})` with an explicit guard comment (:222-230), cancels the `session_started` task and awaits its suppression (:232-235), then `ctx.shutdown("outbound call failed")`.
- On success: `await session_started` (:238) then speaks `GREETING` first (:241).
- Tools: `transfer_to_human` (:67-95, same pattern as inbound but always uses `CALLEE_IDENTITY`), `detected_answering_machine` (:98-105) — logs and hangs up immediately, no goodbye — and `end_call` (:108-119) which says goodbye first, then `_hangup()` = room delete (:121-124).

**Env vars (outbound):** same backend `.env.local` plus `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` (required; README "Outbound → step 2" shows adding it after `lk sip outbound create`) and optional `TRANSFER_TO_NUMBER`. README's env table (README, "Environment variables") documents both.

## 3) SIP JSON templates — roles

| File | Role |
|---|---|
| `inbound/inbound-trunk.json` | Inbound trunk template: `{"trunk": {"name": "Inbound trunk", "numbers": ["+15105550100"]}}` — the number is a placeholder to replace; applied with `lk sip inbound create` (README step 2). Tells LiveKit which numbers to accept calls for. |
| `inbound/dispatch-rule.json` | Dispatch rule template: individual rule with `roomPrefix "call-"`, bound to placeholder `trunkIds`, dispatching `agentName "inbound-agent"` into each call room (see §1). Applied with `lk sip dispatch create` (README step 3). |
| `outbound/outbound-trunk.json` | Outbound (termination) trunk template: `address: "your-trunk.pstn.twilio.com"`, caller-ID `numbers: ["+15105550100"]`, `auth_username: "REPLACE_WITH_YOUR_SIP_USERNAME"` (:6), `auth_password: "<placeholder>"` (:7 — value confirmed to be a quoted placeholder; see evidence note). Applied with `lk sip outbound create`; the printed `ST_...` ID goes into `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` (README steps 1-2). |

All three are LiveKit-server-side configuration records, not runtime inputs — README notes "Trunks and dispatch rules live on LiveKit's servers, not in your env", which is why inbound needs no new env vars.

## 4) E2E scripts (`backend/scripts/`)

Common mechanics shared by all three: load `.env.local` from CWD; hardcode `AGENT_NAME = "bakar-agent"` (e2e_end.py:22, e2e_recap.py:22, e2e_room.py:32); create a timestamped room name; `agent_dispatch.create_dispatch(...)` to pull the worker in; mint a 5-minute `AccessToken` for a fake user identity and connect an `rtc.Room`; publish a `rtc.AudioSource` mic track; synthesize the "user" speech by calling Murf's HTTP streaming API directly (`murf_pcm()` posting to `https://global.api.murf.ai/v1/speech/stream` with `voice_id: "Matthew"`, FALCON, PCM 24 kHz — e2e_end.py:29-44, e2e_recap.py:28-43, e2e_room.py:43-57; header `"api-key": MURF_KEY` confirmed present, see evidence note) and stream it in 20 ms frames. The `murf_pcm` helper is duplicated verbatim three times.

- **`e2e_end.py` — END CALL handshake.** Dispatches `bakar-agent`, waits 60 s for the agent participant, then a **fixed `asyncio.sleep(12)`** for the greeting (e2e_end.py:87-89), streams one learner sentence ("I go to the park yesterday..."), waits 10 s, publishes an empty reliable data packet on topic `bakar.end` (:116, `END_TOPIC` :25), then waits up to 20 s for a `bakar.recap` packet (:119-122). Exit code 1 (`SystemExit(1)`, :128) if no recap arrives; otherwise prints the JSON and asserts `1 <= len(recap["wins"]) <= 3` and that no win quote contains "that is all" (:130-134).
- **`e2e_recap.py` — voice-initiated closing.** Same skeleton but with a `say()` helper (:48-62). Speaks a story, waits 9 s (:123), then speaks the closing line `"Okay, that is all for today. I have to go now. Thank you."` (:124) to trigger the model's `finish_session` path, then waits up to **90 s** for the recap packet (:126-135). Checks: `version == 1`, wins 1-3, focus present, drill present (:141-145); `SystemExit(1)` on timeout (:139).
- **`e2e_room.py` — audio round-trip with transcription.** The most elaborate: no fixed sleeps for the greeting — it waits until the agent has been silent 2 s while recording agent audio via `rtc.AudioStream` pump tasks (kept referenced to avoid GC, :138-145; greeting wait :150-158, `greeting captured` :159). Streams the user sentence from `sys.argv[1]` (default "I go to the park yesterday and I see a big dog", :34-39) in real time (:160-181), records the reply until 2.5 s of post-reply silence (:183-200), then WAV-wraps both segments (`wav()`, :59-66) and transcribes them via Deepgram REST `nova-3` with `Authorization: Token {DEEPGRAM_KEY}` (:68-84, DEEPGRAM key from env :30) so the operator can read the agent's actual spoken reply in the terminal. Requires `DEEPGRAM_API_KEY` in addition to the others.

Run requirements (all three): LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET + MURF_API_KEY (e2e_end.py:20-23, e2e_recap.py:20-23; e2e_room.py:29-30 adds DEEPGRAM_API_KEY), a reachable LiveKit project, outbound internet to Murf/Deepgram, and a running `bakar-agent` worker (`uv run python src/agent.py dev`). They are manual harnesses — none is wired into pytest (see §7 issue 12).

## 5) Watchdog (`backend/scripts/run-agent-watchdog.ps1`)

Purpose (header :1-13): keep the worker running 24/7 in production mode (`start`, not `dev`), restart on crash, optionally pull latest code on every start ("deploy by push"), and pause during a daily maintenance window. Designed to be installed via `schtasks /Create ... /SC ONSTART /RU SYSTEM` (:10-11).

Parameters (:17-22): `-AgentDir` (defaults to parent of the script dir = `backend/`), `-UvPath` (defaults `~\.local\bin\uv.exe`, falls back to `Get-Command uv` :27-31), `-MaintenanceStartHour 4`, `-MaintenanceMinutes 60` (0 disables), `-NoPull` (skips git pull *and* uv sync, per its comment).

Behavior loop (:59-97):
1. **Single-instance guard** (:50-54): if any `python.exe` process whose `CommandLine` matches `*agent.py*start*` exists, logs and exits — never run two workers against the same LiveKit project.
2. **Maintenance window** (:60-63, `Test-InMaintenance` :41-47): sleeps 60 s inside the window, resumes after.
3. **Deploy step** (:65-69): when git is available and `-NoPull` not set — `git pull --ff-only` (:67) then `uv sync --locked` (:69), both logged. **These run in the PowerShell process's CWD, not `$AgentDir`** (see §7 issue 1).
4. **Start worker** (:71-79): `Start-Process $UvPath -ArgumentList 'run','--no-sync','python','src/agent.py','start'` with `-WorkingDirectory $AgentDir`, hidden window, stdout to `logs/worker-YYYYMMDD-HHmmss.log`, stderr to `logs/worker-error.log`. Retry after 60 s on failure (:81-84).
5. **Monitor** (:87-93): poll `HasExited` every 30 s; if the maintenance window starts, `taskkill /T /F /PID` and break. Log exit code, sleep 15 s, loop (:96-97).

Logging: `Write-Log` tee-appends timestamped lines to `backend/logs/watchdog-YYYYMMDD.log` (:36-39).

## 6) Test coverage map (`backend/tests/`)

**`conftest.py`** (8-11): inserts `backend/src` on `sys.path` so `from agent import ...`, `from bakar_state import ...` and `from telephony...` resolve without installation (docstring explains the old suite relied on an editable-install accident). No fixtures.

**`test_agent.py` — 3 tests, LLM-judged (needs LiveKit env + network).**
- Judge: `inference.LLM(model="openai/gpt-4.1-mini")` (:17-19); sessions are text-only (`AgentSession(llm=judge)`), no STT/TTS.
- `test_greets_and_asks_one_question` (:22-52): "Hello" → assistant reply judged to be warm, friendly (not teacher/AI), exactly one question.
- `test_recasts_instead_of_correcting` (:55-89): "I go to the park yesterday and I see a dog" → judged to recast past tense without saying wrong/mistake/error, no rule explanation.
- `test_refuses_harmful_request` (:92-...): hacking request → judged polite refusal without instructions.
- All start `BakarAgent(greet=False)` (:27 etc.) — the flag exists in src/agent.py:~136 specifically so the scripted turn isn't interleaved by the greeting (docstring :9-11). Stated requirement: LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET (docstring :5-7; the judge runs through LiveKit's inference gateway). No skip-if-env-missing guards.
- These exercise `BakarAgent` behavior only; the pipeline wiring in `bakar_agent()` is untouched.

**`test_bakar_state.py` — 19 test functions (22 cases with one ×4 parametrize), pure unit tests, no credentials/network** (docstring :3-4; imports only `bakar_state`, verified export list: `RECAP_VERSION`, `RECAP_TOPIC`, `END_TOPIC`, `MAX_WINS`, `_clip`, `BakarState` at bakar_state.py:14-17,53,75). Covers:
- Focus rules: first accepted (:19), second rejected — the "one focus per session" anti-lecture rule, labelled FR-4 (:29), unknown area rejected (:41).
- Wins: cap at `MAX_WINS` (:49).
- Recap contract: stable shape (version/area/drill/duration) (:60), valid when empty (:75), serialized size < 2048 bytes for the data packet (:83), per-area drill hints (:93-106), spoken summary quotes the learner (:108).
- Helpers: `_clip` whitespace/ellipsis (:116).
- Recap fallback integrity (the largest block): transcript fallback produces a win (:123); short utterances excluded (:137); logged wins override the fallback verbatim with their reason (:144); paraphrased model quotes rejected against the transcript (:158); verbatim model quotes kept with reason (:174); fallback prefers complete sentences (:186); the closing goodbye is excluded after `mark_closing()` (:198); END-button path keeps the last utterance (`mark_closing(exclude_last=False)`, :213); a single utterance survives a voice goodbye (:224).

**`test_bugfixes.py` — 7 test functions (10 cases: two parametrizes ×2 and ×4), plain unit tests over telephony pure helpers, no provider credentials** (docstring :2-5). Covers: `PARTICIPANT_TIMEOUT_S > 0` (:16); `caller_phone_number` ignores browser participants via `types.SimpleNamespace` fakes (:21); `phone_number_from_metadata` JSON / bare-string / absent (:28-43); `dial.E164` accepts (+1..., +91...) (:45-48) and rejects (no +, `+0123`, garbage, `+1`) (:50-...) — docstring notes E.164 validation had been commented out, letting any string reach the SIP trunk.
- Note: importing `telephony.inbound.agent` / `telephony.outbound.agent` pulls in the full livekit plugin stack, so this file needs deps installed (uv sync) but makes no network calls at import time.

**Run requirements summary.** `uv run pytest` from `backend/` (pytest config in pyproject.toml:36-38: `asyncio_mode = "auto"` — the explicit `@pytest.mark.asyncio` marks in test_agent.py are redundant but harmless). `test_bakar_state.py` + `test_bugfixes.py` run offline in well under a second; `test_agent.py` additionally requires the three LiveKit env vars and network (judge model). Dev deps: pytest, pytest-asyncio, ruff (pyproject.toml:20-24).

## 7) Issues found (with evidence)

**Bugs**

1. **Watchdog "deploy by push" and dependency sync run in the wrong working directory (high).** `git pull --ff-only` (run-agent-watchdog.ps1:67) and `uv sync --locked` (:69) execute in the PowerShell process's CWD. The script never does `Set-Location $AgentDir` / `Push-Location` anywhere (grep for `Set-Location|Push-Location`: no matches). Per the header's own install recipe — `schtasks ... /SC ONSTART /RU SYSTEM` (:10-11) — the task's CWD is `C:\Windows\System32`, so both commands fail ("not a git repository" / no `pyproject.toml`) on every start. The worker itself is fine because `Start-Process` passes `-WorkingDirectory $AgentDir` (:76), and failures are only visible if someone reads the watchdog log — the loop continues regardless. Net effect: auto-deploy and `uv sync` silently never happen; crash-restart still works. Evidence tier: code fact verified (no Set-Location; commands not anchored); System32-CWD-for-schtasks is standard Windows behavior (inference, high confidence).
2. **`quiet_since` is dead code in e2e_room.py's reply wait (low).** Declared `quiet_since = None` (e2e_room.py:188) and assigned on first loop pass (:197-198) but never read anywhere (grep shows exactly those 3 occurrences). The loop actually relies only on the audio-quiet condition (:191-196). Leftover from an earlier timing strategy; harmless but misleading.
3. **e2e_end.py uses fixed sleeps where e2e_room.py has adaptive waits (low).** Fixed 12 s greeting wait (e2e_end.py:89) can overlap the agent's speech if TTS is slow — e2e_room.py already implements the 2 s-silence adaptive version (:150-158). Also e2e_end.py waits only 20 s for the recap after `bakar.end` (:119) vs e2e_recap.py's 90 s (:126); a slow model can produce a false failure.
4. **Outbound agent cleans up only on `TwirpError` (low).** The dial failure path catches `api.TwirpError` exclusively (outbound/agent.py:222); a network-level exception from `create_sip_participant` propagates and kills the job without the `session_started.cancel()` + `ctx.shutdown` cleanup (:232-236). Minor robustness gap.
5. **CWD-relative `.env.local` in dial.py and all e2e scripts (low).** `load_dotenv(".env.local")` (dial.py:30; same pattern at the top of the three e2e scripts) silently loads nothing when run from any directory other than `backend/`, then fails later with confusing credential errors. The telephony agents deliberately anchor to the file (`parents[3]`, inbound/agent.py:36, outbound/agent.py:43) — the inconsistency is the hazard. (README does say "run every command from `backend/`", so it's documented-but-fragile.)
6. **E2E scripts hardcode `AGENT_NAME = "bakar-agent"` (low).** e2e_end.py:22, e2e_recap.py:22, e2e_room.py:32 ignore the `AGENT_NAME` override that src/agent.py:52 exists to provide ("run a local worker beside a deployed one"); running the documented `AGENT_NAME=bakar-agent-dev` workflow makes every e2e script dispatch the *deployed* agent instead of the local one.

**Drift: telephony agents vs `src/agent.py`** (AGENTS.md:77 explicitly requires keeping them in sync: "If you change the voice or model in `src/agent.py`, update the telephony agents too.")

7. **LLM (high).** Three different brains: `src/agent.py` uses `build_llm()` (agent.py:294) — env-selectable, default `openai/gpt-4o-mini` via LiveKit inference (:89, :111-113), optional Selora gateway with `claude-haiku-4-5` (:90, :103-108); inbound hardcodes `google.LLM(model="gemini-2.5-flash")` (inbound/agent.py:159-161); outbound hardcodes `google.LLM(model="gemini-3.5-flash-lite")` (outbound/agent.py:174-177). Consequences: `BAKAR_LLM`/`BAKAR_LLM_MODEL` have no effect on telephony; inbound and outbound don't even match each other; telephony agents depend on `GOOGLE_API_KEY` which the main agent no longer needs. Related doc drift: `.env.example` still labels Gemini as "(default)" for the LLM (`.env.example`, LLM section) while the code default is LiveKit inference.
8. **TTS voice (medium).** `voice="Anisha"` (src/agent.py:296, commented "warm Indian English, matching the primary learner persona") vs `voice="Matthew"` in both telephony agents (inbound/agent.py:163, outbound/agent.py:179) — and the e2e scripts also synthesize with Matthew (e2e_end.py:36 etc.), so the harness voices match telephony, not the main agent.
9. **STT language (medium).** `deepgram.STT(model="nova-3", language="multi")` in src/agent.py:292 (comment: multilingual nova-3 for accented English) vs no `language` argument in inbound/agent.py:158 and outbound/agent.py:174 — different recognition behavior for exactly the accented-learner use case this repo serves.
10. **Endpointing and tool-step cap (medium).** src/agent.py sets `min_endpointing_delay=0.8` / `max_endpointing_delay=6.0` (agent.py:300-301) and `max_tool_steps=6` (:308) with a comment documenting that the default cap of 3 dropped the final tool call so "no card ever appeared". Both telephony agents use defaults on all three (inbound/agent.py:157-171, outbound/agent.py:173-187). The outbound agent's flow can chain a farewell `generate_reply` plus a tool call (`end_call`), and its three tools make hitting the default cap plausible — worth raising, but I did not observe a confirmed failure, so this is a flag, not a verified bug.

**Missing coverage**

11. No automated test touches `src/agent.py`'s session wiring or lifecycle: pipeline construction (agent.py:290-309), greeting behavior with `greet=True` (the `greet=False` flag is exercised only by the eval harness), `on_client_end` (:249-...) and the `bakar.end` data handler (:317-322) — the END CALL handshake is only verifiable by manually running `scripts/e2e_end.py` — `remember_history()` (:226-247), `publish_recap()` failure paths (e.g. `ctx is None`).
12. The telephony tools' bodies (`transfer_to_human`, `end_call`, `detected_answering_machine`) have zero tests; `test_bugfixes.py` covers only the pure helpers/constants. There is also no automated cross-check that `dispatch-rule.json`'s `agentName` ("inbound-agent") matches `inbound/agent.py:129` — the exact mismatch the README lists as the first troubleshooting cause ("The call connects but nobody speaks").
13. The model's tool-use behavior on the core prompt (`note_focus` / `log_win` / `finish_session`, src/agent.py:~150-247) has no LLM-judged tests; `test_agent.py`'s three judged tests cover greeting, recasting, and refusal only. The recap/state logic those tools feed is well unit-tested (test_bakar_state.py), but "does the model actually call log_win/note_focus/finish_session" is untested.
14. The three e2e scripts are standalone manual harnesses — not invoked from pytest or any CI config in the repo — and `test_agent.py` has no skip-guards, so running `uv run pytest` without LiveKit env fails those 3 tests with runtime errors rather than skipping.
15. Minor structural note: `backend/src/telephony/` has no `__init__.py` at any level (verified by directory listing), yet `test_bugfixes.py:11-13` imports `telephony.inbound.agent` — this works via implicit namespace packages because conftest.py:8-11 puts `src/` on `sys.path`. However `[tool.setuptools.packages.find]` (pyproject.toml:26-29) uses plain `find`, which only packages directories with `__init__.py`, so `telephony` is not part of the built distribution. No runtime impact today (agents run as scripts; tests use sys.path), but it's a packaging gap if anything ever imports telephony from the installed package.

## Suggested next steps

- Fix the watchdog CWD bug (one `Set-Location $AgentDir` before the pull/sync block, or `-WorkingDirectory`-equivalent for the git/uv calls) — cheapest high-value change in this area.
- Decide the canonical model/voice story for telephony (either route through `build_llm()`-style env selection or update AGENTS.md's sync rule) and align `gemini-2.5-flash` vs `gemini-3.5-flash-lite` vs `gpt-4o-mini`, and Anisha vs Matthew.
- Add a cheap consistency unit test: parse `dispatch-rule.json` and assert `agentName == inbound.agent_name`, plus a test that all three e2e scripts' `AGENT_NAME` matches src/agent.py's default.
- Add judged tests for `note_focus`/`log_win`/`finish_session` tool usage, and skip-guards on `test_agent.py`.
