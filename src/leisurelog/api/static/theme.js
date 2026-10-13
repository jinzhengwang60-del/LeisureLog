// Appearance UI is independent of activity rendering and never touches the API.
const appearance = window.LeisureAppearance;
const button = document.getElementById("theme-toggle");
const MODES = {system: "跟随系统", light: "浅色", dark: "深色"};
const DESCRIPTIONS = {
  sticker: "奶油点阵纸 · 手写标题 · 便利贴与纸胶带",
  minimal: "暖白纸色 · 一种强调色 · 大号数字 · 颜色只留给分类",
  terminal: "Windows 98 · 宋体与立体边框 · 资源管理器列表 · 任务栏",
  sunny: "窗边插画铺满页头 · 随真实时间变换晨昏 · 毛玻璃卡片",
  editorial: "报头与双线 · Georgia 旧式数字 · 左栏要目 · 斜体注释",
  arcade: "PICO-8 十六色 · 扫描线屏幕 · 按键手感 · 高分榜",
};

if (button && appearance) {
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-controls", "appearance-dialog");
  const dialog = document.createElement("dialog");
  dialog.id = "appearance-dialog";
  dialog.className = "appearance-dialog";
  dialog.setAttribute("aria-labelledby", "appearance-title");
  dialog.innerHTML = `
    <div class="dialog-head"><div><p class="eyebrow">LEISURELOG / APPEARANCE</p>
      <h2 id="appearance-title">换一套界面</h2></div>
      <button type="button" data-close aria-label="关闭界面风格">✕</button></div>
    <p>每套风格都有自己的字体、导航、卡片和页面布局。选择后立即应用。</p>
    <div class="skin-options" role="group" aria-label="整套界面风格">
      ${Object.entries(appearance.SKINS).map(([id, skin]) => `
        <button type="button" class="skin-option" data-skin="${id}" aria-pressed="false">
          <span class="skin-preview preview-${id}" aria-hidden="true">
            <i class="preview-nav"></i><i class="preview-heading"></i>
            <i class="preview-timeline"></i><i class="preview-metrics"></i><i class="preview-table"></i>
          </span><strong>${skin.name}</strong><span class="skin-description">${DESCRIPTIONS[id]}</span>
          <span class="skin-selected">使用这套</span>
        </button>`).join("")}
    </div>
    <fieldset class="appearance-modes"><legend>明暗模式</legend>
      ${Object.entries(MODES).map(([mode, name]) => `<label><input type="radio" name="appearance-mode" value="${mode}">${name}</label>`).join("")}
    </fieldset>
    <fieldset class="appearance-modes appearance-motion"><legend>动态效果</legend>
      <label><input type="checkbox" name="appearance-motion">轻柔动画</label>
      <small class="motion-hint"></small>
    </fieldset>
    <p class="appearance-message" id="appearance-message" role="status" aria-live="polite"></p>
    <div class="appearance-footer"><span>只保存界面偏好，活动记录和筛选保持原样。</span>
      <button type="button" class="primary" data-close>完成</button></div>`;
  document.body.append(dialog);
  const message = dialog.querySelector(".appearance-message");
  const motionToggle = dialog.querySelector("[name=appearance-motion]");
  let queue = Promise.resolve();
  let busy = false;
  function render() {
    const preference = appearance.current;
    button.querySelector("span").textContent = `界面风格 · ${appearance.SKINS[preference.style].name}`;
    button.title = "切换整套界面风格与明暗模式";
    button.setAttribute("aria-label", `界面风格：${appearance.SKINS[preference.style].name}`);
    dialog.querySelectorAll("[data-skin]").forEach(option => {
      const selected = option.dataset.skin === preference.style;
      option.setAttribute("aria-pressed", String(selected));
      option.querySelector(".skin-selected").textContent = selected ? "✓ 正在使用" : "使用这套";
      option.disabled = busy;
    });
    dialog.querySelectorAll("[name=appearance-mode]").forEach(input => {
      if (!busy) input.checked = input.value === preference.mode;
      input.disabled = busy;
    });
    dialog.setAttribute("aria-busy", String(busy));
    motionToggle.checked = window.LeisureMotion?.requested ?? true;
    const hint = dialog.querySelector(".motion-hint");
    hint.textContent = window.LeisureMotion?.reduced
      ? "系统已开启减少动态效果，当前显示静态界面。" : "页面、卡片与操作的轻柔过渡。";
  }
  function loadSkin(style) {
    return new Promise((resolve, reject) => {
      const old = document.getElementById("skin-stylesheet");
      const candidate = document.createElement("link");
      candidate.rel = "stylesheet";
      candidate.media = "not all";
      const timeout = window.setTimeout(fail, 10000);
      function fail() {
        window.clearTimeout(timeout);
        candidate.onload = candidate.onerror = null;
        candidate.remove();
        reject(new Error("这套界面暂时没有加载成功，请重试。当前风格已保留。"));
      }
      candidate.onerror = fail;
      candidate.onload = () => {
        window.clearTimeout(timeout);
        candidate.onload = candidate.onerror = null;
        resolve(() => {
          old.remove();
          candidate.id = "skin-stylesheet";
          candidate.media = "all";
        });
      };
      candidate.href = appearance.SKINS[style].href;
      old.after(candidate);
    });
  }
  function change(preference, persist = true) {
    queue = queue.then(async () => {
      busy = true;
      render();
      message.textContent = "正在换装…";
      try {
        const commit = preference.style !== appearance.current.style ? await loadSkin(preference.style) : null;
        const apply = () => { commit?.(); appearance.current = preference; };
        if (window.LeisureMotion) await window.LeisureMotion.transitionAppearance(apply);
        else apply();
        if (persist) {
          try {
            localStorage.setItem(appearance.KEY, JSON.stringify(appearance.current));
            message.textContent = "已应用，刷新和切换页面后仍会使用这套界面。";
          } catch { message.textContent = "已应用。本浏览器不允许保存偏好，刷新后可能恢复默认。"; }
        } else message.textContent = "已同步其他页面的界面选择。";
      } catch (error) { message.textContent = error.message; }
      finally { busy = false; render(); }
    });
  }
  button.addEventListener("click", () => { render(); dialog.showModal(); });
  dialog.querySelectorAll("[data-close]").forEach(close => close.addEventListener("click", () => dialog.close()));
  dialog.addEventListener("close", () => button.focus());
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.querySelectorAll("[data-skin]").forEach(option => option.addEventListener("click", () => {
    change({...appearance.current, style: option.dataset.skin});
  }));
  dialog.querySelectorAll("[name=appearance-mode]").forEach(input => input.addEventListener("change", () => {
    change({...appearance.current, mode: input.value});
  }));
  motionToggle.addEventListener("change", () => {
    const saved = window.LeisureMotion?.setEnabled(motionToggle.checked);
    message.textContent = saved === false ? "已应用。本浏览器暂时无法保存动画偏好。" : "已应用动画偏好。";
    render();
  });
  window.addEventListener("leisurelog:motion", render);
  window.addEventListener("storage", event => {
    if (event.key === appearance.KEY || event.key === "leisurelog:theme" || event.key === null) change(appearance.read(), false);
  });
  appearance.system.addEventListener("change", () => appearance.applyRoot(appearance.current));
  function fallback() {
    render();
    message.textContent = "所选风格加载失败，暂时显示贴纸手帐。可以重新选择。";
  }
  window.addEventListener("leisurelog:skin-fallback", fallback);
  render();
  if (appearance.initialError) fallback();
}
