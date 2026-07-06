"""Tests for models.py — input validation, output formatting, parsing."""

from __future__ import annotations

from src.models import (
    ScraperInput,
    ScrapingMode,
    SearchSort,
    DeliveryTime,
    format_gig_from_search,
    format_gig_detail,
    format_seller_profile,
    _parse_price,
    _str,
    _float,
    _int,
)


class TestScraperInputValidation:
    """ScraperInput model creation and validate_for_mode()."""

    def test_defaults_to_search_gigs(self):
        inp = ScraperInput()
        assert inp.mode == ScrapingMode.SEARCH_GIGS
        assert inp.search_query == ""
        assert inp.max_results == 100
        assert inp.max_pages == 10

    def test_search_gigs_needs_query(self):
        """Search mode without query should return an error."""
        inp = ScraperInput(mode="search_gigs")
        err = inp.validate_for_mode()
        assert err is not None
        assert "search query" in err.lower()

    def test_search_gigs_with_query_valid(self):
        inp = ScraperInput(mode="search_gigs", search_query="web scraping")
        assert inp.validate_for_mode() is None

    def test_search_gigs_with_queries_list_valid(self):
        inp = ScraperInput(
            mode="search_gigs", search_queries_list=["web scraping", "logo design"]
        )
        assert inp.validate_for_mode() is None

    def test_gig_details_needs_urls(self):
        inp = ScraperInput(mode="gig_details")
        err = inp.validate_for_mode()
        assert err is not None
        assert "gig url" in err.lower()

    def test_gig_details_with_urls_valid(self):
        inp = ScraperInput(
            mode="gig_details",
            gig_urls=["https://www.fiverr.com/user/gig-title"],
        )
        assert inp.validate_for_mode() is None

    def test_seller_profiles_needs_urls(self):
        inp = ScraperInput(mode="seller_profiles")
        err = inp.validate_for_mode()
        assert err is not None
        assert "seller url" in err.lower()

    def test_seller_profiles_with_urls_valid(self):
        inp = ScraperInput(
            mode="seller_profiles",
            seller_urls=["https://www.fiverr.com/sellerusername"],
        )
        assert inp.validate_for_mode() is None

    def test_max_results_must_be_at_least_one(self):
        inp = ScraperInput(mode="search_gigs", search_query="test", max_results=0)
        err = inp.validate_for_mode()
        assert err is not None
        assert "maxResults" in err

    def test_cleans_queries_list(self):
        inp = ScraperInput(
            search_queries_list=["a", "", "  b  "],
        )
        assert inp.search_queries_list == ["a", "b"]

    def test_from_actor_input_maps_fields(self):
        raw = {
            "mode": "gig_details",
            "searchQuery": "test",
            "maxResults": 50,
            "includeReviews": True,
            "gigUrls": ["https://fiverr.com/user/gig"],
        }
        inp = ScraperInput.from_actor_input(raw)
        assert inp.mode == ScrapingMode.GIG_DETAILS
        assert inp.search_query == "test"
        assert inp.max_results == 50
        assert inp.include_reviews is True
        assert inp.gig_urls == ["https://fiverr.com/user/gig"]

    def test_from_actor_input_defaults(self):
        inp = ScraperInput.from_actor_input({})
        assert inp.mode == ScrapingMode.SEARCH_GIGS
        assert inp.search_query == ""
        assert inp.max_results == 100
        assert inp.include_reviews is False
        assert inp.unblocker_proxy_url == ""

    def test_unblocker_proxy_url_mapped_and_trimmed(self):
        raw = {"mode": "search_gigs", "searchQuery": "x",
                "unblockerProxyUrl": "  http://u:p@host:8080  "}
        inp = ScraperInput.from_actor_input(raw)
        assert inp.unblocker_proxy_url == "http://u:p@host:8080"

    def test_enum_values(self):
        assert ScrapingMode.SEARCH_GIGS.value == "search_gigs"
        assert ScrapingMode.GIG_DETAILS.value == "gig_details"
        assert ScrapingMode.SELLER_PROFILES.value == "seller_profiles"
        assert SearchSort.RECOMMENDED.value == "recommended"
        assert DeliveryTime.ANY.value == "any"
        assert DeliveryTime.EXPRESS_24H.value == "express_24h"


class TestParsePrice:
    """The _parse_price helper in models.py."""

    def test_none_returns_none(self):
        assert _parse_price(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_price("") is None

    def test_basic_price(self):
        assert _parse_price("$15") == 15.0

    def test_price_with_cents(self):
        assert _parse_price("$15.50") == 15.50

    def test_from_prefix(self):
        assert _parse_price("From US$10") == 10.0

    def test_comma_separated(self):
        assert _parse_price("$1,500") == 1500.0

    def test_no_dollar_sign(self):
        assert _parse_price("25") == 25.0

    def test_text_before_price(self):
        assert _parse_price("Starting at $20") == 20.0

    def test_range_returns_first(self):
        assert _parse_price("$10 - $50") == 10.0


class TestFormatGigFromSearch:
    """format_gig_from_search output shape."""

    def test_basic_fields(self):
        data = {
            "title": "I will scrape data",
            "sellerUsername": "scraperpro",
            "price": 15.0,
            "rating": 4.5,
            "reviewCount": 100,
            "url": "https://fiverr.com/scraperpro/gig",
        }
        out = format_gig_from_search(data)
        assert out["type"] == "gig_search"
        assert out["title"] == "I will scrape data"
        assert out["sellerUsername"] == "scraperpro"
        assert out["price"] == 15.0
        assert out["rating"] == 4.5
        assert out["reviewCount"] == 100
        assert out["url"] == "https://fiverr.com/scraperpro/gig"
        assert "scrapedAt" in out
        assert out["tags"] == []

    def test_nulls_handled(self):
        out = format_gig_from_search({})
        assert out["title"] == ""
        assert out["sellerUsername"] == ""
        assert out["price"] == 0.0
        assert out["rating"] == 0.0
        assert out["reviewCount"] == 0

    def test_gig_id_passed_through(self):
        out = format_gig_from_search({"gigId": "search-web-1-0"})
        assert out["gigId"] == "search-web-1-0"


class TestFormatGigDetail:
    """format_gig_detail output shape."""

    def test_basic_fields(self):
        data = {
            "title": "Full gig title",
            "sellerUsername": "proseller",
            "url": "https://fiverr.com/proseller/gig",
            "packages": [{"name": "Basic", "price": 10}],
            "reviews": [{"text": "Great!"}],
        }
        out = format_gig_detail(data)
        assert out["type"] == "gig_detail"
        assert out["title"] == "Full gig title"
        assert out["sellerUsername"] == "proseller"
        assert out["packages"] == [{"name": "Basic", "price": 10}]
        assert out["reviews"] == [{"text": "Great!"}]
        assert "scrapedAt" in out

    def test_nulls_handled(self):
        out = format_gig_detail({})
        assert out["title"] == ""
        assert out["sellerUsername"] == ""
        assert out["packages"] == []
        assert out["faq"] == []
        assert out["reviews"] == []


class TestFormatSellerProfile:
    """format_seller_profile output shape."""

    def test_basic_fields(self):
        data = {
            "sellerUsername": "topseller",
            "sellerDisplayName": "Top Seller",
            "sellerLevel": "Top Rated",
            "totalOrders": 500,
            "rating": 4.9,
            "badges": ["Top Rated", "Fast Response"],
        }
        out = format_seller_profile(data)
        assert out["type"] == "seller_profile"
        assert out["sellerUsername"] == "topseller"
        assert out["sellerDisplayName"] == "Top Seller"
        assert out["sellerLevel"] == "Top Rated"
        assert out["totalOrders"] == 500
        assert out["rating"] == 4.9
        assert out["badges"] == ["Top Rated", "Fast Response"]

    def test_nulls_handled(self):
        out = format_seller_profile({})
        assert out["sellerUsername"] == ""
        assert out["sellerLevel"] == ""
        assert out["totalOrders"] == 0
        assert out["rating"] == 0.0


class TestStrFloatIntHelpers:
    """_str, _float, _int sanitizers."""

    def test_str(self):
        assert _str("hello") == "hello"
        assert _str(None) == ""
        assert _str(42) == "42"
        assert _str("  spaced  ") == "spaced"

    def test_float(self):
        assert _float("3.14") == 3.14
        assert _float(None) == 0.0
        assert _float("notanumber") == 0.0
        assert _float(5) == 5.0

    def test_int(self):
        assert _int("42") == 42
        assert _int(None) == 0
        assert _int("notanumber") == 0
        assert _int(3.9) == 3