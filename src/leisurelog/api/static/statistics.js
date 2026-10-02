import {categoryLabels} from "./correction.js";

const $ = id => document.getElementById(id);
const today = () => new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
const dayString = value => value.toISOString().slice(0,10);
const names = {"chrome.exe":"Chrome", "msedge.exe":"Microsoft Edge", "ChatGPT.exe":"ChatGPT", "Weixin.exe":"微信", "QQ.exe":"QQ", "explorer.exe":"文件管理器"};
const appName = value => names[value] || value;
let ticket = 0;

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function duration(value) {
  const total = Math.round(value || 0);
  if (total < 60) return `${total} 秒`;
  if (total < 3600) return `${Math.floor(total/60)} 分 ${total%60} 秒`;
  return `${Math.floor(total/3600)} 小时 ${Math.floor(total%3600/60)} 分`;
}

function preset(name) {
  const end = today();
  let start = end;
  if (name === "week") {
    const date = new Date(`${end}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - (date.getUTCDay()+6)%7);
    start = dayString(date);
  } else if (name === "month") start = end.slice(0,7)+"-01";
  else start = end.slice(0,4)+"-01-01";
  $("start").value = start; $("end").value = end;
  document.querySelectorAll("[data-range]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.range === name)));
  load();
}

function ranking(id, rows, label, denominator, empty) {
  const root = $(id); root.replaceChildren();
  if (!rows.length) { root.append(node("p",empty,"empty")); return; }
  const max = denominator ?? Math.max(...rows.map(row => row.active_seconds),1);
  for (const row of rows) {
    const item = node("div",undefined,"rank-row");
    const heading = node("div",undefined,"rank-heading");
    const percentage = denominator ? ` · ${(row.active_seconds/denominator*100).toFixed(1)}%` : "";
    heading.append(node("span",label(row),"rank-name"),node("span",duration(row.active_seconds)+percentage,"rank-value"));
    const track = node("div",undefined,"rank-track");
    const fill = node("div",undefined,`rank-fill ${row.category || ""}`);
    fill.style.width = `${max ? Math.min(100,row.active_seconds/max*100) : 0}%`;
    track.append(fill); item.append(heading,track); root.append(item);
  }
}

function trend(data) {
  const root = $("trend"); root.replaceChildren();
  const max = Math.max(...data.trend.map(row => row.active_seconds),1);
  $("trend-caption").textContent = `${data.granularity === "month" ? "按月" : "按天"} · 扣除离开后时长 · 悬停查看详情${data.granularity === "day" ? "，点击查看当天记录" : ""}`;
  $("trend-empty").hidden = data.coverage.days_with_records > 0;
  root.hidden = data.coverage.days_with_records === 0;
  for (const row of data.trend) {
    const column = node(data.granularity === "day" ? "a" : "div",undefined,"trend-column");
    if (data.granularity === "day") column.href = `/?day=${row.period}`;
    column.tabIndex = 0;
    column.title = row.has_records ? `${row.period}：扣除后 ${duration(row.active_seconds)}，待确认 ${duration(row.unverified_seconds)}，已扣除离开 ${duration(row.afk_seconds)}` : `${row.period}：没有记录，不代表零使用`;
    column.setAttribute("aria-label",column.title);
    const stack = node("div",undefined,"trend-stack");
    const height = row.active_seconds/max*145;
    stack.style.height = `${Math.max(2,height)}px`;
    const uncertain = row.active_seconds ? Math.min(1,row.unverified_seconds/row.active_seconds) : 0;
    const top = node("div",undefined,"trend-segment uncertain"); top.style.height = `${uncertain*100}%`;
    const bottom = node("div",undefined,`trend-segment ${row.has_records ? "confirmed" : "trend-missing"}`); bottom.style.height = `${(1-uncertain)*100}%`;
    stack.append(top,bottom);
    column.append(node("span",row.has_records ? duration(row.active_seconds) : "无记录","trend-value"),stack,
      node("span",data.granularity === "month" ? row.period : row.period.slice(5),"trend-label"));
    root.append(column);
  }
}

async function load() {
  const current = ++ticket;
  $("apply").disabled = true; $("error").hidden = true;
  $("coverage").textContent = "正在读取统计…";
  try {
    const params = new URLSearchParams({start:$("start").value,end:$("end").value,granularity:$("granularity").value});
    const response = await fetch(`/api/statistics?${params}`);
    if (!response.ok) throw new Error(response.status === 422 ? "请检查日期范围：结束日期不能早于开始日期，最多查看 3660 天。" : "无法读取统计，请检查 LeisureLog 服务。");
    const data = await response.json(); if (current !== ticket) return;
    $("active").textContent = duration(data.totals.active_seconds);
    $("leisure").textContent = duration(data.totals.leisure_seconds);
    $("unknown").textContent = duration(data.totals.unknown_seconds);
    $("work").textContent = duration(data.totals.work_seconds);
    $("coverage").textContent = `${data.start} — ${data.end} · ${data.coverage.days_with_records} 天有记录 · ${data.coverage.session_count} 个活动片段${data.coverage.first_day ? ` · 实际记录日期 ${data.coverage.first_day} — ${data.coverage.last_day}` : ""}。无记录日期不代表没有使用。`;
    $("timing").textContent = `原始记录 ${duration(data.totals.recorded_seconds)} · 检测到离开 ${duration(data.totals.detected_afk_seconds)} · 策略保留 ${duration(data.totals.retained_afk_seconds)} · 实际扣除 ${duration(data.totals.afk_seconds)} · 扣除后包含待确认 ${duration(data.totals.unverified_seconds)}。`;
    ranking("categories",data.categories,row=>categoryLabels[row.category]||row.category,data.totals.active_seconds,"这个范围还没有分类记录。");
    ranking("apps",data.apps,row=>appName(row.app),null,"这个范围还没有应用记录。");
    ranking("contents",data.contents,row=>`${row.content} · ${appName(row.app)}`,null,"还没有带内容名称的记录。可以在活动详情中识别或填写内容名称。");
    trend(data);
  } catch (error) {
    if (current !== ticket) return;
    $("error").textContent = error.message; $("error").hidden = false;
    $("coverage").textContent = "当前查询未完成，下方如有图表仍为上一次结果。";
  } finally { if (current === ticket) $("apply").disabled = false; }
}

$("range").addEventListener("submit",event=>{event.preventDefault();document.querySelectorAll("[data-range]").forEach(button=>button.setAttribute("aria-pressed","false"));load();});
document.querySelectorAll("[data-range]").forEach(button=>button.addEventListener("click",()=>preset(button.dataset.range)));
preset("week");
