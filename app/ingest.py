"""
Ingestion job: pulls real CDC influenza-like illness (ILI) surveillance data from the
CMU Delphi Epidata API (which republishes CDC's own ILINet data), cleans it, stores it
in CockroachDB. This is the function EventBridge -> Lambda calls every 4 hours.

Data source: https://cmu-delphi.github.io/delphi-epidata/api/fluview.html
- No API key required for public data.
- License: Publicly Accessible US Government (usa.gov/government-works).
- Weekly granularity (CDC ILINet reports weekly, not daily - a 4h cron will mostly see
  the same week's number until it updates, which is fine and expected for this data).
"""

import requests
from datetime import date, datetime, timedelta
from app.config import TARGET_REGIONS, TARGET_SIGNAL
from app.db import upsert_signal

DELPHI_BASE_URL = "https://api.delphi.cmu.edu/epidata/fluview/"

# Delphi/CDC region codes for the states in scope. Add more here if you widen TARGET_REGIONS.
# Full list of valid codes: https://cmu-delphi.github.io/delphi-epidata/api/geographic_codes.html
STATE_TO_REGION_CODE = {
    "California": "ca",
    "New York": "ny",
}


def _current_epiweek() -> int:
    """CDC epiweeks are close to ISO weeks; good enough approximation for this project."""
    year, week, _ = datetime.utcnow().isocalendar()
    return year * 100 + week


def _epiweek_to_date(epiweek: int) -> str:
    """Convert an epiweek (e.g. 202632) to that week's Monday date, for storage as observed_date."""
    year = epiweek // 100
    week = epiweek % 100
    return datetime.fromisocalendar(year, week, 1).date().isoformat()


def fetch_cdc_data(region: str) -> list[dict]:
    """Pull the last ~8 weeks of ILI data for one region from the Delphi Epidata API."""
    region_code = STATE_TO_REGION_CODE.get(region)
    if region_code is None:
        raise ValueError(f"No Delphi region code mapped for '{region}' - add it to STATE_TO_REGION_CODE")

    current = _current_epiweek()
    start = current - 8  # rough 8-week lookback; fine even if it crosses a year boundary loosely

    resp = requests.get(
        DELPHI_BASE_URL,
        params={"regions": region_code, "epiweeks": f"{start}-{current}"},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("result") != 1:
        print(f"[ingest] No data for {region} ({region_code}): {payload.get('message')}")
        return []

    records = []
    for row in payload.get("epidata", []):
        value = row.get("wili") if row.get("wili") is not None else row.get("ili")
        if value is None:
            continue
        records.append({"date": _epiweek_to_date(row["epiweek"]), "value": value})
    return records


def clean_record(raw: dict) -> dict | None:
    """Validate and normalize one raw record. Return None to drop bad records."""
    try:
        observed_date = raw["date"]
        value = float(raw["value"])
        if value < 0:
            return None
        return {"observed_date": observed_date, "value": value}
    except (KeyError, ValueError, TypeError):
        return None


# --- RESP-NET: COVID-19, flu, and RSV combined hospitalization rates -------------------
# One additional CDC source that covers THREE signals at once, instead of three separate
# fragile integrations. Dataset: "Rates of Laboratory-Confirmed RSV, COVID-19, and Flu
# Hospitalizations from RESP-NET" on data.cdc.gov (Socrata).
#
# TODO: go to data.cdc.gov, search "RESP-NET", open the dataset, click "API" to get the
# real resource ID and confirm these field names, then fill in below.
RESPNET_RESOURCE_ID = "REPLACE_ME"  # e.g. "abcd-1234", from the dataset's API tab
RESPNET_BASE_URL = f"https://data.cdc.gov/resource/{RESPNET_RESOURCE_ID}.json"

# Map our signal_type values to whatever the dataset calls each disease/network -
# confirm exact values once you've pulled a sample row (surveillance network field).
RESPNET_SIGNAL_MAP = {
    "covid19_hospitalization": "COVID-19-NET",
    "rsv_hospitalization": "RSV-NET",
    # flu is already covered by Delphi/ILINet above, so not duplicated here
}


def fetch_respnet_data(region: str, network_label: str) -> list[dict]:
    """Pull recent RESP-NET hospitalization rates for one disease network + region."""
    if RESPNET_RESOURCE_ID == "REPLACE_ME":
        raise NotImplementedError(
            "Fill in RESPNET_RESOURCE_ID at the top of app/ingest.py - see the TODO comment"
        )

    resp = requests.get(
        RESPNET_BASE_URL,
        params={
            "$where": f"surveillance_network='{network_label}' AND state='{region}'",
            "$order": "week_ending_date DESC",
            "$limit": 12,
        },
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()

    records = []
    for row in rows:
        try:
            records.append({"date": row["week_ending_date"][:10], "value": row["rate"]})
        except KeyError:
            continue  # field names not confirmed yet - see TODO above
    return records


def run_ingest():
    results = {"regions_processed": 0, "records_stored": 0, "records_dropped": 0}
    for region in TARGET_REGIONS:
        # Signal 1: flu, from Delphi/ILINet (already working)
        raw_records = fetch_cdc_data(region)
        for raw in raw_records:
            cleaned = clean_record(raw)
            if cleaned is None:
                results["records_dropped"] += 1
                continue
            upsert_signal(
                source="cdc_ilinet",
                signal_type=TARGET_SIGNAL,
                region=region,
                observed_date=cleaned["observed_date"],
                value=cleaned["value"],
            )
            results["records_stored"] += 1

        # Signals 2 & 3: COVID-19 and RSV, from RESP-NET (fill in RESPNET_RESOURCE_ID first)
        for signal_type, network_label in RESPNET_SIGNAL_MAP.items():
            try:
                raw_records = fetch_respnet_data(region, network_label)
            except NotImplementedError as e:
                print(f"[ingest] Skipping {signal_type}: {e}")
                continue
            for raw in raw_records:
                cleaned = clean_record(raw)
                if cleaned is None:
                    results["records_dropped"] += 1
                    continue
                upsert_signal(
                    source="cdc_respnet",
                    signal_type=signal_type,
                    region=region,
                    observed_date=cleaned["observed_date"],
                    value=cleaned["value"],
                )
                results["records_stored"] += 1

        results["regions_processed"] += 1

    print(f"[ingest] {date.today()} run complete: {results}")
    return results


if __name__ == "__main__":
    run_ingest()
