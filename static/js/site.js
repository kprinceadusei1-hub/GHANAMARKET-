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
  if (!toast.classList.contains("error")) setTimeout(dismiss, 5000 + index * 600);
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
