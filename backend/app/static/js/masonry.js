/* Appends meme cards to the shortest stable masonry column. */
(() => {
  const columnCount = (width) => width < 560 ? 2 : width < 800 ? 3 : width < 1120 ? 4 : 5;

  function setup(grid) {
    let columns = [];
    let count = 0;
    let lastWidth = 0;

    function placeCards(rebuild = false) {
      const width = grid.clientWidth;
      if (!width) return;
      const nextCount = columnCount(width);
      const breakpointChanged = nextCount !== count;
      if (rebuild || breakpointChanged) {
        const cards = [...grid.querySelectorAll(":scope > .meme-card, :scope > .masonry-column > .meme-card")];
        grid.querySelectorAll(":scope > .masonry-column").forEach((column) => column.remove());
        columns = Array.from({ length: nextCount }, () => {
          const column = document.createElement("div");
          column.className = "masonry-column";
          column.setAttribute("role", "list");
          grid.append(column);
          return { element: column, height: 0 };
        });
        count = nextCount;
        cards.forEach((card) => appendCard(card));
      } else {
        grid.querySelectorAll(":scope > .meme-card").forEach((card) => appendCard(card));
      }
      const sentinel = grid.querySelector(":scope > .meme-sentinel");
      if (sentinel && grid.lastElementChild !== sentinel) grid.append(sentinel);
      lastWidth = width;
    }

    function appendCard(card) {
      const shortest = columns.reduce((best, column) => column.height < best.height ? column : best, columns[0]);
      const cardWidth = Number(card.dataset.width) || 1;
      const cardHeight = Number(card.dataset.height) || 1;
      const columnWidth = Math.max(1, grid.clientWidth / columns.length);
      shortest.element.append(card);
      shortest.height += columnWidth * cardHeight / cardWidth + 120;
    }

    placeCards(true);
    const resizeObserver = new ResizeObserver(() => {
      if (columnCount(grid.clientWidth) !== count) placeCards(true);
      else if (Math.abs(grid.clientWidth - lastWidth) > 1) lastWidth = grid.clientWidth;
    });
    resizeObserver.observe(grid);
    grid.addEventListener("htmx:afterSwap", () => placeCards());
    grid.addEventListener("htmx:load", () => placeCards());
    new MutationObserver(() => queueMicrotask(() => placeCards())).observe(grid, { childList: true });
    document.body.addEventListener("htmx:afterSwap", (event) => {
      if (event.detail.target === grid || grid.contains(event.detail.target)) placeCards();
    });
  }

  function initialize(root = document) {
    root.querySelectorAll("[data-masonry]:not([data-masonry-ready])").forEach((grid) => {
      grid.dataset.masonryReady = "true";
      setup(grid);
    });
  }

  document.addEventListener("DOMContentLoaded", () => initialize());
  document.body.addEventListener("htmx:load", (event) => initialize(event.detail.elt));
})();