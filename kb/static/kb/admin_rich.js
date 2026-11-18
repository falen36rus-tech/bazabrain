(() => {
  "use strict";

  const toolbar = [
    ["bold", "italic", "underline"],
    [{ size: ["small", false, "large", "huge"] }],
    [{ align: [false, "center", "right", "justify"] }],
    ["clean"],
  ];
  const formats = ["bold", "italic", "underline", "size", "align"];

  function initialize(textarea) {
    if (textarea.dataset.kbRichReady || textarea.closest(".empty-form") || !window.Quill) return;
    textarea.dataset.kbRichReady = "1";

    const wrapper = document.createElement("div");
    wrapper.className = "kb-rich-editor";
    const editor = document.createElement("div");
    wrapper.append(editor);
    textarea.before(wrapper);

    const quill = new window.Quill(editor, {
      theme: "snow",
      modules: { toolbar },
      formats,
      placeholder: "Введите текст и выделите фрагмент для форматирования",
    });
    if (textarea.dataset.kbOriginalRich === "1") {
      quill.clipboard.dangerouslyPasteHTML(textarea.value);
    } else {
      quill.setText(textarea.value);
    }
    textarea.style.display = "none";

    const marker = document.createElement("input");
    marker.type = "hidden";
    marker.name = `${textarea.name}__rich`;
    marker.value = "1";
    textarea.after(marker);

    const titles = {
      ".ql-bold": "Жирный",
      ".ql-italic": "Курсив",
      ".ql-underline": "Подчёркнутый",
      ".ql-clean": "Убрать оформление",
      ".ql-picker.ql-size": "Размер шрифта",
      ".ql-picker.ql-align": "Выравнивание",
    };
    for (const [selector, title] of Object.entries(titles)) {
      const control = wrapper.querySelector(selector);
      if (control) control.title = title;
    }

    textarea.closest("form")?.addEventListener("submit", () => {
      textarea.value = quill.getText().trim() ? quill.root.innerHTML : "";
    });
  }

  function initializeAll() {
    document.querySelectorAll("textarea[data-kb-rich-editor]").forEach(initialize);
    document.querySelectorAll('.inline-related input[type="file"][name$="-image"]').forEach(initializeImageInput);
    document.querySelectorAll('.inline-related input[type="file"][name$="-extra_images"]').forEach(initializeImageInput);
  }

  function imageFiles(files) {
    return Array.from(files || []).filter((file) => file.type.startsWith("image/"));
  }

  function setFiles(input, files) {
    if (!input || !files.length) return;
    const transfer = new DataTransfer();
    for (const file of files) transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function addImages(inline, files, destination) {
    const images = imageFiles(files);
    if (!images.length) return false;
    const primary = inline.querySelector('input[type="file"][name$="-image"]');
    const gallery = inline.querySelector('input[type="file"][name$="-extra_images"]');
    if (!primary || !gallery) return false;

    if (destination === "gallery") {
      setFiles(gallery, [...gallery.files, ...images]);
    } else if (destination === "primary") {
      setFiles(primary, images.slice(0, 1));
      if (images.length > 1) setFiles(gallery, [...gallery.files, ...images.slice(1)]);
    } else if (primary.files.length || inline.querySelector('.field-image .help')) {
      setFiles(gallery, [...gallery.files, ...images]);
    } else {
      setFiles(primary, images.slice(0, 1));
      if (images.length > 1) setFiles(gallery, [...gallery.files, ...images.slice(1)]);
    }
    return true;
  }

  function updateImagePreview(input) {
    const zone = input.closest(".kb-image-dropzone");
    if (!zone) return;
    const preview = zone.querySelector(".kb-image-preview");
    for (const url of zone._previewUrls || []) URL.revokeObjectURL(url);
    zone._previewUrls = [];
    preview.replaceChildren();
    for (const file of Array.from(input.files).slice(0, 5)) {
      const url = URL.createObjectURL(file);
      zone._previewUrls.push(url);
      const thumb = document.createElement("img");
      thumb.src = url;
      thumb.alt = file.name;
      preview.append(thumb);
    }
    const count = input.files.length;
    zone.querySelector(".kb-image-selection").textContent = count
      ? `Выбрано изображений: ${count}${count > 5 ? " (показаны первые 5)" : ""}`
      : "";
  }

  function initializeImageInput(input) {
    if (input.dataset.kbDropReady || input.closest(".empty-form")) return;
    input.dataset.kbDropReady = "1";
    input.accept = "image/*";
    const isGallery = input.name.endsWith("-extra_images");
    const zone = document.createElement("div");
    zone.className = "kb-image-dropzone";
    zone.tabIndex = 0;
    zone.setAttribute("role", "button");
    zone.setAttribute("aria-label", isGallery
      ? "Добавить фото: перетащите, вставьте из буфера или выберите файлы"
      : "Добавить скриншот: перетащите, вставьте из буфера или выберите файл");
    const instruction = document.createElement("span");
    instruction.className = "kb-image-instruction";
    instruction.textContent = isGallery
      ? "Перетащите фото сюда или вставьте Ctrl+V (можно несколько)"
      : "Перетащите скриншот сюда или вставьте Ctrl+V";
    const selection = document.createElement("span");
    selection.className = "kb-image-selection";
    selection.setAttribute("aria-live", "polite");
    const preview = document.createElement("span");
    preview.className = "kb-image-preview";
    input.before(zone);
    zone.append(instruction, input, selection, preview);
    zone.addEventListener("click", (event) => {
      if (event.target === zone || event.target === instruction) input.click();
      zone.focus();
    });
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });
    input.addEventListener("change", () => updateImagePreview(input));
    if (input.files.length) updateImagePreview(input);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeAll, { once: true });
  } else {
    initializeAll();
  }
  new MutationObserver(initializeAll).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.type !== "file" || !input.files?.length) return;
    if (!/-(image|extra_images)$/.test(input.name)) return;
    const inline = input.closest(".inline-related");
    const enteredText = inline?.querySelector(".kb-rich-editor .ql-editor")?.textContent?.trim();
    if (enteredText) return;
    const kind = inline?.querySelector('select[name$="-kind"]');
    if (kind) { kind.value = "image"; kind.dispatchEvent(new Event("change", { bubbles: true })); }
  });
  document.addEventListener("dragover", (event) => {
    if (!Array.from(event.dataTransfer?.items || []).some((item) => item.kind === "file")) return;
    const zone = event.target.closest?.(".kb-image-dropzone");
    if (!zone && !event.target.closest?.(".inline-related .ql-editor")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    zone?.classList.add("kb-image-dragover");
  });
  document.addEventListener("dragleave", (event) => {
    event.target.closest?.(".kb-image-dropzone")?.classList.remove("kb-image-dragover");
  });
  document.addEventListener("drop", (event) => {
    const zone = event.target.closest?.(".kb-image-dropzone");
    const editor = event.target.closest?.(".inline-related .ql-editor");
    if (!zone && !editor) return;
    event.preventDefault();
    zone?.classList.remove("kb-image-dragover");
    const input = zone?.querySelector('input[type="file"]');
    addImages((zone || editor).closest(".inline-related"), event.dataTransfer.files,
      input ? (input.name.endsWith("-extra_images") ? "gallery" : "primary") : "auto");
  });
  document.addEventListener("paste", (event) => {
    const inline = event.target.closest?.(".inline-related");
    if (!inline || !imageFiles(event.clipboardData?.files).length) return;
    const zoneInput = event.target.closest(".kb-image-dropzone")?.querySelector('input[type="file"]');
    const destination = zoneInput ? (zoneInput.name.endsWith("-extra_images") ? "gallery" : "primary") : "auto";
    if (addImages(inline, event.clipboardData.files, destination)) event.preventDefault();
  }, true);
})();
