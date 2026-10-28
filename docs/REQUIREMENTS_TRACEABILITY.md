# Requirements cross-check (generated)

Generated 2026-10-25T02:01:03+01:00 by `src/validation/requirements_check.py`; 142/142 automated tests passing in the supplied results file.

| Status | Count |
|---|---|
| Met | 126 |
| Met with limitation | 9 |
| Superseded by decision | 4 |
| Not verifiable here | 2 |
| NOT MET | 0 |
| **Total** | **141** |

| ID | Plan § | Requirement | Status | Evidence |
|---|---|---|---|---|
| A1 | 2.1 | Trusted data infrastructure: import, validate, clean, document and version datasets from traceable sources | Met | 6 sources, 10 datasets, 10 versions with SHA-256, 10 quality reports / tests: 3/3 passed |
| A2 | 2.2 | Inequality analysis by state, location, gender, wealth and other supported characteristics | Met | state ranking (37 states), North-South gap, gender gaps, national rural/urban and wealth-quintile gaps, poverty gradient / tests: 2/2 passed |
| A3 | 2.3 | Explainable causal AI engine: specify relationships, estimate effects, test assumptions, explain results | Met | graph + assumptions, DoWhy identification and refutations, 4 estimators, SHAP/permutation explanation, narrative explanation / tests: 2/2 passed |
| A4 | 2.4 | Counterfactual policy simulator comparing policies with a baseline, with uncertainty and subgroup impacts | Met | 3 standard scenarios with headline, inequality change, intervals and 11 subgroup rows / tests: 2/2 passed |
| A5 | 2.5 | Validated and deployable application: access, automated tests, audit trail, reproducibility, reporting, deployment documentation | Met | 142 automated tests, all passing / User-access requirement replaced by the no-authentication decision (see S1). |
| B1 | 3 | Python backend with Django as the main application (no unjustified extra frameworks) | Met | django 6.1.2 / Single Django project; JavaScript only draws charts. |
| B2 | 3 | Django templates, HTML, Bootstrap 5 | Met | Bootstrap 5 CSS/JS vendored (self-hosted) |
| B3 | 3 | Plotly interactive visualisations embedded in Django | Met | plotly 7.1.0 / tests: 1/1 passed |
| B4 | 3/6 | MySQL for application records | Not verifiable here | MySQL configuration, utf8mb4 + strict mode, driver fallback and mysqldump-based backup are implemented / No MySQL server could be installed in this sandbox, so migrations and queries were verified only on SQLite (same ORM). Run `DB_ENGINE=mysql python manage.py migrate && pytest` on the target server (docs/DEPLOYMENT.md section 3). |
| B5 | 3 | Pandas, NumPy, PyArrow data processing | Met | pandas 3.0.5, numpy 2.5.3, pyarrow 26.0.0 |
| B6 | 3 | SciPy and Statsmodels statistical analysis | Met | scipy 1.18.1, statsmodels 0.15.0 |
| B7 | 3 | DoWhy and EconML causal inference | Met | dowhy 0.14, econml 0.17.0 / tests: 1/1 passed |
| B8 | 3 | Scikit-learn machine learning (plus SHAP for explanation) | Met | sklearn 1.9.1, shap 0.54.1 |
| B9 | 3 | Geospatial analysis with GeoJSON and Plotly maps | Met with limitation | GeoJSON outline + state-capital points rendered with Plotly / limitation: State boundary polygons with licence terms were not available from the permitted sources, so the map is a point map over a national outline (stated on the page); GeoPandas is not needed for point data and is not installed. |
| B10 | 3/10.2 | Celery and Redis for background processing, if long-running tasks require them | Met with limitation | background execution via a bounded worker thread with status, timeout, retries and duplicate protection / tests: 3/3 passed / limitation: Celery/Redis not used: the plan allows simple processing for a prototype and the longest analysis takes about a minute. A queue should replace the thread worker if many concurrent users are expected. |
| B11 | 3 | Automated tests with Pytest and the Django test framework | Met | 8 test modules |
| B12 | 3 | Version control with Git | Met | repository initialised / Repository initialised (branch main); no commit has been made. When ready: git add -A && git commit. .gitignore keeps secrets, restricted data, databases and artefacts out. |
| B13 | 3/13 | Deployment with Linux server, Gunicorn, Nginx and HTTPS | Not verifiable here | gunicorn config, nginx (TLS) config and systemd unit provided / Configuration files are provided and `check --deploy` is clean (see L-series), but no public server exists in this sandbox to demonstrate HTTPS serving. |
| C1 | 4.1 | Define population and unit of analysis; do not claim school- or household-level findings without such data | Met | unit = state; methodology states data are published aggregates, not household or school records |
| C2 | 4.2 | One primary outcome and a few secondary outcomes | Met | primary: primary out-of-school rate 2021 (MICS6); secondary: boys/girls OOS rate; 2015/16 net enrolment retained as context (definitions not comparable) |
| C3 | 4.3 | Research questions formulated and answered by the application and report | Met | tests: 1/1 passed / five questions on the Methodology page, each linked to the page that answers it; answered in the report |
| D1 | 5.1 / 11.4 | Every source records URL, dataset name, year, period, access date, coverage, licence, documentation, limitations, permitted uses | Met | 6 sources checked for url, name, access date, coverage, licence, limitations, permitted uses; none missing / tests: 2/2 passed |
| D2 | 5.2 | Data-readiness gate with statuses Approved / Approved with limitations / Rejected | Met | {'Rejected': 1, 'Approved with limitations': 8, 'Approved': 1} / tests: 3/3 passed |
| D3 | 5.2 | Gate 1: no causal estimation without a defensible dataset for the primary outcome | Met | primary-outcome dataset (MICS6 2021 state OOS) is approved with limitations; causal run refuses unsupported designs / tests: 2/2 passed |
| D4 | 5.3 (1-2) | Original files kept unmodified in a raw directory, with checksums | Met | 10 raw files re-hashed against the recorded SHA-256; all identical / tests: 1/1 passed |
| D5 | 5.3 (3) | Validate file formats, column names, data types and source metadata | Met | schema check per dataset / tests: 2/2 passed |
| D6 | 5.3 (4) | Standardise state names, identifiers, years, units | Met | 37 canonical states with codes and zones / tests: 2/2 passed |
| D7 | 5.3 (5-6) | Detect duplicates, invalid values, inconsistent definitions, missing data; apply documented cleaning rules | Met | 9 documented rules (R01-R09), 6 cross-table checks, 37 row flags / tests: 2/2 passed |
| D8 | 5.3 (7) | Harmonise indicators only when definitions are comparable | Met | 1 indicator(s) flagged not comparable and not mixed / tests: 1/1 passed |
| D9 | 5.3 (8-10) | Save cleaned data separately; data-quality reports; analytical dataset with documented inclusion/exclusion criteria | Met | analytic n=31 of 37; 6 exclusions each with a reason / tests: 3/3 passed |
| D10 | 5.3 | Recommended project file structure | Met | recommended structure present |
| D11 | 5.3 | Restricted or identifiable records never committed; large raw data stored with checksums | Met | .gitignore excludes restricted data, databases, .env, artefacts; no individual-level data are held |
| D12 | 5.4 | Data dictionary with definition, source and role for each variable; reflects the actual downloads | Met | dictionary page lists variables, sources, roles and variables the sources do not contain / tests: 1/1 passed |
| E1 | 6.2 | Relational entities from the plan | Met | 15/15 planned entities (User, Role, Permission intentionally absent) |
| E2 | 6.2 | Primary/foreign keys, uniqueness constraints, timestamps, indexes, deletion policies | Met | 8 unique columns, 3 table constraints, 4 indexes; foreign keys with PROTECT/CASCADE policies; created_at timestamps / tests: 1/1 passed |
| E3 | 6.2 | Schema managed with Django migrations | Met | models and migrations are in sync (makemigrations --check) |
| E4 | 6.2 | Large model objects stored as versioned artefacts with checksums; never load untrusted serialised models | Met | no deserialisation of model files anywhere (results stored as JSON with SHA-256) / tests: 1/1 passed |
| E5 | 6.1 | Application modules: dashboard, data management, inequality, causal, policy simulation, reports and audit | Met | all seven module pages return 200 / tests: 1/1 passed |
| E6 | 6.3 / 12 | Roles (administrator, researcher, policymaker, viewer), user accounts and permission enforcement | Superseded by decision | django.contrib.auth/admin/sessions are not installed; no login, logout, register, password or admin URLs exist / tests: 2/2 passed / Superseded by the explicit project decision that the system has no authentication of any kind. Protection of the open site relies on read-only public data, CSRF, throttling, input validation and no upload endpoint. |
| F1 | 7.1 | Absolute gaps, relative gaps, disparities, resource distribution, temporal change, Gini where suitable | Met | absolute and relative gaps, gender gaps, Gini/Theil/CV/P90-P10, resource (teacher) inequality, temporal trends, concentration indices, Lorenz curve / tests: 6/6 passed |
| F2 | 7.1 | Every indicator defines denominator, eligible population, weighting, missing-data rule and interpretation | Met | 10 indicators each with denominator, weighting, missing-data rule and interpretation (shown on Methodology page) |
| F3 | 7.1 | Gini not applied indiscriminately to categories or non-comparable rates | Met | Gini restricted to numeric state rates; negative values rejected; methodology states the rule / tests: 2/2 passed |
| F4 | 7.2 | Filters for year, state, rural-urban, gender, wealth group, education level (subject to availability) | Met with limitation | filters: region, geopolitical zone, poverty group, state list, education level; year is fixed per source (single survey wave) and gender is shown as paired gaps / tests: 1/1 passed / limitation: Year filter not offered because each outcome is a single survey wave; rural-urban, sex and wealth-quintile comparisons exist only as national MICS6 figures (no state-level breakdown is published in the retrieved tables). |
| F5 | 7.2 | Visualisations: trends, group bar charts, maps, distribution plots, ranking tables, intervals | Met | trend lines, group bars, point map, Lorenz/distribution plot, ranking table, intervals (checked in browser: 7 + 6 charts render without errors) |
| F6 | 7.2 | Do not rank states on incomplete or non-comparable data without warnings | Met | 21 states carry visible data-issue flags in the ranking / tests: 2/2 passed |
| F7 | 7.2 | Functioning dashboard with reproducible calculations and downloadable results | Met | CSV, Excel, PDF and JSON exports quote run id, configuration hash and data checksum / tests: 2/2 passed |
| F8 | 7 / 11.4 | Inequality results match independently calculated cases | Met | 14/14 headline numbers reproduced by separate code (pairwise Gini, explicit HC3 sandwich, scipy Spearman, scenario arithmetic) / tests: 2/2 passed |
| G1 | 8.1 | Each analysis states treatment, outcome, confounders and estimand | Met | treatment log_pqtr, outcome oos_total_2021, confounders ['pov_215', 'north']; estimand: ATE of a 10% proportional reduction in public pupils-per-qualified-teacher on the state pr... / tests: 2/2 passed |
| G2 | 8.1 | Causal graph with directions; no adjustment for post-treatment variables | Met | graph with 6 edges plus a threat graph with unobserved U; private-school share and enrolment deliberately not adjusted (mediators/colliders) / tests: 2/2 passed |
| G3 | 8.2 | Identification strategy chosen from data and assignment mechanism; inapplicable methods documented | Met | 6 methods assessed: 3 applicable, 3 rejected with reasons (DiD, panel fixed effects, IV) / tests: 1/1 passed |
| G4 | 8.3 | Reproducible 10-step modelling workflow | Met | load approved data -> validate definitions -> graph -> identifiability -> estimators -> intervals -> overlap/balance -> refutation/robustness -> saved config, warnings, versions -> narrative / tests: 2/2 passed |
| G5 | 8.3 | Compare multiple defensible methods rather than picking the favourable one | Met | 4 estimators and 8 specifications reported together |
| G6 | 8.3 / 11.3 | Refutation checks, overlap/balance diagnostics, sensitivity analysis | Met | random common cause, placebo treatment, subsets; GPS overlap/balance; omitted-variable robustness value; leave-one-out and leave-one-zone-out / tests: 2/2 passed |
| G7 | 8.4 | Explanations at feature, causal and subgroup level; SHAP and importance not presented as causal proof | Met | SHAP + permutation importance; effect narrative; North/South and poverty-split estimates; explicit caution text / tests: 2/2 passed |
| G8 | 8 / 1 | Descriptive, predictive, causal and counterfactual analysis kept separate | Met | separate engines (src/inequality, src/causal, src/simulation) and separate pages |
| G9 | 8.2 | Honest limit on claims when identification is weak | Met | verdict: Inconclusive: no reliable evidence of a causal effect of PQTR on OOS rates that is distinguishable from zero in these data. / tests: 1/1 passed |
| H1 | 9.1 | Scenario inputs: target population, intervention, baseline, intensity, effect model, constraints, horizon, uncertainty, assumptions | Met | population/coverage, intervention and intensity, baseline = observed data, effect model, implementation range, horizon (not modelled: cross-section), uncertainty draws, assumptions list / tests: 3/3 passed |
| H2 | 9.2 | Baseline vs counterfactual table: baseline, counterfactual, absolute/relative change, inequality change, interval, subgroups, limitations | Met | baseline, counterfactual, absolute and relative change, inequality change, interval, subgroup effects, limitations / tests: 2/2 passed |
| H3 | 9.3 | Assess overall improvement and disparity change separately | Met | national mean, North-South gap, high/low-poverty gap and Gini each reported with interval / tests: 1/1 passed |
| H4 | 9.3 | No claim that a policy is cheapest or best without cost data | Met | no cost data exist; scenarios never ranked by cost-effectiveness / tests: 1/1 passed |
| H5 | 9.4 | Uncertainty intervals, sensitivity, unsupported-value checks, out-of-support warnings, separate statistical vs implementation uncertainty | Met | interval and implementation range reported separately (not combined); extrapolation and excluded-state warnings / tests: 4/4 passed |
| H6 | 9.4 | Scenario comparisons use identical outcome definitions and baselines | Met | side-by-side comparison page on a common baseline / tests: 1/1 passed |
| H7 | 9 deliverable | Interactive simulator that saves scenarios, compares outcomes, reports uncertainty, reproduces results | Met | 3 saved scenarios / tests: 3/3 passed |
| H8 | 17 | Two or three supported counterfactual scenarios | Met | 3 preset scenarios (S1 universal cap, S2 20% reduction in the North, S3 targeted cap in high-poverty states) |
| I1 | 10.1 | Pages: home, methodology, findings, dashboard, data, inequality, causal, simulation, reports, administration/system pages | Met | 11 pages return 200 to an anonymous visitor / tests: 2/2 passed |
| I2 | 10.1 | Authentication pages: login, logout, password reset, access-denied | Superseded by decision | all return 404 (do not exist) / tests: 1/1 passed / Superseded: no authentication by project decision. |
| I3 | 10.1 | Data management: sources, datasets, versions, quality reports (and uploads) | Met with limitation | sources, datasets, versions, checksums, readiness, quality reports, downloads / limitation: Browser upload of datasets is intentionally not provided: with no login, a public upload endpoint would let anyone alter the evidence base. New data are imported by the operator command `import_datasets` (docs/DATA_IMPORT_GUIDE.md). |
| I4 | 10.1 | Administration: users, permissions, audit logs, system configuration | Met with limitation | public activity (audit) log and system status/configuration page; users and permissions superseded / tests: 2/2 passed / limitation: Users/permissions do not exist (no-authentication decision); audit log and status page replace the administrative views. |
| I5 | 10.2 | Analysis job workflow: validate inputs, create AnalysisRun, execute, record progress/errors/results, view results | Met | 5 runs recorded with status, progress, retries, timings, config hash, data hash, versions / tests: 3/3 passed |
| I6 | 10.2 | Job status, retry rules, timeouts, duplicate-submission protection; failed job never leaves results marked successful | Met | database CHECK constraint forbids results on unsuccessful runs / tests: 5/5 passed |
| I7 | 10.3 | PDF and Excel reports with question, data provenance, methods, estimates and intervals, validation, assumptions, limitations; traceable to run and data version | Met | Excel (8 sheets) and PDF (9 KB) contain run id, hashes, versions, estimates, diagnostics, limitations / tests: 4/4 passed |
| J1 | 11.1 | Data validation: missingness, duplicates, invalid values, identifiers, denominators, source-to-cleaned reconciliation, inclusion rules, reproducible cleaning | Met with limitation | quality report + independent re-download matches stored raw data in 1,671/1,671 cells / tests: 3/3 passed / limitation: Survey weights/complex designs are not applicable: only published aggregates are used, so design-based intervals are unavailable (stated wherever intervals appear). Both extractions use the same text-extraction service, so errors inside the source PDFs are not detectable. |
| J2 | 11.2 | Automated tests for import, constraints, calculations, causal input validation, simulation, job failures, reports, exports | Met | 142 tests in 8 modules; areas: Dataset import and validation; Database constraints; Inequality calculations; Causal input validation; Simulation calculations; Background job failures/retries; Report generation; Export access / tests: 13/13 passed |
| J3 | 11.2 | Tests for user registration, authentication, role/permission enforcement | Superseded by decision | tests: 2/2 passed / Superseded by the no-authentication decision. Replaced by tests proving that NO authentication machinery exists and that every page and download works anonymously. |
| J4 | 11.2 | Unit, integration and end-to-end tests | Met | unit tests (metrics, engines), integration tests (services, DB), end-to-end journeys (simulation_journey_end_to_end) and a headless-browser check of all pages / tests: 2/2 passed |
| J5 | 11.3 | Baseline comparison and out-of-sample evaluation | Met | leave-one-out and leave-zone-out RMSE for mean baseline, region-only, poverty+region, +PQTR and random forest / tests: 1/1 passed |
| J6 | 11.3 | Causal refutation, sensitivity analysis, subgroup evaluation | Met | 3 refutations, robustness value, 4 subgroup estimates with interaction test |
| J7 | 11.3 | Reproducibility testing: same inputs and configuration reproduce the same results | Met | `manage.py verify_reproducibility` recomputes cleaning + inequality + causal from raw data in a fresh process and compares SHA-256 hashes / tests: 3/3 passed / A genuine defect was found and fixed during this cross-check: the stored causal hash did not reproduce in a fresh process (ordering/last-bit float noise from DoWhy). Fixed and covered by a cross-process regression test. |
| J8 | 11.3 | Report supporting evidence and unresolved threats to validity (passing a refutation test is not proof) | Met | stated on Methodology and Causal pages and in exports |
| K1 | 11.4 | Acceptance criterion - Data provenance: documented origin, version, access conditions, limitations | Met | 6/6 sources / tests: 1/1 passed |
| K2 | 11.4 | Acceptance criterion - Data processing: cleaning reproducible and quality checks pass | Met | analytic checksum identical before/after full re-clean / tests: 1/1 passed |
| K3 | 11.4 | Acceptance criterion - Inequality calculations: match independently calculated test cases | Met | 14/14 headline numbers reproduced by separate code (pairwise Gini, explicit HC3 sandwich, scipy Spearman, scenario arithmetic) / tests: 1/1 passed |
| K4 | 11.4 | Acceptance criterion - Causal estimation: treatment, outcome, confounders, assumptions and estimand documented | Met | assumptions A1-A7 documented / tests: 1/1 passed |
| K5 | 11.4 | Acceptance criterion - Uncertainty: uncertainty estimates and diagnostics available | Met | intervals for every estimator; overlap/balance; refutations / tests: 1/1 passed |
| K6 | 11.4 | Acceptance criterion - Policy simulation: baseline/intervention use consistent definitions; assumptions recorded | Met | assumptions saved with each run / tests: 1/1 passed |
| K7 | 11.4 | Acceptance criterion - Software security: access-control tests pass | Met | open-access safeguards tested (headers, CSRF, methods, traversal, escaping, injection, throttling) / tests: 3/3 passed |
| K8 | 11.4 | Acceptance criterion - Reproducibility: documented procedure reproduces key outputs | Met | verify_reproducibility command + docs / tests: 1/1 passed |
| K9 | 11.4 | Acceptance criterion - Reporting: published figures and tables trace back to the analysis run | Met | exports quote run id, configuration, data and results hashes / tests: 1/1 passed |
| L1 | 12/13.2(7) | HTTPS and secure cookies; Django deployment security checks pass | Met | manage.py check --deploy (debug off, HTTPS on): no errors; warnings: security.W021 (W021 = HSTS preload, a deliberate irreversible opt-in left to the domain owner) / tests: 1/1 passed |
| L2 | 12 | CSRF, XSS and SQL-injection protection; input validation | Met | CSRF middleware, auto-escaping templates, ORM-only queries, whitelisted configuration / tests: 5/5 passed |
| L3 | 12 | Environment-based secret management; no secrets committed | Met | secrets read from environment; .env ignored; production refuses to start without a secret key / tests: 1/1 passed |
| L4 | 12 | Audit logging for sensitive operations without personal data | Met | 6 entries; client address stored only as a salted 16-character hash / tests: 3/3 passed |
| L5 | 12 | Restricted access to raw/identifiable data; data minimisation; small-group suppression | Met | no identifiable or household/learner-level records are held or needed; the smallest unit is a state; raw files are not web-served (only cleaned CSV downloads) / tests: 2/2 passed / Small-group suppression not required because no group smaller than a state is published. |
| L6 | 12 / 13 | Secure backups and tested restoration | Met | backup of 2 items restored and verified (exit 0): Restored and verified: 2 files checksummed, 15 tables compared / Backup then restore into a scratch directory; every SHA-256 in the manifest and the table row counts verified. |
| L7 | 12 | Throttling to protect expensive endpoints on an open site | Met | 30 runs/hour per client; saved-scenario cap 500 / tests: 3/3 passed |
| L8 | 12 | Dependency updates, security testing and retention/deletion procedures | Met | pinned requirements; retention/deletion and dependency-update procedure documented in docs/DEPLOYMENT.md |
| L9 | 12 | Review of Nigerian data-protection requirements, research ethics and dataset permissions; fairness of recommendations | Met with limitation | discussed in the research report (Nigeria Data Protection Act 2023; licences; regional fairness) / limitation: Legal/ethics review is desk-based only; no formal ethics-committee or legal sign-off exists. Several source licences are 'not stated', so redistribution of raw tables should be confirmed with the publishers. |
| M1 | 13.2(1) | Separate development, testing and production configurations | Met | environment-driven DEBUG/TESTING/production modes |
| M2 | 13.2(2) | Pin and document Python package versions | Met | requirements.txt pinned to tested versions |
| M3 | 13.2(3) | Configure environment variables and production database credentials | Met | .env.example documents every variable |
| M4 | 13.2(4) | Apply database migrations | Met | migrations provided |
| M5 | 13.2(5) | Configure static files and HTTPS | Met | WhiteNoise static serving; nginx TLS config |
| M6 | 13.2(6) | Disable Django debug mode in production | Met | DEBUG defaults to off |
| M7 | 13.2(7) | Run Django's deployment security checks | Met | manage.py check --deploy (debug off, HTTPS on): no errors; warnings: security.W021 (W021 = HSTS preload, a deliberate irreversible opt-in left to the domain owner) |
| M8 | 13.2(8) | Process supervision and background workers | Met | systemd unit + gunicorn config |
| M9 | 13.2(9) | Application, worker and database logging | Met | console/journald logging configured |
| M10 | 13.2(10) | Configure backups, monitoring and error alerts | Met | backup script and /healthz endpoint for monitoring |
| M11 | 13.2(11) | Test restoring the database and analytical artefacts | Met | backup of 2 items restored and verified (exit 0): Restored and verified: 2 files checksummed, 15 tables compared |
| M12 | 13.2(12) | Document upgrades, rollback and incident response | Met | documented in docs/DEPLOYMENT.md |
| M13 | 13.2 / 13.1 | Deployment architecture (Nginx + HTTPS -> Gunicorn/Django -> database + worker/storage) documented and capacity noted | Met | diagram, sizing note (causal run needs ~1-2 GB RAM and about a minute of CPU) in docs/DEPLOYMENT.md |
| N1 | 14 | Source code: Django app, configuration templates, migrations | Met | present: portal, eduineq, portal/migrations/0001_initial.py, .env.example |
| N2 | 14 | Data package: raw data, cleaned data, data dictionary, source register | Met | present: data/raw, data/processed/state_analytic.parquet, config/source_register.json, docs/DATA_DICTIONARY.md |
| N3 | 14 | Analysis pipeline: reproducible scripts for cleaning and inequality measurement | Met | present: src/cleaning/pipeline.py, src/inequality/metrics.py, notebooks/01_reproduce_key_results.ipynb |
| N4 | 14 | Causal AI package: graphs, estimator configurations, diagnostics | Met | present: src/causal/engine.py, artefacts |
| N5 | 14 | Simulation module: baselines, scenarios, effects, uncertainty | Met | present: src/simulation/engine.py |
| N6 | 14 | Test suite: unit, integration, security, analytical validation | Met | present: tests/test_inequality_metrics.py, tests/test_causal.py, tests/test_simulation.py, tests/test_views.py, src/validation/independent_check.py |
| N7 | 14 | Research report: questions, literature review, methodology, findings, validation, discussion, limitations, references | Met | present: reports/research_report.docx, reports/research_report.pdf |
| N8 | 14 | User documentation: installation, administrator, data-import guides and user manual | Met | present: README.md, docs/INSTALLATION.md, docs/ADMIN_GUIDE.md, docs/DATA_IMPORT_GUIDE.md, docs/USER_MANUAL.md |
| N9 | 14 | Deployment package: production configuration, backup/restore instructions, operational checklist | Met | present: docs/DEPLOYMENT.md, deploy/nginx.conf, deploy/gunicorn.conf.py, deploy/eduineq.service, scripts/backup.py, scripts/restore.py |
| N10 | 14 | Report distinguishes findings from actual data from hypothetical simulation examples; accounts for limitations and inconclusive analyses | Met | simulation results labelled hypothetical in the app and exports; the primary causal result is reported as inconclusive / tests: 1/1 passed |
| N11 | 15 | Eight-week implementation schedule | Met with limitation | Not a deliverable of the software; the work was delivered in one engagement, and the sequence of the plan (data gate -> inequality -> causal -> simulation -> web -> validation) was followed. Data feasibility, the critical dependency, drove the choice of the 2021 outcome and the exclusion of the 2015/16 net-enrolment outcome as the causal outcome. |
| N12 | 16 | Major risks identified with mitigations | Met | risk register with evidence of mitigation in the report |
| P1 | 17 | Minimum viable research system: one primary outcome, documented dataset, reproducible inequality calculations, a defensible causal estimand, validation, 2-3 scenarios, working web app | Met | all six elements delivered (see A-K series) |
| Q1 | 18 | Checklist: research questions and primary outcome defined | Met | see C2, C3 |
| Q2 | 18 | Checklist: sources, licences, provenance documented | Met | 6 sources checked for url, name, access date, coverage, licence, limitations, permitted uses; none missing |
| Q3 | 18 | Checklist: data quality and coverage assessed | Met | 10 dataset assessments |
| Q4 | 18 | Checklist: data dictionary and reproducible cleaning pipeline | Met | dictionary page + `verify_reproducibility` |
| Q5 | 18 | Checklist: inequality metrics independently checked | Met | 14/14 headline numbers reproduced by separate code (pairwise Gini, explicit HC3 sandwich, scipy Spearman, scenario arithmetic) |
| Q6 | 18 | Checklist: causal graph and identification assumptions documented | Met | 7 assumptions, 2 graphs |
| Q7 | 18 | Checklist: causal estimates and uncertainty reported | Met | 4 estimators with intervals |
| Q8 | 18 | Checklist: robustness and sensitivity analyses completed | Met | 8 specifications, leave-one-out/zone-out, permutation test, fractional logit, robustness value |
| Q9 | 18 | Checklist: policy simulations compare baseline and intervention | Met | 3 scenarios |
| Q10 | 18 | Checklist: Django and MySQL integration completed | Met with limitation | Django integration complete and tested; MySQL configured / Django integration complete and tested on SQLite; MySQL configuration implemented but not run against a live MySQL server here (see B4). |
| Q11 | 18 | Checklist: authentication and role permissions tested | Superseded by decision | Superseded by the no-authentication decision (see E6). |
| Q12 | 18 | Checklist: dashboards, filters and reports working | Met | 11 pages return 200 to an anonymous visitor |
| Q13 | 18 | Checklist: analysis jobs and error handling tested | Met | see I5, I6 |
| Q14 | 18 | Checklist: audit logs and data-access safeguards implemented | Met | audit log + safeguards (L-series) |
| Q15 | 18 | Checklist: automated and end-to-end tests passed | Met | 142 tests, 142 passed |
| Q16 | 18 | Checklist: key results reproduced from documented inputs | Met | see J7 and F8 |
| Q17 | 18 | Checklist: deployment and backup restoration tested | Met | backup of 2 items restored and verified (exit 0): Restored and verified: 2 files checksummed, 15 tables compared |
| Q18 | 18 | Checklist: research report and user documentation completed | Met | report and four guides present |
