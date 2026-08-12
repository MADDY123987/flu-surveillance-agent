"""
Scraper for CDC FluView weekly narrative surveillance reports - the real written
analysis (not just numbers) that gets embedded for semantic/vector search.

URL pattern confirmed live (2026-08-12): https://www.cdc.gov/fluview/surveillance/{year}-week-{NN}.html
- Week number is zero-padded to 2 digits (e.g. "2026-week-07", not "2026-week-7").
- A missing/not-yet-published report 404s.
- CDC's report week numbering does NOT line up with Python's ISO calendar week: on
  2026-08-12 (ISO week 33), the latest published report was "Week 30, ending August 1,
  2026" - both a real publish lag and a CDC-epiweek-vs-ISO-week drift, confirmed by
  comparing to the Delphi API's own epiweek values (see app/ingest.py). Because of that
  drift, don't compute a report's week number by formula - discover the latest one by
  probing backward from the current date until a report is found (see find_latest_report).
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import date, timedelta

FLUVIEW_URL = "https://www.cdc.gov/fluview/surveillance/{year}-week-{week:02d}.html"


def _extract_narrative(soup: BeautifulSoup) -> str:
    """Pull the written narrative out of the page, skipping data tables/widgets."""
    content = soup.select_one("#content")
    if content is None:
        return ""

    parts = []

    key_points = content.select_one(".dfe-field")
    if key_points:
        text = key_points.get_text(strip=True)
        if text:
            parts.append(f"Key points: {text}")

    for section in content.select(".dfe-section"):
        heading = section.find(["h2", "h3"])
        heading_text = heading.get_text(strip=True) if heading else None

        section_paragraphs = []
        for p in section.find_all("p"):
            if p.find_parent(class_="dfe-block") is not None:
                continue  # inside a table/iframe wrapper, not narrative prose
            text = p.get_text(" ", strip=True)
            if len(text) > 40:  # drop footnote fragments and empty/near-empty tags
                section_paragraphs.append(text)

        if section_paragraphs:
            if heading_text:
                parts.append(heading_text + ":")
            parts.extend(section_paragraphs)

    return "\n".join(parts)


def fetch_fluview_report(year: int, week: int) -> dict | None:
    """Fetch and parse one FluView weekly report. Returns None if it doesn't exist (404)."""
    url = FLUVIEW_URL.format(year=year, week=week)
    resp = requests.get(url, timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else f"FluView Week {week}, {year}"

    date_tag = soup.select_one("time[datetime]")
    published_date = date_tag["datetime"][:10] if date_tag and date_tag.get("datetime") else None

    content = _extract_narrative(soup)
    if not content:
        return None

    return {
        "source": "cdc_fluview",
        "title": title,
        "content": content,
        "region": "US",
        "published_date": published_date,
        "url": url,
    }


def find_latest_report(max_lookback_weeks: int = 8) -> dict | None:
    """
    Probe backward from today's ISO week to find the most recently published report.
    Needed because CDC's report week numbering lags and drifts from ISO calendar weeks
    (see module docstring) - there's no reliable formula, so we discover it live.
    """
    today = date.today()
    year, week, _ = today.isocalendar()

    # Start a couple weeks ahead of the ISO estimate since CDC's numbering has been
    # observed running behind, then walk backward until a real report is found.
    for offset in range(-2, max_lookback_weeks):
        probe_week = week - offset
        probe_year = year
        if probe_week < 1:
            probe_year -= 1
            probe_week += 52
        if probe_week > 53:
            continue
        report = fetch_fluview_report(probe_year, probe_week)
        if report is not None:
            return report
    return None


def fetch_recent_reports(count: int = 8) -> list[dict]:
    """Walk backward from the latest published report to collect several recent weeks."""
    latest = find_latest_report()
    if latest is None:
        return []

    match = re.search(r"(\d{4})-week-(\d{2})", latest["url"])
    year, week = int(match.group(1)), int(match.group(2))

    reports = [latest]
    for _ in range(count - 1):
        week -= 1
        if week < 1:
            year -= 1
            week = 52
        report = fetch_fluview_report(year, week)
        if report is not None:
            reports.append(report)
    return reports


if __name__ == "__main__":
    latest = find_latest_report()
    if latest:
        print(f"{latest['title']}\n")
        print(latest["content"][:1000])
    else:
        print("No FluView report found")
