import os
import json
from typing import Type

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
    sku: str = Field(
        ...,
        description="Product SKU to look up, e.g. 'ADB366'."
    )


class CommerceProductDataTool(BaseTool):
    """
    Fetch Adobe Commerce product data for a given SKU via the MCP HTTP server.

    Flow:
    1. POST /mcp with 'initialize' to get Mcp-Session-Id from headers
    2. POST /mcp with 'tools/call' (name='productData', arguments={'sku': sku})
    3. Parse JSON-RPC result, extract content[0].text (JSON string), json.loads(...)
    4. Re-organize into a simpler JSON structure
    5. DELETE /mcp with mcp-session-id header to close the session
    """
    name: str = "commerce_product_data_by_sku"
    description: str = (
        "Given a product SKU, fetch structured product data from the Adobe Commerce MCP "
        "server (availability, attributes, images, options, prices, etc.)."
    )
    args_schema: Type[BaseModel] = ProductDataToolInput

    def _run(self, sku: str) -> str:
        session_id = None

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
            tool_payload = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "productData",
                    "arguments": {
                        "sku": sku
                    },
                },
            }

            tool_resp = requests.post(
                COMMERCE_MCP_URL,
                headers={
                    "Content-Type": "application/json",
                    "mcp-session-id": session_id,
                },
                json=tool_payload,
                timeout=20,
            )
            tool_resp.raise_for_status()
            tool_json = tool_resp.json()

            # Expected shape (simplified):
            # {
            #   "jsonrpc": "2.0",
            #   "id": 3,
            #   "result": {
            #     "content": [
            #       {"type": "text", "text": "<JSON STRING HERE>"}
            #     ]
            #   }
            # }
            result = tool_json.get("result", {})
            content_items = result.get("content", []) or []

            text_chunks = [
                item.get("text", "")
                for item in content_items
                if item.get("type") == "text"
            ]
            if not text_chunks:
                raise RuntimeError("No 'text' content returned from tools/call result")

            # The first text chunk is the JSON string you showed in the example
            raw_text = text_chunks[0]
            raw_payload = json.loads(raw_text)  # This has 'message' and 'products'

            # 3) Organize the product JSON into something friendlier
            organized = self._organize_product_payload(sku, raw_payload)

            # Return as JSON string so the LLM can consume it easily
            return json.dumps(organized, ensure_ascii=False)

        except Exception as e:
            # Tool should never throw uncaught exceptions to the agent;
            # instead, return a structured error that the LLM can reason about.
            return json.dumps(
                {
                    "error": str(e),
                    "sku": sku,
                    "source": "CommerceProductDataTool",
                },
                ensure_ascii=False,
            )

        finally:
            # 4) Always try to delete the session if we managed to get one
            if session_id:
                try:
                    requests.delete(
                        COMMERCE_MCP_URL,
                        headers={"mcp-session-id": session_id},
                        timeout=5,
                    )
                except Exception:
                    # Don't mask the main result with cleanup errors
                    pass

    @staticmethod
    def _organize_product_payload(sku: str, payload: dict) -> dict:
        """
        Take the decoded payload from the MCP tool response (your example)
        and reshape it into a cleaner structure while preserving 'raw' for debugging.
        """
        products = payload.get("products", []) or []

        organized = {
            "sku": sku,
            "message": payload.get("message"),
            "products_count": len(products),
            "products": [],
            "raw": payload,  # keep original for debugging / full fidelity
        }

        for p in products:
            # Attributes as name->value map
            attributes_map = {
                attr.get("name"): attr.get("value")
                for attr in (p.get("attributes") or [])
            }

            # Image URLs as a flat list
            image_urls = [img.get("url") for img in (p.get("images") or []) if img.get("url")]

            # Options grouped by id
            options_map = {}
            for opt in (p.get("options") or []):
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
                        }
                        for v in (opt.get("values") or [])
                    ],
                }

            price_range = p.get("priceRange") or {}
            minimum = price_range.get("minimum") or {}
            maximum = price_range.get("maximum") or {}

            def _amt(node, kind):
                return (
                    (((node.get(kind) or {}).get("amount") or {}).get("value"))
                )

            def _currency(node, kind):
                return (
                    (((node.get(kind) or {}).get("amount") or {}).get("currency"))
                )

            organized["products"].append(
                {
                    "sku": p.get("sku"),
                    "name": p.get("name"),
                    "shortDescription": p.get("shortDescription"),
                    "description_html": p.get("description"),
                    "inStock": p.get("inStock"),
                    "addToCartAllowed": p.get("addToCartAllowed"),
                    "lowStock": p.get("lowStock"),
                    "attributes": attributes_map,
                    "images": image_urls,
                    "options": options_map,
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
                    # Keep raw per-product for maximum fidelity if the agent needs more fields
                    "raw": p,
                }
            )

        return organized
