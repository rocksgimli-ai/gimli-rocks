/**
 * Recap payload published by the agent on the `bakar.recap` data topic.
 *
 * A data packet is untrusted input even when it comes from our own agent, so
 * parsing is defensive: unknown versions are ignored, strings are truncated and
 * arrays are bounded. Nothing here touches the DOM, so it is unit-testable.
 */

export const RECAP_TOPIC = 'bakar.recap';
export const END_TOPIC = 'bakar.end';
export const RECAP_VERSION = 1;

export const FOCUS_AREAS = ['pronunciation', 'grammar', 'vocabulary', 'fluency'] as const;

export type FocusArea = (typeof FOCUS_AREAS)[number];

export interface RecapFocus {
  area: FocusArea;
  item: string;
  example: string;
}

export interface RecapWin {
  quote: string;
  why: string;
}

export interface RecapDrill {
  sentence: string;
  hint: string;
}

export interface Recap {
  version: number;
  wins: RecapWin[];
  focus: RecapFocus | null;
  drill: RecapDrill | null;
  durationSeconds: number;
}

const MAX_WINS = 3;
const MAX_TEXT = 400;
const MAX_DURATION_S = 60 * 60 * 4;

function asText(value: unknown, limit = MAX_TEXT): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, limit) : null;
}

function parseFocus(value: unknown): RecapFocus | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Record<string, unknown>;
  const area = raw.area;
  const item = asText(raw.item, 160);
  const example = asText(raw.example, MAX_TEXT);

  if (typeof area !== 'string' || !(FOCUS_AREAS as readonly string[]).includes(area)) return null;
  if (!item || !example) return null;

  return { area: area as FocusArea, item, example };
}

function parseDrill(value: unknown): RecapDrill | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Record<string, unknown>;
  const sentence = asText(raw.sentence, MAX_TEXT);
  if (!sentence) return null;
  return { sentence, hint: asText(raw.hint, 160) ?? '' };
}

function parseWins(value: unknown): RecapWin[] {
  if (!Array.isArray(value)) return [];
  const wins: RecapWin[] = [];
  for (const entry of value.slice(0, MAX_WINS)) {
    if (typeof entry !== 'object' || entry === null) continue;
    const raw = entry as Record<string, unknown>;
    const quote = asText(raw.quote, MAX_TEXT);
    if (!quote) continue;
    wins.push({ quote, why: asText(raw.why, 160) ?? '' });
  }
  return wins;
}

/**
 * Decode a data-channel payload. Returns `null` for anything that is not a
 * recap this client understands — the caller simply keeps the card hidden.
 */
export function parseRecap(raw: string): Recap | null {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return null;
  }

  if (typeof payload !== 'object' || payload === null) return null;
  const data = payload as Record<string, unknown>;
  if (data.version !== RECAP_VERSION) return null;

  const durationRaw = data.duration_s;
  const durationSeconds =
    typeof durationRaw === 'number' && Number.isFinite(durationRaw)
      ? Math.min(Math.max(0, Math.round(durationRaw)), MAX_DURATION_S)
      : 0;

  return {
    version: RECAP_VERSION,
    wins: parseWins(data.wins),
    focus: parseFocus(data.focus),
    drill: parseDrill(data.drill),
    durationSeconds,
  };
}

export function formatDuration(totalSeconds: number): string {
  // An hour or more renders as h:mm:ss (parseRecap caps sessions at 4 h);
  // shorter sessions keep the m:ss the recap card has always shown.
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const mm = minutes.toString().padStart(2, '0');
  const ss = seconds.toString().padStart(2, '0');
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${minutes}:${ss}`;
}
