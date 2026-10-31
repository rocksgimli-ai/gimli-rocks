# Bakar — Full Code Scan Report

**Date:** 2026-10-31 · **Scope:** the entire repository at `S:\Bakar` (~100 tracked files) · **Method:** read-only. Four parallel area scans (backend core; telephony + scripts + tests; frontend; docs + CI + root) each read every assigned file in full and wrote a detail report under `scan/`. The core entrypoint (`backend/src/agent.py`, `backend/src/bakar_state.py`) and `WORKLOG.md` were additionally read directly. Nothing was executed and no project file was modified.

**Area detail reports:**
- [scan/backend-core.md](backend-core.md) — entrypoint, state module, packaging, deploy configs
- [scan/telephony-tests.md](telephony-tests.md) — phone agents, e2e scripts, watchdog, test suite
- [scan/frontend.md](frontend.md) — UI, recap protocol, token endpoint, build surface
- [scan/docs-root.md](docs-root.md) — PRD/PLAN/TECH_DESIGN/DEPLOY/VOICE_QA, CI, startup scripts

---

## 1. What Bakar is

Bakar is a **spoken-English practice companion** — a LiveKit voice agent for people who already understand English but freeze when speaking it. Thesis: keep the learner talking (recast, never correct; ≤2 short sentences per turn; one focus per session), and end every session with a **recap card** ("You said" / "Practise next" / "Say it once more") delivered over the LiveKit data channel. Nothing is persisted; no scores, ever.

Status per `WORKLOG.md`: the core loop (greeting → recast → client-initiated END → recap) has been **verified end-to-end with real providers**, and the agent has been **live on LiveKit Cloud since 2026-10-31** (deployment `CA_[redacted]`, project `[previous-project]`, India South). Still outstanding: human voice QA (`docs/VOICE_QA.md` has never been executed), the public frontend deploy (Netlify), and the token rate limiter.

## 2. Repo map — where the real code is

| Area | Files | Nature |
|---|---|---|
| `backend/src/agent.py` (343 ln) | entrypoint | **All Bakar**: persona prompt, pipeline wiring, 3 tools, END handshake |
| `backend/src/bakar_state.py` (~217 ln) | state | **All Bakar**: pure-Python session memory + recap builder, no LiveKit imports |
| `backend/src/telephony/` | 5 files | Optional phone agents (inbound/outbound), self-contained, **lagging the main agent** |
| `backend/tests/` | 4 files | 19 state unit tests, 10 telephony-helper tests, 3 LLM-judged evals |
| `backend/scripts/` | 4 files | 3 manual e2e harnesses + a Windows watchdog |
| `frontend/lib/recap.ts`, `hooks/useRecap.ts`, `components/bakar/session-recap.tsx`, `lib/ids.ts` | 4 files | **All Bakar**: recap wire format, defensive parser, card UI, UUID ids |
| `frontend/app/api/token/route.ts` | 1 file | Hardened token minting (Bakar-modified) |
| `frontend/components/agents-ui/`, `ai-elements/`, `ui/`, `hooks/agents-ui/` | ~30 files | **Vendored upstream boilerplate** (LiveKit Agents UI + AI Elements registries) |
| `docs/` | 5 files | PRD, PLAN, TECH_DESIGN, DEPLOY, VOICE_QA — mostly current, some stale |
| `WORKLOG.md` | 1 file | Append-only history, 17 entries, 2026-10-27 → 10-31, with verification evidence |

## 3. Architecture and end-to-end flow

Two app services + LiveKit Cloud; no database, no shared state:

```
Browser (Next.js)                      Python worker (LiveKit Agents)
────────────────                       ──────────────────────────────
POST /api/token ────────── server mints 15-min JWT (room-scoped,
                            agent dispatch baked in: AGENT_NAME)
join room bakar_room_<uuid4> ──────► dispatch job → AgentSession
  ◄── greeting (on_enter generate_reply)
  user audio → Deepgram nova-3 (multi) → LLM → Murf "Anisha" TTS
  tools: log_win / note_focus (write to BakarState, in-memory)
END button ── data packet topic `bakar.end` ──► on_client_end()
  ◄── data packet topic `bakar.recap` (JSON, reliable) ──
parseRecap() (defensive) → SessionRecap card → session.end()
```

Closing is **client-initiated by design** (`on_client_end`, agent.py:249-273) because the model skipped `finish_session` in ~half of real runs (WORKLOG 19:00). `finish_session` remains for voice-ended sessions. Two known closing races: see Findings H3.

### Pipeline (agent.py:289-309)

| Stage | Choice | Notes |
|---|---|---|
| STT | Deepgram `nova-3`, `language="multi"` | accented-English friendly |
| LLM | `build_llm()`: default LiveKit inference `openai/gpt-4o-mini`; `BAKAR_LLM=selora` → OpenAI-compatible gateway (`claude-haiku-4-5`) | **not** Gemini, despite docs (see H4) |
| TTS | Murf `voice="Anisha"`, `style="Conversation"`, `text_pacing=True` | warm Indian English |
| Turn end | MultilingualModel turn detector + Silero VAD (prewarmed) | endpointing 0.8 s / 6.0 s for hesitant speakers |
| Latency | `preemptive_generation=True` | |
| Tools | `max_tool_steps=6` | default 3 dropped the recap-publish call in the closing turn |
| Audio in | BVC noise cancellation; `BVCTelephony` for SIP participants | |

### The three tools (all in `BakarAgent`)

1. **`note_focus(area, item, example)`** — one focus per session; second call and unknown areas rejected by **code** (`BakarState.note_focus`), not by the prompt.
2. **`log_win(quote, why)`** — cap 3; quotes must be verbatim; `appears_verbatim()` discards paraphrased quotes at recap time, falling back to the learner's own ≥3-word sentences (punctuated/longest first, goodbye excluded via mode-aware `closing_index`).
3. **`finish_session()`** — idempotent-ish (see H3); publishes the recap JSON (`version: 1`, wins/focus/drill/duration_s, payload < 2 KB, all strings clipped 240/120/200) and returns `spoken_summary()` closing instructions.

`BakarState` is a per-job in-memory dataclass with no locks (single event loop) and no persistence — deliberately, per the PRD.

## 4. Telephony, e2e scripts, watchdog

- **Inbound** (`agent_name="inbound-agent"`, dispatch rule `call-<...>` rooms): waits up to 30 s for the SIP participant, then greets; tools `transfer_to_human` and `end_call`.
- **Outbound** (`agent_name="outbound-agent"`): `dial.py` validates E.164, creates a room, dispatches with the phone number in metadata; the agent starts the session while ringing and dials via SIP trunk (`wait_until_answered=True`), with TwirpError-based failure cleanup.
- **Drift vs the main agent is significant** (violates AGENTS.md's own sync rule): inbound hardcodes `gemini-2.5-flash`, outbound `gemini-3.5-flash-lite`, while the main agent defaults to gpt-4o-mini via `build_llm()`; voice is Matthew not Anisha; STT lacks `language="multi"`; no endpointing/`max_tool_steps` overrides; no recap machinery at all. Findings M2.
- **e2e scripts** (`e2e_end.py`, `e2e_recap.py`, `e2e_room.py`): manual harnesses that synthesize learner speech with Murf HTTP, publish it as paced mic audio, and (in `e2e_room.py`) transcribe the agent's reply via Deepgram. Hardcode `AGENT_NAME="bakar-agent"` and load `.env.local` from CWD. Not wired into pytest/CI.
- **Watchdog** (`run-agent-watchdog.ps1`): crash-restart loop with single-instance guard and maintenance window. Its "deploy by push" is **silently broken** — see H1.

## 5. Tests and CI

| Suite | Kind | Requires |
|---|---|---|
| `test_bakar_state.py` — 19 functions / 22 cases | pure unit (focus cap, win cap, verbatim filter, payload < 2 KB, fallback integrity) | nothing |
| `test_bugfixes.py` — 7 functions / 10 cases | unit over telephony pure helpers (E.164, metadata parsing) | deps only |
| `test_agent.py` — 3 tests | **LLM-as-judge** evals (one-question greeting; recast without meta-commentary; refusal) via `inference.LLM("openai/gpt-4.1-mini")` | LIVEKIT_* env + network; **no skip-guards** |
| `verify-recap.mjs` (9) / `verify-fixes.mjs` (11) | Node contract tests over the real `.ts` modules (need Node ≥ 22.6 type-stripping) | manual only |
| e2e scripts | live-room smoke tests | full credentials + running worker; manual only |

CI (root `.github/workflows/`): backend ruff check+format, backend pytest (injects LIVEKIT secrets), frontend lint+format+build — all on push/PR to `main`. Gaps: no `tsc` step, verify scripts not run in CI, evals fail rather than skip without secrets. Dead workflow copies remain at `backend/.github/workflows/*` and `frontend/.github/workflows/*` (GitHub ignores them, per the note in `backend-lint.yml`).

## 6. Frontend

One page, two views (Welcome ↔ `AgentSessionView_01` cross-fade): visualizer tile, Streamdown chat transcript, mic/camera/screen controls, END CALL, and the Bakar recap card. Custom-Bakar surface is small and clean (recap trio, ids, token route hardening, END handler with 1200 ms grace, welcome copy); everything else is vendored registry boilerplate. Token endpoint: fresh UUIDv4 room/identity, 15-min TTL, least-privilege grants, fail-loud on missing env, secrets server-side — but **unauthenticated and unthrottled** (acknowledged in DEPLOY.md §9; rate limiter is a stated pending item).

## 7. Docs vs reality (conflicts resolved during this scan)

The docs-scan flagged claims it could not verify; the code scans resolved them:

| Doc claim | Reality in code | Verdict |
|---|---|---|
| "Gemini 3.5 Flash-Lite" / "Google Gemini — LLM" (README, TECH_DESIGN, AGENTS.md, `.env.example` "For Gemini (default)") | `build_llm()` default = LiveKit inference `openai/gpt-4o-mini`; `GOOGLE_API_KEY` only used by telephony | **Docs stale** (H4) |
| Focus cap "enforced by the tool, not just the prompt" (PRD FR-4) | Confirmed: `BakarState.note_focus` rejects a second focus | ✅ true |
| `self._state` in userdata per TECH_DESIGN §2.3 | Actually `self.state = BakarState()` on the agent (not userdata) | minor doc drift |
| Recap "exactly 2–3 wins, exactly 1 focus, 1 drill" (PRD) | Code allows empty wins / null focus and the UI has an empty state; observed live recap had 1 win, null focus | **PRD overpromises** (L3) |
| Agent names `inbound-agent`/`outbound-agent` | Confirmed in both telephony files | ✅ true |
| Endpointing 0.8/6.0, preemptive generation, `max_tool_steps=6` | Confirmed at agent.py:300-308 | ✅ true |
| `AGENT_NAME` optional (README/AGENTS.md) | Required at runtime by `route.ts:24` (500 without it) | **Docs stale** (M5) |
| Dockerfile "unchanged from base project" (DEPLOY §10) | CMD was fixed 2026-10-31 to absolute `/app/.venv/bin/python /app/src/agent.py start` | **Doc stale** (M6) |

## 8. Findings (prioritized; file:line evidence)

### High

- **H1 · Watchdog "deploy by push" is broken.** `git pull --ff-only` and `uv sync --locked` (`run-agent-watchdog.ps1:65-69`) run in the PowerShell process CWD; the script never `Set-Location`s to `$AgentDir`. Installed via its own `schtasks /SC ONSTART /RU SYSTEM` recipe, CWD is `C:\Windows\System32`, so both fail on every boot and the loop continues. Crash-restart still works; auto-deploy and dependency sync silently never happen. Fix: anchor the git/uv calls to `$AgentDir`.
- **H2 · Recap can be silently lost on the 1200 ms race.** END button publishes `bakar.end` then `session.end()` after a fixed 1200 ms (`agent-session-block.tsx:193-202`). A recap slower than that (LLM latency) is destroyed with the room; there is no ack/retry/extend. Related backend race: `recap_sent` is checked before an `await` and set after (`agent.py:205-209`, `249-267`), so END pressed during `finish_session`'s suspension (or two rapid END presses) can publish a **duplicate** card and double goodbyes. Fix: extend the grace window on recap arrival; set the flag before the await or use an `asyncio.Lock`.
- **H3 · Unauthenticated, unthrottled token minting.** `route.ts:18-66` gives anyone who can reach the deployment a valid agent-dispatching token; each session burns Murf/Deepgram/LLM budget. Known and documented (DEPLOY.md §9, WORKLOG 10-31 "remaining"); mitigations so far: least-privilege scoped grants, ephemeral UUID rooms, 15-min TTL. Keep the frontend private / enable Deployment Protection until the limiter exists.
- **H4 · The "brain" is misdocumented in three places.** README, TECH_DESIGN, and AGENTS.md say Gemini; the code default is LiveKit inference gpt-4o-mini (`agent.py:93-113`), and `backend/.env.example` contradicts itself (`GOOGLE_API_KEY` "For Gemini (default)" vs its own `BAKAR_LLM=livekit` block). `GOOGLE_API_KEY` is needed only by the telephony agents. Anyone provisioning from the docs wires an unused key and expects the wrong model.

### Medium

- **M1 · `AGENTS.md` describes the upstream starter, not Bakar.** `Assistant`/`my_agent()` (replaced by `BakarAgent`/`bakar_agent`), `my-agent`, "Google Gemini", tests "in `test_agent.py`" only, no mention of `bakar_state.py`, the recap protocol, `BAKAR_LLM`, or the e2e/watchdog scripts. It is the repo's onboarding document and is wrong throughout.
- **M2 · Telephony agents drift from `src/agent.py`** (three different LLMs, Matthew vs Anisha, no `language="multi"`, default endpointing/tool caps, no recap), violating AGENTS.md's explicit sync rule; inbound and outbound don't even match each other.
- **M3 · Fly config below the repo's own measured minimum.** `fly.toml:17-19` allocates 1 GB while `docker-compose.yml:7-10` records ~1.1 GB idle and says "size the VM at 2 GB minimum" → OOM-kill risk on Fly.
- **M4 · Packaging metadata doesn't match how the code runs.** `[tool.setuptools.packages.find]` (`pyproject.toml:25-29`) collects packages, not the top-level modules `agent.py`/`bakar_state.py`, and `telephony/` has no `__init__.py` — a built wheel would be incomplete. Masked today because everything runs as scripts with `src/` on `sys.path` (`conftest.py:8-11` does the same).
- **M5 · `AGENT_NAME` doc mismatch** — required by `route.ts:24`, still "optional" in frontend README (and `my-agent` in AGENTS.md); a README follower gets a hard 500.
- **M6 · Stale deployment docs** — DEPLOY.md §10 ("Dockerfile unchanged") and TECH_DESIGN:147 (`uv run --no-sync`) predate the 2026-10-31 absolute-CMD fix; DEPLOY's env matrix omits `GOOGLE_API_KEY`.
- **M7 · Test coverage gaps** — nothing tests the session wiring, the END handshake (`on_client_end`), `remember_history`/`publish_recap` failure paths, the telephony tool bodies, or whether the model actually calls the three tools; no automated check that `dispatch-rule.json`'s `agentName` matches `inbound/agent.py:129` (the exact mismatch the telephony README lists as troubleshooting cause #1); `test_agent.py` fails rather than skips without credentials; e2e scripts aren't in CI.
- **M8 · Dead/dead-ish config** — taskfile `set_agent_name_if_present` rewrites a literal that no longer exists (no-op); dead workflow copies under `backend/.github`, `frontend/.github`; legacy `.eslintrc.json` beside the flat `eslint.config.mjs`; `eslint.ignoreDuringBuilds: true` (`next.config.ts:3-8`) so builds never lint.
- **M9 · Robustness nits with real failure modes** — `end_tasks` list is never awaited/drained (`agent.py:315-322`); outbound agent cleans up only on `TwirpError` (`outbound/agent.py:222`); CWD-relative `load_dotenv` in `dial.py:30` and all three e2e scripts; e2e scripts hardcode `AGENT_NAME="bakar-agent"`, defeating the dev/prod dispatch separation; `e2e_end.py` uses fixed sleeps (12 s greeting / 20 s recap) where `e2e_room.py` already has adaptive silence-based waits.

### Low

- README drift on both sides (backend: `en-US-matthew` voice example, missing files in the tree, Railway-only deploy section; frontend: still Murf-branded customization examples and a deploy button cloning the upstream starter).
- ~9 declared-but-unimported frontend deps (`@rive-app/react-webgl2`, `@xyflow/react`, `shiki`, `jose`, …) — install-weight only, removal needs a build check.
- `agent-audio-visualizer-aura.tsx:11-18` carries a **Polyform Non-Resale 1.0.0** license header (vendored from Unicorn Studio) — legal awareness before any commercial resale.
- Possible duplicate recap quote via double transcript capture (STT event + history both append; dedupe is consecutive-only, `bakar_state.py:127-130`).
- `formatDuration` renders unbounded minutes (240:00 for 4 h); token 500s disclose which env var is missing; CI pins older action majors in the dead nested workflows; WORKLOG has one out-of-order timestamp (02:10 entry after 20:10); docs contain live infra identifiers (project subdomain, deployment id); `NEXT_PUBLIC_CONN_DETAILS_ENDPOINT` is consumed but undocumented; PRD's normative recap contract (2-3 wins, exactly 1 focus) doesn't match shipped behavior (empty allowed, focus often null in short sessions).

## 9. What's genuinely good

- **Invariants in code, not prompts:** one-focus and three-win caps live in `BakarState`; the recap parser on the frontend treats the data packet as untrusted input (version gate, clamps, bounded strings) and renders plain text only.
- **`bakar_state.py` is import-free of LiveKit** and fully unit-tested offline — the right seam for the hardest logic (verbatim filtering, fallback win selection, closing-index semantics).
- **Honest, evidence-based engineering history:** `WORKLOG.md` records four wrong recap theories before the real root cause (orphaned job runners), measured memory (1.1 GB) before choosing hosts, and registration-log verification of the dispatch-name split.
- **Token endpoint hardening:** UUIDv4 rooms (fixing the dispatch-on-room-creation bug), scoped grants, fail-loud env checks, hex-sanitized remote accent colors, no secrets client-side.
- The main agent's pipeline choices are each justified by an in-code comment tied to a observed failure (`max_tool_steps=6`, endpointing, BVCTelephony for SIP).

## 10. Suggested next steps (highest value first)

1. Fix the watchdog CWD bug (one `Set-Location $AgentDir` — cheapest high-impact fix).
2. Close the recap races: extend grace on `bakar.recap` arrival client-side; make `recap_sent` set-before-await (or lock) server-side.
3. Rewrite `AGENTS.md` for Bakar and reconcile the LLM story across README / TECH_DESIGN / `.env.example` / DEPLOY (gpt-4o-mini default; Gemini = telephony-only).
4. Align telephony with `build_llm()`-style env selection (or update the sync rule), and raise Fly memory to 2 GB.
5. Add skip-guards to `test_agent.py`, a dispatch-name consistency test, and judged tests for tool usage; wire `verify-*.mjs` into CI.
6. Fix `pyproject.toml` packaging (`py-modules` + telephony packaging) before anyone builds a wheel; delete the dead CI copies and taskfile no-op.
