"""Session state and recap payload for Bakar.

Deliberately free of LiveKit imports. The rules that matter — one focus per
session, three wins maximum, a bounded JSON payload — are pure functions, so
they can be tested in milliseconds without credentials or plugins.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

RECAP_VERSION = 1
RECAP_TOPIC = "bakar.recap"
END_TOPIC = "bakar.end"
MAX_WINS = 3

# Keeps the data packet small and the card readable on a phone.
MAX_QUOTE = 240
MAX_ITEM = 120
MAX_EXAMPLE = 200

FOCUS_AREAS = ("pronunciation", "grammar", "vocabulary", "fluency")

# The drill is derived from the focus, so the learner always leaves with one
# sentence they can actually say rather than a rule they have to remember.
_DRILL_HINTS = {
    "pronunciation": "Slowly first, then at normal speed.",
    "grammar": "Say it three times, changing the subject each time.",
    "vocabulary": "Say it once, then again with a different word.",
    "fluency": "Say it once without stopping to think.",
}


def _normalised_words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()


def appears_verbatim(quote: str, transcripts: list[str]) -> bool:
    """True when `quote` occurs word-for-word inside one of the transcripts.

    Models paraphrase. Showing a learner a sentence they did not say is worse
    than showing them nothing, so a quote that fails this check is discarded.
    """
    words = _normalised_words(quote)
    if not words:
        return False
    needle = " ".join(words)
    return any(needle in " ".join(_normalised_words(t)) for t in transcripts)


def _clip(text: str, limit: int) -> str:
    """Collapse whitespace and cap length with an ellipsis."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class Focus:
    area: str
    item: str
    example: str


@dataclass(frozen=True)
class Win:
    quote: str
    why: str


@dataclass
class BakarState:
    """One conversation's worth of memory. Never persisted."""

    focus: Focus | None = None
    wins: list[Win] = field(default_factory=list)
    # Every final user transcript, kept so the recap can fall back to the
    # learner's own words when the model forgets to log a win.
    transcripts: list[str] = field(default_factory=list)
    # Where the goodbye started. Excluded from fallback wins: "okay, bye" is
    # never something to be proud of saying.
    closing_index: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    recap_sent: bool = False

    def note_focus(self, area: str, item: str, example: str) -> tuple[bool, str]:
        """Record the single focus for this session.

        The cap lives here rather than in the prompt: a model under
        conversational pressure will happily correct five things, and five
        corrections is a lesson, not a friend.
        """
        if area not in FOCUS_AREAS:
            allowed = ", ".join(FOCUS_AREAS)
            return False, f"Unknown area. Use one of: {allowed}. Keep talking for now."

        if self.focus is not None:
            return False, (
                f"You already chose a focus for this session: {self.focus.item!r}. "
                "Keep that one and let this go — carry on with the conversation."
            )

        self.focus = Focus(
            area=area,
            item=_clip(item, MAX_ITEM),
            example=_clip(example, MAX_EXAMPLE),
        )
        return True, (
            f"Focus recorded: {self.focus.item}. It is only used in the closing "
            "recap, so do not teach it now."
        )

    def mark_closing(self, *, exclude_last: bool = True) -> None:
        """Remember where the goodbye started.

        `exclude_last` is only true when the learner ended the call by speaking
        ("okay, bye"). Pressing the END button ends the session after ordinary
        speech, so nothing should be excluded.
        """
        self.closing_index = (
            max(0, len(self.transcripts) - 1) if exclude_last else len(self.transcripts)
        )

    def add_transcript(self, text: str) -> None:
        cleaned = _clip(text, MAX_QUOTE)
        # A sentence can arrive twice (STT event + the history pull at close),
        # and not necessarily back to back — drop the duplicate wherever it
        # reappears, or the recap could quote it twice.
        if cleaned and cleaned not in self.transcripts:
            self.transcripts.append(cleaned)

    def effective_wins(self) -> list[Win]:
        """Verbatim wins, or the learner's own longest sentences."""
        if not self.transcripts:
            # Nothing to check against (e.g. typed input in an eval harness).
            return list(self.wins)

        verbatim = [
            win for win in self.wins if appears_verbatim(win.quote, self.transcripts)
        ]
        if verbatim:
            return verbatim

        # Prefer sentences the recogniser closed properly: a fragment cut
        # mid-word makes a poor "you said" quote.
        usable = (
            self.transcripts[: self.closing_index]
            if self.closing_index is not None
            else self.transcripts
        )
        if not usable:
            # One short session: never let the exclusion empty the card.
            usable = self.transcripts
        candidates = sorted(
            (text for text in usable if len(text.split()) >= 3),
            key=lambda text: (text.rstrip()[-1:] in ".!?", len(text)),
            reverse=True,
        )
        return [Win(quote=text, why="") for text in candidates[:2]]

    def log_win(self, quote: str, why: str) -> tuple[bool, str]:
        if len(self.wins) >= MAX_WINS:
            return False, (
                "You already have three wins, which is enough for the recap. "
                "Keep them and keep the conversation going."
            )

        self.wins.append(Win(quote=_clip(quote, MAX_QUOTE), why=_clip(why, MAX_ITEM)))
        return True, "Win recorded. Keep talking."

    def duration_s(self) -> int:
        return max(0, int(time.monotonic() - self.started_at))

    def build_recap(self) -> dict:
        """The payload published on the `bakar.recap` data topic."""
        focus = self.focus
        drill = None
        if focus is not None:
            drill = {
                "sentence": focus.example,
                "hint": _DRILL_HINTS.get(focus.area, "Say it once, then once more."),
            }

        return {
            "version": RECAP_VERSION,
            "wins": [
                {"quote": win.quote, "why": win.why} for win in self.effective_wins()
            ],
            "focus": (
                {"area": focus.area, "item": focus.item, "example": focus.example}
                if focus is not None
                else None
            ),
            "drill": drill,
            "duration_s": self.duration_s(),
        }

    def spoken_summary(self) -> str:
        """Instructions for the model's closing turn, built from what happened."""
        lines = ["The recap card is already on their screen, so do not read it out."]

        wins = self.effective_wins()
        if wins:
            quotes = "; ".join(f'"{win.quote}"' for win in wins[:2])
            lines.append(
                f"Name two things they actually said, word for word: {quotes}."
            )
        else:
            lines.append("Name one thing they said well, even if it was small.")

        if self.focus is not None:
            lines.append(
                f"Then give them one thing to practise — {self.focus.item} — "
                f'with the example "{self.focus.example}".'
            )
        else:
            lines.append("Then give them one small thing to practise next time.")

        lines.append(
            "Finish by inviting them to say that example once. Three short "
            "sentences in total, then stop talking."
        )
        return " ".join(lines)
