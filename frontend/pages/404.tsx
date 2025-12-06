/**
 * -------------------------------------------------------------------------
 * Custom 404 Page
 *
 * This component renders whenever a user navigates to a route that does not
 * exist in the application. It provides a simple, branded error screen with
 * a clear call-to-action to return to the dashboard.
 *
 * Next.js automatically uses this file when named `404.tsx`.
 * -------------------------------------------------------------------------
 */

import Link from "next/link";
import Head from "next/head";

/**
 * Custom404
 *
 * Displays a user-friendly "Page Not Found" screen. Includes:
 *  - SEO-friendly <title>
 *  - Large status code branding
 *  - Minimal text explanation
 *  - A button redirecting the user back to the dashboard
 */
export default function Custom404() {
  return (
    <>
      <Head>
        {/* Set the page title for browsers and SEO tools */}
        <title>404 - Page Not Found | Alex AI Financial Advisor</title>
      </Head>

      {/* Full-screen centred layout */}
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="text-center">
          {/* Large 404 header */}
          <h1 className="text-6xl font-bold text-primary mb-4">404</h1>

          {/* Sub-header explanation */}
          <h2 className="text-2xl font-semibold text-dark mb-4">Page Not Found</h2>

          {/* Additional context */}
          <p className="text-gray-600 mb-8">
            The page you&apos;re looking for doesn&apos;t exist or has been moved.
          </p>

          {/* CTA button linking back to dashboard */}
          <Link href="/dashboard">
            <button className="bg-primary hover:bg-blue-600 text-white px-6 py-3 rounded-lg transition-colors">
              Return to Dashboard
            </button>
          </Link>
        </div>
      </div>
    </>
  );
}
