"""API uctan uca testleri.

Vurgu, sozlesmenin **kararliligi** ve **durustlugu** uzerinde: cevaplar gecerli
JSON olmali (NaN/Infinity tasimamali), sentetik tarife her zaman isaretlenmeli ve
`/decide` asla ciplak bir firma adi dondurmemeli.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from desi_engine.api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


CONTAMINATION_ORDER = {
    "lines": [{"sku": "GD-001", "quantity": 1}, {"sku": "NV-002", "quantity": 1}],
    "city_plate": 65,
    "is_cod": True,
    "customer_clv_try": 4500,
    "order_id": "API-VAN-001",
}

SIMPLE_ORDER = {"lines": [{"sku": "HV-003", "quantity": 2}], "city_plate": 34}


class TestCatalog:
    def test_health_reports_synthetic_tariffs(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["carriers"] == 5
        assert body["cities"] == 81
        assert body["synthetic_tariffs"] is True

    def test_products_endpoint(self, client):
        products = client.get("/api/v1/catalog/products").json()
        assert len(products) >= 40
        assert {"sku", "name", "desi", "risk_category"} <= products[0].keys()

    def test_cities_endpoint_covers_81_provinces(self, client):
        cities = client.get("/api/v1/catalog/cities").json()
        assert len(cities) == 81
        assert {c["plate"] for c in cities} == set(range(1, 82))

    def test_carriers_endpoint_flags_synthetic_tariffs(self, client):
        carriers = client.get("/api/v1/carriers").json()
        assert len(carriers) == 5
        assert all(c["is_synthetic_tariff"] for c in carriers)


class TestPack:
    def test_returns_candidate_plans_with_3d_coordinates(self, client):
        body = client.post("/api/v1/pack", json=SIMPLE_ORDER).json()
        assert body["plans"]
        placement = body["plans"][0]["boxes"][0]["placements"][0]
        assert {"x", "y", "z", "dx", "dy", "dz"} <= placement.keys()

    def test_reports_all_three_baselines(self, client):
        baselines = client.post("/api/v1/pack", json=SIMPLE_ORDER).json()["baselines"]
        assert baselines["quoted_sum_desi"] > 0
        assert baselines["one_box_per_item_desi"] > 0
        assert baselines["volume_rule_desi"] > 0

    def test_contamination_cart_offers_a_separation_plan(self, client):
        plans = client.post("/api/v1/pack", json=CONTAMINATION_ORDER).json()["plans"]
        assert any(p["strategy"] == "sivilar_ayri" for p in plans)


class TestRate:
    def test_quotes_are_sorted_and_itemised(self, client):
        body = client.post("/api/v1/rate", json=SIMPLE_ORDER).json()
        totals = [q["total_try"] for q in body["quotes"]]
        assert totals == sorted(totals)
        assert body["quotes"][0]["lines"]

    def test_synthetic_warning_is_always_set(self, client):
        assert (
            client.post("/api/v1/rate", json=SIMPLE_ORDER).json()["synthetic_tariff_warning"]
            is True
        )

    def test_unserved_carrier_appears_with_a_reason(self, client):
        body = client.post(
            "/api/v1/rate", json={"lines": [{"sku": "HV-003"}], "city_plate": 30}
        ).json()
        assert any("Surat" in item["carrier"] for item in body["ineligible"])


class TestDecide:
    def test_returns_full_rationale_not_just_a_carrier(self, client):
        body = client.post("/api/v1/decide", json=CONTAMINATION_ORDER).json()
        assert body["selected"]["carrier"]
        assert len(body["ranked"]) >= 3
        assert body["rationale"]
        assert body["warnings"]

    def test_reports_the_cheapest_freight_override(self, client):
        body = client.post("/api/v1/decide", json=CONTAMINATION_ORDER).json()
        assert body["overrode_cheapest_freight"] is True
        assert body["cheapest_freight_carrier"] != body["selected"]["carrier"]
        assert body["savings_vs_cheapest_freight_try"] > 0

    def test_cost_lines_are_present_for_every_candidate(self, client):
        body = client.post("/api/v1/decide", json=CONTAMINATION_ORDER).json()
        assert all(candidate["cost_lines"] for candidate in body["ranked"])

    def test_response_is_strictly_valid_json(self, client):
        """`NaN` ve `Infinity` gecerli JSON degildir.

        Gorulmemis bir hucrede ham hasar orani `NaN`, uygun olmayan bir firmada
        skor `inf` olabilir. Bunlarin `null`'a cevrildigini dogruluyoruz -- aksi
        halde tarayicidaki `JSON.parse` patlar.
        """
        raw = client.post("/api/v1/decide", json=CONTAMINATION_ORDER).text
        assert "NaN" not in raw
        assert "Infinity" not in raw
        json.loads(raw)  # katı ayristirma

    def test_unknown_sku_returns_404(self, client):
        response = client.post(
            "/api/v1/decide", json={"lines": [{"sku": "YOK-999"}], "city_plate": 34}
        )
        assert response.status_code == 404

    def test_invalid_plate_is_rejected(self, client):
        response = client.post(
            "/api/v1/decide", json={"lines": [{"sku": "HV-003"}], "city_plate": 99}
        )
        assert response.status_code == 422


class TestLabel:
    def test_produces_one_label_per_parcel_with_barcode_and_zpl(self, client):
        body = client.post("/api/v1/label", json=CONTAMINATION_ORDER).json()
        assert body["labels"]
        first = body["labels"][0]
        assert first["barcode_svg"].startswith("<svg")
        assert first["zpl"].strip().startswith("^XA")
        assert first["tracking_number"] in first["zpl"]

    def test_cod_amount_only_on_first_parcel(self, client):
        labels = client.post("/api/v1/label", json=CONTAMINATION_ORDER).json()["labels"]
        assert labels[0]["cod_amount_try"] > 0
        assert all(item["cod_amount_try"] == 0 for item in labels[1:])


class TestRiskHeatmap:
    def test_returns_all_cells_with_raw_and_shrunk_rates(self, client):
        body = client.get("/api/v1/risk/heatmap").json()
        assert body["total_shipments"] > 10_000
        assert len(body["kappas"]) == 3
        assert len(body["cells"]) == 80
        assert all(cell["shrunk_rate"] > 0 for cell in body["cells"])

    def test_response_is_strictly_valid_json(self, client):
        assert "NaN" not in client.get("/api/v1/risk/heatmap").text


class TestSimulation:
    def test_run_lifecycle(self, client):
        started = client.post("/api/v1/simulate", json={"n_orders": 150, "seed": 5}).json()
        run_id = started["run_id"]
        assert started["state"] in {"pending", "running", "done"}

        # TestClient arka plan gorevlerini istek tamamlandiginda calistirir.
        body = client.get(f"/api/v1/simulate/{run_id}").json()
        assert "summaries" in body or body["state"] in {"pending", "running"}

    def test_unknown_run_returns_404(self, client):
        assert client.get("/api/v1/simulate/yok-boyle-bir-kosu").status_code == 404
