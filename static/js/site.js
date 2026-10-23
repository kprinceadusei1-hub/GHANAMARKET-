// Prevent accidental double submission (e.g. tapping "Pay" twice on a slow connection).
// Buttons are re-enabled if the page is restored from the back/forward cache.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (event.defaultPrevented || form.method.toLowerCase() !== "post" || form.dataset.allowResubmit !== undefined) return;
  const button = event.submitter || form.querySelector('[type="submit"]');
  if (!button || button.disabled) return;
  if (button.name) {
    // A disabled button is not submitted, so carry its value in a hidden field.
    const carrier = document.createElement("input");
    carrier.type = "hidden";
    carrier.name = button.name;
    carrier.value = button.value;
    form.append(carrier);
  }
  setTimeout(() => {
    button.disabled = true;
    button.dataset.label = button.innerHTML;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Please wait…";
  }, 0);
});
window.addEventListener("pageshow", () => {
  document.querySelectorAll('button[aria-busy="true"]').forEach((button) => {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  });
});

// Header gains a shadow once the page scrolls.
(() => {
  const header = document.querySelector(".site-header");
  if (!header) return;
  const sync = () => header.classList.toggle("is-scrolled", window.scrollY > 8);
  window.addEventListener("scroll", sync, { passive: true });
  sync();
})();

// Sections fade up as they enter the viewport. Content is never left hidden: anything already on
// screen shows at once, and a safety timer reveals everything if the observer never fires.
(() => {
  const targets = [...document.querySelectorAll("[data-reveal]")];
  const showAll = () => targets.forEach((el) => el.classList.add("is-visible"));
  if (!("IntersectionObserver" in window)) {
    showAll();
    return;
  }
  setTimeout(showAll, 2000);
  targets.forEach((el) => {
    if (el.getBoundingClientRect().top < window.innerHeight) el.classList.add("is-visible");
  });
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-visible");
      observer.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px -8% 0px" });
  targets.forEach((el) => observer.observe(el));
})();

// Stop the image placeholder shimmer once a card photo has loaded (or failed).
document.querySelectorAll(".product-card-image").forEach((frame) => {
  const image = frame.querySelector("img");
  const done = () => frame.classList.add("is-loaded");
  if (!image || image.complete) done();
  else {
    image.addEventListener("load", done, { once: true });
    image.addEventListener("error", done, { once: true });
  }
});

// Category carousel arrows.
document.querySelectorAll("[data-carousel-prev], [data-carousel-next]").forEach((button) => {
  const rail = document.getElementById(button.dataset.carouselPrev || button.dataset.carouselNext);
  if (!rail) return;
  const direction = button.dataset.carouselPrev ? -1 : 1;
  button.addEventListener("click", () => rail.scrollBy({ left: direction * rail.clientWidth * 0.8, behavior: "smooth" }));
});

// Toasts dismiss themselves after a few seconds, or when closed.
document.querySelectorAll(".toast").forEach((toast, index) => {
  const dismiss = () => {
    toast.classList.add("is-leaving");
    toast.addEventListener("animationend", () => toast.remove(), { once: true });
    setTimeout(() => toast.remove(), 600);
  };
  toast.querySelector(".toast-close")?.addEventListener("click", dismiss);
  if (toast.classList.contains("error")) return;  // Errors stay until closed.
  let timer = setTimeout(dismiss, 8000 + index * 600);
  const pause = () => clearTimeout(timer);
  const resume = () => { clearTimeout(timer); timer = setTimeout(dismiss, 4000); };
  toast.addEventListener("mouseenter", pause);
  toast.addEventListener("focusin", pause);
  toast.addEventListener("mouseleave", resume);
  toast.addEventListener("focusout", resume);
});

document.querySelectorAll("[data-share]").forEach((link) => {
  link.addEventListener("click", async (event) => {
    if (!navigator.share) return;
    event.preventDefault();
    try {
      await navigator.share({ title: link.dataset.shareTitle, url: link.dataset.shareUrl });
    } catch (error) {
      if (error && error.name !== "AbortError") window.open(link.href, "_blank", "noopener");
    }
  });
});

// Keep the Messages badge current without reloading (signed-in pages only).
(() => {
  const url = document.body.dataset.unreadUrl;
  if (!url || document.querySelector("[data-chat-thread]")) return;
  const links = document.querySelectorAll('[data-unread="messages"]');
  async function refresh() {
    if (document.hidden) return;
    try {
      const response = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
      if (!response.ok) return;
      const { messages } = await response.json();
      links.forEach((link) => {
        const holder = link.querySelector(".dock-icon") || link;
        let badge = holder.querySelector(".badge");
        if (messages && !badge) {
          badge = document.createElement("b");
          badge.className = "badge";
          holder.insertBefore(badge, holder.querySelector("span") && holder === link ? link.querySelector("span") : null);
        }
        if (badge) {
          if (messages) badge.textContent = messages; else badge.remove();
        }
        link.setAttribute("aria-label", messages ? `Messages, ${messages} unread` : "Messages");
      });
    } catch (error) { /* ignore */ }
  }
  setInterval(refresh, 30000);
  document.addEventListener("visibilitychange", refresh);
})();

// Category mega menu: hover/focus shows subcategories (desktop); tap opens them (phones).
document.querySelectorAll("[data-mega]").forEach((panel) => {
  const menu = panel.closest("details");
  const links = panel.querySelectorAll("[data-mega-target]");
  const narrow = () => window.matchMedia("(max-width: 759px)").matches;
  const show = (link) => {
    links.forEach((item) => item.classList.toggle("is-active", item === link));
    panel.querySelectorAll(".mega-pane").forEach((pane) => { pane.hidden = pane.id !== link.dataset.megaTarget; });
  };
  links.forEach((link) => {
    link.addEventListener("mouseenter", () => { if (!narrow()) show(link); });
    link.addEventListener("focus", () => { if (!narrow()) show(link); });
    link.addEventListener("click", (event) => {
      if (!narrow()) return;
      event.preventDefault();
      show(link);
      panel.classList.add("show-subs");
    });
  });
  panel.querySelectorAll("[data-mega-back]").forEach((button) => {
    button.addEventListener("click", () => panel.classList.remove("show-subs"));
  });
  menu?.addEventListener("toggle", () => { if (!menu.open) panel.classList.remove("show-subs"); });
});

// Close header dropdowns when clicking elsewhere or pressing Escape.
document.addEventListener("click", (event) => {
  document.querySelectorAll("details.category-menu[open], details.account-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.open = false;
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll("details.category-menu[open], details.account-menu[open]").forEach((menu) => {
    menu.open = false;
    menu.querySelector("summary")?.focus();
  });
});

// Browse sidebar: expand categories in place and find a category as you type.
document.querySelectorAll("[data-side-cats]").forEach((nav) => {
  const groups = [...nav.querySelectorAll("[data-side-group]")];
  const find = nav.querySelector("[data-side-find]");
  const empty = nav.querySelector("[data-side-empty]");
  const allRow = nav.querySelector("[data-side-all]");
  const setOpen = (group, open) => {
    const button = group.querySelector("[data-side-toggle]");
    const list = group.querySelector(".side-subs");
    if (!button || !list) return;
    button.setAttribute("aria-expanded", String(open));
    list.hidden = !open;
  };
  groups.forEach((group) => {
    const button = group.querySelector("[data-side-toggle]");
    group.dataset.initialOpen = button ? button.getAttribute("aria-expanded") : "false";
    button?.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      setOpen(group, open);
      if (!find.value) group.dataset.initialOpen = String(open);
    });
    group.querySelectorAll("[data-side-name]").forEach((node) => { node.dataset.label = node.textContent; });
  });

  const mark = (node, query) => {
    const label = node.dataset.label;
    const at = label.toLowerCase().indexOf(query);
    node.textContent = "";
    if (!query || at < 0) { node.textContent = label; return; }
    const hit = document.createElement("mark");
    hit.textContent = label.slice(at, at + query.length);
    node.append(label.slice(0, at), hit, label.slice(at + query.length));
  };

  const filter = () => {
    const query = find.value.trim().toLowerCase();
    let shown = 0;
    allRow.hidden = Boolean(query);
    groups.forEach((group) => {
      const name = group.querySelector(".side-row [data-side-name]");
      const catHit = name.dataset.label.toLowerCase().includes(query);
      let subHits = 0;
      group.querySelectorAll("[data-side-sub]").forEach((item) => {
        const sub = item.querySelector("[data-side-name]");
        const hit = !query || catHit || sub.dataset.label.toLowerCase().includes(query);
        item.hidden = !hit;
        if (query && sub.dataset.label.toLowerCase().includes(query)) subHits += 1;
        mark(sub, query);
      });
      const allSub = group.querySelector("[data-side-all-sub]");
      if (allSub) allSub.hidden = Boolean(query) && !catHit;
      mark(name, query);
      const visible = !query || catHit || subHits > 0;
      group.hidden = !visible;
      if (visible) shown += 1;
      setOpen(group, query ? subHits > 0 : group.dataset.initialOpen === "true");
    });
    empty.hidden = shown > 0;
    empty.querySelector("span").textContent = find.value.trim();
  };
  find.addEventListener("input", filter);
  find.addEventListener("keydown", (event) => { if (event.key === "Escape") { find.value = ""; filter(); } });
  nav.querySelector("[data-side-clear]").addEventListener("click", () => { find.value = ""; filter(); find.focus(); });
});

// Footer "Back to top": smooth scroll, then move focus to the page content.
document.querySelectorAll("[data-back-to-top]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
    document.getElementById("main-content")?.focus({ preventScroll: true });
  });
});
