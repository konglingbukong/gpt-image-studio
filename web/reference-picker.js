/* Local library picker. Only explicitly added originals enter the composer. */
(() => {
  const dialog = $("#referencePicker");
  const grid = $("#libGrid");
  const addButton = $("#libAdd");
  const pageSize = 18;
  const initial = () => ({category: "", section: "", query: "", page: 0, group: null, angle: ""});
  const filters = {outfits: initial(), poses: initial()};
  let catalogs = new Map();
  let kind = "outfits", current = null, loadingOriginal = false;

  function assetUrl(type, view, variant) {
    return BASE + "/api/references/" + type + "/" + view.id + "/" + variant;
  }

  function options(select, title, values, value) {
    const choices = [...new Set(values)].sort((a, b) => a.localeCompare(b, "zh-CN", {numeric: true}));
    select.replaceChildren(new Option(t(title), ""), ...choices.map(s => new Option(s, s)));
    select.value = choices.includes(value) ? value : "";
    return select.value;
  }

  function refStatus() {
    $("#libRefCount").textContent = t("lib.refCount", {n: st.refs.length, max: MAX_REFS});
    const added = current && st.refs.some(r => r.libraryId === current.view.id);
    const full = st.refs.length >= MAX_REFS;
    addButton.textContent = t(added ? "lib.added" : full ? "toast.maxRefs" : "lib.add");
    addButton.disabled = loadingOriginal || !current || added || full;
    grid.querySelectorAll("button").forEach(button => {
      const selected = current && button.dataset.group === current.group.views[0].id;
      button.setAttribute("aria-pressed", String(!!selected));
    });
  }

  function showDetail(group, angle) {
    $("#libDetail").hidden = !group;
    if (!group) {
      current = null;
      $("#libPreview").removeAttribute("src");
      refStatus();
      return;
    }
    const view = group.views.find(v => v.angle === angle) || group.views[0];
    current = {kind, group, view};
    filters[kind].group = group.views[0].id;
    filters[kind].angle = view.angle;
    const preview = $("#libPreview");
    const url = assetUrl(kind, view, "original");
    if (preview.getAttribute("src") !== url) preview.src = url;
    preview.alt = [group.name, view.angle].filter(Boolean).join(" · ");
    $("#libName").textContent = group.name;
    $("#libPath").textContent = group.category + " / " + group.section;
    $("#libAngles").replaceChildren(...group.views.filter(v => v.angle).map(v => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn";
      button.textContent = v.angle;
      button.setAttribute("aria-pressed", String(v === view));
      button.onclick = () => { showDetail(group, v.angle); $("#libAngles button[aria-pressed=true]")?.focus(); };
      return button;
    }));
    refStatus();
  }

  function draw() {
    const entry = catalogs.get(kind), groups = entry?.data?.groups || [];
    const f = filters[kind];
    const category = options($("#libCategory"), "lib.categories", groups.map(g => g.category), f.category);
    if (entry?.data) f.category = category;
    const inCategory = groups.filter(g => !f.category || g.category === f.category);
    const section = options($("#libSection"), "lib.sections", inCategory.map(g => g.section), f.section);
    if (entry?.data) f.section = section;
    const terms = f.query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const hits = inCategory.filter(g => {
      if (f.section && g.section !== f.section) return false;
      const haystack = [g.name, g.category, g.section].join(" ").toLowerCase();
      return terms.every(word => haystack.includes(word));
    });
    const pages = Math.ceil(hits.length / pageSize);
    if (entry?.data) f.page = Math.max(0, Math.min(f.page, pages - 1));
    const visible = hits.slice(f.page * pageSize, (f.page + 1) * pageSize);
    grid.replaceChildren(...visible.map(g => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.group = g.views[0].id;
      button.title = [g.category, g.section, g.name].join(" / ");
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      img.src = assetUrl(kind, g.views[0], "thumb");
      const label = document.createElement("span");
      label.textContent = g.name;
      button.append(img, label);
      button.onclick = () => showDetail(g, "");
      return button;
    }));
    grid.scrollTop = 0;
    $("#libPrev").disabled = !pages || f.page === 0;
    $("#libNext").disabled = f.page + 1 >= pages;
    $("#libCount").textContent = pages ? t("lib.count", {n: hits.length, page: f.page + 1, pages}) : "";
    $("#libState").textContent = !entry?.data ? t(entry?.error ? "lib.error" : "lib.loading")
      : !entry.data.available ? t("lib.unavailable") : !hits.length ? t("lib.empty") : "";
    const selected = visible.find(g => g.views[0].id === f.group);
    showDetail(selected || visible[0], selected ? f.angle : "");
  }

  async function selectTab(type) {
    kind = type;
    const f = filters[kind], cache = catalogs;
    $("#libSearch").value = f.query;
    $("#libMessage").textContent = "";
    dialog.querySelectorAll("[data-kind]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.kind === type)));
    if (!cache.has(type)) {
      const entry = {};
      cache.set(type, entry);
      draw();
      try {
        const response = await fetch(BASE + "/api/references/" + type);
        if (!response.ok) throw new Error();
        entry.data = await response.json();
        if (!Array.isArray(entry.data.groups)) throw new Error();
      } catch {
        entry.data = null;
        entry.error = true;
      }
    }
    if (dialog.open && catalogs === cache && kind === type) draw();
  }

  addButton.onclick = async () => {
    if (!current || addButton.disabled) return;
    const {kind: type, group, view} = current;
    loadingOriginal = true;
    refStatus();
    try {
      const response = await fetch(assetUrl(type, view, "original"));
      if (!response.ok) throw new Error();
      const blob = await response.blob();
      if (!["image/webp", "image/png"].includes(blob.type)) throw new Error();
      const ref = await readFile(new File([blob], view.file, {type: blob.type}));
      ref.libraryId = view.id;
      ref.libraryLabel = [t("lib." + type), group.name, view.angle].filter(Boolean).join(" · ");
      const added = appendRef(ref);
      $("#libMessage").textContent = added ? t("lib.attached", {n: st.refs.length, name: ref.libraryLabel}) : t("toast.maxRefs");
    } catch {
      $("#libMessage").textContent = t("lib.error");
    } finally {
      loadingOriginal = false;
      refStatus();
    }
  };

  $("#openReferencePicker").onclick = () => {
    if (MODE !== "local") return;
    closePops();
    catalogs = new Map();
    dialog.showModal();
    selectTab(kind);
    dialog.dispatchEvent(new Event("library-opened"));
  };
  dialog.addEventListener("library-installed", () => {
    catalogs = new Map();
    if (dialog.open) selectTab(kind);
  });
  $("#libDone").onclick = () => dialog.close();
  dialog.onclick = e => {
    if (e.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close();
  };
  dialog.querySelectorAll("[data-kind]").forEach(b => b.onclick = () => selectTab(b.dataset.kind));
  $("#libSearchForm").onsubmit = e => e.preventDefault();
  $("#libSearch").oninput = e => { filters[kind].query = e.target.value; filters[kind].page = 0; draw(); };
  $("#libCategory").onchange = e => { Object.assign(filters[kind], {category: e.target.value, section: "", page: 0}); draw(); };
  $("#libSection").onchange = e => { Object.assign(filters[kind], {section: e.target.value, page: 0}); draw(); };
  $("#libPrev").onclick = () => { filters[kind].page--; draw(); };
  $("#libNext").onclick = () => { filters[kind].page++; draw(); };
})();
