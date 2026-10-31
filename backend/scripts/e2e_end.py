"""Verify the END CALL handshake: client publishes bakar.end, agent returns the card."""

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
END_TOPIC = "bakar.end"
RECAP_TOPIC = "bakar.recap"


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


async def main() -> None:
    room_name = f"bakar_end_{int(time.time())}"
    print(f"room: {room_name}")

    # Token-carried dispatch: the agent name rides on the join token, exactly
    # like the frontend's /api/token. LiveKit Cloud wakes the scale-to-zero
    # deployment on room creation; a pre-created explicit dispatch does not.
    token = (
        api.AccessToken(KEY, SECRET)
        .with_identity("e2e-end-user")
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
        if p.identity != "e2e-end-user":
            agent_here.set()

    @room.on("data_received")
    def _data(packet: rtc.DataPacket) -> None:
        nonlocal recap
        if packet.topic == RECAP_TOPIC:
            recap = json.loads(bytes(packet.data))

    await room.connect(URL, token)
    await asyncio.wait_for(agent_here.wait(), timeout=60)
    print("agent joined; waiting 12s for greeting…")
    await asyncio.sleep(12)

    source = rtc.AudioSource(RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    pcm = await asyncio.to_thread(
        murf_pcm, "I go to the park yesterday and I saw a very big dog with my sister."
    )
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

    print("waiting 10s for the reply, then pressing END CALL")
    await asyncio.sleep(10)

    await room.local_participant.publish_data(b"", topic=END_TOPIC, reliable=True)
    print("sent bakar.end")

    # A slow model can take longer than the reply to produce the card;
    # e2e_recap.py already waits 90s, and 20s turned slow closes into failures.
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and recap is None:
        await asyncio.sleep(0.5)

    await room.disconnect()

    print("\n--- recap ---")
    if recap is None:
        print("NO PACKET — handshake failed")
        raise SystemExit(1)
    print(json.dumps(recap, indent=2, ensure_ascii=False))
    print("\n  wins 1-3:", 1 <= len(recap["wins"]) <= 3)
    print(
        "  no goodbye used:",
        all("that is all" not in w["quote"].lower() for w in recap["wins"]),
    )


if __name__ == "__main__":
    asyncio.run(main())
