# Bakar

**A spoken-English companion for people who already know the language and freeze when they have to use it.**

Most learners don't need another lesson. They need ten minutes of talking to something that never grades them. Bakar is that: a friend who keeps the conversation going, absorbs mistakes instead of marking them, and hands back one small thing to practise.

```
you:  "I go to the park yesterday"
bakar: "You went yesterday? Was it busy?"
```

That is the whole product thesis in one exchange. The correction is inside the reply, not on top of it.

---

## How a session works

1. **Bakar speaks first.** A friend doesn't wait in silence — silence is what an under-confident speaker reads as judgement.
2. **You talk.** Turns are capped at two sentences and almost always end with a question.
3. **Mistakes are recast.** The correct form reappears naturally; nothing is labelled "wrong".
4. **One focus, maximum.** If a pattern keeps repeating, it is recorded — once. Everything else is let go.
5. **You leave with proof.** Two things you actually said, one thing to practise, one sentence to say again. Spoken *and* shown as a card.

## Architecture

Two services and a media server, no shared database:

```
Next.js (browser)                         Python agent (worker)
 ├─ /api/token ........ uuid room + dispatch   ├─ Deepgram nova-3  (ears)
 ├─ LiveKit client ..... mic + agent audio     ├─ gpt-4o-mini via LiveKit (brain)
 └─ recap card ......... bakar.recap topic     ├─ Murf Falcon      (voice)
                                               └─ 3 tools + session memory
                        LiveKit Cloud (rooms, dispatch, data)
```

The recap travels over the room's data channel — no second API, no second auth boundary, nothing persisted.

## Run it

```bash
# backend
cd backend
cp .env.example .env.local        # LIVEKIT_*, MURF_API_KEY, DEEPGRAM_API_KEY
uv sync
uv run python src/agent.py download-files   # first time only
uv run python src/agent.py dev

# frontend
cd frontend
cp .env.example .env.local        # LIVEKIT_*, AGENT_NAME=bakar-agent
pnpm install
pnpm dev
```

`AGENT_NAME` must match the agent's dispatch name (`bakar-agent`, set in `backend/src/agent.py`). If it is missing the token endpoint fails loudly rather than connecting you to an empty room.

## What's here

| Path | What it is |
|---|---|
| `backend/src/agent.py` | Persona, pipeline, three tools |
| `backend/src/bakar_state.py` | Session memory + recap payload (pure, unit-tested) |
| `backend/tests/` | State rules with no credentials; LLM-judged evals with them |
| `frontend/components/bakar/session-recap.tsx` | The card that closes the loop |
| `frontend/lib/recap.ts` | Defensive parser for the data packet |
| `backend/src/telephony/` | Phone channel — inbound is a practice line; outbound is a scheduler example |
| `docs/` | Plan, PRD, technical design, deploy guide, voice QA script |

## Design decisions worth knowing

- **No pronunciation score.** Deepgram returns words, not phonemes. Bakar can notice that a word was unclear and ask for it again; it cannot grade an "r". Anything stronger needs a dedicated assessment API (Phase 2 in `docs/PLAN.md`).
- **The focus cap is enforced in code**, not just in the prompt (`bakar_state.note_focus`). A model under conversational pressure will happily correct five things, and five corrections is a lesson.
- **English only.** The learner's first language is a crutch this product deliberately withholds, unless they ask twice.
- **Nothing is stored.** No database, no recording, no transcript persistence. The recap exists for the length of the session.

## Honest limitations

- The token endpoint is unauthenticated by design. It rate-limits per IP in memory only (20 requests/hour, per instance) — fine for local use; keep a public deployment private or behind Deployment Protection.
- No memory across sessions; a returning learner still starts fresh.
- Phone practice answers calls but has no scheduling yet.

## License

MIT — see `LICENSE`.
