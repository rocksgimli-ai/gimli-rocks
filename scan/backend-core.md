# BACKEND CORE scan — `backend/`

Scope read in full: `src/agent.py`, `src/bakar_state.py`, `src/__init__.py`, `pyproject.toml`, `livekit.toml`, `taskfile.yaml`, `Dockerfile`, `docker-compose.yml`, `fly.toml`, `railway.toml`, `.env.example`, `README.md`, `.dockerignore`, `.github/workflows/ruff.yml`, `.github/workflows/tests.yml`. Read-only scan; no project file was modified. All line numbers verified by reading the files.

---

## 1. File-by-file summary

### 1.1 `backend/src/agent.py` (343 lines) — the single entrypoint
- Module docstring (agent.py:1-10): "Bakar — a spoken-English companion", a confidence-building spoken-English practice agent. Short turns, recasts instead of corrections, one thing to practise, visible recap.
- Env loading (agent.py:44-45): `BACKEND_DIR = Path(__file__).resolve().parents[1]`, then `load_dotenv(BACKEND_DIR / ".env.local")` — env is resolved relative to the file, not CWD, explicitly because hosted runtimes start from a different working directory.
- `AGENT_NAME` (agent.py:52): `os.getenv("AGENT_NAME", "bakar-agent")` — the dispatch name; must match the frontend's `AGENT_NAME` or the room gets no dispatch (comment at agent.py:49-51).
- `SYSTEM_PROMPT` (agent.py:54-87): full prompt quoted in §2.1 below.
- LLM factory `build_llm()` (agent.py:93-113): provider switch by `BAKAR_LLM` env (`strip().lower()`; default `"livekit"`):
  - `selora` → `openai.LLM(model=BAKAR_LLM_MODEL or "claude-haiku-4-5", api_key=SELORA_API_KEY, base_url=SELORA_BASE_URL or "https://api.selora.lol/v1")` (agent.py:99-108; constants at 89-90).
  - default → `inference.LLM(model=BAKAR_LLM_MODEL or "openai/gpt-4o-mini")` — LiveKit's inference gateway (agent.py:110-112).
- `GREETING_INSTRUCTIONS` (agent.py:116-119): greet like a friend, one easy specific question about their day, two short sentences, do not introduce self as AI/teacher.
- Class `BakarAgent(Agent)` (agent.py:123-273): per-job agent, owns conversation + session memory (`BakarState`). `__init__(ctx: JobContext | None = None, *, greet: bool = True)` (agent.py:126-130) — `greet=False` exists so eval harnesses can drive the first turn themselves.
  - `on_user_transcribed(event: object)` (agent.py:132-135): keeps every final user transcript (`is_final` check via `getattr`) as recap fallback.
  - `on_enter()` (agent.py:137-144): if `greet`, calls `self.session.generate_reply(instructions=GREETING_INSTRUCTIONS)` — the agent speaks first ("silence is what an under-confident speaker reads as judgement", comment 139-141).
  - Three `@function_tool`s: `note_focus`, `log_win`, `finish_session` — full list in §3.
  - `remember_history()` (agent.py:212-231): pulls user-role items out of `self.session.history.items` into state — backup transcript source because "the STT event … is not guaranteed to fire before the session closes".
  - `publish_recap()` (agent.py:234-247): `await self.ctx.room.local_participant.publish_data(json.dumps(self.state.build_recap(), ensure_ascii=False), topic=RECAP_TOPIC, reliable=True)`; catches all exceptions and returns False — "a missing card must not end a call".
  - `on_client_end()` (agent.py:249-273): END-button path. If `recap_sent`, returns; otherwise logs, `remember_history()`, `mark_closing(exclude_last=False)`, `publish_recap()`, sets `recap_sent = True`, then `generate_reply(instructions="Say a short, warm goodbye. Do not start a new topic.")`. Comment (252-254): "The model cannot be trusted to call finish_session every time (it was advisory in practice), so the learner's own hang-up is the trigger."
- Server wiring (agent.py:273-343):
  - `server = AgentServer()` (273); `prewarm(proc)` loads `silero.VAD.load()` into `proc.userdata["vad"]` (276-277), wired via `server.setup_fnc = prewarm` (280).
  - `@server.rtc_session(agent_name=AGENT_NAME)` on `async def bakar_agent(ctx: JobContext)` (283-284); sets `ctx.log_context_fields = {"room": ctx.room.name}` (285-286).
  - Registers `session.on("user_input_transcribed", agent.on_user_transcribed)` (313).
  - Data listener (315-322): `end_tasks: list[asyncio.Task[None]] = []`; `_on_data` appends `asyncio.create_task(agent.on_client_end())` when `packet.topic == END_TOPIC`; hook: `ctx.room.on("data_received", _on_data)`.
  - `await session.start(agent=agent, room=ctx.room, room_options=room_io.RoomOptions(audio_input=...))` (324-338) with participant-kind-dependent noise cancellation: `noise_cancellation.BVCTelephony()` for `PARTICIPANT_KIND_SIP`, else `noise_cancellation.BVC()` (327-336). Then `await ctx.connect()` (339).
  - `if __name__ == "__main__": cli.run_app(server)` (342-343).

### 1.2 `backend/src/bakar_state.py` (~217 lines) — session state + recap payload
- Header (bakar_state.py:1-6): "Deliberately free of LiveKit imports … pure functions, so they can be tested in milliseconds without credentials or plugins."
- Constants (bakar_state.py:14-24): `RECAP_VERSION = 1`, `RECAP_TOPIC = "bakar.recap"`, `END_TOPIC = "bakar.end"`, `MAX_WINS = 3`, payload caps `MAX_QUOTE = 240`, `MAX_ITEM = 120`, `MAX_EXAMPLE = 200`, `FOCUS_AREAS = ("pronunciation", "grammar", "vocabulary", "fluency")`.
- `_DRILL_HINTS` (27-32): per-area practice hint used in the recap card.
- `appears_verbatim(quote, transcripts)` (36-49): normalizes to lowercase alphanumeric words and does substring matching over joined words — "Models paraphrase. Showing a learner a sentence they did not say is worse than showing them nothing."
- `_clip(text, limit)` (53-58): whitespace collapse + ellipsis truncation.
- Frozen dataclasses `Focus(area, item, example)` (61-65) and `Win(quote, why)` (68-72).
- `@dataclass BakarState` (74-87): `focus: Focus | None`, `wins: list[Win]`, `transcripts: list[str]`, `closing_index: int | None`, `started_at: float = time.monotonic()`, `recap_sent: bool = False`. Docstring: "One conversation's worth of memory. Never persisted."
- Methods: `note_focus` (89-113, one-focus cap enforced here, not in the prompt), `mark_closing(*, exclude_last=True)` (116-125), `add_transcript` (127-130, clip + consecutive-duplicate suppression), `effective_wins` (132-159), `log_win` (161-169, MAX_WINS cap), `duration_s` (171-172), `build_recap` (174-196), `spoken_summary` (198-217). Detail in §4.

### 1.3 `backend/src/__init__.py`
Single comment line: `# This file makes the src directory a Python package`. No exports, no version.

### 1.4 `backend/pyproject.toml`
- Project `bakar-agent` v1.0.0 (pyproject.toml:6-7); `requires-python = ">=3.10, <3.15"` (:9).
- Dependencies (:11-16): `livekit-agents[deepgram,google,openai,silero,turn-detector]~=1.4`, `livekit-murf>=0.1.1`, `livekit-plugins-noise-cancellation~=0.2`, `python-dotenv`.
- Dev group (:18-23): `pytest`, `pytest-asyncio`, `ruff`.
- Packaging (:25-29): `[tool.setuptools.packages.find] where = ["src"]`, `[tool.setuptools.package-dir] "" = "src"` — see Issue 7.
- pytest (:31-33): `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`.
- ruff (:35-45): line-length 88, target py310; lint select `["E","F","W","I","N","B","A","C4","UP","SIM","RUF"]`, ignore E501; format double quotes, space indent.

### 1.5 `backend/livekit.toml`
Two-line LiveKit Cloud project link: `[project] subdomain = "[previous-project]"`, `[agent] id = "CA_[redacted]"`. Sandbox-template artifact, no pipeline config.

### 1.6 `backend/taskfile.yaml`
Task runner (version "3", `dotenv: [".env.local"]`). Vars: `PYTHON_MAIN = ./src/agent.py`. Tasks: `post_create` (prints setup hints, calls the two sub-tasks), `set_agent_name_if_present` (sed-style rewrite of `agent_name="my-agent"` in src/agent.py when `LIVEKIT_AGENT_NAME` is set — see Issue 4), `help_open_sandbox_if_present` (prints sandbox URL), `install` (`uv sync`), `dev` (`uv run src/agent.py dev`, interactive). Template legacy from the LiveKit starter.

### 1.7 `backend/Dockerfile`
Multi-stage, `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` base (ARG `PYTHON_VERSION=3.13`, :6-7). Build stage: gcc/g++/python3-dev, `WORKDIR /app`, copies `pyproject.toml` + `uv.lock`, `uv sync --locked` (:35), `COPY . .` (:40), bakes models via `RUN uv run "src/agent.py" download-files` (:45). Production stage: non-root `appuser` (UID 10001), `COPY --from=build --chown=appuser:appuser /app /app`, `USER appuser`, `CMD ["/app/.venv/bin/python", "/app/src/agent.py", "start"]` (:73).

### 1.8 `backend/docker-compose.yml`
Single service `bakar-agent`, `build: .`, `image: bakar-agent:latest`, `restart: unless-stopped`, `env_file: .env`, `stop_grace_period: 30s`, `mem_limit: 2g` with comment "Measured: ~1.1 GB resident at idle with models loaded … This limit is an OOM guard, not a target — size the VM at 2 GB minimum" (:7-10), json-file log rotation 10m×3. Outbound-only networking (comment :2-3: worker dials out on 443 WSS + UDP; no inbound ports published).

### 1.9 `backend/fly.toml`
Fly.io worker: `app = "bakar-agent"`, `primary_region = "sin"`, builds the local Dockerfile, `[env] BAKAR_LLM = "livekit"`, `BAKAR_LLM_MODEL = "openai/gpt-4o-mini"` (:12-15), `[[vm]] size = "shared-cpu-1x", memory = "1gb"` (:17-19), rolling deploy. Comment: no `[http_service]` because the worker dials out.

### 1.10 `backend/railway.toml`
`[build]` DOCKERFILE/Dockerfile; `[deploy]` restart policy ON_FAILURE, max 10 retries. Comment claims the image CMD already runs `uv run --no-sync src/agent.py start` — stale, see Issue 3.

### 1.11 `backend/.env.example`
Documents: LiveKit URL/key/secret; `MURF_API_KEY`; `DEEPGRAM_API_KEY`; `GOOGLE_API_KEY` ("For Gemini (default)") plus commented `OPENAI_API_KEY`; LLM provider block `BAKAR_LLM=livekit`, `BAKAR_LLM_MODEL=openai/gpt-4o-mini`, commented `SELORA_API_KEY` / `SELORA_BASE_URL=https://api.selora.lol/v1`; optional `AGENT_NAME` (default `bakar-agent`, must match frontend); telephony block: `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`, optional `TRANSFER_TO_NUMBER`. Internal inconsistency about the "default" LLM — see Issue 1.

### 1.12 `backend/README.md`
Positions the project as "Voice Agent with Murf Falcon TTS", flow diagram "User speaks → [Deepgram STT] → text → [Gemini LLM] → response → [Murf Falcon TTS] → audio" (Setup section). Setup via `uv sync`, `cp .env.example .env.local`, `lk app env`, `download-files`, then `dev` / `console` / `start`. Configuration section: SYSTEM_PROMPT location, 10 example prompts (customer support → mental-health companion), voice table (`Anisha` Indian English female listed as default, `en-US-matthew` in the code example — see Issue 8), STT note (Deepgram Nova-3), LLM note ("Default is Google Gemini" — see Issue 1). Telephony section; testing section (`uv run pytest`, LLM-as-judge, needs LIVEKIT_* secrets); deployment section: Railway button + Docker commands only (no Fly/compose — see Issue 8); project-structure tree that omits `bakar_state.py`, `livekit.toml`, `taskfile.yaml`, `fly.toml`, `docker-compose.yml`, `.github/`; links; MIT license.

### 1.13 `backend/.dockerignore`
Excludes tests (`test/ tests/ eval/ evals/`), Python artifacts, venvs, caches, logs, **`.env` and `.env.*`** (secrets never enter the image), `.git`, editors, README/LICENSE, and a long list of coding-agent files (`.claude/`, `AGENTS.md`, `CLAUDE.md`, copilot instructions, etc.). Note: `.env.*` also excludes `.env.example` from the image (harmless).

### 1.14 `backend/.github/workflows/ruff.yml`
On push/PR to `main`. Steps: checkout@v4, `astral-sh/setup-uv@v1`, `actions/setup-python@v4` (Python 3.12), `UV_GIT_LFS=1 uv sync --dev`, `uv run ruff check --output-format=github .`, `uv run ruff format --check --diff .`.

### 1.15 `backend/.github/workflows/tests.yml`
On push/PR to `main`. Same uv/Python setup, then `uv run pytest -v` with `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` from repo secrets. No skip guard — without the secrets the eval suite fails (README states the requirement; both workflows verified to have no `if:` guard).

---

## 2. End-to-end voice pipeline and agent lifecycle

### 2.1 The use case encoded by SYSTEM_PROMPT (agent.py:54-87)
The agent is **Bakar**, "a warm, patient friend who helps people speak English with confidence", aimed at an under-confident learner who "already understands more English than they believe". Operational rules in the prompt:
- Speak 1-2 short sentences per turn, almost every turn ends with a question/invitation; no inflated praise, no corporate tone; talk about what they said, not their English; never mention grammar rules/levels/scores/lessons unless asked.
- **Recast, don't correct** ("I go yesterday" → "You went yesterday — was it busy?"); one focus per session, only if it keeps repeating; offer sentence starters on stalls; on explicit correction request, one precise fix + one example, then hand the turn back.
- Never say "wrong"/"mistake"/"incorrect"/"error"; never two questions at once; never switch to the learner's first language unless asked twice; never claim precise pronunciation judgment.
- Session shape: open with something easy about their day; while talking call `log_win` 2-3 times quoting the learner verbatim and `note_focus` once (prompt explicitly instructs a pre-`finish_session` check so the recap is never empty); the moment the learner signals they're done, call `finish_session`, speak the returned closing lines (two things they said, one thing to practise, one example to repeat), then stop.

### 2.2 Pipeline wiring (agent.py:289-309)
| Component | Selection | Params | Line |
|---|---|---|---|
| STT | `deepgram.STT` | `model="nova-3"`, `language="multi"` (comment: multilingual nova-3 copes with accented English without forcing a locale) | 292 |
| LLM | `build_llm()` | default LiveKit inference `openai/gpt-4o-mini`; `BAKAR_LLM=selora` → OpenAI-compatible gateway, default model `claude-haiku-4-5` | 294 (factory 93-113) |
| TTS | `murf.TTS` | `voice="Anisha"`, `style="Conversation"`, `text_pacing=True` (comment: warm Indian English matching the learner persona) | 296 |
| Turn detection | `MultilingualModel` (LiveKit turn detector) | no params | 299 |
| Endpointing | — | `min_endpointing_delay=0.8`, `max_endpointing_delay=6.0` (learners pause mid-sentence) | 300-301 |
| VAD | `silero.VAD` | preloaded in `prewarm()` into `proc.userdata["vad"]` | 302, 276-277 |
| Latency | — | `preemptive_generation=True` (generate while the user is still finishing) | 304 |
| Tool budget | — | `max_tool_steps=6` (default 3 dropped the recap card when the closing turn made 4 tool calls — comment 306-308) | 308 |
| Noise cancellation | room option | `BVCTelephony()` for SIP participants, `BVC()` otherwise (chosen per `params.participant.kind` via lambda) | 327-336 |

### 2.3 Lifecycle, end to end
1. **Boot**: `cli.run_app(server)` (agent.py:343) starts the AgentServer; `prewarm()` loads Silero VAD once per process (276-280).
2. **Dispatch**: a LiveKit room job matching agent name `AGENT_NAME` (default `bakar-agent`, from env at import time, agent.py:52, 283) triggers `bakar_agent(ctx)`.
3. **Session build**: AgentSession created with the pipeline above; `BakarAgent(ctx)` instantiated; STT final-transcript callback registered (313).
4. **END button listener**: `ctx.room.on("data_received", _on_data)` (322) — a data packet on topic `bakar.end` (END_TOPIC, bakar_state.py:16) spawns `agent.on_client_end()` as an asyncio task (317-321).
5. **Session start**: `session.start(agent=..., room=ctx.room, room_options=...)` with the participant-kind-dependent noise cancellation (324-338); then `await ctx.connect()` (339).
6. **Greeting**: `Agent.on_enter` fires `generate_reply(GREETING_INSTRUCTIONS)` — the agent speaks first (137-144).
7. **Conversation**: STT final transcripts feed both the LLM turn loop and `BakarState.transcripts` (132-135); the LLM may call `log_win` / `note_focus` at any point.
8. **Closing, path A (spoken)**: model calls `finish_session` → history pulled into state → `mark_closing()` → recap JSON published on topic `bakar.recap` → returns `spoken_summary()` instructions that the model speaks aloud (195-210).
9. **Closing, path B (END button)**: data packet on `bakar.end` → `on_client_end()` → history pulled → `mark_closing(exclude_last=False)` → recap published → goodbye `generate_reply` (249-273).
10. **Job end**: after `ctx.connect()` returns there is no explicit drain of `end_tasks` or session shutdown code — the function exits when the connection closes.

### 2.4 Recap payload (`build_recap`, bakar_state.py:174-196)
JSON on topic `bakar.recap`, versioned (`version: 1`): `wins: [{quote, why}]` (via `effective_wins`), `focus: {area, item, example} | null`, `drill: {sentence, hint} | null` (hint from `_DRILL_HINTS` by area), `duration_s` (monotonic, ≥0).

---

## 3. Complete list of agent tools (all in `BakarAgent`)

| # | Tool | Signature | Behavior | Lines |
|---|---|---|---|---|
| 1 | `note_focus` | `async (self, context: RunContext, area: Literal["pronunciation","grammar","vocabulary","fluency"], item: str, example: str) -> str` | Delegates to `BakarState.note_focus`. Rejects unknown `area` (allowed list returned) and rejects a second call once a focus exists ("You already chose a focus … Keep that one"). `item` clipped to 120 chars, `example` to 200. Docstring requires `example` to be a clean self-written sentence, never a possibly-misheard transcript fragment. Logs accepted/rejected. | agent.py:146-169; state logic bakar_state.py:89-113 |
| 2 | `log_win` | `async (self, context: RunContext, quote: str, why: str) -> str` | Delegates to `BakarState.log_win`. Cap of 3 wins (`MAX_WINS`); beyond that returns "You already have three wins…". `quote` clipped to 240, `why` to 120. Docstring: quote must be word-for-word, never tidied/paraphrased, never a goodbye/thank-you/one-word answer. | agent.py:171-192; state logic bakar_state.py:161-169 |
| 3 | `finish_session` | `async (self, context: RunContext) -> str` | Idempotence guard via `state.recap_sent`. Order: `remember_history()` → `mark_closing()` (default `exclude_last=True` — the goodbye utterance itself is excluded from fallback wins) → if already sent, return "The recap has already been sent. Just say goodbye." → else `await publish_recap()` (data packet on `bakar.recap`, reliable) → `recap_sent = True` → return `spoken_summary()` (closing-line instructions built from state). | agent.py:194-210; `publish_recap` 234-247; `spoken_summary` bakar_state.py:198-217 |

There are no other `@function_tool` definitions in `src/agent.py`. (The `.env.example` telephony block references a `transfer_to_human` tool — that lives in `src/telephony/`, outside this scan's assigned files.)

---

## 4. State model (`BakarState`, bakar_state.py)

**Storage mechanism: pure in-memory dataclass. No persistence anywhere** (class docstring: "One conversation's worth of memory. Never persisted.", :76); no LiveKit imports, no I/O, no locks. One instance per job, created in `BakarAgent.__init__` (agent.py:129).

**Fields** (bakar_state.py:78-87): `focus: Focus | None`; `wins: list[Win]` (max 3); `transcripts: list[str]` (every final user sentence, each clipped to 240 chars, consecutive-duplicate suppression only, :127-130); `closing_index: int | None` (where the goodbye started, used to exclude farewell utterances from fallback wins); `started_at` (monotonic clock for `duration_s`); `recap_sent: bool`.

**Invariants enforced in code, not in the prompt** (explicit design note at :92-95 — "a model under conversational pressure will happily correct five things, and five corrections is a lesson, not a friend"):
- At most **one focus** per session (`note_focus` refuses a second, :102-106); focus `area` must be in `FOCUS_AREAS` (:97-100).
- At most **three wins** (`log_win`, :163-166).
- **Bounded payload** via `_clip` caps (240/120/200, :20-22) — "Keeps the data packet small and the card readable on a phone" (:19).

**Win selection — `effective_wins()` (:132-159)**, the most intricate logic:
1. If no transcripts (e.g. typed input in an eval harness — comment :139-140), return logged wins as-is.
2. Else keep only logged wins that `appears_verbatim()` against transcripts (normalized lowercase-alphanumeric word-substring match, :36-49); if any survive, return those. Rationale: "Models paraphrase. Showing a learner a sentence they did not say is worse than showing them nothing" (:42-44).
3. Fallback: the learner's own sentences, from `transcripts[:closing_index]` (goodbye excluded; if that empties the list, all transcripts), filtered to ≥3 words, sorted by `key=(ends_with_".!?"/"!"/"?", len(text))` reversed — i.e. punctuated sentences first, then longer first — top 2 returned as `Win(quote=text, why="")` (:144-158).

**Closing handling**: `mark_closing(*, exclude_last=True)` — `closing_index = max(0, len-1)` when the learner ended by speaking (excludes the goodbye), `len` when END button was pressed (include everything, :116-125). The two closing paths pass the matching flag: `finish_session` uses the default (agent.py:204), `on_client_end` passes `exclude_last=False` (agent.py:265).

**Thread-safety**: no locks, no atomics. All access happens on a single asyncio event loop (tool calls, the `user_input_transcribed` callback, and `on_client_end` tasks are scheduled on the same loop), so there is no parallel mutation — but there **are** `await` gaps between check and set of `recap_sent`, i.e. check-then-act races are possible across suspension points (Issue 5). `started_at` uses `time.monotonic()`, correct for duration measurement.

**Consumers**: `build_recap()` → published as the recap data packet; `spoken_summary()` → returned from `finish_session` as the model's closing instructions; `duration_s()` → embedded in the recap payload.

---

## 5. Deployment / config surface

**Environment variables** (union of `.env.example`, agent.py, fly.toml, docker-compose.yml):

| Variable | Used by | Default | Notes |
|---|---|---|---|
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit connection | — | also required as CI secrets for tests.yml |
| `MURF_API_KEY` | Murf TTS plugin | — | |
| `DEEPGRAM_API_KEY` | Deepgram STT plugin | — | |
| `GOOGLE_API_KEY` | not read by `src/agent.py`; consumed via the `google` extra by telephony agents (`telephony/inbound/agent.py:159-160`, `telephony/outbound/agent.py:175-176`) | — | README/.env.example wrongly call it the main agent's "default" (Issue 1) |
| `BAKAR_LLM` | `build_llm()` | `livekit` | `selora` switches to the OpenAI-compatible gateway |
| `BAKAR_LLM_MODEL` | `build_llm()` | `openai/gpt-4o-mini` (livekit) / `claude-haiku-4-5` (selora) | |
| `SELORA_API_KEY`, `SELORA_BASE_URL` | selora path | `https://api.selora.lol/v1` | comment warns every turn 402s unless the account is activated (agent.py:95-97) |
| `AGENT_NAME` | dispatch name | `bakar-agent` | must match frontend; different suffix isolates a dev worker from deployed workers (agent.py:49-52) |
| `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`, `TRANSFER_TO_NUMBER` | telephony only | — | documented in `.env.example` telephony block |
| `LIVEKIT_AGENT_NAME`, `LIVEKIT_SANDBOX_ID` | taskfile.yaml template tasks | — | not read by the agent |

**Loading order**: `.env.local` at backend root, loaded from a path anchored to `agent.py` (agent.py:44-45); in containers the process env comes from the platform (`env_file: .env` in compose; `fly secrets`; Railway env vars) — `.dockerignore` excludes `.env`/`.env.*` so secrets are never baked into the image.

**Run modes**: `dev` (auto-reload), `console` (terminal), `start` (production worker — the Dockerfile CMD), `download-files` (models; also run at image build, Dockerfile:45). `taskfile.yaml` wraps `install`/`dev`.

**Deployment targets present in the repo**: Dockerfile (uv-based multi-stage, non-root, models baked); docker-compose.yml (single service, 2 GB OOM guard, outbound-only); fly.toml (`bakar-agent`, region `sin`, shared-cpu-1x / 1 GB, LLM pinned to livekit/gpt-4o-mini via `[env]`); railway.toml (Dockerfile builder, ON_FAILURE restart ×10); livekit.toml (LiveKit Cloud project/agent IDs, sandbox template). README's Deployment section documents only Railway + Docker.

**CI**: two workflows on push/PR to `main` — ruff (check + format --check) and pytest eval suite requiring LiveKit secrets; both Python 3.12 via setup-uv@v1.

---

## 6. Issues found

Ordered by severity. Each with file:line evidence.

1. **Docs claim the wrong default LLM (stale "Gemini default" everywhere).** The actual default is LiveKit's inference gateway with `openai/gpt-4o-mini` (agent.py:89, 110-112); `GOOGLE_API_KEY` is never read in `src/agent.py`. Yet README says "Gemini LLM" in the flow diagram (Setup section) and "Default is Google Gemini" (LLM section); `.env.example` labels `GOOGLE_API_KEY` "For Gemini (default)" while its own `BAKAR_LLM` block documents `livekit` as default — internally inconsistent. The `google` extra in pyproject.toml:12 is real but serves only the telephony agents (`telephony/inbound/agent.py:159-160` gemini-2.5-flash, `telephony/outbound/agent.py:175-176` gemini-3.5-flash-lite — cross-referenced to resolve this issue). Root AGENTS.md repeats "Google Gemini — LLM". Confidence: certain (code vs docs, both read).

2. **Fly.io memory (1 GB) is below the repo's own measured minimum.** docker-compose.yml:8-10: "Measured: ~1.1 GB resident at idle with models loaded … size the VM at 2 GB minimum"; fly.toml:17-19 sets `size = "shared-cpu-1x", memory = "1gb"`. Idle alone exceeds the Fly allocation → OOM-kill risk on Fly. The two files were written by the same project, so this is an internal contradiction, not a guess. Confidence: certain on the contradiction; the 1.1 GB figure itself is the repo's claim, not independently verified.

3. **railway.toml comment misstates the image CMD.** railway.toml:4-5: "the image CMD already runs `uv run --no-sync src/agent.py start`". Actual CMD: `["/app/.venv/bin/python", "/app/src/agent.py", "start"]` (Dockerfile:73). Functionally equivalent outcome (both start the worker via the venv), but the comment is factually wrong. Confidence: certain.

4. **taskfile.yaml `set_agent_name_if_present` is dead code against the current agent.** It rewrites the literal `agent_name="my-agent"` in `src/agent.py` (taskfile.yaml:42-53), but agent.py:283 uses `@server.rtc_session(agent_name=AGENT_NAME)` with the value from env (agent.py:52) — no literal match exists, so the substitution silently does nothing. Starter-template legacy. Confidence: certain (both files read; no `agent_name="my-agent"` string exists in agent.py).

5. **Duplicate-recap race across await points (check-then-act on `recap_sent`).** `finish_session` checks `recap_sent` (agent.py:205), then `await publish_recap()` (207), then sets `recap_sent = True` (209). `on_client_end` has the same pattern (check 255, publish ~266, set 267). Both run on one event loop, but if the learner presses END while the model's `finish_session` is suspended at its `await`, `on_client_end` sees `recap_sent == False`, publishes a second recap card, and both fire a goodbye `generate_reply`. Same window exists for two rapid END presses (two `on_client_end` tasks, agent.py:319-320). Low probability, real; a set-before-await flag or an asyncio.Lock would close it. Confidence: high (control flow read directly; race requires specific timing).

6. **`end_tasks` is never awaited or drained.** Tasks created in `_on_data` are only appended to a list (agent.py:315-321); no result checking, no gather, and the list grows unboundedly for repeated END presses (mitigated only by the `recap_sent` early-return at agent.py:255). If the job exits right after `ctx.connect()` returns, a just-spawned `on_client_end` may not finish before process teardown. Confidence: high on the facts; impact modest.

7. **Packaging metadata does not declare the loose modules.** `[tool.setuptools.packages.find] where = ["src"]` (pyproject.toml:25-26) finds *packages*, not the top-level modules `agent.py` / `bakar_state.py`, yet agent.py:37 does `from bakar_state import …`. Imports work in every observed runpath only because `agent.py` is executed as a script, putting `src/` first on `sys.path` (dev: `uv run python src/agent.py`, README; Docker: `/app/.venv/bin/python /app/src/agent.py`, Dockerfile:73). A wheel built from this metadata would not contain the modules; `py-modules` is absent. Related artifact: a `bakar_agent.egg-info/` build directory exists under `backend/src/` (observed during grep) — build output inside the source tree. Confidence: high on metadata vs code; the exact editable-install semantics of uv were not tested (no installs run, per task rules).

8. **README drift vs the actual tree.** (a) Voice example shows `voice="en-US-matthew"` and a `tokenizer=tokenize.basic.SentenceTokenizer(...)` argument (README, Voice section); the code uses `voice="Anisha", style="Conversation", text_pacing=True` with no tokenizer (agent.py:296). (b) Project Structure tree omits `src/bakar_state.py`, `livekit.toml`, `taskfile.yaml`, `fly.toml`, `docker-compose.yml`, `.github/` (README, Project Structure section). (c) Deployment section lists Railway + Docker only, though Fly and Compose configs ship in the same directory. Confidence: certain.

9. **tests.yml has no secret guard.** `uv run pytest -v` runs unconditionally (tests.yml, final step); the eval suite needs `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` (README, Testing section). Any fork/PR without the secrets fails CI by design rather than skipping. Minor, possibly intentional. Confidence: certain.

10. **CI action versions are pinned to older majors.** `astral-sh/setup-uv@v1` and `actions/setup-python@v4` in both workflows (ruff.yml and tests.yml, Install/Set up steps). `actions/setup-python@v4` is deprecated upstream. Cosmetic/operational, no functional bug shown. Confidence: high that the pins are as stated; "deprecated" is upstream knowledge, not verified in-run.

11. **`.env.example` telephony comment references a tool outside the main agent** — "Optional — where the transfer_to_human tool sends callers" (.env.example, telephony block). The tool exists only in the telephony agents (not verified in this scan's assigned files). Cosmetic only.

12. **Possible duplicate recap quotes via double transcript capture.** A final user sentence can enter `transcripts` twice: once from the STT event (agent.py:132-135) and once from chat history at close (`remember_history`, agent.py:212-231), because `add_transcript` only dedupes against the immediately preceding entry (bakar_state.py:127-130). In the fallback branch of `effective_wins` the same sentence could then be selected twice. Edge case; cosmetic impact on the card. Confidence: medium (logic read; not reproduced).

**Not issues (checked and cleared):** `load_dotenv` path anchoring is deliberate and correct for containers (agent.py:42-45); `.dockerignore` correctly strips secrets from the image; `time.monotonic()` is the right clock for `duration_s`; `mark_closing(exclude_last=…)` flags match the two closing paths' semantics (agent.py:204 vs 265, bakar_state.py:116-125); `max_tool_steps=6` is justified by an in-code failure report (agent.py:306-308); VAD prewarm is per-process and correctly shared via `proc.userdata` (agent.py:276-280, 302).

---

*Scan performed 2026-10-31 against the workspace tree at `S:\Bakar`. All 15 assigned files read in full; telephony files were opened only to resolve the `google`-extra question (Issue 1).*
