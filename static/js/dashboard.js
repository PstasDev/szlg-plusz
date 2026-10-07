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
})();
