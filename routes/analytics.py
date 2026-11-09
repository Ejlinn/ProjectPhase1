"""JSON endpoints and the page for the Data Analytics dashboard."""

from flask import Blueprint, jsonify, render_template, request

from services import analytics_service as analytics
from services import ml_service

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
    run = ml_service.latest_metrics()
    if run is None:
        return jsonify({
            "available": False,
            "reason": "No model has been trained yet. Run `python train_model.py` to create one.",
        })
    run["available"] = True
    return jsonify(run)


@analytics_bp.route("/api/ml/predict", methods=["POST"])
def ml_predict():
    payload = request.get_json(silent=True) or {}
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return _bad_request("Send JSON like {\"records\": [{\"heat_input\": 500, \"primary_fuel\": \"Coal\"}]}")
    try:
        return jsonify(ml_service.predict(records))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 409
