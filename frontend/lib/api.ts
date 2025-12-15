/**
 * API client for backend communication.
 *
 * This module centralises all HTTP calls to the backend API and exposes
 * a typed client grouped by resource (user, accounts, positions, analysis, jobs).
 */

import { showToast } from "../components/Toast";
import { API_URL } from "./config";

/**
 * Base URL for all API requests.
 *
 * In production, this should point to the deployed API Gateway / backend URL
 * via the `NEXT_PUBLIC_API_URL` environment variable.
 * Falls back to a local development server if not set.
 */
const API_BASE_URL = API_URL;

/**
 * Representation of a user in the Alex AI system.
 */
export interface User {
  /** Clerk user identifier */
  clerk_user_id: string;
  /** Display name used in the UI */
  display_name: string;
  /** Years remaining until the user's target retirement date */
  years_until_retirement: number;
  /** Target annual income in retirement (typically real terms) */
  target_retirement_income: number;
  /** Target asset class allocation (e.g. equities, bonds, cash) as percentages or weights */
  asset_class_targets: Record<string, number>;
  /** Target regional allocation (e.g. US, UK, Europe) as percentages or weights */
  region_targets: Record<string, number>;
}

/**
 * Representation of an investment account.
 */
export interface Account {
  /** Unique account identifier */
  id: string;
  /** Clerk user identifier that owns the account */
  clerk_user_id: string;
  /** Human-readable account name (e.g. "ISA", "SIPP", "Taxable") */
  name: string;
  /** Account type/category (e.g. "pension", "isa", "taxable") */
  account_type: string;
  /** Optional account purpose description (e.g. "Retirement", "House deposit") */
  purpose?: string;
  /** Cash balance available in this account (in base currency) */
  cash_balance: number;
}

/**
 * Representation of a single position (holding) within an account.
 */
export interface Position {
  /** Unique position identifier */
  id: string;
  /** ID of the account that owns this position */
  account_id: string;
  /** Ticker or instrument symbol (e.g. "VWRL", "AGGH") */
  symbol: string;
  /** Quantity of units/shares held */
  quantity: number;
}

/**
 * Representation of a backend "job" (e.g. analysis run).
 */
export interface Job {
  /** Unique job identifier */
  id: string;
  /** Clerk user identifier that owns the job */
  clerk_user_id: string;
  /** Type of job (e.g. "analysis", "retirement", "report") */
  job_type: string;
  /** Current job status (e.g. "pending", "running", "completed", "failed") */
  status: string;
  /** Optional structured result payload returned by the backend */
  result?: Record<string, unknown>;
  /** Optional error message if the job failed */
  error?: string;
}

/**
 * Error payload returned by the backend for failed requests.
 */
export interface ApiError {
  /** Human-readable error detail */
  detail: string;
}

/**
 * Make an authenticated API request using a bearer token.
 *
 * This helper:
 * - Automatically attaches JSON headers and the `Authorization` header.
 * - Handles common error cases:
 *   - 401 → shows a session-expired toast and redirects to `/`.
 *   - 429 → shows a rate-limit toast.
 * - Throws an Error if the response is not OK.
 *
 * @template T - Expected JSON response type.
 * @param endpoint - API endpoint URL path (e.g. `/api/user`).
 * @param token - Bearer token for authentication.
 * @param options - Optional `fetch` options (method, body, headers, etc.).
 * @returns Parsed JSON response typed as `T`.
 * @throws Error when request fails or response is not OK.
 */
export async function apiRequest<T = unknown>(
  endpoint: string,
  token: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });

  // Handle JWT expiry (401 Unauthorized)
  if (response.status === 401) {
    showToast("error", "Session expired. Please sign in again.");

    // Redirect to home page for re-authentication
    setTimeout(() => {
      window.location.href = "/";
    }, 2000);

    throw new Error("Session expired");
  }

  // Handle rate limiting (429 Too Many Requests)
  if (response.status === 429) {
    showToast("error", "Too many requests. Please slow down.");
    throw new Error("Rate limited");
  }

  // Generic non-OK response handling
  if (!response.ok) {
    const error: ApiError = await response
      .json()
      .catch(() => ({ detail: "Request failed" } as ApiError));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  // Successful case: parse and return JSON payload
  return response.json();
}

/**
 * Factory that creates a typed API client bound to a specific token.
 *
 * Usage:
 * ```ts
 * const client = createApiClient(token);
 * const user = await client.user.get();
 * const accounts = await client.accounts.list();
 * ```
 *
 * The returned object is grouped by domain:
 * - `user`
 * - `accounts`
 * - `positions`
 * - `analysis`
 * - `jobs`
 *
 * @param token - Bearer token to attach to every request.
 * @returns An object exposing typed methods for each resource.
 */
export function createApiClient(token: string) {
  return {
    // User endpoints
    user: {
      /** Retrieve the current user's profile and targets */
      get: () => apiRequest<User>("/api/user", token),

      /**
       * Update user profile / target values.
       *
       * Only fields present in `data` will be updated.
       */
      update: (data: Partial<User>) =>
        apiRequest<User>("/api/user", token, {
          method: "PUT",
          body: JSON.stringify(data),
        }),
    },

    // Account endpoints
    accounts: {
      /** List all accounts for the current user */
      list: () => apiRequest<Account[]>("/api/accounts", token),

      /** Create a new account for the current user */
      create: (data: Partial<Account>) =>
        apiRequest<Account>("/api/accounts", token, {
          method: "POST",
          body: JSON.stringify(data),
        }),

      /** Update an existing account by ID */
      update: (id: string, data: Partial<Account>) =>
        apiRequest<Account>(`/api/accounts/${id}`, token, {
          method: "PUT",
          body: JSON.stringify(data),
        }),

      /** List positions (holdings) for a given account */
      positions: (id: string) =>
        apiRequest<Position[]>(`/api/accounts/${id}/positions`, token),
    },

    // Position endpoints
    positions: {
      /** Create a new position (holding) */
      create: (data: Partial<Position>) =>
        apiRequest<Position>("/api/positions", token, {
          method: "POST",
          body: JSON.stringify(data),
        }),

      /** Update an existing position by ID */
      update: (id: string, data: Partial<Position>) =>
        apiRequest<Position>(`/api/positions/${id}`, token, {
          method: "PUT",
          body: JSON.stringify(data),
        }),

      /** Delete a position by ID */
      delete: (id: string) =>
        apiRequest<void>(`/api/positions/${id}`, token, {
          method: "DELETE",
        }),
    },

    // Analysis endpoints
    analysis: {
      /**
       * Trigger a new analysis job for the current user.
       *
       * Optional `data` can be used to pass scenario-specific parameters.
       */
      trigger: (data: Record<string, unknown> = {}) =>
        apiRequest<Job>("/api/analyze", token, {
          method: "POST",
          body: JSON.stringify(data),
        }),
    },

    // Job endpoints
    jobs: {
      /** Get a single job by ID */
      get: (id: string) => apiRequest<Job>(`/api/jobs/${id}`, token),

      /** List all jobs for the current user */
      list: () => apiRequest<Job[]>("/api/jobs", token),
    },
  };
}

/**
 * Convenience hook for creating an API client inside React components.
 *
 * This hook does not access auth directly; it simply returns a small
 * wrapper around `createApiClient`. In a typical pattern you might use:
 *
 * ```ts
 * const { getToken } = useAuth();
 * const { createClient } = useApiClient();
 *
 * const token = await getToken();
 * const api = createClient(token);
 * const user = await api.user.get();
 * ```
 *
 * @returns An object exposing `createClient(token)` helper.
 */
export function useApiClient() {
  // This hook can be used in components together with Clerk's useAuth()
  return {
    createClient: (token: string) => createApiClient(token),
  };
}
