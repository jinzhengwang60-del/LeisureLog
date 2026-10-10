// Runs before paint. Publishes the current time of day as CSS variables so the sunny skin's
// illustration follows the real day; other skins ignore them. Add ?sky-hour=18.5 to preview a time.
(() => {
  const NIGHT = {top: "#39406a", mid: "#2f3962", low: "#3a3550",
    glow: [60, 70, 140, 0], beam: [0, 0, 0, 0], lamp: 1, moon: 1};
  // [hour, look]: top/mid/low multiply the illustration from sky to desk; glow lights the horizon,
  // beam is late sunlight through the window, lamp is the warm room light, moon fades in at night.
  const KEYS = [
    [0, NIGHT],
    [4.8, NIGHT],
    [6, {top: "#b8a3c4", mid: "#e8b3a8", low: "#c9a3a3",
      glow: [255, 150, 120, .45], beam: [255, 170, 120, .12], lamp: .3, moon: .15}],
    [7.3, {top: "#f2e6ea", mid: "#fde3cc", low: "#f0dccb",
      glow: [255, 200, 150, .18], beam: [255, 214, 160, .18], lamp: 0, moon: 0}],
    [9.5, {top: "#ffffff", mid: "#fffaf3", low: "#fbf3ea",
      glow: [255, 230, 200, .05], beam: [255, 236, 200, .1], lamp: 0, moon: 0}],
    [13, {top: "#ffffff", mid: "#ffffff", low: "#ffffff",
      glow: [255, 230, 200, 0], beam: [255, 240, 210, .06], lamp: 0, moon: 0}],
    [16, {top: "#fff6ea", mid: "#fff0dc", low: "#fbe8d2",
      glow: [255, 210, 150, .08], beam: [255, 210, 150, .16], lamp: 0, moon: 0}],
    [17.6, {top: "#e9c9c4", mid: "#ffcf9e", low: "#f2c4a0",
      glow: [255, 160, 90, .35], beam: [255, 170, 90, .28], lamp: 0, moon: 0}],
    [18.6, {top: "#a98fb8", mid: "#f39a7c", low: "#d49a8c",
      glow: [255, 120, 80, .5], beam: [255, 130, 80, .2], lamp: .2, moon: 0}],
    [19.5, {top: "#5a5a8c", mid: "#7c6a96", low: "#6c6080",
      glow: [180, 110, 150, .25], beam: [0, 0, 0, 0], lamp: .85, moon: .5}],
    [21, NIGHT],
    [24, NIGHT],
  ];
  const hex = value => [1, 3, 5].map(i => parseInt(value.slice(i, i + 2), 16));
  const lerp = (a, b, t) => a + (b - a) * t;
  const rgb = c => `rgb(${c.map(Math.round).join(",")})`;
  const rgba = c => `rgba(${c.slice(0, 3).map(Math.round).join(",")},${+c[3].toFixed(3)})`;

  function phase(hour) {
    return hour < 5 || hour >= 20 ? "night" : hour < 7.5 ? "dawn" : hour < 17 ? "day" : "dusk";
  }
  function look(hour) {
    hour = ((hour % 24) + 24) % 24;
    let i = 0;
    while (KEYS[i + 1][0] <= hour && i < KEYS.length - 2) i++;
    const [h0, a] = KEYS[i], [h1, b] = KEYS[i + 1];
    const t = (hour - h0) / (h1 - h0);
    const color = key => rgb(hex(a[key]).map((v, n) => lerp(v, hex(b[key])[n], t)));
    const light = key => rgba(a[key].map((v, n) => lerp(v, b[key][n], t)));
    return {
      phase: phase(hour),
      vars: {
        "--sky-top": color("top"), "--sky-mid": color("mid"), "--sky-low": color("low"),
        "--sky-glow": light("glow"), "--sky-beam": light("beam"),
        "--sky-lamp": +lerp(a.lamp, b.lamp, t).toFixed(3), "--sky-moon": +lerp(a.moon, b.moon, t).toFixed(3),
      },
    };
  }
  function previewHour(search) {
    const raw = new URLSearchParams(search || "").get("sky-hour");
    const hour = raw === null || raw.trim() === "" ? NaN : Number(raw);
    return hour >= 0 && hour < 24 ? hour : null;
  }
  function currentHour(now = new Date()) {
    return previewHour(window.location?.search) ?? now.getHours() + now.getMinutes() / 60;
  }
  function apply(root = document.documentElement, hour = currentHour()) {
    const {phase: name, vars} = look(hour);
    for (const [key, value] of Object.entries(vars)) root.style.setProperty(key, String(value));
    root.dataset.sky = name;
    return name;
  }

  window.LeisureSkyClock = {look, phase, previewHour, currentHour, apply};
  apply();
  window.setInterval(() => apply(), 60000);
  document.addEventListener?.("visibilitychange", () => { if (!document.hidden) apply(); });
})();
