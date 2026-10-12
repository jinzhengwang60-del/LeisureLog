const options = {
  unknown: "未分类", game: "游戏", video: "视频", film: "影视", anime: "动漫",
  reading: "阅读", music: "音乐", social: "社交", live: "直播", browsing: "网络闲逛",
  work: "工作", study: "学习", create: "创作", coding: "编程", office: "文档与办公",
  design: "设计与制作", meeting: "会议", system: "系统与工具", other: "其他",
};
export const categoryLabels = Object.assign(Object.create(null), options);

function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function field(labelText, control, id) {
  const wrapper = element("div", undefined, "correction-field");
  const label = element("label", labelText);
  label.htmlFor = id;
  control.id = id;
  wrapper.append(label, control);
  return wrapper;
}

async function write(method, payload) {
  const response = await fetch("/api/events/overrides", {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    if (response.status === 404) throw new Error("选中的记录已变化，请关闭详情并刷新列表。");
    if (response.status === 422) throw new Error("输入或匹配范围不符合要求，请检查字段是否为空，以及所选记录的应用、标题或域名是否一致。");
    throw new Error("保存失败，请检查后端连接后再试。");
  }
  return response.json();
}

function hostname(url) {
  try { return new URL(url).hostname; } catch { return ""; }
}

export function createCorrection(data, onSaved) {
  const classification = data.session.classification;
  const ids = data.events.map(event => event.id);
  const form = element("form", undefined, "correction");
  form.append(element("h3", "纠正分类"));
  form.append(element("p", `应用到本次显示的 ${ids.length} 条活动记录，跨日记录的其他日期部分也会一起修改。可以选择记住规则，让相同活动以后自动分类。`));
  const grid = element("div", undefined, "correction-grid");
  const category = element("select");
  const choices = Object.assign(Object.create(null), options);
  if (!(classification.category in choices)) choices[classification.category] = classification.category;
  for (const [value, label] of Object.entries(choices)) {
    const option = element("option", label);
    option.value = value;
    category.append(option);
  }
  category.value = classification.category;
  const content = element("input");
  content.type = "text";
  content.maxLength = 300;
  content.value = classification.content || "";
  content.placeholder = "例如：某款游戏、正在看的电影";
  const tags = element("input");
  tags.type = "text";
  tags.value = classification.tags.join("，");
  tags.placeholder = "用逗号分隔，例如：RPG，开放世界";
  grid.append(field("分类", category, "correction-category"),
    field("内容名称（选填）", content, "correction-content"),
    field("标签（选填）", tags, "correction-tags"));
  form.append(grid);
  const scope = element("select");
  const scopeChoices = [["", "只修改这次记录"], ["title", "记住：同一应用 + 完全相同的标题"],
    ["app", "记住：这个应用的所有活动"], ["domain", "记住：同一应用 + 同一网站域名"], ["url", "记住：同一应用 + 这个页面地址"]];
  for (const [value, label] of scopeChoices) {
    const option = element("option", label);
    option.value = value;
    if (["domain", "url"].includes(value) && !data.events.every(event => hostname(event.url))) option.disabled = true;
    if (value === "title" && !data.events.every(event => event.title)) option.disabled = true;
    scope.append(option);
  }
  const scopeHint = element("p", "只修改当前记录。", "rule-hint");
  scope.addEventListener("change", () => {
    const event = data.events[0];
    scopeHint.textContent = scope.value === "app" ? `匹配应用：${event.app}。这个应用里的所有内容都会使用此分类，选择浏览器时请谨慎。`
      : scope.value === "title" ? `匹配应用 ${event.app}，且标题完全等于：${event.title}。标题变化后不会匹配。`
      : scope.value === "url" ? `匹配应用 ${event.app} 和当前页面地址（忽略页内锚点，保留查询参数）。标题变化仍可识别；其他章节或页面地址需另行识别。`
      : scope.value === "domain" ? `匹配应用 ${event.app} 和域名 ${hostname(event.url)}（不包含其他子域名）。`
      : "只修改当前记录。";
    if (scope.value) scopeHint.textContent += " 保存后会立即重新分类已有匹配记录，并应用于未来记录；已有人工分类保留。";
  });
  form.append(field("自动识别范围", scope, "correction-scope"), scopeHint);
  const feedback = element("p", "", "correction-error");
  feedback.setAttribute("role", "alert");
  feedback.hidden = true;
  const actions = element("div", undefined, "correction-actions");
  const save = element("button", "保存人工分类", "primary");
  save.type = "submit";
  const restore = element("button", "恢复自动分类");
  restore.type = "button";
  const hasManual = data.events.some(event => event.classification.origin === "manual");
  restore.disabled = !hasManual;
  actions.append(save, restore);
  form.append(feedback, actions);
  if (hasManual) form.append(element("p", "这些记录已有人工分类，自动同步会优先保留。"));

  async function submit(remove) {
    feedback.hidden = true;
    const selectedTags = [...new Set(tags.value.split(/[,，]/).map(value => value.trim()).filter(Boolean))];
    if (!remove && selectedTags.length > 30) {
      feedback.textContent = "最多填写 30 个标签。";
      feedback.hidden = false;
      return;
    }
    save.disabled = restore.disabled = true;
    category.disabled = content.disabled = tags.disabled = scope.disabled = true;
    try {
      await write(remove ? "DELETE" : "PUT", remove ? { event_ids: ids } : {
        event_ids: ids, category: category.value,
        content: content.value.trim() || null, tags: selectedTags, remember_scope: scope.value || null,
      });
      await onSaved(remove ? "已恢复自动分类，仍会应用已记住的规则。" : scope.value ? "分类与识别规则已保存，相同活动会自动识别。" : "人工分类已保存，列表与统计已更新。");
    } catch (error) {
      feedback.textContent = error.message || "无法连接后端，请稍后再试。";
      feedback.hidden = false;
    } finally {
      save.disabled = false;
      restore.disabled = !hasManual;
      category.disabled = content.disabled = tags.disabled = scope.disabled = false;
    }
  }
  form.addEventListener("submit", event => { event.preventDefault(); submit(false); });
  restore.addEventListener("click", () => submit(true));
  return form;
}
