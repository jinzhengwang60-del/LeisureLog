const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
  const slot = {children: [], style: {}, replaceChildren(...children) { this.children = children; }};
  const link = href => ({href, hidden: false, getAttribute() {return this.href;}});
  const extra = [link('/games?game=fixture'), link('/game-preferences?start=2026-01-01'), link('/review')];
  const document = {
    querySelectorAll(selector) {return selector === '[data-plugin-navigation]' ? [slot] : extra;},
    createElement() {return {attributes: {}, setAttribute(name, value) {this.attributes[name] = value;}};},
  };
  const context = vm.createContext({document});
  const source = fs.readFileSync(path.join(__dirname, '../../src/leisurelog/api/static/plugin-navigation.js'), 'utf8');
  vm.runInContext(source.replaceAll('export ', ''), context);
  return {slot, extra, render: (pages, current) => context.renderPluginNavigation(
    document, pages, current, ['/games', '/game-preferences'],
  )};
}

test('host page labels are text and the current optional page is identified', () => {
  const ui = setup();
  ui.render([{url: '/games', title: '<img onerror=bad>'}, {url: '/game-preferences', title: '类型与偏好'}], '/games');
  assert.equal(ui.slot.children[0].textContent, '<img onerror=bad>');
  assert.equal(ui.slot.children[0].attributes['aria-current'], 'page');
  assert.equal(ui.slot.children[1].attributes['aria-current'], undefined);
  assert.equal(ui.extra[0].hidden, false);
});

test('disable removes optional menus and hides deep links while core navigation stays available', () => {
  const ui = setup();
  ui.render([{url: '/games', title: '游戏'}], '/');
  ui.render([], '/');
  assert.equal(ui.slot.children.length, 0);
  assert.equal(ui.extra[0].hidden, true);
  assert.equal(ui.extra[1].hidden, true);
  assert.equal(ui.extra[2].hidden, false);
  ui.render([{url: '/games', title: '游戏'}, {url: '/game-preferences', title: '偏好'}], '/');
  assert.equal(ui.extra[0].hidden, false);
  assert.equal(ui.extra[1].hidden, false);
});
