/**
 * Session identifiers for LiveKit rooms.
 *
 * Both values must be unguessable and collision-free:
 *
 * - LiveKit disconnects an existing participant when a second one joins with the
 *   same identity, so a collision kicks a live user out mid-sentence.
 * - Agent dispatch carried by an access token only runs when the room is
 *   *created*. If the generated room name already exists, the user silently ends
 *   up in a room with no agent (and, if they are unlucky, next to a stranger).
 *
 * The previous implementation drew both values from `Math.random() * 10_000`,
 * which collides with ~39% probability at 100 concurrent sessions. A UUIDv4
 * carries 122 random bits.
 */

const ROOM_PREFIX = 'bakar_room_';
const IDENTITY_PREFIX = 'bakar_user_';

function randomId(): string {
  return globalThis.crypto.randomUUID();
}

/** A room name that is unique per session. */
export function newRoomName(): string {
  return `${ROOM_PREFIX}${randomId()}`;
}

/** A participant identity that is unique per connection. */
export function newParticipantIdentity(): string {
  return `${IDENTITY_PREFIX}${randomId()}`;
}
