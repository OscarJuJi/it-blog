/* Search, tag filtering and paging for the front page.
 *
 * The server already rendered every post card. This script never builds markup
 * -- it only decides which of those cards to show. That means there is nothing
 * to escape, nothing to keep in sync with post_item.html, and the page without
 * JavaScript is not a degraded mode but simply this one with no filter applied.
 *
 * The one rule worth keeping: URLs are consumed, never constructed. Python put
 * the /ti-blog prefix on them; string-joining here would silently drop it.
 */
(function () {
  "use strict";

  var PAGE = 10;
  var DEBOUNCE = 120;

  var list = document.querySelector("[data-posts-list]");
  var toolbar = document.querySelector("[data-toolbar]");
  if (!list || !toolbar) return; // not the index

  var search = toolbar.querySelector("[data-search]");
  var chip = toolbar.querySelector("[data-clear-tag]");
  var chipName = toolbar.querySelector("[data-active-tag]");
  var counter = document.querySelector("[data-count]");
  // The masthead carries a static count for visitors without JavaScript. Once
  // the live one is running it says the same thing twice, so it steps aside.
  var staticCount = document.querySelector(".index-count");
  var empty = document.querySelector("[data-empty]");
  var reset = document.querySelector("[data-reset]");
  var loadMore = document.querySelector("[data-load-more]");

  var cards = {};
  var order = [];
  var records = {};
  var query = "";
  var tag = "";
  var shown = PAGE;

  Array.prototype.forEach.call(list.querySelectorAll("[data-slug]"), function (el) {
    cards[el.getAttribute("data-slug")] = el;
  });

  var url = document.body.getAttribute("data-posts-url");
  if (!url) return;

  fetch(url)
    .then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.json();
    })
    .then(start)
    .catch(function () {
      /* Leave the page exactly as served: every post visible, no dead controls. */
    });

  function start(data) {
    (data.posts || []).forEach(function (post) {
      if (!cards[post.slug]) return; // in the index but not on this page
      var tags = (post.tags || []).map(lower);
      records[post.slug] = {
        text: lower(post.title + " " + post.summary + " " + tags.join(" ")),
        tags: tags
      };
      order.push(post.slug);
    });
    if (!order.length) return;

    toolbar.hidden = false;
    if (counter) counter.hidden = false;
    if (staticCount) staticCount.hidden = true;

    search.addEventListener("input", debounce(function () {
      query = search.value.trim().toLowerCase();
      shown = PAGE;
      apply();
    }, DEBOUNCE));

    document.addEventListener("click", onClick);
    if (loadMore) {
      loadMore.addEventListener("click", function () {
        shown += PAGE;
        apply();
      });
    }

    var initial = new URLSearchParams(location.search).get("tag");
    if (initial) tag = initial;
    apply();
  }

  function onClick(event) {
    var link = event.target.closest(".tag-cloud a[data-tag]");
    if (link) {
      event.preventDefault();
      var wanted = link.getAttribute("data-tag");
      tag = tag === wanted ? "" : wanted;
      shown = PAGE;
      // link.href was built by Python, so the prefix is already correct.
      history.replaceState(null, "", tag ? link.href : link.href.split("?")[0]);
      apply();
      return;
    }
    if (event.target.closest("[data-clear-tag]") || event.target.closest("[data-reset]")) {
      event.preventDefault();
      clear();
    }
  }

  function clear() {
    tag = "";
    query = "";
    shown = PAGE;
    search.value = "";
    history.replaceState(null, "", location.pathname);
    apply();
    search.focus();
  }

  function matches(slug) {
    var record = records[slug];
    if (tag && record.tags.indexOf(lower(tag)) === -1) return false;
    if (query && record.text.indexOf(query) === -1) return false;
    return true;
  }

  function lower(value) {
    return String(value).toLowerCase();
  }

  function apply() {
    var hits = order.filter(matches);

    order.forEach(function (slug) {
      cards[slug].hidden = true;
    });
    hits.slice(0, shown).forEach(function (slug) {
      cards[slug].hidden = false;
    });

    var left = Math.max(0, hits.length - shown);
    if (loadMore) {
      loadMore.hidden = left === 0;
      loadMore.textContent = "Show " + Math.min(PAGE, left) + " more (" + left + " left)";
    }
    if (empty) empty.hidden = hits.length !== 0;

    if (chip) {
      chip.hidden = !tag;
      if (tag && chipName) chipName.textContent = tag;
    }
    Array.prototype.forEach.call(document.querySelectorAll(".tag-cloud a[data-tag]"), function (a) {
      a.classList.toggle("is-active", a.getAttribute("data-tag") === tag);
    });

    if (counter) {
      counter.textContent =
        hits.length === order.length
          ? order.length + " entries"
          : hits.length + " of " + order.length + " entries";
    }
  }

  function debounce(fn, wait) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }
})();
