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
        Plotly.react("chart-wi-curve", [
            { type: "scatter", mode: "lines+markers", name: "Forecast CO₂", x: curve.change_pct, y: curve.prediction,
              line: { color: COLORS.fern, width: 2 }, marker: { size: 5 },
              hovertemplate: "Input %{x:+}%<br>Forecast %{y:,.0f} t<extra></extra>" },
            { type: "scatter", mode: "markers", name: "Your setting", x: [d.change_pct], y: [d.scenario.prediction],
              marker: { color: COLORS.clay, size: 12, symbol: "diamond" },
              hovertemplate: "Input %{x:+}%<br>Forecast %{y:,.0f} t<extra></extra>" }
        ], Object.assign({}, CHART_LAYOUT, {
            height: 300, xaxis: { title: d.input.label + " (% change)", zeroline: true },
            yaxis: { title: "Forecast CO₂ (short tons)" }, legend: { orientation: "h", y: -0.3 }
        }), PLOT_CONFIG);

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
