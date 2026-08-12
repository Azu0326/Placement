/* Shell behaviours only — page navigation is Django URLs, not go(). */
(function () {
  const $ = (id) => document.getElementById(id);

  function icons() {
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  }

  function openRail() {
    const rail = $("rail");
    const scrim = $("scrim");
    if (!rail) return;
    rail.classList.remove("-translate-x-full");
    if (scrim) scrim.classList.remove("hidden");
  }

  function closeRail() {
    if (window.innerWidth >= 1024) return;
    const rail = $("rail");
    const scrim = $("scrim");
    if (rail) rail.classList.add("-translate-x-full");
    if (scrim) scrim.classList.add("hidden");
  }

  function collapseRail() {
    const rail = $("rail");
    const shell = $("shell");
    if (!rail || !shell) return;
    rail.classList.toggle("rail-collapsed");
    const collapsed = rail.classList.contains("rail-collapsed");
    rail.classList.toggle("w-[260px]", !collapsed);
    shell.classList.toggle("lg:pl-[260px]", !collapsed);
    shell.classList.toggle("lg:pl-[72px]", collapsed);
  }

  function toggleGrp(id) {
    const el = $(id);
    if (el) el.classList.toggle("open");
  }

  function tog(id) {
    const el = $(id);
    if (el) el.classList.toggle("hidden");
  }

  function stepPage(delta) {
    const input = $("pageNum");
    if (!input) return;
    let value = (parseInt(input.value, 10) || 1) + delta;
    input.value = Math.min(1000, Math.max(1, value));
  }

  function showToast() {
    const toast = $("toast");
    if (!toast) return;
    toast.classList.remove("opacity-0", "translate-y-4", "pointer-events-none");
    window.setTimeout(() => {
      toast.classList.add("opacity-0", "translate-y-4", "pointer-events-none");
    }, 3200);
    icons();
  }

  function startJob(jobsUrl) {
    window.location.href = jobsUrl || "/scraper/jobs/?queued=1";
  }

  function openDrawer() {
    const scrim = $("drawerScrim");
    const drawer = $("drawer");
    if (scrim) scrim.classList.remove("hidden");
    if (drawer) drawer.classList.remove("translate-x-full");
    icons();
  }

  function closeDrawer() {
    const scrim = $("drawerScrim");
    const drawer = $("drawer");
    if (scrim) scrim.classList.add("hidden");
    if (drawer) drawer.classList.add("translate-x-full");
  }

  function runTab(group, idx, btn) {
    document.querySelectorAll(".tab-" + group).forEach((b) => {
      b.classList.remove("border-primary-500", "text-primary-600");
      b.classList.add("border-transparent", "text-ink-mute");
    });
    if (btn) {
      btn.classList.add("border-primary-500", "text-primary-600");
      btn.classList.remove("border-transparent", "text-ink-mute");
    }
    document.querySelectorAll(".pane-" + group).forEach((p, i) => {
      p.classList.toggle("hidden", i !== idx);
    });
  }

  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.getAttribute("data-action");
    if (action === "open-rail") openRail();
    if (action === "close-rail") closeRail();
    if (action === "collapse-rail") collapseRail();
    if (action === "toggle-grp") toggleGrp(btn.getAttribute("data-target"));
    if (action === "toggle") tog(btn.getAttribute("data-target"));
    if (action === "open-drawer") openDrawer();
    if (action === "close-drawer") closeDrawer();
    if (action === "tab") {
      runTab(
        btn.getAttribute("data-group"),
        parseInt(btn.getAttribute("data-idx"), 10) || 0,
        btn
      );
    }
    if (action === "step-page") {
      stepPage(parseInt(btn.getAttribute("data-delta"), 10) || 0);
    }
    if (action === "start-job") {
      startJob(btn.getAttribute("data-jobs-url"));
    }
    if (action === "fill-target") {
      const url = $("targetUrl");
      const page = $("pageNum");
      if (url) url.value = btn.getAttribute("data-url") || "";
      if (page) page.value = btn.getAttribute("data-page") || "1";
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeRail();
      closeDrawer();
      document.querySelectorAll('[id^="job-menu-"]').forEach((menu) => {
        menu.classList.add("hidden");
      });
    }
  });

  // In-page helpers used by later screen phases
  window.tog = tog;
  window.showToast = showToast;
  window.tab = runTab;
  window.openDrawer = openDrawer;
  window.closeDrawer = closeDrawer;

  icons();
})();
