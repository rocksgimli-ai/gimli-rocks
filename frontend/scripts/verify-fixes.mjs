/**
 * Executable regression tests for the non-UI fixes.
 * Run with: node scripts/verify-fixes.mjs
 *
 * Plain ESM (not TypeScript) so it stays outside the Next.js tsconfig project
 * while still importing the real modules under test.
 */
import assert from 'node:assert/strict';
import { newParticipantIdentity, newRoomName } from '../lib/ids.ts';
import { isMatrixType, isVectorListType, isVectorType } from '../lib/shader-uniforms.ts';

let checks = 0;

function check(name, fn) {
  fn();
  checks += 1;
  console.log(`ok  ${name}`);
}

// --- ids: the 10 000-slot namespace is gone --------------------------------
const RUNS = 200_000;
const rooms = new Set();
const identities = new Set();

for (let i = 0; i < RUNS; i += 1) {
  rooms.add(newRoomName());
  identities.add(newParticipantIdentity());
}

check(`room names are unique across ${RUNS} draws`, () => {
  assert.equal(rooms.size, RUNS);
});

check(`identities are unique across ${RUNS} draws`, () => {
  assert.equal(identities.size, RUNS);
});

check('room names keep the prefix and are RFC 4122 shaped', () => {
  const name = newRoomName();
  assert.match(
    name,
    /^bakar_room_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
  );
});

check('identity and room do not share a value', () => {
  assert.notEqual(newRoomName(), newParticipantIdentity());
});

// --- shader uniforms: the off-by-one that dropped well-formed vectors ------
check('isVectorType accepts an exactly sized vec3', () => {
  assert.equal(isVectorType('3f', [1, 0.5, 0]), true);
});

check('isVectorType accepts an exactly sized vec2 and vec4', () => {
  assert.equal(isVectorType('2f', [1, 0]), true);
  assert.equal(isVectorType('4f', [1, 0, 0, 1]), true);
});

check('isVectorType rejects an undersized vector', () => {
  assert.equal(isVectorType('3f', [1, 0]), false);
});

check('isVectorType ignores array uniforms', () => {
  assert.equal(isVectorType('3fv', [1, 0, 0]), false);
});

check('isVectorListType treats a single vector as scalar (no array size)', () => {
  assert.equal(isVectorListType('3fv', [1, 0, 0]), false);
});

check('isVectorListType detects a real list', () => {
  assert.equal(isVectorListType('3fv', [1, 0, 0, 0, 1, 0]), true);
});

check('isMatrixType detects matrix uniforms', () => {
  assert.equal(isMatrixType('Matrix4fv', new Array(16).fill(0)), true);
  assert.equal(isMatrixType('3f', [1, 0, 0]), false);
});

console.log(`\n${checks} checks passed`);
