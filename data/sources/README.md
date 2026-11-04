# Source documents

The documents below are **not included in this repository**: their copyright belongs to their authors and
publishers. Download them to this folder under the file names shown, then run
`python scripts/build_assumptions.py` to rebuild `data/assumptions.csv` from them.

The `param_id` prefixes refer to rows of `data/assumptions.csv`; the `citation`, `locator` and `page`
columns of each row give the exact table and page.

| File name | Document | Author / institution | Year | Download | Supports in `assumptions.csv` |
|---|---|---|---|---|---|
| `bio_2011_2020.pdf` | *Clinical Development Success Rates and Contributing Factors 2011–2020* | D. Thomas, D. Chancellor, A. Micklus et al.; BIO, Informa Pharma Intelligence, QLS Advisors | 2021 (Feb) | https://go.bio.org/rs/490-EHZ-999/images/ClinicalDevelopmentSuccessRates2011_2020.pdf | `BIO21_POS_*`: phase transition success rates by therapeutic area (Fig. 2, p.7), including the base-case gates `BIO21_POS_P2_P3_ALL_INDICATIONS`, `BIO21_POS_P3_NDA_ALL_INDICATIONS`, `BIO21_POS_NDA_APP_ALL_INDICATIONS`. `BIO21_LOA_*`: likelihood of approval (Fig. 5b, p.11) |
| `wong2019_epmc.xml` | Wong C.H., Siah K.W., Lo A.W. *Estimation of clinical trial success rates and related parameters.* Biostatistics 20(2):273–286, doi:10.1093/biostatistics/kxx069 | Authors as listed; journal published by Oxford University Press | 2019 | Full-text XML from Europe PMC: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6409418/fullTextXML (article page: https://pmc.ncbi.nlm.nih.gov/articles/PMC6409418/) | `WONG19_*`: probability of success by phase and therapeutic group (Table 2), including the sensitivity-scenario gates `WONG19_ALL_P2_P3_OVERALL`, `WONG19_ALL_P3_APP_OVERALL`. Page numbers are not verified against the journal PDF (`page_verified=no`) |
| `wong2019_pmc.html` | Same article, PMC HTML page (reference copy only; not parsed) | — | 2019 | https://pmc.ncbi.nlm.nih.gov/articles/PMC6409418/ | — |
| `fda_pdufa_vii_commitment_letter.pdf` | *PDUFA Reauthorization Performance Goals and Procedures, Fiscal Years 2023 Through 2027* (PDUFA VII commitment letter) | U.S. Food and Drug Administration | 2021 | https://www.fda.gov/media/151712/download | `FDA_PDUFA_STANDARD_NME` (12 months), `FDA_PDUFA_PRIORITY_NME` (8 months): review-time inputs (p.4). `FDA_PDUFA_*_NON_NME`: reference only |
| `fda_priority_review_page.html` | *Priority Review* (web page) | U.S. Food and Drug Administration | page content current as of 2018-01-04 | https://www.fda.gov/patients/fast-track-breakthrough-therapy-accelerated-approval-priority-review/priority-review | Cross-check of the 6- vs 10-month review goals in the `FDA_PDUFA_*` rows |
| `fda_new_drug_therapy_approvals_2023.pdf` | *New Drug Therapy Approvals 2023* | FDA Center for Drug Evaluation and Research (CDER) | 2024 (Jan) | https://www.fda.gov/media/175253/download (index: https://www.fda.gov/drugs/development-approval-process-drugs/novel-drug-approvals-fda) | Reference note in `ASSUMPTION_P_PRIORITY` (31 of 55 novel drugs had priority review, p.11). Not a model input |
| `aspe_sertkaya2014_clinical_trial_costs.pdf` | *Examination of Clinical Trial Costs and Barriers for Drug Development* | A. Sertkaya, A. Birkenbach, A. Berlind, J. Eyraud (Eastern Research Group) for HHS Office of the Assistant Secretary for Planning and Evaluation (ASPE) | 2014 (July 25) | https://aspe.hhs.gov/sites/default/files/migrated_legacy_files//44516/rpt_erg.pdf (report page: https://aspe.hhs.gov/reports/examination-clinical-trial-costs-barriers-drug-development) | `ASPE14_COST_P2_MEAN`, `ASPE14_COST_P3_MEAN`: base-case cost per trial (Table 2, p.3-6). `ASPE14_COST_P{2,3}_{MIN,MAX}_AREA`: cost sensitivity range (Table 1, p.3-3). `ASPE14_COST_NDA_FEE`: reference only |

Not in this folder: **ClinicalTrials.gov** trial records, the source of all trial durations
(`data/processed/durations_*.csv`). They are fetched from the public API v2
(https://clinicaltrials.gov/api/v2/studies) into `data/raw/` (also not in the repository):

```bash
python scripts/fetch_ctgov.py      # writes data/raw/ctgov_phase2_3_<UTC timestamp>.jsonl.gz + .manifest.json
python scripts/clean_durations.py  # uses the newest complete snapshot -> data/processed/, docs/filter_log.md
```

ClinicalTrials.gov is updated continuously, so a new snapshot will not reproduce the committed
`data/processed/` files exactly. Each manifest records the API's data timestamp; the committed results
come from the snapshot fetched 2026-10-28 00:00 UTC (API data timestamp 2026-10-27T09:00:04).
