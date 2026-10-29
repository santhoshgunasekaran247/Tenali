import { createContext, useContext, useRef, useState, type ReactNode } from "react";
import { useAuth } from "./auth";

export type CartItem = { product_id: string; variant_id: string | null; quantity: number };
export const cartItemKey = (item: Pick<CartItem, "product_id" | "variant_id">) => `${item.product_id}:${item.variant_id || ""}`;
type Cart = {
  items: CartItem[];
  add: (item: CartItem) => void;
  setQuantity: (item: CartItem, quantity: number) => void;
  remove: (item: CartItem) => void;
  removePurchased: (items: CartItem[]) => void;
};
const CartContext = createContext<Cart | null>(null);

function readCart(key: string | null): { items: CartItem[]; error: string } {
  if (!key) return { items: [], error: "" };
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) || "[]");
    if (!Array.isArray(saved) || saved.length > 30 || saved.some(item =>
      !item || typeof item.product_id !== "string" || !(item.variant_id === null || typeof item.variant_id === "string")
      || !Number.isInteger(item.quantity) || item.quantity < 1 || item.quantity > 100)
      || new Set(saved.map(cartItemKey)).size !== saved.length) {
      throw new Error("Invalid saved cart");
    }
    return { items: saved.map(({ product_id, variant_id, quantity }) => ({ product_id, variant_id, quantity })), error: "" };
  } catch {
    return { items: [], error: "Your saved cart could not be loaded. Please add the products again. Check that browser storage is enabled." };
  }
}

function WorkspaceCart({ companyId, children }: { companyId?: string; children: ReactNode }) {
  const key = companyId ? `tenali-cart:${companyId}` : null;
  const [initial] = useState(() => readCart(key));
  const [items, setItems] = useState(initial.items);
  const currentItems = useRef(items);
  const [error, setError] = useState(initial.error);
  const save = (next: CartItem[]) => {
    if (!key) throw new Error("Open a workspace storefront before adding products.");
    currentItems.current = next;
    setItems(next);
    try { localStorage.setItem(key, JSON.stringify(next)); setError(""); }
    catch { setError("Your cart is available in this tab, but could not be saved. Enable browser storage before leaving this page."); }
  };
  const value: Cart = {
    items,
    add(item) {
      const current = currentItems.current;
      const existing = current.find(entry => cartItemKey(entry) === cartItemKey(item));
      const quantity = (existing?.quantity || 0) + item.quantity;
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100) throw new Error("Online orders support up to 100 units per item. Contact the store for larger quantities.");
      if (!existing && current.length >= 30) throw new Error("Your cart can contain up to 30 different products / variants.");
      save(existing ? current.map(entry => entry === existing ? { ...entry, quantity } : entry) : [...current, item]);
    },
    setQuantity(item, quantity) {
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100) throw new Error("Choose a whole number between 1 and 100.");
      save(currentItems.current.map(entry => cartItemKey(entry) === cartItemKey(item) ? { ...entry, quantity } : entry));
    },
    remove(item) { save(currentItems.current.filter(entry => cartItemKey(entry) !== cartItemKey(item))); },
    removePurchased(purchased) {
      save(currentItems.current.flatMap(entry => {
        const quantity = entry.quantity - (purchased.find(item => cartItemKey(item) === cartItemKey(entry))?.quantity || 0);
        return quantity > 0 ? [{ ...entry, quantity }] : [];
      }));
    },
  };
  return <CartContext.Provider value={value}>{error ? <p className="checkout-notice ops-error" role="alert">{error}</p> : null}{children}</CartContext.Provider>;
}

export function CartProvider({ children }: { children: ReactNode }) {
  const { storefront } = useAuth();
  return <WorkspaceCart key={storefront?.id || "none"} companyId={storefront?.id}>{children}</WorkspaceCart>;
}

export function useCart() {
  const cart = useContext(CartContext);
  if (!cart) throw new Error("CartProvider is required.");
  return cart;
}
