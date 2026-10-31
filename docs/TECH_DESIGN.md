# Bakar — Technical Design (v0)

**Stack:** Next.js 15 (App Router) · LiveKit WebRTC · Python LiveKit Agents 1.4 · Deepgram Nova-3 · gpt-4o-mini via LiveKit inference (default; `BAKAR_LLM` switches provider) · Murf Falcon TTS.

---

## 1. Architecture

Bakar keeps the topology of the starter it grew from — two services, no shared database, LiveKit as the hub.

```
Browser (Next.js on Vercel)
  ├─ POST /api/token ......... mints a 15-min JWT, uuid room, server-side agent dispatch
  ├─ LiveKit client .......... joins room, publishes mic, renders agent audio
  └─ useDataChannel('bakar.recap') ... renders the recap card
                    │
              LiveKit Cloud (rooms, SFU, dispatch)
                    │
  Python agent worker (Docker / Railway)
  ├─ AgentServer + prewarmed Silero VAD
  ├─ AgentSession: Deepgram STT → LLM (build_llm()) → Murf TTS
  ├─ BakarAgent: persona, 3 tools, session state
  └─ publish_data('bakar.recap')
```

Why this shape:

- **No app server between the two services.** Voice never round-trips through Next.js; the token endpoint is the only server API.
- **State lives in the agent process**, scoped to one job. Nothing to provision for v0, nothing to leak.
- **The recap travels over the same room** as the audio, so there is no second channel to secure.

## 2. Agent design

### 2.1 Persona

`SYSTEM_PROMPT` is structured in five blocks so behaviour can be edited independently:

1. **Who you are** — a friend, not a teacher.
2. **Who you're talking to** — someone who knows more English than they believe.
3. **How you speak** — ≤2 sentences; one question per turn; warm, specific, unremarkable.
4. **How you help without stopping them** — recast, one focus, scaffold on silence, correct only when asked.
5. **What you never do** — forbidden words, multiple questions, unfounded pronunciation claims.

The rules are duplicated as code-level guardrails where they can be enforced (FR-4) rather than trusted to the model.

### 2.2 Tools

| Tool | Arguments | Side effect | Enforced rule |
|---|---|---|---|
| `note_focus` | `area`, `item`, `example` | Writes `state.focus` | Rejects a second call with an instruction to keep the first (FR-4) |
| `log_win` | `quote`, `why` | Appends to `state.wins` (max 3) | Keeps verbatim text; drops the 4th |
| `finish_session` | — | Builds recap, publishes data, returns spoken summary | Emits `bakar.recap` when the learner ends by voice |

All three return **strings**, because the model reads the return value as its next instruction context. A tool that raises would break the turn; a tool that returns guidance keeps the conversation alive.

### 2.3 Session state

```python
@dataclass
class BakarState:
    focus: Focus | None = None
    wins: list[Win] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
```

Stored as `self.state = BakarState()` on the `BakarAgent` instance (therefore per job). Not in `userdata`, so a handoff to another agent cannot silently inherit stale state.

### 2.4 Turn-taking

Learners pause mid-sentence. Defaults tuned for native speakers cut them off.

| Setting | Value | Reason |
|---|---|---|
| `min_endpointing_delay` | 0.8 s | Tolerates thinking pauses |
| `max_endpointing_delay` | 6.0 s | Still yields a turn eventually |
| `preemptive_generation` | `True` | Hides LLM+TTS latency behind the pause |
| `allow_interruptions` | `True` | The learner must be able to take the floor back |

### 2.5 Greeting

`Agent.on_enter()` calls `generate_reply()` with a one-line instruction ("greet warmly, ask one easy question about their day"). The starter waited silently for the user, which is exactly wrong for an anxious speaker — silence reads as judgement.

## 3. Frontend design

| File | Change |
|---|---|
| `app-config.ts` | Brand: name, title, description, accent `#C2410C` / dark `#FDBA74`, logo paths, button copy |
| `public/bakar-mark.svg`, `bakar-mark-dark.svg` | Square mark, legible at 24 px (the header renders `size-6`) |
| `components/app/welcome-view.tsx` | Promise-led copy, single CTA, privacy line replaces the starter's "need help?" footer |
| `components/agents-ui/blocks/.../agent-session-block.tsx` | Pre-connect line: *"Take your time — say anything."* Mounts `<SessionRecap />` |
| `components/bakar/session-recap.tsx` *(new)* | Card with wins / focus / drill, dismissible, motion sheet |
| `hooks/useRecap.ts` *(new)* | Wraps `useDataChannel('bakar.recap')`, decodes JSON, validates `version` |

The recap is **additive**: if the channel never fires, the session view is unchanged.

**Trigger:** the END button publishes an empty `bakar.end` packet and then waits up to 4 s for the `bakar.recap` packet before ending the session; the agent answers with the recap and a spoken goodbye. This exists because relying on the model to call `finish_session` was advisory in practice — it logged wins and then said goodbye without publishing. The tool is kept for learners who end the call by voice.

## 4. Data contract

Topic: `bakar.recap`. Payload: UTF-8 JSON, `< 2 KB`, `reliable: true`.

The client validates shape defensively (`version === 1`, arrays bounded, strings truncated) because a data packet is untrusted input even when it comes from our own agent.

## 5. Latency budget

| Stage | Target | Lever |
|---|---|---|
| End of speech → end of turn | 0.8–1.2 s | Endpointing + turn detector |
| Turn → first LLM token | 300–500 ms | gpt-4o-mini (default), short prompt |
| First token → first audio | 300–500 ms | Murf streaming + `text_pacing` |
| **p95 first audio** | **< 1.2 s** | Preemptive generation absorbs most of it |

## 6. Failure modes

| Failure | Behaviour |
|---|---|
| `publish_data` throws | Logged; agent still speaks the recap; UI shows nothing (FR-6 degradation) |
| Learner never speaks | Agent offers a starter once, then waits; no nagging |
| ASR returns garbage | Agent asks for a repeat instead of correcting a phantom error |
| Session ends before any win logged | Recap falls back to the learner's own transcript sentences; `wins` may still be empty — the UI must handle it |
| Token endpoint misconfigured | 500 with a named variable (inherited from the bug-fix pass) |

## 7. Testing

| Layer | What | How |
|---|---|---|
| Unit (py) | focus cap, win cap, recap builder, JSON schema; telephony helpers | `pytest tests/test_bakar_state.py tests/test_bugfixes.py` — no keys needed |
| Wiring (py) | session lifecycle and cross-artifact consistency | `pytest tests/test_agent_lifecycle.py tests/test_consistency.py` |
| Eval (py) | prompt behaviour: greeting, recast, refusal — LLM-as-judge | `pytest tests/test_agent.py` — needs `LIVEKIT_*` creds; skips without them |
| Unit (ts) | recap payload parsing, malformed input; bug-fix regression contracts | `node scripts/verify-recap.mjs` · `node scripts/verify-fixes.mjs` |
| Static | types, lint, format | `tsc --noEmit`, `eslint`, `prettier --check`, `ruff` |
| Build | production bundle | `pnpm build` |
| Live-room smoke (manual) | dispatch → greeting → recast → END → recap against real providers | `backend/scripts/e2e_end.py` / `e2e_recap.py` / `e2e_room.py` — full credentials + a running worker |
| Manual | 10-script voice QA (halting speech, L1 switch, explicit correction request) | checklist in `docs/VOICE_QA.md` |

What cannot be automated here: real ASR/TTS behaviour, barge-in feel, and prompt quality. Those need a human on a microphone; the prompt is therefore written to be edited, with each rule on its own line.

## 8. Security & privacy

- Token route: uuid rooms, server-side dispatch, `AGENT_NAME` required (fixed in the base repo).
- **Unauthenticated by design.** The route now rate-limits per IP in memory (20 requests/hour), but the counter is per instance — on serverless it throttles accidents, not abuse. Keep the deployment private / behind Deployment Protection; Phase 1 adds a signed session cookie + a shared-store limiter.
- No recording, no transcript storage, no analytics backend in v0. Recaps exist only in room memory.
- Provider data handling (Deepgram / the LLM provider / Murf) is governed by their terms; the UI copy must not claim more than "Bakar doesn't store your conversations".

## 9. Deployment

| Piece | Target | Notes |
|---|---|---|
| Frontend | Vercel | `LIVEKIT_*`, `AGENT_NAME` |
| Agent | Docker (Railway/Fly) | `download-files` at build; starts with the absolute-path CMD `/app/.venv/bin/python /app/src/agent.py start` |
| Media | LiveKit Cloud | One project; agent name `bakar-agent` |

Scaling note: one worker process handles concurrent jobs up to `num_idle_processes`; VAD is prewarmed per process, so cold starts cost one model load, not one per session.

## 10. Deliberate limitations

1. **No pronunciation scoring.** Deepgram gives words, not articulation. The agent can notice *clarity* ("say that once more") but cannot grade a phoneme. Anything stronger is Phase 2 with a dedicated assessment API.
2. **No memory across sessions.** A returning learner starts fresh; the persona compensates by asking what they practised last time, but it cannot know.
3. **English-only.** The learner's L1 is a crutch the product deliberately withholds.
