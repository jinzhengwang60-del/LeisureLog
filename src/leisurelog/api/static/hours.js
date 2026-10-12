// Day x hour grid on the statistics page.
import {categoryLabels} from "./correction.js";

const $ = id => document.getElementById(id);
const WEEK = ["周日","周一","周二","周三","周四","周五","周六"];
let ticket = 0;

function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function minutes(value) {
  const m = Math.round((value || 0) / 60);
  return m < 1 ? "不到 1 分" : m >= 60 ? `${Math.floor(m / 60)} 小时 ${m % 60} 分` : `${m} 分`;
}
const label = key => categoryLabels[key] || key;

function legend(seen) {
  const root = $("hours-legend");
  root.replaceChildren();
  for (const key of seen) {
    const item = node("span", undefined, `cat-${key}`);
    item.append(node("i", undefined, "hours-swatch"), document.createTextNode(label(key)));
    root.append(item);
  }
}

export async function renderHours(start, end, filters = {}) {
  const current = ++ticket;
  const root = $("hours");
  try {
    const response = await fetch(`/api/statistics/hours?${new URLSearchParams({start, end, ...filters})}`, {cache: "no-store"});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (current !== ticket) return;
    const totals = {};
    const grid = document.createDocumentFragment();
    grid.append(node("span", "", "hours-corner"));
    for (let h = 0; h < 24; h++) grid.append(node("span", h % 3 === 0 ? String(h) : "", "hours-head"));
    for (const day of data.days) {
      const [y, m, d] = day.day.split("-").map(Number);
      const weekday = WEEK[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
      const name = node("a", `${m}/${d}`, "hours-day");
      name.href = `/?${new URLSearchParams({day:day.day,...filters})}`;
      name.append(node("small", weekday));
      grid.append(name);
      day.hours.forEach((hour, h) => {
        const cell = node("a", undefined, `hours-cell${hour.top ? ` cat-${hour.top}` : ""}`);
        cell.href = `/?${new URLSearchParams({day:day.day,...filters})}`;
        const fill = node("span");
        if (hour.top) {
          // Opacity grows with how much of the hour was counted; never fully invisible.
          fill.style.opacity = String(Math.min(1, 0.25 + 0.75 * hour.active_seconds / 3600));
          for (const [key, seconds] of Object.entries(hour.categories)) totals[key] = (totals[key] || 0) + seconds;
          const parts = Object.entries(hour.categories).sort((a, b) => b[1] - a[1]).map(([key, s]) => `${label(key)} ${minutes(s)}`);
          cell.title = `${m}月${d}日 ${h}:00–${h + 1}:00\n${parts.join("，")}`;
        } else {
          cell.title = `${m}月${d}日 ${h}:00–${h + 1}:00 没有计入的活动`;
        }
        cell.append(fill);
        grid.append(cell);
      });
    }
    root.replaceChildren(grid);
    root.style.setProperty("--rows", data.days.length);
    legend(Object.keys(totals).sort((a, b) => totals[b] - totals[a]));
    $("hours-caption").textContent = data.truncated
      ? `所选范围较长，这里显示最后 31 天（${data.start} 至 ${data.end}）。每格一小时，颜色是这一小时里时间最多的分类，越浓表示计入越多。`
      : "每格一小时，颜色是这一小时里时间最多的分类，越浓表示计入越多。点击格子查看当天记录。";
  } catch {
    if (current === ticket) root.replaceChildren(node("p", "作息图读取失败。", "empty"));
  }
}
