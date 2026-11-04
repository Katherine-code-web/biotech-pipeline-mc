"""Fetch Phase 2/3 trials from ClinicalTrials.gov API v2 into data/raw/.

Outputs (one run = one timestamped snapshot, never overwritten):
  data/raw/ctgov_phase2_3_<YYYYMMDDTHHMMSSZ>.jsonl.gz  raw `studies` records, one per line
  data/raw/ctgov_phase2_3_<YYYYMMDDTHHMMSSZ>.manifest.json   fetch date, query, API version, counts

Standard library only. Usage:
  python scripts/fetch_ctgov.py                  # full pull
  python scripts/fetch_ctgov.py --max-pages 2    # smoke test
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://clinicaltrials.gov/api/v2"
QUERY = "AREA[Phase](PHASE2 OR PHASE3)"  # includes PHASE2/PHASE3 combined trials
FIELDS = [
    "NCTId",
    "Phase",
    "OverallStatus",
    "StartDate",
    "StartDateType",
    "PrimaryCompletionDate",
    "PrimaryCompletionDateType",
    "StudyType",
    "LeadSponsorClass",
]
PAGE_SIZE = 1000
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


def get_json(url: str, retries: int = 4) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args()

    fetched_at = datetime.now(timezone.utc)
    stem = f"ctgov_phase2_3_{fetched_at:%Y%m%dT%H%M%SZ}"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{stem}.jsonl.gz"
    manifest_path = RAW_DIR / f"{stem}.manifest.json"

    version = get_json(f"{BASE}/version")
    params = {
        "filter.advanced": QUERY,
        "fields": ",".join(FIELDS),
        "pageSize": PAGE_SIZE,
        "countTotal": "true",
    }

    n, pages, total, token = 0, 0, None, None
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        while True:
            if token:
                params["pageToken"] = token
            data = get_json(f"{BASE}/studies?{urllib.parse.urlencode(params)}")
            total = data.get("totalCount", total)
            for study in data.get("studies", []):
                f.write(json.dumps(study, ensure_ascii=False) + "\n")
                n += 1
            pages += 1
            print(f"page {pages}: {n}/{total}", flush=True)
            token = data.get("nextPageToken")
            if not token or (args.max_pages and pages >= args.max_pages):
                break
            time.sleep(0.3)  # be polite

    manifest = {
        "source": "ClinicalTrials.gov API v2",
        "endpoint": f"{BASE}/studies",
        "params": {k: v for k, v in params.items() if k != "pageToken"},
        "fetched_at_utc": fetched_at.isoformat(timespec="seconds"),
        "api_version": version.get("apiVersion"),
        "api_data_timestamp": version.get("dataTimestamp"),
        "total_count_reported": total,
        "records_written": n,
        "pages": pages,
        "complete": n == total,
        "output_file": out_path.name,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
