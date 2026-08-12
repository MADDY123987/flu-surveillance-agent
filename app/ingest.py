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


def fetch_respnet_data(region: str, network_label: str) -> list[dict]:
    """Pull recent RESP-NET hospitalization rates for one disease network + region."""
    respnet_state = RESPNET_REGION_MAP.get(region)
    if respnet_state is None:
        return []  # region has no RESP-NET catchment site - expected, not an error

    resp = requests.get(
        RESPNET_BASE_URL,
        params={
            "$where": (
                f"surveillance_network='{network_label}' AND state='{respnet_state}' "
                "AND data_type='Weekly Rate' AND age_category='Overall' AND rate_type='Observed' "
                "AND sex='All' AND race='All'"
            ),
            "$order": "date DESC",
            "$limit": 12,
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
