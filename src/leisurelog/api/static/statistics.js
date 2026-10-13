import {categoryLabels} from "./correction.js?v=activity2";
import {renderHours} from "./hours.js?v=activity2";
import {node, purposeLabels, fillSelect, contextRequest} from "./activity-context.js?v=3";
import {duration, appName, presetDates, ranking} from "./report-ui.js?v=motion1";

const $ = id => document.getElementById(id);
let ticket = 0, projects = [];
const initial = new URLSearchParams(location.search);
let linkedProject = initial.get("project_id") || "";
const filters = () => ({purpose: $("purpose").value, project_id: $("project").value || linkedProject});
const projectName = id => projects.find(p => p.id === id)?.name || "未关联项目";

function preset(name, refresh = true) {
  const range = presetDates(name);
  $("start").value = range.start; $("end").value = range.end;
  document.querySelectorAll("[data-range]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.range === name)));
  if (refresh) load();
}

function trend(data) {
  const root = $("trend"); root.replaceChildren();
  const max = Math.max(...data.trend.map(row => row.active_seconds), 1);
  $("trend-caption").textContent = `${data.granularity === "month" ? "按月" : "按天"} · 按策略计入的时长 · 悬停查看详情${data.granularity === "day" ? "，点击查看当天记录" : ""}`;
  $("trend-empty").hidden = data.coverage.days_with_records > 0;
  root.hidden = data.coverage.days_with_records === 0;
  for (const row of data.trend) {
    const column = node(data.granularity === "day" ? "a" : "div", undefined, "trend-column");
    if (data.granularity === "day") column.href = `/?${new URLSearchParams({day: row.period, ...data.filters})}`;
    column.tabIndex = 0;
    column.title = row.has_records ? `${row.period}：计入 ${duration(row.active_seconds)}，状态待确认 ${duration(row.unverified_seconds)}，已扣除离开 ${duration(row.afk_seconds)}` : `${row.period}：没有匹配记录`;
    column.setAttribute("aria-label", column.title);
    const stack = node("div", undefined, "trend-stack"); stack.style.height = `${Math.max(2, row.active_seconds / max * 145)}px`;
    const uncertain = row.active_seconds ? Math.min(1, row.unverified_seconds / row.active_seconds) : 0;
    const top = node("div", undefined, "trend-segment uncertain"); top.style.height = `${uncertain * 100}%`;
    const bottom = node("div", undefined, `trend-segment ${row.has_records ? "confirmed" : "trend-missing"}`); bottom.style.height = `${(1 - uncertain) * 100}%`;
    stack.append(top, bottom);
    column.append(node("span", row.has_records ? duration(row.active_seconds) : "无记录", "trend-value"), stack,
      node("span", data.granularity === "month" ? row.period : row.period.slice(5), "trend-label"));
    root.append(column);
  }
}

async function load() {
  const current = ++ticket;
  $("apply").disabled = true; $("export").hidden = true; $("error").hidden = true; $("coverage").textContent = "正在读取统计…";
  try {
    const selected = filters(), params = new URLSearchParams({start: $("start").value, end: $("end").value,
      granularity: $("granularity").value, ...selected});
    const data = await contextRequest(`/api/statistics?${params}`);
    if (current !== ticket) return;
    projects = data.project_options;
    fillSelect($("project"), [["none", "未关联项目"], ...projects.map(p => [p.id, p.name + (p.archived ? "（已归档）" : "")])], "全部项目", selected.project_id);
    linkedProject = "";
    $("active").textContent = duration(data.totals.active_seconds);
    $("assigned").textContent = duration(data.projects.filter(p => p.project_id).reduce((sum, p) => sum + p.active_seconds, 0));
    $("unknown").textContent = duration(data.totals.purpose_unknown_seconds);
    $("work").textContent = duration(data.purposes.find(p => p.purpose === "work")?.active_seconds || 0);
    const filterLabel = [purposeLabels[selected.purpose], selected.project_id && projectName(selected.project_id)].filter(Boolean).join(" · ");
    $("coverage").textContent = `${data.start} — ${data.end}${filterLabel ? " · " + filterLabel : ""} · ${data.coverage.days_with_records} 天有匹配记录 · ${data.coverage.session_count} 个活动片段。`;
    $("timing").textContent = `原始记录 ${duration(data.totals.recorded_seconds)} · 检测到离开 ${duration(data.totals.detected_afk_seconds)} · 策略保留 ${duration(data.totals.retained_afk_seconds)} · 实际扣除 ${duration(data.totals.afk_seconds)} · 计入时长中包含状态待确认 ${duration(data.totals.unverified_seconds)}。`;
    ranking($("purposes"), data.purposes, row => purposeLabels[row.purpose] || row.purpose, {denominator: data.totals.active_seconds});
    ranking($("projects"), data.projects, row => projectName(row.project_id), {denominator: data.totals.active_seconds,
      color: row => projects.find(p => p.id === row.project_id)?.color || "var(--muted)",
      link: row => `/projects?${new URLSearchParams({start: data.start, end: data.end, ...(row.project_id ? {project_id: row.project_id} : {})})}`});
    ranking($("categories"), data.categories, row => categoryLabels[row.category] || row.category, {denominator: data.totals.active_seconds});
    ranking($("apps"), data.apps, row => appName(row.app));
    ranking($("contents"), data.contents, row => `${row.content} · ${appName(row.app)}`, {empty: "还没有带内容名称的记录。可以在活动详情中填写内容名称。"});
    trend(data); renderHours(data.start, data.end, selected);
    $("export").href = `/api/statistics/export?${params}`; $("export").hidden = false;
    const url = new URL(location.href); url.search = params.toString(); history.replaceState({}, "", url);
  } catch (error) {
    if (current !== ticket) return;
    $("error").textContent = error.message; $("error").hidden = false;
    $("coverage").textContent = "当前查询未完成，下方如有图表仍为上一次结果。";
  } finally { if (current === ticket) $("apply").disabled = false; }
}

$("range").addEventListener("submit", event => {event.preventDefault(); document.querySelectorAll("[data-range]").forEach(b => b.setAttribute("aria-pressed", "false")); load();});
document.querySelectorAll("[data-range]").forEach(b => b.addEventListener("click", () => preset(b.dataset.range)));
fillSelect($("purpose"), Object.entries(purposeLabels), "全部用途", initial.get("purpose") || "");
fillSelect($("project"), [], "全部项目");
$("purpose").onchange = $("project").onchange = load;
preset("week", false);
if (initial.get("start") && initial.get("end")) {
  $("start").value = initial.get("start"); $("end").value = initial.get("end");
  document.querySelectorAll("[data-range]").forEach(b => b.setAttribute("aria-pressed", "false"));
}
if (["auto", "day", "month"].includes(initial.get("granularity"))) $("granularity").value = initial.get("granularity");
load();
