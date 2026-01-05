import requests
from bs4 import BeautifulSoup
import json
import re
from typing import Any, Dict, List, Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


# =========================
# Helper functions (as you had)
# =========================

def _extract_additional_properties(product_ld: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract additionalProperty[*].name/value into a flat dict.

    Supports:
      - value as scalar (string/number)
      - value as list (we keep the list)
    """
    extra: Dict[str, Any] = {}
    ap = product_ld.get("additionalProperty", [])

    if isinstance(ap, dict):
        ap = [ap]

    for prop in ap:
        if not isinstance(prop, dict):
            continue
        name = prop.get("name")
        value = prop.get("value")
        if not name:
            continue
        extra[name] = value
    return extra


def _fallback_extract_price(soup: BeautifulSoup) -> Dict[str, Optional[Any]]:
    """
    Try to extract price info from HTML when JSON-LD is missing or incomplete.
    """
    price = None
    currency = None
    original_price = None
    original_currency = None

    # 1) Adobe Commerce often uses data-price-type attributes
    price_span = soup.select_one('[data-price-type="finalPrice"] [data-price-amount]')
    if price_span and price_span.has_attr("data-price-amount"):
        try:
            price = float(price_span["data-price-amount"])
        except ValueError:
            pass

    # 2) Fallback: visible price text (very loose)
    if price is None:
        price_el = soup.select_one(".price, .special-price .price, .product-info-main .price")
        if price_el:
            text = price_el.get_text(strip=True)
            m = re.search(r"([$\u00a3\u20ac])\s*([\d.,]+)", text)
            if m:
                symbol, num = m.groups()
                currency = {
                    "$": "USD",
                    "€": "EUR",
                    "£": "GBP"
                }.get(symbol, None)
                try:
                    price = float(num.replace(",", ""))
                except ValueError:
                    pass

    # 3) Original/list price (if shown)
    old_price_el = soup.select_one(".old-price .price, .price-box .old-price .price")
    if old_price_el:
        text = old_price_el.get_text(strip=True)
        m = re.search(r"([$\u00a3\u20ac])\s*([\d.,]+)", text)
        if m:
            symbol, num = m.groups()
            original_currency = {
                "$": "USD",
                "€": "EUR",
                "£": "GBP"
            }.get(symbol, None)
            try:
                original_price = float(num.replace(",", ""))
            except ValueError:
                pass

    return {
        "price": price,
        "price_currency": currency,
        "original_price": original_price,
        "original_price_currency": original_currency,
    }


def _fallback_extract_images(soup: BeautifulSoup) -> List[str]:
    """
    Try to extract main image(s) from HTML when JSON-LD is missing.
    """
    urls: List[str] = []

    for sel in [
        ".product.media img",
        ".gallery-placeholder img",
        ".fotorama__stage__frame img",
        "img[src]"
    ]:
        for img in soup.select(sel):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            if src not in urls:
                urls.append(src)
        if urls:
            break  # stop once we have some reasonably specific matches

    return urls


def scrape_adobestore_pdp(url: str) -> Dict[str, Any]:
    """
    Scrape an Adobe Store (or similar Adobe Commerce) PDP and return a normalized product dictionary.

    - Prefers JSON-LD (Product / ProductGroup) when available.
    - Extracts additionalProperty into `additional_properties`.
    - Falls back to HTML scraping if JSON-LD is missing or incomplete.
    - Ensures there is a 'normalized_sku' field that the agent can pass into
      the CommerceProductDataTool.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    result: Dict[str, Any] = {"url": url}

    # --------------------------------
    # 1. Parse JSON-LD blocks
    # --------------------------------
    jsonld_objects: List[Dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        raw = script.string.strip()
        if not raw:
            continue

        data = None
        for candidate in (raw, raw.strip(";")):
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                data = None
        if data is None:
            continue

        if isinstance(data, list):
            jsonld_objects.extend([obj for obj in data if isinstance(obj, dict)])
        elif isinstance(data, dict):
            jsonld_objects.append(data)

    product_ld: Optional[Dict[str, Any]] = None
    for obj in jsonld_objects:
        obj_type = obj.get("@type")
        if obj_type in ("Product", "ProductGroup"):
            product_ld = obj
            break
    if product_ld is None and jsonld_objects:
        product_ld = jsonld_objects[0]

    # --------------------------------
    # 2. Populate from JSON-LD when present
    # --------------------------------
    if product_ld:
        ptype = product_ld.get("@type")
        result["product_type"] = ptype

        result["sku"] = product_ld.get("sku")
        result["title"] = product_ld.get("name")
        result["description"] = product_ld.get("description")
        result["canonical_url"] = product_ld.get("@id") or url

        # images
        images = product_ld.get("image")
        if isinstance(images, str):
            images = [images]
        elif images is None:
            images = []
        result["images"] = images

        # offers
        price = None
        price_currency = None
        availability = None
        list_price = None
        list_currency = None

        offers = product_ld.get("offers", [])
        if isinstance(offers, dict):
            offers = [offers]

        for offer in offers:
            if not isinstance(offer, dict):
                continue
            price = offer.get("price") or price
            price_currency = offer.get("priceCurrency") or price_currency
            availability = offer.get("availability") or availability

            spec = offer.get("priceSpecification")
            if isinstance(spec, dict):
                list_price = spec.get("price") or list_price
                list_currency = spec.get("priceCurrency") or list_currency

        result["price"] = price
        result["price_currency"] = price_currency
        result["original_price"] = list_price
        result["original_price_currency"] = list_currency
        result["availability"] = availability

        # variants (for ProductGroup)
        variants: List[Dict[str, Any]] = []
        if ptype == "ProductGroup":
            for v in product_ld.get("hasVariant", []):
                if not isinstance(v, dict):
                    continue

                v_offers = v.get("offers", [])
                if isinstance(v_offers, dict):
                    v_offers = [v_offers]

                v_price = None
                v_price_currency = None
                v_availability = None
                for vo in v_offers:
                    if not isinstance(vo, dict):
                        continue
                    v_price = vo.get("price") or v_price
                    v_price_currency = vo.get("priceCurrency") or v_price_currency
                    v_availability = vo.get("availability") or v_availability

                variants.append(
                    {
                        "sku": v.get("sku"),
                        "name": v.get("name"),
                        "image": v.get("image"),
                        "price": v_price,
                        "price_currency": v_price_currency,
                        "availability": v_availability,
                        "offers": v_offers,
                    }
                )
        result["variants"] = variants

        # additionalProperty → additional_properties
        result["additional_properties"] = _extract_additional_properties(product_ld)

        # keep raw JSON-LD
        result["raw_jsonld"] = product_ld
    else:
        # No JSON-LD at all
        result["product_type"] = None
        result["sku"] = None
        result["title"] = None
        result["description"] = None
        result["canonical_url"] = url
        result["images"] = []
        result["price"] = None
        result["price_currency"] = None
        result["original_price"] = None
        result["original_price_currency"] = None
        result["availability"] = None
        result["variants"] = []
        result["additional_properties"] = {}
        result["raw_jsonld"] = None

    # --------------------------------
    # 3. HTML-based extras
    # --------------------------------

    # Breadcrumbs
    breadcrumbs: List[str] = []
    for crumb in soup.select("nav a, .breadcrumb a"):
        text = crumb.get_text(strip=True)
        if text:
            breadcrumbs.append(text)
    seen = set()
    breadcrumbs_unique = []
    for c in breadcrumbs:
        if c not in seen:
            seen.add(c)
            breadcrumbs_unique.append(c)
    result["breadcrumbs"] = breadcrumbs_unique

    # Product code from text pattern, e.g. "Product Code: ADB366" or "SKU: ADB366"
    product_code = None
    for node in soup.find_all(string=re.compile(r"(SKU|Product Code)", re.IGNORECASE)):
        m = re.search(r"(SKU|Product Code)\s*:\s*([A-Z0-9\-]+)", node)
        if m:
            product_code = m.group(2)
            break
    if not product_code:
        product_code = result.get("sku")
    result["product_code"] = product_code

    # Title fallback
    if not result.get("title"):
        h1 = soup.find("h1")
        if h1:
            result["title"] = h1.get_text(strip=True)

    # Description fallback
    if not result.get("description"):
        desc_el = soup.select_one(".product.attribute.description, .product-info-main .value, .product-description")
        if desc_el:
            result["description"] = desc_el.get_text(" ", strip=True)

    # Images fallback
    if not result.get("images"):
        result["images"] = _fallback_extract_images(soup)

    # Price fallback
    if result.get("price") is None:
        price_info = _fallback_extract_price(soup)
        for k, v in price_info.items():
            if result.get(k) is None and v is not None:
                result[k] = v

    # --------------------------------
    # 4. Normalize SKU for agent usage
    # --------------------------------
    normalized_sku = result.get("sku") or result.get("product_code")
    result["normalized_sku"] = normalized_sku

    return result


# =========================
# CrewAI Tool wrapper
# =========================

class ScrapePdpToolInput(BaseModel):
    """
    Input schema for the PDP scraper tool.

    The agent must provide a single, full product detail page URL.
    The URL should be a PDP that clearly corresponds to a single SKU.
    """
    url: str = Field(
        ...,
        description=(
            "Full product detail page URL to scrape. "
            "Example: 'https://www.adobestore.com/products/p-adb366/adb366'. "
            "The page must contain a SKU in JSON-LD or in visible text so it "
            "can be passed to the CommerceProductDataTool."
        )
    )


class CommercePdpScraperTool(BaseTool):
    """
    Scrape a product detail page (PDP) and return the product information
    that is visible and embedded on the webpage itself.

    Use this tool when:
    - You are given a website URL for a product page.
    - You need to understand the product *as shown on the website*:
      title, description, images, price, availability, additional properties,
      breadcrumbs, and (very importantly) the product SKU.

    Output:
    - A JSON object that always includes:
      - `normalized_sku`: the SKU extracted from the page. Use this value as
        input to `commerce_product_data_by_sku` (CommerceProductDataTool).
      - `title`, `description`, `price`, `price_currency`, `images`, etc.
      - `additional_properties`: flattened additionalProperty from JSON-LD.
      - `raw_jsonld`: original JSON-LD Product block when present.
    - If no SKU can be found, the tool returns an error JSON explaining that
      the page is not usable for SKU-based comparison.

    This represents the "webpage source of truth" for what a human shopper sees.
    """

    name: str = "commerce_pdp_scraper"
    description: str = (
        "Given a product detail page URL, scrape the webpage to extract product data "
        "(title, description, price, availability, images, additional properties, "
        "breadcrumbs) and the product SKU. "
        "Returns a JSON object that includes `normalized_sku`, which should be used "
        "as the SKU input for the CommerceProductDataTool (`commerce_product_data_by_sku`) "
        "to compare website content with Commerce backend data."
    )
    args_schema: Type[BaseModel] = ScrapePdpToolInput

    def _run(self, url: str) -> str:
        try:
            data = scrape_adobestore_pdp(url)

            normalized_sku = data.get("normalized_sku")
            if not normalized_sku:
                # Explicit, agent-readable error
                return json.dumps(
                    {
                        "error": (
                            "No SKU found on the provided URL. "
                            "The page does not expose a usable SKU in JSON-LD or text, "
                            "so it cannot be compared with Commerce backend data."
                        ),
                        "url": url,
                        "source": "CommercePdpScraperTool",
                    },
                    ensure_ascii=False,
                )

            # Normal success path
            return json.dumps(
                {
                    "url": url,
                    "normalized_sku": normalized_sku,
                    "title": data.get("title"),
                    "description": data.get("description"),
                    "price": data.get("price"),
                    "price_currency": data.get("price_currency"),
                    "original_price": data.get("original_price"),
                    "original_price_currency": data.get("original_price_currency"),
                    "availability": data.get("availability"),
                    "images": data.get("images"),
                    "breadcrumbs": data.get("breadcrumbs"),
                    "additional_properties": data.get("additional_properties"),
                    "product_type": data.get("product_type"),
                    "product_code": data.get("product_code"),
                    "raw_jsonld": data.get("raw_jsonld"),
                    "raw": data,  # full scraped payload for deeper inspection
                },
                ensure_ascii=False,
            )

        except Exception as e:
            return json.dumps(
                {
                    "error": str(e),
                    "url": url,
                    "source": "CommercePdpScraperTool",
                },
                ensure_ascii=False,
            )
