import os
import json
from typing import Any, Dict, List, Optional, Type

import requests
from pydantic import BaseModel, Field
from crewai.tools import BaseTool


# You can override this via env var in different environments if needed
COMMERCE_MCP_URL = os.environ.get(
    "COMMERCE_MCP_URL",
    "https://compute-backend-p148639-e1512661-commerce-mcp.adobeaemcloud.com/mcp",
)


class ProductDataToolInput(BaseModel):
    """Input schema for the commerce product data tool."""
    sku: str = Field(..., description="Product SKU to look up, e.g. 'ADB366'.")


class CommerceProductDataTool(BaseTool):
    """
    Fetch Adobe Commerce product data for a given SKU via the Commerce Merchandising MCP HTTP server.

    Flow:
    1. POST /mcp with 'initialize' to get Mcp-Session-Id from headers
    2. POST /mcp with 'tools/call' (name='productData', arguments={'sku': sku})
    3. POST /mcp with 'tools/call' (name='productVariants', arguments={'sku': sku})
    4. Parse JSON-RPC results, extract content[0].text (JSON string), json.loads(...)
    5. Re-organize into a simpler JSON structure, preserving ALL fields from both calls
    6. DELETE /mcp with mcp-session-id header to close the session
    """
    name: str = "commerce_product_data_by_sku"
    description: str = (
        "Given a product SKU, fetch structured product data from the Adobe Commerce MCP "
        "server (availability, attributes, images, options, prices, variants, etc.)."
    )
    args_schema: Type[BaseModel] = ProductDataToolInput

    def _run(self, sku: str) -> str:
        session_id: Optional[str] = None

        try:
            # 1) Initialize MCP session
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "crewai-agent",
                        "version": "1.0.0",
                    },
                },
            }

            init_resp = requests.post(
                COMMERCE_MCP_URL,
                headers={"Content-Type": "application/json"},
                json=init_payload,
                timeout=10,
            )
            init_resp.raise_for_status()

            # MCP header is case-insensitive, but we check both common variants
            session_id = (
                init_resp.headers.get("Mcp-Session-Id")
                or init_resp.headers.get("mcp-session-id")
            )
            if not session_id:
                raise RuntimeError("Mcp-Session-Id header missing in initialize response")

            # 2) Call tools/call with productData
            product_data_payload = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "productData",
                    "arguments": {"sku": sku},
                },
            }

            product_data_json = self._call_mcp_tool(
                session_id=session_id,
                payload=product_data_payload,
                timeout=20,
            )
            product_data_raw = self._extract_text_json(product_data_json, tool_name="productData")

            # 3) Call tools/call with productVariants
            product_variants_payload = {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "productVariants",
                    "arguments": {"sku": sku},
                },
            }

            product_variants_json = self._call_mcp_tool(
                session_id=session_id,
                payload=product_variants_payload,
                timeout=25,
            )
            product_variants_raw = self._extract_text_json(product_variants_json, tool_name="productVariants")

            # 4) Organize both payloads into something friendlier (preserve full fidelity)
            organized = self._organize_combined_payload(
                sku=sku,
                product_data_payload=product_data_raw,
                product_variants_payload=product_variants_raw,
            )

            return json.dumps(organized, ensure_ascii=False)

        except Exception as e:
            return json.dumps(
                {
                    "error": str(e),
                    "sku": sku,
                    "source": "CommerceProductDataTool",
                },
                ensure_ascii=False,
            )

        finally:
            # 5) Always try to delete the session if we managed to get one
            if session_id:
                try:
                    requests.delete(
                        COMMERCE_MCP_URL,
                        headers={"mcp-session-id": session_id},
                        timeout=5,
                    )
                except Exception:
                    pass

    @staticmethod
    def _call_mcp_tool(session_id: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """POST a JSON-RPC tools/call payload and return parsed JSON response."""
        resp = requests.post(
            COMMERCE_MCP_URL,
            headers={
                "Content-Type": "application/json",
                "mcp-session-id": session_id,
            },
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_text_json(tool_json: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
        """
        MCP tools/call responses return result.content as a list, where the "text" field
        contains a JSON string. This extracts and json.loads it.

        Raises a RuntimeError if no text chunk is found or JSON is invalid.
        """
        result = tool_json.get("result", {}) or {}
        content_items = result.get("content", []) or []

        text_chunks = [
            item.get("text", "")
            for item in content_items
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if not text_chunks or not text_chunks[0]:
            raise RuntimeError(f"No 'text' content returned from tools/call result for {tool_name}")

        raw_text = text_chunks[0]
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to json.loads() text payload for {tool_name}: {e}") from e

    @staticmethod
    def _organize_combined_payload(
        sku: str,
        product_data_payload: Dict[str, Any],
        product_variants_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Reshape both MCP payloads into a cleaner structure while preserving ALL fields.

        - `product_data_payload` is expected to contain keys like: message, products[]
        - `product_variants_payload` can vary by server implementation; we keep both:
            - a lightly normalized `variants` section if we can detect a list
            - full raw payload in `raw.product_variants`
        """
        products = product_data_payload.get("products", []) or []

        organized: Dict[str, Any] = {
            "sku": sku,

            # Keep top-level messages if present
            "product_data_message": product_data_payload.get("message"),
            "product_variants_message": product_variants_payload.get("message"),

            # Normalized/organized productData portion (same as your previous behavior)
            "products_count": len(products),
            "products": [],

            # Variants: normalized best-effort + raw preserved
            "variants": {
                "count": None,
                "items": None,
                "note": (
                    "Best-effort normalization of productVariants response. "
                    "See raw.product_variants for full fidelity."
                ),
            },

            # Preserve EVERYTHING from both calls for maximum fidelity
            "raw": {
                "product_data": product_data_payload,
                "product_variants": product_variants_payload,
            },
        }

        # ----------------------------
        # Normalize productData.products
        # ----------------------------
        for p in products:
            if not isinstance(p, dict):
                continue

            # Attributes as name->value map
            attributes_map = {
                (attr.get("name") if isinstance(attr, dict) else None): (attr.get("value") if isinstance(attr, dict) else None)
                for attr in (p.get("attributes") or [])
                if isinstance(attr, dict) and attr.get("name") is not None
            }

            # Image URLs as a flat list
            image_urls = [img.get("url") for img in (p.get("images") or []) if isinstance(img, dict) and img.get("url")]

            # Options grouped by id
            options_map: Dict[str, Any] = {}
            for opt in (p.get("options") or []):
                if not isinstance(opt, dict):
                    continue
                opt_id = opt.get("id")
                if not opt_id:
                    continue
                options_map[opt_id] = {
                    "title": opt.get("title"),
                    "multi": opt.get("multi"),
                    "required": opt.get("required"),
                    "values": [
                        {
                            "title": v.get("title"),
                            "value": v.get("value"),
                            "inStock": v.get("inStock"),
                            "type": v.get("type"),
                            "id": v.get("id"),
                        }
                        for v in (opt.get("values") or [])
                        if isinstance(v, dict)
                    ],
                    "raw": opt,  # keep full option record
                }

            price_range = p.get("priceRange") or {}
            minimum = price_range.get("minimum") or {}
            maximum = price_range.get("maximum") or {}

            def _amt(node: Dict[str, Any], kind: str) -> Optional[Any]:
                return (((node.get(kind) or {}).get("amount") or {}).get("value"))

            def _currency(node: Dict[str, Any], kind: str) -> Optional[Any]:
                return (((node.get(kind) or {}).get("amount") or {}).get("currency"))

            organized["products"].append(
                {
                    # Common identifiers
                    "sku": p.get("sku"),
                    "name": p.get("name"),
                    "shortDescription": p.get("shortDescription"),
                    "description_html": p.get("description"),

                    # Inventory and commerce flags
                    "inStock": p.get("inStock"),
                    "addToCartAllowed": p.get("addToCartAllowed"),
                    "lowStock": p.get("lowStock"),

                    # Structured fields
                    "attributes": attributes_map,
                    "images": image_urls,
                    "options": options_map,

                    # Price summary
                    "price": {
                        "currency": (
                            _currency(minimum, "final")
                            or _currency(minimum, "regular")
                            or _currency(maximum, "final")
                            or _currency(maximum, "regular")
                        ),
                        "min_final": _amt(minimum, "final"),
                        "min_regular": _amt(minimum, "regular"),
                        "max_final": _amt(maximum, "final"),
                        "max_regular": _amt(maximum, "regular"),
                    },

                    # Keep raw per-product for full fidelity
                    "raw": p,
                }
            )

        # ----------------------------
        # Best-effort normalize variants
        # ----------------------------
        # Different MCP servers may return variants in different shapes.
        # We attempt common patterns and always keep raw payload.
        variants_items: Optional[List[Any]] = None

        # Common patterns:
        # - {"variants": [...]}
        # - {"items": [...]}
        # - {"products": [{"variants": [...] }]}  (less likely)
        for key in ("variants", "items", "productVariants", "product_variants"):
            v = product_variants_payload.get(key)
            if isinstance(v, list):
                variants_items = v
                break

        # Sometimes variants might be nested under a "data" key
        if variants_items is None:
            data_node = product_variants_payload.get("data")
            if isinstance(data_node, dict):
                for key in ("variants", "items"):
                    v = data_node.get(key)
                    if isinstance(v, list):
                        variants_items = v
                        break

        if variants_items is not None:
            organized["variants"]["items"] = variants_items
            organized["variants"]["count"] = len(variants_items)
        else:
            organized["variants"]["items"] = None
            organized["variants"]["count"] = 0

        return organized
