# Data dictionary

Generated from `portal/views.py::DICTIONARY`, `config/source_register.json`, the analytic file and the database; regenerate with the snippet in `docs/REPRODUCIBILITY.md`. The dictionary reflects the files actually downloaded, not the variable names proposed in the plan: variables the sources do not contain are listed as unavailable.

## 1. Analytic variables (one row per state; 37 rows)

| Variable | Definition | Analytical role | Source |
|---|---|---|---|
| `state` | Standardised state name (36 states + FCT) | Grouping / adjustment | config/states.csv; all sources |
| `state_code` | Two-letter state code (assigned by this project) | Identifier | config/states.csv |
| `zone` | Geopolitical zone: NC, NE, NW, SE, SS, SW | Grouping | config/states.csv |
| `region` | North (NC, NE, NW) or South (SE, SS, SW) | Confounder / subgroup | derived |
| `oos_total_2021, oos_male_2021, oos_female_2021` | Primary out-of-school rate, % of primary-age children (MICS6 2021) | PRIMARY OUTCOME and sex components | UNICEF-MICS6-2021 |
| `pqtr` | Public pupils / qualified public teachers, 2016/17 (computed from counts) | TREATMENT (log used in models) | FME-DIGEST-2017 |
| `ptr` | Public pupils / all public teachers, 2016/17 | Alternative treatment | FME-DIGEST-2017 |
| `pct_qualified_calc` | Qualified teachers as % of all public teachers | Descriptive / predictive feature | FME-DIGEST-2017 |
| `pov_215` | Poverty headcount at $2.15/day, 2018, % | CONFOUNDER / subgroup variable | WB-GPP-2018 |
| `pop6_11_2015` | Projected population aged 6-11 (2015/16) | Weight | FME-OOS-2015 |
| `etpr_2015` | Enrolment-to-population ratio, age 6-11, 2015/16 (%) | Baseline access (lagged covariate) | FME-OOS-2015 |
| `private_share_enrol` | Private schools' share of primary enrolment, % | Descriptive (not adjusted for: possible mediator) | FME-DIGEST-2017 |
| `female_share_total` | Girls' share of primary enrolment, % | Gender inequality (counts) | FME-DIGEST-2017 |
| `completion_m / completion_f, ger_m / ger_f` | Primary completion and gross enrolment ratios by sex (as printed; several implausible >100%) | Descriptive only; flagged | FME-DIGEST-2017 |
| `in_primary_sample` | True when treatment, outcome and confounder are all valid | Inclusion criterion | derived |
| `flags / n_critical_flags` | Integrity flags raised by the cleaning rules | Quality | derived |
| `oos_primary / oos_lower_secondary / oos_upper_secondary` | National out-of-school rates by sex, area and wealth quintile (MICS6 2021, Table 3) | National inequality by wealth / rural-urban / sex | UNICEF-MICS6-2021 |
| `rural_urban (state level)` | NOT available at state level: the extraction could not be verified (see data quality report) | Rejected | UNICEF-MICS6-2021 |
| `household_wealth (household level)` | NOT available: no household microdata were accessible; wealth quintile rates exist only at national level | Not available | - |

## 2. Columns in `data/processed/state_analytic.parquet`

| Column | Type | Non-missing of 37 |
|---|---|---|
| `state` | str | 37 |
| `state_code` | str | 37 |
| `zone` | str | 37 |
| `capital` | str | 37 |
| `lat` | float64 | 37 |
| `lon` | float64 | 37 |
| `pop6_11_2015` | float64 | 37 |
| `pop6_11_m_2015` | float64 | 37 |
| `pop6_11_f_2015` | float64 | 37 |
| `enrol_2015` | float64 | 34 |
| `enrol_m_2015` | float64 | 34 |
| `enrol_f_2015` | float64 | 34 |
| `etpr_2015` | float64 | 34 |
| `etpr_m_2015` | float64 | 34 |
| `etpr_f_2015` | float64 | 33 |
| `oos_children_2015` | float64 | 34 |
| `pub_schools` | float64 | 36 |
| `pub_pupils` | float64 | 34 |
| `pub_female` | float64 | 36 |
| `priv_schools` | float64 | 37 |
| `priv_pupils` | float64 | 34 |
| `priv_female` | float64 | 34 |
| `total_pupils` | float64 | 32 |
| `total_female` | float64 | 34 |
| `female_share_total` | float64 | 34 |
| `private_share_enrol` | float64 | 34 |
| `gpi_counts` | float64 | 34 |
| `t_m` | float64 | 34 |
| `t_f` | float64 | 34 |
| `t_mf` | float64 | 35 |
| `q_m` | float64 | 35 |
| `q_f` | float64 | 35 |
| `q_mf` | float64 | 35 |
| `pct_qualified_calc` | float64 | 35 |
| `female_teacher_share` | float64 | 34 |
| `t211_enrolment` | float64 | 37 |
| `t211_teachers` | float64 | 37 |
| `t211_qualified` | float64 | 37 |
| `ptr_calc` | float64 | 37 |
| `pqtr_calc` | float64 | 37 |
| `ger_m` | float64 | 35 |
| `ger_f` | float64 | 33 |
| `gpi_printed` | float64 | 37 |
| `completion_m` | float64 | 32 |
| `completion_f` | float64 | 33 |
| `ptr_t212` | float64 | 37 |
| `oos_total_2021` | float64 | 37 |
| `oos_male_2021` | float64 | 37 |
| `oos_female_2021` | float64 | 37 |
| `oos_gender_gap_2021` | float64 | 37 |
| `pov_215` | float64 | 36 |
| `pov_365` | float64 | 36 |
| `pov_685` | float64 | 36 |
| `region` | str | 37 |
| `pqtr` | float64 | 32 |
| `ptr` | float64 | 32 |
| `log_pqtr` | float64 | 32 |
| `enrol_ratio_2016` | float64 | 32 |
| `pqtr_robust_z` | float64 | 32 |
| `has_complete_vars` | bool | 37 |
| `critical_flag` | bool | 37 |
| `in_primary_sample` | bool | 37 |
| `exclusion_reason` | str | 37 |
| `flags` | str | 37 |
| `n_critical_flags` | int64 | 37 |

## 3. Indicator definitions

| Indicator | Definition | Denominator | Weighting | Missing-data rule | Comparable |
|---|---|---|---|---|---|
| etpr_2015 |  | Projected population age 6-11 | Ratio of state totals | Rows failing duplicate/identity checks set missing | NO |
| female_share_total |  | Total primary pupils | Ratio of state totals | Missing where totals fail integrity checks | yes |
| oos_female_2021 |  | Girls of primary-school age | As above | No imputation | yes |
| oos_male_2021 |  | Boys of primary-school age | As above | No imputation | yes |
| oos_total_2021 |  | Children of primary-school age (household survey sample) | Survey-weighted by UNICEF/NBS; state rates used as published (rounded to whole %) | No imputation; none missing | yes |
| pct_qualified_calc |  | All public primary teachers | Ratio of state totals | As PQTR | yes |
| pov_215 |  | Population | As published | Borno missing; no imputation | yes |
| pqtr |  | Qualified public primary teachers (NCE and above as defined in the Digest) | Unweighted ratio of state totals | Set to missing where integrity rules R04/R06 fail | yes |
| private_share_enrol |  | Total primary pupils | Ratio of state totals | Missing where totals fail integrity checks | yes |
| ptr |  | All public primary teachers | Unweighted ratio of state totals | As PQTR | yes |

## 4. Source register

| ID | Name | Publisher | Year | Period | Licence | Access date |
|---|---|---|---|---|---|---|
| FME-DIGEST-2017 | Federal Ministry of Education (Nigeria) - Nigeria Digest of Education Statistics 2017 (NEMIS) | Federal Ministry of Education, Department of Planning, Research and Development / NEMIS | 2018 | School year 2016/2017 | Not stated in the document (government publication) | 2026-10-22 |
| FME-OOS-2015 | Federal Ministry of Education - Table 2.23 Out-of-School Children (age 6-11) by State and Gender 2015/2016 | Federal Ministry of Education (publisher not named on the page) | 2019 | School year 2015/2016 | Not stated | 2026-10-22 |
| UNICEF-MICS6-2021 | Nigeria Education Fact Sheets: Analyses for learning and equity using MICS data (MICS6 / MICS-EAGLE, 2021) | UNICEF Nigeria with the National Bureau of Statistics | 2022 | Fieldwork Sep-Dec 2021; school year 2020-2021 | Not stated (UNICEF publication) | 2026-10-22 |
| WB-GPP-2018 | World Bank Geospatial Poverty Portal: state poverty headcount, 2018 (as compiled on Wikipedia 'List of Nigerian states by poverty rate') | World Bank (compiled by Wikipedia contributors) | 2018 | 2018 | Wikipedia text CC BY-SA 4.0; underlying World Bank open data CC BY 4.0 | 2026-10-22 |
| WB-WDI | World Bank World Development Indicators (Nigeria, national series) | World Bank / UNESCO Institute for Statistics | 2026 | 1990-2023 (indicator-specific) | CC BY 4.0 (World Bank Open Data terms) | 2026-10-22 |
| GH-CAPITALS | nigeria-states-GeoJSON (state capital point coordinates) | horlabyc (GitHub); coordinates credited to locationsng-api |  | n/a | Not stated | 2026-10-22 |

URLs, documentation, limitations and permitted uses for each source are in `config/source_register.json` and on the Data page of the portal.

## 5. Datasets and readiness

| Dataset | Raw file | Source | Rows | Readiness |
|---|---|---|---|---|
| `fme_2015_16_oos` | `fme_2015_16_table2_23_oos_by_state.csv` | FME-OOS-2015 | 38 | Approved with limitations |
| `fme_2016_17_enrolment` | `fme_digest_2017_table2_8_enrolment_2016_17.csv` | FME-DIGEST-2017 | 38 | Approved with limitations |
| `fme_2016_17_key_indicators` | `fme_digest_2017_table2_12_key_indicators_2016_17.csv` | FME-DIGEST-2017 | 38 | Approved with limitations |
| `fme_2016_17_ptr` | `fme_digest_2017_table2_11_public_ptr_2016_17.csv` | FME-DIGEST-2017 | 37 | Approved with limitations |
| `fme_2016_17_teachers` | `fme_digest_2017_table2_10_public_teachers_2016_17.csv` | FME-DIGEST-2017 | 38 | Approved with limitations |
| `gh_capitals` | `state_capitals_points.geojson` | GH-CAPITALS | 37 | Rejected |
| `mics_2021_national` | `unicef_mics6_2021_national_oos_by_group.csv` | UNICEF-MICS6-2021 | 10 | Approved with limitations |
| `mics_2021_oos` | `unicef_mics6_2021_primary_oos_by_state.csv` | UNICEF-MICS6-2021 | 37 | Approved with limitations |
| `wb_poverty_2018` | `wb_gpp_poverty_2018_by_state.csv` | WB-GPP-2018 | 36 | Approved |
| `wdi_national` | `wdi_nga_national_series.csv` | WB-WDI | 88 | Approved with limitations |
