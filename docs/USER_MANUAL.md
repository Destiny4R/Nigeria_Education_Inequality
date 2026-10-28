# User manual

Open the site; no sign-in is needed. The menu leads to the pages below.

| Page | Use it to |
|---|---|
| **Home / Methodology** (`/`, `/methodology/`) | Read the five research questions, indicator definitions, the causal approach and what the data cannot show |
| **Dashboard** (`/dashboard/`) | See national indicators, a state map, trend lines and the latest analysis runs |
| **Data** (`/data/`, `/data/dictionary/`) | Inspect sources, licences, dataset versions, checksums, readiness status, data-quality reports and the data dictionary; download cleaned CSV files |
| **Inequality** (`/inequality/`) | Rank states, compare North and South, zones and poverty groups, see gender gaps, Lorenz curve, teacher-resource inequality and national rural-urban and wealth gaps. Filters: region, zone, poverty group, states. Export CSV, Excel, PDF or JSON |
| **Causal analysis** (`/causal/`) | Read the causal graph, assumptions, four estimators, overlap and balance, robustness and sensitivity checks and the plain-language verdict. Submit a custom specification (treatment, outcome, confounders, estimator settings) |
| **Policy simulation** (`/simulate/`) | Build a scenario (e.g. cap pupils per qualified teacher at 35, or cut it by 20% in the North), choose coverage and implementation range, run it, save it, and compare scenarios on a common baseline at `/simulate/compare/` |
| **Reports** (`/reports/`) | Download PDF, Excel and JSON for any run, the summary PDF, and the research report. Every export quotes run id, configuration hash, data fingerprint and software versions |
| **Activity / Status** | Audit log of actions (no personal data) and system configuration |

## Reading results correctly
* The out-of-school figures are survey estimates for the state; the study is **ecological**: it says nothing about individual children or households.
* A causal result marked *Inconclusive* means the data cannot distinguish a real effect from none. It is not evidence of no effect.
* Simulation results are **hypothetical**. They apply the estimated effect, with its uncertainty, to the baseline; they are not forecasts, and scenarios are never ranked by cost because no cost data exist.
* Warnings on a page (small sample, extrapolation, excluded states, data flags) are part of the result. States with data-integrity flags are shown with the flag next to their rank.
