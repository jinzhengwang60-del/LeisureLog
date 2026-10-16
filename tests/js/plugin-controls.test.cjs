const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../src/leisurelog/api/static/plugin-controls.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.replaceAll('export ', '') + '\nthis.controls = {initialSelections, operationRequest, operationMessage, stateText, stateDescription, needsAttention, issueText, pluginApi};', context);
const controls = context.controls;
const plain = value => JSON.parse(JSON.stringify(value));
function plan() {
  return {revision: 4, operation: 'enable', plugin_id: 'example.report', targets: [
    {id: 'example.base', already_running: true, default_grants: ['activity.summary.read'],
      declared_permissions: ['activity.summary.read', 'activity.details.read'], required_permissions: ['activity.summary.read']},
    {id: 'example.report', already_running: false, default_grants: ['activity.summary.read', 'activity.details.read', 'games.types.write'],
      declared_permissions: ['activity.summary.read', 'activity.details.read', 'games.types.write'], required_permissions: ['activity.summary.read']},
  ]};
}
test('a running dependency keeps its actual grant subset; optional writes can be removed', () => {
  const operation = plan(), selected = controls.initialSelections(operation);
  selected['example.report'].delete('games.types.write');
  selected['example.report'].delete('activity.details.read');
  const request = plain(controls.operationRequest(operation, selected));
  assert.equal(request.body.expected_revision, 4);
  assert.deepEqual(request.body.grants, {'example.base': ['activity.summary.read'], 'example.report': ['activity.summary.read']});
});
test('undeclared grants, changed running grants and missing required grants cannot be submitted', () => {
  for (const alter of [selected => selected['example.report'].add('network.request'),
    selected => selected['example.base'].add('activity.details.read'),
    selected => selected['example.report'].delete('activity.summary.read')]) {
    const operation = plan(), selected = controls.initialSelections(operation); alter(selected);
    assert.throws(() => controls.operationRequest(operation, selected));
  }
});
test('saving types without detail access is explained before a mutation request', () => {
  const operation = plan(), selected = controls.initialSelections(operation);
  selected['example.report'].delete('activity.details.read');
  assert.throws(() => controls.operationRequest(operation, selected), /读取活动详情/);
});
test('dependency stop and permission revoke carry the reviewed revision and affected set', () => {
  const operation = {...plan(), operation: 'disable'};
  assert.deepEqual(plain(controls.operationRequest(operation).body), {expected_revision: 4, cascade: true});
  operation.operation = 'revoke'; operation.permission = 'activity.summary.read';
  const request = controls.operationRequest(operation);
  assert.equal(request.method, 'DELETE');
  assert.equal(request.url, '/api/plugins/example.report/permissions/activity.summary.read?expected_revision=4');
});
test('extra targets and invalid operation identities cannot redirect a request', () => {
  const operation = plan(), selected = controls.initialSelections(operation);
  selected['example.unrelated'] = new Set();
  assert.throws(() => controls.operationRequest(operation, selected));
  operation.plugin_id = '../outside';
  assert.throws(() => controls.operationRequest(operation));
  assert.throws(() => controls.operationRequest(null));
});
test('HTTP success with failed startup is not presented as a running feature', () => {
  const operation = plan();
  const result = controls.operationMessage(operation, {plugins: operation.targets.map(target => ({id: target.id, state: 'failed'}))});
  assert.equal(result.tone, 'warning'); assert.match(result.text, /尚未正常运行/);
  assert.equal(controls.operationMessage(operation, {plugins: []}).tone, 'warning');
});
test('a timed out stop remains visibly pending and is not reported as completed', () => {
  const plugin = {id: 'example.report', state: 'failed', enabled: false, workers: [{running: true}]};
  assert.equal(controls.stateText(plugin), '等待任务退出');
  assert.match(controls.stateDescription(plugin), /不能重新启用/);
  const result = controls.operationMessage({...plan(), operation: 'disable'}, {plugins: [plugin]});
  assert.equal(result.tone, 'warning'); assert.match(result.text, /尚未退出/);
});
test('a previously timed out task no longer says restart is blocked after it exits', () => {
  const plugin = {state: 'failed', enabled: false, workers: [{running: false}],
    last_error: {code: 'stop_timeout', message: 'old restart restriction'}};
  assert.equal(controls.stateText(plugin), '已停止');
  assert.match(controls.stateDescription(plugin), /可重新选择授权启用/);
  assert.match(controls.issueText(plugin, plugin.last_error), /已确认旧任务退出/);
  assert.equal(controls.needsAttention(plugin), false);
  plugin.workers[0].running = true;
  assert.equal(controls.needsAttention(plugin), true);
  plugin.workers[0].running = false;
  plugin.last_error.code = 'task_failed';
  assert.equal(controls.needsAttention(plugin), true);
});
test('network failure after a write is uncertain and is never automatically retried', async () => {
  let calls = 0;
  await assert.rejects(controls.pluginApi('/api/plugins/example.report/enable', {method: 'POST', body: {}},
    async () => {calls++; throw new Error('lost response');}), error => error.uncertain && /核对/.test(error.message));
  assert.equal(calls, 1);
});
test('an unreadable successful write response also requires a state check', async () => {
  await assert.rejects(controls.pluginApi('/api/plugins/example.report/disable', {method: 'POST'},
    async () => ({ok: true, json: async () => {throw new Error('bad json');}})), error => error.uncertain);
});
test('stale settings receive a useful message instead of a replay', async () => {
  let calls = 0;
  await assert.rejects(controls.pluginApi('/api/plugins/example.report/enable', {method: 'POST'},
    async () => {calls++; return {ok: false, json: async () => ({detail: {code: 'configuration_conflict', message: 'raw'}})};}),
  error => error.code === 'configuration_conflict' && /重新核对/.test(error.message));
  assert.equal(calls, 1);
});
