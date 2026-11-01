import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MapPin, MessageCircle } from "lucide-react";
import { accountRequest, type NearbyStore } from "../features/shop";

/** Pickup-enabled shops with availability bands for a product, plus a WhatsApp enquiry that records an enquiry reference. */
export function NearbyStores({ productId, variantId, productName, quantity, checkoutEnabled }:
  { productId: string; variantId: string | null; productName: string; quantity: number; checkoutEnabled: boolean }) {
  const [stores, setStores] = useState<NearbyStore[] | null>(null);
  const [defaultNumber, setDefaultNumber] = useState<string | null>(null);
  const [position, setPosition] = useState<{ lat: number; lng: number } | null>(null);
  const [pincode, setPincode] = useState("");
  const [error, setError] = useState("");
  const [enquiry, setEnquiry] = useState({ name: "", phone: "", message: "", store: "" });
  const [enquiryOpen, setEnquiryOpen] = useState(false);
  const [sent, setSent] = useState<{ reference: string; whatsapp_link: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    const params = new URLSearchParams({ product_id: productId });
    if (variantId) params.set("variant_id", variantId);
    if (position) { params.set("lat", String(position.lat)); params.set("lng", String(position.lng)); }
    if (/^[1-9][0-9]{5}$/.test(pincode)) params.set("pincode", pincode);
    try {
      const result = await accountRequest<{ items: NearbyStore[]; default_whatsapp_number: string | null }>(`/nearby?${params}`);
      setStores(result.items); setDefaultNumber(result.default_whatsapp_number); setError("");
    } catch (failure) { setError(String(failure)); }
  };
  useEffect(() => { void load(); }, [productId, variantId, position?.lat, position?.lng, pincode.length === 6 ? pincode : ""]);
  const locate = () => navigator.geolocation?.getCurrentPosition(
    result => setPosition({ lat: result.coords.latitude, lng: result.coords.longitude }),
    () => setError("Location not shared; enter your PIN code to sort stores."));
  const submitEnquiry = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const phone = enquiry.phone.startsWith("+") ? enquiry.phone : `+91${enquiry.phone}`;
      const result = await accountRequest<{ reference: string; whatsapp_link: string | null }>("/enquiries", {
        method: "POST", body: JSON.stringify({ product_id: productId, variant_id: variantId, quantity, store_id: enquiry.store || null,
          shopper_name: enquiry.name, shopper_phone: phone, message: enquiry.message || null }),
      });
      setSent(result);
      if (result.whatsapp_link) window.open(result.whatsapp_link, "_blank", "noopener");
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const label = { available: "In stock", few_left: "Few left", unavailable: "Not in stock" };
  return <section className="ops-card nearby-stores" aria-labelledby="nearby-heading">
    <h2 id="nearby-heading"><MapPin size={18} aria-hidden="true" /> Pick up at a nearby store</h2>
    {error ? <p role="alert" className="ops-error">{error}</p> : null}
    <div className="shop-actions"><button type="button" className="btn light" onClick={locate}>Use my location</button>
      <label>PIN code<input inputMode="numeric" maxLength={6} value={pincode} onChange={event => setPincode(event.target.value)} placeholder="600001" /></label></div>
    {stores === null ? <p>Checking stores...</p> : !stores.length ? <p>No pickup stores are available yet. Delivery and WhatsApp enquiry remain available.</p>
      : <ul className="nearby-store-list">{stores.map(store => <li key={store.store_id}>
        <strong>{store.name}</strong>{store.distance_km !== null ? ` · ${store.distance_km} km` : store.pincode ? ` · ${store.pincode}` : ""}
        <span className={`availability-${store.availability}`}>{label[store.availability]}</span>
        {store.address ? <small>{store.address}</small> : null}
        <span className="shop-actions">
          {checkoutEnabled && store.availability !== "unavailable" ? <Link className="btn light" to={`/cart?pickup=${store.store_id}`}>Reserve for pickup</Link> : null}
          {(store.whatsapp_number || defaultNumber) ? <button type="button" className="btn light" onClick={() => { setEnquiry(previous => ({ ...previous, store: store.store_id })); setEnquiryOpen(true); }}><MessageCircle size={16} aria-hidden="true" /> Ask this store</button> : null}
        </span>
      </li>)}</ul>}
    {enquiryOpen && !sent ? <form className="ops-form" onSubmit={submitEnquiry}><h3>WhatsApp enquiry · {productName}</h3>
      <div className="company-fields">
        <label>Your name<input required maxLength={120} value={enquiry.name} onChange={event => setEnquiry({ ...enquiry, name: event.target.value })} /></label>
        <label>Mobile number<input required pattern="(\\+[1-9][0-9]{7,14}|[6-9][0-9]{9})" value={enquiry.phone} onChange={event => setEnquiry({ ...enquiry, phone: event.target.value })} /></label>
        <label>Message<input maxLength={1000} value={enquiry.message} onChange={event => setEnquiry({ ...enquiry, message: event.target.value })} placeholder="Bulk quantity, customisation, availability..." /></label>
      </div>
      <p className="ops-copy-note">This records an enquiry reference with the store and opens WhatsApp. It does not reserve stock or take payment.</p>
      <div className="shop-actions"><button className="btn" disabled={busy}>{busy ? "Please wait..." : "Open WhatsApp"}</button><button type="button" className="btn light" onClick={() => setEnquiryOpen(false)}>Cancel</button></div>
    </form> : null}
    {sent ? <p role="status">Enquiry {sent.reference} recorded. {sent.whatsapp_link ? <a href={sent.whatsapp_link} target="_blank" rel="noopener noreferrer">Open WhatsApp</a> : "The store will contact you."}</p> : null}
  </section>;
}
