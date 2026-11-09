from models import FacilityRecord, db
from services.db_migrations import ensure_schema
from tests.conftest import add_records


def _seed_facility():
    add_records([
        dict(facility_id="54", facility_name="Smith Generating Facility", state="KY", unit_id="SCT2",
             primary_fuel="Pipeline Natural Gas", co2_mass=28.9, so2_mass=0.292, nox_mass=32.55,
             heat_input=486.1, record_date="2024-06-03", record_hour=12),
        dict(facility_id="54", facility_name="Smith Generating Facility", state="KY", unit_id="SCT2",
             primary_fuel="Pipeline Natural Gas", co2_mass=None, so2_mass=0.5, nox_mass=1.0,
             heat_input=None, record_date="2024-06-03", record_hour=13),
    ])


def test_dashboard_page_loads(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "dashboard.js" in html
    assert "Data Analytics" in html


def test_navigation_and_tutorial_include_dashboard(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/dashboard"' in html
    assert 'data-step="100"' in html


def test_filter_options_endpoint(client, clean_db):
    _seed_facility()
    body = client.get("/api/analytics/filters").get_json()
    assert "KY" in body["states"]
    assert "2024" in body["years"]


def test_bad_query_parameters_return_400(client):
    assert client.get("/api/analytics/summary?year=20x4").status_code == 400
    assert client.get("/api/analytics/top?metric=bogus").status_code == 400
    assert client.get("/api/analytics/summary?dataset_id=abc").status_code == 400


def test_timeseries_scatter_and_top_endpoints_return_json(client, clean_db):
    _seed_facility()
    for url in ["/api/analytics/timeseries", "/api/analytics/scatter",
                "/api/analytics/top?metric=nox_mass&group_by=state"]:
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.is_json


def test_null_co2_is_not_shown_as_zero_in_stats(client, clean_db):
    _seed_facility()
    body = client.get("/api/analytics/summary").get_json()
    co2 = body["statistics"]["co2_mass"]
    assert co2["valid_count"] == 1
    assert co2["missing_count"] == 1
    assert co2["mean"] == 28.9


def test_existing_facility_pages_still_work(client, clean_db):
    _seed_facility()
    detail = client.get("/facility/54")
    assert detail.status_code == 200
    assert b"TRACI 2.2 Impact Summary" in detail.data
    impacts = client.get("/api/facility/54/impacts").get_json()
    assert impacts["record_count"] == 2
    assert impacts["impacts"]["global_climate_kg_co2_eq"] == 28.9 * 907.18474 * 1.0
    assert any("missing" in w.lower() for w in impacts["warnings"]) or impacts["warnings"] == []


def test_export_still_returns_csv(client, clean_db):
    _seed_facility()
    response = client.get("/export")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"


def test_schema_check_keeps_existing_rows(app, clean_db):
    _seed_facility()
    with app.app_context():
        before = db.session.query(FacilityRecord).count()
        changes = ensure_schema(db)
        after = db.session.query(FacilityRecord).count()
    assert changes == []  # the test schema already has every column
    assert before == after == 2
