"""Fiverr Scraper — Playwright-based scraping logic.

Fiverr uses PerimeterX (PX) + Cloudflare bot protection. All requests
must go through a full browser session with residential proxies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from typing import Any, AsyncGenerator
from urllib.parse import urljoin, urlparse

from apify import Actor

from .models import (
    ScraperInput,
    ScrapingMode,
)

logger = logging.getLogger(__name__)

# --- Constants ---

FIVERR_BASE = "https://www.fiverr.com"
SEARCH_URL = f"{FIVERR_BASE}/search/gigs"

# Free tier limit
FREE_TIER_LIMIT = 25

# Navigate timeout. Fiverr responds fast when it responds at all; a 90s
# wait mostly just delays hitting the PerimeterX challenge path. Keep it
# tight so 3 attempts can't burn 4+ minutes before the challenge handler runs.
NAV_TIMEOUT_MS = 45000

# How many seconds to wait after page load for dynamic content
POST_NAV_WAIT_SECS = 3.0

# Max seconds to wait for Cloudflare challenge to resolve (commit strategy)
CF_CHALLENGE_MAX_WAIT = 20.0

# Max retries per navigation
MAX_NAV_RETRIES = 2

# Scroll delay to trigger lazy loading
SCROLL_DELAY_SECS = 1.0

# Text markers that mean the page is a bot/challenge wall, not real content.
# Fiverr fronts with PerimeterX ("It needs a human touch" / ERRCODE PXCR...)
# and occasionally Cloudflare. Keep this list authoritative — both the
# detector and the post-nav guard read from it.
CHALLENGE_MARKERS = [
    "please verify you are a human",
    "access denied",
    "sorry, you have been blocked",
    "automated access",
    "perimeterx",
    "human verification",
    "just a moment",
    "checking your browser",
    "cf-error",
    "cf-browser-verification",
    "cloudflare",
    # PerimeterX current block page
    "it needs a human touch",
    "needs a human touch",
    "loading challenge",
    "pxcr",
    "px-captcha",
    "complete the task and we",
]


# --- Selectors ---
# Fiverr's DOM structure changes frequently, so we use multiple fallback selectors.

# Gig card selectors (search results)
GIG_CARD_SELECTORS = [
    '[class*="gig-card"]',
    '[class*="GigCard"]',
    '[data-testid*="gig"]',
    '[class*="gig-wrapper"]',
    '[class*="search-result"]',
    "article",
    '[class*="card-wrapper"]',
    '[class*="marketplace"]',
]

# Gig title selectors
TITLE_SELECTORS = [
    '[class*="gig-title"] a',
    '[class*="title"] a',
    "h2 a",
    "h3 a",
    '[class*="name"] a',
    "a[class*='title']",
]

# Price selectors
PRICE_SELECTORS = [
    '[class*="price"]',
    '[class*="Price"]',
    '[class*="gig-price"]',
    '[class*="starting-at"]',
    '[class*="price-badge"]',
    "span[class*='price']",
    '[data-testid*="price"]',
]

# Seller name selectors
SELLER_SELECTORS = [
    '[class*="seller-name"]',
    '[class*="username"]',
    '[class*="user-name"]',
    "a[class*='seller']",
    '[class*="Seller"]',
    "span[class*='name']",
    "a[class*='avatar']",
]

# Rating selectors
RATING_SELECTORS = [
    '[class*="rating"]',
    '[class*="Rating"]',
    '[class*="star-rating"]',
    "span[aria-label*='star']",
    "span[class*='star']",
]

# Delivery time selectors
DELIVERY_SELECTORS = [
    '[class*="delivery"]',
    '[class*="Delivery"]',
    '[class*="delivery-time"]',
    "span[class*='duration']",
]

# Description selectors
DESC_SELECTORS = [
    '[class*="description"]',
    '[class*="desc"]',
    "p[class*='desc']",
]

# Pagination selectors
NEXT_PAGE_SELECTORS = [
    'a[class*="next"]',
    'a[aria-label="Next"]',
    'a[rel="next"]',
    '[class*="pagination"] a:last-child',
    '[class*="page-navigation"] a:last-child',
    "button[class*='next']",
    "a[class*='chevron-right']",
]

# Gig detail page selectors
GIG_TITLE_SELECTOR = "h1"
GIG_DESC_SELECTOR = '[class*="description"]'
PACKAGE_SELECTORS = [
    '[class*="package"]',
    '[class*="Package"]',
    '[class*="pricing-card"]',
    '[class*="PricingCard"]',
    '[class*="tier"]',
]
REVIEW_SELECTORS = [
    '[class*="review"]',
    '[class*="Review"]',
    '[class*="rating-wrapper"]',
]
FAQ_SELECTORS = [
    '[class*="faq"]',
    '[class*="FAQ"]',
    '[class*="accordion"]',
]

# Seller profile selectors
SELLER_BIO_SELECTOR = '[class*="seller-description"]'
SELLER_STATS_SELECTORS = [
    '[class*="seller-stats"]',
    '[class*="profile-stats"]',
]


class FiverrScraper:
    """Playwright-based Fiverr scraper with anti-bot resilience."""

    def __init__(
        self,
        config: ScraperInput,
        max_pages: int = 10,
        max_results: int = 100,
    ) -> None:
        self.config = config
        self.max_pages = max_pages
        self.max_results = max_results
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> "FiverrScraper":
        from apify import Actor
        proxy_config = await Actor.create_proxy_configuration(
            actor_proxy_input=self.config.proxy_configuration
        )
        proxy_url = await proxy_config.new_url() if proxy_config else None

        # Prefer Patchright (undetected Playwright fork) — it patches the
        # CDP/runtime leaks PerimeterX fingerprints on. Fall back to vanilla
        # Playwright if Patchright isn't installed (e.g. local dev).
        try:
            from patchright.async_api import async_playwright
            self._engine = "patchright"
        except ImportError:
            from playwright.async_api import async_playwright
            self._engine = "playwright"
        logger.info(f"Browser engine: {self._engine}")

        self._playwright = await async_playwright().start()

        # Container-safe args only. Under Patchright the classic "stealth" flags
        # (--disable-blink-features=AutomationControlled, --disable-web-security)
        # are counterproductive — they are themselves detectable and Patchright
        # already neutralizes the automation signals they targeted.
        base_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
        ]
        if self._engine == "playwright":
            base_args += [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-web-security",
                "--disable-infobars",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--window-size=1920,1080",
            ]
        launch_options = {"headless": True, "args": base_args}
        if proxy_url:
            launch_options["proxy"] = {"server": proxy_url}

        self._browser = await self._playwright.chromium.launch(**launch_options)

        # Randomize viewport slightly per session
        viewport_w = random.randint(1850, 1920)
        viewport_h = random.randint(950, 1080)

        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": viewport_w, "height": viewport_h},
            device_scale_factor=1,
            locale="en-US",
            timezone_id="America/New_York",
            has_touch=False,
            is_mobile=False,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Ch-Ua": '"Not/A)Brand";v="99", "Google Chrome";v="126", "Chromium";v="126"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )

        # Manual stealth init script — ONLY for vanilla Playwright. Patchright
        # injects its masks into an isolated world; a main-world init script
        # like this one is itself a detectable fingerprint, so we skip it.
        if self._engine == "playwright":
            await self._context.add_init_script("""
                // Override navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', { get: () => false });

                // Override navigator.plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });

                // Override navigator.languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });

                // Override chrome.runtime
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };

                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : originalQuery(parameters)
                );

                // Remove webdriver trace from stack traces
                Error.stackTraceLimit = Infinity;
            """)

        # Block unnecessary resources AFTER stealth init
        # NOTE: Not blocking resources initially — Cloudflare challenge may
        # need JS/CSS to complete. Blocking is applied per-page in _navigate
        # after content is confirmed human-readable.
        self._resource_blocking_enabled = False

        self._page = await self._context.new_page()
        self._page.set_default_timeout(NAV_TIMEOUT_MS)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _enable_resource_blocking(self) -> None:
        """Block unnecessary resources (images, fonts, analytics, tracking)
        AFTER content is confirmed human-readable (not a challenge page).
        """
        await self._context.route(
            re.compile(r"\.(png|jpg|jpeg|gif|svg|woff2?|ttf|eot)(\?.*)?$"),
            lambda route: route.abort(),
        )
        await self._context.route(
            re.compile(
                r"(analytics|tracking|beacon|sentry|logrocket|fullstory)"
                r"\.(js|gif)",
                re.IGNORECASE
            ),
            lambda route: route.abort(),
        )
        self._resource_blocking_enabled = True

    async def _detect_challenge_page(self) -> bool:
        """Check if the current page is a Cloudflare / PerimeterX challenge."""
        try:
            page_text = await self._page.inner_text("body")
        except Exception:
            page_text = ""
        # Title often carries the block signal even when body is still a spinner.
        title = (await self._page.title() or "").lower()
        haystack = f"{title}\n{page_text}".lower()
        return any(marker in haystack for marker in CHALLENGE_MARKERS)

    async def _wait_for_challenge_to_resolve(self) -> bool:
        """Poll for Cloudflare challenge resolution up to CF_CHALLENGE_MAX_WAIT.
        Returns True if the challenge resolved (page now shows real content).
        """
        logger.info(
            f"Cloudflare challenge detected. "
            f"Waiting up to {CF_CHALLENGE_MAX_WAIT}s for resolution..."
        )
        deadline = time.monotonic() + CF_CHALLENGE_MAX_WAIT
        poll_interval = 2.0
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)
            if not await self._detect_challenge_page():
                logger.info("Cloudflare challenge resolved.")
                return True
            # Also check if the URL redirected to actual Fiverr content
            current_url = self._page.url
            if "captcha" in current_url.lower() or "challenge" in current_url.lower():
                continue  # Still on challenge page
            if current_url.startswith(FIVERR_BASE):
                # Still on Fiverr but challenge might have passed
                continue
        logger.warning(f"Cloudflare challenge did not resolve within {CF_CHALLENGE_MAX_WAIT}s.")
        return False

    async def _check_page_content(self) -> bool:
        """Return True if the page has real content (not blank/blocked).
        Checks body for meaningful content length.
        """
        try:
            body_text = await self._page.inner_text("body")
            return len(body_text.strip()) > 100
        except Exception:
            return False

    async def _navigate(
        self, url: str, wait_for_selector: str | None = None
    ) -> bool:
        """Navigate to a URL and wait for content.

        Retries with fallback wait strategies if initial load fails.
        On commit strategy, actively waits for Cloudflare challenges to resolve
        before enabling resource blocking and checking for actual content.
        Returns True if we detect real Fiverr content.
        """
        # "commit" fires as soon as the response arrives, so we reach the
        # PerimeterX challenge handler immediately instead of waiting out a
        # 45s timeout on domcontentloaded/load (which the challenge page can
        # stall indefinitely). "load" is intentionally omitted: it is stricter
        # than domcontentloaded and only ever slows us down on Fiverr's SPA.
        wait_strategies = ["commit", "domcontentloaded", "commit"]

        for attempt in range(1 + MAX_NAV_RETRIES):
            strategy = wait_strategies[min(attempt, len(wait_strategies) - 1)]
            try:
                logger.info(
                    f"Navigating to: {url} "
                    f"(attempt {attempt + 1}/{1 + MAX_NAV_RETRIES}, "
                    f"wait_until={strategy})"
                )

                resp = await self._page.goto(
                    url,
                    wait_until=strategy,
                    timeout=NAV_TIMEOUT_MS,
                )

                if resp is None and strategy != "commit":
                    logger.warning(f"Null response from {url}, retrying...")
                    await asyncio.sleep(2 ** attempt)
                    continue

                # Wait a beat for dynamic content
                await asyncio.sleep(POST_NAV_WAIT_SECS)

                # --- Bot-challenge handling ---
                # PerimeterX / Cloudflare can serve a challenge under ANY wait
                # strategy (the page "loads" but shows a wall), so handle it on
                # every attempt, not only on "commit".
                if await self._detect_challenge_page():
                    logger.info(
                        f"Challenge page detected (strategy={strategy}). "
                        f"Waiting for resolution..."
                    )
                    resolved = await self._wait_for_challenge_to_resolve()
                    if not resolved:
                        logger.error(
                            f"Challenge did not resolve for {url}. "
                            "PerimeterX is blocking this session — a residential "
                            "proxy and/or a stealth browser engine is required. "
                            "Retrying with a fresh strategy."
                        )
                        # Let the retry loop try again (new proxy URL / strategy)
                        if attempt < MAX_NAV_RETRIES:
                            await asyncio.sleep(3 * (2 ** attempt))
                            continue
                        return False
                    # Challenge resolved — now we should be on the actual page
                    await asyncio.sleep(POST_NAV_WAIT_SECS)

                    # Check if we still see a challenge
                    if await self._detect_challenge_page():
                        logger.error(
                            f"Still on challenge page after {CF_CHALLENGE_MAX_WAIT}s "
                            f"for {url}"
                        )
                        return False

                # --- Enable deferred resource blocking ---
                # Only block resources AFTER Cloudflare challenge resolved
                if not self._resource_blocking_enabled:
                    await self._enable_resource_blocking()

                # Check page URL — detect redirects to captcha/bot pages
                current_url = self._page.url
                if "captcha" in current_url.lower() or "challenge" in current_url.lower():
                    logger.warning(f"Redirected to captcha/challenge page at {current_url}")
                    return False

                # Check for bot detection text
                try:
                    page_text = await self._page.inner_text("body")
                except Exception:
                    page_text = ""

                if any(
                    marker in page_text.lower() for marker in CHALLENGE_MARKERS
                ):
                    logger.warning(f"Bot detection triggered at {url}")
                    return False

                # Check page has actual content
                if not await self._check_page_content():
                    logger.warning(
                        f"Page loaded but has no meaningful content at {url}"
                    )
                    if strategy != "commit":
                        # Try next strategy
                        continue
                    return False

                if wait_for_selector:
                    try:
                        await self._page.wait_for_selector(
                            wait_for_selector, timeout=15000
                        )
                    except Exception:
                        logger.warning(
                            f"Timeout waiting for selector: {wait_for_selector}"
                        )

                return True

            except Exception as e:
                logger.warning(
                    f"Navigation error to {url} "
                    f"(attempt {attempt + 1}, wait={strategy}): {e}"
                )
                if attempt < MAX_NAV_RETRIES:
                    delay = 3 * (2 ** attempt)  # 3s, 6s
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"All {MAX_NAV_RETRIES + 1} navigation attempts "
                        f"failed for {url}"
                    )

        return False

    async def _extract_text(
        self, element: Any, selector: str
    ) -> str:
        """Try to extract text from an element using a CSS selector."""
        try:
            el = await element.query_selector(selector)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return ""

    async def _extract_text_multi(
        self, element: Any, selectors: list[str]
    ) -> str:
        """Try multiple selectors to extract text from an element."""
        for selector in selectors:
            try:
                el = await element.query_selector(selector)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    async def _extract_href_multi(
        self, element: Any, selectors: list[str]
    ) -> str:
        """Try multiple selectors to extract an href from an element."""
        for selector in selectors:
            try:
                el = await element.query_selector(selector)
                if el:
                    href = await el.get_attribute("href")
                    if href:
                        return urljoin(FIVERR_BASE, href)
            except Exception:
                continue
        return ""

    async def _get_attribute_multi(
        self, element: Any, selectors: list[str], attr: str = "src"
    ) -> str:
        """Try multiple selectors to extract an attribute from an element."""
        for selector in selectors:
            try:
                el = await element.query_selector(selector)
                if el:
                    val = await el.get_attribute(attr)
                    if val:
                        return val
            except Exception:
                continue
        return ""

    async def _scroll_page(self) -> None:
        """Scroll the page to trigger lazy loading."""
        try:
            await self._page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await asyncio.sleep(SCROLL_DELAY_SECS)
        except Exception:
            pass

    async def _has_next_page(self) -> bool:
        """Check if there's a next page of search results."""
        for selector in NEXT_PAGE_SELECTORS:
            try:
                el = await self._page.query_selector(selector)
                if el:
                    disabled = await el.get_attribute("disabled")
                    classes = await el.get_attribute("class") or ""
                    if disabled or "disabled" in classes:
                        continue
                    return True
            except Exception:
                continue
        return False

    async def _extract_gig_card(self, card: Any) -> dict[str, Any]:
        """Extract data from a single gig card element."""
        title = await self._extract_href_multi(card, TITLE_SELECTORS)
        title_text = await self._extract_text_multi(card, TITLE_SELECTORS)
        price_str = await self._extract_text_multi(card, PRICE_SELECTORS)
        seller = await self._extract_text_multi(card, SELLER_SELECTORS)
        rating_str = await self._extract_text_multi(card, RATING_SELECTORS)
        delivery = await self._extract_text_multi(card, DELIVERY_SELECTORS)
        desc = await self._extract_text_multi(card, DESC_SELECTORS)

        # Parse price
        price = self._parse_price(price_str)

        # Parse rating
        rating = self._parse_rating(rating_str)
        review_count = self._parse_review_count(rating_str)

        # Extract tags
        tags = await self._get_tags(card)

        # Extract image URL
        img_el = await card.query_selector("img")
        img_url = ""
        if img_el:
            img_url = await img_el.get_attribute("src") or ""

        return {
            "title": title_text,
            "url": title,
            "price": price,
            "priceString": price_str,
            "sellerUsername": seller,
            "rating": rating,
            "reviewCount": review_count,
            "deliveryTime": delivery,
            "description": desc,
            "tags": tags,
            "imageUrl": img_url,
        }

    def _parse_price(self, text: str) -> float:
        if not text:
            return 0.0
        text = text.replace("from", "").replace("US$", "$").strip()
        match = re.search(r"\$?(\d+(?:,\d{3})*(?:\.\d{1,2})?)", text)
        if match:
            return float(match.group(1).replace(",", ""))
        return 0.0

    def _parse_rating(self, text: str) -> float:
        if not text:
            return 0.0
        match = re.search(r"(\d+\.?\d*)\s*(?:star|out of|/|rating)?", text, re.I)
        if match:
            val = float(match.group(1))
            if val > 5:
                val = val / 100  # Some display as percentage
            return round(min(val, 5.0), 1)
        return 0.0

    def _parse_review_count(self, text: str) -> int:
        if not text:
            return 0
        # Pattern: "(X)" or "X reviews" or "X ratings"
        match = re.search(r"\((\d+(?:\.\d+)?[KkMmBb]?)\)", text)
        if match:
            return self._parse_count(match.group(1))
        match = re.search(
            r"(\d+(?:\.\d+)?[KkMmBb]?)\s*(?:reviews|ratings)", text, re.I
        )
        if match:
            return self._parse_count(match.group(1))
        return 0

    def _parse_count(self, text: str) -> int:
        text = text.upper().strip()
        multiplier = 1
        if text.endswith("K"):
            multiplier = 1000
            text = text[:-1]
        elif text.endswith("M"):
            multiplier = 1000000
            text = text[:-1]
        elif text.endswith("B"):
            multiplier = 1000000000
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except (ValueError, TypeError):
            return 0

    async def _get_tags(self, card: Any) -> list[str]:
        """Extract tag/category text from a gig card."""
        tags = []
        try:
            for selector in [
                '[class*="tag"]',
                '[class*="badge"]',
                '[class*="category"]',
                "span[class*='subcategory']",
            ]:
                elements = await card.query_selector_all(selector)
                for el in elements:
                    text = (await el.inner_text()).strip()
                    if text:
                        tags.append(text)
        except Exception:
            pass
        return tags

    # --- Public Scrape Methods ---

    async def search_gigs(
        self, keyword: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Scrape Fiverr gig search results for a keyword."""
        count = 0
        for page_num in range(1, self.max_pages + 1):
            if count >= self.max_results:
                break

            search_url = f"{SEARCH_URL}?query={keyword}&page={page_num}"

            ok = await self._navigate(search_url)
            if not ok:
                logger.warning(
                    f"Failed to load search page for '{keyword}' "
                    f"page {page_num}"
                )
                break

            # Scroll a couple times to trigger lazy loading
            await self._scroll_page()
            await self._scroll_page()

            # Try to find gig cards
            gig_cards = []
            for selector in GIG_CARD_SELECTORS:
                try:
                    cards = await self._page.query_selector_all(selector)
                    if cards and len(cards) > 1:
                        gig_cards = cards
                        logger.info(
                            f"Found {len(cards)} gigs with "
                            f"selector: {selector}"
                        )
                        break
                except Exception:
                    continue

            if not gig_cards:
                # Fallback: try to get any clickable links in main content
                logger.warning(
                    f"No gig cards found for '{keyword}' page {page_num}. "
                    "Page may be blocked or empty."
                )
                break

            for card in gig_cards:
                if count >= self.max_results:
                    break

                gig = await self._extract_gig_card(card)
                gig["searchKeyword"] = keyword
                gig["gigId"] = f"search-{keyword}-{page_num}-{count}"
                gig["page"] = page_num
                yield gig
                count += 1

            # Check for next page
            if not await self._has_next_page():
                break

        logger.info(
            f"Search '{keyword}' completed: {count} gigs "
            f"across {page_num} pages"
        )

    async def gig_details(
        self, urls: list[str], include_reviews: bool = False
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Scrape full details from individual gig pages."""
        for idx, url in enumerate(urls):
            if not url:
                continue

            ok = await self._navigate(url, wait_for_selector="h1")
            if not ok:
                logger.warning(f"Failed to load gig page: {url}")
                continue

            await asyncio.sleep(POST_NAV_WAIT_SECS)

            gig_detail: dict[str, Any] = {
                "url": url,
                "description": "",
                "packages": [],
                "faq": [],
                "tags": [],
                "imageUrls": [],
                "reviews": [],
            }

            # Title
            try:
                title_el = await self._page.query_selector("h1")
                if title_el:
                    gig_detail["title"] = (await title_el.inner_text()).strip()
            except Exception:
                pass

            # Description
            for sel in [
                '[class*="description"]',
                '[class*="Description"]',
                "section[class*='desc']",
                "div[class*='desc']",
            ]:
                try:
                    el = await self._page.query_selector(sel)
                    if el:
                        gig_detail["description"] = (
                            await el.inner_text()
                        ).strip()
                        gig_detail["descriptionHtml"] = (
                            await el.inner_html()
                        ).strip()
                        break
                except Exception:
                    continue

            # Packages / tiers
            packages = []
            for sel in PACKAGE_SELECTORS:
                try:
                    package_els = await self._page.query_selector_all(sel)
                    for pel in package_els:
                        pkg_text = (await pel.inner_text()).strip()
                        if pkg_text:
                            pkg_name = await self._extract_text(
                                pel, "h3, h4, [class*='title']"
                            )
                            pkg_price = await self._extract_text_multi(
                                pel, PRICE_SELECTORS
                            )
                            pkg_desc = await self._extract_text_multi(
                                pel,
                                [
                                    "p",
                                    '[class*="description"]',
                                    '[class*="desc"]',
                                ],
                            )
                            pkg_delivery = await self._extract_text_multi(
                                pel,
                                [
                                    '[class*="delivery"]',
                                    '[class*="Delivery"]',
                                ],
                            )
                            packages.append({
                                "name": pkg_name,
                                "price": self._parse_price(pkg_price),
                                "priceString": pkg_price,
                                "description": pkg_desc,
                                "deliveryTime": pkg_delivery,
                            })
                            break
                    if packages:
                        break
                except Exception:
                    continue
            gig_detail["packages"] = packages

            # FAQ
            faq_items = []
            for sel in FAQ_SELECTORS:
                try:
                    faq_els = await self._page.query_selector_all(
                        f"{sel} [class*='item'], "
                        f"{sel} [class*='question'], "
                        f"{sel} li"
                    )
                    for fel in faq_els:
                        q_text = (await fel.inner_text()).strip()
                        if q_text:
                            faq_items.append(q_text)
                    if faq_items:
                        break
                except Exception:
                    continue
            gig_detail["faq"] = faq_items

            # Reviews
            if include_reviews:
                reviews = []
                for sel in REVIEW_SELECTORS:
                    try:
                        review_els = (
                            await self._page.query_selector_all(sel)
                        )
                        for rel in review_els[:5]:
                            rev_text = (await rel.inner_text()).strip()
                            if rev_text:
                                reviews.append(rev_text)
                        if reviews:
                            break
                    except Exception:
                        continue
                gig_detail["reviews"] = reviews

            # Seller info from page
            gig_detail["sellerUsername"] = self._extract_seller_from_url(url)

            # Images
            try:
                imgs = await self._page.query_selector_all(
                    "img[class*='gallery'], "
                    "img[class*='portfolio'], "
                    "div[class*='gallery'] img"
                )
                gig_detail["imageUrls"] = [
                    await img.get_attribute("src") or ""
                    for img in imgs[:10]
                ]
            except Exception:
                pass

            yield gig_detail

    async def seller_profiles(
        self, urls: list[str]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Scrape seller profile pages."""
        for url in urls:
            if not url:
                continue

            ok = await self._navigate(url)
            if not ok:
                logger.warning(f"Failed to load seller page: {url}")
                continue

            await asyncio.sleep(POST_NAV_WAIT_SECS)
            await self._scroll_page()

            profile: dict[str, Any] = {
                "url": url,
                "sellerUsername": self._extract_seller_from_url(url),
            }

            # Seller display name
            try:
                for sel in [
                    "h1",
                    '[class*="profile-name"]',
                    '[class*="user-name"]',
                ]:
                    el = await self._page.query_selector(sel)
                    if el:
                        profile["sellerDisplayName"] = (
                            await el.inner_text()
                        ).strip()
                        break
            except Exception:
                pass

            # Description / bio
            for sel in [
                '[class*="description"]',
                SELLER_BIO_SELECTOR,
                '[class*="bio"]',
            ]:
                try:
                    el = await self._page.query_selector(sel)
                    if el:
                        profile["sellerDescription"] = (
                            await el.inner_text()
                        ).strip()
                        break
                except Exception:
                    continue

            # Stats
            for sel in SELLER_STATS_SELECTORS:
                try:
                    el = await self._page.query_selector(sel)
                    if el:
                        stats_text = (await el.inner_text()).strip()
                        # Extract known patterns
                        level_match = re.search(
                            r"(Top Rated|Level \d+|New Seller)",
                            stats_text,
                            re.I,
                        )
                        if level_match:
                            profile["sellerLevel"] = level_match.group(1)
                        orders_match = re.search(
                            r"(\d[\d,]*)\s*(?:orders|completed)",
                            stats_text,
                            re.I,
                        )
                        if orders_match:
                            profile["totalOrders"] = int(
                                orders_match.group(1).replace(",", "")
                            )
                        rating_match = re.search(
                            r"(\d+\.?\d*)\s*(?:rating|stars|out of)",
                            stats_text,
                            re.I,
                        )
                        if rating_match:
                            profile["rating"] = float(rating_match.group(1))
                        break
                except Exception:
                    continue

            # Badges
            try:
                badges = []
                badge_els = await self._page.query_selector_all(
                    '[class*="badge"]:not([class*="nav"]):not([class*="menu"])'
                )
                for bel in badge_els:
                    b_text = (await bel.inner_text()).strip()
                    if b_text:
                        badges.append(b_text)
                profile["badges"] = badges
            except Exception:
                pass

            yield profile

    def _extract_seller_from_url(self, url: str) -> str:
        """Extract seller username from a Fiverr URL."""
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        if path_parts:
            return path_parts[0]
        return ""