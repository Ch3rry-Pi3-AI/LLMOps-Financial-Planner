import { useUser, UserButton, Protect } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/router";
import { ReactNode } from "react";
import PageTransition from "./PageTransition";

/**
 * Props for the main authenticated layout component.
 *
 * @property {ReactNode} children
 * The page content to render inside the layout (below the navigation and above the footer).
 */
interface LayoutProps {
  children: ReactNode;
}

/**
 * Layout is the top-level shell for authenticated pages.
 *
 * Responsibilities:
 * - Wraps protected routes using Clerk's `Protect` component.
 * - Renders a responsive navigation bar with active-link highlighting.
 * - Shows the signed-in user's identity and a Clerk `UserButton` for account actions.
 * - Wraps page content with a `PageTransition` for smooth route transitions.
 * - Displays a persistent disclaimer footer reminding users this is not regulated advice.
 */
export default function Layout({ children }: LayoutProps) {
  const { user } = useUser();
  const router = useRouter();

  /**
   * Helper to determine whether a navigation link is currently active.
   *
   * @param {string} path - The target route path (e.g., "/dashboard").
   * @returns {boolean} True if the current route matches the given path.
   */
  const isActive = (path: string): boolean => router.pathname === path;

  return (
    <Protect
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="text-center">
            <p className="text-gray-600">Redirecting to sign in...</p>
          </div>
        </div>
      }
    >
      <div className="min-h-screen bg-gray-50 flex flex-col">
        {/* Top navigation bar */}
        <nav className="bg-white shadow-sm border-b">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between items-center h-16">
              {/* Logo / brand and primary navigation */}
              <div className="flex items-center gap-8">
                <Link href="/dashboard" className="flex items-center">
                  <h1 className="text-xl font-bold text-dark">
                    Alex{" "}
                    <span className="text-primary">
                      AI Financial Advisor
                    </span>
                  </h1>
                </Link>

                {/* Desktop navigation links */}
                <div className="hidden md:flex items-center gap-6">
                  <Link
                    href="/dashboard"
                    className={`text-sm font-medium transition-colors ${
                      isActive("/dashboard")
                        ? "text-primary"
                        : "text-gray-600 hover:text-primary"
                    }`}
                  >
                    Dashboard
                  </Link>
                  <Link
                    href="/accounts"
                    className={`text-sm font-medium transition-colors ${
                      isActive("/accounts")
                        ? "text-primary"
                        : "text-gray-600 hover:text-primary"
                    }`}
                  >
                    Accounts
                  </Link>
                  <Link
                    href="/advisor-team"
                    className={`text-sm font-medium transition-colors ${
                      isActive("/advisor-team")
                        ? "text-primary"
                        : "text-gray-600 hover:text-primary"
                    }`}
                  >
                    Advisor Team
                  </Link>
                  <Link
                    href="/analysis"
                    className={`text-sm font-medium transition-colors ${
                      isActive("/analysis")
                        ? "text-primary"
                        : "text-gray-600 hover:text-primary"
                    }`}
                  >
                    Analysis
                  </Link>
                </div>
              </div>

              {/* User identity and account dropdown (Clerk) */}
              <div className="flex items-center gap-4">
                <span className="hidden sm:inline text-sm text-gray-600">
                  {user?.firstName || user?.emailAddresses[0]?.emailAddress}
                </span>
                <UserButton afterSignOutUrl="/" />
              </div>
            </div>

            {/* Mobile navigation links (stacked under the main nav bar) */}
            <div className="md:hidden flex items-center gap-4 pb-3">
              <Link
                href="/dashboard"
                className={`text-sm font-medium transition-colors ${
                  isActive("/dashboard")
                    ? "text-primary"
                    : "text-gray-600 hover:text-primary"
                }`}
              >
                Dashboard
              </Link>
              <Link
                href="/accounts"
                className={`text-sm font-medium transition-colors ${
                  isActive("/accounts")
                    ? "text-primary"
                    : "text-gray-600 hover:text-primary"
                }`}
              >
                Accounts
              </Link>
              <Link
                href="/advisor-team"
                className={`text-sm font-medium transition-colors ${
                  isActive("/advisor-team")
                    ? "text-primary"
                    : "text-gray-600 hover:text-primary"
                }`}
              >
                Advisor Team
              </Link>
              <Link
                href="/analysis"
                className={`text-sm font-medium transition-colors ${
                  isActive("/analysis")
                    ? "text-primary"
                    : "text-gray-600 hover:text-primary"
                }`}
              >
                Analysis
              </Link>
            </div>
          </div>
        </nav>

        {/* Main page content with transition wrapper */}
        <main className="flex-1">
          <PageTransition>{children}</PageTransition>
        </main>

        {/* Persistent disclaimer footer */}
        <footer className="bg-white border-t mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-sm text-gray-700 font-medium mb-2">
                Important Disclaimer
              </p>
              <p className="text-xs text-gray-600">
                This AI-generated advice has not been vetted by a qualified
                financial advisor and should not be used for trading decisions.
                For informational purposes only. Always consult with a licensed
                financial professional before making investment decisions.
              </p>
            </div>
            <div className="mt-4 pt-4 border-t border-gray-200">
              <p className="text-xs text-gray-500 text-center">
                © 2025 Alex AI Financial Advisor. Powered by AI agents and built
                with care.
              </p>
            </div>
          </div>
        </footer>
      </div>
    </Protect>
  );
}
