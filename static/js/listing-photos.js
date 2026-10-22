document.querySelectorAll(".listing-form").forEach((form) => {
  const input = form.querySelector('input[type="file"][multiple]');
  const preview = form.querySelector("[data-photo-preview]");
  const status = form.querySelector("[data-photo-status]");
  const uploadControl = form.querySelector(".photo-upload-control");
  const limit = Number(form.dataset.photoLimit);
  let previewUrls = [];

  if (!input || !preview || !status || !uploadControl) return;

  const showFiles = (files) => {
    previewUrls.forEach((url) => URL.revokeObjectURL(url));
    previewUrls = [];
    preview.replaceChildren();
    const images = Array.from(files);

    images.forEach((file) => {
      if (!file.type.startsWith("image/")) return;
      const image = document.createElement("img");
      image.alt = `Preview: ${file.name}`;
      image.src = URL.createObjectURL(file);
      previewUrls.push(image.src);
      preview.append(image);
    });

    if (images.length === 0) {
      status.textContent = "No new photos selected";
    } else if (images.length > limit) {
      status.textContent = `You selected ${images.length} photos. Choose no more than ${limit}.`;
      status.classList.add("field-error");
    } else {
      status.classList.remove("field-error");
      status.textContent = `${images.length} photo${images.length === 1 ? "" : "s"} selected${images.length < 3 ? " — 3 or more views are recommended" : ""}.`;
    }
  };

  input.addEventListener("change", () => showFiles(input.files));
  uploadControl.addEventListener("dragover", (event) => {
    event.preventDefault();
    uploadControl.classList.add("is-dragging");
  });
  uploadControl.addEventListener("dragleave", () => {
    uploadControl.classList.remove("is-dragging");
  });
  uploadControl.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadControl.classList.remove("is-dragging");
    if (!event.dataTransfer) return;
    input.files = event.dataTransfer.files;
    showFiles(input.files);
  });
});
