/* Login screen only: password visibility and the submit loading state. */
(function () {
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }

  document.addEventListener("click", (event) => {
    const btn = event.target.closest('[data-action="toggle-password"]');
    if (!btn) return;
    const input = document.getElementById(btn.getAttribute("data-target"));
    if (!input) return;

    const revealed = input.type === "text";
    input.type = revealed ? "password" : "text";
    btn.setAttribute("aria-pressed", String(!revealed));
    btn.setAttribute("aria-label", revealed ? "Show password" : "Hide password");
    btn.innerHTML = '<i data-lucide="' + (revealed ? "eye" : "eye-off") + '" class="text-[16px]"></i>';
    if (window.lucide) window.lucide.createIcons();
    input.focus();
  });

  const form = document.querySelector("[data-login-form]");
  if (!form) return;

  form.addEventListener("submit", () => {
    const button = form.querySelector("[data-login-submit]");
    if (!button) return;
    // Native validation may still block submission, so only show the loading
    // state once the browser has accepted the form.
    if (typeof form.checkValidity === "function" && !form.checkValidity()) return;

    button.disabled = true;
    const spinner = button.querySelector("[data-spinner]");
    const label = button.querySelector("[data-label]");
    if (spinner) spinner.classList.remove("hidden");
    if (label) label.textContent = "Signing in…";
    if (window.lucide) window.lucide.createIcons();
  });
})();
