/* Renders every <div class="plotly-chart" data-source="ID"> from the Plotly figure JSON in <script id="ID" type="application/json">. */
(function () {
  "use strict";
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var theme = dark ? {font: {color: "#e5e7eb"}, xaxis: {gridcolor: "#374151", zerolinecolor: "#4b5563"}, yaxis: {gridcolor: "#374151", zerolinecolor: "#4b5563"}} : null;

  function merge(base, extra) {
    Object.keys(extra).forEach(function (k) {
      if (extra[k] && typeof extra[k] === "object" && !Array.isArray(extra[k])) { base[k] = merge(base[k] || {}, extra[k]); }
      else { base[k] = extra[k]; }
    });
    return base;
  }

  function render(el) {
    var src = document.getElementById(el.getAttribute("data-source"));
    if (!src || typeof Plotly === "undefined") { el.textContent = "Chart unavailable."; return; }
    var fig;
    try { fig = JSON.parse(src.textContent); } catch (e) { el.textContent = "Chart data could not be read."; return; }
    var layout = fig.layout || {};
    layout.autosize = true;
    if (theme) { layout = merge(layout, JSON.parse(JSON.stringify(theme))); if (layout.title) { layout.title.font = merge(layout.title.font || {}, {color: "#e5e7eb"}); } }
    Plotly.newPlot(el, fig.data || [], layout, {responsive: true, displaylogo: false});
    var label = el.getAttribute("data-label");
    if (label) { el.setAttribute("role", "img"); el.setAttribute("aria-label", label); }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".plotly-chart").forEach(render);
  });
})();
