(function () {
  const script = document.currentScript;
  const url = script && script.getAttribute("data-status-url");
  if (!url) return;
  const terminal = new Set(["COMPLETED", "FAILED", "CANCELLED", "PAUSED"]);

  async function tick() {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return true;
    const body = await response.json();
    if (!body.ok) return true;
    const set = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    };
    set("mPage", body.current_page);
    set("mPages", body.pages_completed);
    set("mDisc", body.records_discovered);
    set("mSaved", body.records_created);
    set("mSkip", body.records_skipped);
    set("mFail", body.records_failed);
    const phase = document.getElementById("runPhase");
    if (phase) phase.textContent = body.phase || "—";
    const bar = document.getElementById("runBar");
    if (bar) bar.style.width = Math.min(95, 15 + body.pages_completed * 10 + body.detail_pages_completed * 2) + "%";
    const events = document.getElementById("runEvents");
    if (events && body.events) {
      events.innerHTML = body.events
        .map((event) => `<li><span class="text-ink-faint">${event.at.slice(11, 19)}</span> ${event.message}</li>`)
        .join("");
    }
    return terminal.has(body.display_status);
  }

  async function loop() {
    const done = await tick();
    if (!done) window.setTimeout(loop, 2000);
  }
  loop();
})();
