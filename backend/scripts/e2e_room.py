"""End-to-end room test without a human microphone.

Dispatches the agent into a fresh room, publishes a synthesized learner
sentence as microphone audio, records whatever the agent says back, and
transcribes it with Deepgram so the result can be read in a terminal.

    uv run python scripts/e2e_room.py "I go to the park yesterday and I see a big dog"
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from livekit import api, rtc

load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")

URL = os.environ["LIVEKIT_URL"]
KEY = os.environ["LIVEKIT_API_KEY"]
SECRET = os.environ["LIVEKIT_API_SECRET"]
MURF_KEY = os.environ["MURF_API_KEY"]
DEEPGRAM_KEY = os.environ["DEEPGRAM_API_KEY"]

AGENT_NAME = os.getenv("AGENT_NAME", "bakar-agent")
SAMPLE_RATE = 24000
FRAME_MS = 20

USER_TEXT = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "I go to the park yesterday and I see a big dog"
)


def murf_pcm(text: str) -> bytes:
    req = urllib.request.Request(
        "https://global.api.murf.ai/v1/speech/stream",
        data=json.dumps(
            {
                "text": text,
                "model": "FALCON",
                "voice_id": "Matthew",
                "style": "Conversation",
                "format": "pcm",
                "sample_rate": SAMPLE_RATE,
            }
        ).encode(),
        headers={"api-key": MURF_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def wav(pcm: bytes) -> bytes:
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


def transcribe(pcm: bytes) -> str:
    if len(pcm) < SAMPLE_RATE:  # under half a second of audio
        return "(no audio captured)"
    req = urllib.request.Request(
        "https://api.deepgram.com/v1/listen?model=nova-3&punctuate=true&smart_format=true",
        data=wav(pcm),
        headers={"Authorization": f"Token {DEEPGRAM_KEY}", "Content-Type": "audio/wav"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = json.load(resp)
    return (
        body["results"]["channels"][0]["alternatives"][0]["transcript"] or "(silence)"
    )


async def main() -> None:
    room_name = f"bakar_e2e_{int(time.time())}"
    print(f"room: {room_name}")

    # Token-carried dispatch: the agent name rides on the join token, exactly
    # like the frontend's /api/token. LiveKit Cloud wakes the scale-to-zero
    # deployment on room creation; a pre-created explicit dispatch does not.
    token = (
        api.AccessToken(KEY, SECRET)
        .with_identity("e2e-user")
        .with_name("E2E user")
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)])
        )
        .with_ttl(timedelta(minutes=5))
        .to_jwt()
    )

    room = rtc.Room()
    agent_audio = bytearray()
    tasks: list[asyncio.Task[None]] = []
    last_agent_audio = 0.0
    agent_joined = asyncio.Event()

    @room.on("participant_connected")
    def _joined(participant: rtc.RemoteParticipant) -> None:
        print("participant joined:", participant.identity)
        if participant.identity != "e2e-user":
            agent_joined.set()

    @room.on("track_subscribed")
    def _track(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO or participant.identity == "e2e-user":
            return

        async def pump() -> None:
            nonlocal last_agent_audio
            stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
            async for event in stream:
                agent_audio.extend(event.frame.data)
                last_agent_audio = time.monotonic()

        # Keep a reference: a bare create_task can be garbage collected mid-flight.
        tasks.append(asyncio.create_task(pump()))

    await room.connect(URL, token)
    print("connected as e2e-user")

    await asyncio.wait_for(agent_joined.wait(), timeout=45)
    print("agent in room; waiting for greeting…")

    # Let the greeting play out: wait until the agent has been quiet for 2s.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        if last_agent_audio and time.monotonic() - last_agent_audio > 2:
            break
    greeting_bytes = len(agent_audio)
    print(f"greeting captured: {greeting_bytes / (SAMPLE_RATE * 2):.1f}s of audio")

    # Publish the learner's sentence as microphone audio, paced in real time.
    pcm = await asyncio.to_thread(murf_pcm, USER_TEXT)
    source = rtc.AudioSource(SAMPLE_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    print(f"speaking: {USER_TEXT!r} ({len(pcm) / (SAMPLE_RATE * 2):.1f}s)")

    step = SAMPLE_RATE * 2 * FRAME_MS // 1000
    for offset in range(0, len(pcm), step):
        chunk = pcm[offset : offset + step]
        if len(chunk) < step:
            chunk = chunk + b"\x00" * (step - len(chunk))
        await source.capture_frame(
            rtc.AudioFrame(
                data=chunk,
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=step // 2,
            )
        )
        await asyncio.sleep(FRAME_MS / 1000)

    print("waiting for the reply…")
    reply_start = len(agent_audio)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        if (
            len(agent_audio) > reply_start
            and last_agent_audio
            and time.monotonic() - last_agent_audio > 2.5
        ):
            break

    reply = bytes(agent_audio[reply_start:])
    print(f"reply captured: {len(reply) / (SAMPLE_RATE * 2):.1f}s")

    await room.disconnect()

    print("\n--- greeting transcript ---")
    print(await asyncio.to_thread(transcribe, bytes(agent_audio[:greeting_bytes])))
    print("\n--- reply transcript ---")
    print(await asyncio.to_thread(transcribe, reply))


if __name__ == "__main__":
    asyncio.run(main())
