# Voice QA script

Run this by hand after any change to `SYSTEM_PROMPT`, the model, or the voice. It takes about ten minutes. Automated tests cannot hear whether Bakar *feels* like a friend.

## Setup

- One browser tab, one speaker, no headphones required but recommended.
- Say things naturally, including hesitations. Do not perform.

## Script

| # | You say | Bakar should | Fail if |
|---|---|---|---|
| 1 | *(join silently)* | Greet within ~3 s and ask one easy question about your day | Waits silently, or opens with an introduction to itself |
| 2 | "I go to the park yesterday" | Use "went" in the reply without commenting on the error; ask a follow-up | Says "should be went", "mistake", or repeats the error back |
| 3 | "I… um… I don't know how to say…" | Offer a starter ("Try: 'It was…'") and wait | Fills the silence with a lecture, or asks a second question |
| 4 | *(say nothing for 10 s)* | Wait; at most one gentle prompt | Repeated prompting, or the agent starts monologuing |
| 5 | "How do I say this correctly?" | One precise fix, one example, then hands the turn back | Lists three rules, or keeps teaching |
| 6 | *(make the same grammar error three times)* | At most one focus is recorded; conversation continues | Corrects you each time, or the recap lists several focuses |
| 7 | Speak Hindi/Spanish for one turn | Replies in English and continues | Switches language immediately |
| 8 | "What's my pronunciation score?" | Says it can't score pronunciation, offers to repeat a word instead | Invents a number |
| 9 | "Okay, I have to go" | Two things you said (quoted), one thing to practise, one sentence to repeat | Generic "great job", or no recap card appears |
| 10 | *(after the card appears)* | Card shows wins + focus + drill; dismiss returns to the welcome screen | Card missing, empty, or blocks the control bar |

## Timing checks

- First audio after you stop speaking: **under ~1.2 s**. If it is slower, check `preemptive_generation` and the network, not the prompt.
- Barge-in: start talking while Bakar is speaking. It should yield within a word or two.

## Tone check (judgement call)

Read the transcript afterwards and ask three questions:

1. Did **you** talk more than Bakar?
2. Did Bakar ever make you feel tested?
3. Would you do this again tomorrow?

If any answer is no, the prompt is wrong — not the learner.

## Known-good transcript fragment

```
bakar: Hey — good to see you. What's the last thing that made you laugh?
you:   I see a video of a dog on a skateboard. I laugh a lot.
bakar: A dog on a skateboard — that would get me too. Was it a small dog?
you:   Yes, very small. He have a little hat.
bakar: The hat is the detail that makes it. Do you watch many dog videos?
```

Note what is absent: no "he *has*", no praise inflation, no second question. The recast rule is working when you cannot point to the moment you were corrected.
