"""Pydantic models for Fiverr Scraper input validation and output formatting."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# --- Input Models ---


class ScrapingMode(str, Enum):
    SEARCH_GIGS = "search_gigs"
    GIG_DETAILS = "gig_details"
    SELLER_PROFILES = "seller_profiles"


class SearchSort(str, Enum):
    RECOMMENDED = "recommended"
    BEST_SELLING = "best_selling"
    NEWEST = "newest"


class DeliveryTime(str, Enum):
    ANY = "any"
    EXPRESS_24H = "express_24h"
    UP_TO_3_DAYS = "up_to_3_days"
    UP_TO_7_DAYS = "up_to_7_days"
    ANY_TIME = "any_time"


class ScraperInput(BaseModel):
    """Validated scraper input from Apify."""

    mode: ScrapingMode = ScrapingMode.SEARCH_GIGS

    # Search mode
    search_query: str = ""
    search_queries_list: list[str] = Field(default_factory=list)
    search_sort: SearchSort = SearchSort.RECOMMENDED
    min_price: float | None = None
    max_price: float | None = None
    delivery_time: DeliveryTime = DeliveryTime.ANY
    category: str = ""

    # Gig details mode
    gig_urls: list[str] = Field(default_factory=list)

    # Seller profiles mode
    seller_urls: list[str] = Field(default_factory=list)

    # General settings
    max_results: int = 100
    max_pages: int = 10
    include_reviews: bool = False

    proxy_configuration: dict | None = None

    # Optional customer-supplied unblocker/anti-bot proxy URL. When set, all
    # requests route through it and the homepage warmup + IP rotation are
    # skipped (the unblocker solves PerimeterX itself, so extra requests only
    # cost the customer). This is the reliable path for Fiverr's PX wall.
    unblocker_proxy_url: str = ""

    @field_validator("search_queries_list", mode="before")
    @classmethod
    def clean_queries_list(
        cls, v: list[str] | None
    ) -> list[str]:
        if not v:
            return []
        return [q.strip() for q in v if q and q.strip()]

    @field_validator("gig_urls", mode="before")
    @classmethod
    def clean_gig_urls(cls, v: list[str] | None) -> list[str]:
        if not v:
            return []
        return [u.strip() for u in v if u.strip()]

    @field_validator("seller_urls", mode="before")
    @classmethod
    def clean_seller_urls(cls, v: list[str] | None) -> list[str]:
        if not v:
            return []
        return [u.strip() for u in v if u.strip()]

    @classmethod
    def from_actor_input(cls, raw: dict[str, Any]) -> ScraperInput:
        """Map Apify input schema field names to model field names."""
        return cls(
            mode=raw.get("mode", "search_gigs"),
            search_query=raw.get("searchQuery", ""),
            search_queries_list=raw.get("searchQueriesList", []),
            search_sort=raw.get("searchSort", "recommended"),
            min_price=raw.get("minPrice"),
            max_price=raw.get("maxPrice"),
            delivery_time=raw.get("deliveryTime", "any"),
            category=raw.get("category", ""),
            gig_urls=raw.get("gigUrls", []),
            seller_urls=raw.get("sellerUrls", []),
            max_results=raw.get("maxResults", 100),
            max_pages=raw.get("maxPages", 10),
            include_reviews=raw.get("includeReviews", False),
            proxy_configuration=raw.get("proxyConfiguration"),
            unblocker_proxy_url=(raw.get("unblockerProxyUrl") or "").strip(),
        )

    def validate_for_mode(self) -> str | None:
        """Return an error message if input is invalid for the selected mode."""
        if self.mode == ScrapingMode.SEARCH_GIGS:
            if not self.search_query and not self.search_queries_list:
                return (
                    "A search query or queries list is required "
                    "for 'Search Gigs' mode."
                )
        if self.mode == ScrapingMode.GIG_DETAILS and not self.gig_urls:
            return (
                "At least one gig URL is required for 'Gig Details' mode."
            )
        if self.mode == ScrapingMode.SELLER_PROFILES and not self.seller_urls:
            return (
                "At least one seller URL is required for "
                "'Seller Profiles' mode."
            )
        if self.max_results < 1:
            return "maxResults must be at least 1."
        return None


# --- Output Formatters ---


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_price(text: str | None) -> float | None:
    """Parse a price string like '$15.00' or 'from $10' to float."""
    if not text:
        return None
    text = text.replace("from", "").replace("US$", "$").strip()
    # Extract first price number
    import re
    match = re.search(r"\$?(\d+(?:,\d{3})*(?:\.\d+)?)", text)
    if match:
        return float(match.group(1).replace(",", ""))
    return None


def format_gig_from_search(d: dict[str, Any]) -> dict[str, Any]:
    """Format a gig card from search results page."""
    return {
        "type": "gig_search",
        "gigId": d.get("gigId", ""),
        "title": _str(d.get("title")),
        "sellerUsername": _str(d.get("sellerUsername")),
        "sellerLevel": _str(d.get("sellerLevel")),
        "price": _float(d.get("price")),
        "priceString": _str(d.get("priceString")),
        "rating": _float(d.get("rating")),
        "reviewCount": _int(d.get("reviewCount")),
        "deliveryTime": _str(d.get("deliveryTime")),
        "description": _str(d.get("description")),
        "url": _str(d.get("url")),
        "tags": d.get("tags", []),
        "category": _str(d.get("category")),
        "subcategory": _str(d.get("subcategory")),
        "isPro": bool(d.get("isPro")),
        "isPromoted": bool(d.get("isPromoted")),
        "imageUrl": _str(d.get("imageUrl")),
        "sellerAvatar": _str(d.get("sellerAvatar")),
        "searchKeyword": _str(d.get("searchKeyword")),
        "scrapedAt": _utc_now(),
    }


def format_gig_detail(d: dict[str, Any]) -> dict[str, Any]:
    """Format full gig detail from a gig page."""
    return {
        "type": "gig_detail",
        "gigId": _str(d.get("gigId")),
        "title": _str(d.get("title")),
        "sellerUsername": _str(d.get("sellerUsername")),
        "sellerDisplayName": _str(d.get("sellerDisplayName")),
        "sellerLevel": _str(d.get("sellerLevel")),
        "sellerAvatar": _str(d.get("sellerAvatar")),
        "sellerResponseTime": _str(d.get("sellerResponseTime")),
        "sellerOrderCompletion": _float(d.get("sellerOrderCompletion")),
        "sellerOnTimeDelivery": _float(d.get("sellerOnTimeDelivery")),
        "memberSince": _str(d.get("memberSince")),
        "totalOrders": _int(d.get("totalOrders")),
        "rating": _float(d.get("rating")),
        "reviewCount": _int(d.get("reviewCount")),
        "url": _str(d.get("url")),
        "description": _str(d.get("description")),
        "descriptionHtml": _str(d.get("descriptionHtml")),
        "category": _str(d.get("category")),
        "subcategory": _str(d.get("subcategory")),
        "tags": d.get("tags", []),
        "isPro": bool(d.get("isPro")),
        "imageUrls": d.get("imageUrls", []),
        "videoUrl": _str(d.get("videoUrl")),
        # Package tiers
        "packages": d.get("packages", []),
        # FAQ
        "faq": d.get("faq", []),
        # Requirements
        "requirements": _str(d.get("requirements")),
        # Reviews (when include_reviews=True)
        "reviews": d.get("reviews", []),
        "scrapedAt": _utc_now(),
    }


def format_seller_profile(d: dict[str, Any]) -> dict[str, Any]:
    """Format a seller profile page."""
    return {
        "type": "seller_profile",
        "sellerUsername": _str(d.get("sellerUsername")),
        "sellerDisplayName": _str(d.get("sellerDisplayName")),
        "sellerLevel": _str(d.get("sellerLevel")),
        "sellerAvatar": _str(d.get("sellerAvatar")),
        "sellerDescription": _str(d.get("sellerDescription")),
        "memberSince": _str(d.get("memberSince")),
        "responseTime": _str(d.get("responseTime")),
        "responseRate": _float(d.get("responseRate")),
        "orderCompletion": _float(d.get("orderCompletion")),
        "onTimeDelivery": _float(d.get("onTimeDelivery")),
        "totalOrders": _int(d.get("totalOrders")),
        "rating": _float(d.get("rating")),
        "reviewCount": _int(d.get("reviewCount")),
        "starBreakdown": d.get("starBreakdown", {}),
        "languages": d.get("languages", []),
        "skills": d.get("skills", []),
        "education": d.get("education", []),
        "certifications": d.get("certifications", []),
        "linkedProfiles": d.get("linkedProfiles", []),
        "badges": d.get("badges", []),
        "activeGigs": d.get("activeGigs", []),
        "url": _str(d.get("url")),
        "scrapedAt": _utc_now(),
    }