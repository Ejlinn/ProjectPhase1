/* Data Analytics dashboard.
 * Every chart and number comes from the /api/analytics and /api/ml endpoints.
 * Nothing on the page is hard-coded data.
 */
(function () {
    "use strict";

    const COLORS = {
        canopy: "#183A2A", fern: "#3F7A44", mango: "#E9A23B", clay: "#A8432B",
        ink: "#1B2A20", line: "#C4CDA9", paper: "#FBFBF2"
    };
    const CHART_LAYOUT = {
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Atkinson Hyperlegible, system-ui, sans-serif", color: COLORS.ink, size: 12 },
        margin: { l: 60, r: 20, t: 20, b: 60 },
        height: 320
    };
    const PLOT_CONFIG = { responsive: true, displaylogo: false };

    let requestCounter = 0;

    // ---------- small helpers ----------

    function fmt(value, digits) {
        if (value === null || value === undefined || Number.isNaN(value)) return "–";
        const d = digits === undefined ? 2 : digits;
        return Number(value).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 });
    }

    function fmtBig(value) {
        if (value === null || value === undefined) return "–";
        const abs = Math.abs(value);
        if (abs >= 1e9) return (value / 1e9).toFixed(2) + " B";
        if (abs >= 1e6) return (value / 1e6).toFixed(2) + " M";
        if (abs >= 1e3) return (value / 1e3).toFixed(1) + " k";
        return fmt(value, 2);
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function showMessage(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text || "";
    }

    function showAlert(text) {
        const el = document.getElementById("page-alert");
        el.textContent = text;
        el.classList.remove("d-none");
    }

    function hideAlert() {
        document.getElementById("page-alert").classList.add("d-none");
    }

    async function getJSON(url) {
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        let body = null;
        try { body = await response.json(); } catch (e) { body = null; }
        if (!response.ok) {
            const message = body && body.error ? body.error : "Request failed (" + response.status + ")";
            throw new Error(message);
        }
        return body;
    }

    function filterQuery() {
        const params = new URLSearchParams();
        const map = { year: "f-year", state: "f-state", fuel: "f-fuel", dataset_id: "f-dataset", facility_id: "f-facility" };
        Object.keys(map).forEach(function (key) {
            const value = document.getElementById(map[key]).value;
            if (value) params.set(key, value);
        });
        return params.toString();
    }

    function withFilters(path, extra) {
        const base = filterQuery();
        const pieces = [base, extra || ""].filter(Boolean).join("&");
        return path + (pieces ? "?" + pieces : "");
    }

    function plotEmpty(id, message) {
        const node = document.getElementById(id);
        if (window.Plotly) Plotly.purge(node);
        node.innerHTML = '<div class="empty-state">' + message + "</div>";
    }

    function plotReady(id) {
        return document.getElementById(id) && window.Plotly !== undefined;
    }

    // ---------- filters ----------

    function fillSelect(id, items, valueKey, labelFn) {
        const select = document.getElementById(id);
        const keep = select.value;
        const first = select.options[0];
        select.innerHTML = "";
        select.appendChild(first);
        items.forEach(function (item) {
            const option = document.createElement("option");
            option.value = item[valueKey];
            option.textContent = labelFn(item);
            select.appendChild(option);
        });
        if (keep && Array.from(select.options).some(function (o) { return o.value === keep; })) {
            select.value = keep;
        }
    }

    async function loadFilterOptions() {
        try {
            const options = await getJSON("/api/analytics/filters");
            fillSelect("f-year", options.years.map(function (y) { return { v: y }; }), "v", function (i) { return i.v; });
            fillSelect("f-state", options.states.map(function (s) { return { v: s }; }), "v", function (i) { return i.v; });
            fillSelect("f-fuel", options.fuels.map(function (s) { return { v: s }; }), "v", function (i) { return i.v; });
            fillSelect("f-dataset", options.datasets, "id", function (i) { return i.label; });
            fillSelect("f-facility", options.facilities, "id", function (i) { return i.name + " (" + i.id + ")"; });
        } catch (err) {
            showAlert("Could not load filter options: " + err.message);
        }
    }

    // ---------- section A ----------

    function renderStatistics(statistics) {
        const co2 = statistics.co2_mass;
        if (co2) {
            setText("kpi-records", fmt(co2.valid_count, 0));
            setText("kpi-records-sub", "of " + fmt(co2.total_count, 0) + " rows (" + fmt(co2.missing_count, 0) + " missing)");
            setText("kpi-mean", fmt(co2.mean, 1));
            setText("kpi-median", fmt(co2.median, 1));
            setText("kpi-std", fmt(co2.std_dev, 1));
            setText("kpi-var", fmtBig(co2.variance));
            setText("kpi-total", fmtBig(co2.sum));
        }

        const tbody = document.querySelector("#stats-table tbody");
        tbody.innerHTML = "";
        const order = ["co2_mass", "so2_mass", "nox_mass", "heat_input", "gross_load"];
        order.forEach(function (key) {
            const s = statistics[key];
            if (!s) return;
            const tr = document.createElement("tr");
            const cells = [
                s.label, s.unit, fmt(s.valid_count, 0), fmt(s.missing_count, 0),
                fmt(s.mean), fmt(s.median), fmt(s.variance) + (s.variance !== null ? " (" + s.variance_unit + ")" : ""),
                fmt(s.std_dev), fmt(s.min), fmt(s.q1), fmt(s.q3), fmt(s.max), fmt(s.iqr)
            ];
            cells.forEach(function (text, i) {
                const td = document.createElement("td");
                td.textContent = text;
                if (i >= 2) td.className = "text-end";
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        if (!tbody.children.length) {
            tbody.innerHTML = '<tr><td colspan="13" class="text-secondary">No records match these filters.</td></tr>';
        }
    }

    function renderQuality(quality) {
        const box = document.getElementById("quality-notes");
        box.innerHTML = "";
        (quality.notes || []).forEach(function (note) {
            const p = document.createElement("div");
            p.textContent = note;
            box.appendChild(p);
        });
        if (quality.flagged_records) {
            const p = document.createElement("div");
            p.textContent = quality.flagged_records + " records were uploaded with at least one missing or defaulted value.";
            box.appendChild(p);
        }
    }

    function renderTraci(traci) {
        if (!traci || !traci.impacts) return;
        setText("traci-gw", fmtBig(traci.impacts.global_climate_kg_co2_eq));
        setText("traci-acid", fmtBig(traci.impacts.acidification_kg_so2_eq));
        const list = document.getElementById("traci-warnings");
        list.innerHTML = "";
        (traci.warnings || []).forEach(function (w) {
            const li = document.createElement("li");
            li.textContent = w;
            list.appendChild(li);
        });
    }

    async function loadSummary() {
        const data = await getJSON(withFilters("/api/analytics/summary"));
        renderStatistics(data.statistics);
        renderQuality(data.data_quality);
        renderTraci(data.traci);
    }

    // ---------- section B ----------

    async function loadTimeseries() {
        const id = "chart-timeseries";
        const data = await getJSON(withFilters("/api/analytics/timeseries"));
        const pollutant = document.getElementById("ts-pollutant").value;
        const labels = { co2: "CO₂", so2: "SO₂", nox: "NOₓ" };
        if (!data.periods || !data.periods.length) {
            plotEmpty(id, "No records match these filters.");
            showMessage("msg-timeseries", "");
            return;
        }
        if (!data.trend_available) {
            // One period only: show the single total as a bar, and say a trend is not possible
            Plotly.react(id, [{
                type: "bar",
                x: data.periods.map(function (p) { return p.period; }),
                y: data.periods.map(function (p) { return p[pollutant]; }),
                marker: { color: COLORS.fern },
                hovertemplate: "%{x}<br>%{y:,.2f} short tons<extra></extra>"
            }], Object.assign({}, CHART_LAYOUT, { yaxis: { title: labels[pollutant] + " (short tons)" } }), PLOT_CONFIG);
        } else {
            Plotly.react(id, [{
                type: "scatter", mode: "lines+markers",
                x: data.periods.map(function (p) { return p.period; }),
                y: data.periods.map(function (p) { return p[pollutant]; }),
                line: { color: COLORS.fern, width: 3 }, marker: { size: 8, color: COLORS.canopy },
                hovertemplate: "%{x}<br>%{y:,.2f} short tons<extra></extra>"
            }], Object.assign({}, CHART_LAYOUT, { yaxis: { title: labels[pollutant] + " (short tons)" } }), PLOT_CONFIG);
        }
        showMessage("msg-timeseries", data.message || "");
    }

    async function loadTopEmitters() {
        const id = "chart-top";
        const metric = document.getElementById("top-metric").value;
        const group = document.getElementById("top-group").value;
        const data = await getJSON(withFilters("/api/analytics/top", "metric=" + metric + "&group_by=" + group + "&limit=10"));
        const warn = document.getElementById("warn-top");
        warn.textContent = (data.warnings || []).join(" ");
        if (!data.items || !data.items.length) {
            plotEmpty(id, data.message || "No values available for this selection.");
            return;
        }
        const items = data.items.slice().reverse();
        Plotly.react(id, [{
            type: "bar", orientation: "h",
            y: items.map(function (i) { return i.label; }),
            x: items.map(function (i) { return i.value; }),
            marker: { color: COLORS.fern },
            hovertemplate: "%{y}<br>%{x:,.2f} " + data.unit + "<extra></extra>"
        }], Object.assign({}, CHART_LAYOUT, {
            height: 360, margin: { l: 220, r: 20, t: 20, b: 50 },
            xaxis: { title: data.label + " (" + data.unit + ")" }
        }), PLOT_CONFIG);
    }

    async function loadScatter() {
        const id = "chart-scatter";
        const data = await getJSON(withFilters("/api/analytics/scatter"));
        if (!data.points || !data.points.length) {
            plotEmpty(id, data.message || "No data for this selection.");
            setText("scatter-fit", "");
            return;
        }
        const traces = [{
            type: "scatter", mode: "markers",
            x: data.points.map(function (p) { return p.x; }),
            y: data.points.map(function (p) { return p.y; }),
            text: data.points.map(function (p) { return "Facility " + p.facility; }),
            marker: { color: COLORS.canopy, opacity: 0.6, size: 7 },
            hovertemplate: "%{text}<br>Heat input %{x:,.1f} mmBtu<br>CO₂ %{y:,.2f} short tons<extra></extra>",
            name: "Records"
        }];
        if (data.trendline) {
            traces.push({
                type: "scatter", mode: "lines",
                x: data.trendline.x, y: data.trendline.y,
                line: { color: COLORS.mango, width: 3 }, name: "Linear fit",
                hoverinfo: "skip"
            });
        }
        Plotly.react(id, traces, Object.assign({}, CHART_LAYOUT, {
            xaxis: { title: data.x_label }, yaxis: { title: data.y_label }, showlegend: true,
            legend: { orientation: "h", y: -0.25 }
        }), PLOT_CONFIG);
        if (data.trendline) {
            setText("scatter-fit", "Fit: CO₂ ≈ " + fmt(data.trendline.slope, 4) + " × heat input + " + fmt(data.trendline.intercept, 2));
        } else {
            setText("scatter-fit", "");
        }
        showMessage("msg-scatter", data.note || "");
    }

    // ---------- section C ----------

    async function loadMlMetrics() {
        const status = document.getElementById("ml-status");
        const data = await getJSON("/api/ml/metrics");
        if (!data.available) {
            status.textContent = data.reason;
            plotEmpty("chart-ml-compare", "Model results are not available yet.");
            plotEmpty("chart-ml-pred", "Model results are not available yet.");
            return;
        }
        status.textContent = "Trained " + data.trained_at + ". Selected model: " + data.selected_model + " (lowest cross-validation RMSE).";
        const tbody = document.querySelector("#ml-table tbody");
        tbody.innerHTML = "";
        const names = Object.keys(data.metrics);
        names.forEach(function (name) {
            const m = data.metrics[name];
            const tr = document.createElement("tr");
            if (name === data.selected_model) tr.className = "table-success";
            const cv = m.validation ? fmt(m.validation.cv_rmse_mean, 2) : "–";
            [name, fmt(m.test.mae, 2), fmt(m.test.rmse, 2), m.test.r2 === null ? "n/a" : fmt(m.test.r2, 3), cv]
                .forEach(function (text, i) {
                    const td = document.createElement("td");
                    td.textContent = text;
                    if (i > 0) td.className = "text-end";
                    tr.appendChild(td);
                });
            tbody.appendChild(tr);
        });

        const details = document.getElementById("ml-details");
        details.innerHTML = "";
        [
            "Target: CO₂ mass (" + data.target_units + ")",
            "Features: " + data.features.join(", "),
            "Rows: " + data.train_rows + " training / " + data.test_rows + " testing",
            "Split: " + data.split_method
        ].forEach(function (line) {
            const p = document.createElement("div");
            p.textContent = line;
            details.appendChild(p);
        });
        if (data.notes) {
            const p = document.createElement("div");
            p.className = "text-secondary";
            p.textContent = data.notes;
            details.appendChild(p);
        }

        Plotly.react("chart-ml-compare", [
            { type: "bar", name: "MAE", x: names, y: names.map(function (n) { return data.metrics[n].test.mae; }), marker: { color: COLORS.mango } },
            { type: "bar", name: "RMSE", x: names, y: names.map(function (n) { return data.metrics[n].test.rmse; }), marker: { color: COLORS.fern } }
        ], Object.assign({}, CHART_LAYOUT, {
            height: 280, barmode: "group",
            yaxis: { title: "Error (short tons), lower is better" },
            legend: { orientation: "h", y: -0.25 }
        }), PLOT_CONFIG);

        const preds = data.predictions || [];
        if (!preds.length) {
            plotEmpty("chart-ml-pred", "No test predictions were saved.");
            return;
        }
        const lo = Math.min.apply(null, preds.map(function (p) { return Math.min(p.actual, p.predicted); }));
        const hi = Math.max.apply(null, preds.map(function (p) { return Math.max(p.actual, p.predicted); }));
        Plotly.react("chart-ml-pred", [
            {
                type: "scatter", mode: "markers", name: "Test rows",
                x: preds.map(function (p) { return p.actual; }),
                y: preds.map(function (p) { return p.predicted; }),
                text: preds.map(function (p) { return "Facility " + p.facility_id; }),
                marker: { color: COLORS.canopy, size: 8, opacity: 0.7 },
                hovertemplate: "%{text}<br>Actual %{x:,.2f}<br>Predicted %{y:,.2f}<extra></extra>"
            },
            {
                type: "scatter", mode: "lines", name: "Perfect prediction",
                x: [lo, hi], y: [lo, hi], line: { color: COLORS.clay, dash: "dash" }, hoverinfo: "skip"
            }
        ], Object.assign({}, CHART_LAYOUT, {
            height: 280,
            xaxis: { title: "Actual CO₂ (short tons)" }, yaxis: { title: "Predicted CO₂ (short tons)" },
            legend: { orientation: "h", y: -0.25 }
        }), PLOT_CONFIG);
        showMessage("msg-ml-pred", "Held-out facilities only. Points on the dashed line would be perfect predictions.");
    }

    // ---------- orchestration ----------

    async function refreshAll() {
        const ticket = ++requestCounter;
        setText("filter-status", "Updating…");
        hideAlert();
        const jobs = [loadSummary(), loadTimeseries(), loadTopEmitters(), loadScatter()];
        const results = await Promise.allSettled(jobs);
        if (ticket !== requestCounter) return; // a newer request has started; ignore this one
        const failures = results.filter(function (r) { return r.status === "rejected"; });
        if (failures.length) {
            showAlert("Some sections could not load: " + failures.map(function (f) { return f.reason.message; }).join("; "));
        }
        setText("filter-status", failures.length ? "Partial results." : "Showing " + (document.getElementById("kpi-records").textContent) + " records.");
    }

    function bindExports() {
        document.querySelectorAll(".export-btn").forEach(function (button) {
            button.addEventListener("click", function () {
                const node = document.getElementById(button.dataset.target);
                if (!node || !window.Plotly || !node.data) {
                    showAlert("Nothing to export yet for this chart.");
                    return;
                }
                Plotly.downloadImage(node, { format: "png", width: 1200, height: 600, filename: button.dataset.name });
            });
        });
    }

    function init() {
        if (!window.Plotly) {
            showAlert("Plotly did not load. Check your internet connection and reload the page.");
        }
        bindExports();
        ["f-year", "f-state", "f-fuel", "f-dataset", "f-facility", "ts-pollutant", "top-metric", "top-group"]
            .forEach(function (id) {
                document.getElementById(id).addEventListener("change", refreshAll);
            });
        document.getElementById("f-reset").addEventListener("click", function () {
            ["f-year", "f-state", "f-fuel", "f-dataset", "f-facility"].forEach(function (id) {
                document.getElementById(id).value = "";
            });
            refreshAll();
        });
        loadFilterOptions().then(refreshAll);
        loadMlMetrics().catch(function (err) {
            document.getElementById("ml-status").textContent = "Model results could not be loaded: " + err.message;
        });
    }

    document.addEventListener("DOMContentLoaded", init);
})();
