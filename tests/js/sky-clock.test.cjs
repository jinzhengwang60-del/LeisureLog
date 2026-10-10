// The sunny skin's time of day: pure colour maths plus the CSS variables published before paint.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../src/leisurelog/api/static/sky-clock.js'), 'utf8');

function setup({search = '', now = new Date(2026, 9, 10, 14, 30)} = {}) {
  const props = new Map();
  const root = {dataset: {}, style: {setProperty: (key, value) => props.set(key, value)}};
  const timers = [];
  const listeners = {};
  const document = {documentElement: root, hidden: false,
    addEventListener: (name, fn) => { listeners[name] = fn; }};
  const window = {location: {search}, setInterval: (fn, ms) => timers.push([fn, ms])};
  class FixedDate extends Date { constructor(...args) { super(...(args.length ? args : [now])); } }
  const context = vm.createContext({window, document, URLSearchParams, Date: FixedDate});
  vm.runInContext(source, context);
  return {clock: window.LeisureSkyClock, root, props, timers, listeners};
}
const channels = value => value.match(/\d+(\.\d+)?/g).map(Number);

test('publishes the current local time before paint and refreshes every minute', () => {
  const env = setup();
  assert.equal(env.root.dataset.sky, 'day');
  for (const key of ['--sky-top', '--sky-mid', '--sky-low', '--sky-glow', '--sky-beam', '--sky-lamp', '--sky-moon']) {
    assert.ok(env.props.has(key), key);
  }
  assert.equal(env.timers.length, 1);
  assert.equal(env.timers[0][1], 60000);
  assert.equal(typeof env.listeners.visibilitychange, 'function');
});

test('midday leaves the illustration untouched; night darkens it and turns the lamp on', () => {
  const {clock} = setup();
  const noon = clock.look(13).vars;
  assert.equal(noon['--sky-top'], 'rgb(255,255,255)');
  assert.equal(noon['--sky-lamp'], 0);
  const night = clock.look(22).vars;
  assert.ok(Math.max(...channels(night['--sky-mid'])) < 120);
  assert.equal(night['--sky-lamp'], 1);
  assert.equal(night['--sky-moon'], 1);
});

test('the look changes gradually and wraps around midnight', () => {
  const {clock} = setup();
  // Three minutes apart never differ by more than 10 levels per channel, even through dawn.
  for (let hour = 0; hour < 24; hour += 0.05) {
    const a = channels(clock.look(hour).vars['--sky-mid']);
    const b = channels(clock.look(hour + 0.05).vars['--sky-mid']);
    assert.ok(a.every((v, i) => Math.abs(v - b[i]) <= 10), `jump near ${hour.toFixed(2)}h`);
  }
  assert.deepEqual(clock.look(24).vars, clock.look(0).vars);
  assert.deepEqual(clock.look(-1).vars, clock.look(23).vars);
});

test('phases follow the hour', () => {
  const {clock} = setup();
  assert.deepEqual([3, 6, 12, 18, 22].map(clock.phase), ['night', 'dawn', 'day', 'dusk', 'night']);
});

test('?sky-hour previews a time; invalid values fall back to the real clock', () => {
  assert.equal(setup({search: '?sky-hour=18.7'}).root.dataset.sky, 'dusk');
  assert.equal(setup({search: '?sky-hour=22', now: new Date(2026, 9, 10, 12)}).root.dataset.sky, 'night');
  for (const search of ['?sky-hour=', '?sky-hour=abc', '?sky-hour=24', '?sky-hour=-1']) {
    assert.equal(setup({search}).root.dataset.sky, 'day', search);
  }
});
