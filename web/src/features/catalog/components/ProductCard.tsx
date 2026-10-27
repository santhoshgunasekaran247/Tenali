import { useNavigate } from "react-router-dom";
import type { CatalogProduct } from "../../../types";
import { moneyLabel, toAssetUrl, whatsappLink } from "../utils";

type ProductCardProps = {
  product: CatalogProduct;
  phone: string;
};

export function ProductCard({ product, phone }: ProductCardProps) {
  const navigate = useNavigate();
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
          {product.best_seller && <span className="badge-best">Best Seller</span>}
          {product.sru_special && <span className="badge-special">SRU Special</span>}
        </div>
        {gallery.length > 1 && <span className="photo-count">{gallery.length} photos</span>}
        {!!product.stock_qty && (
          <span className={product.stock_qty > 0 ? "stock-badge stock-in" : "stock-badge stock-out"}>
            {product.stock_qty > 0 ? "In stock" : "Out of stock"}
          </span>
        )}
      </div>
      <div className="product-body">
        <div className="product-type">{product.brand_name || product.category_title}</div>
        <h3 title={product.name}>{product.name}</h3>
        <div className="price-block">
          <div className="mrp">
            <span>MRP</span>
            <s>{moneyLabel(product.mrp_display)}</s>
          </div>
          <div className="our-price">
            <span>Our Price</span>
            <strong>{moneyLabel(product.selling_price_display)}</strong>
          </div>
        </div>
        <p title={product.description}>{product.description}</p>
        <a
          className="btn whatsapp-btn"
          href={whatsappLink(phone, product.name, product.brand_name || "SRU Collection")}
          onClick={(e) => e.stopPropagation()}
        >
          WhatsApp enquiry
        </a>
      </div>
    </article>
  );
}
