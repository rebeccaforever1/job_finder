"""USAJobs federal job scraper.

Uses the official USAJobs API (free key at developer.usajobs.gov).
Covers all federal positions 

API docs: https://developer.usajobs.gov/API-Reference
"""

import logging
from typing import Optional

from models import Job, JobBoard, SearchQuery
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

USAJOBS_API_URL = "https://data.usajobs.gov/api/search"

# Sign up for a free key at https://developer.usajobs.gov/
# Add these to your .env file:
#   USAJOBS_KEY=your_key_here
#   USAJOBS_EMAIL=your_email_here
import os
USAJOBS_KEY   = os.getenv("USAJOBS_KEY", "")
USAJOBS_EMAIL = os.getenv("USAJOBS_EMAIL", "")


class USAJobsScraper(BaseScraper):
    """Scrape federal job listings from the USAJobs API."""

    def scrape(self, query: SearchQuery, max_results: int = 50) -> list[Job]:
        if not USAJOBS_KEY or not USAJOBS_EMAIL:
            logger.warning(
                "USAJobs API key or email not set. "
                "Add USAJOBS_KEY and USAJOBS_EMAIL to your .env file. "
                "Sign up free at https://developer.usajobs.gov/"
            )
            return []

        params = {
            "Keyword":        query.keywords,
            "LocationName":   query.location or "Washington",
            "ResultsPerPage": min(max_results, 500),
            "DatePosted":     query.max_age_days,
        }
        if query.remote:
            params["RemoteIndicator"] = "True"

        headers = {
            "Host":              "data.usajobs.gov",
            "User-Agent":        USAJOBS_EMAIL,
            "Authorization-Key": USAJOBS_KEY,
        }

        try:
            resp = self.session.get(
                USAJOBS_API_URL,
                params=params,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("USAJobs API request failed: %s", e)
            return []

        items = (
            data.get("SearchResult", {})
                .get("SearchResultItems", [])
        )

        jobs = []
        for item in items:
            try:
                p = item.get("MatchedObjectDescriptor", {})
                job = Job(
                    title       = p.get("PositionTitle", "").strip(),
                    company     = p.get("OrganizationName", "").strip(),
                    location    = p.get("PositionLocationDisplay", "").strip(),
                    url         = p.get("PositionURI", "").strip(),
                    board       = JobBoard.USAJOBS,
                    date_posted = (p.get("PublicationStartDate") or "")[:10],
                    description = p.get("UserArea", {})
                                   .get("Details", {})
                                   .get("JobSummary", ""),
                )
                if job.title and job.url:
                    jobs.append(job)
            except Exception as e:
                logger.debug("Failed to parse USAJobs item: %s", e)

        logger.info("USAJobs: found %d jobs for '%s'", len(jobs), query.keywords)
        return jobs[:max_results]

    def get_job_details(self, job: Job) -> Job:
        # USAJobs API returns a summary in the search results.
        # The full posting is a web page — fetch and parse if needed.
        soup = self._get(job.url)
        if not soup:
            return job

        desc_el = soup.select_one(
            "#job-summary, "
            ".usajobs-joa-summary, "
            "#duties, "
            ".usajobs-joa-duties"
        )
        if desc_el:
            job.description = desc_el.get_text(separator="\n", strip=True)

        return job
