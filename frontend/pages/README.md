# 🖥️ **Frontend Pages — User-Facing Application Shell**

The **`frontend/pages`** folder contains all **Next.js route components** that make up the Alex AI Financial Advisor web experience.

These pages connect the authenticated user to the backend services, render portfolio data and analyses, and orchestrate navigation between the main product surfaces: dashboard, accounts, the AI advisory team, and completed analyses.

The pages layer is responsible for:

1. **Routing & Layout** – Defining URL structure and wiring each route into the shared `Layout` component.
2. **Auth-aware UX** – Using Clerk to handle signed-in vs signed-out states and protecting API calls with bearer tokens.
3. **Data Fetching & Presentation** – Calling backend APIs, shaping the response into UI-friendly structures, and rendering charts/tables/forms.
4. **User Actions & Flows** – Handling flows such as editing settings, adding/removing positions, and launching new AI analyses.

Below is a structured overview of the key page files and how they contribute to the system.

## 📁 **Folder Responsibilities**

The **`frontend/pages`** directory provides:

* All top-level **Next.js routes** for the application (`/`, `/dashboard`, `/advisor-team`, `/analysis`, `/accounts/...`).
* Auth-gated pages that call the backend with **Clerk-issued tokens**.
* High-level orchestration of multi-step flows (start analysis → monitor progress → view results).
* UI entry points for portfolio management (accounts, positions, cash balances).
* A consistent look and feel via the shared `Layout` component.

This folder is the main **presentation and navigation layer** of the app, sitting directly on top of the backend API.

## 🧠 **Files Overview**

### 🏠 `index.tsx` — **Marketing & Entry Landing Page**

* Public-facing landing page at `/`.
* Shows the value proposition (“AI-Powered Financial Future”) and explains the four AI agents.
* Uses **Clerk** components (`SignedIn`, `SignedOut`, `SignInButton`, `SignUpButton`, `UserButton`) to adapt the CTA:

  * Signed-out → “Sign In” / “Get Started”.
  * Signed-in → “Go to Dashboard”.
* Provides a “Watch Demo” button (placeholder) plus feature and benefits sections.
* Renders the footer disclaimer clarifying that advice is informational only.

**Primary role:** Onboard users into the product and funnel them into signup or the dashboard.

### 📊 `dashboard.tsx` — **Personal Financial Overview**

* Authenticated route that loads the current user’s data via **`/api/user`**.
* Fetches:

  * User profile and targets (display name, years to retirement, target income).
  * All accounts and their cash balances.
  * Positions + instruments per account to compute portfolio value and allocation.
* Computes:

  * Total portfolio value (cash + positions).
  * Asset-class breakdown (equity, fixed income, alternatives, cash).
* Renders:

  * Summary cards (portfolio value, number of accounts, last analysis, mini allocation pie).
  * A **“User Settings”** panel with:

    * Display name.
    * Years until retirement slider.
    * Target retirement income.
    * Target asset-class and regional allocations with live mini pie charts.
* Validates user inputs (percentages must sum to 100%, ranges must be sensible) before sending `PUT /api/user`.

**Primary role:** Provide a personalised control centre for user settings and high-level portfolio stats.

### 🤝 `advisor-team.tsx` — **AI Agents & Analysis Launcher**

* Authenticated page that introduces the four AI agents:

  * Financial Planner (orchestrator)
  * Portfolio Analyst
  * Chart Specialist
  * Retirement Planner
* Visual cards show each agent’s icon, role, and description, with **active state highlights** during analysis.
* “Start New Analysis” button:

  * Calls `POST /api/analyze` with `analysis_type: "portfolio"` and optional `options` (jurisdiction, scenarios, rebalancing).
  * Emits custom events (`analysis:started`, `analysis:completed`, `analysis:failed`) for other components (e.g. dashboard) to react.
  * Updates local **progress state** (`starting → planner → parallel → completing → complete/error`).
  * Polls `GET /api/jobs/{job_id}` every few seconds until the job completes or fails.
* Shows a **“Previous Analyses”** list from `GET /api/jobs` with status colouring and quick “View” buttons.

**Primary role:** Act as the “mission control” for launching and tracking AI-powered analyses.

### 📈 `analysis.tsx` — **Portfolio Report, Charts, and Retirement View**

* Authenticated route that displays the **results of a completed analysis job**.
* Can load:

  * A specific job via `?job_id=...`.
  * Or, if no `job_id` is provided, automatically fetches the latest completed job.
* Handles **job status**:

  * `running` / `pending` → shows in-progress messaging and refresh button.
  * `failed` → shows error details and CTA to retry via the Advisor Team.
* Renders a four-tab layout:

  1. **Overview**

     * Renders `report_payload.content` as Markdown using `react-markdown` with `remark-gfm` and `remark-breaks`.
     * Custom typography for headings, lists, tables, blockquotes.
  2. **Charts**

     * Reads `charts_payload` from the job.
     * Automatically infers chart type (`pie`, `donut`, `bar`, `horizontalBar`, `line`) based on the payload.
     * Uses **Recharts** (`PieChart`, `BarChart`, `LineChart`) to render interactive visualisations.
  3. **Retirement Projection**

      * Renders `retirement_payload.analysis` as Markdown inside a highlighted card.
  4. **Rebalancing**

     * Reads `summary_payload.rebalance` and renders suggested trades + drift vs target allocations.
* Includes a “New Analysis” button to jump back to `/advisor-team`.

**Primary role:** Present a rich, interactive result page combining narrative report, charts, and retirement insights from a single analysis run.

### 📂 `accounts/index.tsx` — **Accounts Overview (List Page)**

> Not shown in full above, but implied by `/accounts` navigation and detail page behaviour.

Typically responsible for:

* Listing all user accounts with name, purpose, balances, and quick actions.
* Linking each account to its corresponding detail route at `/accounts/[id]`.
* Serving as the entry point for account-level portfolio management.

**Primary role:** Provide a high-level overview of all investment accounts with navigation into each one.

### 💼 `accounts/[id].tsx` — **Account Detail & Position Management**

* Dynamic route that loads a single account by its `id` from `GET /api/accounts`.
* Fetches:

  * Positions for the account via `GET /api/accounts/{id}/positions`.
  * Instrument catalogue via `GET /api/instruments` for ticker autocomplete.
* Displays:

  * Account header (name, purpose) with inline editing for metadata + cash balance.
  * A summary row of key metrics: cash balance, positions value, total value, count of positions.
  * A detailed positions table (symbol, quantity, price, value).
* Supports actions:

  * **Edit position quantity** in-line with validation and `PUT /api/positions/{position_id}`.
  * **Delete position** with a confirmation modal and `DELETE /api/positions/{position_id}`.
  * **Add position** via a modal:

    * Ticker symbol input with autocomplete from known instruments.
    * Quantity input with validation.
    * Persists via `POST /api/positions`.

**Primary role:** Act as the main **portfolio editing surface** for a single account, with full CRUD support for positions.

## 🧭 **How These Pages Fit Into the Overall System**

The `frontend/pages` module ties together:

1. **Authentication (Clerk)** – Determines what each user can see and attaches tokens to every backend API call.
2. **Backend Services** – Jobs, accounts, positions, instruments, user profile, and AI analysis endpoints.
3. **Visual Components** – Layout, charts, markdown rendering, forms, toasts, and modals.

Together, they form a cohesive **web application shell** on top of the backend’s Reporter, Planner, Charter, Tagger, and Database subsystems, giving users a complete end-to-end experience from data entry to AI-powered financial insights.

## 🚀 **Summary**

The `frontend/pages` folder delivers:

* A clean **Next.js routing layer** for all user-facing screens.
* Auth-aware, token-secured access to backend APIs.
* Rich, interactive UIs for:

  * Portfolio overview and settings.
  * Account and position management.
  * Launching and viewing AI-driven analyses.

It is designed to keep routing and page-level logic **simple, cohesive, and closely aligned with the core financial flows** of the Alex AI platform.
