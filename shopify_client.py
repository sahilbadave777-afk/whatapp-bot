"""Reads live product data from the Shopify Admin GraphQL API."""
import re
import time
import threading
import requests

import config

PRODUCT_FIELDS = """
  id
  title
  handle
  status
  productType
  vendor
  tags
  description(truncateAt: 600)
  onlineStoreUrl
  totalInventory
  tracksInventory
  featuredMedia { preview { image { url } } }
  priceRangeV2 {
    minVariantPrice { amount currencyCode }
    maxVariantPrice { amount currencyCode }
  }
  variants(first: 10) {
    nodes { title sku barcode price inventoryQuantity availableForSale }
  }
"""

SEARCH_QUERY = f"""
query Search($q: String!, $n: Int!) {{
  products(first: $n, query: $q, sortKey: RELEVANCE) {{
    nodes {{ {PRODUCT_FIELDS} }}
  }}
}}
"""

GET_QUERY = f"""
query Get($id: ID!) {{
  product(id: $id) {{ {PRODUCT_FIELDS} }}
}}
"""


class ShopifyClient:
    def __init__(self):
        if not config.SHOPIFY_STORE:
            raise RuntimeError("SHOPIFY_STORE is not set")
        self.base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.SHOPIFY_API_VERSION}/graphql.json"
        self._token = config.SHOPIFY_ADMIN_TOKEN or None
        self._token_expires = float("inf") if self._token else 0.0
        self._lock = threading.Lock()

    # ---------- auth ----------
    def _get_token(self) -> str:
        """Static token if given; otherwise client-credentials token, refreshed before it expires (24h)."""
        with self._lock:
            if self._token and time.time() < self._token_expires - 300:
                return self._token
            if not (config.SHOPIFY_CLIENT_ID and config.SHOPIFY_CLIENT_SECRET):
                raise RuntimeError("Set SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET, or SHOPIFY_ADMIN_TOKEN")
            r = requests.post(
                f"https://{config.SHOPIFY_STORE}/admin/oauth/access_token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": config.SHOPIFY_CLIENT_ID,
                    "client_secret": config.SHOPIFY_CLIENT_SECRET,
                },
                timeout=20,
            )
            r.raise_for_status()
            body = r.json()
            self._token = body["access_token"]
            self._token_expires = time.time() + int(body.get("expires_in", 86399))
            return self._token

    def _gql(self, query: str, variables: dict) -> dict:
        for attempt in range(3):
            r = requests.post(
                self.base,
                json={"query": query, "variables": variables},
                headers={"X-Shopify-Access-Token": self._get_token(), "Content-Type": "application/json"},
                timeout=20,
            )
            if r.status_code == 401 and not config.SHOPIFY_ADMIN_TOKEN:
                self._token_expires = 0  # force refresh and retry
                continue
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            body = r.json()
            errors = body.get("errors")
            if errors:
                if any(e.get("extensions", {}).get("code") == "THROTTLED" for e in errors):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Shopify error: {errors}")
            return body["data"]
        raise RuntimeError("Shopify request failed after retries")

    # ---------- formatting ----------
    def _clean(self, p: dict | None) -> dict | None:
        """Turn a raw Shopify product into the small, accurate record the AI sees."""
        if not p:
            return None
        variants = p.get("variants", {}).get("nodes", [])
        tracks = p.get("tracksInventory")
        total = p.get("totalInventory")
        in_stock = any(v.get("availableForSale") for v in variants)
        pr = p.get("priceRangeV2") or {}
        lo = (pr.get("minVariantPrice") or {}).get("amount")
        hi = (pr.get("maxVariantPrice") or {}).get("amount")
        currency = (pr.get("minVariantPrice") or {}).get("currencyCode", "USD")
        image = (((p.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url")
        url = p.get("onlineStoreUrl") or f"{config.PUBLIC_STORE_URL}/products/{p['handle']}"

        record = {
            "id": p["id"],
            "title": p["title"],
            "price": _fmt_price(lo, hi, currency),
            "in_stock": in_stock,
            "url": url,
            "has_photo": bool(image),
            "product_type": p.get("productType") or None,
            "brand": p.get("vendor") or None,
            # readable tags only (e.g. "BRAKE FLUID"); internal menu/category slugs are kept separately
            "tags": [t for t in p.get("tags", []) if "--" not in t and not t.startswith(("cat-", "rpsmm-"))][:8],
            "description": (p.get("description") or "").strip() or None,
            "variants": [
                {
                    "option": v["title"],
                    "sku": v.get("sku") or None,
                    "barcode": v.get("barcode") or None,
                    "price": v.get("price"),
                    "in_stock": v.get("availableForSale"),
                    **({"qty": v.get("inventoryQuantity")} if config.SHOW_EXACT_STOCK and tracks else {}),
                }
                for v in variants
            ],
        }
        if config.SHOW_EXACT_STOCK and tracks and total is not None:
            record["qty_available"] = total
        # internal fields (start with "_"), stripped before sending to the AI
        record["_image"] = image
        record["_category_tags"] = [t for t in p.get("tags", []) if t.startswith("rpsmm-")]
        return record

    # ---------- public API ----------
    def search(self, text: str, limit: int = 5, in_stock_only: bool = False) -> list[dict]:
        text = (text or "").strip()
        if not text:
            return []
        q = _build_search(text)
        q = f"({q}) AND status:active"
        data = self._gql(SEARCH_QUERY, {"q": q, "n": max(1, min(limit, 10))})
        results = [self._clean(p) for p in data["products"]["nodes"]]
        if in_stock_only:
            results = [r for r in results if r["in_stock"]]

        # Fallback: no hit on the full phrase -> try each meaningful word
        if not results and len(text.split()) > 1:
            words = [w for w in re.findall(r"[A-Za-z0-9\-]{3,}", text) if w.lower() not in STOPWORDS]
            if words:
                q2 = " OR ".join(f"title:*{w}*" for w in words[:5])
                data = self._gql(SEARCH_QUERY, {"q": f"({q2}) AND status:active", "n": max(1, min(limit, 10))})
                results = [self._clean(p) for p in data["products"]["nodes"]]
        return results

    def get(self, product_id: str) -> dict | None:
        if not product_id.startswith("gid://"):
            product_id = f"gid://shopify/Product/{product_id}"
        return self._clean(self._gql(GET_QUERY, {"id": product_id})["product"])

    def related(self, product_id: str | None = None, keywords: str | None = None, limit: int = 5) -> list[dict]:
        """Available alternatives: same store category (deepest rpsmm- tag), product type, brand, or keywords."""
        base = self.get(product_id) if product_id else None
        queries = []
        if base:
            # most specific store category first, e.g. rpsmm-truck-parts--air-brake-and-wheel--camshafts-and-brake-hardware
            for tag in sorted(base["_category_tags"], key=lambda t: t.count("--"), reverse=True)[:2]:
                queries.append(f"tag:{_quote(tag)}")
            if base["product_type"]:
                queries.append(f"product_type:{_quote(base['product_type'])}")
            words = [w for w in re.findall(r"[A-Za-z]{4,}", base["title"]) if w.lower() not in STOPWORDS][:3]
            if words:
                queries.append(" OR ".join(f"title:*{w}*" for w in words))
        if keywords:
            queries.append(_build_search(keywords))

        seen = {base["id"]} if base else set()
        out: list[dict] = []
        for q in queries:
            # Note: RPS doesn't track inventory counts, so "available for sale" is the stock signal.
            data = self._gql(SEARCH_QUERY, {"q": f"({q}) AND status:active", "n": 10})
            for p in data["products"]["nodes"]:
                c = self._clean(p)
                if c and c["id"] not in seen and c["in_stock"]:
                    seen.add(c["id"])
                    out.append(c)
                if len(out) >= limit:
                    return out
        return out


STOPWORDS = {
    "the", "and", "for", "you", "have", "with", "do", "does", "any", "need", "want", "price",
    "how", "much", "what", "your", "this", "that", "stock", "available", "part", "parts",
}


def _quote(s: str) -> str:
    return '"' + s.replace('"', "") + '"'


def _looks_like_part_number(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9\-\.\/]{3,30}", s)) and any(ch.isdigit() for ch in s)


def _build_search(text: str) -> str:
    """Searches title/description by default; part numbers also hit SKU and barcode exactly."""
    text = text.replace('"', "").strip()
    if _looks_like_part_number(text):
        return f"sku:{_quote(text)} OR barcode:{_quote(text)} OR {text}"
    return text


def _fmt_price(lo, hi, currency):
    if lo is None:
        return None
    sym = "$" if currency == "USD" else f"{currency} "
    lo_f, hi_f = float(lo), float(hi or lo)
    if lo_f == 0:
        return None  # $0 means "call for price" - never quote it
    return f"{sym}{lo_f:,.2f}" if lo_f == hi_f else f"{sym}{lo_f:,.2f} - {sym}{hi_f:,.2f}"
