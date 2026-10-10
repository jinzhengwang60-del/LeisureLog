// Node's built-in runner; no browser or extra npm dependency required.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const staticRoot = path.join(__dirname, '../../src/leisurelog/api/static');
const bootstrap = fs.readFileSync(path.join(staticRoot, 'appearance-init.js'), 'utf8');
const controller = fs.readFileSync(path.join(staticRoot, 'theme.js'), 'utf8');
const KEY = 'leisurelog:appearance';

class Element {
  constructor(dataset = {}) { this.dataset = dataset; this.attrs = {}; this.events = {}; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name]; }
  addEventListener(name, fn) { this.events[name] = fn; }
  fire(name, extra = {}) { this.events[name]?.({target: this, ...extra}); }
  querySelector() { return this.span; }
  remove() { this.removed = true; }
  focus() { this.focused = true; }
}

function setup({stored = {}, blocked = false, blockedWrite = false, dark = false, ui = false} = {}) {
  const store = new Map(Object.entries(stored));
  const root = new Element();
  const button = new Element(); button.span = new Element();
  const message = new Element();
  const options = ['sticker', 'minimal', 'terminal', 'sunny', 'editorial', 'arcade'].map(style => {
    const node = new Element({skin: style}); node.span = new Element(); return node;
  });
  const radios = ['system', 'light', 'dark'].map(value => {
    const node = new Element(); node.value = value; return node;
  });
  const closes = [new Element(), new Element()];
  const dialog = new Element();
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; dialog.fire('close'); };
  dialog.querySelector = () => message;
  dialog.querySelectorAll = selector => selector === '[data-skin]' ? options
    : selector === '[name=appearance-mode]' ? radios : closes;
  const links = [new Element()]; links[0].id = 'skin-stylesheet';
  const nodes = [];
  const system = new Element(); system.matches = dark;
  const window = new Element();
  window.matchMedia = () => system;
  window.dispatchEvent = event => window.fire(event.type);
  window.setTimeout = () => 1; window.clearTimeout = () => {};
  const document = {
    documentElement: root,
    getElementById: id => id === 'theme-toggle' ? button : links.find(l => l.id === id && !l.removed),
    createElement: type => {
      if (type === 'dialog') return dialog;
      const node = new Element(); nodes.push(node);
      node.after = candidate => { links.push(candidate); };
      return node;
    },
    body: {append() {}},
  };
  links[0].after = candidate => { links.push(candidate); };
  const localStorage = {
    getItem(key) { if (blocked) throw new Error('disabled'); return store.get(key) ?? null; },
    setItem(key, value) { if (blocked || blockedWrite) throw new Error('quota'); store.set(key, value); },
  };
  const context = vm.createContext({window, document, localStorage, Event: class {constructor(type) {this.type = type;}}});
  vm.runInContext(bootstrap, context);
  window.LeisureAppearance.initializeSkin(links[0]);
  if (ui) vm.runInContext(controller, context);
  return {window, appearance: window.LeisureAppearance, root, links, nodes, store, options, radios, button, dialog, message, system};
}
const plain = value => JSON.parse(JSON.stringify(value));
const flush = () => new Promise(resolve => setImmediate(resolve));

test('default, legacy mode, valid skin and malformed JSON are safe before paint', () => {
  assert.deepEqual(plain(setup().appearance.current), {style:'sticker', mode:'system'});
  const legacy = setup({stored:{'leisurelog:theme':'dark'}});
  assert.equal(legacy.root.dataset.theme, 'dark');
  const broken = setup({stored:{[KEY]:'{oops', 'leisurelog:theme':'light'}});
  assert.deepEqual(plain(broken.appearance.current), {style:'sticker', mode:'light'});
  const current = setup({stored:{[KEY]:JSON.stringify({style:'minimal', mode:'dark'})}});
  assert.equal(current.links[0].href, '/static/skins/minimal.css?v=redesign1');
});
test('unknown skin and mode never become an arbitrary stylesheet URL', () => {
  for (const style of ['__proto__', 'constructor', '/external.css', {}, null]) {
    const env = setup({stored:{[KEY]:JSON.stringify({style, mode:'invalid'})}});
    assert.equal(env.appearance.current.style, 'sticker');
    assert.equal(env.appearance.current.mode, 'system');
  }
});
test('storage unavailable still permits an in-memory preference', () => {
  const env = setup({blocked:true});
  env.appearance.current = {style:'terminal', mode:'dark'};
  assert.equal(env.root.dataset.style, 'terminal');
  assert.equal(env.root.dataset.theme, 'dark');
});
test('system mode resolves at startup and follows changes without changing the saved mode', () => {
  const env = setup({ui:true, dark:true});
  assert.equal(env.root.dataset.theme, 'dark');
  env.system.matches = false; env.system.fire('change');
  assert.equal(env.root.dataset.theme, 'light');
  assert.equal(env.appearance.current.mode, 'system');
  env.appearance.current = {style:'minimal', mode:'dark'};
  env.system.fire('change');
  assert.equal(env.root.dataset.theme, 'dark');
});
test('startup asset failure displays the fallback without erasing the saved selection', () => {
  const saved = JSON.stringify({style:'minimal', mode:'dark'});
  const env = setup({stored:{[KEY]:saved}});
  env.links[0].onerror();
  assert.equal(env.root.dataset.style, 'sticker');
  assert.equal(env.links[0].href, '/static/style.css?v=redesign1');
  assert.equal(env.store.get(KEY), saved);
});
test('a skin replaces the previous CSS only after it loads, then persists', async () => {
  const env = setup({ui:true});
  env.options[1].fire('click'); await flush();
  assert.equal(env.links[0].removed, undefined);
  assert.equal(env.appearance.current.style, 'sticker');
  assert.equal(env.store.has(KEY), false);
  const candidate = env.nodes[0];
  assert.equal(candidate.media, 'not all');
  candidate.onload(); await flush();
  assert.equal(env.links[0].removed, true);
  assert.equal(candidate.media, 'all');
  assert.equal(candidate.id, 'skin-stylesheet');
  assert.equal(JSON.parse(env.store.get(KEY)).style, 'minimal');
  assert.equal(env.options[1].getAttribute('aria-pressed'), 'true');
  assert.equal(env.options[1].disabled, false);
});
test('failed runtime loading preserves current CSS, selection and storage; retry works', async () => {
  const env = setup({ui:true});
  env.options[2].fire('click'); await flush();
  env.nodes[0].onerror(); await flush();
  assert.equal(env.nodes[0].removed, true);
  assert.equal(env.links[0].removed, undefined);
  assert.equal(env.appearance.current.style, 'sticker');
  assert.equal(env.store.has(KEY), false);
  assert.match(env.message.textContent, /当前风格已保留/);
  env.options[1].fire('click'); await flush();
  env.nodes[1].onload(); await flush();
  assert.equal(env.appearance.current.style, 'minimal');
});
test('write failure keeps the new skin and explains that persistence is unavailable', async () => {
  const env = setup({ui:true, blockedWrite:true});
  env.options[2].fire('click'); await flush(); env.nodes[0].onload(); await flush();
  assert.equal(env.appearance.current.style, 'terminal');
  assert.match(env.message.textContent, /不允许保存/);
});
test('another tab updates the skin without writing a feedback loop to storage', async () => {
  const env = setup({ui:true});
  const saved = JSON.stringify({style:'terminal',mode:'dark'});
  env.store.set(KEY, saved); env.window.fire('storage', {key:KEY}); await flush();
  env.nodes[0].onload(); await flush();
  assert.equal(env.root.dataset.theme, 'dark');
  assert.equal(env.root.dataset.style, 'terminal');
  assert.equal(env.store.get(KEY), saved);
  assert.match(env.message.textContent, /同步其他页面/);
});
test('changing brightness retains the skin and closing returns focus', async () => {
  const env = setup({ui:true, stored:{[KEY]:JSON.stringify({style:'minimal',mode:'system'})}});
  env.radios[2].fire('change'); await flush();
  assert.equal(env.appearance.current.style, 'minimal');
  assert.equal(env.root.dataset.theme, 'dark');
  assert.equal(env.nodes.length, 0);
  env.button.fire('click'); assert.equal(env.dialog.open, true);
  env.dialog.close(); assert.equal(env.button.focused, true);
});

test('new collection survives repeated switching, brightness changes and reopening', async () => {
  const env = setup({ui:true});
  for (const style of ['sunny', 'editorial', 'arcade', 'sunny']) {
    const previous = env.links.find(link => link.id === 'skin-stylesheet' && !link.removed);
    env.options.find(option => option.dataset.skin === style).fire('click');
    await flush();
    assert.equal(previous.removed, undefined);
    env.nodes.at(-1).onload(); await flush();
    assert.equal(previous.removed, true);
    env.radios[2].fire('change'); await flush();
    assert.deepEqual(plain(env.appearance.current), {style, mode:'dark'});
    const reopened = setup({stored:{[KEY]:env.store.get(KEY)}});
    assert.deepEqual(plain(reopened.appearance.current), {style, mode:'dark'});
    assert.equal(reopened.links[0].href, env.appearance.SKINS[style].href);
    assert.equal(env.options.filter(option => option.getAttribute('aria-pressed') === 'true').length, 1);
  }
});
