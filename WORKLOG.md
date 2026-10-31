# Bakar — worklog

Append-only. Newest entry at the bottom. Every entry records *what changed*, *why*, and *how it was verified*.

---

## 2026-10-27 · 10:12 · Phase 0 — foundation

**Created `S:\Bakar` and seeded it from the bug-fixed base** (`S:\Voice Agent Project\Copy of murf-livekit-starter-main for bug fix tests`).

- Copied the source tree with robocopy, excluding `node_modules`, `.next`, `.venv`, `__pycache__`, caches.
- 118 files, 3.84 MB.
- **Decision:** did not copy `node_modules`. pnpm's store is a junction farm on Windows; copying it yields a corrupt tree. Reinstalled from the committed lockfile instead (`pnpm install --frozen-lockfile`), which is reproducible and took under a minute from the local store.

**Renamed project metadata**
- `backend/pyproject.toml`: `agent-starter-python` → `bakar-agent`; description rewritten.
- `frontend/package.json`: `agent-starter-react` → `bakar`.
- Renaming the Python project invalidates `uv.lock`'s root entry, so `uv sync` (not `--locked`) was used once to re-lock.

**Incident:** the first `uv sync` failed with `tomllib.TOMLDecodeError: Invalid statement (at line 1, column 1)`. Cause: PowerShell 5.1's `Set-Content -Encoding UTF8` writes a BOM, and `tomllib` rejects it. Fixed by rewriting both files as UTF-8 **without** BOM via `UTF8Encoding($false)`, then verified with `tomllib.load` and `json.load`. Lesson recorded: never edit TOML/JSON through `Set-Content` on this shell.

---

## 10:16 · Documents before code

Wrote, in order:

1. `docs/PLAN.md` — problem, thesis (three mechanisms), v0 scope, non-goals, five phases, north-star metric (*minutes spoken per user per week*), risks, definition of done.
2. `docs/PRD.md` — personas, storyboard, normative conversation rules, 11 functional requirements with acceptance criteria, recap JSON contract, NFRs, metrics, open questions.
3. `docs/TECH_DESIGN.md` — architecture, agent internals, frontend changes, data contract, latency budget, failure modes, test plan, security, deployment, deliberate limitations.

**Key decisions recorded in the docs**
- **No pronunciation scoring in v0.** Deepgram returns words, not phonemes. Faking a score would be the fastest way to lose a learner's trust. Phase 2 adds a real assessment API behind a tool.
- **One focus per session, enforced in code**, not just in the prompt.
- **Recap travels over the LiveKit data channel** (topic `bakar.recap`) rather than a new HTTP endpoint: same room, same auth boundary, no second service.
- **No persistence in v0.**

---

## 10:20 · Backend

**API check before writing any code** (against the installed 1.4.5, not the docs):
- `Agent.on_enter` exists and is async — safe for the greeting.
- `turn_handling=` **does not exist** in 1.4.5 (that is a 2.x API). Used `min_endpointing_delay=0.8` / `max_endpointing_delay=6.0`, which are first-class parameters here.
- `LocalParticipant.publish_data(payload, *, reliable, destination_identities, topic)`.
- `Agent.session` is available inside `on_enter`.

**New `src/bakar_state.py`** — session memory with no LiveKit imports: `Focus`, `Win`, `BakarState`, `build_recap()`, `spoken_summary()`. The one-focus rule and the three-win cap live here, so they are enforced by code rather than hoped for from the model. Text is clipped and the payload is bounded.

**Rewritten `src/agent.py`** — Bakar persona in five blocks (who you are / who you're talking to / how you speak / how you help / what you never do), `on_enter` greeting, three tools (`note_focus`, `log_win`, `finish_session`), dispatch name `bakar-agent`, voice `Anisha`, endpointing widened for learners.

**Verification:** `ruff check` clean, `ruff format` applied, `pytest tests/test_bakar_state.py` → **13 passed in 0.12 s**.

---

## 10:30 · Frontend

**New**
- `lib/recap.ts` — types + defensive `parseRecap` (version gate, 3-win cap, 400-char clamp, duration clamp) + `formatDuration`.
- `hooks/useRecap.ts` — `useDataChannel('bakar.recap')` → state.
- `components/bakar/session-recap.tsx` — the card: duration, "You said", "Practise next", "Say it once more", dismissible.
- `public/bakar-mark.svg` + `bakar-mark-dark.svg` + `app/icon.svg` — a speech-bubble mark, legible at 24 px.

**Changed**
- `app-config.ts` — Bakar name, title, description, accent `#C2410C` / dark `#FDBA74`, new logo paths.
- `welcome-view.tsx` — promise headline, friend framing, privacy line replacing the starter's quickstart footer.
- `layout.tsx` — logo links home via `next/link`; "Built on LiveKit" credit.
- `agent-session-block.tsx` — mounts `<SessionRecap />`; pre-connect line is now "Take your time — say anything."
- `lib/ids.ts` — room prefix `bakar_room_`, identity prefix `bakar_user_`.
- `telephony/inbound/agent.py` — same persona on the phone line.

**Incident:** lint rejected `<a href="/">` for the logo (`@next/next/no-html-link-for-pages`). Fixed properly with `next/link` rather than suppressing the rule. A first attempt left an unclosed `<Link>` because a PowerShell replacement used a backtick-n inside single quotes (which does not expand); caught by `tsc` immediately.

**Verification:** `tsc --noEmit` 0 · `eslint` 0 errors · `prettier --check` pass · `node scripts/verify-recap.mjs` → **9 passed** · `node scripts/verify-fixes.mjs` → 11 passed (prefixes updated) · `pnpm build` → success.

---

## 10:38 · Visual check

Served the production build and drove a browser to it.

- Home: `200`, headline present, "Best with headphones…" footer present.
- `/bakar-mark.svg`: `200 image/svg+xml`; mark renders as an orange rounded square with a cream speech bubble and three dots.
- `/opengraph-image`: `200 image/png`, 265 KB.
- `POST /api/token`: `bakar_room_36fdc6a2-…`, `agents[0].agentName = bakar-agent`, `video.room` matches.
- Screenshot of the welcome screen confirms layout, contrast and the amber CTA in dark mode.

**Note:** the header is `hidden md:flex`, so at the 488 px test viewport the logo is intentionally absent; the mark was verified by fetching and rendering it directly.

---

## 10:42 · Eval suite adaptation

`pytest --collect-only` failed: `tests/test_agent.py` still imported `Assistant`, which no longer exists.

- Made `BakarAgent.__init__(ctx=None, *, greet=True)` and guarded the publish on `ctx is not None`, so evals can run without a room.
- Rewrote the three evals for Bakar's behaviour: greeting asks exactly one question; a past-tense error is recast without meta-commentary; harmful requests are refused.
- Formatted the state tests (my manual edit had broken formatting).

**Verification:** `ruff check` and `ruff format --check` clean; **27 tests collected**, 0 errors; 24 credential-free tests pass.

---

## 10:45 · Final gates

| Gate | Result |
|---|---|
| `ruff check` (backend) | pass |
| `ruff format --check` (backend) | 10 files clean |
| `pytest` credential-free | 24 passed |
| `pytest --collect-only` | 27 collected, 0 errors |
| `tsc --noEmit` | 0 |
| `eslint` | 0 errors (warnings only, inherited) |
| `prettier --check` | pass |
| `pnpm build` | success — `/`, `/api/token`, `/icon.svg` (static), `/opengraph-image` |
| Production smoke | home 200 · icon 200 · OG 200 · token with `bakar_room_` + `bakar-agent` |

**Not verified (needs credentials / a microphone):**
1. A live voice session — greeting timing, recast behaviour in practice, barge-in feel.
2. The recap card with a real published packet. The parser is unit-tested (9 checks) and the component typechecks and builds, but nothing has yet rendered it with live data.
3. The phone line — prompt and greeting changed, but no call was placed.

These are the first three items in `docs/VOICE_QA.md`.

---

## 2026-10-27 · 17:47 · Live credentials

Checked each credential independently before wiring anything (a wrong key should fail in one
place, not inside a voice session):

| Credential | Result |
|---|---|
| Deepgram | `200`, project listed |
| Murf | `200`, 65 KB of PCM for one sentence |
| LiveKit | `200`, JWT minted |
| Selora | key valid, **`402 trial_not_activated`** — the account needs a Telegram handle verified before it will serve a single token |

So the brain needed a decision. LiveKit's own inference gateway answered with nothing but the
project keys (`openai/gpt-4o-mini`, 1.9 s), so `build_llm()` now selects a provider:

- `BAKAR_LLM=livekit` (default) → `inference.LLM`, works today.
- `BAKAR_LLM=selora` → `openai.LLM(base_url=…)`, ready for when the trial is activated.

Secrets live only in gitignored `.env.local` files. `pyproject.toml` gained the `openai` extra.

---

## 18:05 · First real session (no microphone)

Built `backend/scripts/e2e_room.py`: dispatches the agent into a fresh room, synthesises the
learner's sentence with Murf, publishes it as microphone audio paced in real time, records the
agent's audio track, and transcribes it with Deepgram. A terminal can then read what happened.

```
greeting → "Hi there. I'm really glad to see you. How has your day been so far?"
you      → "I go to the park yesterday and I see a big dog"
bakar    → "You saw a big dog yesterday? What kind of dog was it?"
```

The recast works with real STT, a real LLM and real TTS: the correction is inside the reply.
This is the product thesis, verified end to end.

---

## 18:30 · The recap, and four wrong theories

The recap card did not appear. Sequence of hypotheses, in order:

1. **Tool cap.** The closing turn logs two wins + a focus + publishes = four calls; default
   `max_tool_steps` is 3. Plausible, fixed (`max_tool_steps=6`) — and still no packet.
2. **Prompt ordering.** The model logged wins and then said goodbye. Rewrote the closing
   sequence; now it called `finish_session` but with an empty state, because the new wording
   told it to skip recording. Bad trade, reverted.
3. **Unstable facts.** The model quoted a sentence it had *paraphrased* ("…and I a very big
   dog"), so `appears_verbatim()` now rejects quotes that are not word-for-word in the
   transcript, and the recap falls back to the learner's own sentences.
4. **The goodbye counted as a win.** Added a closing index so the final utterance is excluded —
   then discovered that pressing END after ordinary speech also excluded it, leaving a card
   with nothing. Made the exclusion mode-aware (`exclude_last`).

Then the actual root cause: **`finish_session` was never reached at all**, because my repeated
worker restarts left **orphaned job-runner processes** registered with LiveKit. They answered
dispatches with code from an earlier edit, so the symptoms were random. Diagnosed by writing a
module-load marker to a temp file and watching it never appear for the job that answered; then
killing seven orphans (and switching to `taskkill /T` so children die with the parent).

Lesson recorded: after restarting an agent worker on Windows, kill the **tree**, and verify no
`multiprocessing-fork` orphans remain, or dispatch results become non-deterministic.

---

## 19:00 · Design change: the learner ends the call

Even with the cap raised, `finish_session` was advisory — the model skipped it in roughly half
the runs. A core loop cannot depend on that. So the closing became **client-initiated**:

- the END button publishes an empty `bakar.end` packet, waits 1.2 s, then disconnects;
- the agent answers with the recap and a short goodbye;
- `finish_session` remains for learners who end the conversation by voice.

`remember_history()` also pulls user turns out of `session.history`, because the STT event did
not always populate before the session closed.

Verified three times consecutively (once with a trace proving the path):

```
data packet topic='bakar.end' bytes=0 → on_client_end → transcripts=1 wins=0 → recap published
```

and the card content:

```json
{"version": 1, "wins": [{"quote": "I go to the park yesterday, and I saw a very big dog with my sister.", "why": ""}], "focus": null, "drill": null, "duration_s": 27}
```

Verbatim, complete, and no goodbye. The model still declines to pick a focus in a two-turn
synthetic conversation, so `focus`/`drill` are legitimately `null` — that needs a human session,
which is exactly what `docs/VOICE_QA.md` is for.

---

## 19:10 · Gates with live keys

`uv run --env-file .env.local pytest` → **36 passed**, including the three LLM-judged evals
(warm greeting asks one question; a past-tense error is recast without meta-commentary; harmful
requests are refused). Those had never run before, because they need a live project.

Frontend: `tsc` 0 · `eslint` 0 errors · `prettier --check` pass · `pnpm build` success.

**Still unverified:** a human voice session (barge-in feel, latency under real speech), the
recap card rendering with a live packet in a browser, and the phone line. Those are the first
three items in `docs/VOICE_QA.md`.

---

## 2026-10-28 · 20:10 · Deployability: Vercel / Netlify

The user confirmed the app works locally and asked to deploy it. Constraint stated up front:
**only the frontend can be serverless.** The agent worker holds a websocket to LiveKit and
registers for jobs, so it needs a container host. Deployment therefore splits into
frontend (Vercel/Netlify) + agent (Fly/Railway) + LiveKit Cloud (already SaaS).

**One real code change was required.** Two features read `public/` from disk at runtime:
the header's `existsSync()` check for the configured logo, and the OpenGraph route's
background/wordmark loading. Serverless bundles do not include `public/` unless it is traced,
so on Vercel the logo would have silently fallen back to text and the social card to a
gradient. Added `outputFileTracingIncludes` to `next.config.ts`.

**The first key was wrong and the build caught it — not the deploy.** With key `'/*'` the
build passed but `.next/server/*.nft.json` showed zero `public/` files traced for every route.
Switching to explicit route keys (`'/'` and `'/opengraph-image'`) put all 5 public files into
every bundle (page trace 51 → 588 files). Verified by parsing the `.nft.json` files directly,
not by trusting the build's exit code.

**Added**
- `frontend/next.config.ts` — tracing fix above.
- `netlify.toml` (repo root) — base `frontend`, publish `.next`, Node 22; Netlify's Next
  runtime auto-installs, so the plugin is deliberately not pinned in package.json.
- `backend/fly.toml` — Dockerfile build, `shared-cpu-1x`/1 GB, no `[http_service]`
  (the worker dials out; inbound health checks would be idle noise).
- `backend/railway.toml` — switched from nixpacks to `DOCKERFILE`; nixpacks cannot be relied
  on to provision `uv`. This also closes a latent issue flagged in the original audit.
- `docs/DEPLOY.md` — topology, per-host steps, env matrix, post-deploy checklist, and the
  security posture (the token endpoint is still unauthenticated; enable Vercel Deployment
  Protection or keep the URL private until a real limiter exists).

**Verified locally:** TOML parses (`tomllib`), `pnpm build` passes with the new config,
public/ present in every route trace, and the built app still serves `200` for `/`,
`/opengraph-image` and `POST /api/token`.

**Not verified:** an actual deploy. No Vercel/Netlify/Fly CLI and no Docker on this machine,
so the agent image build and a real Fly deploy remain to be executed on the user's side.

---

## 2026-10-28 · 02:10 · Running locally beside a deployment

Question: can the same machine keep running the stack locally once the frontend is on
Vercel/Netlify and the worker is on Fly? Architecturally yes — the frontend and the agent never
talk to each other, they both connect to LiveKit Cloud, and rooms are UUID-named. But one thing
is shared: **the dispatch name**. LiveKit load-balances jobs across every worker registered
under a given name, so a local worker and a deployed worker both registered as `bakar-agent`
would receive each other's sessions unpredictably — and with different code on each.

Fix: `AGENT_NAME` in `backend/src/agent.py` is now read from the environment (default
`bakar-agent`), so a local worker can register as `bakar-agent-dev` and only the local
frontend (with `AGENT_NAME=bakar-agent-dev`) dispatches to it. Both `.env.example` files
document the pattern.

**Verified by registration, not by assumption:** started the worker with no env →
`registered worker {"agent_name": "bakar-agent"}`; started it with
`AGENT_NAME=bakar-agent-dev` → `registered worker {"agent_name": "bakar-agent-dev"}`.
The deployed worker on Fly keeps `bakar-agent` (its `fly.toml` env does not set the variable,
so the default applies).

Also noted for the user: a local worker serving a deployed frontend carries the agent's audio
over the home connection, and the machine must stay awake — fine for demos, not for availability.

---

## 2026-10-29 · 08:30 · Rebrand: Buckr → Bakar

Renamed the product everywhere, not just the visible strings. Three classes of change:

**Folder** — `S:\Buckr` → `S:\Bakar`.

**Code identifiers** (these must match on both sides of the runtime, so they were changed as one
set): `AGENT_NAME` default `buckr-agent` → `bakar-agent`; env vars `BUCKR_LLM` /
`BUCKR_LLM_MODEL` → `BAKAR_LLM` / `BAKAR_LLM_MODEL`; LiveKit data topics `buckr.recap` /
`buckr.end` → `bakar.recap` / `bakar.end`; room and identity prefixes `buckr_room_` /
`buckr_user_` → `bakar_*`; Python package `buckr-agent` → `bakar-agent`; npm package `buckr` →
`bakar`; module `buckr_state.py` → `bakar_state.py`; component folder `components/buckr/` →
`components/bakar/`.

**Assets and copy** — `buckr-mark.svg` / `buckr-mark-dark.svg` → `bakar-*`, page title,
persona ("You are Bakar"), welcome copy, docs, worklog.

35 files changed in place, 5 files/folders renamed, 0 occurrences of the old brand left in
either tree (case-insensitive sweep, excluding build artefacts).

### Two rebuilds were unavoidable

Renaming a folder that contains installed dependencies breaks their recorded absolute paths:

1. **Python venv** — `uv sync` correctly swapped `buckr-agent` for `bakar-agent`, but the venv's
   console-script trampolines still pointed at `S:\Buckr\backend`, so `uv run pytest` died with
   *"uv trampoline failed to canonicalize script path"*. Fix: delete `.venv`, `uv sync --locked`.
2. **node_modules** — pnpm's `.modules.yaml` still declared
   `virtualStoreDir: S:\Buckr\frontend\node_modules\.pnpm`, so the top-level links were
   missing and `tsc`/`next` could not be found even though `pnpm install` exited 0. Fix: delete
   `node_modules`, reinstall (39 s from the local store).

### Verified after the rename

`ruff check` clean · `ruff format --check` clean · **33 backend tests pass** ·
`tsc --noEmit` 0 · `eslint` 0 errors · `prettier --check` pass · `pnpm build` success ·
live room test: dispatched `bakar-agent`, room `bakar_end_…`, card delivered on `bakar.recap`
with verbatim wins and no goodbye.

### MunshiJi

`S:\MunshiJi` was **not** renamed — and it turned out to have grown into its own product since
the copy: persona "Munshi Ji" for CA/CPA/ACCA/FRM/CFA study, dispatch name `munshiji-agent`,
`MUNSHIJI_LLM` env vars. The rebrand touched only its `WORKLOG.md` (the one file still carrying
the old brand); its 33 tests still pass and its own naming was left untouched.

### If a deployment already exists

Update the host environment: `AGENT_NAME=bakar-agent` (frontend), and `BAKAR_LLM` if it was set
explicitly. Any external consumer listening on `buckr.recap` must move to `bakar.recap`.

---

## 2026-10-30 · 15:30 · Free-VPS hosting explored (Oracle/GCP)

The user proposed hosting the worker on a free Ubuntu VPS with Docker. Explored with measurements
instead of opinions:

- **Worker memory, measured:** parent + job process total **~1.1 GB resident** at idle with models
  loaded (137/150 MB working sets, 565 MB before full init, 1098 MB after). Sessions add more.
  Consequence: GCP's free e2-micro (1 GB) **will OOM** — it is not a candidate.
- **ARM verified:** Oracle's free tier is ARM A1. Checked PyPI: every dependency in our lock has a
  cp313 manylinux aarch64 wheel, including livekit-blingfire (the ARM-risk package) at our pinned
  1.1.0. The Dockerfile build will resolve on ARM as-is.
- **Region:** LiveKit project is India South; the worker should be in ap-mumbai-1. GCP free tier is
  US-only, which would add ~100 ms one-way to the audio path.
- **Added:** backend/docker-compose.yml (restart: unless-stopped, env_file .env, 2 GB OOM guard,
  30 s stop grace, no ports - the worker is egress-only) and docs/DEPLOY.md §6 with the deploy
  steps, Oracle caveats (capacity contention in Mumbai, card verification, idle reclaim), and the
  two-agents-on-one-VM pattern (MunshiJi as a second service).

Verdict recorded in the reply: the quoted claim was half right - the worker cannot be serverless,
but "cannot run for free" is false (LiveKit Build hosts one agent free; a free VPS hosts both).
---

## 2026-10-31 · 14:10 · LIVE on LiveKit Cloud

**The agent is now cloud-hosted and verified end-to-end with no local worker running.**

- lk cloud auth + lk agent create --secrets-file .env.secrets created deployment CA_[redacted] (project akar, [previous-project], region India South)
- Build used our Dockerfile; the first deploy failed at runtime: **CMD was missing "python"** (my bug from the --no-sync edit) and the platform starts the container from /, not the Dockerfile's WORKDIR — so the relative src/agent.py path resolved to /src/agent.py (ENOENT)
- Fixes: CMD now uses absolute paths (/app/.venv/bin/python /app/src/agent.py start) and the agent loads .env.local relative to the script file — the runtime is fully CWD-independent
- Redeployed; verified with the room test (no local worker): greeting → recast → END handshake → recap on akar.recap with verbatim wins
- All gates re-verified: ruff clean, 33 tests, tsc 0, build success

**Remaining for public use:** push to GitHub → Netlify import (4 env vars) → Deployment Protection. ~~the "agent unavailable" toast and the token rate limiter are still pending (both small)~~ → the rate limiter landed the same day (see 20:30 entry below); the "agent unavailable" toast already exists in `hooks/useAgentErrors.tsx`.

---

## 2026-10-31 · 20:30 · Full-code scan and cleanup wave

**A read-only scan of the whole repo** (four parallel area reports under `scan/`, synthesized in `scan/code-scan-report.md`) produced 16 consolidated findings; the user asked to fix all of them. Two decisions (cleanup scope, telephony LLM approach) went unanswered and were taken on the recommended defaults: **full cleanup** and **full alignment** — both stated in `scan/fixes-report.md`.

**Backend fixes**
- `run-agent-watchdog.ps1` — the deploy step (`git pull --ff-only` + `uv sync --locked`) is now anchored to `$AgentDir` (`Push-Location`/`finally Pop-Location`). Under its own `schtasks` recipe the CWD is `C:\Windows\System32`, so both commands silently failed on every boot; crash-restart worked, deploy-by-push never did.
- `src/agent.py` — recap double-send race closed: both closing paths set `recap_sent = True` **before** `await publish_recap()`, and a failed publish hands the claim back so the other path can still deliver. `end_tasks` is drained (`asyncio.gather`) after `ctx.connect()` so an END-press task cannot be cut off by job teardown.
- `src/bakar_state.py` — `add_transcript` dedupes against all transcripts; a sentence captured twice (STT event + chat history) could otherwise appear twice in fallback wins.
- Telephony aligned with `src/agent.py` (the repo's own sync rule was being violated): both phone agents use the same env-driven `build_llm()` (default LiveKit inference `openai/gpt-4o-mini`), voice `Anisha`, `language="multi"` on nova-3, learner endpointing 0.8/6.0, `max_tool_steps=6`, and the outbound dial failure path now also cleans up on non-Twirp exceptions. The `google` extra is dropped from `pyproject.toml` — `GOOGLE_API_KEY` is no longer needed by anything.
- Packaging — `[tool.setuptools] py-modules` declared and `telephony/` given `__init__.py` files; `uv build --wheel` verified the wheel now contains `agent.py`, `bakar_state.py` and the full `telephony/` package (before this, a wheel build would have been incomplete).
- `fly.toml` memory 1 GB → 2 GB (the repo's own measurement: ~1.1 GB idle — 1 GB OOM-killed the worker before registration). `taskfile.yaml` no-op task removed. E2E scripts: file-anchored dotenv, `AGENT_NAME` from env, `e2e_end` recap wait 20→90 s, dead `quiet_since` removed.

**Frontend fixes**
- `agent-session-block.tsx` — recap-loss race closed: END waits up to 4 s for a *valid* `bakar.recap` packet (one-time `RoomEvent.DataReceived` listener, `parseRecap`-validated), gives it 300 ms to render, and always ends the session exactly once.
- `app/api/token/route.ts` — in-memory per-IP sliding-window limiter (20 mints/rolling hour → 429 + `Retry-After`), with the honest per-instance caveat in a comment; DEPLOY.md §9 still recommends Deployment Protection for public use.
- `lib/recap.ts` `formatDuration` renders hours (`1:06:40`); `verify-recap.mjs` extended to 10 checks. READMEs de-staled (frontend still described the Murf starter; `AGENT_NAME` is required, not optional); `NEXT_PUBLIC_CONN_DETAILS_ENDPOINT` documented.
- Cleanup: dead `frontend/.github/` workflow copy and legacy `.eslintrc.json` deleted; 9 declared-but-never-imported deps removed (grep-verified zero imports); lockfile updated.

**Docs** — `AGENTS.md` rewritten for the real code (`Assistant`/`my_agent()`/`my-agent`/Gemini claims are gone); TECH_DESIGN / DEPLOY / PRD / PLAN reconciled with the code (LLM default, absolute Docker CMD, state attribute, recap contract wins 0–3 with focus optional, plan DoD wording).

**Tests** — new `test_consistency.py` (dispatch-rule ↔ inbound agent name, dial ↔ outbound, e2e defaults ↔ agent default, frontend/backend topic parity) and `test_agent_lifecycle.py` (closing behavior incl. concurrent closers publishing at most once), both offline; skip-guards added so the LLM-judged evals skip without credentials instead of failing. The three `no_more_events()` assertions were replaced by `_judge_trailing_events()`: the shape-strict assertions contradicted the prompt's own instruction to log wins mid-conversation — two different trailing shapes were observed in live runs (function-call-only; then function-calls + a second message). Now a premature `finish_session` is a hard failure and every trailing assistant message is judge-checked against the normative conversation rules.

**Verification** — backend: `ruff check` clean · 26 files formatted · **pytest 46 passed** (incl. the 3 LLM-judged evals, live) · wheel contents verified. Frontend: verify-recap **10** · verify-fixes **11** · eslint 0 errors (pre-existing warnings only) · `tsc` 0 · prettier pass · `pnpm build` success. Backend `build/` wheel byproduct removed.

**Not verified:** the new END handshake in a real browser session and the phone line (both are `docs/VOICE_QA.md` items); the rate limiter's behavior across multiple serverless instances.

---

## 2026-11-01 · 00:44 · New LiveKit project (gimli), key rotation, Vercel prep

The user provisioned a fresh LiveKit Cloud project (`gimli-bakar-rcjx7kir`) and rotated the Deepgram and Murf keys. **Secrets live only in gitignored files** — `backend/.env.local`, `frontend/.env.local`, `backend/.env.secrets` — verified by `git status` (only `livekit.toml` and `docs/DEPLOY.md` changed) and by a secret-pattern scan of the staged diff before pushing. Git identity switched to the GitHub account email (`rocksgimli@gmail.com`) so commits attribute correctly; nothing else about history changed.

**Agent moved to the new project** (without this, a frontend pointing at `gimli` would hit silent rooms — the old agent lives in the old project):
- `lk project add gimli` with the new URL/key pair; `livekit.toml` repointed to the new subdomain.
- `lk agent create --project gimli --secrets-file .env.secrets --region ap-south` — non-interactive mode needs an explicit region and a `livekit.toml` that does not carry the old agent id. The remote Docker build (models included) continues server-side.
- The agent registered under `bakar-agent` and answered a dispatch **3.5 s** after the build finished; subsequent joins 1.2 s (warm).

**Incident: e2e harnesses vs scale-to-zero.** `e2e_room`/`e2e_end` timed out waiting for the agent while token-carried dispatch joined in seconds. Root cause: the scripts created an **explicit dispatch for a room that did not exist yet**, and in this project the platform serves/wakes the agent via **token-carried dispatch** — the frontend's own path. All three e2e scripts now put the agent name on the join token (`with_room_config`, exactly like `/api/token`) instead of pre-created dispatches.

**Verification:** Murf key direct call → 200, 46 KB audio · Deepgram key direct call → 200 (project `rocksgimli@gmail.com's Project`) · `e2e_room` full round trip on the new project: greeting + the recast ("You went to the park yesterday, and you saw a big dog. What did the dog look like?") transcribed via Deepgram · `e2e_end`: recap payload valid, wins 1–3, no goodbye · ruff clean, 3 files formatted. `e2e_recap` not re-run today (same dispatch mechanism as `e2e_end`). The old project (`[previous-project]`) is untouched and can be deleted from the LiveKit dashboard when convenient.

**Next:** Vercel import (root dir `frontend`, 4 env vars: the new `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` + `AGENT_NAME=bakar-agent`), then Deployment Protection. The token endpoint remains unauthenticated by design; the in-memory limiter is in place.