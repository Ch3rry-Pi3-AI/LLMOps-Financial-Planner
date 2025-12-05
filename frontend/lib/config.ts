/**
 * API configuration utility for determining the correct backend URL
 * in both development and production environments.
 *
 * This file exists because:
 * - In **local development**, the frontend talks directly to `localhost:8000`.
 * - In **production**, the frontend is served behind CloudFront, and the path
 *   `/api/*` is routed by CloudFront → API Gateway → Lambda backend.
 *
 * Therefore:
 * - **Production uses a relative path ("")**, ensuring all requests begin with `/api/...`
 *   and are automatically forwarded by CloudFront.
 * - **Client-side development** uses an absolute URL (`http://localhost:8000`).
 *
 * This logic must be client-safe and SSR-safe.
 */

/**
 * Determines the base API URL depending on environment and execution context.
 *
 * Behaviour:
 * - On the **client**, if the hostname is `localhost`, return the local backend URL.
 * - On the **client**, in production, return an empty string `""`,
 *   meaning all fetch calls use relative paths (e.g. `/api/user`).
 * - On the **server** (Next.js build or prerendering), always return `""`,
 *   because the server does not need to make direct API calls using absolute URLs.
 *
 * @returns {string} The base API URL (`""` for production or `http://localhost:8000` for dev).
 */
export const getApiUrl = (): string => {
  // Running in the browser
  if (typeof window !== "undefined") {
    // Local development environment
    if (window.location.hostname === "localhost") {
      return "http://localhost:8000";
    }

    // Production environment
    // Use relative paths so CloudFront can route /api/* → API Gateway
    return "";
  }

  // Server-side execution (Next.js build / SSR)
  // Always use relative path; absolute paths are not required.
  return "";
};

/**
 * Default export used by API clients.
 *
 * This value is evaluated at import time and is safe for both SSR and client-side usage.
 */
export const API_URL = getApiUrl();
