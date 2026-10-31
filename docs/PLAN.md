# Bakar — build plan

> A spoken-English companion for people who already know the language and freeze when they have to use it.

## 1. The problem

Adults who studied English for a decade still go quiet in a meeting. Their grammar is serviceable and their vocabulary is larger than they think; what fails is **retrieval under social pressure**. They are not missing knowledge — they are missing permission to be imperfect in public.

Existing tools optimise the wrong variable. Quizzes, streaks, level badges and pronunciation scores all measure *knowledge* and, in doing so, make every sentence a test with a grade attached. That raises what Krashen called the affective filter: anxiety that blocks production even when competence is present.

## 2. Thesis

If a learner talks for ten minutes a day to something that never grades them, fluency improves as a *by-product of use* rather than as a prerequisite for it. The companion's only job is to keep the turn alive, absorb errors without ceremony, and hand back one small thing worth practising.

Three mechanisms carry the product:

1. **Lower the stakes.** No score, no level, no "wrong". Errors are absorbed, not flagged.
2. **Maximise output.** The agent speaks less than the learner. Every turn ends with an invitation to talk.
3. **Recast, don't correct.** The correct form reappears naturally inside the reply ("Oh, you *went* yesterday — how was it?"). Explicit correction happens only when asked.

This is the difference between a tutor and a friend. A tutor's turn is a verdict; a friend's turn is a question.

## 3. Scope for v0

A browser voice companion on the existing LiveKit pipeline, plus the smallest possible loop around it:

| Area | v0 |
|---|---|
| Persona | Friend, behaviourally specified (turn length, recasting, scaffolding, one focus) |
| Tools | Record a focus · record a win · end with a recap |
| UI | Rebranded welcome + session, recap card after the conversation |
| Phone | Inbound line repurposed as a practice call; outbound left as an example |
| Data | Nothing persisted; recap lives for the session only |

## 4. Non-goals

- **Phoneme-level pronunciation scoring.** Deepgram returns words, not articulation. Claiming otherwise would be dishonest; real scoring needs a dedicated assessment API (Phase 2).
- Curriculum, levels, streaks, accounts, payments.
- Text chat as the primary mode (it exists, but the loop is voice).
- Multilingual UI. The learner's L1 is deliberately not offered as a crutch.

## 5. Phases

| Phase | Content | Why now |
|---|---|---|
| **0 — this build** | Brand, persona, tools, recap card, phone practice line | Proves the core loop end to end |
| 1 | Session store, progress over time, resume a topic | Turns a demo into a habit |
| 2 | Pronunciation assessment behind a tool; minimal-pair drills from real scores | The feature people *think* they want |
| 3 | Scheduled 2-minute calls, phone-first practice | Removes the "open an app" step |
| 4 | Practice pairs, async voice notes | Social pressure, inverted: accountability instead of judgement |

## 6. Success metrics

**North star:** minutes spoken per active user per week. Not sessions, not streaks — minutes with the microphone open.

Supporting:

- Agent talk ratio **< 40%** of session audio.
- Median learner utterance **> 8 s** by session three.
- Sessions ending with the 60-second drill completed: **> 50%**.
- Self-reported confidence (1–5 before/after): **+1 or better** for returning users.
- D7 return rate (after Phase 1 adds persistence).

## 7. Risks

| Risk | Mitigation |
|---|---|
| ASR mishears an accent, agent "corrects" a non-error — trust collapses instantly | Never correct from one low-confidence transcript; ask for a repeat instead |
| Over-correction turns the friend back into a tutor | Hard cap: one focus per session, enforced by the tool, not just the prompt |
| Latency makes the friend feel like a machine | Preemptive generation, ≤2-sentence turns, endpointing tuned for slower speech |
| The product oversells what it can hear | Copy and prompt never claim phoneme-level accuracy |
| Learner speaks their L1 and the agent follows | English-only rule; switch only after two explicit requests |

## 8. Definition of done (v0)

1. A new user can open the page, press one button, and be in a conversation within one second of speaking.
2. The agent greets first, asks one question, and never exceeds two sentences.
3. Saying something ungrammatical produces a natural recast, not a correction.
4. Ending the conversation produces a spoken recap *and* a visible card showing the learner's wins — logged verbatim or, if none were logged, drawn from their own sentences — plus the focus when one was recorded.
5. `pnpm build`, `tsc`, `eslint`, `ruff` and `pytest` all pass.
6. Nothing is recorded, stored or sent anywhere beyond the real-time providers.
