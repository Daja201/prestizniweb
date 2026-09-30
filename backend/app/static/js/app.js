document.addEventListener("DOMContentLoaded", () => {
  const flash = document.querySelector(".flash");
  if (flash) window.setTimeout(() => flash.remove(), 7000);

  const root = document.documentElement;
  const avatarCharacterInput = document.querySelector("#avatar_character");
  const avatarPreview = document.querySelector("[data-avatar-preview]");
  if (avatarCharacterInput && avatarPreview) {
    const fallbackCharacter = avatarCharacterInput.placeholder;
    avatarCharacterInput.addEventListener("input", () => {
      avatarPreview.textContent = avatarCharacterInput.value || fallbackCharacter;
    });
  }

  const themeToggle = document.querySelector("[data-theme-toggle]");
  const savedTheme = localStorage.getItem("theme");
  if (savedTheme === "dark" || savedTheme === "light") root.dataset.theme = savedTheme;

  if (themeToggle) {
    const syncThemeLabel = () => {
      const dark = root.dataset.theme === "dark";
      themeToggle.textContent = dark ? "WHITE" : "BLACK";
      themeToggle.setAttribute("aria-label", dark ? "Přepnout na světlý režim" : "Přepnout na tmavý režim");
    };
    syncThemeLabel();
    themeToggle.addEventListener("click", () => {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      localStorage.setItem("theme", next);
      syncThemeLabel();
    });
  }

  const memeCards = [...document.querySelectorAll(".meme-card")];
  const pager = document.querySelector("[data-meme-pager]");
  if (memeCards.length && pager) {
    let index = 0;
    const prev = pager.querySelector("[data-meme-prev]");
    const next = pager.querySelector("[data-meme-next]");
    const counter = pager.querySelector("[data-meme-counter]");
    const renderMeme = () => {
      memeCards.forEach((card, i) => card.classList.toggle("is-active", i === index));
      if (counter) counter.textContent = `${index + 1} / ${memeCards.length}`;
      if (prev) prev.disabled = index === 0;
      if (next) next.disabled = index === memeCards.length - 1;
    };
    const showPrevious = () => { if (index > 0) { index -= 1; renderMeme(); } };
    const showNext = () => { if (index < memeCards.length - 1) { index += 1; renderMeme(); } };
    prev?.addEventListener("click", showPrevious);
    next?.addEventListener("click", showNext);
    document.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof HTMLElement && event.target.closest("input, textarea, select, button, a, [contenteditable='true']")) return;

      if (event.key === "ArrowLeft" || event.key === "ArrowUp" || (event.code === "Space" && event.shiftKey)) {
        event.preventDefault();
        showPrevious();
      } else if (event.key === "ArrowRight" || event.key === "ArrowDown" || event.code === "Space") {
        event.preventDefault();
        showNext();
      }
    });
    renderMeme();
  }

  document.addEventListener("click", (event) => {
    document.querySelectorAll("details[open]").forEach((details) => {
      if (!details.contains(event.target)) details.open = false;
    });
  });

  // ── cookie helpers ─────────────────────────────────────────────────────
  const ACK_MAX_AGE = 60 * 60 * 24 * 180; // 180 days
  const getCookie = (name) => {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
  };
  const setCookie = (name, value) => {
    document.cookie = `${name}=${encodeURIComponent(value)}; max-age=${ACK_MAX_AGE}; path=/; samesite=lax`;
  };

  // ── rules / no-responsibility acknowledgment, remembered via cookie ─────
  const rulesOverlay = document.querySelector("[data-rules-overlay]");
  const rulesOkBtn = document.querySelector("[data-rules-ok]");
  if (rulesOverlay && rulesOkBtn) {
    if (getCookie("rules_ack") !== "1") {
      rulesOverlay.classList.add("is-visible");
    }
    rulesOkBtn.addEventListener("click", () => {
      setCookie("rules_ack", "1");
      rulesOverlay.classList.remove("is-visible");
    });
  }

  // ── cookie usage notice ──────────────────────────────────────────────────
  const cookieBanner = document.querySelector("[data-cookie-banner]");
  const cookieOkBtn = document.querySelector("[data-cookie-ok]");
  if (cookieBanner && cookieOkBtn) {
    if (getCookie("cookie_ack") !== "1") {
      cookieBanner.classList.add("is-visible");
    }
    cookieOkBtn.addEventListener("click", () => {
      setCookie("cookie_ack", "1");
      cookieBanner.classList.remove("is-visible");
    });
  }
});
