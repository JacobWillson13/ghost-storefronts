CSV column definitions; dates use ISO format, missing dates are blank, and rates are fractions.

## yearly_overview.csv

| Column | Definition |
|---|---|
| `visits` | Eligible visit-record count in this group/bin. |
| `oob` | Records whose outcome is recorded out of business. |
| `violations` | Records with harmonized violation outcome. |
| `first_visits` | Records with no strictly earlier business timestamp. |
| `oob_unknown_positive` | OOB records with no earlier positive observation. |
| `repeat_unresolved_oob` | OOB records with an earlier OOB and no later positive before this record. |
| `oob_old12` | OOB records with a known last positive more than 12 calendar months earlier. |
| `oob_old24` | OOB records with a known last positive more than 24 calendar months earlier. |
| `oob_old36` | OOB records with a known last positive more than 36 calendar months earlier. |
| `oob_share` | OOB count / visits (0–1). |
| `violation_share` | Violations / visits (0–1). |
| `year` | Inspection calendar year; 2026 ends August 23. |
| `source` | archive or live; 2023 has two partial source periods. |

## program_2023_2026.csv

| Column | Definition |
|---|---|
| `visits` | Eligible visit-record count in this group/bin. |
| `oob` | Records whose outcome is recorded out of business. |
| `violations` | Records with harmonized violation outcome. |
| `first_visits` | Records with no strictly earlier business timestamp. |
| `oob_unknown_positive` | OOB records with no earlier positive observation. |
| `repeat_unresolved_oob` | OOB records with an earlier OOB and no later positive before this record. |
| `oob_old12` | OOB records with a known last positive more than 12 calendar months earlier. |
| `oob_old24` | OOB records with a known last positive more than 24 calendar months earlier. |
| `oob_old36` | OOB records with a known last positive more than 36 calendar months earlier. |
| `oob_share` | OOB count / visits (0–1). |
| `violation_share` | Violations / visits (0–1). |
| `year` | Inspection calendar year; 2026 ends August 23. |
| `inspection_type` | Live recorded program, assumed planned only in the explicitly named model variant. |
| `share_of_year_live_oob` | Program OOB / all live OOB records in that year (0–1). |

## staleness_by_year.csv

| Column | Definition |
|---|---|
| `oob` | Records whose outcome is recorded out of business. |
| `year` | Inspection calendar year; 2026 ends August 23. |
| `age_bin` | Prior-positive age in continuous months: 0–12, 12–24, 24–36, 36–60, 60–120, 120+, Unknown. |
| `year_oob` | All OOB records in this year; repeated denominator, do not sum across bins. |
| `share_of_year_oob` | Age-bin OOB / year_oob (0–1). |

## nta_2025.csv

| Column | Definition |
|---|---|
| `visits` | Eligible visit-record count in this group/bin. |
| `oob` | Records whose outcome is recorded out of business. |
| `violations` | Records with harmonized violation outcome. |
| `first_visits` | Records with no strictly earlier business timestamp. |
| `oob_unknown_positive` | OOB records with no earlier positive observation. |
| `repeat_unresolved_oob` | OOB records with an earlier OOB and no later positive before this record. |
| `oob_old12` | OOB records with a known last positive more than 12 calendar months earlier. |
| `oob_old24` | OOB records with a known last positive more than 24 calendar months earlier. |
| `oob_old36` | OOB records with a known last positive more than 36 calendar months earlier. |
| `oob_share` | OOB count / visits (0–1). |
| `violation_share` | Violations / visits (0–1). |
| `nta2020` | NTA 2020 code; join to GeoJSON property `nta2020`. Includes neighborhoods with at least 500 visits in 2025. |
| `nta_name` | Point-assigned NTA name; use code for joins. |

## industry.csv

| Column | Definition |
|---|---|
| `visits` | Eligible visit-record count in this group/bin. |
| `oob` | Records whose outcome is recorded out of business. |
| `violations` | Records with harmonized violation outcome. |
| `first_visits` | Records with no strictly earlier business timestamp. |
| `oob_unknown_positive` | OOB records with no earlier positive observation. |
| `repeat_unresolved_oob` | OOB records with an earlier OOB and no later positive before this record. |
| `oob_old12` | OOB records with a known last positive more than 12 calendar months earlier. |
| `oob_old24` | OOB records with a known last positive more than 24 calendar months earlier. |
| `oob_old36` | OOB records with a known last positive more than 36 calendar months earlier. |
| `oob_share` | OOB count / visits (0–1). |
| `violation_share` | Violations / visits (0–1). |
| `period` | 2025 or pooled 2015–2019. |
| `industry_group` | Latest earlier industry for visits; latest recorded industry for snapshots. |

## chain_timelines.csv

| Column | Definition |
|---|---|
| `chain` | Explicit chain alias group; RadioShack includes General Wireless; Rite Aid includes Genovese. |
| `location` | Chain-specific BBL or normalized address key; not a unique physical-business census. |
| `address` | Latest observed normalized address for display. |
| `last_seen` | Last visit-record timestamp at this chain/location. |
| `last_positive` | Last compliant, warning or violation timestamp. |
| `first_oob` | First OOB-record timestamp, possibly followed by a positive. |
| `last_oob` | Last OOB-record timestamp. |
| `positive_to_first_oob_days` | Days from last strictly earlier positive to first OOB, nullable; not shutdown latency. |

## model_topk.csv

| Column | Definition |
|---|---|
| `era` | archive test 2019 or live test 2025. |
| `ranker` | staleness_rule, logistic_history, lightgbm_history, or live lightgbm_planned_type. |
| `test_visits` | All eligible test records; repeated denominator across budgets/rankers. |
| `test_oob` | All OOB test records; repeated denominator. |
| `roc_auc` | Test ROC area; repeated per budget. |
| `average_precision` | Test average precision (stepwise PR summary), repeated per budget. |
| `budget` | Fraction of test visit records selected: 0.05, 0.10, 0.20. |
| `selected` | ceil(budget × test_visits); score ties use SHA-256 of inspection ID. |
| `oob` | Selected-set OOB record count. |
| `precision` | Selected OOB / selected records (0–1). |
| `recall` | Selected OOB / test_oob (0–1). |
| `violations` | Selected-set violation record count. |
| `rest_visits` | Test visit records outside the selected set. |
| `rest_oob` | OOB records outside the selected set. |
| `rest_violations` | Violation records outside the selected set. |
| `violation_rate` | Selected violations / selected records (0–1). |
| `rest_violation_rate` | Remaining violations / rest_visits (0–1). |
| `scenario_net_violations_per_1000` | 1000 × (rest_violation_rate − violation_rate); exchangeability scenario, not measured intervention gain. |

## calibration.csv

| Column | Definition |
|---|---|
| `era` | archive test 2019 or live test 2025. |
| `ranker` | staleness_rule, logistic_history, lightgbm_history, or live lightgbm_planned_type. |
| `version` | raw or validation-Platt-calibrated; rule has only calibrated probabilities. |
| `bin` | Test probability quantile interval (up to ten bins; duplicate cutpoints collapse). |
| `visits` | Eligible visit-record count in this group/bin. |
| `oob` | OOB count in this probability bin. |
| `mean_probability` | Mean OOB probability in the bin/group. |
| `observed_share` | Bin OOB / visits (0–1). |

## ghost_by_nta.csv

| Column | Definition |
|---|---|
| `nta2020` | NTA 2020 code; join to `nta2020` in the boundary GeoJSON; UNMAPPED identities are excluded from this CSV but retained in snapshot totals. |
| `nta_name` | Point-assigned NTA name; use code for joins. |
| `businesses` | Snapshot identities with a positive since January 1, 2023 and no unresolved OOB in this group, as of end of August 23, 2026. |
| `expected_oob` | Sum of history-only calibrated probabilities: expected recorded-OOB count if visited under transport assumptions. |
| `mean_probability` | Mean OOB probability in the bin/group. |

## ghost_by_industry.csv

| Column | Definition |
|---|---|
| `industry_group` | Latest earlier industry for visits; latest recorded industry for snapshots. |
| `businesses` | Snapshot identities with a positive since January 1, 2023 and no unresolved OOB in this group, as of end of August 23, 2026. |
| `expected_oob` | Sum of history-only calibrated probabilities: expected recorded-OOB count if visited under transport assumptions. |
| `mean_probability` | Mean OOB probability in the bin/group. |
