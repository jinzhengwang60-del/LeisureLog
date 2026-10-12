// Day ribbon: a 0–24h planner strip with one coloured block per activity session.
import {categoryLabels} from "/static/correction.js?v=activity2";
import {purposeLabels} from "./activity-context.js?v=2";

const DAY_MS = 86400000;
const names = {"chrome.exe":"Chrome","msedge.exe":"Microsoft Edge","ChatGPT.exe":"ChatGPT","explorer.exe":"文件管理器","QQ.exe":"QQ","Weixin.exe":"微信","LockApp.exe":"锁屏","WindowsTerminal.exe":"终端"};
const clock = ms => new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(ms));
const weekdays = ["星期日","星期一","星期二","星期三","星期四","星期五","星期六"];
let ticket = 0, cachedKey = "", cachedItems = [];

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}

export function duration(value) {
  const n = Math.round(value || 0);
  if (n < 60) return `${n} 秒`;
  const h = Math.floor(n / 3600), m = Math.floor(n % 3600 / 60);
  return h ? `${h} 小时 ${m} 分` : `${m} 分`;
}

export function titleDay(day, todayText) {
  const [y, m, d] = day.split("-").map(Number);
  const weekday = weekdays[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  const title = document.getElementById("day-title");
  const sub = document.getElementById("day-weekday");
  const thisYear = todayText.slice(0, 4) === String(y);
  title.textContent = `${thisYear ? "" : y + "年"}${m}月${d}日`;
  sub.textContent = day === todayText ? `${weekday} · 今天` : weekday;
  document.title = `${m}月${d}日 · LeisureLog`;
}

async function fetchAll(params) {
  const response = await fetch(`/api/dashboard/ribbon?${new URLSearchParams(params)}`, {cache: "no-store"});
  if (!response.ok) throw new Error("ribbon");
  return (await response.json()).items;
}

function legend(summary, active) {
  const root = document.getElementById("ribbon-legend");
  root.replaceChildren();
  const rows = Object.entries(summary.active_seconds_by_category || {}).filter(([, s]) => s >= 1).sort((a, b) => b[1] - a[1]);
  if (!rows.length) { root.append(el("li", "这一天还没有计入时长的活动", "ribbon-empty")); return; }
  for (const [category, seconds] of rows) {
    const li = el("li", undefined, `cat-${category}`);
    // Clicking a category filters the list below; clicking it again clears the filter.
    const button = el("button", undefined, "legend-filter");
    button.type = "button";
    button.setAttribute("aria-pressed", String(active === category));
    button.title = active === category ? "显示全部分类" : `只看“${categoryLabels[category] || category}”`;
    button.append(el("i"), el("span", categoryLabels[category] || category), el("b", duration(seconds)));
    button.onclick = () => document.dispatchEvent(new CustomEvent("leisurelog:category", {detail: category}));
    li.append(button);
    if (category === "unknown") {
      const link = el("a", "去分类", "legend-link");
      link.href = "/unclassified";
      li.append(link);
    }
    root.append(li);
  }
}

function tip() {
  let node = document.querySelector(".ribbon-tip");
  if (!node) { node = el("div", undefined, "ribbon-tip"); node.hidden = true; document.body.append(node); }
  return node;
}

function draw(track, items, day, isToday, onPick) {
  const start = Date.parse(`${day}T00:00:00+08:00`), end = start + DAY_MS;
  const frag = document.createDocumentFragment();
  for (const item of items) {
    const from = Math.max(start, item.start), to = Math.min(end, item.end);
    if (!(to > from)) continue;
    const category = item.category;
    const block = el("div", undefined, `block cat-${category}`);
    block.style.left = `${(from - start) / DAY_MS * 100}%`;
    block.style.width = `${(to - from) / DAY_MS * 100}%`;
    block.dataset.label = `${names[item.app] || item.app || "未知应用"}`;
    block.dataset.content = item.content || "";
    block.dataset.range = `${clock(from)}–${clock(to)}`;
    block.dataset.category = categoryLabels[category] || category;
    block.dataset.purpose = purposeLabels[item.purpose] || "用途待确认";
    block.dataset.active = duration(item.active_seconds);
    block.onclick = () => onPick(item);
    frag.append(block);
  }
  track.replaceChildren(frag);
  if (isToday) {
    const now = el("div", undefined, "ribbon-now");
    now.style.left = `${Math.min(100, (Date.now() - start) / DAY_MS * 100)}%`;
    track.append(now);
  }
  const t = tip();
  track.onmousemove = event => {
    const block = event.target.closest(".block");
    if (!block) { t.hidden = true; return; }
    t.replaceChildren(el("b", block.dataset.range), el("div", `${block.dataset.label} · ${block.dataset.category} · ${block.dataset.purpose}`));
    if (block.dataset.content) t.append(el("div", block.dataset.content));
    t.append(el("div", `计入 ${block.dataset.active}，点击查看依据`));
    t.hidden = false;
    const x = Math.min(event.clientX + 14, window.innerWidth - t.offsetWidth - 8);
    t.style.left = `${x}px`; t.style.top = `${event.clientY + 16}px`;
  };
  track.onmouseleave = () => { t.hidden = true; };
}

// params: day/app/category/query; summary from the dashboard response.
export async function renderRibbon(params, summary, {force = false, isToday = false, onPick}) {
  const track = document.getElementById("ribbon");
  legend(summary, params.category);
  const key = JSON.stringify(params);
  const current = ++ticket;
  try {
    if (force || key !== cachedKey) { cachedItems = await fetchAll(params); cachedKey = key; }
    if (current !== ticket) return;
    draw(track, cachedItems, params.day, isToday, onPick);
    const total = Object.values(summary.active_seconds_by_category || {}).reduce((a, b) => a + b, 0);
    track.setAttribute("aria-label", `当天共 ${cachedItems.length} 个活动片段，计入 ${duration(total)}。详细列表见下方表格。`);
  } catch {
    if (current === ticket) track.replaceChildren();
  }
}
