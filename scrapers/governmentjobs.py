"""GovernmentJobs (NEOGOV) scraper.

Covers Washington State, King County, City of Seattle, and the
general GovernmentJobs keyword search — the main ATS platform
used by local and state government agencies in the Pacific Northwest.

NEOGOV renders job listings server-side, so standard HTML scraping
works without JavaScript execution. Rate limiting is respected via
the BaseScraper delay.
"""

import logging
import time
from typing import Optional
from urllib.parse import quote_plus

from models import Job, JobBoard, SearchQuery
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Agency-specific portals relevant to Rebecca's target employers.
# Add or remove entries here to target additional agencies.
NEOGOV_PORTALS = [
    ("GovernmentJobs-WA",   "https://www.governmentjobs.com/careers/washington"),
    ("GovernmentJobs-King", "https://www.governmentjobs.com/careers/kingcounty"),
    ("GovernmentJobs-SEA",  "https://www.governmentjobs.com/careers/seattle"),
    ("GovernmentJobs-ALL",  "https://www.governmentjobs.com/jobs"),
]


class GovernmentJobsScraper(BaseScraper):
    """Scrape job listings from GovernmentJobs.com (NEOGOV platform)."""

    def scrape(self, query: SearchQuery, max_results: int = 50) -> list[Job]:
        all_jobs: list[Job] = []
        seen_urls: set[str] = set()
        per_portal = max(max_results // len(NEOGOV_PORTALS), 10)

        for label, base_url in NEOGOV_PORTALS:
            if len(all_jobs) >= max_results:
                break

            if "careers/" in base_url:
                url = f"{base_url}?search=true&keyword={quote_plus(query.keywords)}"
            else:
                url = (
                    f"{base_url}"
                    f"?keyword={quote_plus(query.keywords)}"
                    f"&location={quote_plus(query.location or 'Washington')}"
                )

            jobs = self._scrape_portal(url, label, per_portal)
            for job in jobs:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)

            time.sleep(1.5)

        logger.info(
            "GovernmentJobs: found %d unique jobs for '%s'",
            len(all_jobs), query.keywords,
        )
        return all_jobs[:max_results]

    def _scrape_portal(self, url: str, label: str, max_results: int) -> list[Job]:
        jobs: list[Job] = []
        page = 1

        while len(jobs) < max_results:
            page_url = f"{url}&page={page}" if page > 1 else url
            soup = self._get(page_url)
            if not soup:
                break

            # NEOGOV uses a table with id="job-table" on agency portals
            # and div-based cards on the general search page.
            rows = soup.select("#job-table tbody tr")
            if not rows:
                rows = soup.select("div.views-row, li.job-listing, .job-card")
            if not rows:
                # Last-resort: any link containing /careers/ or /jobs/
                rows = soup.select("a[href*='/careers/'], a[href*='/jobs/']")

            if not rows:
                logger.debug("[%s] No job rows found at %s", label, page_url)
                break

            for row in rows:
                job = self._parse_row(row, label)
                if job:
                    jobs.append(job)

            # Pagination: stop if fewer results than expected or no next page
            next_el = soup.select_one("a[rel='next'], a.next, li.pager-next a")
            if not next_el or len(rows) < 5:
                break

            page += 1

        return jobs

    def _parse_row(self, row, label: str) -> Optional[Job]:
        # Title + URL
        link = (
            row.select_one("a[href*='/careers/'], a[href*='/jobs/']")
            or row.select_one("a")
        )
        if not link:
            # Row might itself be an <a> tag
            if row.name == "a" and row.get("href"):
                link = row
            else:
                return None

        title = link.get_text(strip=True)
        if not title:
            return None

        href = link.get("href", "")
        if href.startswith("/"):
            href = "https://www.governmentjobs.com" + href
        if not href.startswith("http"):
            return None

        # Department / org
        org_el = row.select_one(
            ".department, .employer, .agency, "
            "td:nth-child(2), span.department"
        )
        org = org_el.get_text(strip=True) if org_el else label

        # Location
        loc_el = row.select_one(
            ".location, .city, td:nth-child(3), span.location"
        )
        location = loc_el.get_text(strip=True) if loc_el else "Washington"

        # Closing date
        close_el = row.select_one(
            ".closing-date, .deadline, td:nth-child(4), span.closing"
        )
        closing = close_el.get_text(strip=True) if close_el else ""

        # Salary
        salary_el = row.select_one(".salary, td:nth-child(5), span.salary")
        salary = salary_el.get_text(strip=True) if salary_el else ""

        return Job(
            title    = title,
            company  = org,
            location = location,
            url      = href,
            board    = JobBoard.GOVERNMENTJOBS,
            salary   = salary,
            # Store closing date in date_posted field for display
            date_posted = closing,
        )

    def get_job_details(self, job: Job) -> Job:
        soup = self._get(job.url)
        if not soup:
            return job

        desc_el = soup.select_one(
            "#job-description-body, "
            ".job-description, "
            "div[class*='Description'], "
            "#tab1"
        )
        if desc_el:
            job.description = desc_el.get_text(separator="\n", strip=True)

        return job
