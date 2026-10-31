# AGENTS.md

This is the Bakar monorepo — a spoken-English practice companion built on LiveKit Agents, powered by Murf Falcon TTS. The learner talks to a voice agent that recasts instead of correcting, and every session ends with a recap card delivered over the LiveKit data channel.

## Repository structure

```
├── backend/
│   ├── src/agent.py        # Agent entrypoint — persona, pipeline, tools, END handshake
│   ├── src/bakar_state.py  # Session memory + recap payload (pure Python, no LiveKit imports)
│   ├── src/telephony/      # Optional phone agents (inbound/ and outbound/)
│   ├── scripts/            # Manual e2e harnesses + Windows watchdog
│   └── tests/              # Unit tests + LLM-judged evals
├── frontend/               # Next.js UI (LiveKit Agents UI components)
│   ├── app/                # Pages and API routes (incl. /api/token)
│   ├── components/         # UI components (agents-ui, app, ui, bakar)
│   ├── hooks/ lib/         # Recap hook + parser, uuid ids, shared utils
│   ├── scripts/            # Contract tests over the TS modules (verify-*.mjs)
│   └── app-config.ts       # Branding and feature config
├── docs/                   # PRD, build plan, technical design, deploy guide, voice QA script
├── start_app.sh            # Start all services (macOS/Linux)
└── start_app.ps1           # Start all services (Windows)
```

## Backend

### Tech stack
- **Python 3.10+** with **uv** package manager
- **LiveKit Agents SDK** (`livekit-agents ~1.4`) — voice AI agent framework
- **Murf Falcon** (`livekit-murf`) — text-to-speech; voice **Anisha**, style `Conversation`, `text_pacing=True`
- **Deepgram Nova-3** — speech-to-text, `language="multi"`
- **LLM** — default `openai/gpt-4o-mini` through **LiveKit's inference gateway**; `BAKAR_LLM=selora` switches to an OpenAI-compatible gateway (default model `claude-haiku-4-5`)
- **Silero VAD** + **LiveKit Turn Detector** — voice activity and turn detection

### Key file: `backend/src/agent.py`
The single entrypoint. It contains:
- `SYSTEM_PROMPT` — controls the agent's behaviour (change this to change the use case)
- `BakarAgent` class — extends `Agent`; owns the session state and the three tools (`@function_tool`):
  - `note_focus(area, item, example)` — records the one focus; a second call is rejected by code
  - `log_win(quote, why)` — keeps up to 3 verbatim quotes of things the learner actually said
  - `finish_session()` — publishes the recap and returns the spoken closing lines
- `bakar_agent()` — builds the voice pipeline (STT → LLM → TTS), registers under `AGENT_NAME`, and subscribes to `bakar.end` data packets
- `prewarm()` — pre-loads the Silero VAD model

The LLM comes from `build_llm()`: `BAKAR_LLM=livekit` (default) routes through LiveKit's inference gateway; `BAKAR_LLM=selora` uses the Selora gateway. Pipeline tuning is deliberate — endpointing 0.8 s / 6.0 s, `max_tool_steps=6`, `preemptive_generation=True` — with in-code comments explaining each choice. Do not casually change them.

### Session state and the recap handshake: `backend/src/bakar_state.py`
Pure Python (no LiveKit imports), one instance per job on `BakarAgent.state`. The product caps live in code, not prompts:
- one focus per session (a second `note_focus` is rejected), at most 3 wins
- logged wins survive only if verbatim (`appears_verbatim()`); when none do, the recap falls back to the learner's own transcript sentences (the goodbye utterance is excluded on voice endings)
- strings are clipped (quote 240 / item 120 / example 200) and the `bakar.recap` payload stays < 2 KB

Closing is **client-initiated**: the END button publishes `bakar.end`; the agent answers by publishing the recap JSON on `bakar.recap` and then saying goodbye. `finish_session` is kept for sessions that end by voice.

### Running the backend
```bash
cd backend
uv sync
uv run python src/agent.py download-files   # first time only
uv run python src/agent.py dev              # development
uv run python src/agent.py console          # terminal-only testing
uv run python src/agent.py start            # production (what the Dockerfile and watchdog run)
```

### Environment variables
Copy `backend/.env.example` to `backend/.env.local`. Required keys:
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `MURF_API_KEY`
- `DEEPGRAM_API_KEY`

LLM selection (all optional):
- `BAKAR_LLM` — `livekit` (default) or `selora`; the LiveKit route needs nothing beyond the keys above
- `BAKAR_LLM_MODEL` — model override (defaults: `openai/gpt-4o-mini` for livekit, `claude-haiku-4-5` for selora)
- `SELORA_API_KEY`, `SELORA_BASE_URL` — only for `BAKAR_LLM=selora`

`GOOGLE_API_KEY` is **not** used by any agent — no Google key is needed anywhere in this repo.

`AGENT_NAME` (optional, default `bakar-agent`) is the dispatch name and must match the frontend's `AGENT_NAME`. Use `bakar-agent-dev` to run a local worker beside a deployed one without the two competing for jobs.

### Code style
Uses **ruff** for linting and formatting:
```bash
uv run ruff check .
uv run ruff format .
```
Config is in `pyproject.toml` — 88 char line length, double quotes, space indent.

### Testing
Tests live in `backend/tests/`:
- `test_bakar_state.py` — the state rules (focus cap, win cap, verbatim filter, recap build); no credentials needed
- `test_bugfixes.py` — unit tests for the telephony helpers
- `test_agent_lifecycle.py` / `test_consistency.py` — session wiring and cross-artifact consistency
- `test_agent.py` — LLM-judged evals

Run with:
```bash
uv run pytest
```

The evals in `test_agent.py` use LiveKit's testing framework with LLM-as-judge evaluation (not mocks). They are skip-guarded: without `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` they skip instead of failing.

When modifying the system prompt or adding tools, write tests first. Use the existing evals as a pattern — they call `session.run(user_input=...)` and use `.judge()` to evaluate responses.

Manual harnesses (not wired into pytest/CI):
- `frontend/scripts/verify-recap.mjs`, `frontend/scripts/verify-fixes.mjs` — Node contract tests over the real TS modules
- `backend/scripts/e2e_end.py`, `e2e_recap.py`, `e2e_room.py` — live-room smoke tests; they need full credentials and a running worker, e.g. `uv run python scripts/e2e_room.py "I go to the park yesterday"` from `backend/`

### Telephony (`backend/src/telephony/`)
Optional phone-call agents, separate from the browser agent in `src/agent.py`:
- `inbound/agent.py` — answers incoming calls (`agent_name="inbound-agent"`)
- `outbound/agent.py` — places calls (`agent_name="outbound-agent"`), triggered by `outbound/dial.py`
- `*.json` — SIP trunk and dispatch rule templates applied with the `lk` CLI

Each agent file is intentionally self-contained: the voice pipeline is duplicated rather than shared, so a folder can be copied out and hacked on independently. The agents are aligned with `src/agent.py` — same env-selected LLM (`build_llm()` logic), same voice (Anisha), same Deepgram `nova-3` `language="multi"` setup. The sync rule stays: if you change the voice or model in `src/agent.py`, update the telephony agents too.

Requires no extra dependencies — `livekit-api` ships with `livekit-agents`. Uses the same `.env.local` as the rest of the backend (including `BAKAR_LLM*`/`SELORA_*`; no `GOOGLE_API_KEY`), plus `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` (outbound only) and the optional `TRANSFER_TO_NUMBER`.

See `backend/src/telephony/README.md` for the SIP setup.

### Dependencies
Managed via `uv` and defined in `pyproject.toml`. Always use `uv sync` and `uv run` — never `pip install`.

## Frontend

### Tech stack
- **Next.js** (React, TypeScript)
- **pnpm** package manager
- **LiveKit Agents UI** (shadcn-based components)
- **Tailwind CSS**

### Key files
- `frontend/app-config.ts` — branding, feature flags, accent colors, visualizer config
- `frontend/app/page.tsx` — main page
- `frontend/app/api/token/route.ts` — LiveKit token endpoint (mints a 15-min room-scoped JWT; requires `AGENT_NAME`; in-memory per-IP rate limit)
- `frontend/components/app/` — app-level logic (welcome view, view controller, theme)
- `frontend/components/agents-ui/` — voice UI components (visualizers, controls, chat)
- `frontend/lib/recap.ts`, `frontend/hooks/useRecap.ts`, `frontend/components/bakar/session-recap.tsx` — the recap protocol: defensive parsing of the `bakar.recap` packet, the data-channel hook, and the card UI
- `frontend/lib/ids.ts` — room/identity uuid helpers

### Running the frontend
```bash
cd frontend
pnpm install
pnpm dev
```

### Environment variables
Copy `frontend/.env.example` to `frontend/.env.local`. Required:
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `AGENT_NAME` — **required**; must match the agent's dispatch name (`bakar-agent` unless overridden server-side). The token endpoint fails loudly (500) without it.

### Checks
```bash
pnpm lint                       # ESLint
pnpm format:check               # Prettier
pnpm build                      # production build (type-checks)
node scripts/verify-recap.mjs   # recap contract tests
node scripts/verify-fixes.mjs   # bug-fix regression contract tests
```

## Common tasks

### Change what the agent does
Edit `SYSTEM_PROMPT` in `backend/src/agent.py`. See `backend/README.md` for example prompts.

### Change the voice
Edit the `voice` argument in `murf.TTS(...)` in `backend/src/agent.py`, and mirror the change in the telephony agents — they duplicate the pipeline on purpose. Browse voices at https://murf.ai/api/docs/voices-styles/voice-library.

### Add a tool to the agent
Add a method to the `BakarAgent` class in `backend/src/agent.py` with the `@function_tool` decorator; import `function_tool` and `RunContext` from `livekit.agents`. Tools return instruction strings the model reads as its next context. Any cap that matters (one focus, three wins) belongs in `bakar_state.py`, where it can be unit-tested — not in the prompt alone. The closing turn chains several tool calls, which is why `max_tool_steps=6`; raise it if a new tool must run in that turn.

### Switch the LLM
Set `BAKAR_LLM=livekit` (default — LiveKit inference gateway, `openai/gpt-4o-mini`) or `BAKAR_LLM=selora` (OpenAI-compatible Selora gateway, default `claude-haiku-4-5`, needs `SELORA_API_KEY`/`SELORA_BASE_URL`). Override the model with `BAKAR_LLM_MODEL`. The switch lives in `build_llm()` in `agent.py`.

### Change frontend branding
Edit `frontend/app-config.ts` — company name, page title, logo paths, accent colors, button text, visualizer type.

## Documentation references

- Murf Falcon TTS: https://murf.ai/api/docs/text-to-speech/streaming
- Murf Voice Library: https://murf.ai/api/docs/voices-styles/voice-library
- LiveKit Agents SDK: https://docs.livekit.io/agents
- LiveKit Agents UI: https://livekit.io/ui
- Deepgram STT: https://developers.deepgram.com
