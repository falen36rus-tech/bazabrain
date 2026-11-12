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
})();
