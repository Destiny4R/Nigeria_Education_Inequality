/* Polls status.json of a queued/running analysis run and reloads the page when it finishes. */
(function () {
  "use strict";
  var box = document.getElementById("run-status");
  if (!box) { return; }
  var url = box.getAttribute("data-status-url");
  var out = box.querySelector("[data-progress]");
  var tries = 0;
  function poll() {
    tries += 1;
    fetch(url, {headers: {"Accept": "application/json"}, credentials: "same-origin"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (out) { out.textContent = d.status + (d.progress ? " - " + d.progress : ""); }
        if (d.status === "succeeded" || d.status === "failed") { window.location.reload(); return; }
        setTimeout(poll, Math.min(1000 + tries * 500, 5000));
      })
      .catch(function () { setTimeout(poll, 5000); });
  }
  poll();
})();
