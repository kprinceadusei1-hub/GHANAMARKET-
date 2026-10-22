// Control Centre chrome: collapsible sidebar (desktop rail / mobile drawer), dropdown menus, filters.
(() => {
  const root = document.documentElement;
  const mobile = window.matchMedia("(max-width: 1023px)");
  const scrim = document.querySelector("[data-cc-nav-close]");

  const setDrawer = (open) => {
    root.classList.toggle("cc-drawer-open", open);
    if (scrim) scrim.hidden = !open;
  };

  document.querySelectorAll("[data-cc-nav-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      if (mobile.matches) {
        setDrawer(!root.classList.contains("cc-drawer-open"));
        return;
      }
      const collapsed = root.classList.toggle("cc-collapsed");
      try { localStorage.setItem("gm.cc.collapsed", collapsed ? "1" : "0"); } catch (e) { /* storage unavailable */ }
      button.setAttribute("aria-expanded", String(!collapsed));
    });
  });
  scrim?.addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    setDrawer(false);
    document.querySelectorAll(".cc-menu[open]").forEach((menu) => menu.removeAttribute("open"));
  });

  // In the collapsed rail, opening a group expands the sidebar so its links are readable.
  document.querySelectorAll(".cc-nav-group > summary").forEach((summary) => {
    summary.addEventListener("click", () => {
      if (!mobile.matches && root.classList.contains("cc-collapsed")) {
        root.classList.remove("cc-collapsed");
        try { localStorage.setItem("gm.cc.collapsed", "0"); } catch (e) { /* storage unavailable */ }
      }
    });
  });

  // Close dropdown menus when clicking elsewhere; only one open at a time.
  document.addEventListener("click", (event) => {
    document.querySelectorAll(".cc-menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
  });

  document.querySelectorAll("[data-autosubmit]").forEach((select) => {
    select.addEventListener("change", () => select.form.submit());
  });
})();

// Live queue counts: poll every minute while the tab is visible and update the bell, menu and quick stats.
(() => {
  const header = document.querySelector("[data-pulse-url]");
  if (!header) return;
  const url = header.dataset.pulseUrl;
  const status = document.querySelector("[data-pulse-status]");
  const refresh = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      document.querySelectorAll("[data-pulse-total]").forEach((badge) => {
        badge.textContent = data.total;
        badge.hidden = !data.total;
      });
      document.querySelectorAll("[data-pulse-queue]").forEach((node) => {
        const value = data.queues[node.dataset.pulseQueue];
        if (value === undefined) return;
        node.textContent = value;
        node.classList.toggle("is-hot", value > 0 && node.classList.contains("cc-pill"));
      });
      if (status) status.textContent = `Live counts updated at ${data.checked_at}.`;
    } catch (error) { /* offline: keep the last counts */ }
  };
  setInterval(refresh, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
})();
