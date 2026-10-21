// The host advertises only active, registered pages. Labels are rendered as text.
let revision = 0;

export function renderPluginNavigation(document, pages, pathname, managedUrls = []) {
  const available = new Set(pages.map(page => page.url));
  for (const slot of document.querySelectorAll('[data-plugin-navigation]')) {
    const links = pages.map(page => {
      const link = document.createElement('a');
      link.href = page.url;
      link.textContent = page.title;
      if (page.url === pathname) link.setAttribute('aria-current', 'page');
      return link;
    });
    slot.replaceChildren(...links);
    // Flatten the placeholder for existing skin navigation layouts.
    slot.style.display = 'contents';
  }
  const managed = new Set(managedUrls);
  for (const link of document.querySelectorAll('a[href]')) {
    const path = link.getAttribute('href').split('?')[0].split('#')[0];
    if (managed.has(path)) link.hidden = !available.has(path);
  }
}

export async function refreshPluginNavigation() {
  const current = ++revision;
  try {
    const response = await fetch('/api/plugin-navigation', {cache: 'no-store'});
    if (!response.ok) return;
    const data = await response.json();
    if (current !== revision || !Array.isArray(data.pages)) return;
    renderPluginNavigation(document, data.pages, location.pathname, data.managed_urls);
  } catch {
    // Keep navigation and core page controls usable during a service reconnect.
  }
}

// On narrow screens the navigation is one scrolling row; keep the current page in view.
function revealCurrentPage() {
  const nav = document.querySelector('.site-nav');
  const current = nav?.querySelector('[aria-current=page]');
  if (!current || nav.scrollWidth <= nav.clientWidth) return;
  const offset = current.getBoundingClientRect().left - nav.getBoundingClientRect().left;
  nav.scrollLeft += offset - (nav.clientWidth - current.offsetWidth) / 2;
}

if (typeof window !== 'undefined') {
  revealCurrentPage();
  refreshPluginNavigation().then(revealCurrentPage);
  window.addEventListener('focus', refreshPluginNavigation);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshPluginNavigation();
  });
}
