import { useNavigate } from "react-router-dom";
import type { CatalogProduct } from "../../../types";
import { moneyLabel, toAssetUrl, whatsappLink } from "../utils";
import { useAuth } from "../../auth";
import { storefrontText } from "../storefrontText";

type ProductCardProps = {
  product: CatalogProduct;
  phone: string;
};

export function ProductCard({ product, phone }: ProductCardProps) {
  const navigate = useNavigate();
  const {storefront,user}=useAuth();
  const company=storefront||{company_name:user?.company_name||"Tenali",nickname:undefined};
  const copy=storefront?.storefront_content?.product||{};
  const text=(key:string,fallback:string,variables:Record<string,string|number>={})=>storefrontText(copy[key]||fallback,company,variables);
  const gallery = (product.image_urls || "")
    .split("|")
    .map((img) => img.trim())
    .filter(Boolean);
  const image = gallery[0] || product.image_url;

  return (
    <article
      className="product-card dynamic-card"
      role="link"
      tabIndex={0}
      onClick={() => navigate(`/products/${product.id}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter") navigate(`/products/${product.id}`);
      }}
    >
      <div className="product-image">
        <img src={toAssetUrl(image)} alt={product.name} loading="lazy" />
        <div className="product-tags">
          {product.best_seller && <span className="badge-best">{text("best_seller_badge","Best Seller")}</span>}
          {product.sru_special && <span className="badge-special">{text("special_badge","Special")}</span>}
        </div>
        {gallery.length > 1 && <span className="photo-count">{text("photos_count","{count} photos",{count:gallery.length})}</span>}
        {!!product.stock_qty && (
          <span className={product.stock_qty > 0 ? "stock-badge stock-in" : "stock-badge stock-out"}>
            {product.stock_qty > 0 ? text("in_stock","In stock") : text("out_of_stock","Out of stock")}
          </span>
        )}
      </div>
      <div className="product-body">
        <div className="product-type">{product.brand_name || product.category_title}</div>
        <h3 title={product.name}>{product.name}</h3>
        <div className="price-block">
          <div className="mrp">
            <span>{text("mrp_label","MRP")}</span>
            <s>{moneyLabel(product.mrp_display)}</s>
          </div>
          <div className="our-price">
            <span>{text("our_price_label","Our Price")}</span>
            <strong>{moneyLabel(product.selling_price_display)}</strong>
          </div>
        </div>
        <p title={product.description}>{product.description}</p>
        {phone?<a
          className="btn whatsapp-btn"
          href={whatsappLink(phone, product.name, product.brand_name || company.nickname || company.company_name, text("whatsapp_message","Hello, I am interested in {product_name} from {brand_name}. Please share pricing, availability and bulk options."))}
          onClick={(e) => e.stopPropagation()}
        >
          {text("whatsapp_enquiry","WhatsApp enquiry")}
        </a>:null}
      </div>
    </article>
  );
}
