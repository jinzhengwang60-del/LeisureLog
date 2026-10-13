const $ = (id) => document.getElementById(id);
let state;
async function request(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options});
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "操作未完成，请稍后重试");
  return result;
}
function showError(error) { $("setup-error").textContent = error.message; $("setup-error").hidden = false; }
async function load() {
  state = await request("/_desktop/status");
  $("version").textContent = `本机安装版 · ${state.version}`;
  $("data-dir").textContent = state.data_dir;
  $("heading").textContent = state.setup_completed ? "本机设置与连接" : "欢迎使用 LeisureLog";
  $("first-run").hidden = state.setup_completed;
  $("running-settings").hidden = !state.setup_completed;
  $("sync-label").textContent = state.sync.enabled ? "自动同步已开启" : "自动同步已停止";
  $("toggle-sync").textContent = state.sync.enabled ? "停止自动同步" : "开启自动同步";
  $("sync-error").textContent = state.sync.last_error ? "最近一次同步没有完成，请检查 ActivityWatch 是否正在运行。" : "记录会每分钟自动整理一次。";
}
async function check() {
  $("check-aw").disabled = true;
  $("aw-status").textContent = "正在检查本机连接…";
  try {
    const result = await request("/_desktop/activitywatch");
    $("aw-status").textContent = result.connected ? "已连接本机 ActivityWatch" : "还没有连接到 ActivityWatch";
    $("offline-note").hidden = result.connected && result.currentwindow > 0;
    const entries = [
      [result.currentwindow, "前台应用记录", "没有发现窗口 watcher，请检查 ActivityWatch 托盘"],
      [result.afkstatus, "离开状态记录", "没有发现 AFK watcher，离开状态可能无法判断"],
      [result["web.tab.current"], "网页详情记录", "尚未接入浏览器扩展（可选）"],
    ];
    $("aw-details").replaceChildren(...entries.map(([count, label, missing]) => {
      const item = document.createElement("li");
      item.textContent = count ? `✓ ${label}已就绪` : `○ ${missing}`;
      return item;
    }));
  } finally { $("check-aw").disabled = false; }
}
$("consent").addEventListener("change", () => { $("finish-setup").disabled = !$("consent").checked; });
$("check-aw").addEventListener("click", () => check().catch(showError));
$("finish-setup").addEventListener("click", async () => {
  $("finish-setup").disabled = true;
  $("setup-error").hidden = true;
  try {
    await request("/_desktop/setup", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({consent:$("consent").checked, initial_hours:Number($("initial-hours").value)})});
    location.assign("/");
  } catch (error) { showError(error); $("finish-setup").disabled = !$("consent").checked; }
});
$("toggle-sync").addEventListener("click", async () => {
  $("toggle-sync").disabled = true;
  try {
    await request("/_desktop/sync", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled:!state.sync.enabled})});
    await load();
  } catch (error) { showError(error); }
  finally { $("toggle-sync").disabled = false; }
});
Promise.all([load(), check()]).catch(showError);
