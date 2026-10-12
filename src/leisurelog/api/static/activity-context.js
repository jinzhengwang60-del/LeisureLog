export const purposeLabels = Object.freeze({
  work: "工作", study: "学习", create: "创作", communication: "沟通",
  leisure: "娱乐", system: "系统操作", other: "其他", unknown: "用途待确认",
});

export function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

export async function contextRequest(url, options) {
  const response = await fetch(url, {cache: "no-store", ...options});
  if (!response.ok) {
    const detail = await response.json().then(body => body.detail).catch(() => null);
    const messages = {
      "Browser purpose must be scoped to a title, URL or website": "浏览器包含不同内容，请按标题、关键词、网页地址或网站关联。",
      "Selected records must share the same matching scope": "所选活动的匹配条件不同。可以仅修改本次记录，或缩小选择范围后保存规则。",
      "The selected matching field is empty": "所选活动没有这个匹配信息，请换一种关联范围。",
      "The keyword must occur in every selected activity title": "关键词需要出现在每条所选活动的标题中。",
      "A keyword rule needs one application and 2 to 300 characters": "关键词需要 2–300 个字符，所选记录需要来自同一个应用。",
      "A remembered rule must contain an explicit choice": "恢复自动用途不能记为规则，请选择一个具体用途或只关联项目。",
    };
    if (typeof detail === "string" && messages[detail]) throw new Error(messages[detail]);
    throw new Error(response.status === 404 ? "项目或活动已变化，请刷新后重试。"
      : response.status === 422 ? "输入无法保存，请检查日期、名称、用途或关联范围。"
      : "暂时无法连接 LeisureLog，请重试。");
  }
  return response.status === 204 ? null : response.json();
}

export function fillSelect(select, entries, title, chosen = select.value) {
  select.replaceChildren();
  for (const [value, label] of [["", title], ...entries]) {
    const option = node("option", label);
    option.value = value;
    select.append(option);
  }
  select.value = [...select.options].some(o => o.value === chosen) ? chosen : "";
}

export function contextBadges(context = {}, projects = []) {
  const box = node("span", undefined, "context-badges");
  const purpose = context?.purpose || "unknown";
  box.append(node("span", purposeLabels[purpose] || purpose, `purpose-badge purpose-${purpose}`));
  if (context?.purpose_origin === "manual") box.append(node("small", "人工", "manual-label"));
  const project = projects.find(p => p.id === context?.project_id);
  if (project) {
    const badge = node("span", project.name, "project-badge");
    badge.title = project.archived ? "已归档项目" : "关联项目";
    box.append(badge);
  }
  return box;
}

export function attributionPayload(ids, purpose, project, scope = "", matchText = "") {
  if (!ids.length || ids.length > 1000) throw new Error("一次选择 1–1000 条活动记录。请缩小选择范围。");
  const body = {event_ids: [...new Set(ids)]};
  if (purpose !== "__keep__") body.purpose = purpose === "__auto__" ? null : purpose;
  if (project !== "__keep__") body.project_id = project === "none" ? null : project;
  if (!("purpose" in body) && !("project_id" in body)) throw new Error("先选择要修改的用途或项目。");
  if (scope) body.remember_scope = scope;
  if (scope === "title_contains") body.match_text = matchText.trim();
  return body;
}

export async function createContextEditor(data, onSaved, {batch = false} = {}) {
  const options = await contextRequest("/api/activity-context/options");
  const form = node("form", undefined, "context-editor");
  form.append(node("h3", batch ? "批量修改用途与项目" : "用途与项目"));
  if (!batch) form.append(contextBadges(data.session.context, options.projects));
  else form.append(node("p", `将修改所选的 ${data.events.length} 条活动记录；保持当前归属的字段不会被覆盖。`, "context-help"));
  form.append(node("p", "用途独立于活动类型。可以把视频归为学习，也可以把多个应用关联到同一项目。", "context-help"));
  const fields = node("div", undefined, "context-fields");
  const purpose = node("select"), project = node("select"), scope = node("select");
  function field(text, control, suffix) {
    control.id = `context-${suffix}`;
    const wrapper = node("div", undefined, "context-field"), label = node("label", text);
    label.htmlFor = control.id; wrapper.append(label, control); return wrapper;
  }
  const keep = "__keep__";
  fillSelect(purpose, [["__auto__", "恢复自动用途"], ...Object.entries(options.purposes)], "保持当前用途");
  purpose.firstChild.value = keep; purpose.value = keep;
  fillSelect(project, [["none", "不关联项目"], ...options.projects.filter(p => !p.archived)
    .map(p => [p.id, p.name])], "保持当前归属");
  project.firstChild.value = keep; project.value = keep;
  fillSelect(scope, [["title", "以后同一标题"], ["title_contains", "以后标题含关键词"], ["url", "以后同一网页地址"],
    ["domain", "以后同一网站"], ["app", "以后同一应用"]], "仅修改这次记录");
  fields.append(field("用途", purpose, "purpose"), field("项目", project, "project"),
    field("自动关联范围", scope, "scope"));
  form.append(fields);
  const keyword = node("input"), keywordLabel = field("标题关键词", keyword, "keyword");
  keyword.type = "text"; keyword.maxLength = 300; keyword.placeholder = "例如 LeisureLog 或毕业论文";
  keywordLabel.className = "context-keyword"; keywordLabel.hidden = true; form.append(keywordLabel);
  keyword.minLength = 2;
  scope.onchange = () => { keywordLabel.hidden = scope.value !== "title_contains"; keyword.required = !keywordLabel.hidden; };
  form.append(node("p", "记住规则会同时更新已有的匹配记录，并用于以后的活动；人工选择继续优先。", "context-help"));
  const message = node("p", "", "context-message"); message.setAttribute("role", "status");
  const buttons = node("div", undefined, "context-actions"), save = node("button", "保存用途与项目", "primary"),
    restore = node("button", "恢复自动归属"), link = node("a", "管理项目", "context-link");
  save.type = "submit"; restore.type = "button"; link.href = "/projects";
  buttons.append(save, restore, link); form.append(message, buttons);
  const ids = data.events.map(e => e.id);
  let busy = false;
  async function submit(reset) {
    if (busy) return;
    let body;
    try { body = reset ? {event_ids: ids} : attributionPayload(ids, purpose.value, project.value, scope.value, keyword.value); }
    catch (error) { message.textContent = error.message; return; }
    busy = true; save.disabled = restore.disabled = true; message.textContent = "正在保存…";
    try {
      await contextRequest("/api/events/context", {method: reset ? "DELETE" : "PUT",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      await onSaved(reset ? "已恢复自动归属。已有自动关联规则仍会生效。" : "用途与项目已保存，相关统计已更新。");
    } catch (error) { message.textContent = error.message; }
    finally { busy = false; save.disabled = restore.disabled = false; }
  }
  form.onsubmit = event => { event.preventDefault(); submit(false); };
  restore.onclick = () => submit(true);
  return form;
}

export async function openContextRules() {
  const dialog = node("dialog", undefined, "context-rule-dialog");
  const head = node("div", undefined, "dialog-head"), close = node("button", "关闭");
  head.append(node("h2", "自动关联规则"), close); dialog.append(head);
  dialog.append(node("p", "这些规则决定未来活动的用途与项目。删除规则会重算自动归属，人工指定的归属仍然保留。"));
  const body = node("div", "正在读取…"); dialog.append(body); document.body.append(dialog);
  close.onclick = () => dialog.close(); dialog.onclose = () => dialog.remove(); dialog.showModal();
  async function load() {
    try {
      const [rules, options] = await Promise.all([contextRequest("/api/activity-context/rules"), contextRequest("/api/activity-context/options")]);
      if (!dialog.isConnected) return;
      body.replaceChildren();
      if (!rules.length) body.append(node("p", "还没有自动关联规则。可在活动详情中保存。", "empty"));
      for (const rule of rules) {
        const row = node("div", undefined, "context-rule-row"), info = node("div"), remove = node("button", "删除");
        const scopeNames = {app: "整个应用", title: "标题", title_contains: "标题关键词", url: "网页地址", domain: "网站"};
        const text = [rule.app, `${scopeNames[rule.scope] || rule.scope}：${rule.value}`];
        if (rule.assignments.purpose) text.push(purposeLabels[rule.assignments.purpose]);
        if ("project_id" in rule.assignments) text.push(options.projects.find(p => p.id === rule.assignments.project_id)?.name || "不关联项目");
        info.append(node("p", text.join(" · "))); row.append(info, remove); body.append(row);
        remove.onclick = async () => {
          remove.disabled = true;
          try { await contextRequest(`/api/activity-context/rules/${encodeURIComponent(rule.id)}`, {method: "DELETE"});
            document.dispatchEvent(new CustomEvent("leisurelog:changed")); await load();
          } catch (error) { info.append(node("p", error.message, "error")); remove.disabled = false; }
        };
      }
    } catch (error) { body.textContent = error.message; }
  }
  await load();
}
