# ABC SIP Prototype

React + Vite prototype demonstrating where AI can improve K-12 ABC
(Attendance / Behavior / Course-performance) and School Improvement Plan
processes. **All data is fabricated.**

## Run locally

```
npm install
npm run dev
```

Then open the URL Vite prints (typically `http://localhost:5173`).

## Build

```
npm run build
```

Output is a fully static site in `dist/` — no server runtime, no env vars.

## Deploy to Cloudflare Pages

Two options:

**Option A · Connect the repo in the Cloudflare dashboard:**
- Framework preset: `Vite`
- Build command: `npm run build`
- Build output directory: `dist`

**Option B · Wrangler / CLI:**

```
npm install -g wrangler
npm run build
wrangler pages deploy dist --project-name=abc-sip-prototype
```

## Layout

- Slim header with title + "Prototype — no real data" disclaimer
- Vertical sidebar nav, grouped by area
- Each view component owns its own state, including a `Utilize SIS (True/False)` toggle where relevant

## View → Component map

| Sidebar item                  | Component                                  |
|-------------------------------|--------------------------------------------|
| Daily Attendance              | `views/CategorizeAttendance.jsx`           |
| Weekly Attendance (Tier 2)    | `views/AdditionalTiers.jsx`                |
| Behavior Review               | `views/Behavior.jsx`                       |
| ABC Clusters (VAE) Screening  | `views/ABCScreening.jsx`                   |
| School Improvement Plans      | `views/SchoolImprovementPlan.jsx`          |
| Upload Data                   | `views/UploadData.jsx`                     |

## Notes

- Charts: `recharts`. Heatmap is hand-rolled CSS grid for crispness.
- All mock data lives in `src/data/mockData.js`.
- No backend — pure SPA, safe for Pages with no build-time secrets.
