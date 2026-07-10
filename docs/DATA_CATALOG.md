# California School-Level Data Catalog

Raw data pull for the California school improvement dashboard. This is the **raw
layer** — files are stored as originally published (tab-delimited `.txt`, `.csv`,
`.xlsx`, `.zip`), unmodified. Transformations/indicators come in a later step.

- **Pulled:** 2026-07-08
- **Coverage:** most recent 1–2 school years available per dataset (2022‑23 → 2024‑25)
- **Grain:** school level wherever the source publishes it (files also contain
  district / county / state aggregate rows — filter on `Aggregate Level`)
- **Root:** `California/raw/<domain>/`

---

## How this data was obtained (important for refreshing)

The California Dept. of Education sites (`www.cde.ca.gov`, `www3.cde.ca.gov`,
`www6.cde.ca.gov`) sit behind **Radware Bot Manager**, which serves a CAPTCHA to
any non-browser client (curl, scripts, this agent all get blocked). So the CDE
`.txt`/`.xlsx` data files **cannot be scripted directly** from cde.ca.gov.

Files here were sourced through channels that are *not* bot-blocked:

| Source | Used for | Method |
|---|---|---|
| **Wayback Machine** (`web.archive.org`) | All CDE `demo-downloads` files + ESSA finance + FRPM | CDX index → raw `…/<ts>id_/<url>` |
| **CA Open Data / ArcGIS Hub** (`data.ca.gov`, `gis.data.ca.gov`) | School & district directory + demographics | CKAN API + Hub download API |
| **ETS CAASPP portal** (`caaspp-elpac.ets.org`) | CAASPP ELA/Math results | Direct research-file ZIP download |

> ⚠️ **Wayback 5 MiB trap:** Wayback sometimes stores a *truncated 5,242,880‑byte*
> capture of large files. Several files were initially truncated and re‑pulled from
> the **largest available snapshot** (pick max `length` in CDX, not the newest). If
> you refresh, re-validate that no `.txt` is exactly 5,242,880 bytes and each ends
> in a newline.

To refresh with live (untruncated) data, download the CDE files in a **browser**
from the source pages listed in each section below.

---

## The linkage / join model (school ↔ district ↔ county)

Every CDE file carries the **CDS code** components; the directory files carry the
full 14-digit CDS plus names. Join on these:

```
CDS (14) = CountyCode(2) + DistrictCode(5) + SchoolCode(7)
```

| Field in directory CSV | Field in CDE demo-download files |
|---|---|
| `CDS Code` (14-digit) | (concatenate the three below) |
| `District Code` (7) `School Code` (7) | `DistrictCode`, `SchoolCode` |
| `County Name` / `District Name` / `School Name` | `CountyName` / `DistrictName` / `SchoolName` |

`Aggregate Level` in the CDE files = `S` (school), `D` (district), `C` (county),
`T`/`X` (state). Filter to `S` for school-level analysis.

---

## `directory/` — school & district lists, links (✔ complete, current)

Single richest reference layer. `schools_2025-26.csv` alone gives the school list,
the school→district→county links, geographic (residence) district assignments,
legislative districts, grade span, charter/Title I/DASS/ESSA-assistance flags, AND
enrollment demographics.

| File | Year | Rows | Source |
|---|---|---|---|
| `schools_2025-26.csv` | 2025‑26 | 9,946 schools | CDEGIS "California Public Schools 2025‑26" (ArcGIS Hub) |
| `public-schools_2024-25.csv` | 2024‑25 | ~10k | CDEGIS "California Public Schools 2024‑25" |
| `district_offices_2025-26.csv` | 2025‑26 | all LEAs | CDEGIS "California School District Offices 2025‑26" |
| `school-district-offices_2024-25.csv` | 2024‑25 | all LEAs | CDEGIS 2024‑25 |

Key columns: `CDS Code, District Code, School Code, County/District/School Name,
School Level, Grade Low/High, Charter, Title I, DASS, Assistance Status ESSA,
Enroll Total`, full race/ethnicity + EL/Foster/Homeless/Migrant/SED/SWD/FRPM
counts & %, per-grade enrollment, Latitude/Longitude, Geographic
{Elementary,High,Unified} District, US Congressional / CA Senate / CA Assembly district.

Live source (browser): CDE School Directory export — `cde.ca.gov/schooldirectory/report?rid=dl1&tp=txt`.

---

## `demographics/` — enrollment, poverty, subgroups (✔ complete)

| File | Year | Rows | What it is |
|---|---|---|---|
| `enrollment_censusday_2024-25.txt` | 2024‑25 | 269,158 | Census Day enrollment by school × grade × race/ethnicity × gender |
| `enrollment_censusday_2023-24.txt` | 2023‑24 | 267,762 | same |
| `frpm_2425.xlsx` | 2024‑25 | ~10k schools | Free/Reduced-Price Meal eligibility (poverty / SED) counts & % |
| `frpm_2324.xlsx` | 2023‑24 | ~10k schools | same |
| `homeless_2023-24.txt` | 2023‑24 | 150,810 | Homeless student enrollment by subgroup |
| `sped_primarydisability_2024-25.txt` | 2024‑25 | 117,334 | Special-ed enrollment by primary disability |
| `sped_primarydisability_2023-24.txt` | 2023‑24 | 115,423 | same |
| `mobility_stability_2023-24.txt` | 2023‑24 | 358,419 | Student stability / mobility rate |

Also note: rich demographics are already embedded in the `directory/` CSVs.
Live sources: `cde.ca.gov/ds/ad/` (Enrollment, FRPM, Homeless, SpEd, Stability file pages).

---

## `attendance/` — chronic absenteeism (✔ complete)

| File | Year | Rows | What it is |
|---|---|---|---|
| `chronicabsenteeism_2023-24.txt` | 2023‑24 | 343,602 | Chronic absenteeism eligible enrollment, count & rate, by school × subgroup |
| `chronicabsenteeism_2022-23.txt` | 2022‑23 | 343,652 | same |
| `absenteeismreason_2023-24.txt` | 2023‑24 | 375,754 | Absences by reason (excused/unexcused/suspension/etc.), by subgroup |
| `absenteeismreason_2022-23.txt` | 2022‑23 | 375,822 | same |

Chronic-absenteeism rate is a core CA Dashboard indicator.
Live source: `cde.ca.gov/ds/ad/filesabd.asp`, `…/filesabr.asp`.
(True daily ADA % is not in a statewide school file — derive from these or from P‑2 ADA reports.)

---

## `behavior/` — discipline (✔ 2022‑23 & 2023‑24; ⚠ 2024‑25 partial)

| File | Year | Rows | What it is |
|---|---|---|---|
| `suspension_2023-24.txt` | 2023‑24 | 225,157 | Suspension counts, unduplicated students, rate, by reason & subgroup |
| `expulsion_2023-24.txt` | 2023‑24 | 225,157 | Expulsion counts & rate by reason & subgroup |
| `expulsion_2022-23.txt` | 2022‑23 | 226,179 | same |

⚠️ **2024‑25 suspension** (`suspension25.txt`) exists but Wayback has **only a
truncated capture** (cut off inside the first county). Not included. Grab it from a
browser at `cde.ca.gov/ds/ad/filessd.asp` when you need the freshest year.
Live sources: `…/filessd.asp` (suspension), `…/filesed.asp` (expulsion).

---

## `academics/` — assessments & graduation (✔ complete; large files)

| File | Year | Size / Rows | What it is |
|---|---|---|---|
| `caaspp_smarterbalanced_all_2024-25.zip` | 2024‑25 | 157 MB zip → ~992 MB txt | **CAASPP** Smarter Balanced ELA + Math: every school × grade × subgroup, mean scale score, % at each achievement level, met-standard %. Includes `sb_ca2025entities` lookup inside. |
| `caaspp_smarterbalanced_all_2023-24.zip` | 2023‑24 | 157 MB zip | same |
| `caaspp_entities_2024-25.zip` / `_2023-24.zip` | — | small | County/district/school + test/subgroup code lookups (standalone) |
| `acgr_gradcohort_2024-25.txt` | 2024‑25 | 113,653 | Adjusted Cohort Graduation Rate + outcome breakdown (grad, dropout, GED, still enrolled) |
| `acgr_gradcohort_2023-24.txt` | 2023‑24 | 113,867 | same |
| `fosteryouth_gradcohort_2023-24.txt` | 2023‑24 | 113,977 | Foster-youth cohort graduation |
| `collegegoingrate_16mo_2021-22.txt` | 2021‑22 | 227,646 | College-Going Rate (16 months after HS), latest published |
| `teacherassignment_tamo_2022-23.txt` | 2022‑23 | 1,520,856 | **Teacher assignment (TAMO)** — clear/out-of-field/intern/ineffective FTE by subject (educator-equity, *not* test scores) |

CAASPP files are stored zipped (≈1 GB each unzipped). Layout = fixed CSV; the
`entities` file maps codes→names. Live source: `caaspp-elpac.ets.org` → Research Files.
**Not yet pulled (same method, easy adds):** ELPAC (English-learner proficiency /
ELPI indicator) and CAST (science) research files on the same ETS portal.

---

## `budgets/` — finance (✔ per-pupil + full SACS ledger)

| File | Year | Grain | What it is |
|---|---|---|---|
| `essa_perpupil_expenditure_2023-24.xlsx` | 2023‑24 | school + LEA | ESSA Per-Pupil Expenditure: total $ per pupil, split federal / state-local / excluded |
| `essa_perpupil_expenditure_2022-23.xlsx` | 2022‑23 | school + LEA | same (coarse — a per-pupil total by fund source, no category detail) |
| `sacs/sacs2324.mdb` | 2023‑24 | **LEA (+ partial school)** | **SACS unaudited actuals** — the full general ledger |
| `sacs/sacs2223.mdb` | 2022‑23 | LEA (+ partial school) | same |
| `sacs/charter2324/alt2324data.mdb` | 2023‑24 | charter LEA | Charter-school financials (reported separately from SACS) |

**SACS = the real depth.** Each `.mdb` (MS Access, ~460 MB) is CDE's Annual Financial
Data. The key table **`UserGL`** is every LEA's ledger row, keyed by
`Ccode·Dcode·SchoolCode · Fund · Resource · Goal · Function · Object`, with `Value` =
amount. Decode with the lookup tables in the same DB: **`Fund`, `Resource`, `Goal`,
`Function`, `Object`** (+ `LEAs`, `Charters`, `UserGL_Totals` = county/state totals).
This is expenditures-by-object (salaries/benefits/services/supplies/capital) and
by-function (instruction/pupil-services/admin/plant) — the Ed-Data depth, built from source.

- ⚠️ **Grain nuance:** `UserGL` *has* a `SchoolCode` field, so SACS is **not purely
  district-level** — but most LEAs book to the district (`SchoolCode = 0000000`) and only
  some code to specific schools, so school-level coverage is **partial and inconsistent**.
  Treat SACS as LEA-grain with opportunistic school detail.
- **Reading the `.mdb`:** no converter is installed here; the file is raw as CDE ships it.
  Export `UserGL` later with `mdb-tools` (`mdb-export sacs2324.mdb UserGL > usergl.csv`),
  Access/ODBC, or DuckDB's Access extension. Readme (schema) is the `.docx` beside each DB.
- **2024‑25 not included** — `sacs2425.exe` isn't archived in Wayback yet; grab from a
  browser at `cde.ca.gov/ds/fd/fd/` when needed.

Live sources: `cde.ca.gov/ds/fd/fd/` (Annual Financial Data — self-extracting `.exe`
on `www3.cde.ca.gov/fiscal-downloads/…`), SACS Data Viewer `cde.ca.gov/ds/fd/dv/`.
Also unpulled: **Current Expense per ADA** (`…/ds/fd/ec/`), **J-90 teacher salaries**
(`…/ds/fd/cs/`, readmes archived through 2024‑25), LCFF/Principal Apportionment.

---

## `staffing/` — staff headcount & FTE (✔ current headcount; ⚠ FTE historical)

| File | Year | Rows | What it is |
|---|---|---|---|
| `cbeds_staff_racegender_2023-24_a.txt` / `_b.txt` | 2023‑24 | 48k / 66k | **CBEDS ORA** — staff counts by school × staff type (`Description/Level/Section`) × race/ethnicity/gender. Current source for student/staff ratios. |
| `cbeds_staff_racegender_2022-23_a.txt` / `_b.txt` | 2022‑23 | 50k / 66k | same |
| `staff_school_fte_2017-18_HISTORICAL.txt` | 2017‑18 | 385k | `StaffSchoolFTE` — teacher/admin/pupil-services **FTE by school**. Last flat-file year. |
| `staff_demographics_2017-18_HISTORICAL.txt` | 2017‑18 | 365k | `StaffDemo` — staff demographics, education, years of experience. Last flat-file year. |

⚠️ **Staffing flat files stopped at 2017‑18.** CDE moved certificated-staff reporting
into CALPADS Fall 2; **2019‑20 → 2023‑24 staff FTE / experience / student-staff ratios
exist only interactively on DataQuest**, not as bulk files. So for a *current* FTE-ratio
metric, either derive it from the CBEDS staff counts above ÷ enrollment, or scrape
DataQuest. The teacher-quality angle (out-of-field/intern) is already covered by
`academics/teacherassignment_tamo_2022-23.txt`. Live source: `cde.ca.gov/ds/ad/staff.asp`.

---

## `climate/` — school climate (⚠ gated — see below)

**No file included.** California's school-climate survey data
(CalSCHLS / California Healthy Kids Survey, Staff Survey, Parent Survey) is **not
published as a bulk downloadable dataset**:

- **Raw student/staff/parent datasets** require a signed data-request application
  (confidentiality assurances) via CalSCHLS — `calschls.org/reports-data/`.
- **Aggregated results** are browsable but not bulk-downloadable via **Query CHKS**
  and the **CalSCHLS Data Dashboards**; district/county PDF reports since 2007 at
  `calschls.org/reports-data/search-lea-reports/`; some tables on `kidsdata.org`.
- On the state **Dashboard**, "School Climate" (Priority 6) is a **local indicator**
  (self-reported by LEAs) with no statewide data file.

**Practical proxy already in this pull:** suspension/expulsion + chronic
absenteeism are the state's quantitative climate/engagement measures.
**To get real climate data:** submit a CalSCHLS data request, or scrape Query CHKS.

---

## Known gaps & data that needs a browser (Radware-blocked)

| Want | Status | Where |
|---|---|---|
| CA School **Dashboard computed indicators** (color/status/change, all metrics in one file) | Not pulled — bot-blocked & not in Wayback | `cde.ca.gov/ta/ac/cm/` "Downloadable Data Files" (browser). We hold the raw inputs to compute these ourselves. |
| 2024‑25 **suspension** (full) | Wayback truncated | `cde.ca.gov/ds/ad/filessd.asp` (browser) |
| **ELPAC / CAST** research files | Not pulled (easy add) | `caaspp-elpac.ets.org` |
| **SACS / Current Expense** district finance | Not pulled | `cde.ca.gov/ds/fd/` (browser) |
| Live untruncated refresh of any CDE file | Use browser | source pages above |

---

## Suggested next steps toward indicators

1. Build a **school dimension** from `directory/schools_2025-26.csv` (CDS = grain).
2. Standardize each raw file: filter `Aggregate Level = S`, normalize the
   `ReportingCategory`/subgroup codes to a shared crosswalk, cast rates to numeric.
3. Join all domains on the 14-digit CDS + school year.
4. Recreate Dashboard-style indicators (status + change) for chronic absenteeism,
   suspension, ELA/Math (distance-from-standard via CAASPP), graduation, college/career.
5. Backfill the browser-only items above as needed.
