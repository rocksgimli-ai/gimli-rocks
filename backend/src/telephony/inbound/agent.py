"""Inbound telephony agent — answers incoming phone calls.

A caller dials your phone number, your SIP provider forwards the call to LiveKit,
and LiveKit's dispatch rule routes it to this agent by name ("inbound-agent").

Run it with:

    uv run python src/telephony/inbound/agent.py dev

See src/telephony/README.md for the trunk and dispatch rule setup.
"""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit import api, rtc
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

logger = logging.getLogger("inbound-agent")

load_dotenv(Path(__file__).resolve().parents[3] / ".env.local")

# Optional — a phone number to transfer callers to when they ask for a human.
# Leave unset and the transfer tool politely declines instead.
TRANSFER_TO_NUMBER = os.getenv("TRANSFER_TO_NUMBER")

# How long to wait for the caller to appear before releasing the worker slot.
PARTICIPANT_TIMEOUT_S = 30.0

# Change this prompt to change what your phone agent does.
SYSTEM_PROMPT = """You are Bakar on the phone: a warm friend who helps the caller practise speaking English. They already understand more than they believe, so keep them talking rather than testing them. Ask one easy question at a time, speak in one or two short sentences, and never point out mistakes — if they say something ungrammatical, use the correct form naturally in your reply and carry on. Never say "wrong", "mistake" or "error". If they ask for a human, use the transfer_to_human tool. When the call is clearly over, use the end_call tool."""

# The first thing the caller hears when they pick up.
GREETING = "Hey — Bakar here. What's one thing that happened today?"

# Deliberately duplicated from src/agent.py: each telephony folder is
# self-contained so it can be copied out and hacked on independently.
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


class InboundAgent(Agent):
    def __init__(self, ctx: JobContext, caller_identity: str | None) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.ctx = ctx
        # The LiveKit participant identity of the caller — needed to transfer them.
        self.caller_identity = caller_identity

    @function_tool
    async def transfer_to_human(self, context: RunContext) -> str:
        """Transfer the caller to a human colleague.

        Use this when the caller explicitly asks for a person, or when you cannot
        help them with their request.
        """
        if not TRANSFER_TO_NUMBER or not self.caller_identity:
            return "Transfers are not available on this line. Offer to take a message instead."

        # Tell the caller before transferring — the SIP transfer cuts off the audio.
        await context.session.generate_reply(
            instructions="Tell the caller you're connecting them to a colleague now."
        )

        logger.info("transferring caller to %s", TRANSFER_TO_NUMBER)
        try:
            await self.ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=self.ctx.room.name,
                    participant_identity=self.caller_identity,
                    transfer_to=f"tel:{TRANSFER_TO_NUMBER}",
                    play_dialtone=True,
                )
            )
        except Exception:
            logger.exception("transfer failed")
            return "The transfer did not go through. Apologize and offer to take a message."

        return "Transferred."

    @function_tool
    async def end_call(self, context: RunContext) -> str:
        """Hang up the call.

        Use this only once the caller has said goodbye or the conversation is clearly over.
        """
        # Let the agent finish its closing line before the call drops.
        await context.session.generate_reply(
            instructions="Say a short, warm goodbye to the caller."
        )

        logger.info("ending call")
        await self.ctx.api.room.delete_room(
            api.DeleteRoomRequest(room=self.ctx.room.name)
        )
        return "Call ended."


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


def caller_phone_number(participant: rtc.RemoteParticipant) -> str | None:
    """The caller's phone number, if this participant arrived over SIP.

    LiveKit puts the caller ID in a participant attribute. Browser participants
    (i.e. anyone testing from the frontend) will not have it.
    """
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return None
    return participant.attributes.get("sip.phoneNumber")


@server.rtc_session(agent_name="inbound-agent")
async def inbound_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Join the room first so we can read the caller's details before greeting them.
    await ctx.connect()

    try:
        # A job whose caller never arrives must not hold a worker slot forever.
        participant = await asyncio.wait_for(
            ctx.wait_for_participant(), timeout=PARTICIPANT_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        logger.warning(
            "no participant joined within %ss, ending job", PARTICIPANT_TIMEOUT_S
        )
        ctx.shutdown("no participant joined")
        return

    phone_number = caller_phone_number(participant)
    logger.info(
        "inbound call answered",
        extra={"caller": phone_number or "unknown", "identity": participant.identity},
    )

    # Same voice pipeline as src/agent.py — see that file for the annotated version.
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="multi"),
        llm=build_llm(),
        tts=murf.TTS(
            voice="Anisha",
            style="Conversation",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        min_endpointing_delay=0.8,
        max_endpointing_delay=6.0,
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        max_tool_steps=6,
    )

    await session.start(
        agent=InboundAgent(ctx, participant.identity),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                # BVCTelephony is tuned for the narrow frequency range of phone audio.
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    # Speak first — the caller dialled you, so they expect to be greeted.
    await session.say(GREETING, allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(server)
