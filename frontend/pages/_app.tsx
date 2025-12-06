/**
 * -------------------------------------------------------------------------
 * Custom Next.js App Component
 *
 * This file overrides Next.js' default App component. It is used to:
 * 1. Initialise global providers (e.g., Clerk, global styles).
 * 2. Wrap every page in shared layout components.
 * 3. Register global UI elements such as the Toast system.
 * 4. Provide a top-level error boundary to catch unexpected runtime errors.
 *
 * Anything placed here will be included on *every page* of the application.
 * -------------------------------------------------------------------------
 */

import "@/styles/globals.css";                  // Global CSS applied across the entire app
import type { AppProps } from "next/app";
import { ClerkProvider } from "@clerk/nextjs";  // Authentication/identity provider for all pages
import { ToastContainer } from "@/components/Toast"; // Global toast/notification system
import ErrorBoundary from "@/components/ErrorBoundary"; // Catches unhandled rendering errors

/**
 * App
 *
 * The root React component for all pages. Next.js automatically injects the
 * correct `Component` and `pageProps` during routing.
 *
 * @param Component - The page component being rendered
 * @param pageProps - Props passed to the page by Next.js (incl. server-side props)
 */
export default function App({ Component, pageProps }: AppProps) {
  return (
    // Wrap everything in an error boundary so unexpected failures are captured
    <ErrorBoundary>
      {/* Provides user authentication/session context to the entire application */}
      <ClerkProvider {...pageProps}>
        {/* Render the active page */}
        <Component {...pageProps} />

        {/* Global toast notifications (accessible anywhere in the app) */}
        <ToastContainer />
      </ClerkProvider>
    </ErrorBoundary>
  );
}
