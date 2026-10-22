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
    mainImage.src = image.src;
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
