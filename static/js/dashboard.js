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
    // the last response behind each "Download data" button, so the export matches what is on screen
    const lastData = {};
    let lastDistribution = null;

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
        lastData.summary = data;
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

    // ---------- section B2: derived indicators, distribution, correlation ----------

    function pctText(value) {
        return value === null || value === undefined ? "" : " (" + signed(value, 1) + "%)";
    }

    async function loadIndicators() {
        const data = await getJSON(withFilters("/api/analytics/indicators"));
        lastData.indicators = data;
        const tbody = document.querySelector("#ind-table tbody");
        tbody.innerHTML = "";
        (data.by_year || []).forEach(function (r) {
            const tr = document.createElement("tr");
            [r.group, fmtBig(r.co2_total),
             r.co2_total_change === undefined ? "–" : signed(r.co2_total_change, 0) + pctText(r.co2_total_change_pct),
             fmt(r.co2_intensity, 3), fmt(r.so2_intensity, 3), fmt(r.nox_intensity, 3), fmt(r.heat_rate, 2),
             r.heat_rate_change === undefined ? "–" : signed(r.heat_rate_change, 2) + pctText(r.heat_rate_change_pct)
            ].forEach(function (text, i) {
                const td = document.createElement("td");
                td.textContent = text;
                if (i > 0) td.className = "text-end";
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        if (!tbody.children.length) tbody.innerHTML = '<tr><td colspan="8" class="text-secondary">No records match these filters.</td></tr>';
        setText("ind-note", data.note || "");
        renderIndicatorChart();
    }

    function renderIndicatorChart() {
        const data = lastData.indicators;
        if (!data) return;
        const metric = document.getElementById("ind-metric").value;
        const meta = data.indicators[metric];
        const rows = (data.by_state || []).filter(function (r) { return r[metric] !== null; });
        if (!rows.length) {
            plotEmpty("chart-ind-state", "No records with gross load for this selection, so the ratio is undefined.");
            return;
        }
        Plotly.react("chart-ind-state", [{
            type: "bar", x: rows.map(function (r) { return r.group; }), y: rows.map(function (r) { return r[metric]; }),
            marker: { color: COLORS.fern },
            customdata: rows.map(function (r) { return r.records; }),
            hovertemplate: "%{x}<br>%{y:,.3f} " + meta.unit + "<br>%{customdata:,} records<extra></extra>"
        }], Object.assign({}, CHART_LAYOUT, { xaxis: { title: "State" }, yaxis: { title: meta.label + " (" + meta.unit + ")" } }), PLOT_CONFIG);
    }

    async function loadDistribution() {
        lastDistribution = await getJSON(withFilters("/api/analytics/distribution"));
        lastData.distribution = lastDistribution;
        renderDistribution();
        const corr = lastDistribution.correlation;
        if (!corr) {
            plotEmpty("chart-corr", "Not enough records to compute correlations.");
            showMessage("msg-corr", "");
            return;
        }
        Plotly.react("chart-corr", [{
            type: "heatmap", z: corr.matrix, x: corr.labels, y: corr.labels, zmin: -1, zmax: 1,
            colorscale: [[0, COLORS.clay], [0.5, "#F4F1E4"], [1, COLORS.canopy]],
            text: corr.matrix.map(function (row) { return row.map(function (v) { return v === null ? "–" : v.toFixed(2); }); }),
            texttemplate: "%{text}", hovertemplate: "%{y} vs %{x}<br>r = %{z:.3f}<extra></extra>"
        }], Object.assign({}, CHART_LAYOUT, { margin: { l: 100, r: 20, t: 20, b: 80 } }), PLOT_CONFIG);
        showMessage("msg-corr", "Pearson correlation (r) between each pair of measures, using records that have both values. 1 means they rise together.");
    }

    function renderDistribution() {
        const d = lastDistribution;
        if (!d) return;
        const view = document.getElementById("dist-view").value;
        if (view === "hist") {
            const h = d.histogram;
            if (!h) { plotEmpty("chart-dist", "Not enough CO₂ values for a histogram."); showMessage("msg-dist", ""); return; }
            const mids = h.counts.map(function (_, i) { return Math.sqrt(h.edges[i] * h.edges[i + 1]); });
            const widths = h.counts.map(function (_, i) { return h.edges[i + 1] - h.edges[i]; });
            Plotly.react("chart-dist", [{
                type: "bar", x: mids, y: h.counts, width: widths, marker: { color: COLORS.fern, line: { color: COLORS.paper, width: 1 } },
                customdata: h.counts.map(function (_, i) { return [h.edges[i], h.edges[i + 1]]; }),
                hovertemplate: "%{customdata[0]:,.1f} to %{customdata[1]:,.1f} t<br>%{y:,} records<extra></extra>"
            }], Object.assign({}, CHART_LAYOUT, { bargap: 0, xaxis: { title: "CO₂ per record (short tons, log scale)", type: "log" }, yaxis: { title: "Records" } }), PLOT_CONFIG);
            showMessage("msg-dist", h.zero_count ? fmt(h.zero_count, 0) + " records with exactly 0 t are not shown on the log scale." : "");
        } else {
            if (!d.boxes.length) { plotEmpty("chart-dist", "Not enough CO₂ values for a box plot."); showMessage("msg-dist", ""); return; }
            Plotly.react("chart-dist", [{
                type: "box", name: "CO₂", x: d.boxes.map(function (b) { return b.group; }),
                q1: d.boxes.map(function (b) { return b.q1; }), median: d.boxes.map(function (b) { return b.median; }),
                q3: d.boxes.map(function (b) { return b.q3; }), lowerfence: d.boxes.map(function (b) { return b.low; }),
                upperfence: d.boxes.map(function (b) { return b.high; }), mean: d.boxes.map(function (b) { return b.mean; }), boxmean: true,
                marker: { color: COLORS.fern }, line: { color: COLORS.canopy }
            }], Object.assign({}, CHART_LAYOUT, { xaxis: { title: "State" }, yaxis: { title: "CO₂ per record (short tons)" }, showlegend: false }), PLOT_CONFIG);
            showMessage("msg-dist", "Box = middle half of the records (Q1 to Q3), line = median, dashed = mean. Whiskers reach the furthest value within 1.5 × IQR; " +
                fmt(d.boxes.reduce(function (s, b) { return s + b.outliers; }, 0), 0) + " records beyond them are outliers and not drawn.");
        }
    }

    // ---------- section C: forecast models ----------

    const REFERENCE_PREFIX = "Ridge + same-day";

    function fillStateSelects(states, current) {
        ["ml-state", "wi-state"].forEach(function (id) {
            const select = document.getElementById(id);
            select.innerHTML = "";
            if (!states.length) {
                const option = document.createElement("option");
                option.value = "";
                option.textContent = "No models yet";
                select.appendChild(option);
                return;
            }
            states.forEach(function (state) {
                const option = document.createElement("option");
                option.value = state;
                option.textContent = state;
                select.appendChild(option);
            });
            select.value = current || states[0];
        });
    }

    async function loadMlMetrics(stateOverride) {
        const status = document.getElementById("ml-status");
        const wanted = stateOverride !== undefined ? stateOverride : document.getElementById("ml-state").value;
        const data = await getJSON("/api/ml/metrics" + (wanted ? "?state=" + encodeURIComponent(wanted) : ""));
        fillStateSelects(data.states_trained || [], data.state || wanted);
        lastData.model = data;
        if (!data.available) {
            status.textContent = data.reason;
            ["chart-ml-compare", "chart-ml-daily", "chart-ml-pred"].forEach(function (id) {
                plotEmpty(id, "Model results are not available yet.");
            });
            document.querySelector("#ml-table tbody").innerHTML = "";
            document.getElementById("ml-details").innerHTML = "";
            return false;
        }
        status.textContent = data.state + " model, trained " + data.trained_at + ". Best by validation error: " +
            data.selected_model + ".";

        const tbody = document.querySelector("#ml-table tbody");
        tbody.innerHTML = "";
        const names = Object.keys(data.metrics);
        names.forEach(function (name) {
            const m = data.metrics[name];
            const tr = document.createElement("tr");
            if (name === data.selected_model) tr.className = "table-success";
            if (name.indexOf(REFERENCE_PREFIX) === 0) tr.className = "text-secondary fst-italic";
            const cv = m.validation ? fmt(m.validation.cv_rmse_mean, 1) : "–";
            [name, fmt(m.test.mae, 1), fmt(m.test.rmse, 1), m.test.r2 === null ? "n/a" : fmt(m.test.r2, 3), cv]
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
            "Target: CO₂ per unit per day (" + data.target_units + ")",
            "Inputs: " + data.features.join(", ") + ". State is not an input.",
            "Training: " + fmt(data.train_rows, 0) + " unit-days, " + (data.train_dates || []).join(" to "),
            "Testing: " + fmt(data.test_rows, 0) + " unit-days, " + (data.test_dates || []).join(" to ") + " (the latest days)",
            "Split: " + data.split_method
        ].forEach(function (line) {
            const p = document.createElement("div");
            p.textContent = line;
            details.appendChild(p);
        });
        if (data.notes) {
            const p = document.createElement("div");
            p.className = "text-secondary mt-1";
            p.textContent = data.notes;
            details.appendChild(p);
        }

        const labelNames = names.map(function (n) { return n.length > 24 ? n.slice(0, 22) + "…" : n; });
        Plotly.react("chart-ml-compare", [
            { type: "bar", name: "MAE", x: labelNames, y: names.map(function (n) { return data.metrics[n].test.mae; }), marker: { color: COLORS.mango },
              customdata: names, hovertemplate: "%{customdata}<br>MAE %{y:,.1f}<extra></extra>" },
            { type: "bar", name: "RMSE", x: labelNames, y: names.map(function (n) { return data.metrics[n].test.rmse; }), marker: { color: COLORS.fern },
              customdata: names, hovertemplate: "%{customdata}<br>RMSE %{y:,.1f}<extra></extra>" }
        ], Object.assign({}, CHART_LAYOUT, {
            height: 300, barmode: "group", margin: { l: 60, r: 20, t: 20, b: 90 },
            yaxis: { title: "Error on test days (short tons), lower is better" },
            legend: { orientation: "h", y: -0.4 }
        }), PLOT_CONFIG);

        const daily = data.daily || [];
        if (!daily.length) {
            plotEmpty("chart-ml-daily", "No daily test results were saved.");
        } else {
            Plotly.react("chart-ml-daily", [
                { type: "scatter", mode: "lines", name: "Actual", x: daily.map(function (d) { return d.date; }),
                  y: daily.map(function (d) { return d.actual; }), line: { color: COLORS.canopy, width: 2 } },
                { type: "scatter", mode: "lines", name: "Forecast (" + data.selected_model + ")", x: daily.map(function (d) { return d.date; }),
                  y: daily.map(function (d) { return d.predicted; }), line: { color: COLORS.mango, width: 2, dash: "dot" } }
            ], Object.assign({}, CHART_LAYOUT, {
                height: 280, xaxis: { title: "Test day" }, yaxis: { title: "All units in " + data.state + " (short tons CO₂)" },
                legend: { orientation: "h", y: -0.3 }
            }), PLOT_CONFIG);
        }
        showMessage("msg-ml-daily", "Each day adds up every unit that had a usable forecast. These are the latest days, which were not used to train.");

        const preds = data.predictions || [];
        if (!preds.length) {
            plotEmpty("chart-ml-pred", "No test predictions were saved.");
            return true;
        }
        const lo = Math.min.apply(null, preds.map(function (p) { return Math.min(p.actual, p.predicted); }));
        const hi = Math.max.apply(null, preds.map(function (p) { return Math.max(p.actual, p.predicted); }));
        Plotly.react("chart-ml-pred", [
            {
                type: "scattergl", mode: "markers", name: "Unit-days",
                x: preds.map(function (p) { return p.actual; }),
                y: preds.map(function (p) { return p.predicted; }),
                text: preds.map(function (p) { return "Facility " + p.facility_id + ", unit " + p.unit_id + ", " + p.date; }),
                marker: { color: COLORS.canopy, size: 5, opacity: 0.5 },
                hovertemplate: "%{text}<br>Actual %{x:,.0f}<br>Forecast %{y:,.0f}<extra></extra>"
            },
            {
                type: "scatter", mode: "lines", name: "Perfect forecast",
                x: [lo, hi], y: [lo, hi], line: { color: COLORS.clay, dash: "dash" }, hoverinfo: "skip"
            }
        ], Object.assign({}, CHART_LAYOUT, {
            height: 280,
            xaxis: { title: "Actual CO₂ (short tons)" }, yaxis: { title: "Forecast CO₂ (short tons)" },
            legend: { orientation: "h", y: -0.3 }
        }), PLOT_CONFIG);
        showMessage("msg-ml-pred", "A sample of " + fmt(preds.length, 0) + " of " + fmt(data.predictions_total, 0) +
            " test unit-days. Points on the dashed line would be perfect forecasts.");
        return true;
    }

    // ---------- section D: what-if sensitivity ----------

    let whatIfTicket = 0;
    let whatIfTimer = null;

    function fillPlainSelect(id, items, valueOf, labelOf, keep) {
        const select = document.getElementById(id);
        const previous = keep ? select.value : "";
        const first = id === "wi-facility" ? select.options[0] : null;
        select.innerHTML = "";
        if (first) select.appendChild(first);
        items.forEach(function (item) {
            const option = document.createElement("option");
            option.value = valueOf(item);
            option.textContent = labelOf(item);
            select.appendChild(option);
        });
        if (previous && Array.prototype.some.call(select.options, function (o) { return o.value === previous; })) {
            select.value = previous;
        }
    }

    async function loadWhatIfOptions() {
        const state = document.getElementById("wi-state").value;
        if (!state) return false;
        const data = await getJSON("/api/sensitivity/options?state=" + encodeURIComponent(state));
        fillPlainSelect("wi-facility", data.facilities || [],
            function (f) { return f.id; }, function (f) { return f.name + " (" + f.id + ")"; }, false);
        fillPlainSelect("wi-input", data.inputs || [],
            function (i) { return i.key; }, function (i) { return i.label; }, true);
        fillPlainSelect("wi-model", (data.models || []).map(function (m) { return { name: m }; }),
            function (m) { return m.name; }, function (m) { return m.name + (m.name === data.default_model ? " (best)" : ""); }, false);
        if (data.default_model) document.getElementById("wi-model").value = data.default_model;
        return true;
    }

    function signed(value, digits) {
        if (value === null || value === undefined) return "–";
        return (value > 0 ? "+" : "") + fmt(value, digits);
    }

    function updateSliderLabel() {
        const v = Number(document.getElementById("wi-slider").value);
        setText("wi-slider-label", (v > 0 ? "+" : "") + v + "%");
    }

    async function loadWhatIf() {
        const ticket = ++whatIfTicket;
        const state = document.getElementById("wi-state").value;
        const warnings = document.getElementById("wi-warnings");
        if (!state) {
            plotEmpty("chart-wi-curve", "Train a model first (python train_model.py).");
            plotEmpty("chart-wi-tornado", "Train a model first (python train_model.py).");
            return;
        }
        const params = new URLSearchParams({
            state: state,
            input: document.getElementById("wi-input").value || "level",
            change_pct: document.getElementById("wi-slider").value
        });
        const facility = document.getElementById("wi-facility").value;
        const model = document.getElementById("wi-model").value;
        if (facility) params.set("facility_id", facility);
        if (model) params.set("model", model);

        let d;
        try {
            d = await getJSON("/api/sensitivity?" + params.toString());
        } catch (err) {
            if (ticket !== whatIfTicket) return;
            warnings.innerHTML = "";
            const li = document.createElement("li");
            li.textContent = err.message;
            warnings.appendChild(li);
            plotEmpty("chart-wi-curve", "No what-if result for this selection.");
            plotEmpty("chart-wi-tornado", "No what-if result for this selection.");
            return;
        }
        if (ticket !== whatIfTicket) return; // the slider moved again; ignore this answer
        lastData.whatif = d;

        setText("wi-base", fmt(d.baseline.prediction, 0) + " t");
        setText("wi-scenario", fmt(d.scenario.prediction, 0) + " t");
        setText("wi-change", signed(d.scenario.change, 0) + " t" +
            (d.scenario.change_pct === null ? "" : " (" + signed(d.scenario.change_pct, 1) + "%)"));
        setText("wi-sens", d.sensitivity.per_one_percent === null ? "–" : fmt(d.sensitivity.per_one_percent, 2) + "% per 1%");
        const inputs = d.baseline.inputs;
        setText("wi-basis", "Forecast for " + d.baseline.forecast_for + ". Typical values: " + d.baseline.based_on +
            ". Yesterday's CO₂ " + fmt(inputs.co2_lag1, 0) + " t, yesterday's heat input " + fmt(inputs.heat_lag1, 0) +
            " mmBtu, fuel " + (inputs.primary_fuel || "unknown") + ". Model: " + d.model + ".");
        warnings.innerHTML = "";
        d.warnings.forEach(function (w) {
            const li = document.createElement("li");
            li.textContent = w;
            warnings.appendChild(li);
        });

        const curve = d.curve;
        const firstColumn = d.input.columns[0];
        const inputValues = (curve.input_values || {})[firstColumn] || [];
        const outside = curve.outside_range || [];
        const base = d.baseline.prediction;
        // shade the parts of the slider range that go outside what the model trained on
        const shapes = [];
        curve.change_pct.forEach(function (step, i) {
            if (outside[i]) shapes.push({ type: "rect", xref: "x", yref: "paper", x0: step - 2.5, x1: step + 2.5, y0: 0, y1: 1,
                                          fillcolor: COLORS.clay, opacity: 0.12, line: { width: 0 } });
        });
        shapes.push({ type: "line", xref: "x", yref: "paper", x0: 0, x1: 0, y0: 0, y1: 1, line: { color: COLORS.ink, dash: "dot", width: 1 } });
        if (base !== null) shapes.push({ type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: base, y1: base, line: { color: COLORS.ink, dash: "dot", width: 1 } });
        const hover = "Input %{x:+}% (%{customdata[0]:,.0f})<br>Forecast %{y:,.0f} t<br>Change %{customdata[1]:+,.0f} t (%{customdata[2]:+.1f}%)<extra></extra>";
        function custom(step, value, i) {
            return [inputValues[i], value === null || base === null ? 0 : value - base, value === null || !base ? 0 : (value - base) / base * 100];
        }
        Plotly.react("chart-wi-curve", [
            { type: "scatter", mode: "lines+markers", name: "Forecast CO₂", x: curve.change_pct, y: curve.prediction,
              line: { color: COLORS.fern, width: 2 },
              marker: { size: 6, color: outside.map(function (o) { return o ? COLORS.clay : COLORS.fern; }) },
              customdata: curve.change_pct.map(function (s, i) { return custom(s, curve.prediction[i], i); }),
              hovertemplate: hover },
            { type: "scatter", mode: "markers", name: "Baseline", x: [0], y: [base],
              marker: { color: COLORS.ink, size: 11, symbol: "circle-open", line: { width: 2 } },
              hovertemplate: "Baseline<br>Forecast %{y:,.0f} t<extra></extra>" },
            { type: "scatter", mode: "markers", name: "Your setting", x: [d.change_pct], y: [d.scenario.prediction],
              marker: { color: COLORS.mango, size: 12, symbol: "diamond" },
              hovertemplate: "Input %{x:+}%<br>Forecast %{y:,.0f} t<extra></extra>" }
        ], Object.assign({}, CHART_LAYOUT, {
            height: 300, shapes: shapes, xaxis: { title: d.input.label + " (% change)", zeroline: false },
            yaxis: { title: "Forecast CO₂ (short tons)" }, legend: { orientation: "h", y: -0.3 }
        }), PLOT_CONFIG);
        if (outside.some(Boolean)) {
            const li = document.createElement("li");
            li.textContent = "Shaded red parts of the curve use input values outside the range the model trained on.";
            warnings.appendChild(li);
        }
        renderScenarios(d);

        const rows = d.tornado.rows.slice().reverse();
        Plotly.react("chart-wi-tornado", [
            { type: "bar", orientation: "h", name: "Input −" + d.tornado.step_pct + "%",
              y: rows.map(function (r) { return r.label; }), x: rows.map(function (r) { return r.down_pct; }),
              marker: { color: COLORS.mango }, hovertemplate: "%{y}<br>%{x:+.1f}% forecast<extra></extra>" },
            { type: "bar", orientation: "h", name: "Input +" + d.tornado.step_pct + "%",
              y: rows.map(function (r) { return r.label; }), x: rows.map(function (r) { return r.up_pct; }),
              marker: { color: COLORS.canopy }, hovertemplate: "%{y}<br>%{x:+.1f}% forecast<extra></extra>" }
        ], Object.assign({}, CHART_LAYOUT, {
            height: 300, barmode: "group", margin: { l: 150, r: 20, t: 20, b: 60 },
            xaxis: { title: "Change in forecast CO₂ (%)", zeroline: true }, legend: { orientation: "h", y: -0.3 }
        }), PLOT_CONFIG);
        showMessage("msg-wi-tornado", "Each input is moved by ±" + d.tornado.step_pct +
            "% on its own. The longer the bar, the more the forecast depends on that input.");
    }

    function renderScenarios(d) {
        const rows = d.scenarios || [];
        if (!rows.length) { plotEmpty("chart-wi-scenarios", "No scenarios."); return; }
        Plotly.react("chart-wi-scenarios", [{
            type: "bar", x: rows.map(function (s) { return s.label; }), y: rows.map(function (s) { return s.prediction; }),
            marker: { color: rows.map(function (s) { return s.key === "baseline" ? COLORS.ink : (s.outside_range.length ? COLORS.clay : COLORS.fern); }) },
            customdata: rows.map(function (s) { return [s.description, s.change || 0, s.change_pct || 0]; }),
            hovertemplate: "<b>%{x}</b><br>%{customdata[0]}<br>Forecast %{y:,.0f} t<br>Change %{customdata[1]:+,.0f} t (%{customdata[2]:+.1f}%)<extra></extra>"
        }], Object.assign({}, CHART_LAYOUT, {
            height: 300, margin: { l: 60, r: 20, t: 20, b: 90 },
            shapes: d.baseline.prediction === null ? [] : [{ type: "line", xref: "paper", yref: "y", x0: 0, x1: 1,
                y0: d.baseline.prediction, y1: d.baseline.prediction, line: { color: COLORS.ink, dash: "dot", width: 1 } }],
            yaxis: { title: "Forecast CO₂ (short tons)" }
        }), PLOT_CONFIG);
        const tbody = document.querySelector("#wi-scen-table tbody");
        tbody.innerHTML = "";
        rows.forEach(function (s) {
            const tr = document.createElement("tr");
            if (s.outside_range.length) tr.className = "text-danger";
            const name = document.createElement("td");
            name.textContent = s.label + (s.outside_range.length ? " (outside training range)" : "");
            name.title = s.description;
            tr.appendChild(name);
            [fmt(s.prediction, 0), s.key === "baseline" ? "–" : signed(s.change, 0), s.key === "baseline" ? "–" : signed(s.change_pct, 1) + "%"]
                .forEach(function (text) {
                    const td = document.createElement("td");
                    td.className = "text-end";
                    td.textContent = text;
                    tr.appendChild(td);
                });
            tbody.appendChild(tr);
        });
    }

    function scheduleWhatIf() {
        updateSliderLabel();
        clearTimeout(whatIfTimer);
        whatIfTimer = setTimeout(loadWhatIf, 180);
    }

    async function changeModelState(state) {
        fillStateSelects(
            Array.prototype.map.call(document.getElementById("ml-state").options, function (o) { return o.value; }).filter(Boolean),
            state);
        await loadMlMetrics(state);
        if (await loadWhatIfOptions()) await loadWhatIf();
    }

    // ---------- orchestration ----------

    async function refreshAll() {
        const ticket = ++requestCounter;
        setText("filter-status", "Updating…");
        hideAlert();
        // keep the filters in the address bar so a view can be bookmarked or shared and reopens the same way
        const query = filterQuery();
        history.replaceState(null, "", location.pathname + (query ? "?" + query : ""));
        const jobs = [loadSummary(), loadTimeseries(), loadTopEmitters(), loadScatter(), loadIndicators(), loadDistribution()];
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
        document.querySelectorAll(".data-btn").forEach(function (button) {
            button.addEventListener("click", function () {
                const data = lastData[button.dataset.key];
                if (!data) {
                    showAlert("Nothing to download yet for this section.");
                    return;
                }
                const filters = {};
                new URLSearchParams(filterQuery()).forEach(function (v, k) { filters[k] = v; });
                // metadata so the file can be understood and reproduced later
                const metadata = {
                    exported_at: new Date().toISOString(),
                    application: "epaData Phase 2 dashboard",
                    source_endpoint_section: button.dataset.key,
                    page_url: location.href,
                    dashboard_filters: filters,
                    units: "Masses in short tons unless a field says otherwise; heat input in mmBtu; gross load in MWh.",
                    indicator_definitions: {
                        co2_intensity: "CO₂ mass / gross load (short tons per MWh)",
                        so2_intensity: "SO₂ mass × 2000 / gross load (lb per MWh)",
                        nox_intensity: "NOₓ mass × 2000 / gross load (lb per MWh)",
                        heat_rate: "heat input / gross load (mmBtu per MWh)"
                    }
                };
                if (button.dataset.key === "model" || button.dataset.key === "whatif") {
                    const m = lastData.model || {};
                    metadata.model = { state: m.state, selected_model: m.selected_model, features: m.features,
                                       train_dates: m.train_dates, test_dates: m.test_dates, split_method: m.split_method,
                                       trained_at: m.trained_at };
                }
                const blob = new Blob([JSON.stringify({ metadata: metadata, data: data }, null, 2)], { type: "application/json" });
                const link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = button.dataset.name + ".json";
                document.body.appendChild(link);
                link.click();
                link.remove();
                setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
            });
        });
    }

    function applyUrlFilters() {
        const params = new URLSearchParams(location.search);
        const map = { year: "f-year", state: "f-state", fuel: "f-fuel", dataset_id: "f-dataset", facility_id: "f-facility" };
        Object.keys(map).forEach(function (key) {
            const value = params.get(key);
            const select = document.getElementById(map[key]);
            if (value && Array.prototype.some.call(select.options, function (o) { return o.value === value; })) select.value = value;
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
        document.getElementById("ind-metric").addEventListener("change", renderIndicatorChart);
        document.getElementById("dist-view").addEventListener("change", renderDistribution);
        loadFilterOptions().then(function () { applyUrlFilters(); return refreshAll(); });
        document.getElementById("ml-state").addEventListener("change", function (e) { changeModelState(e.target.value); });
        document.getElementById("wi-state").addEventListener("change", function (e) { changeModelState(e.target.value); });
        ["wi-facility", "wi-input", "wi-model"].forEach(function (id) {
            document.getElementById(id).addEventListener("change", loadWhatIf);
        });
        document.getElementById("wi-slider").addEventListener("input", scheduleWhatIf);
        updateSliderLabel();
        loadMlMetrics().then(function (found) {
            return found ? loadWhatIfOptions().then(function (ok) { return ok ? loadWhatIf() : null; }) : null;
        }).catch(function (err) {
            document.getElementById("ml-status").textContent = "Model results could not be loaded: " + err.message;
        });
    }

    document.addEventListener("DOMContentLoaded", init);
})();
