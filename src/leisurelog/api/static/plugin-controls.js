// Pure management logic shared by the page and its behavior checks.
export const PERMISSIONS = {
  'activity.summary.read': ['读取活动汇总', '查看按日期、类别、用途和项目汇总的时长。'],
  'activity.details.read': ['读取活动详情', '允许读取应用、窗口标题和网页地址等详情，实际范围由功能接口限制。'],
  'classification.propose': ['提供自动分类建议', '参与活动识别；你保存的人工修正保持优先。'],
  'games.catalog.read': ['读取已保存的游戏资料', '使用已导入的名称、标签与识别信息。'],
  'games.catalog.propose': ['更新本地游戏资料', '提交游戏名称、标签与识别信息，由核心校验后保存。'],
  'games.statistics.read': ['读取游戏统计', '查看游戏的累计时长、记录日期与类型信息。'],
  'games.types.write': ['保存人工游戏类型', '保存或恢复你选择的主类型与标签，同时需要读取活动详情。'],
  'files.import': ['读取接入文件', '从已配置的本地位置读取导出资料。'],
  'files.export': ['导出文件', '将数据写入文件；当前版本尚未开放此能力。'],
  'network.request': ['访问外部网络', '向外部服务发出请求；当前版本尚未开放此能力。'],
};
export const CAPABILITIES = {
  'game-catalog': '游戏资料', classifier: '自动识别', analytics: '分析报告',
  page: '功能页面', task: '后台任务', source: '活动来源', theme: '界面风格',
};

export function permissionText(value) { return PERMISSIONS[value] || [value, '请核对该权限的用途。']; }
function stoppedAfterTimeout(plugin) {
  return plugin.state === 'failed' && plugin.last_error?.code === 'stop_timeout'
    && !plugin.enabled && !plugin.workers?.some(worker => worker.running);
}
export function needsAttention(plugin) {
  return Boolean(plugin.catalog_error) || plugin.state === 'unavailable'
    || (plugin.state === 'failed' && !stoppedAfterTimeout(plugin));
}
export function issueText(plugin, issue) {
  return issue.code === 'stop_timeout' && stoppedAfterTimeout(plugin)
    ? '上次停用超过等待时间；当前已确认旧任务退出。' : issue.message;
}
export function stateText(plugin) {
  if (plugin.state === 'failed' && plugin.workers?.some(worker => worker.running)) return '等待任务退出';
  if (stoppedAfterTimeout(plugin)) return '已停止';
  return ({running: '已启用', disabled: '已停用', starting: '正在启动', stopping: '正在停用',
    failed: '运行异常', unavailable: '暂不可用'})[plugin.state] || '状态待确认';
}
export function stateDescription(plugin) {
  if (plugin.state === 'running') return '本次已经正常启用。';
  if (plugin.state === 'disabled') return '下次启动仍会保留停用选择。';
  if (stoppedAfterTimeout(plugin)) return '旧任务已退出，可重新选择授权启用。';
  if (plugin.state === 'failed' && plugin.workers?.some(worker => worker.running)) {
    return '相关功能已撤下；旧任务退出前不能重新启用。';
  }
  return plugin.enabled ? '已保存启用选择，但本次尚未正常运行。' : '当前没有运行，可核对原因后再启用。';
}

function checkedPlan(plan) {
  const id = value => typeof value === 'string' && value.length <= 100
    && /^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$/.test(value);
  if (!plan || typeof plan !== 'object' || !Number.isSafeInteger(plan.revision) || plan.revision < 0 || !id(plan.plugin_id)
      || !['enable', 'disable', 'revoke'].includes(plan.operation)
      || !Array.isArray(plan.targets) || !plan.targets.length || plan.targets.length > 64
      || plan.targets.some(target => !id(target.id))
      || new Set(plan.targets.map(target => target.id)).size !== plan.targets.length
      || !plan.targets.some(target => target.id === plan.plugin_id)) {
    throw new Error('操作计划不完整，请重新核对。');
  }
}

export function initialSelections(plan) {
  checkedPlan(plan);
  return Object.fromEntries(plan.targets.map(target => [target.id,
    new Set(target.already_running ? target.default_grants
      : [...target.default_grants, ...target.required_permissions]),
  ]));
}

export function operationRequest(plan, selections = {}) {
  checkedPlan(plan);
  const base = '/api/plugins/' + encodeURIComponent(plan.plugin_id);
  if (plan.operation === 'disable') return {url: base + '/disable', method: 'POST', body: {
    expected_revision: plan.revision, cascade: plan.targets.length > 1,
  }};
  if (plan.operation === 'revoke') {
    if (typeof plan.permission !== 'string' || !PERMISSIONS[plan.permission]) {
      throw new Error('撤销权限无效，请重新核对。');
    }
    return {url: base + '/permissions/' + encodeURIComponent(plan.permission)
      + '?expected_revision=' + plan.revision, method: 'DELETE'};
  }
  if (Object.keys(selections).some(id => !plan.targets.some(target => target.id === id))) {
    throw new Error('不能为这次操作之外的功能授权。');
  }
  const grants = {};
  for (const target of plan.targets) {
    const selected = [...(selections[target.id] || [])];
    if (new Set(selected).size !== selected.length
        || selected.some(value => !target.declared_permissions.includes(value))
        || target.required_permissions.some(value => !selected.includes(value))) {
      throw new Error('请保留必需权限，并核对本次授权。');
    }
    if (target.already_running && (selected.length !== target.default_grants.length
        || target.default_grants.some(value => !selected.includes(value)))) {
      throw new Error('正在运行的依赖需要保留现有授权。');
    }
    if (selected.includes('games.types.write') && !selected.includes('activity.details.read')) {
      throw new Error('保存人工游戏类型还需要“读取活动详情”权限。');
    }
    grants[target.id] = selected;
  }
  return {url: base + '/enable', method: 'POST', body: {grants, expected_revision: plan.revision}};
}

export function operationMessage(plan, snapshot) {
  if (!Array.isArray(snapshot?.plugins)) return {tone: 'warning', text: '未能核对操作结果，请刷新状态。'};
  const targets = snapshot.plugins.filter(plugin => plan.targets.some(target => target.id === plugin.id));
  if (plan.operation === 'enable') {
    const failed = targets.find(plugin => plugin.state !== 'running');
    return failed || targets.length !== plan.targets.length ? {tone: 'warning', text: '启用选择已保存，但功能尚未正常运行。请查看下方原因。'}
      : {tone: 'success', text: '已启用所选功能，授权已保存。'};
  }
  if (targets.some(plugin => plugin.workers?.some(worker => worker.running))) {
    return {tone: 'warning', text: '已撤下功能并保存停用选择。仍有任务尚未退出，暂时不能重新启用。'};
  }
  return {tone: 'success', text: plan.operation === 'revoke'
    ? '已撤销授权并停用相关功能。记录和人工修正已保留。'
    : '已保存停用选择。记录和人工修正已保留。'};
}

export class PluginApiError extends Error {
  constructor(message, code = '', uncertain = false) { super(message); this.code = code; this.uncertain = uncertain; }
}
export async function pluginApi(url, request = {}, fetcher = fetch) {
  const mutation = request.method && request.method !== 'GET';
  let response;
  try {
    response = await fetcher(url, {cache: 'no-store', method: request.method || 'GET',
      signal: typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(15000) : undefined,
      headers: request.body === undefined ? undefined : {'Content-Type': 'application/json'},
      body: request.body === undefined ? undefined : JSON.stringify(request.body),
    });
  } catch {
    throw new PluginApiError(mutation ? '没有收到操作结果。正在读取最新状态，请核对后再操作。'
      : '暂时无法连接 LeisureLog。显示的可能是上次读取的状态，请稍后刷新。', '', Boolean(mutation));
  }
  let data;
  try { data = await response.json(); } catch {
    throw new PluginApiError('未能读取操作结果，请刷新核对。', '', Boolean(mutation));
  }
  if (!response.ok) {
    const detail = data.detail, code = detail?.code || '';
    const message = code === 'configuration_conflict' ? '插件设置已变化，请重新核对后再操作。'
      : typeof detail?.message === 'string' ? detail.message
      : typeof detail === 'string' ? detail : '请求未能完成，请刷新核对设置。';
    throw new PluginApiError(message, code);
  }
  return data;
}
