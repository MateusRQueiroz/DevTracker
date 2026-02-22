# DevTracker — Predictive Project Blueprint

DevTracker is an AI-powered project planning and effort estimation tool built for engineering teams who need honest answers before committing to a deadline. Submit a project's title, description, tech stack, and team composition and DevTracker returns a complete capacity analysis — including per-role hour breakdowns, a projected finish date, and an automatic "red zone" flag when the numbers don't add up.

Under the hood, Google Gemini evaluates each project across five complexity dimensions. Those scores feed a deterministic estimator that translates AI marks into concrete hours, compares them against your team's real working-day capacity, and surfaces exactly where the gaps are.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | Django 5.x |
| AI / LLM | Google Gemini (`gemini-2.5-flash` by default via `google-genai`) |
| Database | SQLite (default) — swappable via Django `DATABASES` |
| Frontend | Django templates + vanilla JS + CSS (no SPA framework) |
| Configuration | `python-dotenv` + `.env` file |
| Python | 3.10+ recommended |

---

## How It Works

### 1. Project Intake (`POST /api/intake/`)

A client submits a JSON payload containing the project title, description, tech stack array, deadline, and team roster (each member defined by role and seniority level).

### 2. Complexity Scoring via Gemini (`app/services/gemini.py`)

The intake handler calls `get_complexity_marks()`, which sends a structured prompt to Gemini and receives five integer scores on a 1–10 scale:

- **`complexity_score`** — overall project complexity
- **`estimated_features_count`** — implied feature breadth
- **`tech_difficulty`** — difficulty of the selected technologies
- **`integration_complexity`** — number and depth of integrations
- **`uncertainty_factor`** — ambiguity and risk in the requirements

If no API key is present or if Gemini is unreachable, a deterministic local heuristic (`_heuristic_marks`) takes over. It derives scores from text length, stack breadth, and keyword signals (e.g. `payments`, `websocket`, `kubernetes`) so the app remains fully functional offline.

### 3. Effort Estimation (`app/services/estimator.py`)

`run_estimation()` converts Gemini marks into hours using a formula *TODO* . An `adjusted_effort_score` (1–10 weighted average with an uncertainty uplift) provides a single headline risk number.

### 4. Role-Split Calculation

Gemini is queried a second time for a `FE / BE / DEVOPS` labor split (fractions summing to 1.0) informed by the tech stack and difficulty marks. A post-processing layer enforces realistic constraints — minimum FE allocation when a frontend framework is present, a baseline DevOps slice for any web app with build/deploy requirements, and hard caps to prevent lopsided splits. A deterministic fallback handles Gemini failures.

### 5. Capacity vs. Effort Analysis

Each developer's daily capacity is calculated as `6 hours × seniority multiplier` (Junior 0.8×, Mid 1.0×, Senior 1.2×) scaled by the working days remaining until the deadline (weekdays only). The role split is applied to total effort hours to produce per-role effort figures, which are then compared against per-role capacity. The delta drives the labor recommendation (`add N FTE` or `cut N FTE`) for each discipline.

### 6. Red Zone Detection

A project enters the red zone if any of the following conditions are true:

- The deadline has already passed
- Total capacity hours fall short of total effort hours
- Required roles inferred from the tech stack are not covered by the team
- The projected finish date exceeds the deadline

All triggered reasons are stored as a human-readable list on the project record.

### 7. Persistence & API

All project data, marks, and derived estimates are persisted to the database via Django ORM. The REST API supports full CRUD:

- `GET /api/project/<id>/` — fetch full project details and estimates
- `PUT/PATCH /api/project/<id>/` — update fields; re-runs Gemini and estimation automatically when title, description, or stack changes
- `DELETE /api/project/<id>/` — remove the project

### 8. Frontend

Three Django-template-rendered pages provide a browser UI:

- `/` — landing/home page
- `/dashboard/` — searchable list of all projects with red-zone indicators
- `/projects/<id>/` — detailed project view with role charts and team breakdown

---

## Directory Structure

```
DevTracker-main/
└── predictive_blueprint/         # Django project root
    ├── manage.py
    ├── requirements.txt
    ├── .env.example
    ├── config/                   # Django configuration
    │   ├── settings.py
    │   ├── urls.py               # Root URL dispatcher
    │   ├── wsgi.py
    │   └── asgi.py
    └── app/                      # Main application
        ├── models.py             # Project + Dev models
        ├── views.py              # API endpoints + page views
        ├── urls.py               # App-level URL patterns
        ├── services/
        │   ├── gemini.py         # Gemini complexity scoring + heuristic fallback
        │   └── estimator.py      # Effort computation, role splits, red-zone logic
        ├── templates/app/
        │   ├── base.html
        │   ├── index.html
        │   ├── dashboard.html
        │   ├── project_detail.html
        │   └── not_found.html
        ├── static/app/
        │   ├── app.js
        │   └── styles.css
        └── migrations/
            ├── 0001_initial.py
            └── 0002_complexity_v2_role_breakdown.py
```

---

## Dependencies

```
Django>=5.0,<6.0
python-dotenv>=1.0
google-genai>=0.5
```

Install with:

```bash
pip install -r predictive_blueprint/requirements.txt
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
GEMINI_API_KEY=YOUR_API_KEY_HERE
GEMINI_MODEL=gemini-2.5-flash
```

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Recommended | Google AI Studio API key. The app runs without it using the local heuristic fallback. |
| `GEMINI_MODEL` | Optional | Gemini model identifier. Defaults to `gemini-2.5-flash`. Accepts both `model-name` and `models/model-name` formats. |
| `DJANGO_SECRET_KEY` | Production | Django secret key. A dev-only insecure default is used if not set. Set this before any non-local deployment. |

---

## Setup & Running Locally

**1. Clone and navigate to the project**

```bash
git clone <repo-url>
cd DevTracker-main/predictive_blueprint
```

**2. Create and activate a virtual environment**

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows: .venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Configure environment**

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

**5. Run database migrations**

```bash
python manage.py migrate
```

**6. Start the development server**

```bash
python manage.py runserver
```

The app will be available at `http://127.0.0.1:8000`.

---

## API Quick Reference

### Create a Project

```http
POST /api/intake/
Content-Type: application/json

{
  "title": "E-Commerce Platform",
  "description": "Multi-tenant storefront with Stripe payments and real-time inventory.",
  "tech_stack": ["Django", "React", "AWS", "Docker"],
  "deadline": "2026-06-01",
  "team": [
    { "role": "BE", "seniority": "SENIOR" },
    { "role": "FE", "seniority": "MID" },
    { "role": "DEVOPS", "seniority": "MID" }
  ]
}
```

**Response**

```json
{
  "ok": true,
  "project_id": 1,
  "red_zone": false,
  "red_reasons": []
}
```

### Retrieve a Project

```http
GET /api/project/1/
```

### Update a Project

```http
PATCH /api/project/1/
Content-Type: application/json

{ "deadline": "2026-07-15" }
```

### Delete a Project

```http
DELETE /api/project/1/
```

---

### Team Role & Seniority Options

**Roles:** `FE` (Frontend), `BE` (Backend), `DEVOPS`

**Seniority levels:** `JUNIOR`, `MID`, `SENIOR`

---

## Notes

- The app defaults to SQLite. To use PostgreSQL or another database, update the `DATABASES` setting in `config/settings.py` accordingly.
- `DEBUG=True` is set by default. Disable this for any production or staging deployment and ensure `DJANGO_SECRET_KEY` is set to a strong random value.
- CSRF protection is currently disabled on the API endpoints via `@csrf_exempt`. For production use, implement token-based authentication and remove these decorators.
