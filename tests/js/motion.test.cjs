const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../src/leisurelog/api/static/motion.js'), 'utf8');
const KEY = 'leisurelog:motion';

function setup({saved, reduce = false, blocked = false, nativeTransition = false, observe = false} = {}) {
  const store = new Map(saved === undefined ? [] : [[KEY, saved]]);
  const listeners = new Map(), mediaListeners = new Map(), animations = [];
  const root = {dataset: {style: 'sticker'}}, stylesheet = {};
  const media = {matches: reduce, addEventListener: (name, fn) => mediaListeners.set(name, fn)};
  const window = {
    matchMedia: () => media,
    addEventListener: (name, fn) => listeners.set(name, fn),
    dispatchEvent: event => listeners.get(event.type)?.(event),
  };
  const document = {
    documentElement: root, hidden: false, readyState: 'loading',
    getElementById: () => stylesheet, addEventListener() {},
  };
  const localStorage = {
    getItem: key => { if (blocked) throw new Error('unavailable'); return store.get(key) ?? null; },
    setItem: (key, value) => { if (blocked) throw new Error('unavailable'); store.set(key, value); },
  };
  const transitions = [];
  if (nativeTransition) document.startViewTransition = update => {
    update();
    const transition = {
      ready: Promise.reject(new Error('capture unavailable')), finished: Promise.resolve(), updateCallbackDone: Promise.resolve(),
      skipTransition() { this.skipped = true; },
    };
    transitions.push(transition);
    return transition;
  };
  const context = vm.createContext({window, document, localStorage, Event: class {constructor(type) {this.type = type;}}});
  const observers = [];
  if (observe) {
    window.innerHeight = 600;
    context.IntersectionObserver = class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe() {} unobserve() {} disconnect() {}
    };
  }
  vm.runInContext(source, context);
  function element({hidden = false, supported = true} = {}) {
    const node = {getClientRects: () => hidden ? [] : [{}]};
    if (supported) node.animate = (frames, timing) => {
      let finish;
      const animation = {frames, timing, finished: new Promise(resolve => { finish = resolve; }), cancel() {this.cancelled = true; finish();}};
      node.lastAnimation = animation;
      animations.push(animation);
      return animation;
    };
    return node;
  }
  const container = children => ({querySelectorAll: () => children});
  return {motion: window.LeisureMotion, root, stylesheet, media, mediaListeners, listeners, store, animations, transitions, observers, element, container};
}

test('same-query refresh stays still while a changed filter receives a new entrance', () => {
  const env = setup(), list = env.container([env.element(), env.element()]);
  env.motion.reveal(list, {key: 'today'});
  assert.equal(env.animations.length, 2);
  env.motion.reveal(list, {key: 'today'});
  assert.equal(env.animations.length, 2);
  env.motion.reveal(list, {key: 'yesterday'});
  assert.equal(env.animations.length, 4);
  assert.equal(env.animations[0].cancelled, true);
  assert.equal(env.animations[0].frames.some(frame => 'transform' in frame), false);
});

test('system reduced motion immediately cancels running effects and disables the animation stylesheet', () => {
  const env = setup();
  env.motion.reveal(env.container([env.element()]));
  env.media.matches = true; env.mediaListeners.get('change')();
  assert.equal(env.motion.enabled, false);
  assert.equal(env.motion.requested, true);
  assert.equal(env.root.dataset.motion, 'off');
  assert.equal(env.stylesheet.media, 'not all');
  assert.equal(env.animations[0].cancelled, true);
  env.motion.reveal(env.container([env.element()]));
  assert.equal(env.animations.length, 1);
});

test('saved off preference is preserved across reloads and storage events without writing back', () => {
  const env = setup({saved: '0'});
  assert.equal(env.motion.enabled, false);
  env.store.set(KEY, '1'); env.listeners.get('storage')({key: KEY});
  assert.equal(env.motion.enabled, true);
  assert.equal(env.stylesheet.media, 'all');
  assert.equal(env.motion.setEnabled(false), true);
  assert.equal(env.store.get(KEY), '0');
  assert.equal(setup({saved: env.store.get(KEY)}).motion.enabled, false);
});

test('blocked preference storage still applies the choice and reports that it was not saved', () => {
  const env = setup({blocked: true});
  assert.equal(env.motion.setEnabled(false), false);
  assert.equal(env.motion.enabled, false);
  assert.equal(env.stylesheet.media, 'not all');
});

test('older animation APIs and hidden elements leave the real content and updates usable', async () => {
  const env = setup();
  env.motion.reveal(env.container([env.element({hidden: true}), env.element({supported: false})]));
  assert.equal(env.animations.length, 0);
  let updates = 0;
  await env.motion.transitionAppearance(() => { updates++; });
  assert.equal(updates, 1);
});

test('native transition capture failure cannot lose or duplicate a skin change', async () => {
  const env = setup({nativeTransition: true});
  let updates = 0;
  await env.motion.transitionAppearance(() => { updates++; });
  assert.equal(updates, 1);
  assert.equal(env.transitions.length, 1);
  env.motion.setEnabled(false);
  await env.motion.transitionAppearance(() => { updates++; });
  assert.equal(updates, 2);
  assert.equal(env.transitions.length, 1);
});

test('scroll entrance uses refreshed children rather than animating discarded data', () => {
  const env = setup({observe: true});
  const discarded = env.element(), current = env.element();
  let children = [discarded];
  const list = {querySelectorAll: () => children, getBoundingClientRect: () => ({top: 900, bottom: 1100})};
  env.motion.reveal(list, {key: 'same-query'});
  assert.equal(env.animations.length, 0);
  children = [current];
  env.motion.reveal(list, {key: 'same-query'});
  env.observers[0].callback([{isIntersecting: true, target: list}]);
  assert.equal(env.animations.length, 1);
  assert.equal(discarded.lastAnimation, undefined);
  assert.equal(current.lastAnimation, env.animations[0]);
  env.motion.reveal(list, {key: 'same-query'});
  assert.equal(env.animations.length, 1);
});
