document.addEventListener("DOMContentLoaded", () => {
  const flash = document.querySelector(".flash");
  if (flash) window.setTimeout(() => flash.remove(), 7000);

  const root = document.documentElement;
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
    prev?.addEventListener("click", () => { if (index > 0) { index -= 1; renderMeme(); } });
    next?.addEventListener("click", () => { if (index < memeCards.length - 1) { index += 1; renderMeme(); } });
    document.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") prev?.click();
      if (event.key === "ArrowRight") next?.click();
    });
    renderMeme();
  }

  document.addEventListener("click", (event) => {
    document.querySelectorAll("details[open]").forEach((details) => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
});
