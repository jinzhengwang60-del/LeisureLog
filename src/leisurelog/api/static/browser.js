function node(tag, text) {
  const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el;
}
export async function openBrowserSetup() {
  const dialog = node("dialog"), header = node("div"), close = node("button", "关闭浏览器接入");
  header.className = "dialog-head"; close.onclick = () => dialog.close();
  header.append(node("h2", "Edge 与 Chrome 网页记录"), close);
  const status = node("p", "正在检查 ActivityWatch…"), list = node("div");
  status.setAttribute("role", "status");
  const install = node("a", "打开官方 Web Watcher 安装页");
  install.href = "https://chromewebstore.google.com/detail/activitywatch-web-watcher/nglaklhklhcoonedhgnpgddginnjdadi";
  install.target = "_blank"; install.rel = "noopener noreferrer";
  const refresh = node("button", "重新检查接入状态");
  dialog.append(header, node("p", "分别在日常使用的 Edge 和 Chrome 中安装官方扩展。保持 ActivityWatch 运行，正常访问网页后，LeisureLog 每分钟自动导入。"), install,
    node("p", "只使用普通 HTTP/HTTPS 页面。隐私窗口及浏览器内部页面不导入 LeisureLog。网页记录用来补充前台窗口的标题和网址，不额外增加时长；后台标签页不作为独立活动计时。"), status, list, refresh);
  document.body.append(dialog); dialog.addEventListener("close", () => dialog.remove(), {once:true}); dialog.showModal();
  async function load() {
    refresh.disabled = true;
    try {
      const response = await fetch("/api/browser/status"); if (!response.ok) throw new Error("无法读取 ActivityWatch，请检查它是否运行。");
      const data = await response.json(); list.replaceChildren();
      status.textContent = data.buckets.length ? `已发现 ${data.buckets.length} 个网页数据源，已导入 ${data.browser_records} 条网页记录，已关联 ${data.matched_segments} 个前台活动片段。` : "尚未发现网页记录：请在 Edge 和 Chrome 分别安装扩展，并正常访问一个网页后再检查。";
      for (const bucket of data.buckets) list.append(node("p", `${bucket.id} · ${bucket.records} 条 · 设备：${bucket.devices.join("、") || "等待导入"}`));
      if (data.browser_records && !data.matched_segments) list.append(node("p", "已有网页数据，但暂未与前台窗口匹配。系统会保留窗口记录；标题、设备或时间不匹配时不会强行关联。"));
    } catch(error) { status.textContent = error.message; }
    finally { refresh.disabled = false; }
  }
  refresh.onclick = load; await load();
}
