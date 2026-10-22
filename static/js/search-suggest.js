// Header search suggestions: categories and listing titles from the server, plus recent searches
// kept only in this browser. Works as an ARIA combobox; the form still submits normally without JS.
document.querySelectorAll("[data-search-suggest]").forEach((form, formIndex) => {
  const input = form.querySelector('input[name="q"]');
  const endpoint = form.dataset.searchSuggest;
  const listUrl = form.getAttribute("action");
  const RECENT_KEY = "gm-recent-searches";
  const panel = document.createElement("ul");
  panel.id = `search-suggestions-${formIndex}`;
  panel.className = "search-suggestions";
  panel.setAttribute("role", "listbox");
  panel.hidden = true;
  form.append(panel);
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", panel.id);
  input.setAttribute("aria-expanded", "false");

  let items = [];
  let active = -1;
  let timer;
  let controller;

  const readRecent = () => {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").slice(0, 5); } catch { return []; }
  };
  const saveRecent = (term) => {
    term = term.trim();
    if (term.length < 2) return;
    try {
      const recent = readRecent().filter((item) => item.toLowerCase() !== term.toLowerCase());
      localStorage.setItem(RECENT_KEY, JSON.stringify([term, ...recent].slice(0, 5)));
    } catch { /* storage unavailable (private mode) */ }
  };
  const searchUrl = (term) => `${listUrl}?q=${encodeURIComponent(term)}`;

  const close = () => {
    panel.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };

  const render = (groups) => {
    panel.replaceChildren();
    items = [];
    groups.forEach(({ title, entries }) => {
      if (!entries.length) return;
      const heading = document.createElement("li");
      heading.className = "search-suggestions-heading";
      heading.setAttribute("role", "presentation");
      heading.textContent = title;
      panel.append(heading);
      entries.forEach(({ label, url }) => {
        const option = document.createElement("li");
        option.id = `suggestion-${formIndex}-${items.length}`;
        option.setAttribute("role", "option");
        option.className = "search-suggestion";
        option.textContent = label;
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          go(url, label);
        });
        panel.append(option);
        items.push({ element: option, url, label });
      });
    });
    panel.hidden = items.length === 0;
    input.setAttribute("aria-expanded", String(!panel.hidden));
  };

  const go = (url, label) => {
    if (label) saveRecent(label);
    window.location.href = url;
  };

  const highlight = (index) => {
    items.forEach((item, i) => item.element.classList.toggle("is-active", i === index));
    active = index;
    if (index >= 0) input.setAttribute("aria-activedescendant", items[index].element.id);
    else input.removeAttribute("aria-activedescendant");
  };

  const showRecent = () => {
    const recent = readRecent();
    render([{ title: "Recent searches", entries: recent.map((term) => ({ label: term, url: searchUrl(term) })) }]);
  };

  const fetchSuggestions = async (term) => {
    controller?.abort();
    controller = new AbortController();
    try {
      const response = await fetch(`${endpoint}?q=${encodeURIComponent(term)}`, { signal: controller.signal });
      if (!response.ok) return;
      const data = await response.json();
      if (input.value.trim() !== term) return;
      render([
        { title: "Categories", entries: data.categories.map((c) => ({ label: c.label, url: c.url })) },
        { title: "Listings", entries: data.listings.map((title) => ({ label: title, url: searchUrl(title) })) },
      ]);
    } catch { /* offline or aborted: keep the plain search box working */ }
  };

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const term = input.value.trim();
    if (term.length < 2) { showRecent(); return; }
    timer = setTimeout(() => fetchSuggestions(term), 200);
  });
  input.addEventListener("focus", () => { if (input.value.trim().length < 2) showRecent(); });
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (event) => {
    if (panel.hidden || !items.length) return;
    if (event.key === "ArrowDown") { event.preventDefault(); highlight((active + 1) % items.length); }
    else if (event.key === "ArrowUp") { event.preventDefault(); highlight((active - 1 + items.length) % items.length); }
    else if (event.key === "Escape") { close(); }
    else if (event.key === "Enter" && active >= 0) { event.preventDefault(); go(items[active].url, items[active].label); }
  });
  form.addEventListener("submit", () => saveRecent(input.value));
});
