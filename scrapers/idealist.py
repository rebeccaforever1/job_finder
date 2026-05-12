"""Idealist nonprofit job scraper.

Covers nonprofit, NGO, and mission-driven organizations.
Tries the Idealist JSON API first; falls back to HTML scraping
if the API endpoint changes (as it has historically).

Filters for Director-level and Executive roles by default,

"""

import logging
from typing import Optional
from urllib.parse import quote_plus

from models import Job, JobBoard, SearchQuery
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

IDEALIST_API_URL  = "https://www.idealist.org/api/v1/listings"
IDEALIST_BASE_URL = "https://www.idealist.org"

# Professional levels to filter for — set to senior/director roles.
# Full list: ENTRY_LEVEL, MID_LEVEL, SENIOR, DIRECTOR, EXECUTIVE, BOARD_MEMBER
PROFESSIONAL_LEVELS = ["DIRECTOR", "EXECUTIVE", "SENIOR"]


class IdealistScraper(BaseScraper):
    """Scrape nonprofit job listings from Idealist."""

    def scrape(self, query: SearchQuery, max_results: int = 50) -> list[Job]:
        jobs = self._scrape_api(query, max_results)
        if not jobs:
            logger.info("Idealist API returned no results — trying HTML scrape.")
            jobs = self._scrape_html(query, max_results)

        logger.info(
            "Idealist: found %d jobs for '%s'",
            len(jobs), query.keywords,
        )
        return jobs[:max_results]

    def _scrape_api(self, query: SearchQuery, max_results: int) -> list[Job]:
        """Hit the Idealist JSON API (no auth required)."""
        params = {
            "q":                 query.keywords,
            "location":          query.location or "Seattle, WA",
            "type":              "JOB",
            "professionalLevel": PROFESSIONAL_LEVELS,
            "page":              1,
            "pageSize":          min(max_results, 50),
        }
        if query.remote:
            params["locationType"] = "REMOTE"

        try:
            resp = self.session.get(
                IDEALIST_API_URL,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug("Idealist API request failed: %s", e)
            return []

        jobs = []
        for item in data.get("results", []):
            try:
                job_id  = item.get("id", "")
                org     = item.get("org", {})
                loc     = item.get("locationType") or item.get("location", "")

                job = Job(
                    title       = item.get("title", "").strip(),
                    company     = org.get("name", "").strip() if org else "",
                    location    = loc.strip() if isinstance(loc, str) else "",
                    url         = f"{IDEALIST_BASE_URL}/en/job/{job_id}",
                    board       = JobBoard.IDEALIST,
                    date_posted = (item.get("publishedAt") or "")[:10],
                    description = item.get("description", ""),
                )
                if job.title and job_id:
                    jobs.append(job)
            except Exception as e:
                logger.debug("Failed to parse Idealist API item: %s", e)

        return jobs

    def _scrape_html(self, query: SearchQuery, max_results: int) -> list[Job]:
        """Fallback HTML scraper for Idealist search results."""
        levels = "&".join(
            f"professionalLevel={lvl}" for lvl in PROFESSIONAL_LEVELS
        )
        url = (
            f"{IDEALIST_BASE_URL}/en/jobs"
            f"?q={quote_plus(query.keywords)}"
            f"&location={quote_plus(query.location or 'Seattle, WA')}"
            f"&{levels}"
        )

        jobs = []
        page = 1

        while len(jobs) < max_results:
            page_url = f"{url}&page={page}" if page > 1 else url
            soup = self._get(page_url)
            if not soup:
                break

            cards = soup.select(
                "[data-testid='listing-card'], "
                ".listing-card, "
                "article.job-listing, "
                "li[data-qa='job-listing']"
            )
            if not cards:
                break

            for card in cards:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)

            next_el = soup.select_one(
                "a[rel='next'], "
                "[data-testid='pagination-next'], "
                "a.pagination__next"
            )
            if not next_el or len(cards) < 5:
                break

            page += 1

        return jobs

    def _parse_card(self, card) -> Optional[Job]:
        title_el = card.select_one(
            "h2, h3, "
            "[data-testid='listing-title'], "
            "[data-qa='listing-title']"
        )
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title:
            return None

        org_el = card.select_one(
            "[data-testid='org-name'], "
            ".org-name, "
            "[data-qa='org-name']"
        )
        org = org_el.get_text(strip=True) if org_el else ""

        loc_el = card.select_one(
            "[data-testid='location'], "
            ".location, "
            "[data-qa='location']"
        )
        location = loc_el.get_text(strip=True) if loc_el else ""

        link_el = card.select_one("a[href]")
        if not link_el:
            return None

        href = link_el.get("href", "")
        if href.startswith("/"):
            href = IDEALIST_BASE_URL + href
        if not href.startswith("http"):
            return None

        return Job(
            title    = title,
            company  = org,
            location = location,
            url      = href,
            board    = JobBoard.IDEALIST,
        )

    def get_job_details(self, job: Job) -> Job:
        soup = self._get(job.url)
        if not soup:
            return job

        desc_el = soup.select_one(
            "[data-testid='listing-description'], "
            ".listing-description, "
            "[data-qa='description'], "
            "section.description"
        )
        if desc_el:
            job.description = desc_el.get_text(separator="\n", strip=True)

        return job
