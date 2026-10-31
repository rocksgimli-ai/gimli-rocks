import { NextResponse } from 'next/server';
import { AccessToken, type AccessTokenOptions, type VideoGrant } from 'livekit-server-sdk';
import { RoomConfiguration } from '@livekit/protocol';
import { newParticipantIdentity, newRoomName } from '@/lib/ids';

type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

const NO_STORE = { 'Cache-Control': 'no-store' };

// don't cache the results
export const revalidate = 0;

// Naive per-IP rate limiting for token minting: at most MINT_RATE_LIMIT
// requests per IP per MINT_RATE_WINDOW_MS (sliding window). Honest caveat
// (DEPLOY.md §9): on serverless every instance keeps its own map, so this is
// not a global cap — it still stops the most naive scripted abuse without a
// shared store.
const MINT_RATE_LIMIT = 20;
const MINT_RATE_WINDOW_MS = 60 * 60 * 1000; // rolling hour

const mintTimestampsByIp = new Map<string, number[]>();

function rateLimitKey(request: Request): string {
  // First value in x-forwarded-for is the original client; proxies append the
  // rest of the chain. Without the header (direct access) everything shares
  // one bucket, which is the conservative direction for a limiter.
  const forwarded = request.headers.get('x-forwarded-for');
  return forwarded?.split(',')[0]?.trim() || 'unknown';
}

/**
 * Record one mint attempt for `key` and return the Retry-After in seconds:
 * 0 means the request may proceed, > 0 means the window is exhausted.
 * Expired timestamps are pruned while the window is evaluated.
 */
function consumeMintSlot(key: string, now: number): number {
  const timestamps = (mintTimestampsByIp.get(key) ?? []).filter(
    (ts) => now - ts < MINT_RATE_WINDOW_MS
  );
  if (timestamps.length >= MINT_RATE_LIMIT) {
    mintTimestampsByIp.set(key, timestamps);
    return Math.ceil((timestamps[0] + MINT_RATE_WINDOW_MS - now) / 1000);
  }
  timestamps.push(now);
  mintTimestampsByIp.set(key, timestamps);
  return 0;
}

export async function POST(request: Request) {
  // Abuse gate before minting anything: reject with 429 once the caller's IP
  // has exhausted its rolling-hour budget.
  const clientKey = rateLimitKey(request);
  const retryAfterSeconds = consumeMintSlot(clientKey, Date.now());
  if (retryAfterSeconds > 0) {
    console.error(`[token] rate limit exceeded for ${clientKey}`);
    return NextResponse.json(
      { error: 'Too many token requests. Try again later.' },
      { status: 429, headers: { ...NO_STORE, 'Retry-After': String(retryAfterSeconds) } }
    );
  }

  const serverUrl = process.env.LIVEKIT_URL;
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const agentName = process.env.AGENT_NAME;

  if (!serverUrl || !apiKey || !apiSecret || !agentName) {
    const missing = !serverUrl
      ? 'LIVEKIT_URL'
      : !apiKey
        ? 'LIVEKIT_API_KEY'
        : !apiSecret
          ? 'LIVEKIT_API_SECRET'
          : 'AGENT_NAME';

    // Fail loudly instead of minting a token that can never dispatch an agent:
    // the UI would connect successfully and the user would simply hear nothing.
    console.error(`[token] ${missing} is not set`);
    return NextResponse.json(
      { error: `Server is missing ${missing}` },
      { status: 500, headers: NO_STORE }
    );
  }

  // One room per session, one identity per connection. See lib/ids.ts for why
  // these must not come from a small random namespace.
  const roomName = newRoomName();
  const participantIdentity = newParticipantIdentity();
  const participantName = 'user';

  try {
    const participantToken = await createParticipantToken(
      { identity: participantIdentity, name: participantName },
      roomName,
      apiKey,
      apiSecret,
      RoomConfiguration.fromJson({ agents: [{ agentName }] }, { ignoreUnknownFields: true })
    );

    const data: ConnectionDetails = {
      serverUrl,
      roomName,
      participantName,
      participantToken,
    };

    return NextResponse.json(data, { headers: NO_STORE });
  } catch (error) {
    // Always return a response: falling out of the catch would make Next.js throw
    // "No response is returned from route handler". The detail stays in the log.
    console.error('[token] failed to create a participant token', error);
    return NextResponse.json(
      { error: 'Could not create a session' },
      { status: 500, headers: NO_STORE }
    );
  }
}

function createParticipantToken(
  userInfo: AccessTokenOptions,
  roomName: string,
  apiKey: string,
  apiSecret: string,
  roomConfig: RoomConfiguration
): Promise<string> {
  const at = new AccessToken(apiKey, apiSecret, {
    ...userInfo,
    ttl: '15m',
  });
  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };
  at.addGrant(grant);
  at.roomConfig = roomConfig;

  return at.toJwt();
}
