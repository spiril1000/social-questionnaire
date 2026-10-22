// "Install the admin" banner, admin pages only, on phones. Android/Chrome gets a real Install button
// (beforeinstallprompt); iPhone Safari has no such API, so it shows the Add to Home Screen steps.
(function () {
  var banner = document.getElementById("install-banner");
  if (!banner) return;

  var DISMISS_KEY = "install-banner-dismissed";
  var DISMISS_DAYS = 14;
  var standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  var phone = window.matchMedia("(max-width: 767px)").matches || window.matchMedia("(pointer: coarse)").matches;
  var ios = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var deferredPrompt = null;

  function dismissedRecently() {
    try {
      var at = parseInt(localStorage.getItem(DISMISS_KEY) || "0", 10);
      return Date.now() - at < DISMISS_DAYS * 24 * 3600 * 1000;
    } catch (e) {
      return false;
    }
  }

  function show(kind) {
    if (standalone || !phone || dismissedRecently()) return;
    banner.querySelector("[data-install-text=android]").hidden = kind !== "android";
    banner.querySelector("[data-install-text=ios]").hidden = kind !== "ios";
    banner.querySelector("[data-install=accept]").hidden = kind !== "android";
    banner.querySelector("[data-install=dismiss]").textContent = kind === "ios" ? "Got it" : "Not now";
    banner.hidden = false;
  }

  function hide(remember) {
    banner.hidden = true;
    if (remember) {
      try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (e) { /* private mode */ }
    }
  }

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault(); // use our banner instead of the browser's mini-infobar
    deferredPrompt = e;
    show("android");
  });

  window.addEventListener("appinstalled", function () { hide(true); });

  banner.addEventListener("click", function (e) {
    var action = e.target.closest("[data-install]");
    if (!action) return;
    if (action.dataset.install === "accept" && deferredPrompt) {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(function (choice) {
        hide(choice.outcome === "accepted");
        deferredPrompt = null;
      });
    } else {
      hide(true);
    }
  });

  if (ios) show("ios");
})();
