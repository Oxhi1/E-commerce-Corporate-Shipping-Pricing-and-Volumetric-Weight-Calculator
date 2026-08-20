"""Komut satiri arayuzu -- motoru aray uz olmadan surmek icin.

Aray uz gelistirilmeden once motorun dogrulanabilmesi ve sunum sirasinda bir
terminalde hizlica gosterilebilmesi icin var. Ciktilar bilincli olarak duz metin:
her ortamda calisir, kopyalanip rapora yapistirilabilir.

    python -m desi_engine.cli rate     --cart examples/banyo_seti.json --city 34
    python -m desi_engine.cli decide   --cart examples/zeytinyagi_nevresim.json --city 65
    python -m desi_engine.cli pack     --cart examples/banyo_seti.json
    python -m desi_engine.cli simulate --orders 5000 --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .domain.models import Address, Cart, CartLine, Order
from .engine import Engine, build_engine
from .packing import render_box_svg, render_plan_svg

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


# ---- girdi okuma -------------------------------------------------------------


def load_cart(engine: Engine, path: Path) -> tuple[Cart, bool, float]:
    """Sepet dosyasini okur. `(sepet, kapida_odeme, clv)` doner.

    Beklenen bicim:
        {"lines": [{"sku": "HV-003", "quantity": 2}], "cod": false, "clv": 4500}
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines = [
        CartLine(product=engine.product(entry["sku"]), quantity=int(entry.get("quantity", 1)))
        for entry in payload["lines"]
    ]
    return Cart(lines=lines), bool(payload.get("cod", False)), float(payload.get("clv", 0.0))


def build_order(engine: Engine, cart_path: Path, plate: int, order_id: str) -> Order:
    cart, is_cod, clv = load_cart(engine, cart_path)
    province = engine.provinces.get(plate)
    return Order(
        order_id=order_id,
        cart=cart,
        address=Address(city_plate=plate, city_name=province.name, region=province.region),
        is_cod=is_cod,
        customer_clv_try=clv,
    )


# ---- komutlar ----------------------------------------------------------------


def cmd_rate(args: argparse.Namespace) -> int:
    engine = build_engine(args.data)
    order = build_order(engine, Path(args.cart), args.city, "CLI-RATE")
    zone = engine.provinces.zone_class(order.origin_plate, args.city)
    plan = engine.planner.plan(order.cart)

    print(f"\n{order.address.city_name} ({args.city}) — bolge: {zone.value}")
    print(f"Sepet: {order.cart.total_value_try:,.2f} TL, {order.cart.total_weight_kg:.2f} kg")
    print(
        f"Koli plani: {plan.parcel_count} koli ({'+'.join(b.box.code for b in plan.boxes)}), "
        f"{plan.packed_desi:.1f} desi\n"
    )

    print(f"{'Firma':16}{'Desi':>6}{'Taban':>10}{'Yakit':>9}{'Sigorta':>9}{'KDV':>9}{'TOPLAM':>11}")
    print("-" * 70)
    for evaluation in sorted(engine.selector.evaluate_all(order), key=lambda e: e.freight_try):
        if not evaluation.eligible:
            print(f"{evaluation.display_name:16}  — {', '.join(evaluation.ineligibility_reasons)}")
            continue
        quote = evaluation.freight
        base = sum(p.base_after_min for p in quote.parcels)
        fuel = sum(p.fuel_try for p in quote.parcels)
        print(
            f"{evaluation.display_name:16}{evaluation.chargeable_desi:>6.0f}{base:>10.2f}"
            f"{fuel:>9.2f}{quote.insurance_try:>9.2f}{quote.vat_try:>9.2f}{quote.total_try:>11.2f}"
        )

    if engine.uses_synthetic_tariffs:
        print("\n[!] ORNEK TARIFE — bu fiyatlar sentetik veriden, gercek sozlesme degil.")
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    engine = build_engine(args.data)
    order = build_order(engine, Path(args.cart), args.city, "CLI-DECIDE")
    decision = engine.selector.decide(order)

    print(f"\n{'=' * 78}")
    print(f"SIPARIS {decision.order_id} — {order.address.city_name} ({decision.zone.value})")
    print(f"{'=' * 78}")
    print(
        f"{'Firma':16}{'Koli':>5}{'Desi':>6}{'Nakliye':>10}{'Hasar':>9}"
        f"{'Gecikme':>9}{'Ambalaj':>9}{'TOPLAM':>10}"
    )
    print("-" * 78)
    for evaluation in decision.ranked:
        components = evaluation.components
        marker = "  <-- SECILEN" if evaluation.carrier == decision.selected.carrier else ""
        print(
            f"{evaluation.display_name:16}{evaluation.parcel_count:>5}"
            f"{evaluation.chargeable_desi:>6.0f}{components.freight_try:>10.2f}"
            f"{components.damage_try:>9.2f}{components.delay_try:>9.2f}"
            f"{components.packaging_try:>9.2f}{components.expected_total_try:>10.2f}{marker}"
        )
    for evaluation in decision.rejected:
        print(
            f"{evaluation.display_name:16}  ELENDI: {', '.join(evaluation.ineligibility_reasons)}"
        )

    print(f"\nIkinciye marj: {decision.margin_try:.2f} TL (%{decision.margin_pct * 100:.1f})")
    if decision.overrode_cheapest_freight:
        print(
            f"En ucuz nakliye reddedildi — bu karar "
            f"{decision.savings_vs_cheapest_freight_try:.2f} TL kazandirdi."
        )

    if args.explain:
        print("\nGEREKCE")
        for line in decision.rationale:
            print(f"  - {line}")
        if decision.warnings:
            print("\nUYARILAR")
            for warning in decision.warnings:
                print(f"  ! {warning}")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    engine = build_engine(args.data)
    cart, _, _ = load_cart(engine, Path(args.cart))
    plans = engine.planner.candidates(cart)
    baselines = plans[0].baselines

    print(
        f"\nSepet: {sum(line.quantity for line in cart.lines)} urun, "
        f"{cart.total_value_try:,.2f} TL, {cart.total_weight_kg:.2f} kg"
    )
    print("\nBAZ CIZGILER")
    print(
        f"  Kotasyon toplami (urun desileri)   {baselines.quoted_sum_desi:7.2f} desi  "
        f"[fiziksel olarak ulasilamaz]"
    )
    print(
        f"  Her urun ayri koli                 {baselines.one_box_per_item_desi:7.2f} desi  "
        f"({baselines.one_box_per_item_parcels} koli)"
    )
    print(
        f"  Hacim kurali (Excel mantigi)       {baselines.volume_rule_desi:7.2f} desi  "
        f"({baselines.volume_rule_parcels} koli)"
    )

    print(f"\nADAY PLANLAR ({len(plans)})")
    print(f"  {'Strateji/varyant':30}{'Koli':>5}{'Desi':>8}{'Tasarruf':>10}{'Dolgu':>8}  Kutular")
    for plan in plans:
        print(
            f"  {plan.strategy + '/' + plan.variant:30}{plan.parcel_count:>5}"
            f"{plan.packed_desi:>8.2f}{plan.desi_savings_pct * 100:>9.1f}%"
            f"{plan.mean_fill_ratio * 100:>7.0f}%  {'+'.join(b.box.code for b in plan.boxes)}"
        )

    best = min(plans, key=lambda p: p.packed_desi)
    print(f"\nEn az desi ureten plan: {best.strategy}/{best.variant}")
    print(
        f"  Kotasyon acigi: %{best.quote_gap_pct * 100:+.1f} "
        "(pozitif = mevcut sistem dusuk fiyat veriyor, fark cepten odeniyor)"
    )

    if args.verbose:
        print("\nYERLESIM DETAYI")
        for index, box in enumerate(best.boxes, start=1):
            print(
                f"  Koli {index}: {box.box.code} ({box.box.name}) — "
                f"dis {box.outer_desi:.2f} desi, brut {box.gross_weight_kg:.2f} kg, "
                f"dolgu %{box.fill_ratio * 100:.0f}"
            )
            for placement in box.placements:
                print(
                    f"     {placement.sku:10} {placement.name[:28]:30} "
                    f"konum ({placement.x:5.1f},{placement.y:5.1f},{placement.z:5.1f}) "
                    f"olcu {placement.dx:5.1f}x{placement.dy:5.1f}x{placement.dz:5.1f}"
                )

    if args.render:
        path = Path(args.render)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Tek koli varsa saf SVG, birden fazlaysa hepsini iceren bir HTML parcasi.
        content = (
            render_plan_svg(best.boxes) if len(best.boxes) > 1 else render_box_svg(best.boxes[0])
        )
        path.write_text(content, encoding="utf-8")
        print(f"\nGorsel yazildi: {path}")

    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from .simulation import SimulationConfig, SimulationRunner

    engine = build_engine(args.data)
    print(f"Simulasyon basliyor: {args.orders:,} siparis, tohum {args.seed}")
    result = SimulationRunner(
        engine,
        SimulationConfig(
            n_orders=args.orders,
            seed=args.seed,
            progress_every=max(1000, args.orders // 10),
        ),
    ).run()

    print(
        f"\nTamamlandi: {result.elapsed_seconds:.1f} sn "
        f"({result.elapsed_seconds / args.orders * 1000:.2f} ms/siparis)"
    )
    print(
        f"\n{'Politika':30}{'TL/siparis':>12}{'Nakliye':>10}{'Gizli%':>8}"
        f"{'Hasar%':>8}{'Gec%':>7}{'Gun':>6}"
    )
    print("-" * 81)
    for summary in result.summaries.values():
        print(
            f"{summary.policy_code.value + ' ' + summary.label:30}"
            f"{summary.cost_per_order_try:>12.2f}{summary.freight_per_order_try:>10.2f}"
            f"{summary.hidden_cost_share * 100:>7.1f}%{summary.damage_rate * 100:>7.2f}%"
            f"{summary.late_rate * 100:>6.1f}%{summary.mean_delivery_days:>6.2f}"
        )

    print("\nKARSILASTIRMALAR (%95 guven araligi ile)")
    for comparison in result.comparisons:
        print(f"  {comparison.describe()}")

    print(f"\nKalibrasyon hatasi (ECE): {result.calibration_error:.4f}")
    print(f"Paketleme onbellegi isabet orani: %{result.packing_cache_hit_rate * 100:.1f}")

    if args.report:
        from .reporting import write_html_report

        path = Path(args.report)
        write_html_report(result, path)
        print(f"\nRapor yazildi: {path}")
    return 0


# ---- giris noktasi -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="desi", description="Ozdilek cok firmali kargo fiyatlama ve desi motoru"
    )
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_DATA_DIR, help="Veri dizini (varsayilan: ./data)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rate = subparsers.add_parser("rate", help="Tum firmalarin nakliye teklifleri")
    rate.add_argument("--cart", required=True)
    rate.add_argument("--city", type=int, required=True, help="Varis il plaka kodu")
    rate.set_defaults(func=cmd_rate)

    decide = subparsers.add_parser("decide", help="Firma secimi ve gerekcesi")
    decide.add_argument("--cart", required=True)
    decide.add_argument("--city", type=int, required=True)
    decide.add_argument("--explain", action="store_true", help="Gerekce metnini yazdir")
    decide.set_defaults(func=cmd_decide)

    pack = subparsers.add_parser("pack", help="Koli plani ve desi tasarrufu")
    pack.add_argument("--cart", required=True)
    pack.add_argument("--verbose", action="store_true", help="Yerlesim koordinatlarini yazdir")
    pack.add_argument(
        "--render",
        help="Koli yerlesimini SVG olarak yaz (orn. out/koli.svg). PNG icin harici "
        "bir donusturucu gerekir; raster bagimliligi eklenmedi.",
    )
    pack.set_defaults(func=cmd_pack)

    simulate = subparsers.add_parser("simulate", help="Monte Carlo politika karsilastirmasi")
    simulate.add_argument("--orders", type=int, default=5000)
    simulate.add_argument("--seed", type=int, default=42)
    simulate.add_argument("--report", help="HTML rapor cikti yolu")
    simulate.set_defaults(func=cmd_simulate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
