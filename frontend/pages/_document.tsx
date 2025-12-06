/**
 * -------------------------------------------------------------------------
 * Custom Next.js Document
 *
 * This file allows control over the overall HTML structure of the application.
 * It runs only on the server and is used for:
 *   - Injecting metadata into the <html> and <head> tags
 *   - Adding global attributes (e.g., lang="en")
 *   - Registering favicons, manifests, and theme configuration
 *
 * Unlike `_app.tsx`, this file does NOT handle application-level React state.
 * It strictly shapes the final HTML document that wraps all pages.
 * -------------------------------------------------------------------------
 */

import { Html, Head, Main, NextScript } from "next/document";

/**
 * Document
 *
 * Custom Document component that defines the HTML template for all pages.
 * This is rendered on the server and does not rerender on the client.
 */
export default function Document() {
  return (
    <Html lang="en">
      <Head>
        {/* Standard favicon */}
        <link rel="icon" href="/favicon.ico" />

        {/* SVG icon fallback */}
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />

        {/* Apple icon for iOS home-screen shortcuts */}
        <link rel="apple-touch-icon" href="/favicon.ico" />

        {/* PWA manifest configuration */}
        <link rel="manifest" href="/manifest.json" />

        {/* SEO + App metadata */}
        <meta
          name="description"
          content="Alex AI Financial Advisor - Your intelligent portfolio management assistant"
        />

        {/* Browser theme colour for mobile UI chrome */}
        <meta name="theme-color" content="#209DD7" />
      </Head>

      {/* Global body settings */}
      <body className="antialiased">
        {/* Main application content */}
        <Main />

        {/* Next.js runtime + scripts */}
        <NextScript />
      </body>
    </Html>
  );
}
