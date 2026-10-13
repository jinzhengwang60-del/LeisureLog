function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function bytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1048576) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1048576).toFixed(2)} MB`;
}

function time(value) {
  return value ? new Date(value).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai", hour12: false}) : "暂无记录";
}

export async function openStorage() {
  const dialog = node("dialog");
  const header = node("div", undefined, "dialog-head");
  const close = node("button", "关闭存储与备份");
  close.onclick = () => dialog.close();
  header.append(node("h2", "存储与备份"), close);
  const status = node("p", "正在读取…");
  status.setAttribute("role", "status");
  const overview = node("div");
  const actions = node("div", undefined, "correction-actions");
  const backup = node("button", "创建本地备份", "primary");
  const refresh = node("button", "刷新存储情况");
  const history = node("div");
  const cleanup = node("button", "备份并整理旧快照");
  cleanup.disabled = true;
  const cleanupInfo = node("p");
  const cleanupBox = node("section", undefined, "correction");
  cleanupBox.append(node("h3", "整理原始记录的更新版本"), cleanupInfo,
    node("p", "保留每条活动的最新原始记录、全部日期的活动历史、人工分类和识别规则。仅移除已被新版本替代的原始快照；旧版本仍可从整理前备份找回。"),
    node("p", "执行前自动创建并验证完整备份，再整理并尝试回收数据库空间。备份会额外占用空间，这次操作不保证硬盘总占用立即减少。"), cleanup);
  actions.append(backup, refresh);
  dialog.append(header, status, overview, actions,
    node("p", "每次备份保存完整数据库，并在独立临时数据库中恢复、核对全部表的数据及完整性。备份另存分类配置文件，不会替换当前数据库。"),
    node("p", "全部历史继续保留，仅按需整理旧快照，不按日期删除活动。备份也会占用空间；同一硬盘上的备份用于恢复误操作，长期保存请再复制到其他磁盘。"), cleanupBox, history);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();

  async function load() {
    const response = await fetch("/api/storage");
    if (!response.ok) throw new Error("无法读取存储情况，请检查服务是否运行。");
    const data = await response.json();
    cleanupInfo.textContent = `目前有 ${data.superseded_snapshots} 份原始更新快照可以整理。`;
    cleanup.disabled = data.superseded_snapshots === 0;
    overview.replaceChildren();
    const metrics = node("div", undefined, "detail-summary");
    for (const [label, value] of [["当前数据库及辅助文件", bytes(data.live_bytes)],
      ["备份目录占用", bytes(data.backup_bytes)], ["已保存的备份", `${data.backups.length} 份`]]) {
      const item = node("div");
      item.append(node("small", label), node("strong", value));
      metrics.append(item);
    }
    overview.append(metrics, node("p", `数据库位置：${data.database_path}`, "detail-title"),
      node("p", `备份位置：${data.backup_directory}`, "detail-title"),
      node("p", `记录范围（北京时间）：${time(data.earliest_record_at)} — ${time(data.latest_record_at)}`),
      node("p", `活动 ${data.counts.activity_events} 条 · 活动片段 ${data.counts.sessions} 个 · 原始快照 ${data.counts.raw_events} 份 · 离开状态 ${data.counts.idle_events} 条`),
      node("p", `人工分类 ${data.counts.manual_overrides} 条 · 已记住规则 ${data.counts.learned_rules} 条`),
      node("p", `主数据库 ${bytes(data.database_bytes)} · 写入日志 ${bytes(data.wal_bytes)} · 共享辅助文件 ${bytes(data.shm_bytes)}。文件大小会随写入与日志回收变化。`));
    const automatic = data.automatic_backup;
    history.replaceChildren(node("h3", "自动备份与已有备份"),
      node("p", automatic.enabled ? `每 ${automatic.every_days} 天自动备份一次，保留最近 ${automatic.keep} 份自动备份；手动备份继续保留。备份独立于活动同步，关闭同步或 ActivityWatch 暂时离线时也会检查。`
        : "自动备份已关闭，仍然可以手动创建完整备份。"));
    if (automatic.enabled) history.append(node("p", `最近检查：${time(automatic.last_attempt_at)} · ${automatic.running ? "正在检查" : automatic.last_error ? "检查失败，将在下次重试" : "等待下一次检查"}`));
    if (automatic.last_error) history.append(node("p", "自动备份检查失败。请检查磁盘空间及目录权限；也可以尝试手动备份。", "error"));
    if (!data.backups.length) history.append(node("p", "还没有备份，点击上方按钮创建第一份。"));
    for (const item of data.backups) {
      const row = node("article", undefined, "correction");
      row.append(node("p", `${item.automatic ? "自动备份" : "手动备份"} · ${time(item.created_at)} · ${bytes(item.bytes)} · ${item.verified ? "恢复核对通过" : "未验证"}`),
        node("p", item.name, "detail-title"),
        node("p", `活动 ${item.counts.activity_events} 条 · 人工分类 ${item.counts.manual_overrides} 条 · 识别规则 ${item.counts.learned_rules} 条`));
      const download = node("a", "下载完整备份（含分类配置）");
      download.href = item.archive_url;
      download.download = item.name.replace(/\.db$/, ".zip");
      row.append(download);
      history.append(row);
    }
  }

  backup.onclick = async () => {
    backup.disabled = refresh.disabled = cleanup.disabled = true;
    status.textContent = "正在备份并验证恢复，请稍候…";
    try {
      const response = await fetch("/api/storage/backups", {method: "POST"});
      if (!response.ok) throw new Error(response.status === 409 ? "另一份备份正在创建，请稍后刷新。" : "备份失败，请检查磁盘空间和文件权限后重试。");
      await response.json();
      await load();
      status.textContent = "备份已保存，独立恢复核对通过。";
    } catch (error) { status.textContent = error.message; }
    finally { backup.disabled = refresh.disabled = false; }
  };
  cleanup.onclick = async () => {
    backup.disabled = refresh.disabled = cleanup.disabled = true;
    status.textContent = "正在备份、验证和整理旧快照，请稍候…";
    try {
      const response = await fetch("/api/storage/compact", {method: "POST"});
      if (!response.ok) throw new Error(response.status === 409 ? "另一项存储操作正在执行，请稍后刷新。" : "整理未完成，请检查服务和磁盘空间；不会删除没有备份的旧版本。");
      const result = await response.json();
      await load();
      status.textContent = result.deleted_snapshots === 0 ? "没有需要整理的旧快照，活动历史保持完整。"
        : `已整理 ${result.deleted_snapshots} 份旧快照。数据库及辅助文件：${bytes(result.before_bytes)} → ${bytes(result.after_bytes)}。活动历史与人工分类保留，整理前备份已保存。${result.warning ? "空间回收尚未完全完成，使用中的日志可能稍后释放。" : ""}`;
    } catch (error) {
      status.textContent = error.message;
      try { await load(); } catch {}
    } finally { backup.disabled = refresh.disabled = false; }
  };
  refresh.onclick = async () => {
    try { await load(); status.textContent = "存储情况已更新。"; }
    catch (error) { status.textContent = error.message; }
  };
  try { await load(); status.textContent = "数据保存在本机，以下数量覆盖全部日期。"; }
  catch (error) { status.textContent = error.message; backup.disabled = true; }
}
