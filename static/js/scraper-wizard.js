/* New Scraper Job wizard — persists each step as a draft. */
(function () {
  const configEl = document.getElementById("wizard-config");
  const choicesEl = document.getElementById("wizard-choices");
  const metaEl = document.getElementById("wizard-meta");
  if (!configEl || !choicesEl || !metaEl) return;

  const state = JSON.parse(configEl.textContent);
  const choices = JSON.parse(choicesEl.textContent);
  const meta = JSON.parse(metaEl.textContent);
  const steps = choices.steps || [];
  let index = Math.max(0, steps.findIndex((s) => s.key === (state.wizard_step || "basic")));

  const root = document.getElementById("wizardRoot");
  const errors = document.getElementById("wizardErrors");
  const back = document.getElementById("wizardBack");
  const next = document.getElementById("wizardNext");
  const save = document.getElementById("wizardSave");

  function csrf() {
    return meta.csrf;
  }

  function optionList(pairs, selected) {
    return (pairs || [])
      .map(([value, label]) => `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(label)}</option>`)
      .join("");
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function originBadge(item) {
    const via = (item && item.last_updated_via) || (item && item.created_via) || "manual";
    const label = via === "csv" ? "CSV import" : "Manual";
    return `<span class="text-[10.5px] uppercase tracking-wide text-ink-faint border border-slate-200 rounded-md px-1.5 py-0.5">${label}</span>`;
  }

  function field(label, name, value, extra) {
    return `<label class="block"><span class="text-[13.5px] font-medium block mb-1.5">${esc(label)}</span>
      <input name="${esc(name)}" value="${esc(value || "")}" ${extra || ""} class="input"></label>`;
  }

  function showErrors(list) {
    if (!list || !list.length) {
      errors.classList.add("hidden");
      errors.textContent = "";
      return;
    }
    errors.classList.remove("hidden");
    errors.innerHTML = list.map((item) => `<p>${esc(item)}</p>`).join("");
  }

  function highlightNav() {
    document.querySelectorAll(".wizard-step").forEach((btn, i) => {
      btn.classList.toggle("bg-primary-50", i === index);
      btn.classList.toggle("text-primary-700", i === index);
      btn.classList.toggle("font-medium", i === index);
    });
    back.disabled = index === 0;
    next.textContent = index === steps.length - 1 ? "Save and finish" : "Continue";
  }

  function render() {
    const key = steps[index].key;
    const map = {
      basic: renderBasic,
      source: renderSource,
      variables: renderVariables,
      results: renderResults,
      detail: renderFields.bind(null, "detail_page"),
      pagination: renderPagination,
      execution: renderExecution,
      preview: renderPreview,
      review: renderReview,
    };
    root.innerHTML = `<div class="p-5 sm:p-6 space-y-5">${(map[key] || renderBasic)()}</div>`;
    highlightNav();
    if (window.lucide) window.lucide.createIcons();
    bindStep();
  }

  function renderBasic() {
    return `
      <h2 class="text-[15px] font-semibold">Basic information</h2>
      ${field("Job name", "name", state.name, "required")}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Description</span>
        <textarea name="description" class="input min-h-[88px] h-auto py-2">${esc(state.description || "")}</textarea></label>
      ${field("Tags", "tags", (state.tags || []).join(", "), 'placeholder="scholarships, australia"')}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Status</span>
        <select name="status" class="select">${optionList(choices.job_statuses, state.status)}</select></label>
      <p class="text-[12.5px] text-ink-mute">A job can stay a draft until the URL, fields and pagination are complete. Names only need to be unique for your account.</p>`;
  }

  function renderSource() {
    const req = state.request_settings || {};
    return `
      <h2 class="text-[15px] font-semibold">Source and request</h2>
      ${field("Starting URL", "start_url", state.start_url, 'placeholder="https://search.studyaustralia.gov.au/scholarships?page=1"')}
      ${field("URL template", "url_template", state.url_template, 'placeholder="https://…/scholarships?page={{page}}"')}
      <div class="grid sm:grid-cols-2 gap-4">
        <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">HTTP method</span>
          <select name="http_method" class="select">${optionList(choices.http_methods, state.http_method)}</select></label>
        <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Rendering mode</span>
          <select name="rendering_mode" class="select">${optionList(choices.render_modes, state.rendering_mode)}</select></label>
        ${field("Timeout (seconds)", "timeout", req.timeout || 20, "type=number min=1 max=120")}
        ${field("Wait after load (ms)", "wait_after_load_ms", req.wait_after_load_ms || 0, "type=number min=0")}
        ${field("Wait-for selector", "wait_for_selector", req.wait_for_selector || "")}
        ${field("User-agent", "user_agent", req.user_agent || "")}
      </div>
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="follow_redirects" ${req.follow_redirects !== false ? "checked" : ""}> Follow redirects</label>
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="verify_tls" ${req.verify_tls !== false ? "checked" : ""}> Verify TLS</label>
      <button type="button" id="testPage" class="h-10 px-4 rounded-xl bg-accent-50 text-accent-600 text-[13.5px] font-medium border border-accent-500/25">Test page</button>
      <div id="testPageResult" class="text-[13px] text-ink-soft"></div>`;
  }

  function renderVariables() {
    const rows = (state.variables || [])
      .map((item, i) => variableRow(item, i))
      .join("");
    return `
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-[15px] font-semibold">Variable parameters</h2>
        <div class="flex gap-2">
          <button type="button" id="addVariable" class="btn-secondary btn-sm"><i data-lucide="plus"></i>Add variable</button>
          <button type="button" class="btn-secondary btn-sm csv-open">Import CSV</button>
        </div>
      </div>
      <p class="text-[13px] text-ink-soft">Variables can come from the URL or from HTML and are reused in later URLs, pagination, detail pages and output fields. Use <code class="font-mono text-[12px]">{{variable_name}}</code> in templates.</p>
      <div class="overflow-x-auto"><table class="w-full text-[12.5px]">
        <thead><tr class="text-left text-[11.5px] uppercase tracking-wider text-ink-mute">
          <th class="py-2">Name</th><th>Source</th><th>Selector / parameter</th><th>Type</th><th>Source</th><th></th>
        </tr></thead>
        <tbody id="varBody">${rows}</tbody>
      </table></div>
      <div id="varEditor"></div>`;
  }

  function variableRow(item, i) {
    return `<tr class="border-t border-slate-100">
      <td class="py-2 font-mono">${esc(item.name)}</td>
      <td>${esc(item.source_type)}</td>
      <td class="truncate max-w-[180px]">${esc(item.selector || (item.configuration || {}).parameter || "")}</td>
      <td>${esc(item.data_type)}</td>
      <td>${originBadge(item)}</td>
      <td class="text-right space-x-1">
        <button type="button" data-edit-var="${i}" class="text-primary-600">Edit</button>
        <button type="button" data-dup-var="${i}" class="text-ink-soft">Duplicate</button>
        <button type="button" data-del-var="${i}" class="text-err-700">Delete</button>
      </td></tr>`;
  }

  function renderResults() {
    return `
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-[15px] font-semibold">Result selection</h2>
        <div class="flex gap-2">
          <button type="button" class="btn-secondary btn-sm" id="focusResult">Configure manually</button>
          <button type="button" class="btn-secondary btn-sm csv-open">Import CSV</button>
        </div>
      </div>
      ${field("Result item CSS selector", "result_selector", state.result_selector, 'placeholder=".scholarship-list-card"')}
      ${field("Result list container (optional)", "result_list_selector", state.result_list_selector)}
      ${field("Detail-link selector", "detail_link_selector", state.detail_link_selector, 'placeholder="h3 a"')}
      ${field("Detail-link attribute", "detail_link_attribute", state.detail_link_attribute || "href")}
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="follow_detail_pages" ${state.follow_detail_pages ? "checked" : ""}> Follow detail pages</label>
      ${field("Unique-record field", "unique_field_name", state.unique_field_name, 'placeholder="detail_url"')}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Duplicate handling</span>
        <select name="duplicate_handling" class="select">${optionList(choices.duplicate_handling, state.duplicate_handling)}</select></label>
      ${field("Maximum records", "maximum_records", state.maximum_records || "", "type=number min=1")}
      <button type="button" id="testResult" class="h-10 px-4 rounded-xl border border-slate-300 text-[13.5px] font-medium">Test result selector</button>
      <div id="resultPreview" class="text-[13px] text-ink-soft"></div>
      <div class="flex flex-wrap items-center justify-between gap-2 pt-2">
        <h3 class="text-[14.5px] font-semibold">Result fields</h3>
        <button type="button" data-add-field="result_item" class="btn-secondary btn-sm">Add result field</button>
      </div>
      <p class="text-[13px] text-ink-soft">Listing-page and system fields. Detail-page fields are on the next step.</p>
      ${fieldsTable("result_item")}`;
  }

  function renderFields(scope) {
    return `
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-[15px] font-semibold">${scope === "detail_page" ? "Detail page fields" : "Output fields"}</h2>
        <div class="flex gap-2">
          <button type="button" data-add-field="${scope}" class="btn-secondary btn-sm">${scope === "detail_page" ? "Add detail field" : "Add field"}</button>
          ${scope === "detail_page" ? '<button type="button" class="btn-secondary btn-sm csv-open">Import CSV</button>' : ""}
        </div>
      </div>
      <p class="text-[13px] text-ink-soft">Internal names must match <code class="font-mono">^[a-z][a-z0-9_]*$</code>. Display labels generate names automatically.</p>
      ${fieldsTable(scope)}`;
  }

  function fieldsTable(scope) {
    const items = (state.fields || []).filter((item) =>
      scope === "detail_page" ? item.scope === "detail_page" : item.scope !== "detail_page"
    );
    const rows = items
      .map((item, i) => `<tr class="border-t border-slate-100">
        <td class="py-2 font-mono">${esc(item.name)}</td><td>${esc(item.label)}</td>
        <td>${esc(item.scope)}</td><td class="truncate max-w-[160px]">${esc(item.selector)}</td>
        <td>${originBadge(item)}</td>
        <td class="text-right"><button type="button" data-edit-field="${esc(item.name)}" class="text-primary-600">Edit</button>
        <button type="button" data-del-field="${esc(item.name)}" class="text-err-700">Delete</button></td></tr>`)
      .join("");
    return `<div class="overflow-x-auto"><table class="w-full text-[12.5px]">
      <thead><tr class="text-left text-[11.5px] uppercase tracking-wider text-ink-mute">
        <th class="py-2">Name</th><th>Label</th><th>Scope</th><th>Selector</th><th>Entry</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="py-4 text-ink-mute">No fields yet.</td></tr>'}</tbody></table></div>
      <button type="button" data-add-field="${scope}" class="btn-secondary btn-sm mt-3">Add field</button>
      <div id="fieldEditor"></div>`;
  }

  function renderPagination() {
    const p = state.pagination_settings || {};
    return `
      <h2 class="text-[15px] font-semibold">Pagination</h2>
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Mode</span>
        <select name="mode" class="select">${optionList(choices.pagination_modes, p.mode)}</select></label>
      ${field("Pagination variable", "variable", p.variable || "page")}
      ${field("Query parameter", "parameter", p.parameter || "page")}
      ${field("URL template", "url_template", state.url_template || p.url_template || "")}
      <div class="grid sm:grid-cols-3 gap-4">
        ${field("Start", "start", p.start || 1, "type=number")}
        ${field("Increment", "increment", p.increment || 1, "type=number")}
        ${field("Maximum pages", "maximum_pages", state.maximum_pages || p.maximum_pages || 100, "type=number")}
      </div>
      ${field("Next-button selector", "next_button_selector", p.next_button_selector || 'a[aria-label="Next page"]')}
      ${field("Wait after pagination (ms)", "wait_after_pagination_ms", p.wait_after_pagination_ms || 0, "type=number")}
      <p class="text-[12.5px] text-ink-mute">Stop rules combine: no results, no new detail URLs, repeated page fingerprint, maximum pages, consecutive failures, and cancellation.</p>`;
  }

  function renderExecution() {
    const e = state.execution_settings || {};
    return `
      <h2 class="text-[15px] font-semibold">Execution settings</h2>
      ${field("Delay between requests (seconds)", "delay_seconds", e.delay_seconds || 0.5, "type=number step=0.1")}
      ${field("Retries", "retries", e.retries || 2, "type=number")}
      ${field("Maximum run time (seconds)", "max_run_seconds", e.max_run_seconds || 900, "type=number")}
      ${field("Maximum records", "maximum_records", state.maximum_records || "", "type=number")}
      <p class="text-[12.5px] text-ink-mute">The scraper respects these caps and never bypasses CAPTCHAs or access controls.</p>`;
  }

  function renderPreview() {
    return `
      <h2 class="text-[15px] font-semibold">Test and preview</h2>
      <p class="text-[13px] text-ink-soft">Test the starting URL, then test a selector against the fetched HTML. Scripts are stripped from the preview.</p>
      <div class="flex flex-wrap gap-2">
        <button type="button" id="testPage" class="btn-primary">Test page</button>
        <button type="button" id="testResult" class="btn-secondary">Test result selector</button>
      </div>
      <div id="testPageResult" class="text-[13px]"></div>
      <div id="resultPreview" class="text-[13px]"></div>`;
  }

  function renderReview() {
    return `
      <h2 class="text-[15px] font-semibold">Review and save</h2>
      <dl class="grid sm:grid-cols-2 gap-3 text-[13px]">
        <div><dt class="text-ink-faint">Name</dt><dd class="font-medium">${esc(state.name)}</dd></div>
        <div><dt class="text-ink-faint">Status</dt><dd>${esc(state.status)}</dd></div>
        <div class="sm:col-span-2"><dt class="text-ink-faint">Start URL</dt><dd class="break-all">${esc(state.start_url)}</dd></div>
        <div class="sm:col-span-2"><dt class="text-ink-faint">URL template</dt><dd class="break-all font-mono text-[12px]">${esc(state.url_template)}</dd></div>
        <div><dt class="text-ink-faint">Variables</dt><dd>${(state.variables || []).length}</dd></div>
        <div><dt class="text-ink-faint">Fields</dt><dd>${(state.fields || []).length}</dd></div>
      </dl>
      <p class="text-[13px] text-ink-soft">Saving as Active validates the complete configuration. You can still keep it as a draft.</p>`;
  }

  function collect() {
    const data = {};
    root.querySelectorAll("input, select, textarea").forEach((el) => {
      if (!el.name) return;
      if (el.type === "checkbox") data[el.name] = el.checked;
      else data[el.name] = el.value;
    });
    if (data.tags && typeof data.tags === "string") {
      data.tags = data.tags.split(",").map((t) => t.trim()).filter(Boolean);
    }
    ["timeout", "wait_after_load_ms", "start", "increment", "maximum_pages", "maximum_records", "retries"].forEach((key) => {
      if (data[key] !== undefined && data[key] !== "") data[key] = Number(data[key]);
    });
    if (data.delay_seconds) data.delay_seconds = Number(data.delay_seconds);
    return data;
  }

  async function persist() {
    const step = steps[index].key;
    const payload = collect();
    payload.variables = state.variables || [];
    payload.fields = state.fields || [];
    const response = await fetch(`/scraper/api/jobs/${meta.jobId}/wizard/${step}/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!body.ok) {
      showErrors(body.errors || [body.error || "Could not save."]);
      return false;
    }
    Object.assign(state, body.job);
    showErrors([]);
    return true;
  }

  async function api(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(payload || {}),
    });
    return response.json();
  }

  function bindStep() {
    const addVar = document.getElementById("addVariable");
    if (addVar) addVar.addEventListener("click", () => openVariable());
    root.querySelectorAll("[data-edit-var]").forEach((btn) =>
      btn.addEventListener("click", () => openVariable(Number(btn.dataset.editVar)))
    );
    root.querySelectorAll("[data-dup-var]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const item = { ...(state.variables || [])[Number(btn.dataset.dupVar)] };
        item.name = `${item.name}_copy`;
        item.id = undefined;
        state.variables.push(item);
        render();
      })
    );
    root.querySelectorAll("[data-del-var]").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.variables.splice(Number(btn.dataset.delVar), 1);
        render();
      })
    );
    root.querySelectorAll("[data-add-field]").forEach((btn) =>
      btn.addEventListener("click", () => openField({ scope: btn.dataset.addField }))
    );
    root.querySelectorAll("[data-edit-field]").forEach((btn) =>
      btn.addEventListener("click", () => openField(state.fields.find((f) => f.name === btn.dataset.editField)))
    );
    root.querySelectorAll("[data-del-field]").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.fields = state.fields.filter((f) => f.name !== btn.dataset.delField);
        render();
      })
    );
    const testPage = document.getElementById("testPage");
    if (testPage) testPage.addEventListener("click", runTestPage);
    const testResult = document.getElementById("testResult");
    if (testResult) testResult.addEventListener("click", runTestResult);
    root.querySelectorAll(".csv-open").forEach((btn) => btn.addEventListener("click", openCsvModal));
  }

  function openVariable(idx) {
    const existing = idx >= 0 ? state.variables[idx] : { source_type: "counter", data_type: "integer", configuration: { start_value: 1, increment: 1 }, transformations: ["trim"] };
    const editor = document.getElementById("varEditor");
    if (!editor) return;
    editor.innerHTML = `<div class="mt-4 rounded-xl border border-slate-200 p-4 space-y-3">
      ${field("Variable name", "var_name", existing.name || "")}
      ${field("Display label", "var_label", existing.label || "")}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Source</span>
        <select name="var_source" class="select">${optionList(choices.source_types, existing.source_type)}</select></label>
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Scope</span>
        <select name="var_scope" class="select">${optionList(choices.scopes, existing.scope)}</select></label>
      ${field("Selector or parameter", "var_selector", existing.selector || (existing.configuration || {}).parameter || "")}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Value from</span>
        <select name="var_value_from" class="select">${optionList(choices.value_from, existing.value_from)}</select></label>
      ${field("Attribute name", "var_attr", existing.attribute_name || "")}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Data type</span>
        <select name="var_type" class="select">${optionList(choices.data_types, existing.data_type)}</select></label>
      ${field("Start value", "var_start", (existing.configuration || {}).start_value || (existing.configuration || {}).start || 1, "type=number")}
      ${field("Increment", "var_inc", (existing.configuration || {}).increment || 1, "type=number")}
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="var_required" ${existing.required ? "checked" : ""}> Required</label>
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="var_multiple" ${existing.multiple ? "checked" : ""}> Multiple values</label>
      <div class="flex gap-2">
        <button type="button" id="saveVar" class="btn-primary btn-sm">Save variable</button>
        <button type="button" id="testVar" class="btn-secondary btn-sm">${(existing.source_type || "") === "counter" ? "Test variable" : "Test selector"}</button>
      </div>
      <div id="varTest" class="text-[12.5px] text-ink-soft"></div>
    </div>`;
    document.getElementById("saveVar").addEventListener("click", () => {
      const item = {
        name: root.querySelector("[name=var_name]").value,
        label: root.querySelector("[name=var_label]").value,
        source_type: root.querySelector("[name=var_source]").value,
        scope: root.querySelector("[name=var_scope]").value,
        selector: root.querySelector("[name=var_selector]").value,
        value_from: root.querySelector("[name=var_value_from]").value,
        attribute_name: root.querySelector("[name=var_attr]").value,
        data_type: root.querySelector("[name=var_type]").value,
        configuration: {
          start_value: Number(root.querySelector("[name=var_start]").value || 1),
          increment: Number(root.querySelector("[name=var_inc]").value || 1),
          parameter: root.querySelector("[name=var_selector]").value,
        },
        transformations: existing.transformations || ["trim", "normalize_whitespace"],
        required: root.querySelector("[name=var_required]").checked,
        multiple: root.querySelector("[name=var_multiple]").checked,
        created_via: existing.created_via || "manual",
        last_updated_via: "manual",
      };
      state.variables = state.variables || [];
      if (idx >= 0) state.variables[idx] = item;
      else state.variables.push(item);
      render();
    });
    document.getElementById("testVar").addEventListener("click", async () => {
      const source = root.querySelector("[name=var_source]").value;
      if (source === "counter") {
        const body = await api(`/scraper/api/jobs/${meta.jobId}/test-variable/`, {
          name: root.querySelector("[name=var_name]").value || "page",
          source_type: "counter",
          url_template: state.url_template,
          configuration: {
            start_value: Number(root.querySelector("[name=var_start]").value || 1),
            increment: Number(root.querySelector("[name=var_inc]").value || 1),
          },
        });
        document.getElementById("varTest").textContent = body.ok
          ? `Values ${JSON.stringify(body.values)}. URLs: ${(body.rendered_urls || []).join(" → ")}`
          : body.error;
        return;
      }
      const body = await api(`/scraper/api/jobs/${meta.jobId}/test-selector/`, {
        selector: root.querySelector("[name=var_selector]").value,
        value_from: root.querySelector("[name=var_value_from]").value,
        attribute_name: root.querySelector("[name=var_attr]").value,
      });
      document.getElementById("varTest").textContent = body.ok
        ? `${body.matches} matches. ${JSON.stringify((body.samples || []).map((s) => s.transformed).slice(0, 3))}`
        : body.error;
    });
  }

  function openField(existing) {
    existing = existing || { scope: "result_item", extraction_method: "text_content", data_type: "text", include_in_csv: true, include_in_sqlite: true };
    const editor = document.getElementById("fieldEditor");
    if (!editor) return;
    editor.innerHTML = `<div class="mt-4 rounded-xl border border-slate-200 p-4 space-y-3">
      ${field("Display label", "f_label", existing.label || "")}
      ${field("Internal name", "f_name", existing.name || "")}
      ${field("Description", "f_desc", existing.description || "")}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Scope</span>
        <select name="f_scope" class="select">${optionList(choices.scopes, existing.scope)}</select></label>
      ${field("CSS selector", "f_selector", existing.selector || "")}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Extraction</span>
        <select name="f_extract" class="select">${optionList(choices.value_from, existing.extraction_method)}</select></label>
      ${field("Attribute name", "f_attr", existing.attribute_name || "")}
      <label class="block"><span class="text-[13.5px] font-medium block mb-1.5">Data type</span>
        <select name="f_type" class="select">${optionList(choices.data_types, existing.data_type)}</select></label>
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="f_required" ${existing.required ? "checked" : ""}> Required</label>
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="f_unique" ${existing.unique ? "checked" : ""}> Unique</label>
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="f_csv" ${existing.include_in_csv !== false ? "checked" : ""}> Include in CSV</label>
      <label class="flex items-center gap-2 text-[13px]"><input type="checkbox" name="f_sqlite" ${existing.include_in_sqlite !== false ? "checked" : ""}> Include in SQLite</label>
      <button type="button" id="saveField" class="btn-primary btn-sm">Save field</button>
    </div>`;
    const labelInput = root.querySelector("[name=f_label]");
    const nameInput = root.querySelector("[name=f_name]");
    labelInput.addEventListener("blur", async () => {
      if (nameInput.value) return;
      const body = await api("/scraper/api/field-name/", { label: labelInput.value });
      if (body.ok) nameInput.value = body.name;
    });
    document.getElementById("saveField").addEventListener("click", () => {
      const item = {
        name: nameInput.value,
        label: labelInput.value,
        description: root.querySelector("[name=f_desc]").value,
        scope: root.querySelector("[name=f_scope]").value,
        selector: root.querySelector("[name=f_selector]").value,
        extraction_method: root.querySelector("[name=f_extract]").value,
        attribute_name: root.querySelector("[name=f_attr]").value,
        data_type: root.querySelector("[name=f_type]").value,
        transformations: ["trim", "normalize_whitespace"],
        required: root.querySelector("[name=f_required]").checked,
        unique: root.querySelector("[name=f_unique]").checked,
        include_in_csv: root.querySelector("[name=f_csv]").checked,
        include_in_sqlite: root.querySelector("[name=f_sqlite]").checked,
        created_via: existing.created_via || "manual",
        last_updated_via: "manual",
      };
      if (item.extraction_method === "attribute") item.transformations.push("resolve_absolute_url");
      state.fields = (state.fields || []).filter((f) => f.name !== existing.name);
      state.fields.push(item);
      render();
    });
  }

  async function runTestPage() {
    const out = document.getElementById("testPageResult");
    out.textContent = "Testing…";
    const body = await api(`/scraper/api/jobs/${meta.jobId}/test-page/`, {
      url: (root.querySelector("[name=start_url]") || {}).value || state.start_url,
      rendering_mode: (root.querySelector("[name=rendering_mode]") || {}).value || state.rendering_mode,
    });
    if (!body.ok) {
      out.textContent = body.error;
      return;
    }
    if (body.inferred_url_template && root.querySelector("[name=url_template]")) {
      root.querySelector("[name=url_template]").value = body.inferred_url_template;
      state.url_template = body.inferred_url_template;
    }
    out.innerHTML = `<div class="rounded-xl border border-slate-200 p-3 space-y-1">
      <p>HTTP ${esc(body.status_code)} · ${esc(body.content_type)} · ${esc(body.duration_ms)} ms</p>
      <p class="break-all">Final URL: ${esc(body.final_url)}</p>
      <p>${body.javascript_likely ? "JavaScript rendering appears necessary." : "HTTP response looks usable."}</p>
      <iframe sandbox class="w-full h-64 bg-slate-50 rounded-lg border border-slate-200" srcdoc="${esc(body.html).slice(0, 20000)}"></iframe>
    </div>`;
  }

  async function runTestResult() {
    const out = document.getElementById("resultPreview");
    out.textContent = "Testing…";
    const body = await api(`/scraper/api/jobs/${meta.jobId}/test-selector/`, {
      selector: (root.querySelector("[name=result_selector]") || {}).value || state.result_selector,
    });
    if (!body.ok) {
      out.textContent = body.error;
      return;
    }
    out.innerHTML = `<p>${body.matches} matching cards.${body.warning ? " " + esc(body.warning) : ""}</p>
      <div class="grid gap-2">${(body.samples || []).map((s) => `<div class="rounded-lg border border-slate-200 p-2 text-[12px]">${esc(s.transformed || s.raw || "")}</div>`).join("")}</div>`;
  }

  document.querySelectorAll(".wizard-step").forEach((btn, i) => {
    btn.addEventListener("click", async () => {
      if (await persist()) {
        index = i;
        render();
      }
    });
  });
  back.addEventListener("click", async () => {
    if (index === 0) return;
    if (await persist()) {
      index -= 1;
      render();
    }
  });
  next.addEventListener("click", async () => {
    if (!(await persist())) return;
    if (index === steps.length - 1) {
      window.location.href = `/scraper/jobs/${meta.jobId}/`;
      return;
    }
    index += 1;
    render();
  });
  save.addEventListener("click", persist);

  const csvModal = document.getElementById("csvModal");
  const csvFile = document.getElementById("csvFile");
  const csvSummary = document.getElementById("csvSummary");
  const csvPreview = document.getElementById("csvPreview");
  const csvConfirm = document.getElementById("csvConfirmBtn");
  const csvErrors = document.getElementById("csvErrorsBtn");
  let lastErrorCsv = "";

  function csvMode() {
    const selected = document.querySelector("input[name=csvMode]:checked");
    return selected ? selected.value : "merge";
  }

  function openCsvModal() {
    if (!csvModal) return;
    csvModal.classList.remove("hidden");
    csvSummary.textContent = "";
    csvPreview.innerHTML = "";
    csvConfirm.disabled = true;
  }

  function closeCsvModal() {
    if (csvModal) csvModal.classList.add("hidden");
  }

  async function postCsv(path, extra) {
    const data = extra || new FormData();
    if (csvFile && csvFile.files[0] && !data.has("file")) data.append("file", csvFile.files[0]);
    data.set("mode", csvMode());
    if (document.getElementById("csvReplaceConfirm") && document.getElementById("csvReplaceConfirm").checked) {
      data.set("confirm_replace", "true");
    }
    const response = await fetch(path, { method: "POST", headers: { "X-CSRFToken": csrf() }, body: data });
    return response.json();
  }

  document.getElementById("cfgImportCsv")?.addEventListener("click", openCsvModal);
  document.getElementById("cfgAddManual")?.addEventListener("click", () => {
    const add = document.getElementById("addVariable") || root.querySelector("[data-add-field]");
    if (add) add.click();
  });
  document.getElementById("csvCancel")?.addEventListener("click", closeCsvModal);
  document.querySelectorAll("input[name=csvMode]").forEach((input) =>
    input.addEventListener("change", () => {
      const wrap = document.getElementById("csvReplaceConfirmWrap");
      if (wrap) wrap.classList.toggle("hidden", csvMode() !== "replace");
      csvConfirm.disabled = true;
    })
  );
  document.getElementById("csvPreviewBtn")?.addEventListener("click", async () => {
    const body = await postCsv(`/scraper/api/jobs/${meta.jobId}/config-csv/preview/`);
    lastErrorCsv = body.error_csv || "";
    if (!body.ok) {
      csvSummary.textContent = body.error || "Preview failed.";
      csvConfirm.disabled = true;
      csvErrors.classList.toggle("hidden", !lastErrorCsv);
      return;
    }
    const s = body.summary || {};
    csvSummary.innerHTML = `<p>${s.new_rows || 0} new rows · ${s.updated_rows || 0} rows will be updated · ${s.kept_rows || 0} existing rows will remain unchanged · ${s.deleted_rows || 0} rows will be deleted</p>
      <p>${s.valid_rows || 0} valid · ${s.invalid_rows || 0} invalid · ${s.warning_rows || 0} with warnings</p>`;
    csvPreview.innerHTML = `<table class="w-full"><thead><tr class="text-left text-ink-mute"><th class="py-1">Row</th><th>Type</th><th>Name</th><th>Action</th><th>Status</th></tr></thead><tbody>${(body.rows || [])
      .map((row) => `<tr class="border-t border-slate-100"><td class="py-1">${row.csv_row}</td><td>${esc(row.row_type)}</td><td class="font-mono">${esc(row.name)}</td><td>${esc(row.action)}</td><td>${row.valid ? "Valid" : esc((row.errors[0] || {}).message || "Invalid")}</td></tr>`)
      .join("")}</tbody></table>`;
    csvConfirm.disabled = !body.can_import || (csvMode() === "replace" && !document.getElementById("csvReplaceConfirm").checked);
    csvErrors.classList.toggle("hidden", !lastErrorCsv);
  });
  document.getElementById("csvReplaceConfirm")?.addEventListener("change", () => {
    csvConfirm.disabled = csvMode() === "replace" && !document.getElementById("csvReplaceConfirm").checked;
  });
  document.getElementById("csvConfirmBtn")?.addEventListener("click", async () => {
    const body = await postCsv(`/scraper/api/jobs/${meta.jobId}/config-csv/import/`);
    if (!body.ok) {
      csvSummary.textContent = body.error || "Import failed.";
      return;
    }
    Object.assign(state, body.job);
    closeCsvModal();
    render();
  });
  document.getElementById("csvErrorsBtn")?.addEventListener("click", () => {
    const blob = new Blob([lastErrorCsv || "row,column,value,code,message,suggestion\n"], { type: "text/csv" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "configuration_import_errors.csv";
    link.click();
  });

  render();
})();
