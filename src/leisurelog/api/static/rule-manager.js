import {categoryLabels} from "./correction.js?v=content1";

function node(tag, text) {
  const item = document.createElement(tag);
  if (text) item.textContent = text;
  return item;
}

export async function openRules(onChanged) {
  const dialog = node("dialog");
  const heading = node("div");
  heading.className = "dialog-head";
  const close = node("button", "关闭规则");
  close.onclick = () => dialog.close();
  heading.append(node("h2", "已记住的识别规则"), close);
  const body = node("div");
  body.append(node("p", "页面地址 > 相同标题 > 网站域名 > 整个应用；同等范围的新规则优先。删除规则会重新分类已有记录，保留单独的人工修改。"));
  const status = node("p");
  status.setAttribute("role", "status");
  const list = node("div");
  body.append(status, list);
  dialog.append(heading, body);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();

  async function load() {
    const response = await fetch("/api/classification/rules");
    if (!response.ok) throw new Error("无法读取规则，请稍后重试。");
    const rules = await response.json();
    list.replaceChildren();
    if (!rules.length) list.append(node("p", "还没有记住的规则。在活动详情中纠正分类时，可选择自动识别范围。"));
    for (const rule of rules) {
      const item = node("article");
      item.className = "correction";
      const scope = {app: "整个应用", title: "相同标题", domain: "相同域名", url: "这个页面地址"}[rule.scope];
      item.append(node("h3", `${rule.app} · ${scope}`));
      if (rule.scope !== "app") item.append(node("p", rule.value));
      item.append(node("p", `${categoryLabels[rule.classification.category] || rule.classification.category} · ${rule.classification.content || "无内容名称"} · ${rule.classification.tags.join("，") || "无标签"}`));
      const remove = node("button", "删除这条规则");
      remove.onclick = async () => {
        remove.disabled = true;
        try {
          const result = await fetch(`/api/classification/rules/${encodeURIComponent(rule.id)}`, {method: "DELETE"});
          if (!result.ok && result.status !== 404) throw new Error("删除失败，请稍后重试。");
          await load();
          status.textContent = "规则已删除；单独的人工分类仍然保留。";
          await onChanged();
        } catch (error) {
          status.textContent = error.message;
          remove.disabled = false;
        }
      };
      item.append(remove);
      list.append(item);
    }
  }
  try { await load(); } catch (error) { status.textContent = error.message; }
}
