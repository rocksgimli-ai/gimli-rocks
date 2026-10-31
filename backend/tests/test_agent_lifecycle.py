"""Lifecycle tests for the two closing paths, with fakes only — no network.

finish_session (model-initiated) and on_client_end (END button) must together
publish exactly one recap card, even when they race. The room and session are
faked with SimpleNamespace objects, so these tests run offline in milliseconds.
"""

import asyncio
import json
from types import SimpleNamespace

from agent import BakarAgent
from bakar_state import RECAP_TOPIC


def _fake_ctx(published: list[tuple[str, str]]) -> SimpleNamespace:
    """A JobContext stand-in whose room delivers publish_data into a list."""

    async def publish_data(payload: str, *, topic: str, reliable: bool) -> None:
        published.append((topic, payload))

    return SimpleNamespace(
        room=SimpleNamespace(
            local_participant=SimpleNamespace(publish_data=publish_data)
        )
    )


def _fake_session(user_turns: list[str]) -> tuple[SimpleNamespace, list[str]]:
    """An AgentSession stand-in: chat history plus a generate_reply recorder."""
    replies: list[str] = []

    def generate_reply(*, instructions: str) -> None:
        replies.append(instructions)

    session = SimpleNamespace(
        history=SimpleNamespace(
            items=[SimpleNamespace(role="user", content=turn) for turn in user_turns]
        ),
        generate_reply=generate_reply,
    )
    return session, replies


async def test_publish_recap_without_room_returns_false() -> None:
    agent = BakarAgent(ctx=None)
    assert await agent.publish_recap() is False


async def test_finish_session_without_room_hands_the_claim_back() -> None:
    """The publish fails (ctx is None), so the claim must not latch: the END
    path stays able to deliver the card, and a retry simply tries again."""
    agent = BakarAgent(ctx=None)

    summary = await agent.finish_session(None)

    assert summary  # non-empty closing instructions for the model
    assert agent.state.recap_sent is False

    again = await agent.finish_session(None)
    assert again  # the retry does not crash or stall


async def test_finish_session_latches_only_after_a_successful_publish() -> None:
    published: list[tuple[str, str]] = []
    agent = BakarAgent(ctx=_fake_ctx(published))

    summary = await agent.finish_session(None)
    assert summary
    assert agent.state.recap_sent is True
    assert [topic for topic, _ in published] == [RECAP_TOPIC]

    second = await agent.finish_session(None)
    assert "already been sent" in second
    assert len(published) == 1  # the second call must not send a duplicate card


async def test_on_client_end_publishes_once_and_says_goodbye(monkeypatch) -> None:
    published: list[tuple[str, str]] = []
    session, replies = _fake_session(["I went to the park yesterday"])
    monkeypatch.setattr(BakarAgent, "session", property(lambda self: session))

    agent = BakarAgent(ctx=_fake_ctx(published))
    await agent.on_client_end()

    assert agent.state.recap_sent is True
    assert "I went to the park yesterday" in agent.state.transcripts
    assert [topic for topic, _ in published] == [RECAP_TOPIC]
    assert json.loads(published[0][1])["version"] == 1
    assert len(replies) == 1  # exactly one goodbye instruction


async def test_concurrent_closing_paths_publish_at_most_once(monkeypatch) -> None:
    """END pressed while finish_session is suspended must not double-send."""
    session, _replies = _fake_session(["I went to the park yesterday"])
    monkeypatch.setattr(BakarAgent, "session", property(lambda self: session))

    agent = BakarAgent(ctx=_fake_ctx([]))
    calls: list[int] = []

    async def slow_publish() -> bool:
        await asyncio.sleep(0.05)
        calls.append(1)
        return True

    monkeypatch.setattr(agent, "publish_recap", slow_publish)

    await asyncio.gather(agent.finish_session(None), agent.on_client_end())

    assert len(calls) == 1  # the second closing path saw the claim and backed off
