import {gameAccess, gameRequest, readGameAccess} from './game-access.js';

const $ = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const duration = value => {
  const n = Math.round(value || 0);
  return n < 60 ? n + ' 秒' : n < 3600 ? Math.floor(n / 60) + ' 分 ' + n % 60 + ' 秒'
    : Math.floor(n / 3600) + ' 小时 ' + Math.floor(n % 3600 / 60) + ' 分';
};
const date = value => value ? new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date(value)) : '暂无记录';
const clock = value => new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(value));
let offset = 0, dayOffset = 0, key = null, version = 0, total = 0, typeOptions = null;
let access = gameAccess(null), displayedType = null, writing = false;
const limit = 50, dayLimit = 30, preferenceRange = {};
const initialParams = new URLSearchParams(location.search);
for (const field of ['start', 'end']) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(initialParams.get(field) || '')) {
    preferenceRange[field] = initialParams.get(field);
  }
}
if (preferenceRange.start && preferenceRange.end) {
  for (const anchor of document.querySelectorAll('a[href="/game-preferences"]')) {
    anchor.href = '/game-preferences?' + new URLSearchParams(preferenceRange);
  }
}
function editControls() {
  $('type-form').hidden = !access.edit;
  for (const id of ['primary-type', 'type-tags', 'save-type']) $(id).disabled = !access.edit || writing;
  $('reset-type').disabled = !access.edit || writing || displayedType?.source !== 'manual';
}
async function refreshAccess(ticket) {
  const next = await readGameAccess();
  if (ticket !== version) return null;
  access = next;
  $('game-access-message').textContent = access.message;
  $('game-access-note').hidden = !access.message;
  editControls();
  return access;
}
function state(item) {
  return item.in_catalog ? item.installed
    ? item.matches.length ? '已安装 · 有识别依据' : '已安装 · 待补充识别依据'
    : '库条目 · 未安装' : item.app ? '历史游戏记录 · ' + item.app : '历史游戏记录';
}
function link(text, parameters) {
  const anchor = node('a', text); anchor.href = '/?' + new URLSearchParams(parameters);
  return anchor;
}
function showCatalog() {
  key = null; dayOffset = 0;
  $('detail').hidden = true; $('catalog').hidden = false;
  const range = new URLSearchParams(preferenceRange).toString();
  history.replaceState(null, '', '/games' + (range ? '?' + range : ''));
}
function renderList(data) {
  total = data.total;
  $('total').textContent = total;
  $('recorded-games').textContent = data.recorded_games;
  $('total-time').textContent = duration(data.active_seconds);
  $('rows').replaceChildren();
  for (const item of data.items) {
    const row = node('tr'), name = node('td');
    const title = node(access.details ? 'button' : 'span', item.name, 'library-title game-title');
    if (access.details) title.onclick = () => openDetail(item.key);
    name.append(title, node('div', item.sessions ? item.sessions + ' 个游玩片段' : '暂无游玩记录', 'game-state'));
    name.append(node('div', '主类型：' + item.game_type.label
      + (item.game_type.source === 'manual' ? ' · 人工' : ''), 'game-state'));
    row.append(name, node('td', state(item)), node('td', item.sessions ? duration(item.active_seconds) : '暂无记录', 'num'),
      node('td', item.sessions ? item.days : '—', 'num'), node('td', date(item.last_seen)));
    $('rows').append(row);
  }
  $('empty').hidden = total !== 0;
  $('page-label').textContent = total ? (offset + 1) + '–' + Math.min(offset + limit, total)
    + ' / 共 ' + total + ' 个条目' : '共 0 个条目';
  $('previous').disabled = !offset; $('next').disabled = offset + limit >= total;
}
async function load() {
  const ticket = ++version;
  $('loading').hidden = false; $('error').hidden = true;
  try {
    const current = await refreshAccess(ticket);
    if (!current) return;
    if (current.known && !current.available) {
      $('rows').replaceChildren(); $('empty').hidden = true;
      for (const id of ['total', 'recorded-games', 'total-time']) $(id).textContent = '—';
      $('page-label').textContent = '当前功能不可用';
      $('previous').disabled = true; $('next').disabled = true; return;
    }
    const data = await gameRequest('/api/game-statistics?' + new URLSearchParams({
      query: $('search').value, scope: $('scope').value, sort: $('sort').value, limit, offset,
    }));
    if (ticket !== version) return;
    if (offset && offset >= data.total) {offset = 0; return load();}
    renderList(data);
  } catch (error) {
    if (ticket === version) {$('error').textContent = error.message; $('error').hidden = false;}
  } finally {if (ticket === version) $('loading').hidden = true;}
}
function bars(container, rows) {
  container.replaceChildren();
  if (!rows.length) {container.append(node('p', '暂无游玩记录', 'no-data')); return;}
  const max = Math.max(...rows.map(row => row.active_seconds), 1);
  for (const row of rows) {
    const line = node('div', undefined, 'month'), track = node('div', undefined, 'month-track');
    const fill = node('div', undefined, 'month-fill');
    fill.style.width = row.active_seconds / max * 100 + '%'; track.append(fill);
    line.append(node('span', row.month), track, node('span', duration(row.active_seconds), 'month-value'));
    container.append(line);
  }
}
function renderType(item) {
  displayedType = item.game_type;
  const type = displayedType;
  $('type-info').textContent = '当前主类型：' + type.label + ' · '
    + (type.source === 'manual' ? '人工选择，优先保留' : '自动建议') + ' · 自动参考：' + type.automatic_label;
  $('source-tags').textContent = '来源标签：' + (type.source_tags.join('、') || '暂无来源标签');
  $('type-tags-summary').textContent = '补充标签：' + (type.tags.join('、') || '暂无补充标签');
  $('type-tags-summary').hidden = access.edit;
  if (access.edit) {
    $('primary-type').replaceChildren();
    for (const option of typeOptions) {
      const field = node('option', option.label); field.value = option.id;
      $('primary-type').append(field);
    }
    $('primary-type').value = type.primary; $('type-tags').value = type.tags.join('\n');
  }
  editControls(); $('type-message').hidden = true;
}
function renderDetail(data) {
  const item = data.item;
  renderType(item);
  $('detail-name').textContent = item.name; $('detail-state').textContent = state(item);
  $('seen').textContent = item.sessions ? '首次记录 ' + date(item.first_seen) + ' · 最近游玩 ' + date(item.last_seen)
    : '尚未采集到这款游戏的游玩记录';
  for (const [id, value] of [['active', duration(item.active_seconds)], ['raw', duration(item.recorded_seconds)],
    ['days-count', item.days], ['sessions-count', item.sessions]]) $(id).textContent = value;
  $('no-history').hidden = Boolean(item.sessions);
  $('no-history').textContent = item.matches.length
    ? '暂无游玩记录。游戏资料已经接入；正常游玩并同步后，记录会逐步出现。'
    : '暂无游玩记录。这个库条目尚未配置游戏识别依据。';
  $('timing').textContent = '检测到离开 ' + duration(item.detected_afk_seconds)
    + ' · 策略保留 ' + duration(item.retained_afk_seconds) + ' · 实际扣除 ' + duration(item.afk_seconds)
    + ' · 状态待确认 ' + duration(item.unverified_seconds);
  bars($('months'), data.months);
  $('day-rows').replaceChildren();
  const max = Math.max(...data.days.map(day => day.active_seconds), 1);
  for (const day of data.days) {
    const row = node('tr'), name = node('td'), chart = node('td');
    const track = node('div', undefined, 'daily-track'), fill = node('div', undefined, 'daily-fill');
    fill.style.width = day.active_seconds / max * 100 + '%'; track.title = duration(day.active_seconds);
    track.append(fill); chart.append(track); name.append(link(day.day, {day: day.day}));
    row.append(name, chart, node('td', duration(day.recorded_seconds), 'num'),
      node('td', duration(day.active_seconds), 'num'), node('td', duration(day.afk_seconds), 'num'));
    $('day-rows').append(row);
  }
  $('day-label').textContent = data.day_total ? (dayOffset + 1) + '–' + Math.min(dayOffset + dayLimit, data.day_total)
    + ' / ' + data.day_total + ' 个有记录日期' : '暂无游玩记录';
  $('day-previous').disabled = !dayOffset; $('day-next').disabled = dayOffset + dayLimit >= data.day_total;
  $('recent').replaceChildren();
  for (const session of data.recent_sessions) {
    const entry = node('div', undefined, 'recent-entry');
    entry.append(link(date(session.start_time) + ' ' + clock(session.start_time) + ' – '
      + date(session.end_time) + ' ' + clock(session.end_time) + ' · 查看记录依据',
    {day: session.day, session: session.id, app: session.app}),
    node('p', '计入 ' + duration(session.active_seconds) + ' · 原始 ' + duration(session.recorded_seconds) + ' · ' + session.app),
    node('p', session.title || '无窗口标题'));
    $('recent').append(entry);
  }
  if (!data.recent_sessions.length) $('recent').append(node('p', '暂无游玩片段', 'no-data'));
  $('detail').hidden = false;
}
async function openDetail(newKey, reset = true) {
  const ticket = ++version;
  $('loading').hidden = false; $('error').hidden = true;
  try {
    const current = await refreshAccess(ticket);
    if (!current) return;
    if (!current.details) {showCatalog(); return load();}
    key = newKey;
    if (reset) dayOffset = 0;
    $('catalog').hidden = true; $('detail').hidden = true;
    history.replaceState(null, '', '/games?' + new URLSearchParams({game: key, ...preferenceRange}));
    const data = await gameRequest('/api/game-statistics/' + encodeURIComponent(key) + '?'
      + new URLSearchParams({limit: dayLimit, offset: dayOffset}));
    if (ticket !== version) return;
    if (dayOffset && dayOffset >= data.day_total) {dayOffset = 0; return openDetail(key, false);}
    if (access.edit && !typeOptions) typeOptions = (await gameRequest('/api/game-types')).types;
    if (ticket === version) renderDetail(data);
  } catch (error) {
    if (ticket === version) {
      $('error').textContent = error.message; $('error').hidden = false; showCatalog();
    }
  } finally {if (ticket === version) $('loading').hidden = true;}
}
async function changeType(reset) {
  const target = key;
  if (!target || writing) return;
  const body = {primary: $('primary-type').value,
    tags: $('type-tags').value.split(/\r?\n/).map(tag => tag.trim()).filter(Boolean)};
  writing = true; editControls();
  $('type-message').hidden = false; $('type-message').textContent = '正在保存…';
  try {
    const current = await refreshAccess(version);
    if (!current || key !== target) return;
    if (!current.edit) throw new Error(current.message);
    await gameRequest('/api/game-types/' + encodeURIComponent(target), reset ? {method: 'DELETE'} : {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    if (key === target) {
      await openDetail(target, false);
      if (key === target) {
        $('type-message').textContent = reset ? '已恢复自动类型；历史类型统计已更新。'
          : '类型与标签已保存；历史类型统计已更新。';
        $('type-message').hidden = false;
      }
    }
  } catch (error) {
    if (key === target) {
      await refreshAccess(version);
      $('type-message').textContent = error.message; $('type-message').hidden = false;
    }
  } finally {writing = false; editControls();}
}
$('filters').onsubmit = event => {event.preventDefault(); offset = 0; load();};
$('refresh').onclick = load;
$('previous').onclick = () => {offset = Math.max(0, offset - limit); load();};
$('next').onclick = () => {offset += limit; load();};
$('back').onclick = () => {showCatalog(); load();};
$('detail-refresh').onclick = () => openDetail(key, false);
$('day-previous').onclick = () => {dayOffset = Math.max(0, dayOffset - dayLimit); openDetail(key, false);};
$('day-next').onclick = () => {dayOffset += dayLimit; openDetail(key, false);};
$('type-form').onsubmit = event => {event.preventDefault(); changeType(false);};
$('reset-type').onclick = () => changeType(true);
const initial = initialParams.get('game');
if (initial) openDetail(initial); else load();
