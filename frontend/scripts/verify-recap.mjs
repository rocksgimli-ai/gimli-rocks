/**
 * Contract tests for the `bakar.recap` payload.
 * Run with: node scripts/verify-recap.mjs
 */
import assert from 'node:assert/strict';
import { formatDuration, parseRecap } from '../lib/recap.ts';

let checks = 0;
function check(name, fn) {
  fn();
  checks += 1;
  console.log(`ok  ${name}`);
}

const valid = {
  version: 1,
  wins: [
    { quote: 'I went to the park with my sister', why: 'past tense, unprompted' },
    { quote: 'It was really funny', why: 'natural intonation' },
  ],
  focus: { area: 'pronunciation', item: "th in 'three'", example: 'I have three brothers.' },
  drill: { sentence: 'I have three brothers.', hint: 'Slowly first, then at normal speed.' },
  duration_s: 512,
};

check('parses a well-formed recap', () => {
  const recap = parseRecap(JSON.stringify(valid));
  assert.ok(recap);
  assert.equal(recap.durationSeconds, 512);
  assert.equal(recap.wins.length, 2);
  assert.equal(recap.focus.area, 'pronunciation');
  assert.equal(recap.drill.sentence, 'I have three brothers.');
});

check('ignores an unknown version', () => {
  assert.equal(parseRecap(JSON.stringify({ ...valid, version: 2 })), null);
});

check('ignores malformed json', () => {
  assert.equal(parseRecap('{not json'), null);
  assert.equal(parseRecap('null'), null);
  assert.equal(parseRecap('"hello"'), null);
});

check('caps wins at three', () => {
  const many = { ...valid, wins: [...valid.wins, valid.wins[0], valid.wins[0], valid.wins[0]] };
  assert.equal(parseRecap(JSON.stringify(many)).wins.length, 3);
});

check('drops a focus with an unknown area but keeps the wins', () => {
  const recap = parseRecap(
    JSON.stringify({ ...valid, focus: { ...valid.focus, area: 'spelling' } })
  );
  assert.equal(recap.focus, null);
  assert.equal(recap.wins.length, 2);
});

check('accepts a session with no focus, drill or wins', () => {
  const recap = parseRecap(JSON.stringify({ version: 1, wins: [], focus: null, drill: null }));
  assert.deepEqual(recap.wins, []);
  assert.equal(recap.focus, null);
  assert.equal(recap.drill, null);
  assert.equal(recap.durationSeconds, 0);
});

check('truncates oversized strings', () => {
  const recap = parseRecap(
    JSON.stringify({ ...valid, wins: [{ quote: 'x'.repeat(5000), why: 'y'.repeat(5000) }] })
  );
  assert.ok(recap.wins[0].quote.length <= 400);
  assert.ok(recap.wins[0].why.length <= 160);
});

check('rejects a non-numeric duration without throwing', () => {
  assert.equal(parseRecap(JSON.stringify({ ...valid, duration_s: 'long' })).durationSeconds, 0);
});

check('formats duration as m:ss', () => {
  assert.equal(formatDuration(0), '0:00');
  assert.equal(formatDuration(65), '1:05');
  assert.equal(formatDuration(512), '8:32');
});

check('formats durations of an hour or more as h:mm:ss', () => {
  assert.equal(formatDuration(3599), '59:59');
  assert.equal(formatDuration(3600), '1:00:00');
  assert.equal(formatDuration(4000), '1:06:40');
});

console.log(`\n${checks} checks passed`);
