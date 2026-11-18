"""JSON endpoints and the page for the Data Analytics dashboard."""

from flask import Blueprint, jsonify, render_template, request

from services import analytics_service as analytics

analytics_bp = Blueprint("analytics", __name__)


def _bad_request(message):
    return jsonify({"error": message}), 400


def _filters():
    return analytics.parse_filters(request.args)


@analytics_bp.route("/dashboard")
def dashboard():
    return render_template(
        "dashboard.html",
        active="dashboard",
        hero_title="Data Analytics",
        hero_sub="Descriptive statistics, emissions charts, and CO₂ model results built from the EPA records in this database.",
        hero_size="compact",
    )


@analytics_bp.route("/api/analytics/filters")
def filter_options():
    return jsonify(analytics.filter_options())


@analytics_bp.route("/api/analytics/summary")
def summary():
    try:
        return jsonify(analytics.summary(_filters()))
    except ValueError as exc:
        return _bad_request(str(exc))


@analytics_bp.route("/api/analytics/timeseries")
def timeseries():
    try:
        return jsonify(analytics.emissions_over_time(_filters()))
    except ValueError as exc:
        return _bad_request(str(exc))


@analytics_bp.route("/api/analytics/top")
def top():
    try:
        limit = min(max(int(request.args.get("limit", 10)), 1), 50)
        return jsonify(analytics.top_emitters(
            _filters(),
            metric=request.args.get("metric", "co2_mass"),
            limit=limit,
            group_by=request.args.get("group_by", "facility"),
        ))
    except ValueError as exc:
        return _bad_request(str(exc))


@analytics_bp.route("/api/analytics/scatter")
def scatter():
    try:
        return jsonify(analytics.heat_vs_co2(_filters()))
    except ValueError as exc:
        return _bad_request(str(exc))


@analytics_bp.route("/api/ml/metrics")
def ml_metrics():
    from services import ml_service  # loads scikit-learn, so only when the dashboard asks for it
    state = (request.args.get("state") or "").strip().upper() or None
    run = ml_service.latest_metrics(state)
    if run is None:
        trained = ml_service.trained_states()
        reason = (f"No model has been trained for {state} yet. Run `python train_model.py --state {state}`."
                  if state and trained else
                  "No model has been trained yet. Run `python train_model.py` to create one per state.")
        return jsonify({"available": False, "reason": reason, "states_trained": trained})
    run["available"] = True
    return jsonify(run)


@analytics_bp.route("/api/ml/predict", methods=["POST"])
def ml_predict():
    payload = request.get_json(silent=True) or {}
    records = payload.get("records")
    state = str(payload.get("state") or "").strip().upper()
    if not isinstance(records, list) or not records or not state:
        return _bad_request(
            "Send JSON like {\"state\": \"KY\", \"records\": [{\"co2_lag1\": 3000, \"heat_lag1\": 30000, "
            "\"co2_lag7\": 2900, \"co2_roll7\": 3100, \"heat_roll7\": 31000, \"primary_fuel\": \"Coal\", "
            "\"date\": \"2025-06-01\"}]}")
    from services import ml_service
    try:
        return jsonify(ml_service.predict(records, state=state))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return _bad_request(str(exc))


@analytics_bp.route("/api/sensitivity/options")
def sensitivity_options():
    from services import sensitivity_service
    state = (request.args.get("state") or "").strip().upper() or None
    return jsonify(sensitivity_service.options(state))


@analytics_bp.route("/api/sensitivity")
def sensitivity():
    """What-if: scale one input of the forecast and see how the forecast CO₂ moves."""
    from services import sensitivity_service
    state = (request.args.get("state") or "").strip().upper()
    if not state:
        return _bad_request("state is required, for example ?state=KY&change_pct=20")
    try:
        return jsonify(sensitivity_service.sensitivity(
            state,
            facility_id=(request.args.get("facility_id") or "").strip() or None,
            input_key=request.args.get("input", sensitivity_service.DEFAULT_INPUT),
            change_pct=request.args.get("change_pct", 0),
            model_name=(request.args.get("model") or "").strip() or None,
        ))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return _bad_request(str(exc))
