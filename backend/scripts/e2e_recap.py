"""End-to-end recap test: trigger the closing turn and capture the data packet."""

from __future__ import annotations

import asyncio
import json
import os
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

AGENT_NAME = os.getenv("AGENT_NAME", "bakar-agent")
RATE = 24000
STEP_MS = 20
TOPIC = "bakar.recap"


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
                "sample_rate": RATE,
            }
        ).encode(),
        headers={"api-key": MURF_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


async def say(source: rtc.AudioSource, text: str) -> None:
    pcm = await asyncio.to_thread(murf_pcm, text)
    print(f"  you: {text!r}")
    step = RATE * 2 * STEP_MS // 1000
    for offset in range(0, len(pcm), step):
        chunk = pcm[offset : offset + step].ljust(step, b"\x00")
        await source.capture_frame(
            rtc.AudioFrame(
                data=chunk,
                sample_rate=RATE,
                num_channels=1,
                samples_per_channel=step // 2,
            )
        )
        await asyncio.sleep(STEP_MS / 1000)


async def main() -> None:
    room_name = f"bakar_recap_{int(time.time())}"
    print(f"room: {room_name}")

    # Token-carried dispatch: the agent name rides on the join token, exactly
    # like the frontend's /api/token. LiveKit Cloud wakes the scale-to-zero
    # deployment on room creation; a pre-created explicit dispatch does not.
    token = (
        api.AccessToken(KEY, SECRET)
        .with_identity("e2e-recap-user")
        .with_name("E2E user")
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)])
        )
        .with_ttl(timedelta(minutes=5))
        .to_jwt()
    )

    room = rtc.Room()
    recap: dict | None = None
    agent_here = asyncio.Event()

    @room.on("participant_connected")
    def _pc(p: rtc.RemoteParticipant) -> None:
        if p.identity != "e2e-recap-user":
            print("agent joined:", p.identity)
            agent_here.set()

    @room.on("data_received")
    def _data(packet: rtc.DataPacket) -> None:
        nonlocal recap
        if packet.topic != TOPIC:
            return
        try:
            recap = json.loads(bytes(packet.data))
            print("recap packet received")
        except Exception as exc:
            print("bad recap packet:", exc)

    await room.connect(URL, token)
    await asyncio.wait_for(agent_here.wait(), timeout=60)
    print("waiting 12s for the greeting…")
    await asyncio.sleep(12)

    source = rtc.AudioSource(RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    await say(
        source, "I go to the park yesterday and I saw a very big dog with my sister."
    )
    await asyncio.sleep(9)
    await say(source, "Okay, that is all for today. I have to go now. Thank you.")

    deadline = time.monotonic() + 90
    started = time.monotonic()
    while time.monotonic() < deadline and recap is None:
        await asyncio.sleep(1)
        waited = int(time.monotonic() - started)
        if waited % 10 == 0:
            print(f"  …waiting for recap ({waited}s)")

    await room.disconnect()

    print("\n--- recap ---")
    if recap is None:
        print("NO PACKET on", TOPIC)
        raise SystemExit(1)
    print(json.dumps(recap, indent=2, ensure_ascii=False))
    print("\nchecks:")
    print("  version == 1:", recap.get("version") == 1)
    print("  wins 1-3:", 1 <= len(recap.get("wins", [])) <= 3)
    print("  single focus:", recap.get("focus") is not None)
    print("  drill present:", recap.get("drill") is not None)


if __name__ == "__main__":
    asyncio.run(main())
