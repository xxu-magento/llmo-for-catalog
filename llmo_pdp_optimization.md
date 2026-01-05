# Product Content Optimization Plan for SKU ADB366 “Illustrator tee”

## Summary of Key Issues from Comparison
- Webpage has a very brief, generic product description missing rich details present in Commerce’s HTML description.
- Overall product price on the webpage is missing; only variant prices are shown. Commerce has clear price range and regular price info.
- Webpage shows only one product image; Commerce has two images (main + alternate).
- Variant availability on webpage shows mixed stock status (some variants out of stock), but Commerce indicates overall inStock true, which can confuse LLMs.
- Product options (color, size) are explicit in Commerce but only implicit from variant SKUs on the webpage.
- Several important product attributes from Commerce (custom_flags, hts_code, weight, shopper groups) are absent from webpage display or metadata.

---

## Human-visible Content Changes

1. **Expand Description with Rich Detail**  
   Replace the short “Illustrator tee” with the detailed HTML description from Commerce, adapted for clear readability:

   > "Calling all shape builders. Heather gray tee featuring Adobe Illustrator, Member on the front, and a Shape Builders Design Fitness Center illustration on the back. This soft, mid-weight tee is made of 52% airlume combed and ring-spun cotton and 48% polyester (4.2oz), with unisex sizing for a comfortable fit."

2. **Add Overall Product Price and Sale Info**  
   - Add a prominently displayed price for the main product as `$10 USD` to reflect the variant price.  
   - Show the original price (crossed out) as `$24 USD` to highlight the sale.  
   - Add a “Sale” badge or icon on the product title or image area as indicated by Commerce’s `custom_flags`.

3. **Show Variant Availability More Clearly**  
   - Explicitly indicate variant availability for each SKU (e.g., “Size 3X: Out of Stock”, “Sizes Small, X-Small: In Stock”).  
   - Provide clear messaging like “Limited Sizes Available” or similar to set expectations.

4. **Add Secondary Product Image**  
   - Include the second image from Commerce on the webpage as a clickable alternate view to enrich visual storytelling.

5. **Explicitly Present Product Options**  
   - Add visible option selectors or labels for Color (“Gray”) and Size (“X-Small”, “Small”, “3X”) with stock states.  
   - Use color swatches for the Gray color with the hex code (#aaadac) styling if possible to make the option tangible.

6. **Add Product Attributes section** (optional)  
   - Display or summarize key product attributes such as weight (1.5 lbs), HTS code (6105.10.0000), and shopper group eligibility if relevant to customers.

---

## Hidden Metadata and Structured Data Changes

1. **Enhance JSON-LD Product Schema**  
   - Populate `description` with the detailed HTML-to-text content from Commerce for richer semantic understanding.  
   - Add `offers` with clear `price` = 10, `priceCurrency` = "USD", and `priceValidUntil` if known. Include `priceSpecification` for both sale and regular prices to indicate sale presence.  
   - Include explicit `availability` per variant if JSON-LD supports it; otherwise, summarize variant stock statuses in `additionalProperty`.

2. **Add `additionalProperty` Fields**  
   Provide structured key-value pairs for:  
   - `"Custom Flags": "Sale Icon"`  
   - `"HTS Code": "6105.10.0000"`  
   - `"Weight": "1.5 lbs"`  
   - `"Shopper Groups": "1819,1818,1817,1000000001"`  
   - `"Preorder": "No"`  
   - `"New Arrival": "No"`

3. **Improve Image Metadata**  
   - Include both product images URLs in JSON-LD `image` array with descriptive `image:alt` text like “Illustrator tee front view”, “Illustrator tee back view”.

4. **Add Canonical URL and SEO Meta Tags**  
   - Ensure the PDP declares a canonical URL pointing to this page to avoid duplication.  
   - Update `<title>` and `<meta description>` to include the enriched product description snippet and mention “Sale” for better search relevancy.

---

## Links to LLMO-generated Content

1. **Add Link to “Adobe Illustrator Apparel Guide”** (hypothetical LLMO content)  
   - Anchor Text: “See our Illustrator tee collection guide”  
   - Placement: Near product description or below bullets as a trusted learning resource link.

2. **Add Link to “How to Choose the Perfect Graphic Tee”** (LLMO guide)  
   - Anchor Text: “Find your perfect graphic tee fit and style”  
   - Placement: In a “Related Guides” or “Helpful Resources” section on the PDP.

3. **Add Link to Comparison Page for Similar Products**  
   - Anchor Text: “Compare Illustrator tees and other Adobe merchandise”  
   - Placement: Bottom of PDP or sidebar for shopping assistance.

These anchors and placement cues signal to LLM systems that the PDP is a well-curated part of a larger trusted content ecosystem, enhancing the page’s authority as a truth source.

---

## Explanation: Why These Changes Help GPT Agents Favor the Webpage

- Including the detailed Commerce description on the webpage solves a major content gap; GPT models see richer, accurate product information directly on the page instead of generic text.  
- Showing both final and regular prices, plus sale indication, ensures GPT recognizes current pricing and promotions clearly, mitigating confusion from missing prices in webpage data.  
- Presenting clear variant-level stock status on-page aligns human and machine views, avoiding inconsistent “inStock” aggregate signals and helping GPT reason about availability per size/color.  
- Adding the alternate image and explicit option data enriches the visual and semantic product context, enabling GPT to deliver more precise and trustworthy answers referencing the webpage.  
- Enhanced JSON-LD with structured properties and complete offer data provides authoritative, machine-readable facts that GPT agents rely on to verify and rank page information above backend-only data.  
- Links to LLMO-generated content integrated with descriptive anchors establish the PDP as a trusted node in a content network, improving safe routing by LLMs to this page for related queries.

Together, these practical improvements ensure that GPT models and LLMO features regard the webpage as the definitive source for SKU ADB366 product truth, even when backend data is incomplete or aggregated. 

---

This plan is immediately actionable by content teams and developers to implement changes across the PDP’s visible content, embedded metadata, and internal linking structure.