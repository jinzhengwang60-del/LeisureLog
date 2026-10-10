import {categoryLabels} from "/static/correction.js?v=system1";

const $ = id => document.getElementById(id);
const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const label = key => categoryLabels[key] || key;
const appName = app => ({"chrome.exe": "Chrome", "msedge.exe": "Microsoft Edge", "Weixin.exe": "微信", "QQ.exe": "QQ"})[app] || (app || "").replace(/\.exe$/i, "");
const nameOf = item => item.content || appName(item.app);

function node(tag, text, cls) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (cls) element.className = cls;
  return element;
}
function hm(value) {
  const n = Math.round((value || 0) / 60);
  if (n < 1) return value >= 1 ? "不到 1 分钟" : "0 分";
  const h = Math.floor(n / 60), m = n % 60;
  return h ? (m ? `${h} 小时 ${m} 分` : `${h} 小时`) : `${m} 分`;
}
const shortDate = iso => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;
const weekday = iso => WEEKDAYS[(new Date(`${iso}T12:00:00+08:00`).getUTCDay() + 6) % 7];
const shift = (iso, days) => new Date(new Date(`${iso}T12:00:00+08:00`).getTime() + days * 86400000).toISOString().slice(0, 10);
function compare(now, before, unit = "上周") {
  if (!before && !now) return `和${unit}一样，都没有记录`;
  if (!before) return `${unit}没有记录`;
  const diff = now - before;
  if (Math.abs(diff) < 300 || Math.abs(diff) < before * 0.05) return `和${unit}差不多`;
  return `比${unit}${diff > 0 ? "多" : "少"} ${hm(Math.abs(diff))}`;
}

let week = new URLSearchParams(location.search).get("week");
let ticket = 0;

function summary(data) {
  const parts = [];
  const span = data.is_current ? "这周到目前为止" : "这一周";
  if (!data.leisure_seconds) return `${span}还没有娱乐记录。`;
  parts.push(`${span}一共娱乐了 ${hm(data.leisure_seconds)}，${compare(data.leisure_seconds, data.previous_leisure_seconds)}。`);
  const top = data.top_activities[0];
  if (top) parts.push(`花时间最多的是「${nameOf(top)}」，${hm(top.active_seconds)}，有 ${top.days} 天在玩。`);
  if (data.busiest_day) parts.push(`${weekday(data.busiest_day.day)}是玩得最多的一天（${hm(data.busiest_day.leisure_seconds)}）。`);
  const fresh = data.top_activities.filter(item => item.new).map(nameOf);
  if (fresh.length) parts.push(`新出现的有：${fresh.slice(0, 3).join("、")}。`);
  return parts.join("");
}

function renderDays(data) {
  const box = $("days");
  box.replaceChildren();
  const max = Math.max(1, ...data.days.map(d => d.groups ? d.groups.leisure : 0));
  for (const day of data.days) {
    const leisure = day.groups ? day.groups.leisure : 0;
    const column = day.future ? node("div", undefined, "trend-column future") : node("a", undefined, "trend-column");
    if (!day.future) { column.href = `/?day=${day.day}`; column.title = `${day.day} 娱乐 ${hm(leisure)}`; }
    const compact = leisure >= 3600 ? `${(leisure / 3600).toFixed(1)} 小时` : hm(leisure);
    column.append(node("span", day.future ? "" : (leisure ? compact : "—"), "trend-value"));
    const stack = node("div", undefined, "trend-stack");
    stack.style.height = `${leisure / max * 100}%`;
    const parts = Object.entries(day.leisure_by_category).sort((a, b) => b[1] - a[1]);
    for (const [category, seconds] of parts) {
      const segment = node("span", undefined, `trend-segment cat-${category}`);
      segment.style.height = `${seconds / (leisure || 1) * 100}%`;
      segment.title = `${label(category)} ${hm(seconds)}`;
      stack.append(segment);
    }
    if (!leisure) stack.className = "trend-missing";
    const tag = node("span", weekday(day.day), "trend-label");
    tag.append(node("small", ` ${shortDate(day.day)}`));
    column.append(stack, tag);
    if (data.busiest_day && data.busiest_day.day === day.day) column.classList.add("busiest");
    box.append(column);
  }
}

function rankRow(name, value, share, category, extra) {
  const row = node("div", undefined, "rank-row");
  const heading = node("div", undefined, "rank-heading");
  const title = node("span", undefined, "rank-name");
  title.append(node("i", undefined, `rank-dot cat-${category}`), document.createTextNode(name));
  if (extra) title.append(extra);
  heading.append(title, node("span", value, "rank-value"));
  const track = node("div", undefined, "rank-track"), fill = node("div", undefined, `rank-fill ${category}`);
  fill.style.width = `${Math.max(share * 100, 1)}%`;
  track.append(fill);
  row.append(heading, track);
  return row;
}

function renderLists(data) {
  const top = $("top");
  top.replaceChildren();
  const max = Math.max(1, ...data.top_activities.map(a => a.active_seconds));
  for (const item of data.top_activities) {
    const tags = node("span", undefined, "rank-tags");
    tags.append(node("small", `${label(item.category)} · ${item.days} 天`));
    if (item.new) tags.append(node("b", "新", "new-tag"));
    top.append(rankRow(nameOf(item), hm(item.active_seconds), item.active_seconds / max, item.category, tags));
  }
  if (!data.top_activities.length) top.append(node("p", "这一周没有超过 1 分钟的娱乐活动。", "empty"));

  const box = $("categories");
  box.replaceChildren();
  const keys = new Set([...Object.keys(data.leisure_by_category), ...Object.keys(data.previous_leisure_by_category)]);
  const rows = [...keys].map(key => [key, data.leisure_by_category[key] || 0, data.previous_leisure_by_category[key] || 0])
    .filter(([, now, before]) => now >= 60 || before >= 60).sort((a, b) => b[1] - a[1]);
  const top2 = Math.max(1, ...rows.map(r => r[1]));
  for (const [key, now, before] of rows) {
    const delta = node("small", compare(now, before), now > before ? "delta more" : now < before ? "delta less" : "delta");
    box.append(rankRow(label(key), hm(now), now / top2, key, delta));
  }
  if (!rows.length) box.append(node("p", "这一周和上周都没有娱乐记录。", "empty"));
}

function render(data) {
  week = data.week_start;
  const end = data.week_end;
  $("week-title").textContent = data.is_current ? "这一周" : `${shortDate(data.week_start)} – ${shortDate(end)}`;
  $("week-label").textContent = `每周回顾 · ${data.week_start} 至 ${end}`;
  document.title = `${shortDate(data.week_start)}–${shortDate(end)} · 每周回顾 · LeisureLog`;
  $("summary").textContent = summary(data);
  $("leisure").textContent = hm(data.leisure_seconds);
  $("leisure-compare").textContent = `${compare(data.leisure_seconds, data.previous_leisure_seconds)}（上周 ${hm(data.previous_leisure_seconds)}）`;
  const days = data.days_with_records;
  $("daily").textContent = days ? hm(data.leisure_seconds / days) : "—";
  $("daily-note").textContent = days ? `${days} 天有记录` : "这一周没有记录";
  const longest = data.longest_session;
  $("longest").textContent = longest ? hm(longest.active_seconds) : "—";
  $("longest-note").textContent = longest ? `${nameOf(longest)} · ${weekday(longest.start_time.slice(0, 10))} ${new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false}).format(new Date(longest.start_time))} 开始` : "没有娱乐记录";
  $("late").textContent = hm(data.late_night_seconds);
  $("late-note").textContent = data.late_night_seconds >= 60 ? "零点到五点之间" : "这周没有熬夜娱乐";
  renderDays(data);
  renderLists(data);
  $("next-week").disabled = !data.has_next;
  $("this-week").disabled = data.is_current;
  const url = new URL(location.href);
  if (data.is_current) url.searchParams.delete("week"); else url.searchParams.set("week", data.week_start);
  history.replaceState({}, "", url);
}

async function load(day) {
  const request = ++ticket;
  $("error").hidden = true;
  document.querySelectorAll(".week-nav button").forEach(b => { b.disabled = true; });
  try {
    const response = await fetch(`/api/review${day ? `?day=${day}` : ""}`);
    if (!response.ok) throw new Error("读取失败，请确认 LeisureLog 正在运行。");
    const data = await response.json();
    if (request === ticket) render(data);
  } catch (error) {
    if (request === ticket) { $("error").textContent = error.message; $("error").hidden = false; }
  } finally {
    if (request === ticket) $("previous-week").disabled = false;
  }
}

$("previous-week").onclick = () => load(shift(week, -7));
$("next-week").onclick = () => load(shift(week, 7));
$("this-week").onclick = () => load(null);
load(week && /^\d{4}-\d{2}-\d{2}$/.test(week) ? week : null);
