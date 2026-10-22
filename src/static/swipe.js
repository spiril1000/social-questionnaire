// One question per screen. The form still works without this script (all questions stacked).
(function () {
  var form = document.getElementById("survey");
  if (!form) return;

  var slides = Array.prototype.slice.call(form.querySelectorAll("[data-step]"));
  var segments = Array.prototype.slice.call(document.querySelectorAll(".seg"));
  var backButton = document.getElementById("back");
  var AUTO_ADVANCE = { stars: true, nps: true, choice: true, matrix: true, contact: true };
  var MSG_REQUIRED = "Please answer this one to continue.";
  var MSG_HANDLE = "Add your username or number so we can reach you.";
  var current = 0;
  var depth = 0; // history entries we pushed, so the back button can use history.back()
  var advanceTimer = null;

  // Contact questions: the chosen method, and whether its username/number field is filled in
  function contactMethod(slide) {
    var checked = slide.querySelector("input[type=radio]:checked");
    return checked ? checked.value : null;
  }

  function contactHandle(slide) {
    var input = slide.querySelector(".contact-handle");
    return input ? input.value.trim() : "";
  }

  // Matches the server: a required question needs at least one answer
  function isAnswered(slide) {
    if (slide.dataset.type === "contact") {
      var method = contactMethod(slide);
      return method === "none" || (method !== null && contactHandle(slide) !== "");
    }
    if (slide.querySelector("input[type=radio]:checked")) return true;
    return Array.prototype.some.call(slide.querySelectorAll("input[type=text]:not(.comment), textarea"), function (el) {
      return el.value.trim() !== "";
    });
  }

  // The optional comment field under the answers (not an answer by itself)
  function hasComment(slide) {
    var input = slide.querySelector(".comment");
    return !!input && input.value.trim() !== "";
  }

  // Fully answered, e.g. every row of a rating grid. Used for auto-advance.
  function isComplete(slide) {
    if (slide.dataset.type === "contact") return contactMethod(slide) === "none";
    if (slide.dataset.type !== "matrix") return isAnswered(slide);
    return Array.prototype.every.call(slide.querySelectorAll(".stars"), function (g) {
      return g.querySelector("input:checked");
    });
  }

  // A contact method was picked but the username/number is still missing
  function missingHandle(slide) {
    var method = slide.dataset.type === "contact" && contactMethod(slide);
    return !!method && method !== "none" && contactHandle(slide) === "";
  }

  function updateContact(slide, focus) {
    var input = slide.querySelector(".contact-handle");
    var checked = slide.querySelector("input[type=radio]:checked");
    if (!input) return;
    var none = !checked || checked.value === "none";
    input.classList.toggle("is-hidden", none);
    if (checked && checked.dataset.placeholder) input.placeholder = checked.dataset.placeholder;
    input.type = checked && checked.value === "phone" ? "tel" : "text";
    if (focus && !none) input.focus();
  }

  function updateNextButton(slide) {
    var button = slide.querySelector("[data-next]");
    if (!button || slide.classList.contains("intro")) return;
    var skip = !slide.hasAttribute("data-required") && !isAnswered(slide) && !missingHandle(slide) && !hasComment(slide);
    button.textContent = skip ? "Skip" : "Next";
    button.classList.toggle("is-skip", skip);
  }

  function show(index) {
    clearTimeout(advanceTimer);
    current = Math.max(0, Math.min(slides.length - 1, index));
    slides.forEach(function (slide, i) {
      slide.classList.toggle("is-active", i === current);
      slide.classList.toggle("is-prev", i < current);
      slide.classList.toggle("is-next", i > current);
      slide.inert = i !== current;
      slide.setAttribute("aria-hidden", i !== current ? "true" : "false");
    });
    // Slide 0 is the intro, so question k is slide k + 1
    segments.forEach(function (seg, k) {
      seg.classList.toggle("done", k < current - 1);
      seg.classList.toggle("current", k === current - 1);
    });
    backButton.hidden = current === 0;
    updateNextButton(slides[current]);
  }

  function go(index) {
    if (index === current) return;
    history.pushState({ step: index }, "");
    depth++;
    show(index);
  }

  function shake(slide, message) {
    var error = slide.querySelector(".slide-error");
    if (error) {
      error.textContent = message || MSG_REQUIRED;
      error.hidden = false;
    }
    slide.classList.remove("shake");
    void slide.offsetWidth; // restart the animation
    slide.classList.add("shake");
  }

  // Why this slide can't be left yet, or null if it can
  function blocker(slide) {
    if (missingHandle(slide)) return MSG_HANDLE;
    if (slide.hasAttribute("data-required") && !isAnswered(slide)) return MSG_REQUIRED;
    return null;
  }

  function next() {
    var slide = slides[current];
    var problem = blocker(slide);
    if (problem) {
      shake(slide, problem);
      return;
    }
    if (current === slides.length - 1) {
      form.requestSubmit ? form.requestSubmit() : form.submit();
    } else {
      go(current + 1);
    }
  }

  function back() {
    if (current === 0) return;
    if (depth > 0) {
      history.back(); // popstate shows the previous slide
    } else {
      history.replaceState({ step: current - 1 }, "");
      show(current - 1);
    }
  }

  form.addEventListener("click", function (e) {
    if (e.target.closest("[data-next]")) next();
  });
  backButton.addEventListener("click", back);

  window.addEventListener("popstate", function (e) {
    depth = Math.max(0, depth - 1);
    show(e.state && typeof e.state.step === "number" ? e.state.step : 0);
  });

  form.addEventListener("change", function (e) {
    var slide = e.target.closest("[data-step]");
    if (!slide) return;
    if (slide.dataset.type === "contact" && e.target.type === "radio") updateContact(slide, true);
    var error = slide.querySelector(".slide-error");
    if (error && !blocker(slide)) error.hidden = true;
    updateNextButton(slide);
    // Tapping an answer moves on by itself, after a beat so the pop animation is visible.
    // Not when there's a comment field, or nobody would get to use it.
    if (AUTO_ADVANCE[slide.dataset.type] && e.target.type === "radio" && isComplete(slide)
        && !slide.querySelector(".comment")
        && slides.indexOf(slide) === current && current < slides.length - 1) {
      clearTimeout(advanceTimer);
      advanceTimer = setTimeout(next, 450);
    }
  });

  form.addEventListener("input", function (e) {
    var slide = e.target.closest("[data-step]");
    if (!slide) return;
    var error = slide.querySelector(".slide-error");
    if (error && !error.hidden && !blocker(slide)) error.hidden = true;
    updateNextButton(slide);
  });

  // Enter in a one-line text box goes to the next question instead of submitting
  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.matches("input[type=text], input[type=tel]")) {
      e.preventDefault();
      next();
    }
  });

  // Last line of defence before submitting: jump to the first question that isn't done
  form.addEventListener("submit", function (e) {
    for (var i = 1; i < slides.length; i++) {
      var problem = blocker(slides[i]);
      if (problem) {
        e.preventDefault();
        go(i);
        shake(slides[i], problem);
        return;
      }
    }
  });

  slides.forEach(function (slide) {
    if (slide.dataset.type === "contact") updateContact(slide, false);
  });

  // Start on the first question the server rejected, otherwise on the intro (or, when previewing
  // one question in the admin, on that question)
  var firstError = slides.findIndex(function (s) { return s.hasAttribute("data-error"); });
  var start = firstError > 0 ? firstError : parseInt(form.dataset.start, 10) || 0;
  history.replaceState({ step: start }, "");
  show(start);
})();
