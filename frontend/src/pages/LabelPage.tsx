/**
 * Etiket önizleme sekmesi — karar zincirinin son halkası.
 *
 * Kullanıcının 4. maddesi: "paketleme personeli düşünmez, sadece etiketi
 * yapıştırır." Etiket aynı zamanda **denetim kaydı**: üzerinde kararın özeti var,
 * böylece bir şikâyet geldiğinde "bu koli neden bu firmayla gitti" sorusunun
 * cevabı etiketten okunabiliyor.
 *
 * Barkod `dangerouslySetInnerHTML` ile basılıyor. Kaynak kendi backend'imizin
 * ürettiği, sabit şablonlu SVG; içine kullanıcı metni girmiyor (takip numarası
 * `[A-Z0-9]` ile sınırlı). Yine de bu, dışarıdan gelen HTML'e güvenmenin genel
 * olarak tehlikeli olduğu gerçeğini değiştirmez — kaynak değişirse gözden geçirilmeli.
 */

import { formatTry } from "../api/client";
import type { LabelResponse } from "../api/types";

export function LabelPage({ data }: { data: LabelResponse }) {
  const download = (zpl: string, tracking: string) => {
    const blob = new Blob([zpl], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${tracking}.zpl`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="stack">
      <div className="card">
        <div className="card-header">
          <h2>Kargo etiketleri</h2>
          <span className="badge badge--neutral">
            {data.labels.length} koli · {data.carrier}
          </span>
        </div>
        <p className="card-note">
          Karar verildikten sonra depodaki yazıcıya gidecek çıktı. ZPL (Zebra
          Programming Language) sektörün fiili standardı; barkodu yazıcının kendisi
          kodlar. Aşağıdaki önizlemedeki barkod aynı veriyi taşıyan gerçek bir
          Code&nbsp;128 çizimidir.
        </p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: 18,
        }}
      >
        {data.labels.map((label) => (
          <div className="card stack" key={label.tracking_number}>
            <div className="shipping-label">
              <div className="label-carrier">{label.carrier_display}</div>
              <div className="label-meta">
                <span>Sipariş {data.order_id}</span>
                <span>
                  Koli {label.parcel_index}/{label.parcel_count}
                </span>
                <span>Kutu {label.box_code}</span>
              </div>
              <div>
                <div className="label-section-title">ALICI</div>
                <div className="label-city">{label.recipient}</div>
                <div className="label-zone">
                  Bölge: {label.zone} · Ücretli desi: {label.chargeable_desi}
                </div>
              </div>
              <div
                className="label-barcode"
                dangerouslySetInnerHTML={{ __html: label.barcode_svg }}
              />
              {label.is_cod && label.cod_amount_try > 0 && (
                <div className="label-cod">
                  KAPIDA ÖDEME: {formatTry(label.cod_amount_try)} TL
                </div>
              )}
              <div className="label-note">{label.decision_note}</div>
              {label.is_synthetic_tariff && (
                <div className="label-synthetic">
                  ÖRNEK TARİFE — gerçek sözleşme fiyatı değil
                </div>
              )}
            </div>

            <div className="row">
              <button
                className="button"
                onClick={() => download(label.zpl, label.tracking_number)}
              >
                ZPL indir
              </button>
              <code style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {label.tracking_number}
              </code>
            </div>

            <details>
              <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--text-secondary)" }}>
                ZPL kaynağını göster
              </summary>
              <pre
                style={{
                  background: "var(--surface-0)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  padding: 10,
                  fontSize: 11.5,
                  overflowX: "auto",
                  marginTop: 8,
                }}
              >
                {label.zpl}
              </pre>
            </details>
          </div>
        ))}
      </div>
    </div>
  );
}
