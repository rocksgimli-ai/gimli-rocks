"""Bakar — a spoken-English companion.

The learner already knows more English than they believe. This agent exists to
keep them talking: short turns, recasts instead of corrections, one thing to
practise, and a recap they can see.

Run it with:

    uv run python src/agent.py dev
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    llm,
    room_io,
)
from livekit.plugins import deepgram, murf, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from bakar_state import END_TOPIC, RECAP_TOPIC, BakarState

logger = logging.getLogger("bakar")


# Resolve relative to this file: hosted runtimes start the container from a
# different working directory than the Dockerfile's WORKDIR.
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env.local")

# The dispatch name. The frontend must expose the same value as AGENT_NAME,
# otherwise the token carries no dispatch and the room stays silent.
# Override it (AGENT_NAME=bakar-agent-dev) to run a local worker beside a
# deployed one: LiveKit load-balances jobs across every worker registered
# under the same name, so identical names means unpredictable routing.
AGENT_NAME = os.getenv("AGENT_NAME", "bakar-agent")

SYSTEM_PROMPT = """You are Bakar: a warm, patient friend who helps people speak English with confidence.

WHO YOU ARE TALKING TO
Someone who already understands more English than they believe. They freeze because they are afraid of sounding foolish, not because they lack words. Your job is to keep them talking, not to test them.

HOW YOU SPEAK
- One or two short sentences per turn. Almost every turn ends with a question or an invitation.
- Warm, specific, ordinary. No inflated praise ("Amazing!", "Perfect!") and no corporate tone.
- Talk about the thing they just said, not about their English.
- Never mention grammar rules, levels, scores or lessons unless they ask.

HOW YOU HELP WITHOUT STOPPING THEM
- Recast, don't correct. If they say "I go yesterday", answer "You went yesterday — was it busy?" and continue. Never point out the change.
- One focus per session. Pick at most one pronunciation point or grammar pattern, and only if it keeps repeating. Let everything else go.
- If a word is unclear, ask them to say it once more, then use it correctly in your next sentence.
- If they stall, offer a sentence starter ("Try: 'It was...'") and wait. Never fill a silence with a lecture.
- If they ask to be corrected, give one precise fix and one example, then hand the turn back.

WHAT YOU NEVER DO
- Never say "wrong", "mistake", "incorrect" or "error".
- Never ask two questions at once.
- Never switch to their first language unless they ask twice.
- Never claim to judge pronunciation precisely. You hear clarity, not phonemes.

THE SHAPE OF A SESSION
Open with something easy and specific about their day. Follow whatever they care about.

CLOSING — in this order
1. While you talk, not at the end: call log_win two or three times when they say something well, quoting their sentence word for word. Call note_focus once for the single clearest issue you notice — one occurrence is enough, you do not need a pattern. These notes are what the recap is built from.
   Before you call finish_session, check: if you have not called note_focus yet and you noticed anything at all about their English, call it now — even once is enough. The learner leaves with nothing to practise otherwise.
2. The moment they signal they are finished ("I have to go", "that's all", "bye"), call finish_session. Do not wait for another turn.
3. finish_session returns your closing lines. Say them: two things they actually said, one thing to practise, one example to repeat.
4. Then stop talking. Do not start a new topic.
"""

DEFAULT_LIVEKIT_MODEL = "openai/gpt-4o-mini"
DEFAULT_SELORA_MODEL = "claude-haiku-4-5"


def build_llm() -> llm.LLM | inference.LLM:
    """Pick the brain.

    `BAKAR_LLM=selora` uses any OpenAI-compatible gateway (Selora) — activate
    the account first, or every turn fails with 402. The default routes through
    LiveKit's inference gateway, which needs nothing beyond the project keys.
    """
    provider = os.getenv("BAKAR_LLM", "livekit").strip().lower()

    if provider == "selora":
        model = os.getenv("BAKAR_LLM_MODEL") or DEFAULT_SELORA_MODEL
        logger.info("llm=selora model=%s", model)
        return openai.LLM(
            model=model,
            api_key=os.getenv("SELORA_API_KEY"),
            base_url=os.getenv("SELORA_BASE_URL", "https://api.selora.lol/v1"),
        )

    model = os.getenv("BAKAR_LLM_MODEL") or DEFAULT_LIVEKIT_MODEL
    logger.info("llm=livekit-inference model=%s", model)
    return inference.LLM(model=model)


GREETING_INSTRUCTIONS = (
    "Greet them like a friend who is glad to see them, then ask one easy, specific "
    "question about their day. Two short sentences. Do not introduce yourself as an "
    "AI or as a teacher."
)


class BakarAgent(Agent):
    """Per-job agent: owns the conversation and the session's small memory."""

    def __init__(self, ctx: JobContext | None = None, *, greet: bool = True) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.ctx = ctx
        self._greet = greet
        self.state = BakarState()

    def on_user_transcribed(self, event: object) -> None:
        """Keep every final user sentence for the recap fallback."""
        if getattr(event, "is_final", False):
            self.state.add_transcript(getattr(event, "transcript", ""))

    async def on_enter(self) -> None:
        if not self._greet:
            # Eval harnesses drive the first turn themselves; a spontaneous
            # greeting would interleave with the scripted input.
            return
        # The starter waited silently for the user. Silence is exactly what an
        # under-confident speaker reads as judgement, so Bakar speaks first.
        self.session.generate_reply(instructions=GREETING_INSTRUCTIONS)

    @function_tool
    async def note_focus(
        self,
        context: RunContext,
        area: Literal["pronunciation", "grammar", "vocabulary", "fluency"],
        item: str,
        example: str,
    ) -> str:
        """Record the single thing this learner should practise after the session.

        Use this at most once per conversation, and only for a pattern that keeps
        coming back. Do not teach the item now — it is for the closing recap.

        Args:
            area: Which kind of issue this is.
            item: The focus in a few words, e.g. "th in 'three'" or "past tense".
            example: One short, natural sentence that demonstrates it.
                It must be a clean, correct sentence you write yourself
                (e.g. "I went to the park yesterday."), never a copy of
                a transcript fragment that may have been misheard.
        """
        accepted, message = self.state.note_focus(area, item, example)
        logger.info("focus %s: %s", "accepted" if accepted else "rejected", item)
        return message

    @function_tool
    async def log_win(
        self,
        context: RunContext,
        quote: str,
        why: str,
    ) -> str:
        """Keep something the learner actually said well, word for word.

        Record two or three of these across the session — a full sentence, a
        natural phrase, a tense they got right without help. Quote them exactly;
        do not tidy the grammar.

        Args:
            quote: Their sentence, copied word for word. Do not tidy the
                grammar and do not paraphrase — this text is shown back to them.
                Never log a goodbye, a thank-you or a one-word answer.
            why: A short reason it worked, e.g. "past tense, unprompted".
        """
        accepted, message = self.state.log_win(quote, why)
        logger.info("win %s", "accepted" if accepted else "rejected")
        return message

    @function_tool
    async def finish_session(self, context: RunContext) -> str:
        """End the session and send the learner their recap card.

        You MUST call this exactly once, as soon as the learner signals they are
        finished — before you say goodbye, and before recording anything else.
        It publishes the card they see on screen and returns the closing lines
        you should say. If you skip it, the session ends with no recap at all.
        """
        self.remember_history()
        self.state.mark_closing()
        if self.state.recap_sent:
            return "The recap has already been sent. Just say goodbye."

        # Claim the recap before the await: END pressed while this coroutine is
        # suspended must not publish a second card. If the publish fails, hand
        # the claim back so the other closing path can still deliver the card.
        self.state.recap_sent = True
        if not await self.publish_recap():
            self.state.recap_sent = False
        return self.state.spoken_summary()

    def remember_history(self) -> None:
        """Pull user turns out of the session history.

        The STT event is the primary source, but it is not guaranteed to fire
        before the session closes; the chat history always has the turns.
        """
        try:
            items = self.session.history.items
        except Exception:
            return

        for item in items:
            if getattr(item, "role", None) != "user":
                continue
            content = getattr(item, "content", None)
            if isinstance(content, list):
                text = " ".join(part for part in content if isinstance(part, str))
            else:
                text = content if isinstance(content, str) else ""
            if text.strip():
                self.state.add_transcript(text)

    async def publish_recap(self) -> bool:
        """Send the recap packet. Never raises: a missing card must not end a call."""
        if self.ctx is None:
            return False
        try:
            await self.ctx.room.local_participant.publish_data(
                json.dumps(self.state.build_recap(), ensure_ascii=False),
                topic=RECAP_TOPIC,
                reliable=True,
            )
            return True
        except Exception:
            logger.exception("failed to publish the recap")
            return False

    async def on_client_end(self) -> None:
        """END CALL: send the card, then say goodbye.

        The model cannot be trusted to call finish_session every time (it was
        advisory in practice), so the learner's own hang-up is the trigger.
        """
        if self.state.recap_sent:
            return
        # END button: the last thing they said was ordinary speech.
        logger.info("client ended the session")
        self.remember_history()
        logger.info(
            "recap: %d transcript(s), %d logged win(s)",
            len(self.state.transcripts),
            len(self.state.wins),
        )
        self.state.mark_closing(exclude_last=False)
        # Same claim-before-await as finish_session: only one closing path may
        # publish the card, and a failed publish hands the claim back.
        self.state.recap_sent = True
        if not await self.publish_recap():
            self.state.recap_sent = False
        self.session.generate_reply(
            instructions="Say a short, warm goodbye. Do not start a new topic."
        )


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def bakar_agent(ctx: JobContext) -> None:
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session = AgentSession(
        # Ears: multilingual nova-3 copes with accented English without forcing
        # the learner into one locale.
        stt=deepgram.STT(model="nova-3", language="multi"),
        # Brain: provider chosen by env, see build_llm().
        llm=build_llm(),
        # Voice: warm Indian English, matching the primary learner persona.
        tts=murf.TTS(voice="Anisha", style="Conversation", text_pacing=True),
        # Turn detection plus generous bounds: learners pause mid-sentence, and
        # interrupting them is the fastest way to make them stop talking.
        turn_detection=MultilingualModel(),
        min_endpointing_delay=0.8,
        max_endpointing_delay=6.0,
        vad=ctx.proc.userdata["vad"],
        # Generate while they are still finishing, so the reply feels immediate.
        preemptive_generation=True,
        # The closing turn logs two wins, the focus, and then publishes the recap:
        # four tool calls. The default cap of 3 dropped the last one, so no card
        # ever appeared.
        max_tool_steps=6,
    )

    agent = BakarAgent(ctx)
    # If the model forgets to log a win, the recap still quotes the learner.
    session.on("user_input_transcribed", agent.on_user_transcribed)

    end_tasks: list[asyncio.Task[None]] = []

    def _on_data(packet: rtc.DataPacket) -> None:
        logger.debug("data packet topic=%r", packet.topic)
        if packet.topic == END_TOPIC:
            end_tasks.append(asyncio.create_task(agent.on_client_end()))

    ctx.room.on("data_received", _on_data)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    await ctx.connect()

    # Let a just-spawned END handler finish before the job tears down.
    if end_tasks:
        await asyncio.gather(*end_tasks, return_exceptions=True)


if __name__ == "__main__":
    cli.run_app(server)
