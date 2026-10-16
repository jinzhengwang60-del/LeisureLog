const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,
  '../../src/leisurelog_plugins/game_analysis/static/game-access.js'), 'utf8');
const context = vm.createContext({URLSearchParams});
vm.runInContext(source.replaceAll('export ', '')
  + '\nthis.access = {gameAccess, gameRequest, readGameAccess, gameLink};', context);
const controls = context.access;
const read = ['activity.summary.read', 'games.statistics.read'];
const snapshot = (grants, state = 'running') => ({plugins: [{
  id: 'leisurelog.game-analysis', state, permissions: grants,
  declared_permissions: [...read, 'activity.details.read', 'games.types.write'],
  saved_permissions: [...read, 'activity.details.read', 'games.types.write'],
}]});

test('summary, detail and editing are distinct modes based on actual grants', () => {
  const base = controls.gameAccess(snapshot(read));
  assert.equal(base.available, true); assert.equal(base.details, false); assert.equal(base.edit, false);
  const detail = controls.gameAccess(snapshot([...read, 'activity.details.read']));
  assert.equal(detail.details, true); assert.equal(detail.edit, false);
  const edit = controls.gameAccess(snapshot([...read, 'activity.details.read', 'games.types.write']));
  assert.equal(edit.edit, true);
  assert.equal(controls.gameAccess(snapshot([...read, 'games.types.write'])).edit, false);
});
test('saved intent, declared rights and another plugin cannot enable actions', () => {
  const data = snapshot(read);
  data.plugins.push({id:'example.other', state:'running', permissions:['games.types.write']});
  assert.equal(controls.gameAccess(data).edit, false);
  assert.equal(controls.gameAccess(snapshot([...read, 'activity.details.read'], 'failed')).details, false);
  assert.equal(controls.gameAccess(snapshot(['games.statistics.read'])).available, false);
});
test('unknown metadata or lost state reads leave detail and write controls closed', async () => {
  for (const data of [null, {}, {plugins:[]}, snapshot(null), snapshot({}, 'failed')]) {
    const access = controls.gameAccess(data);
    assert.equal(access.details, false); assert.equal(access.edit, false);
  }
  const access = await controls.readGameAccess(async () => {throw new Error('offline');});
  assert.equal(access.known, false); assert.equal(access.details, false);
  assert.match(access.message, /暂时无法确认/);
});
test('a game with summary-only grants has no deep link; a permitted link keeps its range', () => {
  const document = {createElement: tag => ({tag})};
  const item = {name:'<unsafe title>', key:'playnite:example'};
  const plain = controls.gameLink(document, item, controls.gameAccess(snapshot(read)));
  assert.equal(plain.tag, 'span'); assert.equal(plain.href, undefined);
  assert.equal(plain.textContent, item.name);
  const linked = controls.gameLink(document, item,
    controls.gameAccess(snapshot([...read, 'activity.details.read'])), {start:'2026-01-01',end:'2026-12-31'});
  assert.equal(linked.tag, 'a'); assert.match(linked.href, /start=2026-01-01&end=2026-12-31/);
});
test('a lost write response is not automatically replayed', async () => {
  let calls = 0;
  await assert.rejects(controls.gameRequest('/api/game-types/example', {method:'PUT'}, async () => {
    calls++; throw new Error('lost');
  }), /刷新核对/);
  assert.equal(calls, 1);
});
test('inactive endpoints give an actionable error and reads request fresh state', async () => {
  await assert.rejects(controls.gameRequest('/api/game-statistics', {}, async (_url, options) => {
    assert.equal(options.cache, 'no-store');
    return {ok:false,status:503,json:async()=>({detail:{message:'unavailable'}})};
  }), /插件管理/);
});
