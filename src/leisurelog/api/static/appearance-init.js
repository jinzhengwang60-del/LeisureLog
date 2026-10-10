// Runs before paint. Each skin owns its stylesheet, typography and layout.
(() => {
  const KEY = "leisurelog:appearance";
  const MODES = ["system", "light", "dark"];
  const SKINS = {
    sticker: {name: "手帐", href: "/static/style.css?v=redesign1"},
    minimal: {name: "素白", href: "/static/skins/minimal.css?v=redesign1"},
    terminal: {name: "旧电脑", href: "/static/skins/terminal.css?v=redesign1"},
    sunny: {name: "窗边", href: "/static/skins/sunny.css?v=redesign1"},
    editorial: {name: "周刊", href: "/static/skins/editorial.css?v=redesign1"},
    arcade: {name: "掌机", href: "/static/skins/arcade.css?v=redesign1"},
  };
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  function normalize(value, fallbackMode = "system") {
    return {
      style: Object.hasOwn(SKINS, value?.style) ? value.style : "sticker",
      mode: MODES.includes(value?.mode) ? value.mode : fallbackMode,
    };
  }
  function read() {
    try {
      const legacy = localStorage.getItem("leisurelog:theme");
      const fallbackMode = MODES.includes(legacy) ? legacy : "system";
      let value;
      try { value = JSON.parse(localStorage.getItem(KEY)); } catch { /* damaged preference */ }
      return normalize(value, fallbackMode);
    } catch { return normalize(null); }
  }
  function applyRoot(preference) {
    const root = document.documentElement;
    root.dataset.style = preference.style;
    root.dataset.mode = preference.mode;
    root.dataset.theme = preference.mode === "system"
      ? (system.matches ? "dark" : "light") : preference.mode;
  }
  let current = read();
  let initialError = false;
  applyRoot(current);
  window.LeisureAppearance = {
    KEY, MODES, SKINS, system, normalize, read, applyRoot,
    get current() { return {...current}; },
    set current(value) { current = normalize(value); applyRoot(current); },
    get initialError() { return initialError; },
    initializeSkin(link) {
      link.onerror = () => {
        initialError = true;
        current = {...current, style: "sticker"};
        applyRoot(current);
        link.onerror = null;
        link.href = SKINS.sticker.href;
        window.dispatchEvent(new Event("leisurelog:skin-fallback"));
      };
      link.href = SKINS[current.style].href;
    },
  };
})();
