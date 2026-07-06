"""Fiverr Scraper — Apify Actor entry point.

Scrapes Fiverr.com using Playwright with residential proxies.
Handles PerimeterX bot detection via full browser rendering.
"""

from __future__ import annotations

import asyncio
import logging
import os

from apify import Actor

from .models import ScraperInput
from .scraper import FiverrScraper

logger = logging.getLogger(__name__)

# Margin circuit breaker: abort a run once estimated cost exceeds gross revenue.
GROSS_PER_RESULT_USD = 0.002  # $2.00 / 1,000 results (target Console price)
MIN_COST_ALLOWANCE_USD = 0.05
CU_RATE_USD_PER_HR = 0.20  # Starter tier
RESIDENTIAL_USD_PER_GB = 8.0


def _estimate_run_cost_usd(elapsed_s: float, total_bytes: int) -> float:
    """Rough run cost = compute (mem·time) + residential proxy bandwidth."""
    mem_gb = int(os.environ.get("ACTOR_MEMORY_MBYTES", "2048")) / 1024
    compute_usd = (elapsed_s / 3600) * mem_gb * CU_RATE_USD_PER_HR
    proxy_usd = (total_bytes / 1e9) * RESIDENTIAL_USD_PER_GB
    return compute_usd + proxy_usd


async def main() -> None:
    """Main actor function."""
    async with Actor:
        # 1. Get and validate input
        raw_input = await Actor.get_input() or {}

        config = ScraperInput.from_actor_input(raw_input)
        validation_error = config.validate_for_mode()
        if validation_error:
            await Actor.fail(status_message=validation_error)
            return

        # 1b. Charge actor-start — one-time per run fee
        start_charge = await Actor.charge(event_name="actor-start")
        if start_charge and start_charge.event_charge_limit_reached:
            await Actor.fail(
                status_message="Run limit reached. Please subscribe to continue using this actor."
            )
            return

        # 2. Free user limit
        is_paying = os.environ.get("APIFY_IS_AT_HOME") == "1" and os.environ.get(
            "APIFY_USER_IS_PAYING"
        ) == "1"

        max_results = config.max_results
        if not is_paying and os.environ.get("APIFY_IS_AT_HOME") == "1":
            max_results = min(max_results, 25)
            Actor.log.info(
                "Free tier: limited to 25 results. "
                "Subscribe for unlimited results."
            )

        Actor.log.info(
            f"Starting Fiverr Scraper | mode={config.mode.value} | "
            f"max_results={max_results}"
        )

        # 3. Set up proxy. A customer-supplied unblocker URL wins — it solves
        # PerimeterX itself, so we route everything through it and skip the
        # warmup/rotation dance. Otherwise fall back to Apify residential.
        use_unblocker = bool(config.unblocker_proxy_url)
        if use_unblocker:
            config.proxy_configuration = {
                "useApifyProxy": False,
                "proxyUrls": [config.unblocker_proxy_url],
            }
            Actor.log.info(
                "Using customer unblocker proxy — warmup & IP rotation disabled."
            )
        elif not config.proxy_configuration:
            config.proxy_configuration = {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
            }

        # 4. Resume state
        state = await Actor.use_state(default_value={"scraped": 0, "failed": 0})

        count = state["scraped"]
        batch: list[dict] = []
        batch_size = 25
        total_bytes = 0
        start_time = asyncio.get_event_loop().time()
        cost_exceeded = False

        await Actor.set_status_message("Starting Playwright browser...")

        async with FiverrScraper(
            config,
            max_pages=config.max_pages,
            max_results=max_results,
            use_unblocker=use_unblocker,
        ) as scraper:
            try:
                if config.mode.value == "search_gigs":
                    queries = (
                        config.search_queries_list
                        if config.search_queries_list
                        else [config.search_query]
                    )
                    for query in queries:
                        if count >= max_results:
                            break

                        await Actor.set_status_message(
                            f"Searching: '{query}' ({count}/{max_results})"
                        )

                        async for gig in scraper.search_gigs(query):
                            if count >= max_results:
                                break

                            # Charge per-gig for each result
                            gig_charge = await Actor.charge(event_name="per-gig")
                            if gig_charge and gig_charge.event_charge_limit_reached:
                                Actor.log.warning(
                                    "Event charge limit reached on per-gig. Stopping."
                                )
                                cost_exceeded = True
                                break

                            batch.append(gig)
                            count += 1
                            state["scraped"] = count

                            if len(batch) >= batch_size:
                                charge_result = await Actor.push_data(batch)
                                batch = []

                                # Check for event charge limit
                                if (
                                    charge_result
                                    and charge_result.event_charge_limit_reached
                                ):
                                    Actor.log.warning(
                                        "Event charge limit reached on push. "
                                        "Stopping."
                                    )
                                    break

                                await Actor.set_status_message(
                                    f"Scraped {count}/{max_results} gigs"
                                )

                            # Margin breaker
                            elapsed = (
                                asyncio.get_event_loop().time() - start_time
                            )
                            est_cost = _estimate_run_cost_usd(elapsed, total_bytes)
                            budget = max(
                                MIN_COST_ALLOWANCE_USD,
                                count * GROSS_PER_RESULT_USD,
                            )
                            if est_cost > budget:
                                cost_exceeded = True
                                Actor.log.warning(
                                    f"Margin breaker tripped: "
                                    f"est cost ~${est_cost:.3f} > "
                                    f"budget ${budget:.3f} after {count} items. "
                                    "Stopping to protect margin."
                                )
                                await Actor.set_status_message(
                                    f"Stopped at {count} items — "
                                    "run cost exceeded revenue."
                                )
                                break

                        if cost_exceeded:
                            break

                elif config.mode.value == "gig_details":
                    await Actor.set_status_message(
                        f"Scraping {len(config.gig_urls)} gig details..."
                    )

                    async for detail in scraper.gig_details(
                        config.gig_urls,
                        include_reviews=config.include_reviews,
                    ):
                        # Charge per-gig-detail for each result
                        detail_charge = await Actor.charge(event_name="per-gig-detail")
                        if detail_charge and detail_charge.event_charge_limit_reached:
                            Actor.log.warning(
                                "Event charge limit reached on per-gig-detail. Stopping."
                            )
                            break

                        batch.append(detail)
                        count += 1
                        state["scraped"] = count

                        if len(batch) >= batch_size:
                            charge_result = await Actor.push_data(batch)
                            batch = []
                            if (
                                charge_result
                                and charge_result.event_charge_limit_reached
                            ):
                                Actor.log.warning(
                                    "Event charge limit reached. Stopping."
                                )
                                break

                elif config.mode.value == "seller_profiles":
                    await Actor.set_status_message(
                        f"Scraping {len(config.seller_urls)} seller profiles..."
                    )

                    async for profile in scraper.seller_profiles(
                        config.seller_urls
                    ):
                        # Charge per-seller-profile for each result
                        seller_charge = await Actor.charge(event_name="per-seller-profile")
                        if seller_charge and seller_charge.event_charge_limit_reached:
                            Actor.log.warning(
                                "Event charge limit reached on per-seller-profile. Stopping."
                            )
                            break

                        batch.append(profile)
                        count += 1
                        state["scraped"] = count

                        if len(batch) >= batch_size:
                            charge_result = await Actor.push_data(batch)
                            batch = []
                            if (
                                charge_result
                                and charge_result.event_charge_limit_reached
                            ):
                                Actor.log.warning(
                                    "Event charge limit reached. Stopping."
                                )
                                break

            except Exception as e:
                state["failed"] += 1
                Actor.log.error(f"Scraping error: {e}")
            finally:
                # Flush remaining batch
                if batch:
                    await Actor.push_data(batch)

        # 5. Fail loud on 0 results
        if count == 0:
            await Actor.fail(
                status_message=(
                    "Scraped 0 results. Either targets are invalid/empty, "
                    "or Fiverr changed its HTML and the scraper needs "
                    "updating. Check the logs."
                )
            )
            return

        # 6. Instrumentation
        elapsed = asyncio.get_event_loop().time() - start_time
        est_cost = _estimate_run_cost_usd(elapsed, total_bytes)
        Actor.log.info(
            f"Cost report | "
            f"items: {count} | "
            f"elapsed: {elapsed:.1f}s | "
            f"est cost: ${est_cost:.4f}"
        )

        msg = f"Done. Scraped {count} items."
        if cost_exceeded:
            msg += " Stopped early at run cost cap."
        if state["failed"] > 0:
            msg += f" {state['failed']} errors encountered."
        if (
            not is_paying
            and os.environ.get("APIFY_IS_AT_HOME") == "1"
            and count >= 25
        ):
            msg += (
                " Free tier limit (25) reached."
                " Subscribe for unlimited results."
            )

        Actor.log.info(msg)
        await Actor.set_status_message(msg)