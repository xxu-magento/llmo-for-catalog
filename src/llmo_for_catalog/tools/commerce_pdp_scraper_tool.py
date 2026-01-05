import json
import re
from typing import Any, Dict, List, Optional, Type

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from crewai.tools import BaseTool

# =========================
# Helper functions
# =========================

def _extract_additional_properties(product_ld: Dict[str, Any]) -> Dict[str, Any]:
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


def _get_meta_content(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """Helper to safely get meta/link attribute content."""
    el = soup.select_one(selector)
    if not el:
        return None
    # meta uses "content"; canonical uses "href"
    if el.has_attr("content"):
        val = el.get("content")
        return val.strip() if isinstance(val, str) and val.strip() else None
    if el.has_attr("href"):
        val = el.get("href")
        return val.strip() if isinstance(val, str) and val.strip() else None
    return None


def _extract_h1(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    if not h1:
        return None
    text = h1.get_text(" ", strip=True)
    return text if text else None


def _detect_title_format(title_tag: Optional[str]) -> Dict[str, Any]:
    """
    Optional: detect if a site uses a title pattern like:
    '{brand} - {page}' or '{page} | {brand}'.
    """
    if not title_tag:
        return {"seo_title_format": None, "seo_title_format_notes": None}

    # Heuristics
    if " | " in title_tag:
        return {
            "seo_title_format": "pipe",
            "seo_title_format_notes": "Title tag contains ' | ' separator (often '{page} | {brand}').",
        }
    if " - " in title_tag:
        return {
            "seo_title_format": "dash",
            "seo_title_format_notes": "Title tag contains ' - ' separator (often '{brand} - {page}' or '{page} - {brand}').",
        }
    return {"seo_title_format": "none", "seo_title_format_notes": "No common separator detected."}


def _extract_description_block(soup: BeautifulSoup) -> Dict[str, Any]:
    """
    Extract PDP description blocks as both HTML (if possible) and plain text.
    This is useful for SEO agent improvements.
    """
    # Common PDP description containers across Adobe Commerce themes
    desc_el = soup.select_one(
        ".product.attribute.description, .product-info-main .value, .product-description"
    )
    if not desc_el:
        return {
            "pdp": {
                "description_html": None,
                "description_plain": None,
            }
        }

    html = str(desc_el)
    plain = desc_el.get_text(" ", strip=True)
    return {
        "pdp": {
            "description_html": html if html else None,
            "description_plain": plain if plain else None,
        }
    }


def _fallback_extract_price(soup: BeautifulSoup) -> Dict[str, Optional[Any]]:
    price = None
    currency = None
    original_price = None
    original_currency = None

    price_span = soup.select_one('[data-price-type="finalPrice"] [data-price-amount]')
    if price_span and price_span.has_attr("data-price-amount"):
        try:
            price = float(price_span["data-price-amount"])
        except ValueError:
            pass

    if price is None:
        price_el = soup.select_one(".price, .special-price .price, .product-info-main .price")
        if price_el:
            text = price_el.get_text(strip=True)
            m = re.search(r"([$\u00a3\u20ac])\s*([\d.,]+)", text)
            if m:
                symbol, num = m.groups()
                currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(symbol)
                try:
                    price = float(num.replace(",", ""))
                except ValueError:
                    pass

    old_price_el = soup.select_one(".old-price .price, .price-box .old-price .price")
    if old_price_el:
        text = old_price_el.get_text(strip=True)
        m = re.search(r"([$\u00a3\u20ac])\s*([\d.,]+)", text)
        if m:
            symbol, num = m.groups()
            original_currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(symbol)
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
    urls: List[str] = []
    for sel in [
        ".product.media img",
        ".gallery-placeholder img",
        ".fotorama__stage__frame img",
        "img[src]",
    ]:
        for img in soup.select(sel):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            if src not in urls:
                urls.append(src)
        if urls:
            break
    return urls


def _make_soup(html: str) -> BeautifulSoup:
    """
    Prefer lxml if installed; fall back to html.parser.
    """
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def scrape_pdp(url: str) -> Dict[str, Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        # Make errors easier to diagnose
        if resp.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {resp.status_code} fetching PDP URL: {url}",
                response=resp,
            )
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch PDP URL: {url}. Error: {str(e)}") from e

    soup = _make_soup(resp.text)
    result: Dict[str, Any] = {"url": url}

    # --------------------------------
    # SEO + page-level fields
    # --------------------------------
    seo_title_tag = soup.title.get_text(strip=True) if soup.title else None

    seo_meta_description = _get_meta_content(soup, 'meta[name="description"]')
    if not seo_meta_description:
        seo_meta_description = _get_meta_content(soup, 'meta[property="og:description"]')

    seo_canonical = _get_meta_content(soup, 'link[rel="canonical"]')
    seo_robots = _get_meta_content(soup, 'meta[name="robots"]')

    html_tag = soup.find("html")
    page_lang = html_tag.get("lang") if html_tag and html_tag.get("lang") else None

    seo_h1 = _extract_h1(soup)

    result["seo"] = {
        "title_tag": seo_title_tag,
        "meta_description": seo_meta_description,
        "h1": seo_h1,
        "canonical": seo_canonical,
        "robots": seo_robots,
        "page_lang": page_lang,
    }
    result.update(_detect_title_format(seo_title_tag))
    result.update(_extract_description_block(soup))

    # --------------------------------
    # 1) Parse JSON-LD blocks when available
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
    # 2) Populate from JSON-LD when available
    # --------------------------------
    if product_ld:
        ptype = product_ld.get("@type")
        result["product_type"] = ptype

        result["sku"] = product_ld.get("sku")
        result["title"] = product_ld.get("name")
        result["description"] = product_ld.get("description")
        result["canonical_url"] = product_ld.get("@id") or url

        images = product_ld.get("image")
        if isinstance(images, str):
            images = [images]
        elif images is None:
            images = []
        result["images"] = images

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
        result["additional_properties"] = _extract_additional_properties(product_ld)
        result["raw_jsonld"] = product_ld
    else:
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
    # 3) HTML-based extras
    # --------------------------------
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

    product_code = None
    for node in soup.find_all(string=re.compile(r"(SKU|Product Code)", re.IGNORECASE)):
        m = re.search(r"(SKU|Product Code)\s*:\s*([A-Z0-9\-]+)", str(node))
        if m:
            product_code = m.group(2)
            break
    if not product_code:
        product_code = result.get("sku")
    result["product_code"] = product_code

    # Title fallback from SEO H1 if JSON-LD title missing
    if not result.get("title"):
        if seo_h1:
            result["title"] = seo_h1

    # Description fallback from extracted block (plain text)
    if not result.get("description"):
        if result.get("pdp", {}).get("description_plain"):
            result["description"] = result["pdp"]["description_plain"]

    if not result.get("images"):
        result["images"] = _fallback_extract_images(soup)

    if result.get("price") is None:
        price_info = _fallback_extract_price(soup)
        for k, v in price_info.items():
            if result.get(k) is None and v is not None:
                result[k] = v

    normalized_sku = result.get("sku") or result.get("product_code")
    result["normalized_sku"] = normalized_sku

    return result


# =========================
# CrewAI Tool wrapper
# =========================

class ScrapePdpToolInput(BaseModel):
    url: str = Field(
        ...,
        description=(
            "Full product detail page URL to scrape. "
            "Example: 'https://www.adobestore.com/products/p-adb366/adb366'. "
            "The page must contain a SKU in JSON-LD or in visible text so it "
            "can be passed to the CommerceProductDataTool."
        ),
    )


class CommercePdpScraperTool(BaseTool):
    name: str = "commerce_pdp_scraper"
    description: str = (
        "Given a product detail page URL, scrape the webpage to extract product data "
        "(title, description, price, availability, images, additional properties, "
        "breadcrumbs) and SEO fields (title tag, meta description, H1, canonical, robots, page language). "
        "Returns a JSON object that includes `normalized_sku`, which should be used "
        "as the SKU input for the CommerceProductDataTool (`commerce_product_data_by_sku`)."
    )
    args_schema: Type[BaseModel] = ScrapePdpToolInput

    def _run(self, url: str) -> str:
        try:
            data = scrape_pdp(url)

            normalized_sku = data.get("normalized_sku")
            if not normalized_sku:
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
                    "seo": data.get("seo"),
                    "seo_title_format": data.get("seo_title_format"),
                    "seo_title_format_notes": data.get("seo_title_format_notes"),
                    "pdp": data.get("pdp"),
                    "raw_jsonld": data.get("raw_jsonld"),
                    "raw": data,
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
