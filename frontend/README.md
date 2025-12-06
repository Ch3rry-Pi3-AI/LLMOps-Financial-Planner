# 🎨 **Frontend Module — User Interface for the Alex AI Financial Advisor**

The **`frontend/`** folder contains the complete **Next.js + TypeScript web application** that powers the user-facing experience of the Alex AI Financial Advisor platform.

This module is responsible for rendering authenticated dashboards, orchestrating financial analysis flows, managing user interactions, and presenting results returned by the backend LLM services.
It forms the presentation layer of the system, sitting directly above backend APIs and integrating deeply with Clerk authentication.

The frontend is built on:

* **Next.js 14 (App Router off / Pages Router enabled)**
* **TypeScript** for strict, predictable typing
* **TailwindCSS** with custom theming
* **Clerk** for authentication and session security

Together, these technologies provide a **fast, responsive, enterprise-grade UX** optimised for clarity, reliability, and professional financial workflows.

The frontend module performs four core responsibilities:

1. Rendering authenticated UI surfaces (dashboard, accounts, advisor team, analysis pages)
2. Connecting to backend LLM agents and REST endpoints through typed API helpers
3. Managing global UI structure and interaction components (toasts, modals, loaders)
4. Applying consistent styling and themes across the entire experience

Below is a structured overview of the purpose of this folder and how each of its submodules contributes to the system.

## 📁 **Folder Responsibilities**

The **frontend/** directory provides:

* The full Next.js web client for authenticated users
* A modular UI system built from reusable React components
* A typed frontend logic layer (`lib/`) for backend communication and configuration
* Route-level pages that orchestrate application flows and display analysis results
* A global CSS theme defining colours, fonts, tokens, and Light-mode-only styling
* Public assets required by the UI (icons, images, static files)
* Project-level configuration files (Next.js config, TypeScript config, ESLint, PostCSS)

This folder represents the complete **presentation and interaction layer** of the Alex AI Financial Advisor, delivering a high-quality, consistent user experience backed by modern UI engineering practices.

## 🧭 **Submodules Overview**

### 📄 `pages/` — User-Facing Application Shell

Houses all **Next.js route components** and orchestrates navigation, data fetching, and API interaction for user flows such as portfolio management, advisor team workflows, and analysis result views.

Key responsibilities include routing, auth gating, data presentation, and UX orchestration.

### 🎛️ `components/` — Reusable UI Building Blocks

Contains all **shared React components**, including layout wrappers, modals, error boundaries, loaders, and notification systems.

Provides the global structure and interaction patterns used across the entire app.

### 🧩 `lib/` — Core Client-Side Logic Utilities

Implements typed API clients, runtime configuration, and event signalling mechanisms that support consistent communication with backend services.

Acts as the operational backbone of the frontend.

### 🎨 `styles/` — Global CSS & Theming

Defines global CSS tokens, Tailwind configuration, and the application's customised colour scheme.

Provides a unified visual language across all pages and components.

### 🌐 `public/` — Static Assets

Stores static images, icons, and metadata used by the frontend.

Files here are served directly by the Next.js static asset pipeline.

### 🧰 Root-Level Config Files

Includes:

* `next.config.ts` — Next.js configuration
* `tsconfig.json` — TypeScript compiler configuration
* `eslint.config.mjs` — Linting rules
* `postcss.config.mjs` — CSS/Tailwind build configuration
* `package.json` — Frontend dependencies and scripts

Together, these ensure the project builds consistently and conforms to modern TypeScript + Next.js standards.

## 🚀 **How This Module Fits Into the Overall System**

The frontend is the **gateway through which all users interact with the platform**.

It consumes results produced by backend compute modules:

1. **Planner** → Financial projections and risk evaluation
2. **Reporter** → Narrative explanations
3. **Charter** → Chart specifications and visualisation data

The frontend assembles these into a cohesive, seamless interface that empowers users to understand their portfolios, receive AI-supported insights, and manage their financial goals.

## ✨ **Summary**

The `frontend/` folder delivers:

* A **fully authenticated**, production-grade Next.js client
* A modular architecture separating UI, logic, and routes
* Clean integration with backend LLM agents through typed clients
* A polished, consistent UI defined by reusable design patterns and global theming

This module forms the **public face** of the Alex AI Financial Advisor system and provides a fast, secure, and intuitive experience for end users.