(() => {
  "use strict";

  const sidebar = document.querySelector("#site-sidebar");
  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  const sidebarClose = document.querySelector("[data-sidebar-close]");
  const sidebarBackdrop = document.querySelector("[data-sidebar-backdrop]");

  function setSidebarOpen(open) {
    if (!sidebar || !sidebarToggle || !sidebarBackdrop) return;
    sidebar.classList.toggle("is-open", open);
    sidebarToggle.setAttribute("aria-expanded", String(open));
    sidebarToggle.setAttribute("aria-label", open ? "Закрыть разделы" : "Открыть разделы");
    sidebarBackdrop.hidden = !open;
    document.body.classList.toggle("sidebar-open", open);
    if (open) sidebarClose?.focus();
    else sidebarToggle.focus();
  }

  sidebarToggle?.addEventListener("click", () => setSidebarOpen(!sidebar.classList.contains("is-open")));
  sidebarClose?.addEventListener("click", () => setSidebarOpen(false));
  sidebarBackdrop?.addEventListener("click", () => setSidebarOpen(false));
  sidebar?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      if (window.matchMedia("(max-width: 920px)").matches) setSidebarOpen(false);
    });
  });

  const tree = document.querySelector(".sidebar-nav");
  function setTreeExpanded(item, expanded, persist = false) {
    const button = item.querySelector(":scope > .nav-tree-row > [data-tree-toggle]");
    const children = item.querySelector(":scope > [data-tree-children]");
    if (!button || !children) return;
    button.setAttribute("aria-expanded", String(expanded));
    button.setAttribute("aria-label", `${expanded ? "Свернуть" : "Развернуть"} ${item.querySelector(":scope > .nav-tree-row > .nav-tree-link")?.textContent?.trim() || "раздел"}`);
    children.hidden = !expanded;
    if (persist) {
      try { window.localStorage.setItem(`kb-tree-${item.dataset.treeId}`, String(expanded)); } catch (_) { /* Storage may be unavailable. */ }
    }
  }

  if (tree) {
    const isHome = Boolean(document.querySelector(".sidebar-home[aria-current='page']"));
    const defaultOpen = new Set();
    if (isHome) {
      const firstRoot = tree.querySelector(".nav-tree[data-depth='0'] > .nav-tree-item");
      if (firstRoot) {
        defaultOpen.add(firstRoot);
        const firstChild = firstRoot.querySelector(":scope > .nav-tree-children > .nav-tree > .nav-tree-item");
        if (firstChild) defaultOpen.add(firstChild);
      }
    }
    tree.querySelectorAll("[data-tree-item]").forEach((item) => {
      let expanded = defaultOpen.has(item);
      if (!isHome) {
        try {
          const stored = window.localStorage.getItem(`kb-tree-${item.dataset.treeId}`);
          if (stored !== null) expanded = stored === "true";
        } catch (_) { /* Storage may be unavailable. */ }
      }
      setTreeExpanded(item, expanded);
    });
    tree.querySelectorAll("[aria-current='page']").forEach((active) => {
      let item = active.closest("[data-tree-item]");
      while (item) {
        setTreeExpanded(item, true);
        item = item.parentElement?.closest("[data-tree-item]");
      }
    });
    tree.querySelectorAll("[data-tree-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const item = button.closest("[data-tree-item]");
        if (item) setTreeExpanded(item, button.getAttribute("aria-expanded") !== "true", true);
      });
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar?.classList.contains("is-open")) setSidebarOpen(false);
  });

  const searchRoot = document.querySelector("[data-search-root]");
  const searchInput = searchRoot?.querySelector("[data-search-input]");
  const searchPopover = searchRoot?.querySelector("[data-search-suggestions]");
  let suggestTimer = null;
  let suggestAbort = null;
  let selectedIndex = -1;
  let suggestionButtons = [];

  function hideSuggestions() {
    if (!searchPopover || !searchInput) return;
    searchPopover.hidden = true;
    searchInput.setAttribute("aria-expanded", "false");
    searchInput.removeAttribute("aria-activedescendant");
    selectedIndex = -1;
  }

  function selectSuggestion(index) {
    if (!searchInput) return;
    selectedIndex = index;
    suggestionButtons.forEach((button, i) => {
      button.classList.toggle("is-selected", i === index);
      button.setAttribute("aria-selected", String(i === index));
    });
    if (index >= 0 && suggestionButtons[index]) {
      searchInput.setAttribute("aria-activedescendant", suggestionButtons[index].id);
      suggestionButtons[index].scrollIntoView({ block: "nearest" });
    } else {
      searchInput.removeAttribute("aria-activedescendant");
    }
  }

  function renderSuggestions(items, query) {
    if (!searchPopover || !searchInput) return;
    searchPopover.replaceChildren();
    suggestionButtons = [];
    selectedIndex = -1;
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "suggestion-empty";
      empty.textContent = "Совпадений не найдено";
      searchPopover.append(empty);
    } else {
      items.slice(0, 6).forEach((item, index) => {
        if (!item || typeof item.title !== "string" || typeof item.url !== "string" || !/^\/(?!\/)/.test(item.url)) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "suggestion-item";
        button.id = `search-suggestion-${index}`;
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        const title = document.createElement("strong");
        title.textContent = item.title;
        button.append(title);
        if (item.section) {
          const section = document.createElement("small");
          section.textContent = String(item.section);
          button.append(section);
        }
        button.addEventListener("click", () => window.location.assign(item.url));
        searchPopover.append(button);
        suggestionButtons.push(button);
      });
    }
    const more = document.createElement("a");
    more.className = "suggestion-more";
    const url = new URL(searchRoot.querySelector("form").action);
    url.searchParams.set("q", query);
    more.href = `${url.pathname}${url.search}`;
    more.textContent = "Показать все результаты";
    searchPopover.append(more);
    searchPopover.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
  }

  async function loadSuggestions(query) {
    if (!searchRoot || !query || query.length < 2) { hideSuggestions(); return; }
    suggestAbort?.abort();
    suggestAbort = new AbortController();
    const url = new URL(searchRoot.dataset.suggestUrl, window.location.origin);
    url.searchParams.set("q", query);
    try {
      const response = await fetch(url, { credentials: "same-origin", signal: suggestAbort.signal, headers: { Accept: "application/json" } });
      if (!response.ok) { hideSuggestions(); return; }
      const data = await response.json();
      if (searchInput?.value.trim() !== query) return;
      renderSuggestions(Array.isArray(data) ? data : (Array.isArray(data.results) ? data.results : []), query);
    } catch (error) {
      if (error.name !== "AbortError") hideSuggestions();
    }
  }

  searchInput?.addEventListener("input", () => {
    window.clearTimeout(suggestTimer);
    const query = searchInput.value.trim();
    if (query.length < 2) { suggestAbort?.abort(); hideSuggestions(); return; }
    suggestTimer = window.setTimeout(() => loadSuggestions(query), 220);
  });
  searchInput?.addEventListener("focus", () => {
    const query = searchInput.value.trim();
    if (query.length >= 2) loadSuggestions(query);
  });
  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { hideSuggestions(); return; }
    if (!searchPopover || searchPopover.hidden || !suggestionButtons.length) return;
    if (event.key === "ArrowDown") { event.preventDefault(); selectSuggestion((selectedIndex + 1) % suggestionButtons.length); }
    if (event.key === "ArrowUp") { event.preventDefault(); selectSuggestion((selectedIndex - 1 + suggestionButtons.length) % suggestionButtons.length); }
    if (event.key === "Enter" && selectedIndex >= 0) { event.preventDefault(); suggestionButtons[selectedIndex].click(); }
  });
  document.addEventListener("click", (event) => {
    if (searchRoot && !searchRoot.contains(event.target)) hideSuggestions();
    const accountMenu = document.querySelector(".account-menu[open]");
    if (accountMenu && !accountMenu.contains(event.target)) accountMenu.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (!searchInput || event.altKey || event.shiftKey) return;
    const target = event.target;
    const editing = target instanceof Element && Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
    if ((!editing && event.key === "/") || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k")) {
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
    }
  });

  const lightbox = document.querySelector("[data-lightbox]");
  if (lightbox) {
    const image = lightbox.querySelector("[data-lightbox-image]");
    const caption = lightbox.querySelector("[data-lightbox-caption]");
    document.querySelectorAll("[data-lightbox-open]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!image || !caption) return;
        image.src = button.dataset.lightboxSrc || "";
        image.alt = button.dataset.lightboxCaption || "Изображение статьи";
        caption.textContent = button.dataset.lightboxCaption || "";
        lightbox.showModal();
      });
    });
    lightbox.addEventListener("click", (event) => { if (event.target === lightbox) lightbox.close(); });
    lightbox.addEventListener("close", () => { if (image) image.removeAttribute("src"); });
  }

  const tocWrap = document.querySelector("[data-toc-wrap]");
  const toc = tocWrap?.querySelector("[data-toc]");
  const headings = [...document.querySelectorAll("[data-toc-source]")];
  if (tocWrap && toc && headings.length) {
    headings.forEach((heading, index) => {
      heading.id = `article-heading-${index + 1}`;
      const link = document.createElement("a");
      link.href = `#${heading.id}`;
      link.textContent = heading.textContent.trim();
      toc.append(link);
    });
    tocWrap.hidden = false;
    if ("IntersectionObserver" in window) {
      const links = [...toc.querySelectorAll("a")];
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            links.forEach((link) => link.classList.toggle("is-current", link.hash === `#${entry.target.id}`));
          }
        });
      }, { rootMargin: "-105px 0px -65% 0px" });
      headings.forEach((heading) => observer.observe(heading));
    }
  }
})();
