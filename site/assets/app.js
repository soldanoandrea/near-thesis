/* near-thesis dashboard: renders the chart specs in data.js with Plotly, in the current light/dark theme.
   No build step, no network calls besides the pinned Plotly.js script tag; works from file:// and GitHub Pages. */
(function () {
  "use strict";
  var root = document.documentElement;
  var DATA = window.NT_DATA || { charts: [] };
  var VAR = { s1: "--series-1", s2: "--series-2", s3: "--series-3", s4: "--series-4", s5: "--series-5",
              s6: "--series-6", s7: "--series-7", s8: "--series-8", ink: "--text-primary", ink2: "--text-secondary",
              muted: "--text-muted", grid: "--grid", axis: "--axis", surface: "--surface-1", page: "--page" };

  function storedTheme() { try { return localStorage.getItem("nt-theme"); } catch (e) { return null; } }
  function saveTheme(t) { try { if (t) localStorage.setItem("nt-theme", t); else localStorage.removeItem("nt-theme"); } catch (e) { /* private mode */ } }
  function applyTheme(t) {
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t); else root.removeAttribute("data-theme");
    var b = document.getElementById("theme-toggle");
    if (b) b.textContent = "Theme: " + (t || "auto");
  }

  function cssVar(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function rgba(hex, a) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var n = parseInt(h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }
  function color(tok) {
    var m = /^@([a-z0-9]+)(?:\/([0-9.]+))?$/.exec(tok);
    if (!m || !VAR[m[1]]) return tok;
    var c = cssVar(VAR[m[1]]);
    return m[2] ? rgba(c, m[2]) : c;
  }
  function resolve(o) {
    if (typeof o === "string") return o.charAt(0) === "@" ? color(o) : o;
    if (Array.isArray(o)) return o.map(resolve);
    if (o && typeof o === "object") { var r = {}; for (var k in o) r[k] = resolve(o[k]); return r; }
    return o;
  }
  function merge(a, b) {
    var out = {}, k;
    for (k in a) out[k] = a[k];
    for (k in b) out[k] = (b[k] && typeof b[k] === "object" && !Array.isArray(b[k]) && out[k] && typeof out[k] === "object")
      ? merge(out[k], b[k]) : b[k];
    return out;
  }

  var capture = (/(?:^|[#&])capture=([a-z0-9-]+)/.exec(location.hash) || [])[1] || null;

  function setupCapture() {
    if (!capture) return;
    var target = document.getElementById("card-" + capture) || document.getElementById(capture);
    if (!target) return;
    document.body.classList.add("capture");
    target.classList.add("capture-target");
    var note = (/(?:^|[#&])note=([^&]+)/.exec(location.hash) || [])[1];
    if (note) {  // a short heading for video frames, e.g. #capture=intents&note=2%2F6%20...
      var div = document.createElement("div");
      div.className = "capture-note";
      div.textContent = decodeURIComponent(note);
      target.insertBefore(div, target.firstChild);
    }
    var p = target.parentElement;
    while (p && p !== document.body) { p.classList.add("capture-keep"); p = p.parentElement; }
  }

  // capture mode: the plot takes the window height left over by the card's title, caption and source line
  function captureHeight(el) {
    var card = el.closest(".capture-target"), used = 0, cs = getComputedStyle(card);
    Array.prototype.forEach.call(card.children, function (ch) {
      var s = getComputedStyle(ch);
      if (ch === el || ch.contains(el) || s.display === "none") return;
      used += ch.getBoundingClientRect().height + parseFloat(s.marginTop) + parseFloat(s.marginBottom);
    });
    return Math.max(260, Math.floor(window.innerHeight - used - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - 4));
  }

  function render() {
    if (!window.Plotly) { document.body.classList.add("no-plotly"); return; }
    var ink = cssVar("--text-primary");
    DATA.charts.forEach(function (c) {
      var el = document.getElementById("plot-" + c.id);
      if (!el || (capture && !el.closest(".capture-target"))) return;
      var narrow = el.clientWidth < 640;
      var layout = resolve(c.layout);
      if (narrow && c.layout_narrow) layout = merge(layout, resolve(c.layout_narrow));
      if (narrow && layout.legend) {  // phone width: one legend entry per line, kept clear of the plot area
        var n = c.traces.filter(function (t) { return t.showlegend !== false && t.name && t.type !== "sankey"; }).length;
        var m = layout.margin || {};
        if (layout.legend.y > 0.5) {
          layout.legend = merge(layout.legend, { orientation: "v", x: 0, y: 1.0, xanchor: "left", yanchor: "bottom" });
          m.t = Math.max(m.t || 0, 18 + 22 * n);
        } else {
          layout.legend = merge(layout.legend, { orientation: "v", x: 0, y: -0.12, xanchor: "left", yanchor: "top" });
          m.b = Math.max(m.b || 0, 70 + 22 * n);
        }
        layout.margin = m;
      }
      layout.height = capture ? captureHeight(el) : ((narrow && c.height_narrow) || c.height);
      layout.paper_bgcolor = "rgba(0,0,0,0)";
      layout.plot_bgcolor = "rgba(0,0,0,0)";
      layout.font = merge({ family: getComputedStyle(document.body).fontFamily, color: ink, size: capture ? 14 : 12 }, layout.font || {});
      layout.hoverlabel = { bgcolor: cssVar("--surface-1"), bordercolor: cssVar("--axis"), font: { color: ink } };
      if (layout.legend) layout.legend.font = { color: cssVar("--text-secondary"), size: capture ? 14 : 12 };
      var config = { responsive: true, displaylogo: false, displayModeBar: !capture && !narrow,
                     modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"] };
      el.dataset.narrow = narrow ? "1" : "0";
      window.Plotly.react(el, resolve(c.traces), layout, config);
    });
  }

  var lastNarrow = null, timer = null;
  function onResize() {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var el = document.querySelector(".plot");
      var n = el ? el.clientWidth < 640 : false;
      if (n !== lastNarrow) { lastNarrow = n; render(); }
    }, 150);
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(storedTheme());
    setupCapture();
    var b = document.getElementById("theme-toggle");
    if (b) b.addEventListener("click", function () {
      var cur = storedTheme(), next = cur === null ? "light" : cur === "light" ? "dark" : null;
      saveTheme(next); applyTheme(next); render();
    });
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      if (mq.addEventListener) mq.addEventListener("change", render);
    }
    window.addEventListener("resize", onResize);
    var el = document.querySelector(".plot");
    lastNarrow = el ? el.clientWidth < 640 : false;
    render();
    document.body.setAttribute("data-rendered", window.Plotly ? "plotly" : "tables-only");
    document.body.setAttribute("data-ih", String(window.innerHeight));  // used by the screenshot script
    document.body.setAttribute("data-iw", String(window.innerWidth));
  });
})();
