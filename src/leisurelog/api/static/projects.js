import {node, contextRequest, purposeLabels, openContextRules} from "./activity-context.js?v=2";
import {duration, appName, presetDates, ranking} from "./report-ui.js?v=2";

const $ = id => document.getElementById(id);
let ticket = 0, detailTicket = 0, editing = null, items = [];
const selectedProject = new URLSearchParams(location.search).get("project_id");
let openedSelection = false;
const params = () => new URLSearchParams({start: $("start").value, end: $("end").value});
const projectURL = id => `/statistics?${params()}&project_id=${encodeURIComponent(id)}`;

function renderCards() {
  const root = $("projects"); root.replaceChildren();
  const query = $("project-search").value.trim().toLocaleLowerCase();
  const shown = items.filter(p => (!p.archived || $("show-archived").checked)
    && `${p.name} ${p.description}`.toLocaleLowerCase().includes(query));
  for (const project of shown) {
    const card = node("article", undefined, `project-card${project.archived ? " archived" : ""}`);
    card.style.setProperty("--project-color", project.color);
    card.append(node("h2", project.name), node("p", project.archived ? "已归档 · 历史仍保留" : "进行中"),
      node("p", project.description || "可以在活动详情中关联记录"),
      node("strong", duration(project.active_seconds), "project-time"),
      node("p", `${project.days} 天有记录 · ${project.sessions} 个活动片段`));
    const controls = node("div", undefined, "context-actions"), detail = node("button", "查看活动"), edit = node("button", "编辑");
    detail.type = edit.type = "button"; detail.onclick = () => openDetail(project.id); edit.onclick = () => openEditor(project);
    controls.append(detail, edit); card.append(controls); root.append(card);
  }
  $("empty").hidden = shown.length > 0;
  $("empty").querySelector("h2").textContent = items.length ? "没有匹配的项目" : "把活动关联到你在做的事情";
  $("empty").querySelector("p").textContent = items.length
    ? "试试其他关键词，或勾选显示归档项目。"
    : "先创建一个项目，再打开活动详情，选择这个项目。记住标题或网站规则后，后续匹配的活动会自动归入。";
}

async function load() {
  const current = ++ticket;
  $("apply").disabled = true; $("error").hidden = true; $("coverage").textContent = "正在读取项目…";
  try {
    const data = await contextRequest(`/api/projects?${params()}`);
    if (current !== ticket) return;
    items = data.items;
    $("active").textContent = duration(data.totals.active_seconds);
    $("assigned").textContent = duration(data.totals.active_seconds - data.unassigned_seconds);
    $("unassigned").textContent = duration(data.unassigned_seconds);
    $("project-count").textContent = items.filter(p => p.active_seconds > 0).length;
    $("coverage").textContent = `${data.start} — ${data.end} · ${items.length} 个项目 · 按活动发生日期统计。`;
    renderCards();
    const url = new URL(location.href); url.searchParams.set("start", data.start); url.searchParams.set("end", data.end);
    history.replaceState({}, "", url);
    if (selectedProject && !openedSelection) { openedSelection = true; openDetail(selectedProject); }
  } catch (error) {
    if (current === ticket) { $("error").textContent = error.message; $("error").hidden = false;
      $("coverage").textContent = "当前查询未完成，下方如有项目仍为上一次结果。"; }
  } finally { if (current === ticket) $("apply").disabled = false; }
}

function openEditor(project = null) {
  editing = project;
  $("editor-title").textContent = project ? "编辑项目" : "新建项目";
  $("project-name").value = project?.name || ""; $("project-description").value = project?.description || "";
  $("project-color").value = project?.color || "#6366f1"; $("project-archived").checked = project?.archived || false;
  $("editor-message").textContent = ""; $("save-project").disabled = false;
  $("project-editor").showModal(); $("project-name").focus();
}

async function openDetail(id) {
  const current = ++detailTicket, body = $("project-body");
  body.replaceChildren(node("p", "正在读取项目活动…")); $("project-title").textContent = "项目活动";
  if (!$("project-detail").open) $("project-detail").showModal();
  try {
    const data = await contextRequest(`/api/projects/${encodeURIComponent(id)}?${params()}`);
    if (current !== detailTicket || !$("project-detail").open) return;
    $("project-title").textContent = data.project.name;
    body.replaceChildren(node("p", data.project.description), node("p", `${data.start} — ${data.end}`),
      node("h3", `活动时间 ${duration(data.totals.active_seconds)}`));
    const link = node("a", "打开项目统计 →", "context-link"); link.href = projectURL(id); body.append(link);
    body.append(node("h3", "主要应用")); const apps = node("div", undefined, "ranking"); body.append(apps);
    ranking(apps, data.apps, row => appName(row.app), {empty: "还没有关联活动。打开活动记录的详情，选择这个项目。"});
    body.append(node("h3", "用途分布")); const purposes = node("div", undefined, "ranking"); body.append(purposes);
    ranking(purposes, data.purposes, row => purposeLabels[row.purpose] || row.purpose, {denominator: data.totals.active_seconds});
    body.append(node("h3", "有记录的日期")); const days = node("div", undefined, "project-history"); body.append(days);
    for (const day of data.days) {
      const item = node("a", `${day.day} · ${duration(day.active_seconds)}`);
      item.href = `/?${new URLSearchParams({day: day.day, project_id: id})}`; days.append(item);
    }
    if (!data.days.length) days.append(node("p", "这个范围内还没有活动。"));
  } catch (error) { if (current === detailTicket) body.replaceChildren(node("p", error.message, "error")); }
}

$("project-form").onsubmit = async event => {
  event.preventDefault(); if ($("save-project").disabled) return;
  $("save-project").disabled = true; $("editor-message").textContent = "正在保存…";
  const body = {name: $("project-name").value.trim(), description: $("project-description").value,
    color: $("project-color").value, archived: $("project-archived").checked};
  try {
    await contextRequest(editing ? `/api/projects/${encodeURIComponent(editing.id)}` : "/api/projects", {
      method: editing ? "PUT" : "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    $("project-editor").close(); await load();
  } catch (error) { $("editor-message").textContent = error.message; }
  finally { $("save-project").disabled = false; }
};

function preset(name, refresh = true) {
  const range = presetDates(name); $("start").value = range.start; $("end").value = range.end;
  document.querySelectorAll("[data-range]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.range === name)));
  if (refresh) load();
}
$("range").onsubmit = event => { event.preventDefault(); document.querySelectorAll("[data-range]").forEach(b => b.setAttribute("aria-pressed", "false")); load(); };
document.querySelectorAll("[data-range]").forEach(b => { b.onclick = () => preset(b.dataset.range); });
$("create-project").onclick = () => openEditor(); $("project-search").oninput = renderCards;
$("show-archived").onchange = renderCards; $("manage-context").onclick = openContextRules;
$("close-editor").onclick = $("cancel-editor").onclick = () => $("project-editor").close();
$("close-detail").onclick = () => { ++detailTicket; $("project-detail").close(); };
document.addEventListener("leisurelog:changed", load);
preset("month", false);
const initial = new URLSearchParams(location.search);
if (initial.get("start") && initial.get("end")) {
  $("start").value = initial.get("start"); $("end").value = initial.get("end");
  document.querySelectorAll("[data-range]").forEach(b => b.setAttribute("aria-pressed", "false"));
}
load();
