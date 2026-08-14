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
    "US": "nat",
    "California": "ca",
    "Texas": "tx",
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
    try:
        return datetime.fromisocalendar(year, week, 1).date().isoformat()
    except ValueError:
        # CDC's epiweek numbering isn't strictly ISO - some years it reaches a week 53
        # that ISO's calendar doesn't have for that year. Approximate as one week past
        # ISO week 52, consistent with this function's existing documented approximation.
        return (datetime.fromisocalendar(year, 52, 1) + timedelta(weeks=1)).date().isoformat()


def fetch_cdc_data(region: str, epiweek_range: str | None = None) -> list[dict]:
    """
    Pull ILI data for one region from the Delphi Epidata API. Defaults to the last ~8
    weeks (the regular rolling window this function is called with every 4h); pass an
    explicit epiweek_range (e.g. "202601-202615") to pull a specific historical window
    instead, for one-off backfills - see run_backfill().
    """
    region_code = STATE_TO_REGION_CODE.get(region)
    if region_code is None:
        raise ValueError(f"No Delphi region code mapped for '{region}' - add it to STATE_TO_REGION_CODE")

    if epiweek_range is None:
        current = _current_epiweek()
        start = current - 8  # rough 8-week lookback; fine even if it crosses a year boundary loosely
        epiweek_range = f"{start}-{current}"

    resp = requests.get(
        DELPHI_BASE_URL,
        params={"regions": region_code, "epiweeks": epiweek_range},
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


# --- RESP-NET: COVID-19 and RSV hospitalization rates -----------------------------------
# One additional CDC source that covers two signals at once. Dataset: "Rates of
# Laboratory-Confirmed RSV, COVID-19, and Flu Hospitalizations from the RESP-NET
# Surveillance Systems" on data.cdc.gov (Socrata).
# https://data.cdc.gov/Public-Health-Surveillance/Rates-of-Laboratory-Confirmed-RSV-COVID-19-and-Flu/kvib-3txy
#
# Confirmed via a live query against the dataset (2026-08-12):
# - surveillance_network values: 'FluSurv-NET', 'COVID-NET', 'RSV-NET', 'Combined'
#   (flu is already covered by Delphi/ILINet above, so FluSurv-NET is not used here)
# - state field holds full state names (e.g. 'California'); the national aggregate
#   row uses state='Overall', not a state name
# - date field is just 'date' (week-ending date), not 'week_ending_date'
# - rate value is in 'estimate' (returned as a string), not 'rate'
# - data_type must be filtered to 'Weekly Rate' (the dataset also has cumulative-season
#   rates, deaths, ICU admission, and ventilation rows mixed into the same table)
# - age_category must be filtered to 'Overall' (dataset also has many age-bracket rows)
# - rate_type filtered to 'Observed' (vs. 'Age-Adjusted' / 'Estimated')
# - sex and race must ALSO be filtered to 'All' each - even within age_category='Overall'
#   the table has separate rows broken out by sex and by race, so omitting these filters
#   returns multiple duplicate-looking rows per date
# - IMPORTANT: RESP-NET's catchment is a subset of states, not all 50 - Texas is NOT a
#   participating site for COVID-NET or RSV-NET. Of our 4 locked regions, only
#   California and New York (plus the 'Overall' national aggregate) have RESP-NET data;
#   Texas will only ever have the ILINet flu signal. This is a real data-availability
#   gap, not a bug - fetch_respnet_data() returns [] for unmapped regions rather than
#   erroring, and run_ingest() just stores fewer records for Texas.
RESPNET_RESOURCE_ID = "kvib-3txy"
RESPNET_BASE_URL = f"https://data.cdc.gov/resource/{RESPNET_RESOURCE_ID}.json"

RESPNET_SIGNAL_MAP = {
    "covid19_hospitalization": "COVID-NET",
    "rsv_hospitalization": "RSV-NET",
}

# Our TARGET_REGIONS values -> this dataset's 'state' field values.
RESPNET_REGION_MAP = {
    "US": "Overall",
    "California": "California",
    "New York": "New York",
    # Texas intentionally omitted - not a RESP-NET catchment state, see note above.
}


def fetch_respnet_data(region: str, network_label: str, date_range: tuple[str, str] | None = None) -> list[dict]:
    """
    Pull RESP-NET hospitalization rates for one disease network + region. Defaults to
    the most recent 12 weekly rows (the regular call, no date filter); pass an explicit
    date_range (start, end) as 'YYYY-MM-DD' strings to pull a specific historical window
    instead, for one-off backfills - see run_backfill().
    """
    respnet_state = RESPNET_REGION_MAP.get(region)
    if respnet_state is None:
        return []  # region has no RESP-NET catchment site - expected, not an error

    where_clause = (
        f"surveillance_network='{network_label}' AND state='{respnet_state}' "
        "AND data_type='Weekly Rate' AND age_category='Overall' AND rate_type='Observed' "
        "AND sex='All' AND race='All'"
    )
    if date_range is not None:
        start, end = date_range
        where_clause += f" AND date >= '{start}' AND date <= '{end}'"

    resp = requests.get(
        RESPNET_BASE_URL,
        params={
            "$where": where_clause,
            "$order": "date DESC",
            "$limit": 300 if date_range is not None else 12,  # 300 covers ~2 years of weekly rows
        },
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()

    records = []
    for row in rows:
        try:
            records.append({"date": row["date"][:10], "value": float(row["estimate"])})
        except (KeyError, ValueError, TypeError):
            continue
    return records


def _ingest_region(region: str, results: dict, epiweek_range: str | None = None, respnet_date_range: tuple[str, str] | None = None):
    # Signal 1: flu, from Delphi/ILINet (already working)
    raw_records = fetch_cdc_data(region, epiweek_range=epiweek_range)
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
            raw_records = fetch_respnet_data(region, network_label, date_range=respnet_date_range)
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


def run_ingest():
    """Regular ingest cycle - the rolling ~8-week window, called every 4h by Lambda."""
    results = {"regions_processed": 0, "records_stored": 0, "records_dropped": 0}
    for region in TARGET_REGIONS:
        _ingest_region(region, results)

    print(f"[ingest] {date.today()} run complete: {results}")
    return results


BACKFILL_START_EPIWEEK = 202440  # ~Sept 2024; deliberately continuous, no gaps (see HANDOFF.md)


def run_backfill(epiweek_range: str | None = None, respnet_date_range: tuple[str, str] | None = None):
    """
    One-off historical backfill for a continuous, unbroken date range (default:
    BACKFILL_START_EPIWEEK through today) - not part of the regular 4h ingest cycle,
    not wired into Lambda/EventBridge. A single range query per region/source (the
    Delphi and Socrata APIs both accept a date/epiweek range directly), not one call
    per week, so this stays fast and continuous by construction - no gaps get
    introduced the way separate disjoint backfill windows previously did.
    """
    if epiweek_range is None:
        epiweek_range = f"{BACKFILL_START_EPIWEEK}-{_current_epiweek()}"
    if respnet_date_range is None:
        respnet_date_range = (_epiweek_to_date(BACKFILL_START_EPIWEEK), date.today().isoformat())

    results = {"regions_processed": 0, "records_stored": 0, "records_dropped": 0}
    for region in TARGET_REGIONS:
        _ingest_region(region, results, epiweek_range=epiweek_range, respnet_date_range=respnet_date_range)

    print(f"[ingest] backfill ({epiweek_range}, respnet {respnet_date_range}) complete: {results}")
    return results


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        run_backfill()
    else:
        run_ingest()
