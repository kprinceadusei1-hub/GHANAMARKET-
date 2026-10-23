document.querySelectorAll("[data-product-gallery]").forEach((gallery) => {
  const mainImage = gallery.querySelector("[data-gallery-main]");
  const thumbnails = Array.from(gallery.querySelectorAll("[data-gallery-thumbnail]"));
  const count = gallery.querySelector("[data-gallery-count]");
  const previous = gallery.querySelector("[data-gallery-previous]");
  const next = gallery.querySelector("[data-gallery-next]");

  if (!mainImage || thumbnails.length < 2) return;

  let activeIndex = 0;

  const showPhoto = (index) => {
    activeIndex = (index + thumbnails.length) % thumbnails.length;
    const thumbnail = thumbnails[activeIndex];
    const image = thumbnail.querySelector("img");
    mainImage.src = image.dataset.full || image.src;
    mainImage.alt = thumbnail.getAttribute("aria-label");
    count.textContent = `${activeIndex + 1} / ${thumbnails.length}`;
    thumbnails.forEach((item, itemIndex) => {
      const active = itemIndex === activeIndex;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-current", String(active));
    });
  };

  thumbnails.forEach((thumbnail, index) => {
    thumbnail.addEventListener("click", () => showPhoto(index));
  });
  previous.addEventListener("click", () => showPhoto(activeIndex - 1));
  next.addEventListener("click", () => showPhoto(activeIndex + 1));
  gallery.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") showPhoto(activeIndex - 1);
    if (event.key === "ArrowRight") showPhoto(activeIndex + 1);
  });
});

// Blurred backdrop follows the current photo; tap the photo for a full-screen viewer.
document.querySelectorAll("[data-product-gallery]").forEach((gallery) => {
  const frame = gallery.querySelector(".detail-image");
  const mainImage = gallery.querySelector("[data-gallery-main]");
  const dialog = gallery.querySelector("[data-lightbox]");
  if (!frame || !mainImage) return;
  const photos = Array.from(gallery.querySelectorAll("[data-gallery-thumbnail] img")).map((img) => img.dataset.full || img.src);
  if (!photos.length) photos.push(mainImage.src);
  new MutationObserver(() => frame.style.setProperty("--gallery-bg", `url("${mainImage.src}")`))
    .observe(mainImage, { attributes: true, attributeFilter: ["src"] });

  if (!dialog || typeof dialog.showModal !== "function") return;
  const image = dialog.querySelector("[data-lightbox-image]");
  const count = dialog.querySelector("[data-lightbox-count]");
  let index = 0;
  const show = (i) => {
    index = (i + photos.length) % photos.length;
    image.src = photos[index];
    count.textContent = `${index + 1} / ${photos.length}`;
  };
  gallery.querySelector("[data-gallery-open]")?.addEventListener("click", () => {
    show(Math.max(0, photos.indexOf(mainImage.src)));
    dialog.showModal();
  });
  dialog.querySelector("[data-lightbox-close]").addEventListener("click", () => dialog.close());
  dialog.querySelector("[data-lightbox-previous]")?.addEventListener("click", () => show(index - 1));
  dialog.querySelector("[data-lightbox-next]")?.addEventListener("click", () => show(index + 1));
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") show(index - 1);
    if (event.key === "ArrowRight") show(index + 1);
  });
  let startX = null;
  dialog.addEventListener("touchstart", (event) => { startX = event.touches[0].clientX; }, { passive: true });
  dialog.addEventListener("touchend", (event) => {
    if (startX === null) return;
    const delta = event.changedTouches[0].clientX - startX;
    if (Math.abs(delta) > 40) show(index + (delta < 0 ? 1 : -1));
    startX = null;
  });
});

// Long descriptions start collapsed with a "Show more" button.
document.querySelectorAll("[data-clamp]").forEach((box) => {
  const toggle = box.parentElement.querySelector("[data-clamp-toggle]");
  if (!toggle || box.scrollHeight <= 260) return;
  box.classList.add("is-clamped");
  toggle.hidden = false;
  toggle.addEventListener("click", () => {
    const open = box.classList.toggle("is-clamped");
    toggle.textContent = open ? "Show more" : "Show less";
  });
});

// Quantity stepper (− 1 +) for Buy now / Add to cart.
document.querySelectorAll("[data-stepper]").forEach((stepper) => {
  const input = stepper.querySelector("input");
  const min = Number(input.min) || 1;
  const max = Number(input.max) || 1;
  const buttons = stepper.querySelectorAll("[data-step]");
  const sync = () => {
    const value = Math.min(max, Math.max(min, Math.round(Number(input.value) || min)));
    input.value = value;
    buttons[0].disabled = value <= min;
    buttons[1].disabled = value >= max;
  };
  buttons.forEach((button) => button.addEventListener("click", () => {
    input.value = Number(input.value) + Number(button.dataset.step);
    sync();
  }));
  input.addEventListener("change", sync);
  sync();
});
