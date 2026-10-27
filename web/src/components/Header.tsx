import { Link } from "react-router-dom";
import { toAssetUrl } from "../features/catalog/utils";

type HeaderProps = {
  menuOpen: boolean;
  onMenuToggle: () => void;
};

export function Header({ menuOpen, onMenuToggle }: HeaderProps) {
  return (
    <header className="header">
      <Link className="brand" to="/">
        <img src={toAssetUrl("sru-global-logo.png")} alt="SRU Global" />
      </Link>
      <nav className={menuOpen ? "open" : ""}>
        <a href="/#collection-special">SRU Collection Special</a>
        <a href="/#categories">Categories</a>
        <a href="/#best-sellers">Best Sellers</a>
        <a href="/#sru-specials">SRU Specials</a>
        <a href="/#brands">Brands</a>
        <a href="/#contact">Contact</a>
      </nav>
      <button className="menu" aria-label="Open menu" onClick={onMenuToggle}>
        ☰
      </button>
    </header>
  );
}
