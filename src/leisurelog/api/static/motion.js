// Presentation only: animation preferences and short, cancellable transitions.
(() => {
  const KEY = "leisurelog:motion";
  const root = document.documentElement;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const played = new WeakMap();
  const running = new Set();
  const byElement = new WeakMap();
  const pending = new WeakMap();
  let revealObserver;
  let activeTransition;
  const read = () => { try { return localStorage.getItem(KEY) !== "0"; } catch { return true; } };
  let requested = read();
  const enabled = () => requested && !reduced.matches;

  function apply() {
    root.dataset.motion = enabled() ? "on" : "off";
    const stylesheet = document.getElementById("motion-stylesheet");
    if (stylesheet) stylesheet.media = enabled() ? "all" : "not all";
    if (!enabled()) {
      for (const animation of running) animation.cancel();
      activeTransition?.skipTransition();
    }
    window.dispatchEvent(new Event("leisurelog:motion"));
  }

  function animate(elements, {kind = "enter", distance = 8, stagger = 28} = {}) {
    if (!enabled() || document.hidden) return;
    const duration = {sticker: 340, minimal: 260, terminal: 180, sunny: 380, editorial: 320, arcade: 220}[root.dataset.style] || 300;
    elements.filter(element => element.getClientRects().length).slice(0, 16).forEach((element, index) => {
      if (typeof element.animate !== "function") return;
      byElement.get(element)?.cancel();
      // Individual translate/scale properties preserve a skin's existing rotation.
      const frames = kind === "bar"
        ? [{scale: "0 1"}, {scale: "1 1"}]
        : [{opacity: 0, translate: `0 ${distance}px`}, {opacity: 1, translate: "0 0"}];
      const animation = element.animate(frames, {
        duration, delay: Math.min(index * stagger, 168), easing: "cubic-bezier(.22,1,.36,1)", fill: "backwards",
      });
      running.add(animation);
      byElement.set(element, animation);
      animation.finished.catch(() => {}).finally(() => {
        running.delete(animation);
        if (byElement.get(element) === animation) byElement.delete(element);
      });
    });
  }

  function reveal(container, {key = "initial", selector = ":scope > *", kind = "enter", distance = 8} = {}) {
    if (!container || played.get(container) === key) return;
    const elements = [...container.querySelectorAll(selector)];
    if (!elements.length) return;
    // A refresh of the same query updates data without replaying the entrance.
    played.set(container, key);
    const rect = container.getBoundingClientRect?.();
    if (typeof IntersectionObserver === "function" && rect && (rect.top >= window.innerHeight || rect.bottom <= 0)) {
      if (!revealObserver) revealObserver = new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const options = pending.get(entry.target);
          revealObserver.unobserve(entry.target);
          pending.delete(entry.target);
          // Read the current children: a background refresh may have replaced them.
          if (options) animate([...entry.target.querySelectorAll(options.selector)], options);
        }
      }, {threshold: .04});
      pending.set(container, {selector, kind, distance});
      revealObserver.observe(container);
    } else {
      pending.delete(container);
      revealObserver?.unobserve(container);
      animate(elements, {kind, distance});
    }
  }

  async function transitionAppearance(update) {
    if (!enabled() || document.hidden || typeof document.startViewTransition !== "function") { update(); return; }
    let transition;
    try { transition = document.startViewTransition(update); }
    catch { update(); return; }
    activeTransition = transition;
    transition.ready.catch(() => {});
    transition.finished.catch(() => {}).finally(() => {
      if (activeTransition === transition) activeTransition = undefined;
    });
    await transition.updateCallbackDone;
    // Keep appearance controls busy until the snapshot overlay stops intercepting input.
    await transition.finished.catch(() => {});
  }

  window.LeisureMotion = {
    get enabled() { return enabled(); },
    get requested() { return requested; },
    get reduced() { return reduced.matches; },
    setEnabled(value) {
      requested = Boolean(value);
      let saved = true;
      try { localStorage.setItem(KEY, requested ? "1" : "0"); } catch { saved = false; }
      apply();
      return saved;
    },
    reveal, transitionAppearance,
  };
  reduced.addEventListener("change", apply);
  window.addEventListener("storage", event => {
    if (event.key === KEY || event.key === null) { requested = read(); apply(); }
  });
  apply();

  function enterPage() {
    const main = document.querySelector("main");
    if (!main) return;
    animate([...document.querySelectorAll(".top, main > .heading, main > .day-head")], {distance: 5, stagger: 40});
    const panels = [...main.querySelectorAll(".today > article, .metrics > article, .ribbon, .chart-panel, .records, .project-empty")];
    if (typeof IntersectionObserver === "function") {
      const observer = new IntersectionObserver(entries => {
        const visible = entries.filter(entry => entry.isIntersecting);
        visible.forEach(entry => observer.unobserve(entry.target));
        animate(visible.map(entry => entry.target));
      }, {threshold: .04});
      panels.forEach(panel => observer.observe(panel));
      window.addEventListener("pagehide", event => {
        if (!event.persisted) { observer.disconnect(); revealObserver?.disconnect(); }
      });
    } else animate(panels);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", enterPage, {once: true});
  else enterPage();
  document.addEventListener("toggle", event => {
    if (event.target.tagName !== "DETAILS" || !event.target.open || event.target.classList.contains("tools")) return;
    animate([...event.target.children].filter(child => child.tagName !== "SUMMARY"), {distance: 5});
  }, true);
})();
