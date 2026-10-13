import {node, contextRequest, createContextEditor, openContextRules} from "./activity-context.js?v=3";
import {duration, appName, presetDates} from "./report-ui.js?v=3";

const $ = id => document.getElementById(id), pageSize = 40;
let offset = 0, ticket = 0, groups = 0;
const initial = new URLSearchParams(location.search);
const params = () => new URLSearchParams({start: $("pending-start").value, end: $("pending-end").value,
  search: $("pending-search").value.trim(), limit: pageSize, offset});

function selectTab(name) {
  for (const kind of ["purpose", "category"]) {
    const active = name === kind;
    $(`${kind}-tab`).setAttribute("aria-selected", String(active)); $(`${kind}-tab`).tabIndex = active ? 0 : -1;
    $(`${kind}-panel`).hidden = !active;
  }
  const url = new URL(location.href); url.searchParams.set("tab", name); history.replaceState({}, "", url);
}

async function confirm(group, button) {
  button.disabled = true;
  const dialog = node("dialog", undefined, "confirmation-dialog"), head = node("div", undefined, "dialog-head"), close = node("button", "关闭");
  const title = group.website || appName(group.app_name);
  head.append(node("h2", `确认用途 · ${title}`), close); dialog.append(head);
  const body = node("div", "正在读取这一组的记录…"); dialog.append(body); document.body.append(dialog);
  close.onclick = () => dialog.close(); dialog.onclose = () => dialog.remove(); dialog.showModal();
  try {
    const query = new URLSearchParams({start: $("pending-start").value, end: $("pending-end").value,
      source: group.source, app: group.app, website: group.website, limit: 1000});
    const data = await contextRequest(`/api/activity-context/pending/events?${query}`);
    if (!dialog.isConnected) return;
    body.replaceChildren();
    if (!data.items.length) { body.append(node("p", "这一组的记录已经变化，请关闭后刷新。")); return; }
    body.append(node("p", `${data.total_events} 条待确认记录 · 来自当前日期范围`),
      node("p", "归属按整条来源记录保存，跨午夜的记录可能同时更新相邻日期。", "context-help"));
    if (data.total_events > data.items.length) body.append(node("p", `本次选择最近 ${data.items.length} 条，其余可继续处理；保存自动规则时会先预览全部历史的影响。`, "context-help"));
    const samples = node("details", undefined, "context-explanation"); samples.append(node("summary", "看看这一组的记录"));
    for (const item of data.items.slice(0, 6)) samples.append(node("p", item.title || item.app));
    body.append(samples);
    const editor = await createContextEditor({events: data.items}, async message => {
      dialog.close(); $("pending-notice").textContent = message; $("pending-notice").hidden = false;
      offset = 0; await load();
    }, {batch: true});
    if (dialog.isConnected) body.append(editor);
  } catch (error) { if (dialog.isConnected) body.replaceChildren(node("p", error.message, "error")); }
  finally { button.disabled = false; }
}

function render(data) {
  const root = $("pending-groups"); root.replaceChildren();
  if (!data.items.length) {
    const empty = node("div", undefined, "project-empty");
    empty.append(node("h2", data.groups ? "这一页没有记录" : "这个范围没有待确认的用途"),
      node("p", $("pending-search").value.trim() ? "试试其他应用或网站，或扩大日期范围。" : "已有明确用途的活动会自动从这里移出。日常活动可以不关联项目。"));
    root.append(empty);
  }
  for (const group of data.items) {
    const row = node("article", undefined, "pending-group"), info = node("div", undefined, "pending-info"),
      title = group.website || appName(group.app_name), facts = node("div", undefined, "pending-facts"), button = node("button", "确认用途", "primary");
    info.append(node("h2", title), node("p", group.browser ? `${appName(group.app_name)} · ${group.website ? "按网站分组" : "未获得网页地址，可按标题确认"}` : `${group.app_name} · 按应用分组`, "pending-meta"));
    if (group.sample_titles.length) info.append(node("p", group.sample_titles.join(" · "), "pending-sample"));
    facts.append(node("strong", duration(group.active_seconds)), node("small", `${group.sessions} 个片段 · ${group.days} 天有记录`));
    button.type = "button"; button.onclick = () => confirm(group, button); row.append(info, facts, button); root.append(row);
  }
  $("pending-time").textContent = duration(data.active_seconds); $("pending-count").textContent = data.groups;
  $("pending-page-count").textContent = data.items.length; groups = data.groups;
  $("pending-prev").disabled = offset === 0; $("pending-next").disabled = offset + pageSize >= groups;
  $("pending-page").textContent = groups ? `${offset + 1}–${offset + data.items.length} / ${groups} 组` : "0 组";
}

async function load() {
  const current = ++ticket;
  $("pending-apply").disabled = true; $("pending-error").hidden = true; $("pending-coverage").textContent = "正在读取待确认活动…";
  try {
    const data = await contextRequest(`/api/activity-context/pending?${params()}`);
    if (current !== ticket) return;
    render(data); $("pending-coverage").textContent = `${data.start} — ${data.end} · 用途待确认的活动按时间排列。`;
    const url = new URL(location.href); url.searchParams.set("start", data.start); url.searchParams.set("end", data.end); history.replaceState({}, "", url);
  } catch (error) {
    if (current === ticket) { $("pending-error").textContent = error.message; $("pending-error").hidden = false;
      $("pending-coverage").textContent = "查询未完成，下方如有记录仍为上一次结果。"; }
  } finally { if (current === ticket) $("pending-apply").disabled = false; }
}

function preset(name, refresh = true) {
  const range = presetDates(name); $("pending-start").value = range.start; $("pending-end").value = range.end;
  document.querySelectorAll("[data-pending-range]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.pendingRange === name)));
  if (refresh) { offset = 0; load(); }
}
$("pending-range").onsubmit = event => { event.preventDefault(); offset = 0;
  document.querySelectorAll("[data-pending-range]").forEach(button => button.setAttribute("aria-pressed", "false")); load(); };
document.querySelectorAll("[data-pending-range]").forEach(button => { button.onclick = () => preset(button.dataset.pendingRange); });
$("pending-prev").onclick = () => { offset = Math.max(0, offset - pageSize); load(); };
$("pending-next").onclick = () => { if (offset + pageSize < groups) { offset += pageSize; load(); } };
for (const name of ["purpose", "category"]) {
  $(`${name}-tab`).onclick = () => selectTab(name);
  $(`${name}-tab`).onkeydown = event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault(); const next = event.key === "Home" ? "purpose" : event.key === "End" ? "category" : name === "purpose" ? "category" : "purpose";
      selectTab(next); $(`${next}-tab`).focus();
    }
  };
}
$("manage-confirmation-rules").onclick = openContextRules;
document.addEventListener("leisurelog:changed", () => { offset = 0; load(); });
preset("month", false);
if (initial.get("start") && initial.get("end")) {
  $("pending-start").value = initial.get("start"); $("pending-end").value = initial.get("end");
  document.querySelectorAll("[data-pending-range]").forEach(button => button.setAttribute("aria-pressed", "false"));
}
selectTab(initial.get("tab") === "category" ? "category" : "purpose"); load();
