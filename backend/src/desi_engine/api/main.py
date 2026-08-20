"""FastAPI uygulamasi -- motorun HTTP yuzeyi.

Tasarim ilkesi: **hicbir uc nokta ciplak bir sonuc dondurmez.** `/decide` yalnizca
firma adi degil, tum adaylari, elenenleri, kalem kalem maliyetleri ve gerekceyi
dondurur. Sentetik tarife kullaniliyorsa her cevap bunu isaretler.

Calistirma:
    uvicorn desi_engine.api.main:app --reload
    -> http://localhost:8000/docs
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..decision.objective import ObjectiveParams
from ..decision.selector import NoEligibleCarrierError
from ..domain.models import Address, Cart, CartLine, Order
from ..engine import Engine, build_engine
from ..labels.zpl import build_labels, to_zpl
from . import mapping
from . import schemas as api

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"

#: Arayuzun gelistirme sunucusu. Uretimde ayni kokten servis edilecegi icin
#: bu listenin daralmasi beklenir.
ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

#: Simulasyon kosulari bellekte tutulur. Tek kullanicili bir demo icin yeterli;
#: cok kullanicili bir kurulumda kalici bir depoya tasinmali.
_runs: dict[str, dict[str, Any]] = {}

_engine: Engine | None = None


def get_engine() -> Engine:
    if _engine is None:  # pragma: no cover - lifespan her zaman kurar
        raise RuntimeError("Motor henuz kurulmadi")
    return _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Motoru acilista bir kez kurar.

    Hasar ve teslimat modellerinin egitimi birkac saniye suruyor; her istekte
    tekrarlamak arayuzu kullanilmaz kilardi.
    """
    global _engine
    _engine = build_engine(DEFAULT_DATA_DIR)
    # Modelleri simdi egit; ilk istegi bekletme.
    _ = _engine.selector
    yield
    _engine = None


app = FastAPI(
    title="Ozdilek Desi Motoru",
    description=(
        "Cok firmali kargo fiyatlama, sanal kutulama ve karar motoru. "
        "**Bu kurulum sentetik tarife ve sentetik gecmis veri kullanir; "
        "fiyatlar gercek sozlesme fiyatlari degildir.**"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---- yardimcilar -------------------------------------------------------------


def _build_order(engine: Engine, payload: api.OrderIn) -> Order:
    try:
        lines = [
            CartLine(product=engine.product(line.sku), quantity=line.quantity)
            for line in payload.lines
        ]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        province = engine.provinces.get(payload.city_plate)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Order(
        order_id=payload.order_id,
        cart=Cart(lines=lines),
        address=Address(
            city_plate=province.plate,
            city_name=province.name,
            region=province.region,
            is_rural=payload.is_rural,
        ),
        is_cod=payload.is_cod,
        customer_clv_try=payload.customer_clv_try,
    )


# ---- katalog -----------------------------------------------------------------


@app.get("/api/v1/health", tags=["sistem"])
def health() -> dict[str, Any]:
    engine = get_engine()
    return {
        "status": "ok",
        "carriers": len(engine.tariffs),
        "products": len(engine.products),
        "cities": len(engine.provinces),
        "synthetic_tariffs": engine.uses_synthetic_tariffs,
    }


@app.get("/api/v1/catalog/products", response_model=list[api.ProductOut], tags=["katalog"])
def list_products() -> list[api.ProductOut]:
    engine = get_engine()
    return [mapping.product_out(p) for p in engine.products.values()]


@app.get("/api/v1/catalog/cities", response_model=list[api.CityOut], tags=["katalog"])
def list_cities() -> list[api.CityOut]:
    engine = get_engine()
    return [mapping.city_out(p) for p in engine.provinces]


@app.get("/api/v1/carriers", response_model=list[api.CarrierOut], tags=["katalog"])
def list_carriers() -> list[api.CarrierOut]:
    engine = get_engine()
    return [mapping.carrier_out(t) for t in engine.tariffs]


# ---- cekirdek islemler -------------------------------------------------------


@app.post("/api/v1/pack", response_model=api.PackResponse, tags=["motor"])
def pack(payload: api.OrderIn) -> api.PackResponse:
    """Sepeti kolilere yerlestirir ve aday planlari dondurur.

    Her yerlesimin 3B koordinatlari cevapta; arayuzdeki koli gorsellestirmesi
    bunlari dogrudan kullanir.
    """
    engine = get_engine()
    order = _build_order(engine, payload)
    plans = engine.planner.candidates(order.cart)
    baselines = plans[0].baselines

    return api.PackResponse(
        baselines=api.BaselinesOut(**baselines.model_dump()),
        plans=[mapping.packing_plan_out(plan) for plan in plans],
    )


@app.post("/api/v1/rate", response_model=api.RateResponse, tags=["motor"])
def rate(payload: api.OrderIn) -> api.RateResponse:
    """Tum firmalarin nakliye teklifleri, kalem kalem dokumle."""
    engine = get_engine()
    order = _build_order(engine, payload)
    zone = engine.provinces.zone_class(order.origin_plate, order.address.city_plate)
    evaluations = engine.selector.evaluate_all(order)

    quotes = [
        api.FreightQuoteOut(
            carrier=e.carrier,
            display_name=e.display_name,
            is_synthetic_tariff=e.uses_synthetic_tariff,
            parcel_count=e.parcel_count,
            chargeable_desi=e.chargeable_desi,
            total_try=e.freight.total_try,
            subtotal_before_vat_try=e.freight.subtotal_before_vat,
            vat_try=e.freight.vat_try,
            lines=[
                api.CostLineOut(label=label, amount_try=amount)
                for label, amount in e.freight.explain_lines()
            ],
        )
        for e in sorted(evaluations, key=lambda e: e.freight_try)
        if e.eligible and e.freight
    ]

    return api.RateResponse(
        zone=zone.value,
        city_name=order.address.city_name,
        quotes=quotes,
        ineligible=[
            {"carrier": e.display_name, "reason": ", ".join(e.ineligibility_reasons)}
            for e in evaluations
            if not e.eligible
        ],
        synthetic_tariff_warning=engine.uses_synthetic_tariffs,
    )


@app.post("/api/v1/decide", response_model=api.DecisionResponse, tags=["motor"])
def decide(payload: api.OrderIn) -> api.DecisionResponse:
    """Firmayi secer ve **tam gerekce agacini** dondurur.

    Cevap asla yalnizca bir firma adi degildir: tum adaylar, elenenler ve
    gerekceleri, her adayin kalem kalem maliyeti ve en ucuz nakliyenin neden
    reddedildigi de yer alir.
    """
    engine = get_engine()
    order = _build_order(engine, payload)
    try:
        decision = engine.selector.decide(order)
    except NoEligibleCarrierError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return mapping.decision_out(decision, order.address.city_name)


@app.post("/api/v1/label", response_model=api.LabelResponse, tags=["motor"])
def label(payload: api.OrderIn) -> api.LabelResponse:
    """Karari verir ve koli basina kargo etiketi uretir (ZPL + barkod onizleme)."""
    engine = get_engine()
    order = _build_order(engine, payload)
    try:
        decision = engine.selector.decide(order)
    except NoEligibleCarrierError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    labels = build_labels(order, decision)
    return api.LabelResponse(
        order_id=order.order_id,
        carrier=decision.selected.carrier,
        labels=[
            api.LabelOut(
                tracking_number=item.tracking_number,
                carrier=item.carrier,
                carrier_display=item.carrier_display,
                parcel_index=item.parcel_index,
                parcel_count=item.parcel_count,
                box_code=item.box_code,
                chargeable_desi=item.chargeable_desi,
                recipient=f"{item.recipient_plate:02d} {item.recipient_city}",
                zone=item.zone,
                is_cod=item.is_cod,
                cod_amount_try=item.cod_amount_try,
                decision_note=item.decision_note,
                is_synthetic_tariff=item.is_synthetic_tariff,
                barcode_svg=item.barcode_svg,
                zpl=to_zpl(item),
            )
            for item in labels
        ],
    )


# ---- risk --------------------------------------------------------------------


@app.get("/api/v1/risk/heatmap", response_model=api.RiskHeatmapResponse, tags=["risk"])
def risk_heatmap() -> api.RiskHeatmapResponse:
    """Firma x bolge x kategori hasar matrisi -- ham ve shrinkage'li, yan yana."""
    engine = get_engine()
    estimator = engine.damage_estimator
    frame = estimator.heatmap_frame()

    return api.RiskHeatmapResponse(
        global_rate=estimator.global_rate,
        total_shipments=estimator.total_shipments,
        kappas=estimator.kappas,
        cells=[
            api.RiskCellOut(
                carrier=row.carrier,
                zone=row.zone,
                risk_category=row.risk_category,
                shipments=int(row.shipments),
                damages=int(row.damages),
                raw_rate=mapping._finite(row.raw_rate),
                shrunk_rate=row.shrunk_rate,
                ci_low=row.ci_low,
                ci_high=row.ci_high,
                upper_95=row.upper_95,
                prior_weight=row.prior_weight,
            )
            for row in frame.itertuples()
        ],
    )


# ---- simulasyon --------------------------------------------------------------


def _run_simulation(run_id: str, request: api.SimulationRequest) -> None:
    """Arka planda kosar. Kosu birkac dakika surebilir; istegi bekletmiyoruz."""
    from ..simulation import SimulationConfig, SimulationRunner

    _runs[run_id] |= {"state": "running", "message": "Simulasyon calisiyor"}
    try:
        engine = build_engine(
            DEFAULT_DATA_DIR,
            objective=ObjectiveParams(risk_aversion_lambda=request.risk_aversion_lambda),
        )
        result = SimulationRunner(
            engine,
            SimulationConfig(
                n_orders=request.n_orders,
                seed=request.seed,
                capacity_share=request.capacity_share,
            ),
        ).run()

        _runs[run_id] |= {
            "state": "done",
            "progress": 1.0,
            "message": "Tamamlandi",
            "result": api.SimulationResultOut(
                run_id=run_id,
                n_orders=result.n_orders,
                seed=result.seed,
                elapsed_seconds=result.elapsed_seconds,
                headline=result.headline(),
                summaries=[
                    api.PolicySummaryOut(
                        policy=s.policy_code.value,
                        label=s.label,
                        orders=s.orders,
                        cost_per_order_try=s.cost_per_order_try,
                        freight_per_order_try=s.freight_per_order_try,
                        hidden_cost_share=s.hidden_cost_share,
                        damage_rate=s.damage_rate,
                        late_rate=s.late_rate,
                        mean_delivery_days=s.mean_delivery_days,
                        mean_parcels=s.mean_parcels,
                        mean_chargeable_desi=s.mean_chargeable_desi,
                        carrier_mix=s.carrier_mix,
                    )
                    for s in result.summaries.values()
                ],
                comparisons=[
                    api.ComparisonOut(
                        baseline=c.baseline,
                        treatment=c.treatment,
                        mean_difference=c.mean_difference,
                        ci_low=c.ci_low,
                        ci_high=c.ci_high,
                        relative_saving=c.relative_saving,
                        is_significant=c.is_significant,
                        description=c.describe(),
                    )
                    for c in result.comparisons
                ],
                calibration=[
                    api.CalibrationBinOut(
                        lower=b.lower,
                        upper=b.upper,
                        count=b.count,
                        predicted_mean=b.predicted_mean,
                        observed_rate=b.observed_rate,
                    )
                    for b in result.calibration
                ],
                calibration_error=result.calibration_error,
            ),
        }
    except Exception as exc:
        _runs[run_id] |= {"state": "failed", "message": f"{type(exc).__name__}: {exc}"}


@app.post("/api/v1/simulate", response_model=api.SimulationStatus, tags=["simulasyon"])
def start_simulation(
    request: api.SimulationRequest, background_tasks: BackgroundTasks
) -> api.SimulationStatus:
    """Monte Carlo kosusunu arka planda baslatir ve bir `run_id` dondurur."""
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    _runs[run_id] = {"state": "pending", "progress": 0.0, "message": "Sirada"}
    background_tasks.add_task(_run_simulation, run_id, request)
    return api.SimulationStatus(run_id=run_id, state="pending", message="Sirada")


@app.get("/api/v1/simulate/{run_id}", tags=["simulasyon"])
def simulation_status(run_id: str) -> Any:
    """Kosunun durumunu, tamamlandiysa sonucunu dondurur."""
    record = _runs.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Bilinmeyen kosu: {run_id}")
    if record["state"] == "done":
        return record["result"]
    return api.SimulationStatus(
        run_id=run_id,
        state=record["state"],
        progress=record.get("progress", 0.0),
        message=record.get("message", ""),
    )
