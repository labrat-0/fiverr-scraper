"""Tests for scraper.py — parsing logic that doesn't need Playwright.

The Playwright-dependent methods (navigate, extract_gig_card, etc.)
cannot be tested without a browser. This suite covers the pure-Python
helpers: _parse_price, _parse_rating, _parse_review_count, _parse_count,
_extract_seller_from_url.
"""

from __future__ import annotations

from src.scraper import FiverrScraper
from src.models import ScraperInput, ScrapingMode


def make_scraper():
    return FiverrScraper(
        config=ScraperInput(mode=ScrapingMode.SEARCH_GIGS, search_query="test"),
    )


class TestParsePrice:
    """FiverrScraper._parse_price — price string parser."""

    def test_empty(self):
        s = make_scraper()
        assert s._parse_price("") == 0.0

    def test_simple_dollar(self):
        s = make_scraper()
        assert s._parse_price("$15") == 15.0

    def test_with_cents(self):
        s = make_scraper()
        assert s._parse_price("$15.50") == 15.50

    def test_from_prefix(self):
        s = make_scraper()
        assert s._parse_price("From US$10") == 10.0

    def test_comma_thousands(self):
        s = make_scraper()
        assert s._parse_price("$1,500") == 1500.0

    def test_range_returns_first_number(self):
        s = make_scraper()
        assert s._parse_price("$10 - $50") == 10.0

    def test_no_symbol(self):
        s = make_scraper()
        assert s._parse_price("25") == 25.0

    def test_text_only_returns_zero(self):
        s = make_scraper()
        assert s._parse_price("Free") == 0.0


class TestParseRating:
    """FiverrScraper._parse_rating — rating string parser."""

    def test_empty(self):
        s = make_scraper()
        assert s._parse_rating("") == 0.0

    def test_simple(self):
        s = make_scraper()
        assert s._parse_rating("4.5") == 4.5

    def test_star_suffix(self):
        s = make_scraper()
        assert s._parse_rating("4.5 stars") == 4.5

    def test_out_of(self):
        s = make_scraper()
        assert s._parse_rating("4 out of 5") == 4.0

    def test_percentage(self):
        """95% should be divided by 100 -> 0.95, but then min(0.95, 5) -> 0.95.
        Actually if the regex matches 95, it's 95 > 5 -> 95/100 = 0.95."""
        s = make_scraper()
        assert s._parse_rating("95%") == 0.9

    def test_clamped_at_5(self):
        s = make_scraper()
        assert s._parse_rating("5.0") == 5.0
        assert s._parse_rating("5.5") <= 5.0

    def test_with_review_count(self):
        s = make_scraper()
        assert s._parse_rating("4.5 (102 reviews)") == 4.5


class TestParseReviewCount:
    """FiverrScraper._parse_review_count — extract count from rating string."""

    def test_empty(self):
        s = make_scraper()
        assert s._parse_review_count("") == 0

    def test_parentheses(self):
        s = make_scraper()
        assert s._parse_review_count("4.5 (102)") == 102

    def test_reviews_suffix(self):
        s = make_scraper()
        assert s._parse_review_count("4.5 102 reviews") == 102

    def test_ratings_suffix(self):
        s = make_scraper()
        assert s._parse_review_count("4.5 50 ratings") == 50

    def test_k_count(self):
        s = make_scraper()
        assert s._parse_review_count("4.5 (1.2K reviews)") == 1200

    def test_no_count_returns_zero(self):
        s = make_scraper()
        assert s._parse_review_count("4.5 stars") == 0


class TestParseCount:
    """FiverrScraper._parse_count — K/M/B suffix parser."""

    def test_plain_number(self):
        s = make_scraper()
        assert s._parse_count("500") == 500

    def test_k_suffix(self):
        s = make_scraper()
        assert s._parse_count("1.5K") == 1500

    def test_m_suffix(self):
        s = make_scraper()
        assert s._parse_count("2M") == 2000000

    def test_b_suffix(self):
        s = make_scraper()
        assert s._parse_count("1B") == 1000000000

    def test_lowercase_k(self):
        s = make_scraper()
        assert s._parse_count("500k") == 500000

    def test_invalid_returns_zero(self):
        s = make_scraper()
        assert s._parse_count("abc") == 0

    def test_whitespace(self):
        s = make_scraper()
        assert s._parse_count(" 1K ") == 1000


class TestExtractSellerFromUrl:
    """FiverrScraper._extract_seller_from_url."""

    def test_standard_url(self):
        s = make_scraper()
        assert (
            s._extract_seller_from_url(
                "https://www.fiverr.com/sellerusername/scrape-web-data"
            )
            == "sellerusername"
        )

    def test_profile_url(self):
        s = make_scraper()
        assert (
            s._extract_seller_from_url("https://www.fiverr.com/sellerusername")
            == "sellerusername"
        )

    def test_url_with_query_params(self):
        s = make_scraper()
        assert (
            s._extract_seller_from_url(
                "https://www.fiverr.com/sellerusername/gig?source=search"
            )
            == "sellerusername"
        )

    def test_empty_path(self):
        s = make_scraper()
        assert s._extract_seller_from_url("https://www.fiverr.com/") == ""

    def test_invalid_url(self):
        s = make_scraper()
        assert s._extract_seller_from_url("") == ""