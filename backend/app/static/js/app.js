/* Small site-wide browser helpers. */
document.addEventListener("DOMContentLoaded", () => {
  const flash = document.querySelector(".flash");
  if (flash) window.setTimeout(() => flash.remove(), 7000);

  document.addEventListener("click", (event) => {
    document.querySelectorAll("details[open]").forEach((details) => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
});