// Presentation uses actual grants; the host remains authoritative for every request.
const OWNER = 'leisurelog.game-analysis';
const SUMMARY = 'activity.summary.read', STATS = 'games.statistics.read';
const DETAILS = 'activity.details.read', WRITE = 'games.types.write';
const UNKNOWN = Object.freeze({known: false, available: false, details: false, edit: false,
  message: '暂时无法确认功能授权，仅显示游戏汇总。请刷新或在插件管理中核对授权。'});

export function gameAccess(snapshot) {
  if (!Array.isArray(snapshot?.plugins)) return UNKNOWN;
  const plugin = snapshot.plugins.find(item => item?.id === OWNER);
  if (plugin && (!Array.isArray(plugin.permissions)
      || plugin.permissions.some(value => typeof value !== 'string'))) return UNKNOWN;
  const grants = new Set(plugin?.permissions || []);
  const available = plugin?.state === 'running' && grants.has(SUMMARY) && grants.has(STATS);
  const details = Boolean(available && grants.has(DETAILS));
  const edit = Boolean(details && grants.has(WRITE));
  return Object.freeze({known: true, available: Boolean(available), details, edit,
    message: !available ? '游戏分析当前未启用或授权不完整。可在插件管理中查看状态。'
      : !details ? '当前只读取游戏统计；查看游玩明细需在插件管理中授权读取活动详情。'
      : !edit ? '当前可查看明细；修改游戏类型需在插件管理中授权保存人工游戏类型。' : ''});
}

export async function gameRequest(path, request = {}, fetcher = fetch) {
  const write = Boolean(request.method && request.method !== 'GET');
  let response;
  try {
    response = await fetcher(path, {...request, cache: 'no-store',
      signal: typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
        ? AbortSignal.timeout(15000) : undefined});
  } catch {
    throw new Error(write ? '没有收到保存结果，请刷新核对后再操作。'
      : '暂时无法连接 LeisureLog，请检查服务后刷新。');
  }
  let data;
  try { data = await response.json(); } catch {
    throw new Error(write ? '未能读取保存结果，请刷新核对后再操作。' : '未能读取游戏数据，请刷新后重试。');
  }
  if (!response.ok) {
    const message = response.status === 403 || response.status === 503
      ? '游戏功能已停用、授权不足或暂时不可用，可前往插件管理核对。'
      : response.status === 404 ? '游戏记录已变化，请返回列表刷新。'
      : typeof data.detail === 'string' ? data.detail : '请求未完成，请核对输入或刷新后重试。';
    throw new Error(message);
  }
  return data;
}

export async function readGameAccess(fetcher = fetch) {
  try { return gameAccess(await gameRequest('/api/plugins', {}, fetcher)); }
  catch { return UNKNOWN; }
}

export function gameLink(document, item, access, range = {}) {
  const element = document.createElement(access.details ? 'a' : 'span');
  element.textContent = item.name;
  if (access.details) element.href = '/games?' + new URLSearchParams({game: item.key, ...range});
  return element;
}
