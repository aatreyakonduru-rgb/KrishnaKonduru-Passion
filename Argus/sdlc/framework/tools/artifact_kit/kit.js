
/* Devin artifact kit — self-contained behavior for standalone HTML artifacts.
   No build step, no imports, no network calls. Every widget is progressive
   enhancement: the markup stays readable and printable with scripting off. */
(function () {
  "use strict";

  var root = document.documentElement;
  var THEMES = { light: 1, dark: 1 };

  function showError(message) {
    document.querySelectorAll("[data-a-error]").forEach(function (region) {
      region.hidden = false;
      var detail = region.querySelector("[data-a-error-detail]");
      if (detail && message) detail.textContent = message;
    });
  }

  window.addEventListener("error", function (event) {
    showError(event.message);
  });
  window.addEventListener("unhandledrejection", function (event) {
    showError(String(event.reason || "An interactive control failed."));
  });

  /* ---------- theme ----------
     Order of precedence:
       1. an explicit host signal (`?theme=`/`#theme=`, a `devin:theme`
          message from an embedding page, or a preset `data-theme`),
       2. a reader's in-document choice,
       3. the OS/browser preference via `prefers-color-scheme`.
     Hosts that expose no signal simply fall through to step 3. */
  function hostTheme() {
    var search = new URLSearchParams(
      window.location.search + "&" + window.location.hash.replace(/^#/, "")
    );
    var fromUrl = search.get("theme");
    if (fromUrl && THEMES[fromUrl]) return fromUrl;
    var preset = root.getAttribute("data-theme");
    if (preset && THEMES[preset]) return preset;
    return null;
  }

  function systemTheme() {
    return window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  var pinned = hostTheme();

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-a-theme-toggle]").forEach(function (el) {
      var label =
        theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
      el.setAttribute("aria-label", label);
      el.setAttribute("title", label);
    });
  }

  apply(pinned || systemTheme());

  if (window.matchMedia) {
    var media = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function () {
      if (!pinned) apply(systemTheme());
    };
    if (media.addEventListener) media.addEventListener("change", onChange);
    else if (media.addListener) media.addListener(onChange);
  }

  window.addEventListener("message", function (event) {
    if (window.parent === window || event.source !== window.parent) return;
    var data = event.data;
    if (!data || data.type !== "devin:theme" || !THEMES[data.theme]) return;
    pinned = data.theme;
    apply(pinned);
  });

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-a-theme-toggle]");
    if (!toggle) return;
    pinned = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    apply(pinned);
  });

  /* ---------- tabs ----------
     <div data-a-tabs role="tablist">
       <button class="a-btn" role="tab" aria-controls="panel-id">Label</button>
     Panels are plain elements toggled with `hidden`, so print reveals the
     active one and `.a-print-reveal` can opt others in. */
  function selectTab(list, tab) {
    list.querySelectorAll('[role="tab"]').forEach(function (candidate) {
      var selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      var panel = document.getElementById(
        candidate.getAttribute("aria-controls") || ""
      );
      if (panel) panel.hidden = !selected;
    });
  }

  document.querySelectorAll("[data-a-tabs]").forEach(function (list) {
    var tabs = Array.prototype.slice.call(
      list.querySelectorAll('[role="tab"]')
    );
    if (!tabs.length) return;
    var active =
      tabs.filter(function (t) {
        return t.getAttribute("aria-selected") === "true";
      })[0] || tabs[0];
    selectTab(list, active);

    list.addEventListener("click", function (event) {
      var tab = event.target.closest('[role="tab"]');
      if (tab) selectTab(list, tab);
    });

    list.addEventListener("keydown", function (event) {
      var step =
        event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      var current = tabs.indexOf(document.activeElement);
      var next = tabs[(current + step + tabs.length) % tabs.length];
      next.focus();
      selectTab(list, next);
    });
  });

  /* ---------- row filters ----------
     <select data-a-filter="#table-id" data-a-filter-key="team">
     Rows opt in with a matching `data-team` attribute; "all" clears it. */
  document.querySelectorAll("[data-a-filter]").forEach(function (control) {
    var target = document.querySelector(control.getAttribute("data-a-filter"));
    var key = control.getAttribute("data-a-filter-key") || "filter";
    if (!target) return;

    var emptySelector = control.getAttribute("data-a-filter-empty");
    var empty = emptySelector ? document.querySelector(emptySelector) : null;

    var applyFilter = function () {
      var value = control.value;
      var shown = 0;
      /* Re-read the rows every time: a script may have replaced them since
         the last pass, and those rows must obey the current selection too. */
      target.querySelectorAll("[data-" + key + "]").forEach(function (row) {
        var match = value === "all" || row.getAttribute("data-" + key) === value;
        row.hidden = !match;
        if (match) shown += 1;
      });
      if (empty) empty.hidden = shown !== 0;
      target.hidden = shown === 0 && !!empty;
    };

    control.addEventListener("change", applyFilter);
    applyFilter();

    /* Rows swapped in by a script are filtered as soon as they land, so a
       redraw never shows rows the current selection excludes. Only childList
       is watched, so the `hidden` writes above cannot retrigger this. */
    new MutationObserver(function () {
      applyFilter();
    }).observe(target, { childList: true, subtree: true });
  });

  /* ---------- tooltips ----------
     One shared tooltip serves every chart and any element carrying
     `data-a-tip`. Pointer, keyboard focus, and touch all route through the
     same show/hide pair, so an exact value is never hover-only. */
  var tipEl = null;
  var tipRelease = null;
  var tipHost = null;

  function tipNode() {
    if (tipEl) return tipEl;
    tipEl = document.createElement("div");
    tipEl.className = "a-tip a-no-print";
    tipEl.setAttribute("role", "tooltip");
    tipEl.hidden = true;
    document.body.appendChild(tipEl);
    return tipEl;
  }

  function hideTip() {
    var release = tipRelease;
    tipRelease = null;
    tipHost = null;
    if (release) release();
    if (tipEl) tipEl.hidden = true;
  }

  function positionTip(anchor, pointer) {
    var el = tipNode();
    var width = el.offsetWidth;
    var height = el.offsetHeight;
    var edge = 8;
    var x = pointer ? pointer.x + 14 : anchor.left + anchor.width / 2 - width / 2;
    var y = pointer ? pointer.y - height - 16 : anchor.top - height - 10;
    if (y < edge) y = pointer ? pointer.y + 22 : anchor.bottom + 10;
    x = Math.max(edge, Math.min(x, window.innerWidth - width - edge));
    y = Math.max(edge, Math.min(y, window.innerHeight - height - edge));
    el.style.transform =
      "translate(" + Math.round(x) + "px, " + Math.round(y) + "px)";
  }

  function tipRow(row) {
    var line = document.createElement("div");
    line.className =
      "a-tip__row" + (row.series ? " a-series-" + row.series : "");
    if (row.series) {
      var swatch = document.createElement("span");
      swatch.className = "a-tip__swatch";
      line.appendChild(swatch);
    }
    var name = document.createElement("span");
    name.className = "a-tip__name";
    name.textContent = row.name || "";
    line.appendChild(name);
    var value = document.createElement("span");
    value.className = "a-tip__value";
    value.textContent = row.value == null || row.value === "" ? "—" : row.value;
    line.appendChild(value);
    return line;
  }

  /* `content` is { title, text, rows: [{ name, value, series }] }. `release`
     runs when the tooltip is replaced or dismissed so the owner can drop its
     highlight state. */
  function showTip(content, host, anchor, pointer, release) {
    if (tipRelease && tipRelease !== release) {
      var previous = tipRelease;
      tipRelease = null;
      previous();
    }
    tipRelease = release || null;
    tipHost = host || null;
    var el = tipNode();
    el.textContent = "";
    if (content.title) {
      var title = document.createElement("div");
      title.className = "a-tip__title";
      title.textContent = content.title;
      el.appendChild(title);
    }
    if (content.text) {
      var text = document.createElement("div");
      text.className = "a-tip__text";
      text.textContent = content.text;
      el.appendChild(text);
    }
    (content.rows || []).forEach(function (row) {
      el.appendChild(tipRow(row));
    });
    el.hidden = false;
    positionTip(anchor, pointer);
  }

  /* Escape hatch for hand-authored marks: `data-a-tip` holds the value text
     and the optional `data-a-tip-title` holds a heading. */
  function annotatedHost(node) {
    return node && node.closest ? node.closest("[data-a-tip]") : null;
  }

  function showAnnotatedTip(host, pointer) {
    showTip(
      {
        title: host.getAttribute("data-a-tip-title") || "",
        text: host.getAttribute("data-a-tip") || ""
      },
      host,
      host.getBoundingClientRect(),
      pointer,
      null
    );
  }

  document.addEventListener("pointerover", function (event) {
    var host = annotatedHost(event.target);
    if (!host) return;
    showAnnotatedTip(
      host,
      event.pointerType === "touch" ? null : { x: event.clientX, y: event.clientY }
    );
  });

  document.addEventListener("pointermove", function (event) {
    if (!tipHost || event.pointerType === "touch") return;
    if (!tipHost.hasAttribute || !tipHost.hasAttribute("data-a-tip")) return;
    if (annotatedHost(event.target) !== tipHost) return;
    positionTip(tipHost.getBoundingClientRect(), {
      x: event.clientX,
      y: event.clientY
    });
  });

  document.addEventListener("pointerout", function (event) {
    var host = annotatedHost(event.target);
    if (!host || host !== tipHost) return;
    if (event.relatedTarget && host.contains(event.relatedTarget)) return;
    hideTip();
  });

  document.addEventListener("focusin", function (event) {
    var host = annotatedHost(event.target);
    if (host) showAnnotatedTip(host, null);
  });

  document.addEventListener("focusout", function (event) {
    var host = annotatedHost(event.target);
    if (!host || host !== tipHost) return;
    /* A still-hovered mark keeps its tooltip; `pointerout` closes that one. */
    if (host.matches && host.matches(":hover")) return;
    hideTip();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") hideTip();
  });

  window.addEventListener("scroll", hideTip, true);
  window.addEventListener("resize", hideTip);

  /* ---------- charts ----------
     <figure class="a-figure" data-a-chart="bar|stacked-bar|line"> wrapping a
     plain <table> of the same numbers. The table is both the data source and
     the no-script fallback: the kit draws the chart from it and then keeps it
     under a disclosure as the exact-value equivalent. Each category gets a
     hover band that also takes keyboard focus, so pointer, arrow keys, and
     tap all produce the same readout. */
  var SVG_NS = "http://www.w3.org/2000/svg";
  var CHART_WIDTH = 640;
  var CHART_TYPES = { bar: 1, "stacked-bar": 1, line: 1 };

  function svgNode(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, String(attrs[key]));
    });
    return node;
  }

  /* `data-value` wins so cells can stay human-readable ("1,284", "18m 24s"). */
  function cellNumber(cell) {
    var explicit = cell.getAttribute("data-value");
    var text = (explicit === null ? cell.textContent : explicit) || "";
    var match = text
      .replace(/\u2212/g, "-")
      .replace(/,/g, "")
      .match(/-?\d*\.?\d+/);
    return match ? parseFloat(match[0]) : null;
  }

  function readChartTable(table) {
    var headCells = table.querySelectorAll("thead th");
    if (headCells.length < 2) return null;
    var series = [];
    for (var column = 1; column < headCells.length; column += 1) {
      series.push(headCells[column].textContent.trim());
    }
    var categories = [];
    table.querySelectorAll("tbody tr").forEach(function (row) {
      var cells = row.children;
      if (cells.length < 2) return;
      /* A hidden row is filtered out, so the chart matches what is listed. */
      if (row.hidden || row.hasAttribute("data-a-excluded")) return;
      var point = {
        label: cells[0].textContent.trim(),
        row: row,
        values: [],
        texts: []
      };
      series.forEach(function (name, position) {
        var cell = cells[position + 1];
        point.values.push(cell ? cellNumber(cell) : null);
        point.texts.push(cell ? cell.textContent.trim() : "");
      });
      categories.push(point);
    });
    return categories.length
      ? { series: series, categories: categories }
      : null;
  }

  function niceCeil(value) {
    if (!(value > 0)) return 1;
    var magnitude = Math.pow(10, Math.floor(Math.log(value) / Math.LN10));
    var steps = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10];
    for (var i = 0; i < steps.length; i += 1) {
      if (value <= steps[i] * magnitude) return steps[i] * magnitude;
    }
    return 10 * magnitude;
  }

  function formatTick(value) {
    var size = Math.abs(value);
    if (size >= 1000000) {
      return (value / 1000000).toFixed(size % 1000000 ? 1 : 0) + "M";
    }
    if (size >= 1000) return (value / 1000).toFixed(size % 1000 ? 1 : 0) + "k";
    return String(Math.round(value * 100) / 100);
  }

  /* Per-figure render state so a chart can be drawn more than once: the
     nodes from the previous pass are thrown away and rebuilt from whatever
     the table says now. */
  var chartState = new WeakMap();

  function chartTable(figure) {
    var details = figure.querySelector(".a-chart__data");
    return (details || figure).querySelector("table");
  }

  /* The table is the source of truth, so any change to it — a filter hiding
     rows, new rows, an edited cell — redraws the chart on its own. */
  function watchChartTable(figure, state) {
    if (state.observer) return;
    var queued = false;
    state.observer = new MutationObserver(function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () {
        queued = false;
        renderChart(figure);
      });
    });
    /* Watching the disclosure rather than the table keeps the chart live even
       when a script replaces the whole <table>. */
    state.observer.observe(state.details, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["hidden", "data-a-excluded", "data-value"]
    });
  }

  function renderChart(figure) {
    var type = figure.getAttribute("data-a-chart");
    var table = chartTable(figure);
    if (!CHART_TYPES[type] || !table) return;

    var state = chartState.get(figure);
    if (!state) {
      state = { nodes: [], details: null, observer: null, focused: null };
      chartState.set(figure, state);
    }

    /* Keeping the reader's place: a re-render restores keyboard focus to the
       same category when it survives. */
    var hadFocus = state.nodes.some(function (node) {
      return node.contains(document.activeElement);
    });
    var refocus = hadFocus ? state.focused : null;
    if (tipHost && figure.contains(tipHost)) hideTip();
    state.nodes.forEach(function (node) {
      if (node.parentNode) node.parentNode.removeChild(node);
    });
    state.nodes = [];

    if (!state.details) {
      var source = table.closest(".a-table-scroll") || table;
      var details = document.createElement("details");
      details.className = "a-disclosure a-chart__data";
      var summary = document.createElement("summary");
      summary.textContent = "Data table";
      details.appendChild(summary);
      source.parentNode.insertBefore(details, source);
      details.appendChild(source);
      state.details = details;
    }
    watchChartTable(figure, state);

    var data = readChartTable(table);
    if (!data) {
      var empty = document.createElement("p");
      empty.className = "a-chart__empty";
      empty.textContent =
        figure.getAttribute("data-a-chart-empty") ||
        "No data for this selection.";
      figure.insertBefore(empty, state.details);
      state.nodes.push(empty);
      state.focused = null;
      return;
    }

    var stacked = type === "stacked-bar";
    var isLine = type === "line";
    var height = parseFloat(figure.getAttribute("data-a-chart-height")) || 220;
    var unit = figure.getAttribute("data-a-chart-unit") || "";
    var tickUnit = unit.length <= 2 ? unit : "";
    var pad = { top: 14, right: 14, bottom: 30, left: 46 };
    var plotWidth = CHART_WIDTH - pad.left - pad.right;
    var plotHeight = height - pad.top - pad.bottom;
    var bandWidth = plotWidth / data.categories.length;

    var high = 0;
    var low = 0;
    data.categories.forEach(function (point) {
      var sum = 0;
      point.values.forEach(function (value) {
        if (value === null) return;
        sum += value > 0 ? value : 0;
        low = Math.min(low, value);
        if (!stacked) high = Math.max(high, value);
      });
      if (stacked) high = Math.max(high, sum);
    });
    var declaredMax = parseFloat(figure.getAttribute("data-a-chart-max"));
    var maxY = isFinite(declaredMax) ? declaredMax : niceCeil(high);
    var minY = low < 0 ? -niceCeil(-low) : 0;
    var span = maxY - minY || 1;

    var scaleY = function (value) {
      return pad.top + ((maxY - value) / span) * plotHeight;
    };
    var centerX = function (index) {
      return pad.left + bandWidth * (index + 0.5);
    };
    var describe = function (index) {
      var point = data.categories[index];
      return (
        point.label +
        ": " +
        data.series
          .map(function (name, position) {
            return name + " " + (point.texts[position] || "no value");
          })
          .join(", ")
      );
    };

    var caption = figure.querySelector("figcaption");
    var svg = svgNode("svg", {
      class: "a-chart",
      viewBox: "0 0 " + CHART_WIDTH + " " + height,
      role: "group",
      "aria-label":
        (figure.getAttribute("data-a-chart-label") ||
          (caption ? caption.textContent.trim() : "Chart")) +
        ". Use the arrow keys to read each value."
    });

    var grid = svgNode("g", { class: "a-chart__grid" });
    var axis = svgNode("g", { class: "a-chart__axis" });
    for (var tick = 0; tick <= 4; tick += 1) {
      var value = minY + (span * tick) / 4;
      var y = scaleY(value);
      grid.appendChild(
        svgNode("line", {
          x1: pad.left,
          y1: y,
          x2: CHART_WIDTH - pad.right,
          y2: y
        })
      );
      var tickLabel = svgNode("text", {
        x: pad.left - 8,
        y: y + 3.5,
        "text-anchor": "end"
      });
      tickLabel.textContent = formatTick(value) + tickUnit;
      axis.appendChild(tickLabel);
    }

    var labelStep = Math.ceil(data.categories.length / 8);
    data.categories.forEach(function (point, index) {
      if (index % labelStep) return;
      var text = svgNode("text", {
        x: centerX(index),
        y: height - 10,
        "text-anchor": "middle"
      });
      text.textContent = point.label;
      axis.appendChild(text);
    });

    var plot = svgNode("g", { class: "a-chart__plot" });
    /* Past ~30 points a marker per category reads as a scatter plot instead
       of a line, so dense series drop to a bare stroke and only the active
       point is drawn (CSS gives it a radius again). */
    var pointRadius = data.categories.length > 30 ? 0 : 2.75;
    if (isLine) {
      data.series.forEach(function (name, position) {
        /* A missing value breaks the line rather than bridging the gap. */
        var segments = [[]];
        data.categories.forEach(function (point, index) {
          var value = point.values[position];
          if (value === null) {
            if (segments[segments.length - 1].length) segments.push([]);
            return;
          }
          segments[segments.length - 1].push(
            centerX(index) + "," + scaleY(value)
          );
          plot.appendChild(
            svgNode("circle", {
              class: "a-chart__point a-series-" + (position + 1),
              cx: centerX(index),
              cy: scaleY(value),
              r: pointRadius,
              "data-a-index": index
            })
          );
        });
        segments.forEach(function (coordinates) {
          if (!coordinates.length) return;
          plot.insertBefore(
            svgNode("polyline", {
              class: "a-chart__series a-series-" + (position + 1),
              points: coordinates.join(" ")
            }),
            plot.firstChild
          );
        });
      });
    } else {
      var inset = bandWidth * 0.18;
      var slot = (bandWidth - inset * 2) / (stacked ? 1 : data.series.length);
      var baseline = scaleY(Math.max(minY, 0));
      data.categories.forEach(function (point, index) {
        var stackTop = 0;
        data.series.forEach(function (name, position) {
          var value = point.values[position];
          if (value === null) return;
          var from = baseline;
          var to;
          if (stacked) {
            from = scaleY(stackTop);
            stackTop += value;
            to = scaleY(stackTop);
          } else {
            to = scaleY(value);
          }
          plot.appendChild(
            svgNode("rect", {
              class: "a-chart__bar a-series-" + (position + 1),
              x:
                pad.left +
                bandWidth * index +
                inset +
                slot * (stacked ? 0 : position),
              y: Math.min(from, to),
              width: Math.max(1, slot - 2),
              height: Math.max(1, Math.abs(to - from)),
              rx: 2,
              "data-a-index": index
            })
          );
        });
      });
    }

    var crosshair = svgNode("line", {
      class: "a-chart__crosshair",
      x1: pad.left,
      x2: pad.left,
      y1: pad.top,
      y2: pad.top + plotHeight,
      hidden: "hidden"
    });

    var overlay = svgNode("g", { class: "a-chart__bands" });
    var bands = data.categories.map(function (point, index) {
      var band = svgNode("rect", {
        class: "a-chart__band",
        x: pad.left + bandWidth * index,
        y: pad.top,
        width: bandWidth,
        height: plotHeight,
        tabindex: index === 0 ? 0 : -1,
        role: "img",
        "aria-label": describe(index)
      });
      overlay.appendChild(band);
      return band;
    });

    svg.appendChild(grid);
    svg.appendChild(axis);
    svg.appendChild(plot);
    svg.appendChild(crosshair);
    svg.appendChild(overlay);

    figure.insertBefore(svg, state.details);
    state.nodes.push(svg);

    if (data.series.length > 1) {
      var legend = document.createElement("ul");
      legend.className = "a-legend";
      data.series.forEach(function (name, position) {
        var item = document.createElement("li");
        item.className = "a-series-" + (position + 1);
        var swatch = document.createElement("span");
        swatch.className = "a-legend__swatch";
        item.appendChild(swatch);
        item.appendChild(document.createTextNode(name));
        legend.appendChild(item);
      });
      figure.insertBefore(legend, state.details);
      state.nodes.push(legend);
    }

    var readout = document.createElement("p");
    readout.className = "a-visually-hidden";
    readout.setAttribute("aria-live", "polite");
    figure.appendChild(readout);
    state.nodes.push(readout);

    var clear = function () {
      bands.forEach(function (band) {
        band.removeAttribute("data-a-active");
      });
      plot.querySelectorAll("[data-a-index]").forEach(function (mark) {
        mark.removeAttribute("data-a-active");
      });
      crosshair.setAttribute("hidden", "hidden");
      readout.textContent = "";
    };

    var activate = function (index, pointer) {
      if (index < 0 || index >= bands.length) return;
      clear();
      bands[index].setAttribute("data-a-active", "true");
      plot
        .querySelectorAll('[data-a-index="' + index + '"]')
        .forEach(function (mark) {
          mark.setAttribute("data-a-active", "true");
        });
      if (isLine) {
        crosshair.setAttribute("x1", centerX(index));
        crosshair.setAttribute("x2", centerX(index));
        crosshair.removeAttribute("hidden");
      }
      readout.textContent = describe(index);
      showTip(
        {
          title: data.categories[index].label,
          rows: data.series.map(function (name, position) {
            return {
              name: name,
              value: data.categories[index].texts[position],
              series: position + 1
            };
          })
        },
        bands[index],
        bands[index].getBoundingClientRect(),
        pointer,
        clear
      );
    };

    /* -1 outside the plot area, so the axis and margins read as no category. */
    var indexAt = function (clientX) {
      var box = svg.getBoundingClientRect();
      if (!box.width) return -1;
      var local = ((clientX - box.left) / box.width) * CHART_WIDTH;
      if (local < pad.left || local > pad.left + plotWidth) return -1;
      var index = Math.floor((local - pad.left) / bandWidth);
      return Math.max(0, Math.min(data.categories.length - 1, index));
    };

    svg.addEventListener("pointermove", function (event) {
      if (event.pointerType === "touch") return;
      var index = indexAt(event.clientX);
      if (index === -1) {
        if (bands.indexOf(document.activeElement) === -1) hideTip();
        return;
      }
      activate(index, { x: event.clientX, y: event.clientY });
    });

    svg.addEventListener("pointerdown", function (event) {
      if (event.pointerType !== "touch") return;
      activate(indexAt(event.clientX), null);
    });

    /* Touch leaves as soon as the finger lifts, so a tap keeps its readout. */
    svg.addEventListener("pointerleave", function (event) {
      if (event.pointerType === "touch") return;
      if (bands.indexOf(document.activeElement) === -1) hideTip();
    });

    bands.forEach(function (band, index) {
      band.addEventListener("focus", function () {
        state.focused = {
          index: index,
          row: data.categories[index].row,
          label: data.categories[index].label
        };
        activate(index, null);
      });
      band.addEventListener("blur", function () {
        if (tipHost === band) hideTip();
      });
    });

    svg.addEventListener("keydown", function (event) {
      var current = bands.indexOf(document.activeElement);
      if (current === -1) return;
      var next = current;
      if (event.key === "ArrowRight") next = current + 1;
      else if (event.key === "ArrowLeft") next = current - 1;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = bands.length - 1;
      else return;
      event.preventDefault();
      next = Math.max(0, Math.min(bands.length - 1, next));
      bands.forEach(function (band, position) {
        band.setAttribute("tabindex", position === next ? "0" : "-1");
      });
      bands[next].focus();
    });

    if (refocus) {
      /* The same row, not the same slot: filtering rows above the reader's
         position must not move them onto a different bar. */
      var target = data.categories.findIndex(function (category) {
        return category.row === refocus.row;
      });
      /* Rows rebuilt wholesale lose their identity, so fall back to the label
         and then to the old slot. */
      if (target === -1) {
        target = data.categories.findIndex(function (category) {
          return category.label === refocus.label;
        });
      }
      if (target === -1) target = Math.min(refocus.index, bands.length - 1);
      bands.forEach(function (band, position) {
        band.setAttribute("tabindex", position === target ? "0" : "-1");
      });
      bands[target].focus();
    }
  }

  function renderCharts(target) {
    if (target === undefined || target === null) {
      document.querySelectorAll("[data-a-chart]").forEach(renderChart);
      return;
    }
    var scope =
      typeof target === "string" ? document.querySelector(target) : target;
    if (!scope) return;
    if (scope.matches && scope.matches("[data-a-chart]")) renderChart(scope);
    else scope.querySelectorAll("[data-a-chart]").forEach(renderChart);
  }

  renderCharts();

  /* The only public surface of the kit: artifacts that swap or filter a
     chart's rows themselves can force a redraw, though the table observer
     above already covers ordinary DOM edits. */
  window.artifactKit = window.artifactKit || {};
  window.artifactKit.renderCharts = renderCharts;

  /* Print carries the numbers, not the hover: expand every chart's data
     table before the page is rendered. */
  var printReopened = [];
  window.addEventListener("beforeprint", function () {
    hideTip();
    document.querySelectorAll(".a-chart__data").forEach(function (details) {
      if (details.open) return;
      printReopened.push(details);
      details.open = true;
    });
  });

  window.addEventListener("afterprint", function () {
    printReopened.forEach(function (details) {
      details.open = false;
    });
    printReopened = [];
  });

  /* ---------- diagram: pan, zoom, select ----------
     Pointer drag and wheel pan/zoom the viewport group; arrow keys and
     +/-/0 do the same from the keyboard so the diagram is operable without
     a pointing device. Node clicks (or Enter/Space) update the inspector. */
  document.querySelectorAll("[data-a-diagram]").forEach(function (diagram) {
    var svg = diagram.querySelector("[data-a-diagram-canvas]");
    var viewport = diagram.querySelector("[data-a-diagram-viewport]");
    if (!svg || !viewport) return;

    var view = { x: 0, y: 0, scale: 1 };
    var drag = null;

    var render = function () {
      viewport.setAttribute(
        "transform",
        "translate(" + view.x + " " + view.y + ") scale(" + view.scale + ")"
      );
    };

    var zoomBy = function (factor) {
      view.scale = Math.min(2.5, Math.max(0.5, view.scale * factor));
      render();
    };

    svg.addEventListener("pointerdown", function (event) {
      if (event.target.closest("[data-a-node]")) return;
      drag = { x: event.clientX, y: event.clientY };
      svg.setPointerCapture(event.pointerId);
    });

    svg.addEventListener("pointermove", function (event) {
      if (!drag) return;
      view.x += event.clientX - drag.x;
      view.y += event.clientY - drag.y;
      drag = { x: event.clientX, y: event.clientY };
      render();
    });

    var endDrag = function () {
      drag = null;
    };
    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", endDrag);

    svg.addEventListener(
      "wheel",
      function (event) {
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        zoomBy(event.deltaY < 0 ? 1.1 : 0.9);
      },
      { passive: false }
    );

    diagram.addEventListener("keydown", function (event) {
      var pan = { ArrowUp: [0, 24], ArrowDown: [0, -24], ArrowLeft: [24, 0], ArrowRight: [-24, 0] }[
        event.key
      ];
      if (pan && !event.target.closest("[data-a-node]")) {
        event.preventDefault();
        view.x += pan[0];
        view.y += pan[1];
        render();
        return;
      }
      if (event.key === "+" || event.key === "=") zoomBy(1.1);
      else if (event.key === "-") zoomBy(0.9);
      else if (event.key === "0") {
        view = { x: 0, y: 0, scale: 1 };
        render();
      }
    });

    diagram.querySelectorAll("[data-a-zoom]").forEach(function (button) {
      button.addEventListener("click", function () {
        var action = button.getAttribute("data-a-zoom");
        if (action === "in") zoomBy(1.15);
        else if (action === "out") zoomBy(0.87);
        else {
          view = { x: 0, y: 0, scale: 1 };
          render();
        }
      });
    });

    var inspector = diagram.querySelector("[data-a-inspector]");
    var select = function (node) {
      diagram.querySelectorAll("[data-a-node]").forEach(function (other) {
        other.setAttribute("aria-current", String(other === node));
      });
      if (!inspector) return;
      var title = inspector.querySelector("[data-a-inspector-title]");
      var body = inspector.querySelector("[data-a-inspector-body]");
      if (title) title.textContent = node.getAttribute("data-a-title") || "";
      if (body) body.textContent = node.getAttribute("data-a-detail") || "";
    };

    diagram.querySelectorAll("[data-a-node]").forEach(function (node) {
      node.addEventListener("click", function () {
        select(node);
      });
      node.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        select(node);
      });
    });

    render();
  });
})();
    