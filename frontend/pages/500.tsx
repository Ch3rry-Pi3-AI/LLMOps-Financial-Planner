/**
 * -------------------------------------------------------------------------
 * Custom 500 Page
 *
 * This component renders when an unexpected server-side error occurs
 * that prevents the page from loading. It provides a branded, user-friendly
 * fallback screen that reassures the user and offers a path back into the app.
 *
 * Next.js automatically uses this file when named `500.tsx`.
 * -------------------------------------------------------------------------
 */

import Link from "next/link";
import Head from "next/head";

/**
 * Custom500
 *
 * Displays a generic “Internal Server Error” page. Includes:
 *  - SEO-aware <title>
 *  - Prominent status code (500)
 *  - Clear explanation that the issue is on the server
 *  - Button allowing the user to return to the dashboard safely
 */
export default function Custom500() {
  return (
    <>
      <Head>
        {/* Provide a meaningful page title for browsers and SEO */}
        <title>500 - Server Error | Alex AI Financial Advisor</title>
      </Head>

      {/* Full-screen centred layout with neutral background */}
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="text-center">
          {/* Main error code in brand-coloured red */}
          <h1 className="text-6xl font-bold text-red-500 mb-4">500</h1>

          {/* Human-readable explanation of the issue */}
          <h2 className="text-2xl font-semibold text-dark mb-4">
            Internal Server Error
          </h2>

          {/* Brief message encouraging the user to retry later */}
          <p className="text-gray-600 mb-8">
            Something went wrong on our end. Please try again later.
          </p>

          {/* CTA button linking users back to the dashboard */}
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
