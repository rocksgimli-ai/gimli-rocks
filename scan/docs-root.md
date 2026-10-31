# Scan report — docs, CI, root scripts (Bakar monorepo)

**Scope (15 assigned files, all read in full):** `README.md`, `WORKLOG.md`, `AGENTS.md`, `docs/PRD.md`, `docs/PLAN.md`, `docs/TECH_DESIGN.md`, `docs/DEPLOY.md`, `docs/VOICE_QA.md`, `netlify.toml`, `start_app.sh`, `start_app.ps1`, `.github/workflows/backend-lint.yml`, `.github/workflows/backend-tests.yml`, `.github/workflows/frontend.yml`, `.gitignore`.

**Method / evidence tiers used below**

- **[D]** — verified by directly reading the assigned file (statement about what the doc *says*).
- **[L]** — file-layout fact verified by `ls`/`find` (existence of a path only; **content not read**).
- **[N]** — NOT verified in code; a doc claim that would need a code check (flagged per task instructions).
- **[X]** — external/general knowledge, not a repo fact (labeled, used only for defaults like port numbers).

Additional cheap, read-only cross-checks performed for §8 (existence/grep only, no project file modified): `backend/.env.example`, `frontend/.env.example`, `backend/.gitignore`, `frontend/.gitignore`, directory listings of `backend/`, `frontend/`, and targeted `find`/`grep`. Secrets files (`backend/.env.local`, `backend/.env.secrets`, `frontend/.env.local`) were deliberately **not opened**.

---

## 1) What the Bakar product is supposed to be (PRD + README)

**Bakar is a spoken-English practice companion** — "a spoken-English companion for people who already know the language and freeze when they have to use it" [D, README.md:3]. The thesis: ten minutes of talking to something that never grades you; corrections are absorbed via *recasting* (the correct form reappears inside a natural reply, never labeled "wrong"), demonstrated in the canonical exchange `"I go to the park yesterday"` → `"You went yesterday? Was it busy?"` [D, README.md:9-13].

Session rules (README "How a session works", lines 17-23) [D]:
1. Bakar speaks first (silence reads as judgement to an anxious speaker).
2. Turns capped at two sentences, almost always ending with a question.
3. Mistakes are recast, never marked.
4. One recorded focus maximum per session.
5. Session ends with a recap card ("You said" / "Practise next" / "Say it once more").

The PRD (`docs/PRD.md`, status "draft for build", last updated 2026-10-27, PRD.md:4-6) makes it normative [D]:
- **Personas:** primary "Priya" (29, Bengaluru, competent-but-silent), secondary "Marco", tertiary "Yuki" (PRD.md:13-23).
- **Principles:** learner talks > 60% of the time (agent < 40% spoken time), errors absorbed, one focus per session, silence allowed, "No score, ever", honest about limits (PRD.md:26-32).
- **Normative conversation rules** (PRD.md:54-63): ≤ 2 sentences/turn; ≥ 90% of turns end with a question/invitation; recast without meta-commentary; at most one focus (second `note_focus` attempt "rejected by the tool"); English only (switch after two explicit requests); forbidden words "wrong", "mistake", "incorrect", "error"; scaffold after ~6 s of silence, at most once per topic; recap "Exactly two or three wins, exactly one focus, exactly one drill sentence" (PRD.md:63).
- **11 functional requirements FR-1..FR-11** with acceptance criteria (PRD.md:67-79), incl. FR-4 (focus cap enforced in the tool, PRD.md:72) and FR-6 (two recap triggers: client `bakar.end` packet, or `finish_session` when the model closes by voice; PRD.md:74).
- **Recap data contract:** topic `bakar.recap`, reliable, `version: 1`, wins 2–3, focus exactly 1, payload < 2 KB (PRD.md:83-101).
- **NFRs:** p95 end-of-turn → first agent audio < 1.2 s; agent < 40% talk ratio; recap publish failure degrades to speech-only; keyboard-dismissible card; "cost of a coffee" per 10-min session (PRD.md:104-108).
- **Metrics:** console-only event log in v0, no backend (PRD.md:111-121). **Out of scope for v0:** pronunciation scores, accounts/history/streaks, curriculum, payments, non-English UI (PRD.md:124-130).

Architecture per README: two services + media server, no shared database — Next.js frontend (token endpoint, LiveKit client, recap card) and a Python agent worker (Deepgram nova-3 STT, Gemini 3.5 Flash-Lite LLM, Murf Falcon TTS, "3 tools + session memory"), joined by LiveKit Cloud; recap travels over the room data channel (README.md:27-38). "Nothing is stored. No database, no recording, no transcript persistence" (README.md:76). Honest limitations stated: unauthenticated token endpoint, no cross-session memory, no phone scheduling yet (README.md:78-82).

---

## 2) Current status and history per WORKLOG.md (chronological)

`WORKLOG.md` declares itself "Append-only. Newest entry at the bottom" with each entry recording what/why/how-verified [D, WORKLOG.md:3]. 17 entries, 2026-10-27 → 2026-10-31. The project is **functionally live on LiveKit Cloud as of 2026-10-31** [D, WORKLOG.md:377-385].

| When (entry header) | Line | What happened |
|---|---|---|
| 2026-10-27 10:12 — Phase 0 foundation | 7 | Created `S:\Bakar` seeded from `S:\Voice Agent Project\Copy of murf-livekit-starter-main for bug fix tests` (118 files, 3.84 MB); skipped `node_modules` copy; renamed pyproject/npm metadata to `bakar-agent`/`bakar`; **incident:** PowerShell 5.1 `Set-Content -Encoding UTF8` writes a BOM that breaks `tomllib` — rewritten BOM-less (WORKLOG.md:7-21). |
| 10:16 — Documents before code | 24 | Wrote PLAN → PRD → TECH_DESIGN in that order; key decisions: no pronunciation scoring in v0, one focus enforced in code, recap over LiveKit data channel (topic `bakar.recap`), no persistence (WORKLOG.md:24-37). |
| 10:20 — Backend | 40 | **API check against installed livekit-agents 1.4.5, not docs:** `turn_handling=` does not exist in 1.4.x (2.x API); used `min_endpointing_delay=0.8` / `max_endpointing_delay=6.0`. New `src/bakar_state.py` (no LiveKit imports; `Focus`, `Win`, `BakarState`, `build_recap()`, `spoken_summary()`). Rewrote `src/agent.py`: 5-block persona, `on_enter` greeting, three tools (`note_focus`, `log_win`, `finish_session`), dispatch name `bakar-agent`, voice `Anisha`. Verified: ruff clean, 13 state tests pass (WORKLOG.md:40-53, esp. 50). |
| 10:30 — Frontend | 56 | New: `lib/recap.ts` (defensive `parseRecap`), `hooks/useRecap.ts` (`useDataChannel('bakar.recap')`), `components/bakar/session-recap.tsx`, SVG marks. Changed: `app-config.ts` (accent `#C2410C`/`#FDBA74`), `welcome-view.tsx`, `layout.tsx`, `agent-session-block.tsx`, `lib/ids.ts` (prefixes `bakar_room_`/`bakar_user_`), telephony inbound persona. **Incident:** `<a href="/">` lint error fixed with `next/link`. Verified: tsc 0, eslint 0, prettier pass, `verify-recap.mjs` 9 passed, `verify-fixes.mjs` 11, `pnpm build` success (WORKLOG.md:56-76). |
| 10:38 — Visual check | 78 | Served prod build; home 200, SVG/OG 200, `POST /api/token` returns `bakar_room_…` + `bakar-agent`; header intentionally `hidden md:flex` (WORKLOG.md:78-90). |
| 10:42 — Eval suite adaptation | 92 | `pytest --collect-only` failed: old `test_agent.py` imported the now-removed `Assistant`. Made `BakarAgent.__init__(ctx=None, *, greet=True)` and guarded publish on `ctx is not None`; rewrote 3 LLM-judged evals. 27 collected, 24 credential-free pass (WORKLOG.md:92-102). |
| 10:45 — Final gates | 104 | Full gate table (ruff/format, 24 pytest, tsc 0, eslint 0, prettier, pnpm build, prod smoke). **Explicitly not verified:** live voice session, recap card with a real packet, phone line (WORKLOG.md:104-125). |
| 2026-10-27 17:47 — Live credentials | 127 | Checked each key independently: Deepgram 200, Murf 200 (65 KB PCM), LiveKit 200, **Selora `402 trial_not_activated`**. LLM decision: `build_llm()` provider switch — `BAKAR_LLM=livekit` (default, LiveKit inference gateway) / `BAKAR_LLM=selora` (OpenAI-compatible, ready). `pyproject.toml` gained the `openai` extra (WORKLOG.md:127-147, esp. 137). |
| 18:05 — First real session (no microphone) | 149 | Built `backend/scripts/e2e_room.py` (dispatches agent, synthesizes learner audio with Murf, records + transcribes agent reply with Deepgram). Product thesis verified end-to-end: recast "You saw a big dog yesterday?" with real STT/LLM/TTS (WORKLOG.md:149-164). |
| 18:30 — The recap, and four wrong theories | 166 | Recap card didn't appear. Hypotheses tried: tool cap (raised `max_tool_steps` 3→6), prompt ordering (reverted), unstable facts (`appears_verbatim()` rejects paraphrased quotes), goodbye counted as win (mode-aware `exclude_last`). **Actual root cause: orphaned job-runner processes** from worker restarts answered dispatches with stale code; killed seven orphans; lesson: on Windows kill the process *tree* (WORKLOG.md:166-191, esp. 171, 180). |
| 19:00 — Design change: the learner ends the call | 193 | `finish_session` was advisory (skipped in ~half of runs) → **closing became client-initiated**: END button publishes empty `bakar.end`, waits 1.2 s, disconnects; agent answers with recap + goodbye; `finish_session` kept for voice-ended sessions. `remember_history()` pulls user turns from `session.history`. Verified 3×; observed recap payload `{"version":1,"wins":[{...one win...}],"focus":null,"drill":null,"duration_s":27}` — focus/drill legitimately null in a 2-turn synthetic conversation (WORKLOG.md:193-221, esp. 196, 214). |
| 19:10 — Gates with live keys | 223 | 36 pytest passed incl. the 3 LLM-judged evals (first time with a live project). Still unverified: human voice session, recap card in a browser, phone line (WORKLOG.md:223-235). |
| 2026-10-28 20:10 — Deployability Vercel/Netlify | 237 | Constraint: only the frontend can be serverless. One code change: `outputFileTracingIncludes` in `next.config.ts` (serverless bundles don't include `public/`); first key `'/*'` silently traced zero public files — explicit route keys `'/'`, `'/opengraph-image'` fixed it, verified by parsing `.nft.json` not by exit code. Added `netlify.toml`, `backend/fly.toml` (no `[http_service]`), `backend/railway.toml` (DOCKERFILE builder, not nixpacks), `docs/DEPLOY.md`. **Not verified: an actual deploy** (no Vercel/Netlify/Fly CLI, no Docker on the machine) (WORKLOG.md:237-275, esp. 258-266, 272-275). |
| 2026-10-28 02:10 — Local beside deployment | 277 | **Dispatch-name collision risk:** LiveKit load-balances across all workers registered under one name, so a local worker would fight the deployed one. Fix: `AGENT_NAME` in `backend/src/agent.py` now env-driven (default `bakar-agent`); local dev uses `bakar-agent-dev`. Verified by actual registration logs for both values (WORKLOG.md:277-300). |
| 2026-10-29 08:30 — Rebrand Buckr → Bakar | 302 | Full rename incl. runtime identifiers: env vars `BUCKR_LLM*`→`BAKAR_LLM*`, topics `buckr.recap/end`→`bakar.*`, prefixes, package names, module `buckr_state.py`→`bakar_state.py`, component folder. 35 files changed, 0 old-brand occurrences left. Two forced rebuilds (venv trampoline paths, pnpm `virtualStoreDir`). `S:\MunshiJi` deliberately *not* renamed — it grew into its own product (CA/CPA study agent, `munshiji-agent`) (WORKLOG.md:302-353, esp. 319). |
| 2026-10-30 15:30 — Free-VPS hosting (Oracle/GCP) | 355 | Measured worker memory: **~1.1 GB resident idle** with models loaded → GCP e2-micro (1 GB) will OOM. ARM verified: every locked dep incl. `livekit-blingfire` 1.1.0 has cp313 aarch64 wheels. Region: LiveKit project is India South → worker should be `ap-mumbai-1`. Added `backend/docker-compose.yml` (restart unless-stopped, env_file .env, 2 GB OOM guard, 30 s grace, no ports) and DEPLOY.md §6. Verdict: "cannot run for free" is false (WORKLOG.md:355-375, esp. 368). |
| 2026-10-31 14:10 — LIVE on LiveKit Cloud | 377 | **Agent is cloud-hosted and verified end-to-end with no local worker.** `lk agent create --secrets-file .env.secrets` → deployment `CA_[redacted]` (project bakar, [previous-project], India South). First deploy failed at runtime: **CMD was missing "python"** and platform starts from `/` not the Dockerfile WORKDIR → fixed with absolute paths (`/app/.venv/bin/python /app/src/agent.py start`) and CWD-independent `.env.local` loading. Room test verified greeting → recast → END handshake → recap. Remaining: GitHub push → Netlify import (4 env vars) → Deployment Protection; "agent unavailable" toast and token rate limiter still pending (WORKLOG.md:377-385, esp. 381-383). |

**Net current status per the worklog:** core loop (greeting → recast → client-initiated END → recap card data) verified end-to-end with real providers, including from the cloud deployment; 33 backend tests passing post-rebrand; frontend gates green. Outstanding: human voice QA, browser rendering of the card with a live packet, phone line, public frontend deploy (Netlify), rate limiter + "agent unavailable" toast.

---

## 3) Plan vs built (docs/PLAN.md and docs/TECH_DESIGN.md claims vs expected code)

> Per task constraints I did **NOT** read backend/frontend source. Every item below marked **[N]** is a doc claim that the code is *expected* to satisfy and that a code-reading pass must confirm. Items marked **[L]** were only existence-checked.

### 3.1 docs/PLAN.md (build plan) [D for content]

- Thesis: fluency as by-product of use; three mechanisms — lower the stakes, maximise output, recast-don't-correct; frames the affective filter (Krashen) (PLAN.md:9, 13-21).
- v0 scope table (PLAN.md:27-33): persona + 3 tools (record focus / record win / end with recap), rebranded UI + recap card, inbound phone line as practice call, nothing persisted.
- Non-goals: phoneme scoring (Phase 2, needs dedicated assessment API), curriculum/levels/streaks/accounts/payments, text-chat-first, multilingual UI (PLAN.md:35-40).
- Five phases (PLAN.md:42-50): 0 = this build; 1 = session store/progress/resume; 2 = pronunciation assessment + minimal-pair drills; 3 = scheduled 2-minute phone-first calls; 4 = practice pairs/async voice notes.
- North-star metric: **minutes spoken per active user per week** (PLAN.md:54); supporting: agent talk ratio < 40%, median learner utterance > 8 s by session three, > 50% drill completion, +1 confidence self-report, D7 return after Phase 1 (PLAN.md:58-62).
- Risks (PLAN.md:64-72): ASR mishears → never correct from one low-confidence transcript; over-correction → hard cap "enforced by the tool, not just the prompt"; latency → preemptive generation + tuned endpointing; overselling hearing; L1 leakage → English-only rule.
- Definition of done v0 (PLAN.md:74-81): one-button start; greeting + one question + ≤2 sentences; natural recast; spoken recap + visible card with two wins and one focus; `pnpm build`, `tsc`, `eslint`, `ruff`, `pytest` pass; nothing recorded/stored.

**Plan-vs-built deltas visible from docs alone:** DoD item 4 says the card shows "two wins and one focus", but the only observed live recap (WORKLOG.md:214) had **one** win and **null** focus/drill; TECH_DESIGN itself allows empty wins (TECH_DESIGN.md:120). See §8 (inconsistency #3). DoD item 5 gates are all reported green in WORKLOG (10-45 and 19:10 entries), so the *test* half of the DoD is documented as met; the *behavioural* half (two wins + focus) is documented as not yet met in synthetic sessions.

### 3.2 docs/TECH_DESIGN.md — concrete code claims needing verification [all N unless noted]

| # | Doc claim (TECH_DESIGN.md) | Expected code location | Status |
|---|---|---|---|
| 1 | Stack: "Next.js 15 (App Router) · LiveKit WebRTC · Python LiveKit Agents 1.4 · Deepgram Nova-3 · Gemini 3.5 Flash-Lite · Murf Falcon" (line 3) | `frontend/package.json`, `backend/pyproject.toml`, `backend/src/agent.py` | [N] stack line; "Gemini" conflicts with WORKLOG/env example — see §8 #2 |
| 2 | 5-block `SYSTEM_PROMPT` (who you are / who you're talking to / how you speak / how you help / what you never do) (§2.1) | `backend/src/agent.py` | [N] |
| 3 | Tools table: `note_focus(area,item,example)` rejects a 2nd call with keep-the-first guidance (FR-4); `log_win(quote,why)` max 3, keeps verbatim, drops 4th; `finish_session()` builds+publishes recap, returns spoken summary; **all three return strings** (§2.2, lines 48-52) | `backend/src/agent.py`, `backend/src/bakar_state.py` | [N] (existence of `bakar_state.py` [L]) |
| 4 | `@dataclass BakarState(focus, wins, started_at)` stored on `self._state` per job, deliberately **not** in `userdata` (§2.3) | `backend/src/agent.py` | [N] |
| 5 | Turn-taking: `min_endpointing_delay=0.8`, `max_endpointing_delay=6.0`, `preemptive_generation=True`, `allow_interruptions=True` (§2.4, lines 72-77); WORKLOG:50 says 0.8/6.0 were applied after discovering `turn_handling=` doesn't exist in 1.4.5 | `backend/src/agent.py` | [N] |
| 6 | `Agent.on_enter()` greets with one warm question (§2.5) | `backend/src/agent.py` | [N] |
| 7 | END button publishes empty `bakar.end`, waits ~1.2 s, disconnects; agent replies on `bakar.recap`; `finish_session` kept for voice endings (line 96) | `frontend/components/agents-ui/.../agent-session-block.tsx` (+ agent `on_client_end` handler) | [N] |
| 8 | `hooks/useRecap.ts` wraps `useDataChannel('bakar.recap')`, validates `version === 1`, arrays bounded, strings truncated; recap is additive (§3) | `frontend/hooks/useRecap.ts`, `frontend/lib/recap.ts`, `frontend/components/bakar/session-recap.tsx` | [L] all three files exist; content [N] |
| 9 | Failure modes: publish throws → agent still speaks recap; recap with empty `wins` must be handled by UI; token endpoint 500 with named variable (§6, line 120) | agent + frontend | [N] |
| 10 | Testing layers incl. `pytest tests/test_bakar_state.py` (no keys) and `node scripts/verify-recap.mjs` (§7) | `backend/tests/`, `frontend/scripts/verify-recap.mjs` | [L] `test_bakar_state.py` and `verify-recap.mjs` exist (also `test_bugfixes.py`, `verify-fixes.mjs`, `conftest.py`, `e2e_*.py` — none mentioned in TECH_DESIGN) |
| 11 | Security: uuid rooms, server-side dispatch, `AGENT_NAME` required; still unauthenticated; Phase 1 adds signed cookie + per-IP limiter (§8) | `frontend/app/api/token/route.ts` | [N] |
| 12 | Deployment: agent via Docker (Railway/Fly), `download-files` at build, **`uv run --no-sync` at start** (line 147) | `backend/Dockerfile`, `fly.toml`, `railway.toml` | [L] files exist; **stale** vs WORKLOG.md:382-383 (CMD now absolute venv python path) — see §8 #4 |
| 13 | `fly.toml` `shared-cpu-1x`/1 GB, no `[http_service]`; `railway.toml` builder DOCKERFILE (DEPLOY/WORKLOG cross-claim) | `backend/fly.toml`, `backend/railway.toml` | [L] exist; content [N] |
| 14 | Latency budget p95 first audio < 1.2 s (§5) | behavior | [N] — cannot be verified statically |

Other documented-but-unverified mechanisms from WORKLOG: `max_tool_steps=6` (WORKLOG.md:171), `appears_verbatim()` transcript check, mode-aware `exclude_last` win exclusion (WORKLOG.md:180), `remember_history()` pulling from `session.history` (WORKLOG.md:200-202), env-driven `AGENT_NAME` default `bakar-agent` (WORKLOG.md:283-286; existence-documented in `backend/.env.example:45-53`), `outputFileTracingIncludes` with explicit route keys in `next.config.ts` (WORKLOG.md:249-253), CWD-independent `.env.local` loading (WORKLOG.md:383).

---

## 4) Deployment story (docs/DEPLOY.md + netlify.toml)

### 4.1 Topology [D]

Three pieces (DEPLOY.md:7-15): **Frontend** (Next.js 15, Vercel/Netlify), **Agent worker** (long-lived Python process holding a WebSocket — "The agent cannot go on Vercel or Netlify... Serverless functions sleep between requests and would deregister"; if only the frontend is deployed "the page loads, the token works, and the room is silent", DEPLOY.md:13), **LiveKit Cloud** (media plane, nothing to deploy). Minimal public deployment: Vercel-or-Netlify + Fly-or-Railway + existing LiveKit project (DEPLOY.md:15). Concrete project identifiers appear in the doc: `wss://[previous-project].livekit.cloud` (DEPLOY.md:29, 83) and owner `[previous-account-email]` (DEPLOY.md:3).

### 4.2 Documented options [D]

1. **Vercel (recommended), §1** — root dir `frontend`, 4 env vars, `vercel.json` intentionally absent; **"Make it private first"** via Deployment Protection because `/api/token` has no auth of its own and an open URL lets anyone spend Deepgram/Gemini/Murf budget (DEPLOY.md:38).
2. **Netlify, §2** — reads `netlify.toml`; same four env vars; "do not add `@netlify/plugin-nextjs` to `package.json`" (DEPLOY.md:49).
3. **Agent on LiveKit Cloud (managed), §3** — `lk cloud auth` / `lk agent create` / `lk agent deploy`; registered name becomes the dispatch name; provider keys live in the dashboard; hosted Sandbox URL available for demos (DEPLOY.md:53-71). Per WORKLOG this is the option actually executed on 2026-10-31 (deployment `CA_[redacted]`; WORKLOG.md:377-383) — though with `--secrets-file .env.secrets`, which DEPLOY.md §3 does not mention.
4. **Agent on Fly.io / Railway, §4** — Dockerfile downloads models at build; `fly secrets set ...`; "deliberately no `[http_service]`"; `BAKAR_LLM`/`BAKAR_LLM_MODEL` non-secret in `fly.toml [env]` (DEPLOY.md:74-93); Railway forced to `builder = "DOCKERFILE"` because "nixpacks cannot be relied on to provision `uv`" (DEPLOY.md:95-97).
5. **Own hardware, §5** — worker dials out on 443 only, no port forwarding; `backend/scripts/run-agent-watchdog.ps1` (exists [L]) auto-restarts in ~15 s, refuses a second worker against the same project, daily maintenance window, optional `git pull`+`uv sync` on start, logs to `backend/logs/watchdog-YYYYMMDD.log` (DEPLOY.md:99-113); includes `powercfg`/`schtasks` ONSTART install commands (DEPLOY.md:119-130); cost framing (~15–30 W, ₹100–150/month) and LiveKit free **Build** plan comparison (1 agent deployment + 1,000 agent session minutes/month) (DEPLOY.md:132-141).
6. **Free VPS (Oracle/GCP), §6** — measured ~1.1 GB idle footprint; Oracle ARM A1 "best" (ARM wheels verified for pinned deps), GCP e2-micro "will OOM"; region must be `ap-mumbai-1` (LiveKit project in India South; US VPS ≈ +100 ms one-way); `docker compose up -d --build`, nothing to open in the firewall; two-agents-on-one-VM pattern (MunshiJi as second service with different `AGENT_NAME`) (DEPLOY.md:143-183).
7. **Post-deploy verification, §7** — ordered checks (token curl → `registered worker` log → dispatch → END → recap card → SIP call); the 500 `{"error":"Server is missing AGENT_NAME"}` is intentional fail-loud behavior (DEPLOY.md:185-196).
8. **Env matrix, §8** (DEPLOY.md:199-210): frontend needs `LIVEKIT_URL/KEY/SECRET` + `AGENT_NAME`; agent needs the LiveKit trio + `DEEPGRAM_API_KEY` + `MURF_API_KEY`; `BAKAR_LLM(_MODEL)` and `SELORA_*` optional. **`GOOGLE_API_KEY` appears nowhere in DEPLOY.md** (grep across the file: zero hits) — see §8 #2.
9. **Security, §9** — `/api/token` "unauthenticated and unthrottled"; a real limiter needs a shared store (in-memory per-instance limiter would give false confidence on serverless); keys host-side only, only the minted 15-minute JWT leaves the server; `.env.local` gitignored (DEPLOY.md:213-218).
10. **What was verified, §10** — TOML parses, next.config tracing builds, **but "the Dockerfile itself is unchanged from the base project"** (DEPLOY.md:222) — stale vs the 2026-10-31 CMD fix (§8 #4).

### 4.3 netlify.toml [D]

- `[build]` base `frontend`, command `pnpm build`, publish `.next` (netlify.toml:10-12); `NODE_VERSION = "22"` (netlify.toml:15) — consistent with frontend.yml Node 22.
- `SECRETS_SCAN_OMIT_KEYS = "AGENT_NAME,LIVEKIT_URL"` with an inline justification: `AGENT_NAME` is intentionally client-embedded and the project subdomain appears in `livekit.toml`/docs; the LiveKit key/secret are not in the repo and stay scanned (netlify.toml:16-20). (The referenced `backend/livekit.toml` exists [L].)
- `[[plugins]] package = "@netlify/plugin-nextjs"` with the comment that without it "Netlify publishes .next as static files: pages 404 and the token API doesn't exist" (netlify.toml:22-26). Compatible with DEPLOY.md:49's "don't pin it in package.json" (declare in netlify.toml instead; WORKLOG.md:258-259 confirms the intent). **Netlify path is documented but never executed** — WORKLOG.md:385 still lists "Netlify import (4 env vars)" as remaining.

---

## 5) Voice QA methodology (docs/VOICE_QA.md) [D]

A **manual 10-minute script**, run "after any change to `SYSTEM_PROMPT`, the model, or the voice", because "Automated tests cannot hear whether Bakar *feels* like a friend" (VOICE_QA.md:3). Setup: one browser tab, one speaker, natural speech incl. hesitations — "Do not perform" (VOICE_QA.md:5-8).

- **10-row script table** (VOICE_QA.md:12-23), each row = input / "Bakar should" / "Fail if": (1) silent join → greet ≤ ~3 s + one easy question; (2) past-tense error → "went" recast with no meta-commentary; (3) halting speech → offer one starter and wait; (4) 10 s silence → at most one gentle prompt; (5) "How do I say this correctly?" → one fix + one example, hand back; (6) same error three times → at most one focus recorded; (7) speak Hindi/Spanish → reply in English; (8) "What's my pronunciation score?" → refuse to invent a number, offer a repeat; (9) "Okay, I have to go" → two verbatim quotes, one practice item, one repeat sentence; (10) after card → card shows wins+focus+drill, dismiss returns to welcome.
- **Timing checks** (VOICE_QA.md:25-28): first audio < ~1.2 s ("check `preemptive_generation` and the network, not the prompt"); barge-in should yield "within a word or two".
- **Tone check** (VOICE_QA.md:30-37): three judgement questions post-session (did you talk more; did you feel tested; would you return) — "If any answer is no, the prompt is wrong — not the learner."
- **Known-good transcript fragment** (VOICE_QA.md:40-47) demonstrating recasts with no correction markers ("Note what is absent: no 'he *has*', no praise inflation, no second question").

Note: the worklog repeatedly defers exactly these checks to this doc ("Those are the first three items in docs/VOICE_QA.md", WORKLOG.md:123-125, 233-235) — i.e., the doc is the pending human-QA backlog, and per the worklog none of its 10 rows has been executed yet [D].

---

## 6) CI pipelines (.github/workflows/) [D; workflow contents read in full]

Common shape of all three workflows: trigger `on: push` + `pull_request` to `main` only (backend-lint.yml:7-11; backend-tests.yml:3-7; frontend.yml:3-7); per-ref `concurrency` group with `cancel-in-progress: true` (content of each file); `defaults.run.working-directory` pinned per app.

| Workflow | Job | Runner | Steps |
|---|---|---|---|
| **backend-lint.yml** | `ruff` | ubuntu-latest | checkout@v4 → astral-sh/setup-uv@v5 (`version: "latest"`) → setup-python@v5 **3.12** → `uv sync --locked` → `uv run ruff check --output-format=github .` → `uv run ruff format --check --diff .` (backend-lint.yml:18-43) |
| **backend-tests.yml** | `pytest` | ubuntu-latest | same setup → `uv sync --locked` → `uv run pytest -v` with env `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` from GitHub **secrets** (backend-tests.yml:30-40) |
| **frontend.yml** | `lint-and-build` | ubuntu-latest | checkout@v4 → pnpm/action-setup@v4 **pnpm 9** → setup-node@v4 **Node 22** + pnpm cache keyed on `frontend/pnpm-lock.yaml` → `pnpm install --frozen-lockfile` → `pnpm lint` → `pnpm format:check` → `pnpm build` (frontend.yml:22-44) |

Observations:
- backend-lint.yml:3-5 carries a NOTE: "workflow files must live at the repository root (.github/workflows). The previous copies under backend/.github and frontend/.github were never executed by GitHub Actions." Those dead copies **still exist on disk**: `backend/.github/workflows/ruff.yml`, `backend/.github/workflows/tests.yml`, `frontend/.github/workflows/build-and-test.yaml` [L] — see §8 #5.
- `backend-tests.yml` assumes GitHub secrets exist; per WORKLOG the suite contains 24+ credential-free tests plus LLM-judged evals that need a live project. Whether the evals **skip or fail** without secrets (i.e., whether CI is red on a fork without secrets) depends on test code — [N], needs `backend/tests/` reading.
- Frontend CI runs eslint/prettier/build but **no explicit `tsc --noEmit` step** and **neither** `node scripts/verify-recap.mjs` **nor** `verify-fixes.mjs`, although TECH_DESIGN.md:126-127 lists `verify-recap.mjs` as the TS unit-test layer and WORKLOG used it as a gate. (Next.js build type-checks by default; whether `ignoreBuildErrors` is set in `next.config.ts` is [N].)
- CI Python floor is 3.12 (backend-lint.yml:34, backend-tests.yml:30); AGENTS.md:24 advertises "Python 3.10+" — not a conflict, but the CI is stricter.
- Netlify Node 22 (netlify.toml:15) matches frontend.yml Node 22. pnpm 9 in CI; `pnpm build` in Netlify uses the repo's package.json engine config (not read — [N]).

---

## 7) Startup scripts behavior and port allocation [D]

### start_app.sh (14 lines)
- If `livekit-server` exists: `livekit-server --dev &` (start_app.sh:4-5); else prints a warning and relies on configured `LIVEKIT_URL` (start_app.sh:7).
- Backgrounds `(cd backend && uv run python src/agent.py dev) &` and `(cd frontend && pnpm dev) &` (start_app.sh:10-11), then `wait` (start_app.sh:14) — all three share one terminal; Ctrl-C handling depends on the shell's job handling (not specified).
- **No checks for `uv` or `pnpm`** (only `livekit-server` is checked); does not run `uv sync`, `pnpm install`, `download-files`, or create `.env.local` — prerequisites are assumed.

### start_app.ps1
- `$ErrorActionPreference = "Stop"` (line 1); **hard-fails** if `uv` or `pnpm` missing (`throw "Missing required command: uv|pnpm"`, lines 9-14) — stricter than the bash version (behavioral asymmetry between the two scripts).
- Resolves repo root from the script path; starts **three separate PowerShell windows** with `-NoExit`: optional `livekit-server --dev` (lines 27-32, with the same warning fallback at :32), `uv run python src/agent.py dev` in `backend/` (35-37), `pnpm dev` in `frontend/` (39-41).
- Comment at lines 22-26 documents a PowerShell 5.1 quoting pitfall (paths with spaces truncated in `-ArgumentList`; solved via `-WorkingDirectory`) and preserves the pre-rename origin path "S:\Voice Agent Project\..." — consistent with WORKLOG.md:9's seed source.

### Port allocation
- **Neither script sets any port.** No `-p`/`PORT` anywhere in either script, `netlify.toml`, or the workflow files [D].
- Implicit defaults [X, external knowledge — not a repo fact]: `pnpm dev` (Next.js) serves on **3000**; `livekit-server --dev` listens on **7880** (plus UDP media range); the agent in `dev` mode is an outbound websocket **worker that listens on no TCP port** (it registers with LiveKit and receives jobs), so there is no port collision among the three processes by default.
- If `livekit-server` is absent, both scripts degrade gracefully to LiveKit Cloud via `LIVEKIT_URL` (start_app.sh:7, start_app.ps1:32) — i.e., a local media server is optional.
- Note: `agent.py dev` (worker) does not run `uv sync` first; AGENTS.md's run instructions treat `uv sync` / `download-files` as one-time manual steps (AGENTS.md:39-44), so a fresh clone + `start_app.*` without setup would fail in the backend window [N: exact failure mode depends on `uv run` behavior].

---

## 8) Inconsistencies between docs and repo reality (file:line evidence)

Tier legend: **[conflict]** = two repo artifacts disagree; **[stale]** = doc predates documented change; **[unverified]** = doc claim with no code evidence gathered (flagged, not asserted false).

1. **[conflict/stale] `AGENTS.md` describes the upstream starter, not Bakar.** It names the root `murf-livekit-starter/` (AGENTS.md:8) while README.md:1 titles the repo "Bakar"; it documents an `Assistant` class and `my_agent()` (AGENTS.md:34-35) that per WORKLOG.md:50 were replaced by the Bakar persona + `BakarAgent` (and WORKLOG.md:98 says the old evals broke because `Assistant` "no longer exists"); it lists "Google Gemini — LLM" as the stack LLM (AGENTS.md:28); it says tests live only in `backend/tests/test_agent.py` (AGENTS.md:63) while `backend/tests/` also contains `test_bakar_state.py`, `test_bugfixes.py`, `conftest.py` [L]; and it never mentions `bakar_state.py`, the recap card, `BAKAR_LLM`, or the e2e/watchdog scripts. AGENTS.md:128 still points tool-authors at the `Assistant` class.
2. **[conflict] Which LLM is "the brain" — three docs, two answers.** README.md:31 and TECH_DESIGN.md:3/21/109 say **Gemini 3.5 Flash-Lite**; AGENTS.md:28 says **Google Gemini**; but WORKLOG.md:127-147 documents the Selora `402 trial_not_activated` failure and a provider switch where **`BAKAR_LLM=livekit` (default) routes through LiveKit's inference gateway**, and `backend/.env.example:37-43` sets `BAKAR_LLM=livekit` + `BAKAR_LLM_MODEL=openai/gpt-4o-mini` with the comment "livekit (default) ... nothing beyond the LiveKit keys above is required" (backend/.env.example:37). Compounding it: `backend/.env.example:28-29` still says "For Gemini (default)" with an **uncommented** `GOOGLE_API_KEY=...` line — internally contradicting line 37 of the same file — and README.md:44 still lists `GOOGLE_API_KEY` in the required-env comment, while DEPLOY.md's env matrix (DEPLOY.md:199-210) has **no** `GOOGLE_API_KEY` row at all (grep of DEPLOY.md for `GOOGLE_API_KEY`: 0 hits). What `build_llm()` actually does is [N] (code not read).
3. **[conflict] Recap contract: "exactly 2–3 wins, exactly 1 focus, 1 drill" vs built behavior.** PRD.md:63 and PRD.md:101 make the recap shape normative ("Exactly two or three wins, exactly one focus, exactly one drill sentence"; "Rules: `wins` 2–3 items · `focus` exactly 1"), and PLAN.md:79's DoD expects "two wins and one focus". But TECH_DESIGN.md:120 admits "Recap uses the focus only; `wins` may be empty — the UI must handle it", and the only recorded live recap is `{"wins":[one win, "why": ""],"focus":null,"drill":null,"duration_s":27}` (WORKLOG.md:214), which the worklog itself calls legitimate ("focus/drill are legitimately null", WORKLOG.md:216-218). The PRD's normative contract and the shipped/observed behavior disagree; which side `bakar_state.py`/`session-recap.tsx` implement is [N].
4. **[stale] Deployment docs vs the 2026-10-31 container fix.** DEPLOY.md:222 states "the Dockerfile itself is unchanged from the base project", and TECH_DESIGN.md:147 says the agent starts via "`uv run --no-sync`". WORKLOG.md:382-383 supersedes both: the first cloud deploy failed because "CMD was missing 'python'... (my bug from the --no-sync edit)" and was fixed to **absolute paths** `/app/.venv/bin/python /app/src/agent.py start` plus CWD-independent `.env.local` loading. DEPLOY.md §4 (line 78: "starts the worker with `--no-sync`") and §10 were not updated after the fix.
5. **[conflict-with-reality] Dead CI copies the lint workflow's own note says were superseded.** backend-lint.yml:3-5 explains that workflow copies under `backend/.github` and `frontend/.github` "were never executed by GitHub Actions" — but they are still present: `backend/.github/workflows/ruff.yml`, `backend/.github/workflows/tests.yml`, `frontend/.github/workflows/build-and-test.yaml` [L]. Harmless to CI (GitHub ignores non-root locations, exactly as the note says) but misleading repo hygiene: a reader can believe backend tests are defined twice.
6. **[conflict] WORKLOG violates its own append-chronology.** Header: "Append-only. Newest entry at the bottom" (WORKLOG.md:3). The entry at WORKLOG.md:277 is stamped "2026-10-28 · 02:10" and sits *below* the "2026-10-28 · 20:10" entry at :237 — same-day timestamps in descending order. Either the 02:10 stamp is wrong (its content — a deployed worker already existing, per "While a deployed worker exists" reasoning — fits after the 20:10 deployability work, i.e. it is plausibly 2026-10-29 ~02:10) or it was appended late. [D on the ordering; the cause is unverified.]
7. **[conflict] `AGENT_NAME`: optional `my-agent` (AGENTS.md) vs required `bakar-agent` (everything else).** AGENTS.md:111: "`AGENT_NAME` (optional — set to `my-agent` for explicit dispatch)". frontend/.env.example documents `AGENT_NAME=bakar-agent` as required ("required" block comment; token fails loudly per README.md:56); DEPLOY.md:199-206 matrix lists `AGENT_NAME` ✅ for frontend. The starter value `my-agent` would dispatch to nothing.
8. **[stale] README's dispatch-name wording.** README.md:56 says the dispatch name is "`bakar-agent`, set in `backend/src/agent.py`" — true as the default, but since WORKLOG.md:283-286 (and `backend/.env.example:45-53`) `AGENT_NAME` is env-overridable precisely so a local worker can coexist with a deployed one; README omits the override.
9. **[unverified] Telephony agent names.** AGENTS.md:73-74 claims `agent_name="inbound-agent"` / `"outbound-agent"` in `telephony/{inbound,outbound}/agent.py`. README.md (What's here table) calls inbound "a practice line" and WORKLOG.md:68-69 says the inbound persona was rewritten to Bakar's. Whether the registered names were changed to match (and whether the inbound line is dispatched as `bakar-agent` or still `inbound-agent`) is [N] — and it matters, because dispatch names are load-bearing (WORKLOG.md:277-286).
10. **[unverified] FR enforcement locations.** PRD FR-4 (PRD.md:72) and PLAN.md:69 promise the focus cap is enforced by the *tool* (`bakar_state.note_focus`), FR-7's 6-second scaffold (PRD.md:75, PRD.md:62) presumably by prompt/timer, FR-10 no-persistence (PRD.md:78) is a negative claim. None checked in code [N]; WORKLOG asserts `note_focus`/win-cap live in `bakar_state.py` (WORKLOG.md:46-49) but that is the worklog's word, not code evidence.
11. **[unverified] Netlify behavior claim.** netlify.toml:22-24 asserts that without `@netlify/plugin-nextjs` "Netlify publishes .next as static files: pages 404 and the token API doesn't exist." Plausible and standard, but the Netlify path has never been executed (WORKLOG.md:272-275 "Not verified: an actual deploy"; still pending per WORKLOG.md:385) — the claim is documentation, not verified behavior.
12. **[minor] `.gitignore` is layered, not flat.** The root `.gitignore` (5 lines: `.env`, `.env.*`, `!.env.example`, `.DS_Store`) ignores env files at any depth (so `backend/.env.local` and `backend/.env.secrets` — which exists on disk [L] — are covered) but **not** `node_modules`, `.next`, `.venv`, `__pycache__`, or `logs/`; those are covered only by the nested `backend/.gitignore` (e.g. `KMS` line 7, `.venv` line 8, `logs/` line 35) and `frontend/.gitignore` (`/node_modules` line 5, `/.next/` line 14, `.env*` line 20). Net effect is correct, but the root file alone gives a false impression; also both nested files carry AI-assistant scratch entries (`.claude/`, `.codex/`, `.gemini/`, `.cursor/`) that AGENTS.md doesn't mention [D].
13. **[minor] Undocumented backend scripts.** `backend/scripts/` contains `e2e_end.py` and `e2e_recap.py` [L] beyond the WORKLOG-documented `e2e_room.py` (WORKLOG.md:151-152); neither doc nor worklog describes them, and TECH_DESIGN's test table (§7) doesn't list the e2e layer at all.
14. **[minor] Docs contain live infrastructure identifiers.** DEPLOY.md:3 (owner email), :29/:83 (`wss://[previous-project].livekit.cloud`), and WORKLOG.md:381 (deployment id `CA_[redacted]`) are committed to the repo. Not secrets, but they pin docs to one specific LiveKit project; `netlify.toml:16-20` even anticipates secrets-scanning friction from the subdomain.

---

## 9) Verification status summary

- **Verified by reading (D):** everything quoted above about what the 15 assigned files say; plus `backend/.env.example`, `frontend/.env.example`, both nested `.gitignore` files.
- **Verified by existence only (L):** `backend/src/{agent.py,bakar_state.py}`, `backend/src/telephony/{inbound/agent.py, outbound/agent.py, outbound/dial.py}`, `backend/tests/{conftest.py,test_agent.py,test_bakar_state.py,test_bugfixes.py}`, `backend/scripts/{e2e_room.py,e2e_end.py,e2e_recap.py,run-agent-watchdog.ps1}`, `backend/{Dockerfile,fly.toml,railway.toml,docker-compose.yml,livekit.toml,taskfile.yaml}`, `backend/{KMS/,logs/}`, `frontend/{lib/recap.ts,lib/ids.ts,hooks/useRecap.ts,components/bakar/session-recap.tsx,scripts/verify-recap.mjs,scripts/verify-fixes.mjs,next.config.ts}`, `backend/.env.secrets` (not opened), stale `*/.github/workflows/*` copies.
- **Not verified (needs a code pass, per task scope):** SYSTEM_PROMPT structure; tool implementations and string-return convention; `BakarState` placement (`self._state` vs `userdata`); endpointing/preemptive/allow_interruptions values; `bakar.end`/`bakar.recap` wire format on both sides; END-button 1.2 s handshake in `agent-session-block.tsx`; `parseRecap` bounds/clamps; token route's fail-loud 500; `build_llm()` provider selection (Gemini vs livekit gateway vs Selora); telephony agent names; `next.config.ts` `outputFileTracingIncludes`; `fly.toml`/`railway.toml`/`docker-compose.yml` contents; whether LLM-judged evals skip or fail without credentials in CI; whether `next build` type-checking is disabled anywhere.

## 10) Suggested next steps (if a deeper pass is wanted)

1. Read `backend/src/agent.py` + `backend/src/bakar_state.py` against TECH_DESIGN §2.1-2.5 and PRD FR-1..FR-9 (items 1-5, 10 above) — highest value: resolves the LLM identity conflict (#2) and the recap-contract conflict (#3) at the code level.
2. Read `frontend/app/api/token/route.ts`, `frontend/lib/recap.ts`, `frontend/hooks/useRecap.ts`, `frontend/components/bakar/session-recap.tsx`, and the END-button handler against TECH_DESIGN §3/§6/§8 (items 7-9, 11).
3. Read `backend/tests/` to answer the CI secrets question (#5's neighbor: skip vs fail without LIVEKIT secrets).
4. Read `backend/{Dockerfile,fly.toml,railway.toml,docker-compose.yml}` and update DEPLOY.md §4/§10 + TECH_DESIGN.md:147 to the post-2026-10-31 CMD reality (#4).
5. Decide whether `AGENTS.md` should be rewritten for Bakar (it currently onboards contributors to the wrong class names, env vars, and agent names) and whether the dead `.github` copies under `backend/`/`frontend/` should be deleted (#1, #5, #7).
