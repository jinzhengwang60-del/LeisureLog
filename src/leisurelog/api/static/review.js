import {node, purposeLabels, contextBadges, contextRequest} from "./activity-context.js?v=3";
import {appName, ranking} from "./report-ui.js?v=motion1";

const $ = id => document.getElementById(id);
const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const nameOf = item => item.content || appName(item.app);
const shortDate = iso => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;
const weekday = iso => WEEKDAYS[(new Date(`${iso}T12:00:00+08:00`).getUTCDay() + 6) % 7];
const shift = (iso, days) => new Date(new Date(`${iso}T12:00:00+08:00`).getTime() + days * 86400000).toISOString().slice(0, 10);
function hm(value) {
  const n = Math.round((value || 0) / 60);
  if (n < 1) return value >= 1 ? "不到 1 分钟" : "0 分";
  const h = Math.floor(n / 60), m = n % 60;
  return h ? (m ? `${h} 小时 ${m} 分` : `${h} 小时`) : `${m} 分`;
}
function compare(now, before) {
  if (!before && !now) return "两周均无计入时长";
  if (!before) return "上周没有计入时长";
  const diff = now - before;
  if (Math.abs(diff) < 300 || Math.abs(diff) < before * 0.05) return "和上周差不多";
  return `比上周${diff > 0 ? "多" : "少"} ${hm(Math.abs(diff))}`;
}
let week = new URLSearchParams(location.search).get("week"), ticket = 0;

function summary(data) {
  const span = data.is_current ? "这周到目前为止" : "这一周";
  if (!data.activity_seconds) return `${span}还没有计入的电脑活动。`;
  const parts = [`${span}记录了 ${hm(data.activity_seconds)} 的电脑活动，${compare(data.activity_seconds, data.previous_activity_seconds)}。`];
  const top = data.all_top_activities[0];
  if (top) parts.push(`花时间最多的是「${nameOf(top)}」，${hm(top.active_seconds)}，在 ${top.days} 天出现过。`);
  if (data.project_count) parts.push(`活动涉及 ${data.project_count} 个项目。`);
  return parts.join("");
}

function renderDays(data) {
  const box = $("days"); box.replaceChildren();
  const max = Math.max(1, ...data.all_days.map(d => d.active_seconds));
  for (const day of data.all_days) {
    const column = node(day.future ? "div" : "a", undefined, `trend-column${day.future ? " future" : ""}`);
    if (!day.future) { column.href = `/?day=${day.day}`; column.title = `${day.day} 活动 ${hm(day.active_seconds)}`; }
    column.append(node("span", day.future ? "" : day.active_seconds ? hm(day.active_seconds) : "无记录", "trend-value"));
    const stack = node("div", undefined, "trend-stack"); stack.style.height = `${day.active_seconds / max * 145}px`;
    for (const [purpose, seconds] of Object.entries(day.purpose_seconds).sort((a, b) => b[1] - a[1])) {
      const part = node("span", undefined, `trend-segment purpose-${purpose}`);
      part.style.height = `${seconds / (day.active_seconds || 1) * 100}%`; part.title = `${purposeLabels[purpose]} ${hm(seconds)}`; stack.append(part);
    }
    if (!day.active_seconds) stack.className = "trend-missing";
    const tag = node("span", weekday(day.day), "trend-label"); tag.append(node("small", ` ${shortDate(day.day)}`));
    column.append(stack, tag); box.append(column);
  }
}

function renderLists(data) {
  const top = $("top"); top.replaceChildren();
  const max = Math.max(1, ...data.all_top_activities.map(a => a.active_seconds));
  for (const item of data.all_top_activities) {
    const row = node("div", undefined, "rank-row"), heading = node("div", undefined, "rank-heading");
    const title = node("span", nameOf(item), "rank-name");
    title.append(contextBadges({purpose: item.purpose, project_id: item.project_id}, data.project_options));
    heading.append(title, node("span", hm(item.active_seconds), "rank-value"));
    const track = node("div", undefined, "rank-track"), fill = node("div", undefined, `rank-fill purpose-${item.purpose}`);
    fill.style.width = `${item.active_seconds / max * 100}%`; track.append(fill); row.append(heading, track); top.append(row);
  }
  if (!data.all_top_activities.length) top.append(node("p", "这一周没有超过 1 分钟的活动。", "empty"));
  const purposes = $("categories"); purposes.replaceChildren();
  const keys = new Set([...Object.keys(data.purpose_seconds), ...Object.keys(data.previous_purpose_seconds)]);
  const rows = [...keys].map(key => ({purpose: key, active_seconds: data.purpose_seconds[key] || 0, before: data.previous_purpose_seconds[key] || 0}))
    .filter(row => row.active_seconds || row.before).sort((a, b) => b.active_seconds - a.active_seconds);
  ranking(purposes, rows, row => `${purposeLabels[row.purpose] || row.purpose} · ${compare(row.active_seconds, row.before)}`);
  const range = {start: data.week_start, end: data.week_end};
  const name = id => data.project_options.find(p => p.id === id)?.name || "未关联项目";
  ranking($("projects"), data.project_seconds.sort((a, b) => b.active_seconds - a.active_seconds), row => name(row.project_id), {
    color: row => data.project_options.find(p => p.id === row.project_id)?.color || "var(--muted)",
    denominator: data.activity_seconds,
    link: row => row.project_id ? `/projects?${new URLSearchParams({...range, project_id: row.project_id})}`
      : `/statistics?${new URLSearchParams({...range, project_id: "none"})}`,
  });
  $("project-link").href = `/projects?${new URLSearchParams(range)}`;
}

function render(data) {
  week = data.week_start;
  $("week-title").textContent = data.is_current ? "这一周" : `${shortDate(week)} – ${shortDate(data.week_end)}`;
  $("week-label").textContent = `每周回顾 · ${week} 至 ${data.week_end}`;
  document.title = `${shortDate(week)}–${shortDate(data.week_end)} · 每周回顾 · LeisureLog`;
  $("summary").textContent = summary(data); $("leisure").textContent = hm(data.activity_seconds);
  $("leisure-compare").textContent = `${compare(data.activity_seconds, data.previous_activity_seconds)}（上周 ${hm(data.previous_activity_seconds)}）`;
  const days = data.all_days.filter(d => !d.future && d.active_seconds > 0).length;
  $("daily").textContent = days ? hm(data.activity_seconds / days) : "—";
  $("daily-note").textContent = days ? `${days} 天有计入的活动` : "这一周没有计入的活动";
  $("pending").textContent = hm(data.purpose_unknown_seconds);
  $("pending-note").textContent = data.purpose_unknown_seconds > 0 ? "可在活动详情中指定用途" : "已有用途判断";
  $("project-count").textContent = data.project_count;
  renderDays(data); renderLists(data);
  $("next-week").disabled = !data.has_next; $("this-week").disabled = data.is_current;
  const url = new URL(location.href); if (data.is_current) url.searchParams.delete("week"); else url.searchParams.set("week", week);
  history.replaceState({}, "", url);
}

async function load(day) {
  const current = ++ticket; let succeeded = false; $("error").hidden = true;
  document.querySelectorAll(".week-nav button").forEach(b => { b.disabled = true; });
  try { const data = await contextRequest(`/api/review${day ? `?day=${day}` : ""}`); if (current === ticket) { render(data); succeeded = true; } }
  catch (error) { if (current === ticket) { $("error").textContent = error.message; $("error").hidden = false; } }
  finally { if (current === ticket) { $("previous-week").disabled = !week; if (!succeeded) $("this-week").disabled = false; } }
}
$("previous-week").onclick = () => load(shift(week, -7)); $("next-week").onclick = () => load(shift(week, 7)); $("this-week").onclick = () => load(null);
load(week && /^\d{4}-\d{2}-\d{2}$/.test(week) ? week : null);
