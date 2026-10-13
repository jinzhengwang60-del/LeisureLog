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
      "Rule preview is outdated; preview again": "记录或规则已经变化，请重新预览后保存。",
      "This change has already been undone": "这次修改已经撤销，请刷新修改记录。",
      "These decisions changed after this operation; undo newer changes first": "相关记录后来又被修改，请先撤销较新的修改，再处理这次操作。",
    };
    const error = new Error(typeof detail === "string" && messages[detail] ? messages[detail]
      : response.status === 404 ? "项目或活动已变化，请刷新后重试。"
      : response.status === 409 ? "记录正在变化，请刷新后重试。"
      : response.status === 422 ? "输入无法保存，请检查日期、名称、用途或关联范围。"
      : "暂时无法连接 LeisureLog，请重试。");
    error.status = response.status; throw error;
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
  form.append(node("p", "保存规则前会先预览影响范围。规则会用于全部历史和以后匹配的活动；未选中的人工归属继续优先。", "context-help"));
  const impact = node("section", undefined, "context-preview"); impact.hidden = true; form.append(impact);
  const message = node("p", "", "context-message"); message.setAttribute("role", "status");
  const buttons = node("div", undefined, "context-actions"), save = node("button", "保存用途与项目", "primary"),
    restore = node("button", "恢复自动归属"), link = node("a", "管理项目", "context-link");
  save.type = "submit"; restore.type = "button"; link.href = "/projects";
  buttons.append(save, restore, link); form.append(message, buttons);
  const ids = data.events.map(e => e.id);
  let busy = false, preview = null, previewBody = "";
  function invalidate() {
    preview = null; previewBody = ""; impact.hidden = true;
    save.textContent = scope.value ? "预览规则影响" : "保存用途与项目";
    keywordLabel.hidden = scope.value !== "title_contains"; keyword.required = !keywordLabel.hidden;
    message.textContent = "";
  }
  for (const control of [purpose, project, scope, keyword]) control.addEventListener("input", invalidate);
  function contextText(context) {
    const name = options.projects.find(p => p.id === context.project_id)?.name;
    return `${purposeLabels[context.purpose] || context.purpose} · ${name || "不关联项目"}`;
  }
  function showPreview(result) {
    impact.replaceChildren(node("h4", "规则影响预览"),
      node("p", `全部历史中匹配 ${result.matched_events} 条，${result.changed_events} 条会改变用途或项目；${result.manual_protected_events} 条保留已有人工选择。`),
      node("p", `本次选中 ${result.selected_events} 条会按你的选择修改。以下是最多 6 条匹配样例；匹配记录也可能受更具体的规则影响。`, "context-help"));
    for (const sample of result.samples) {
      const item = node("article", undefined, "context-preview-sample");
      item.append(node("strong", sample.title || sample.app),
        node("p", `${contextText(sample.before)} → ${contextText(sample.after)}`),
        node("small", sample.manual_protected ? "保留人工指定" : sample.changed ? "将改变归属" : "用途与项目保持原值"));
      impact.append(item);
    }
    impact.hidden = false; save.textContent = "确认规则并保存";
  }
  if (!batch && ids.length) {
    const explanation = node("details", undefined, "context-explanation"), summary = node("summary", "为什么这样归属？"), content = node("div");
    explanation.append(summary, content); form.insertBefore(explanation, fields);
    let loaded = false;
    explanation.ontoggle = async () => {
      if (!explanation.open || loaded) return;
      content.textContent = "正在读取归属来源…";
      try {
        const result = await contextRequest(`/api/events/${encodeURIComponent(ids[0])}/context/explanation`);
        loaded = true; content.replaceChildren();
        if (ids.length > 1) content.append(node("p", `此片段包含 ${ids.length} 条记录，以下说明第一条的来源。`, "context-help"));
        for (const [key, label] of [["purpose", "用途"], ["project_id", "项目"]]) {
          const field = result.fields[key], rule = result.matched_rules.find(r => r.id === field.rule_id);
          const origin = field.origin === "manual" ? "人工指定，优先于自动规则"
            : rule ? `已记住的${scopeLabels[rule.scope]}规则：${rule.value}`
            : field.origin.startsWith("config:") ? `配置中的用途规则：${field.origin.slice(7)}`
            : field.origin === "category" ? "按活动类型推定用途"
            : key === "project_id" ? "没有自动关联项目，可以保持不关联" : "尚未确定";
          content.append(node("p", `${label}：${origin}`));
        }
        content.append(node("p", "自动规则依次比较网页地址、完整标题、标题关键词、网站、应用；相同范围较新的规则先使用，较长的标题关键词优先。", "context-help"));
      } catch (error) { content.textContent = error.message; }
    };
  }
  async function submit(reset) {
    if (busy) return;
    let body;
    try { body = reset ? {event_ids: ids} : attributionPayload(ids, purpose.value, project.value, scope.value, keyword.value); }
    catch (error) { message.textContent = error.message; return; }
    busy = true;
    const controls = [save, restore, purpose, project, scope, keyword]; controls.forEach(control => { control.disabled = true; });
    const fingerprint = JSON.stringify(body);
    const needsPreview = !reset && body.remember_scope && (!preview || previewBody !== fingerprint);
    message.textContent = needsPreview ? "正在核对全部历史中的影响范围…" : "正在保存…";
    try {
      if (needsPreview) {
        preview = await contextRequest("/api/activity-context/preview", {method: "POST",
          headers: {"Content-Type": "application/json"}, body: fingerprint});
        previewBody = fingerprint; showPreview(preview); message.textContent = "核对影响范围后，点击“确认规则并保存”。"; return;
      }
      if (!reset && body.remember_scope) body.preview_token = preview.preview_token;
      const result = await contextRequest("/api/events/context", {method: reset ? "DELETE" : "PUT",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      await onSaved((reset ? "已恢复自动归属。已有自动关联规则仍会生效。" : "用途与项目已保存，相关统计已更新。")
        + (result.change_id ? "可在“规则与修改记录”中撤销。" : ""));
    } catch (error) { if (error.status === 409) invalidate(); message.textContent = error.message; }
    finally { busy = false; controls.forEach(control => { control.disabled = false; }); }
  }
  form.onsubmit = event => { event.preventDefault(); submit(false); };
  restore.onclick = () => submit(true);
  return form;
}

export async function openContextRules() {
  const dialog = node("dialog", undefined, "context-rule-dialog");
  const head = node("div", undefined, "dialog-head"), close = node("button", "关闭");
  head.append(node("h2", "规则与修改记录"), close); dialog.append(head);
  dialog.append(node("p", "规则按网页、标题、关键词、网站、应用的范围依次匹配。人工指定优先。保存、恢复归属和删除规则都可以在下方撤销。"));
  const body = node("div", "正在读取…"); dialog.append(body); document.body.append(dialog);
  close.onclick = () => dialog.close(); dialog.onclose = () => dialog.remove(); dialog.showModal();
  let changeOffset = 0;
  async function load() {
    try {
      const [rules, options, changes] = await Promise.all([contextRequest("/api/activity-context/rules"), contextRequest("/api/activity-context/options"), contextRequest(`/api/activity-context/changes?limit=20&offset=${changeOffset}`)]);
      if (!dialog.isConnected) return;
      body.replaceChildren(node("h3", "自动关联规则"));
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
            document.dispatchEvent(new CustomEvent("leisurelog:changed")); changeOffset = 0; await load();
          } catch (error) { info.append(node("p", error.message, "error")); remove.disabled = false; }
        };
      }
      body.append(node("h3", "最近的归属修改"), node("p", "撤销会恢复该次操作之前的归属并重新统计。如果相关记录后来再次被修改，需要先撤销较新的操作。", "context-help"));
      if (!changes.items.length) body.append(node("p", "还没有可撤销的修改。旧版本中已经保存的规则仍然有效。", "empty"));
      const actions = {attribute: "修改用途与项目", remember: "保存自动关联规则", restore: "恢复自动归属", remove_rule: "删除自动关联规则"};
      for (const change of changes.items) {
        const row = node("div", undefined, "context-rule-row"), info = node("div"), undo = node("button", change.undone_at ? "已撤销" : "撤销");
        const date = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "short"}).format(new Date(change.created_at));
        info.append(node("p", `${actions[change.action] || change.action}${change.event_count ? ` · ${change.event_count} 条记录` : ""}`), node("small", date));
        undo.disabled = Boolean(change.undone_at); row.append(info, undo); body.append(row);
        undo.onclick = async () => {
          undo.disabled = true;
          try {
            await contextRequest(`/api/activity-context/changes/${encodeURIComponent(change.id)}/undo`, {method: "POST"});
            document.dispatchEvent(new CustomEvent("leisurelog:changed")); await load();
          } catch (error) { info.append(node("p", error.message, "error")); undo.disabled = false; }
        };
      }
      if (changes.total > 20) {
        const pager = node("div", undefined, "context-actions"), prev = node("button", "较新的修改"), next = node("button", "较早的修改");
        prev.disabled = changeOffset === 0; next.disabled = changeOffset + 20 >= changes.total;
        prev.onclick = () => { changeOffset = Math.max(0, changeOffset - 20); load(); };
        next.onclick = () => { changeOffset += 20; load(); };
        pager.append(prev, node("small", `${changeOffset + 1}–${changeOffset + changes.items.length} / ${changes.total} 次`), next); body.append(pager);
      }
    } catch (error) { body.textContent = error.message; }
  }
  await load();
}

export const scopeLabels = Object.freeze({app: "应用", title: "完整标题", title_contains: "标题关键词", url: "网页地址", domain: "网站"});
