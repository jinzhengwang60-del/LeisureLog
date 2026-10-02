function node(tag, text) {
  const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el;
}
const labels = {afk:"按离开状态扣除", foreground:"按前台时长计入", audible:"前台网页有声音时保留"};
export function createTiming(data, onSaved) {
  const form = node("form"), heading = node("h3", "修正计时方式"); form.className = "correction";
  const s = data.session, select = node("select"), label = node("label", "计时方式");
  select.id = "timing-policy"; label.htmlFor = select.id;
  for (const [value, text] of [["automatic", "使用默认 / 配置策略"], ...Object.entries(labels)]) {
    const option = node("option", text); option.value = value; select.append(option);
  }
  select.value = s.timing_origin === "manual" ? s.timing_policy : "automatic";
  const detected = Math.round(s.detected_afk_seconds || 0), retained = Math.round(s.retained_afk_seconds || 0);
  form.append(heading, node("p", `当前：${labels[s.timing_policy] || s.timing_policy} · ${s.timing_origin === "manual" ? "人工选择" : s.timing_origin.startsWith("rule:") ? "配置规则" : "默认策略"}。检测到离开 ${detected} 秒，策略保留 ${retained} 秒，实际扣除 ${Math.round(s.afk_seconds)} 秒。`),
    node("p", "前台计入适合修正阅读、观看或手柄游戏被误判离开；它也会计入真正挂机的前台时间。有声音只是辅助依据，不能证明一直在观看。缺少离开状态的时间仍标为待确认。"), label, select);
  const hint = node("p", "本次显示的活动记录会一起修改；跨日记录的其他日期部分也会更新。恢复默认会重新应用配置规则。原始离开记录保留。");
  const error = node("p"); error.setAttribute("role", "alert");
  const save = node("button", "保存计时方式"); save.type = "submit"; save.className = "primary";
  form.append(hint, save, error);
  form.onsubmit = async event => {
    event.preventDefault(); save.disabled = true; error.textContent = "";
    try {
      const response = await fetch("/api/events/timing", {method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({event_ids:data.events.map(e=>e.id),policy:select.value === "automatic" ? null : select.value})});
      if (!response.ok) throw new Error(response.status === 404 ? "记录已变化，请刷新后重试。" : "保存计时方式失败，请重试。");
      await onSaved("计时方式已保存，活动时长与统计已更新。");
    } catch(e) { error.textContent = e.message; }
    finally { save.disabled = false; }
  };
  return form;
}
