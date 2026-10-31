# Bakar — Product Requirements Document (v0)

**Status:** draft for build
**Owner:** product
**Last updated:** 2026-10-27

---

## 1. Problem statement

Competent-but-silent English speakers avoid speaking because every attempt feels like an exam. They already understand most of what they hear and read; they cannot retrieve it fast enough under social pressure. The bottleneck is **confidence and reps**, not curriculum.

**Product promise:** ten minutes of talking to someone who never grades you, after which speaking feels slightly less dangerous.

## 2. Users

### Primary — "Priya", 29, Bengaluru
Reads and writes English all day (Slack, docs, email). In meetings she rehearses sentences in her head, then says them too late. She has never been told she is bad at English; she has simply concluded she is "not a speaker". She will not buy a course. She might talk to something for ten minutes on a Tuesday night.

**Job:** *When I have to speak English tomorrow, help me get through ten minutes tonight without feeling stupid — so I stop avoiding it.*

### Secondary — "Marco", 34, São Paulo
Intermediate, good grammar, weak listening. Wants to be understood on a trip, not to pass a test. Responds well to topics, badly to drills.

### Tertiary — "Yuki", 26, Tokyo
Large passive vocabulary, slow output, high fear of mistakes. Needs long silences tolerated.

## 3. Principles

1. **The learner talks more than the agent.** Target: agent < 40% of spoken time.
2. **Errors are absorbed, not surfaced.** A recast is a reply, not a correction.
3. **One focus per session.** Two corrections is a lesson; one is a gift.
4. **Silence is allowed.** A pause is thinking, not failure.
5. **No score, ever.** Nothing in the UI or the speech implies a grade.
6. **Honest about limits.** The agent hears clarity, not phonemes.

## 4. Experience

### 4.1 First session (storyboard)

| Step | What the learner sees / hears | Requirement |
|---|---|---|
| 1 | Welcome: *"Speak English like you already can."* One button: **Start talking** | No signup, no level test |
| 2 | Agent, ~1 s after joining: *"Hey — good to see you. What's the last thing that made you laugh?"* | FR-1 |
| 3 | Learner answers haltingly. Agent: *"A dog on a scooter — that's a good one. Where were you?"* | FR-2, FR-3 |
| 4 | Learner says "I go to the park yesterday". Agent: *"You went yesterday? Was it busy?"* | FR-3 |
| 5 | Learner stalls for 8 s. Agent: *"Try: 'It was…' — take your time."* | FR-7 |
| 6 | Learner asks "how do I say this?" Agent gives one fix + one example, then hands the turn back | FR-4 |
| 7 | Learner says "okay, I have to go". Agent: two verbatim wins, one focus, one sentence to repeat | FR-5, FR-6 |
| 8 | A card appears: **You said** (2 quotes) · **Practise next** (1 item, 1 example) · **Say it once more** | FR-6 |

### 4.2 Conversation rules (normative)

| Rule | Requirement |
|---|---|
| Length | ≤ 2 sentences per turn; ≥ 90% of turns end with a question or invitation |
| Recast | Corrected form appears in the agent's reply with no meta-commentary ("you should say", "the correct way is") |
| Correction on request | One precise fix, one example, then return the turn |
| Focus | At most one recorded focus per session; a second attempt is rejected by the tool |
| Language | English only; switch only after two explicit requests |
| Forbidden words | "wrong", "mistake", "incorrect", "error" |
| Silence | After ~6 s of no speech following a prompt, offer a sentence starter — at most once per topic |
| Recap | Two or three wins and one focus when warranted; per the data contract (§6) the card tolerates fewer — wins may be drawn from the learner's own sentences, focus and drill may be null |

## 5. Functional requirements

| ID | Requirement | Acceptance criteria |
|---|---|---|
| **FR-1** | Agent speaks first on join | Within 3 s of the room becoming active, the agent produces one greeting + one open question |
| **FR-2** | Turn discipline | Sampled over 20 turns: no turn exceeds 2 sentences; ≥ 18 end in a question/invitation |
| **FR-3** | Recast | Given "I go yesterday", the reply contains "went" and does **not** contain "should", "correct", "mistake" |
| **FR-4** | Focus cap | Calling `note_focus` twice returns an error string instructing the agent to keep the first focus; session state holds exactly one |
| **FR-5** | Wins | `log_win` stores up to 3 quotes; the recap shows them only verbatim (paraphrases are discarded); when none survive, it quotes the learner's own transcript sentences |
| **FR-6** | Recap | Two triggers publish JSON on `bakar.recap`: the learner pressing END (client sends `bakar.end`, agent replies with the card) and `finish_session` when the model closes by voice. UI renders the card within 2 s; dismissing it returns to the welcome view; wins are verbatim or drawn from the learner's own transcripts |
| **FR-7** | Scaffold | If no transcript follows a prompt for 6 s, the agent offers a starter; never more than once per topic |
| **FR-8** | Language | Agent replies in English when addressed in another language; switches only after two explicit requests |
| **FR-9** | Tone | No forbidden words in any agent output; no claims of phoneme-level assessment |
| **FR-10** | Privacy | No audio recording, no transcript persistence, no database writes |
| **FR-11** | Phone | Inbound call answers with the same persona and the same rules; greeting ≤ 2 sentences |

## 6. Recap data contract

Published on LiveKit data channel, topic `bakar.recap`, `reliable: true`.

```json
{
  "version": 1,
  "wins": [
    { "quote": "I went to the park with my sister", "why": "past tense, no prompting" }
  ],
  "focus": {
    "area": "pronunciation",
    "item": "th in 'three'",
    "example": "I have three brothers."
  },
  "drill": { "sentence": "I have three brothers.", "hint": "tongue between the teeth, then a soft 'r'" },
  "duration_s": 512
}
```

Rules: `wins` 0–3 items — logged wins quoted verbatim, falling back to the learner's own transcript sentences when the model logs none (the goodbye utterance is excluded when the session ends by voice) · `focus` at most 1, `null` when none was recorded · `drill` present only when `focus` is set, derived from it · all strings bounded (quote 240 / item 120 / example 200 chars) · payload < 2 KB · unknown fields ignored by the client (`version` guards future changes).

## 7. Non-functional requirements

- **Latency:** p95 time from end-of-turn to first agent audio < 1.2 s.
- **Talk ratio:** agent < 40% of session speech time (measured from transcript durations in Phase 1).
- **Robustness:** if the recap publish fails, the agent still speaks the recap; the UI simply shows nothing.
- **Accessibility:** recap card is keyboard-dismissible; contrast ≥ 4.5:1 for body text.
- **Cost:** a 10-minute session should stay within the STT+LLM+TTS budget of a coffee.

## 8. Metrics and events

| Event | When | Properties |
|---|---|---|
| `session_started` | room connected | `room_id` (uuid, not persisted) |
| `turn_completed` | agent turn ends | `agent_sentences`, `duration_ms` |
| `focus_recorded` | tool call | `area` |
| `recap_shown` | UI renders card | `wins`, `has_drill` |
| `session_ended` | disconnect | `duration_s`, `turns` |

v0 logs these to the browser console only (no backend). Phase 1 moves them server-side.

## 9. Out of scope for v0

- Pronunciation scores and phoneme feedback.
- Accounts, history, streaks, badges.
- Curriculum or lesson plans.
- Payments.
- Non-English UI.

## 10. Open questions

1. Voice: `Anisha` (en-IN, warm) vs a neutral en-US voice — depends on the primary market.
2. Do we persist recaps locally (localStorage) so a learner can see yesterday's focus? Cheap, but changes the privacy story.
3. Should the drill be spoken by the agent first (model) or attempted by the learner first (harder, better)?
4. Phone line: same persona, or a shorter "two-minute check-in" format?
