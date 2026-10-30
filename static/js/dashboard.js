(function () {
  var root = document.documentElement;

  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    var label = function () {
      toggle.textContent = root.getAttribute("data-theme") === "light" ? "Sötét mód" : "Világos mód";
    };
    label();
    toggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("szlg-theme", next); } catch (e) {}
      label();
    });
  }

  document.addEventListener("submit", function (event) {
    var message = event.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var source = document.getElementById(button.getAttribute("data-copy"));
    if (!source || !navigator.clipboard) return;
    navigator.clipboard.writeText(source.value).then(function () {
      var original = button.textContent;
      button.textContent = "Másolva";
      setTimeout(function () { button.textContent = original; }, 1500);
    });
  });

  document.querySelectorAll("[data-group-selector]").forEach(function (selector) {
    var search = selector.querySelector("[data-group-selector-search]");
    var options = Array.prototype.slice.call(
      selector.querySelectorAll("[data-group-selector-option]")
    );
    var status = selector.querySelector("[data-group-selector-status]");
    var empty = selector.querySelector("[data-group-selector-empty]");
    var selected = selector.querySelector("[data-group-selector-selected]");
    var clear = selector.querySelector("[data-group-selector-clear]");

    if (!search || !status || !empty || !selected || !clear) return;

    search.hidden = false;
    status.hidden = false;
    clear.hidden = false;
    selector.setAttribute("data-enhanced", "true");

    function updateGroupSelector() {
      var query = search.value.trim().toLocaleLowerCase();
      var visibleCount = 0;
      var selectedNames = [];

      options.forEach(function (option) {
        var checkbox = option.querySelector('input[type="checkbox"]');
        var name = option.textContent.trim();
        var matches = !query || name.toLocaleLowerCase().indexOf(query) !== -1;

        option.hidden = !matches;
        if (matches) visibleCount += 1;
        if (checkbox && checkbox.checked) selectedNames.push(name);
      });

      status.textContent =
        "Találat: " + visibleCount + " · Kijelölve: " + selectedNames.length;
      empty.hidden = visibleCount !== 0;
      selected.hidden = selectedNames.length === 0;
      selected.textContent = "Kiválasztva: " + selectedNames.join(", ");
      clear.disabled = selectedNames.length === 0;
    }

    selector.addEventListener("change", function (event) {
      if (event.target.matches('input[type="checkbox"]')) updateGroupSelector();
    });
    search.addEventListener("input", updateGroupSelector);
    clear.addEventListener("click", function () {
      options.forEach(function (option) {
        var checkbox = option.querySelector('input[type="checkbox"]');
        if (checkbox) checkbox.checked = false;
      });
      updateGroupSelector();
      search.focus();
    });

    updateGroupSelector();
  });
})();
