import {node} from "./activity-context.js?v=2";

export const today = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

export function duration(value) {
  const n = Math.round(value || 0);
  if (n < 60) return `${n} 秒`;
  if (n < 3600) return `${Math.floor(n / 60)} 分 ${n % 60} 秒`;
  return `${Math.floor(n / 3600)} 小时 ${Math.floor(n % 3600 / 60)} 分`;
}

export const appName = value => ({
  "chrome.exe": "Chrome", "msedge.exe": "Microsoft Edge", "ChatGPT.exe": "ChatGPT",
  "Weixin.exe": "微信", "QQ.exe": "QQ", "explorer.exe": "文件管理器",
  "Code.exe": "Visual Studio Code", "WINWORD.EXE": "Word", "EXCEL.EXE": "Excel", "POWERPNT.EXE": "PowerPoint",
})[value] || (value || "").replace(/\.exe$/i, "");

export function presetDates(name) {
  const end = today();
  let start = end;
  if (name === "week") {
    const date = new Date(`${end}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
    start = date.toISOString().slice(0, 10);
  } else if (name === "month") start = end.slice(0, 7) + "-01";
  else if (name === "year") start = end.slice(0, 4) + "-01-01";
  return {start, end};
}

export function ranking(root, rows, label, {denominator, empty = "这个范围还没有记录。", link, color} = {}) {
  root.replaceChildren();
  if (!rows.length) { root.append(node("p", empty, "empty")); return; }
  const max = denominator ?? Math.max(...rows.map(row => row.active_seconds), 1);
  for (const row of rows) {
    const item = node("div", undefined, "rank-row"), heading = node("div", undefined, "rank-heading");
    const percentage = denominator ? ` · ${(row.active_seconds / denominator * 100).toFixed(1)}%` : "";
    const name = node(link ? "a" : "span", label(row), "rank-name");
    if (link) name.href = link(row);
    heading.append(name, node("span", duration(row.active_seconds) + percentage, "rank-value"));
    const track = node("div", undefined, "rank-track"),
      fill = node("div", undefined, `rank-fill ${row.purpose ? "purpose-" + row.purpose : row.category || ""}`);
    fill.style.width = `${max ? Math.min(100, row.active_seconds / max * 100) : 0}%`;
    if (color) fill.style.backgroundColor = color(row);
    track.append(fill); item.append(heading, track); root.append(item);
  }
}
