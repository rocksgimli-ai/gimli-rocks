"""Tests for the rules that make Bakar a companion rather than a quiz.

These import no LiveKit modules, so they run in well under a second and need no
credentials.
"""

import json

import pytest

from bakar_state import (
    MAX_WINS,
    RECAP_VERSION,
    BakarState,
    _clip,
)


def test_first_focus_is_accepted() -> None:
    state = BakarState()
    accepted, message = state.note_focus(
        "pronunciation", "th in 'three'", "I have three brothers."
    )
    assert accepted is True
    assert state.focus is not None
    assert "three" in message


def test_second_focus_is_rejected_and_the_first_survives() -> None:
    """One focus per session — the core anti-lecture rule (FR-4)."""
    state = BakarState()
    state.note_focus("grammar", "past tense", "I went to the park.")
    accepted, message = state.note_focus("vocabulary", "commute", "I commute by bus.")

    assert accepted is False
    assert "already chose a focus" in message
    assert state.focus is not None
    assert state.focus.item == "past tense"


def test_unknown_focus_area_is_rejected() -> None:
    state = BakarState()
    accepted, message = state.note_focus("spelling", "silent letters", "knight")
    assert accepted is False
    assert "Unknown area" in message
    assert state.focus is None


def test_wins_are_capped() -> None:
    state = BakarState()
    for index in range(MAX_WINS):
        assert state.log_win(f"quote {index}", "clear sentence")[0] is True

    accepted, message = state.log_win("one too many", "should be dropped")
    assert accepted is False
    assert "three wins" in message
    assert len(state.wins) == MAX_WINS


def test_recap_shape_is_stable() -> None:
    state = BakarState()
    state.note_focus("fluency", "fillers", "I mean, it was fine.")
    state.log_win("I went to the park with my sister", "past tense, unprompted")

    recap = state.build_recap()

    assert recap["version"] == RECAP_VERSION
    assert recap["focus"]["area"] == "fluency"
    assert recap["drill"]["sentence"] == "I mean, it was fine."
    assert recap["wins"][0]["quote"].startswith("I went to the park")
    assert isinstance(recap["duration_s"], int)
    assert recap["duration_s"] >= 0


def test_recap_without_focus_or_wins_is_valid() -> None:
    """A session can end before anything was recorded; the UI must cope."""
    recap = BakarState().build_recap()
    assert recap["focus"] is None
    assert recap["drill"] is None
    assert recap["wins"] == []


def test_recap_is_small_enough_for_a_data_packet() -> None:
    state = BakarState()
    state.note_focus("pronunciation", "x" * 500, "y" * 500)
    for _ in range(MAX_WINS):
        state.log_win("z" * 500, "w" * 500)

    payload = json.dumps(state.build_recap(), ensure_ascii=False)
    assert len(payload.encode("utf-8")) < 2048


@pytest.mark.parametrize(
    ("area", "expected"),
    [
        ("pronunciation", "Slowly first"),
        ("grammar", "three times"),
        ("vocabulary", "different word"),
        ("fluency", "without stopping"),
    ],
)
def test_drill_hint_matches_the_area(area: str, expected: str) -> None:
    state = BakarState()
    state.note_focus(area, "item", "example sentence.")
    assert expected in state.build_recap()["drill"]["hint"]


def test_spoken_summary_quotes_the_learner() -> None:
    state = BakarState()
    state.log_win("It was really funny", "spoke without prompting")
    summary = state.spoken_summary()
    assert "It was really funny" in summary
    assert "recap card is already on their screen" in summary


def test_clip_collapses_whitespace_and_caps_length() -> None:
    assert _clip("  a   b \n c ", 20) == "a b c"
    clipped = _clip("word " * 100, 40)
    assert len(clipped) == 40
    assert clipped.endswith("…")


def test_duplicate_transcripts_are_dropped_wherever_they_reappear() -> None:
    """The same sentence captured twice (STT event + history pull) must
    survive only once, even when the copies are not back to back."""
    state = BakarState()
    state.add_transcript("I saw a big dog with my sister")
    state.add_transcript("It was really nice.")
    state.add_transcript("I saw a big dog with my sister")

    assert state.transcripts == [
        "I saw a big dog with my sister",
        "It was really nice.",
    ]


def test_recap_falls_back_to_the_learners_own_words() -> None:
    """A model that forgets log_win must not produce an empty card."""
    state = BakarState()
    state.add_transcript("Hi")
    state.add_transcript(
        "I go to the park yesterday and I saw a big dog with my sister"
    )

    recap = state.build_recap()

    assert len(recap["wins"]) == 1
    assert "big dog" in recap["wins"][0]["quote"]


def test_short_transcripts_are_not_used_as_wins() -> None:
    state = BakarState()
    state.add_transcript("Yes")
    state.add_transcript("Okay thanks")
    assert state.build_recap()["wins"] == []


def test_logged_wins_win_over_the_fallback() -> None:
    """A verbatim logged win keeps its reason; the raw transcript is not used."""
    state = BakarState()
    state.add_transcript(
        "I go to the park yesterday and I saw a big dog with my sister"
    )
    state.log_win("I saw a big dog with my sister", "natural delivery")

    wins = state.build_recap()["wins"]
    assert len(wins) == 1
    assert wins[0]["quote"] == "I saw a big dog with my sister"
    assert wins[0]["why"] == "natural delivery"


def test_paraphrased_model_quote_is_rejected() -> None:
    """The model dropped a word once; the card must never show a sentence the
    learner did not say."""
    state = BakarState()
    state.add_transcript(
        "I go to the park yesterday and I saw a very big dog with my sister"
    )
    state.log_win(
        "I go to the park yesterday and I a very big dog with my sister", "past tense"
    )

    wins = state.build_recap()["wins"]
    assert len(wins) == 1
    assert "saw a very big dog" in wins[0]["quote"]


def test_verbatim_model_quote_is_kept_with_its_reason() -> None:
    state = BakarState()
    state.add_transcript(
        "I go to the park yesterday and I saw a very big dog with my sister"
    )
    state.log_win("I saw a very big dog with my sister", "past tense, unprompted")

    wins = state.build_recap()["wins"]
    assert len(wins) == 1
    assert wins[0]["why"] == "past tense, unprompted"


def test_fallback_prefers_a_complete_sentence() -> None:
    """A fragment cut mid-word ("…with my sis") should lose to a closed sentence."""
    state = BakarState()
    state.add_transcript(
        "I go to the park yesterday and I saw a very big dog with my sis"
    )
    state.add_transcript("It was really nice.")

    wins = state.build_recap()["wins"]
    assert wins[0]["quote"] == "It was really nice."


def test_goodbye_is_never_used_as_a_win() -> None:
    """The closing utterance is excluded from the fallback, not just discouraged."""
    state = BakarState()
    state.add_transcript(
        "I go to the park yesterday and I saw a very big dog with my sister"
    )
    state.add_transcript("Okay. That is all for today.")
    state.mark_closing()

    wins = state.build_recap()["wins"]

    assert len(wins) == 1
    assert "big dog" in wins[0]["quote"]


def test_button_end_keeps_the_last_utterance() -> None:
    """Pressing END after a sentence must not discard that sentence."""
    state = BakarState()
    state.add_transcript("I saw a big dog with my sister")
    state.mark_closing(exclude_last=False)

    wins = state.build_recap()["wins"]
    assert len(wins) == 1
    assert "big dog" in wins[0]["quote"]


def test_single_utterance_survives_voice_ending() -> None:
    """Even a voice goodbye cannot empty the card entirely."""
    state = BakarState()
    state.add_transcript("I saw a big dog with my sister")
    state.mark_closing()  # exclude_last=True would slice this away

    assert len(state.build_recap()["wins"]) == 1
