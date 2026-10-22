// Admin actions without a page reload, so the list stays where you scrolled to.
// Forms marked data-ajax are posted with fetch(); without JavaScript they still work
// (the server then redirects back to the item's #anchor).
(function () {
  function renumber(list) {
    var items = Array.prototype.slice.call(list.querySelectorAll(":scope > li[id]"));
    items.forEach(function (li, i) {
      var num = li.querySelector(".qnum");
      if (num) num.textContent = i + 1;
      var up = li.querySelector("input[value=up]");
      var down = li.querySelector("input[value=down]");
      if (up) up.form.querySelector("button").disabled = i === 0;
      if (down) down.form.querySelector("button").disabled = i === items.length - 1;
    });
  }

  function updateCount(delta) {
    var count = document.querySelector("[data-count]");
    if (count) count.textContent = Math.max(0, parseInt(count.textContent, 10) + delta);
  }

  function flash(el) {
    el.classList.remove("flash");
    void el.offsetWidth; // restart the animation
    el.classList.add("flash");
  }

  function move(form) {
    var item = form.closest("li");
    var list = item.parentNode;
    var up = form.querySelector("input[name=direction]").value === "up";
    var sibling = up ? item.previousElementSibling : item.nextElementSibling;
    if (!sibling) return;
    var before = item.getBoundingClientRect().top;
    list.insertBefore(item, up ? sibling : sibling.nextElementSibling);
    renumber(list);
    // Keep the moved card under your finger instead of the page staying put
    window.scrollBy(0, item.getBoundingClientRect().top - before);
    flash(item);
    var button = form.querySelector("button");
    if (!button.disabled) button.focus();
  }

  function remove(form) {
    var item = form.closest("li, details");
    var list = item.parentNode;
    item.classList.add("removing");
    setTimeout(function () {
      item.remove();
      if (list.matches("ol, ul")) renumber(list);
      updateCount(-1);
    }, 250);
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      e.preventDefault();
      return;
    }
    var action = form.dataset.ajax;
    if (!action) return;
    e.preventDefault();
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    }).then(function (res) {
      if (!res.ok) throw new Error(res.status);
      if (action === "move") move(form);
      if (action === "remove") remove(form);
    }).catch(function () {
      form.submit(); // fall back to a normal post
    });
  });

  // Coming back from an edit (#r-12 / #q-abc): open and highlight that item
  if (location.hash) {
    var target = document.getElementById(location.hash.slice(1));
    if (target) {
      if (target.tagName === "DETAILS") target.open = true;
      flash(target);
    }
  }
})();
