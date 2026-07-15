> **⚠️ ARCHIVED — This actor has been deleted from Apify and is no longer maintained.**

# Fiverr Scraper

Scrape Fiverr gigs, search results, and seller profiles at scale. Search by keyword, extract full gig details (packages, FAQ, reviews), or scrape seller profiles. No API keys, no login required.

## What does it do?

The Fiverr Scraper pulls structured data from Fiverr.com — the world's largest freelance marketplace. It handles PerimeterX bot protection using full browser rendering with Playwright and Apify Residential proxies, giving you clean, consistent JSON output ready for market research, competitor analysis, lead generation, or AI pipelines.

**Three modes in one actor:**

- **🔍 Search Gigs** — search by keyword, extract gig cards with pricing, ratings, seller info, and delivery times. Batch search multiple keywords in one run.
- **📄 Gig Details** — provide full gig URLs, get complete details: descriptions, all package tiers with prices, FAQ, seller stats, and optional recent reviews.
- **👤 Seller Profiles** — scrape seller profile pages for stats, badges, bio, languages, and skills.

## 👥 Who Uses This

### 🏢 Market Researchers and Analysts

You need to understand the freelance marketplace — what services are offered, at what price points, by which sellers. The Fiverr Scraper lets you track pricing trends, identify high-demand categories, and map the competitive landscape across gig economy verticals.

**Track pricing in a category:**

```json
{
    "mode": "search_gigs",
    "searchQueriesList": ["web scraping", "data entry", "logo design", "Python script"],
    "searchSort": "best_selling",
    "maxResults": 500
}
```

Run on a daily or weekly schedule to track category-level pricing shifts over time.

---

### 💼 Lead Generation and Sales Teams

You want to find Fiverr sellers offering services related to your product or partnership opportunity. Search for relevant keywords, extract seller profiles and contact signals, and build targeted outreach lists.

**Find top sellers in a niche:**

```json
{
    "mode": "search_gigs",
    "searchQuery": "AI chatbot development",
    "searchSort": "recommended",
    "maxResults": 200
}
```

Then switch to seller profile mode to get detailed stats on high-potential leads.

---

### 🧪 Data Scientists and AI Engineers

You need structured marketplace data for training pricing models, building recommendation systems, or analyzing the gig economy. The consistent JSON output (prices, ratings, descriptions, seller stats) is ready for feature engineering without post-processing.

**Build a pricing dataset:**

```json
{
    "mode": "gig_details",
    "gigUrls": ["https://www.fiverr.com/seller1/gig-name", "https://www.fiverr.com/seller2/another-gig"],
    "includeReviews": true
}
```

---

### 🛠️ Product and Strategy Teams

You're evaluating entering a new service category on Fiverr. Use the scraper to understand what's already offered, at what price, and by whom. The batch search feature lets you sweep multiple query terms in one run for a comprehensive category analysis.

## Input

| Field | Type | Default | Description |
|---|---|---|---|
| `mode` | select | `search_gigs` | 🎯 Scraping mode |
| `searchQuery` | string | — | 🔍 Single search keyword |
| `searchQueriesList` | array (JSON) | `[]` | 🔍 Batch search queries |
| `searchSort` | select | `recommended` | 🔃 Sort order |
| `minPrice` | number | — | 💰 Minimum price filter |
| `maxPrice` | number | — | 💰 Maximum price filter |
| `deliveryTime` | select | `any` | ⏱️ Delivery time filter |
| `category` | string | — | 📂 Fiverr category filter |
| `gigUrls` | array | `[]` | 📄 Gig URLs for detail mode |
| `sellerUrls` | array | `[]` | 👤 Seller profile URLs |
| `includeReviews` | boolean | `false` | ⭐ Include reviews in gig details |
| `maxResults` | integer | 100 | 🔢 Max results (free: 25 limit) |
| `maxPages` | integer | 10 | 📄 Max search pages per query |
| `proxyConfiguration` | proxy | Residential | 🔒 Proxy config |

## Output

Each record has a `type` field: `gig_search`, `gig_detail`, or `seller_profile`.

### Search Results (`gig_search`) — $2.00 / 1,000 records

| Field | Type | Description |
|---|---|---|
| `title` | string | Gig title |
| `sellerUsername` | string | Fiverr seller username |
| `sellerLevel` | string | Seller level (Top Rated, Level 2, etc.) |
| `price` | number | Gig starting price in USD |
| `rating` | number | Rating (0–5) |
| `reviewCount` | integer | Number of reviews |
| `deliveryTime` | string | Estimated delivery time |
| `url` | string | Gig permalink |
| `tags` | array | Gig categories/tags |
| `isPro` | boolean | Fiverr Pro verified |
| `isPromoted` | boolean | Promoted listing |
| `searchKeyword` | string | The keyword that produced this result |

### Gig Details (`gig_detail`) — $3.00 / 1,000 records

All search fields plus:

| Field | Type | Description |
|---|---|---|
| `description` | string | Full gig description |
| `packages` | array | All pricing tiers (name, price, delivery, description) |
| `faq` | array | Gig FAQ items |
| `reviews` | array | Recent reviews (when `includeReviews=true`) |
| `imageUrls` | array | Gallery image URLs |
| `sellerAvatar` | string | Seller profile picture |

### Seller Profiles (`seller_profile`) — $3.00 / 1,000 records

| Field | Type | Description |
|---|---|---|
| `sellerDisplayName` | string | Seller's display name |
| `sellerDescription` | string | Seller bio |
| `sellerLevel` | string | Fiverr seller level |
| `totalOrders` | integer | Total completed orders |
| `rating` | number | Overall rating |
| `badges` | array | Seller badges |

## Cost

Typical run costs (with Apify Residential proxies):

| Scenario | Results | Est. Cost |
|---|---|---|
| Search "web scraping" (1 page, 24 gigs) | 24 | ~$0.05–0.08 |
| Search 5 keywords, 3 pages each (batch) | 360 | ~$0.70–1.00 |
| Scrape 10 gig details | 10 | ~$0.15–0.25 |
| Scrape 5 seller profiles | 5 | ~$0.10–0.15 |

Pricing is **pay-per-event** — you only pay for results you receive:

- **$2.00 / 1,000 search results** — `per-gig` event charges per gig card scraped
- **$3.00 / 1,000 detail/profile records** — `per-gig-detail` / `per-seller-profile` event
- **$0.02 / run** — `actor-start` event covers minimum compute

## Why This Scraper vs Alternatives

| Feature | **labrat011/fiverr-scraper** | igview-owner/fiverr-scraper | piotrv1001/fiverr-listings-scraper |
|---|---|---|---|
| **Price / 1k** | **$2.00** | $5.00 | $1.50 |
| **Search by keyword** | ✅ | ✅ | ✅ |
| **Batch search** | ✅ (JSON array) | — | — |
| **Gig details (full)** | ✅ | — | — |
| **Seller profiles** | ✅ | — | — |
| **Package tiers** | ✅ | — | — |
| **FAQ extraction** | ✅ | — | — |
| **Reviews** | ✅ (optional) | — | — |
| **Price + delivery filters** | ✅ | — | — |
| **Free tier (25 results)** | ✅ | — | — |
| **MCP-ready** | ✅ | — | — |

## Limitations

- **Fiverr's HTML changes** — if the scraper breaks, file a GitHub issue and we'll patch it
- **Residential proxies required** — datacenter IPs are blocked by PerimeterX
- **Rate limits** — Fiverr may throttle aggressive scraping; reasonable pagination is built in
- **Free tier capped at 25 results** — subscribe for full access

## Changelog

### v1.0.0 — Initial release
- Search Fiverr gigs by keyword (single or batch)
- Extract full gig details from individual URLs
- Scrape seller profile pages
- PerimeterX/Cloudflare bypass via Playwright + residential proxies
- Batch search with automatic query iteration
- Price and delivery time filters
- Margin circuit breaker to prevent runaway costs