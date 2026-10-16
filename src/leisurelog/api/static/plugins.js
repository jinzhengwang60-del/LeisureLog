import {CAPABILITIES, initialSelections, issueText, needsAttention, operationMessage, operationRequest, permissionText,
  pluginApi, stateDescription, stateText} from './plugin-controls.js';
import {refreshPluginNavigation} from './plugin-navigation.js';

const $ = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const model = {snapshot: null, renderKey: '', busy: false, request: 0, plan: null, selections: null, trigger: null, pendingFocus: false};
const dialog = $('plugin-action');

function message(id, text = '', tone = '') {
  $(id).textContent = text;
  $(id).hidden = !text;
  if (id === 'management-message') $(id).className = 'plugin-message ' + tone;
}
function restoreActionFocus() {
  model.pendingFocus = false;
  const trigger = model.trigger;
  if (trigger?.isConnected && !trigger.disabled) {trigger.focus(); return;}
  const pluginId = trigger?.dataset.focusKey?.split(':')[0];
  const replacement = [...$('plugin-list').querySelectorAll('button[data-focus-key]')]
    .find(element => element.dataset.focusKey.startsWith(pluginId + ':') && !element.disabled);
  (replacement || $('refresh-plugins')).focus();
}
function managedBusy(busy) {
  model.busy = busy;
  $('refresh-plugins').disabled = busy;
  for (const button of $('plugin-list').querySelectorAll('button')) {
    button.disabled = busy || button.dataset.blocked === 'true' || Boolean(model.snapshot?.configuration_error || model.snapshot?.closing);
  }
  for (const id of ['close-action', 'cancel-action', 'apply-action']) $(id).disabled = busy;
  for (const input of dialog.querySelectorAll('input')) input.disabled = busy || input.dataset.locked === 'true';
  dialog.setAttribute('aria-busy', String(busy));
  $('action-progress').hidden = !busy || !dialog.open;
  if (!busy && model.pendingFocus) restoreActionFocus();
}
function button(text, plugin, operation, permission) {
  const element = node('button', text);
  element.type = 'button';
  element.dataset.focusKey = plugin.id + ':' + operation + ':' + (permission || '');
  const blocked = operation === 'enable' && plugin.state !== 'running' && plugin.workers?.some(worker => worker.running);
  element.dataset.blocked = String(Boolean(blocked));
  element.disabled = model.busy || blocked || Boolean(model.snapshot?.configuration_error || model.snapshot?.closing);
  element.addEventListener('click', () => openPlan(plugin, operation, permission, element));
  return element;
}
function render(snapshot) {
  if (!Array.isArray(snapshot.plugins) || !Number.isSafeInteger(snapshot.revision)) {
    throw new Error('插件状态不完整，请稍后刷新。');
  }
  model.snapshot = snapshot;
  $('plugin-updated').textContent = '更新于 ' + new Intl.DateTimeFormat('zh-CN', {hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(new Date());
  const renderKey = JSON.stringify(snapshot);
  if (renderKey === model.renderKey) return;
  model.renderKey = renderKey;
  const expanded = new Set([...$('plugin-list').querySelectorAll('details[open]')].map(e => e.dataset.plugin));
  const focused = document.activeElement?.dataset.focusKey;
  $('plugin-total').textContent = snapshot.plugins.length;
  $('plugin-running').textContent = snapshot.plugins.filter(p => p.state === 'running').length;
  $('plugin-attention').textContent = snapshot.plugins.filter(needsAttention).length;
  message('management-notice', snapshot.configuration_error
    ? '插件设置暂时无法读取，管理操作已暂停。原设置文件已保留，基础活动记录仍可使用。请修复设置后重启。'
    : snapshot.closing ? 'LeisureLog 正在关闭，暂时不能更改插件。' : '');
  $('plugin-list').replaceChildren();
  for (const plugin of snapshot.plugins) {
    const card = node('article', undefined, 'plugin-card'), header = node('div', undefined, 'plugin-card-header');
    const name = node('div');
    name.append(node('h3', plugin.version === null ? '未找到的功能' : plugin.name),
      node('p', plugin.version ? '版本 ' + plugin.version : '保存的选择目前没有对应功能', 'plugin-version'));
    const tone = plugin.state === 'running' ? 'running' : needsAttention(plugin)
      ? plugin.state === 'unavailable' ? 'unavailable' : 'failed' : '';
    const state = node('span', stateText(plugin), 'plugin-state ' + tone);
    header.append(name, state); card.append(header);
    const capabilities = node('div', undefined, 'plugin-capabilities');
    for (const capability of plugin.capabilities || []) capabilities.append(node('span', CAPABILITIES[capability] || capability));
    card.append(capabilities, node('p', stateDescription(plugin), 'plugin-description'));
    for (const issue of [plugin.last_error, plugin.catalog_error].filter(Boolean)) {
      card.append(node('p', issueText(plugin, issue), 'plugin-issue'));
    }
    const actions = node('div', undefined, 'plugin-actions');
    if (plugin.version !== null && plugin.state !== 'running') {
      const enable = button(plugin.enabled || plugin.state === 'failed' ? '重新尝试启用' : '启用', plugin, 'enable');
      enable.className = 'primary'; actions.append(enable);
    }
    if (plugin.enabled || ['running', 'starting', 'stopping'].includes(plugin.state)) {
      actions.append(button(plugin.version === null ? '移除失效选择' : '停用', plugin, 'disable'));
    }
    card.append(actions);
    const details = node('details'); details.dataset.plugin = plugin.id; details.open = expanded.has(plugin.id);
    const summary = node('summary', '授权与运行详情'); summary.dataset.focusKey = plugin.id + ':details';
    details.append(summary);
    const grants = plugin.state === 'running' ? plugin.permissions : plugin.saved_permissions || [];
    details.append(node('p', plugin.state === 'running' ? '本次生效的授权' : '已保存的授权（本次可能未生效）'));
    const list = node('ul', undefined, 'plugin-permission-list');
    for (const grant of grants) {
      const item = node('li'); item.append(node('span', permissionText(grant)[0]));
      if (plugin.version !== null) item.append(button('撤销并停用', plugin, 'revoke', grant));
      list.append(item);
    }
    if (!grants.length) list.append(node('li', '当前没有生效或保存的授权。'));
    details.append(list, node('p', '调整权限时先停用，再选择授权启用；撤销任一权限会停用整个功能及依赖它的功能。'));
    const debug = node('div', undefined, 'plugin-debug');
    debug.append(node('p', '功能标识：' + plugin.id));
    if (plugin.dependencies?.length) debug.append(node('p', '依赖：' + plugin.dependencies.map(dep => snapshot.plugins.find(p => p.id === dep.id)?.name || dep.id).join('、')));
    const live = (plugin.workers || []).filter(worker => worker.running).length;
    debug.append(node('p', live ? '尚有 ' + live + ' 项工作未退出。' : '当前没有未退出的工作。'));
    if (plugin.last_error) debug.append(node('p', '问题标识：' + plugin.last_error.code));
    details.append(debug); card.append(details); $('plugin-list').append(card);
  }
  $('plugin-empty').hidden = snapshot.plugins.length !== 0;
  if (focused) [...$('plugin-list').querySelectorAll('[data-focus-key]')].find(e => e.dataset.focusKey === focused)?.focus({preventScroll: true});
}
async function refresh({quiet = false} = {}) {
  const ticket = ++model.request;
  try {
    const snapshot = await pluginApi('/api/plugins');
    if (ticket !== model.request) return;
    const previous = model.renderKey;
    render(snapshot); message('management-error');
    if (previous !== model.renderKey) message('management-message');
    if (!quiet || previous !== model.renderKey) await refreshPluginNavigation();
  } catch (error) {
    if (ticket === model.request) message('management-error', error.message);
  }
}
function renderPlan(plan) {
  model.plan = plan;
  model.selections = plan.operation === 'enable' ? initialSelections(plan) : {};
  $('action-targets').replaceChildren(); message('action-error');
  $('apply-action').disabled = false;
  if (plan.operation === 'enable') {
    $('action-title').textContent = '启用功能并选择授权'; $('apply-action').textContent = '确认授权并启用';
    $('action-description').textContent = '核对本次功能及其依赖需要的权限。必需项保持选中；取消可选项后，部分功能可能无法使用。';
    for (const target of plan.targets) {
      const group = node('fieldset', undefined, 'plugin-grants');
      group.append(node('legend', target.name), node('p', target.already_running
        ? '已经运行，沿用现有授权。' : target.id === plan.plugin_id ? '本次选择的功能' : '启用所需的依赖功能'));
      for (const permission of target.declared_permissions) {
        const required = target.required_permissions.includes(permission), label = node('label', undefined, 'plugin-permission-choice');
        const input = node('input'); input.type = 'checkbox'; input.checked = model.selections[target.id].has(permission);
        input.disabled = target.already_running || required;
        input.dataset.locked = String(input.disabled);
        input.addEventListener('change', () => input.checked ? model.selections[target.id].add(permission) : model.selections[target.id].delete(permission));
        const text = node('span'), [title, description] = permissionText(permission), titleNode = node('strong', title);
        if (required) titleNode.append(node('span', '必需', 'plugin-required'));
        text.append(titleNode, node('small', description)); label.append(input, text); group.append(label);
      }
      if (!target.declared_permissions.length) group.append(node('p', '此功能没有申请数据权限。'));
      $('action-targets').append(group);
    }
  } else {
    $('action-title').textContent = plan.operation === 'revoke' ? '撤销授权并停用' : '停用功能';
    $('apply-action').textContent = plan.operation === 'revoke' ? '确认撤销并停用' : '确认停用';
    $('action-description').textContent = (plan.operation === 'revoke'
      ? '撤销“' + permissionText(plan.permission)[0] + '”会停用整个功能。' : '停用选择会保留到下次启动。')
      + (plan.targets.length > 1 ? '以下依赖功能也会一并停用。' : '') + ' 已保存的原始记录和人工修正会保留。';
    for (const target of plan.targets) $('action-targets').append(node('div', target.name, 'plugin-affected'));
  }
}
async function openPlan(plugin, operation, permission, trigger) {
  if (model.busy) return;
  model.trigger = trigger; managedBusy(true); message('management-error'); message('management-message');
  try {
    const query = new URLSearchParams({operation, expected_revision: model.snapshot.revision});
    if (permission) query.set('permission', permission);
    const plan = await pluginApi('/api/plugins/' + encodeURIComponent(plugin.id) + '/plan?' + query);
    renderPlan(plan); dialog.showModal();
  } catch (error) {
    message('management-error', error.message); await refresh({quiet: true});
  } finally {
    if (!dialog.open) model.pendingFocus = true;
    managedBusy(false);
  }
}
async function apply() {
  if (model.busy || !model.plan) return;
  let request;
  try { request = operationRequest(model.plan, model.selections); } catch (error) {
    message('action-error', error.message); return;
  }
  managedBusy(true); message('action-error');
  try {
    const snapshot = await pluginApi(request.url, request);
    ++model.request; render(snapshot);
    const result = operationMessage(model.plan, snapshot);
    dialog.close(); message('management-message', result.text, result.tone);
    await refreshPluginNavigation();
  } catch (error) {
    message('action-error', error.message);
    // A lost response can follow a successful write. Refresh, never resend it.
    await refresh({quiet: true}); await refreshPluginNavigation();
    model.plan = null;
  } finally {
    managedBusy(false);
    if (!model.plan && dialog.open) {
      $('apply-action').disabled = true;
      $('cancel-action').focus();
    }
  }
}
$('refresh-plugins').addEventListener('click', () => refresh());
$('apply-action').addEventListener('click', apply);
for (const id of ['close-action', 'cancel-action']) $(id).addEventListener('click', () => {if (!model.busy) dialog.close();});
dialog.addEventListener('cancel', event => {if (model.busy) event.preventDefault();});
dialog.addEventListener('close', () => {
  model.plan = null;
  if (model.busy) model.pendingFocus = true; else restoreActionFocus();
});
window.addEventListener('focus', () => {if (!model.busy && !dialog.open) refresh({quiet: true});});
document.addEventListener('visibilitychange', () => {if (!document.hidden && !model.busy && !dialog.open) refresh({quiet: true});});
setInterval(() => {if (!document.hidden && !model.busy && !dialog.open) refresh({quiet: true});}, 15000);
refresh();
