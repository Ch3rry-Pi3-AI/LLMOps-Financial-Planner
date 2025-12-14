/**
 * Home / Landing Page
 *
 * Public marketing front-door for the Alex AI Financial Advisor app.
 */

import {
  SignInButton,
  SignUpButton,
  SignedIn,
  SignedOut,
  UserButton,
} from "@clerk/nextjs";
import Link from "next/link";
import Head from "next/head";

export default function Home() {
  return (
    <>
      <Head>
        <title>Alex AI Financial Advisor</title>
      </Head>

      <div className="min-h-screen bg-background">
        {/* Top nav (public) */}
        <nav className="px-6 py-4 bg-surface border-b border-border">
          <div className="max-w-7xl mx-auto flex justify-between items-center">
            <div className="text-xl font-bold text-foreground tracking-tight">
              Alex <span className="text-primary">AI Financial Advisor</span>
            </div>

            <div className="flex items-center gap-3">
              <SignedOut>
                <SignInButton mode="modal">
                  <button className="px-4 py-2 rounded-lg border border-border bg-surface-2 text-foreground hover:bg-surface-2/80 transition-colors">
                    Sign In
                  </button>
                </SignInButton>
                <SignUpButton mode="modal">
                  <button className="px-4 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors">
                    Get Started
                  </button>
                </SignUpButton>
              </SignedOut>

              <SignedIn>
                <div className="flex items-center gap-3">
                  <Link href="/dashboard">
                    <button className="px-4 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors">
                      Go to Dashboard
                    </button>
                  </Link>
                  <UserButton afterSignOutUrl="/" />
                </div>
              </SignedIn>
            </div>
          </div>
        </nav>

        {/* Hero */}
        <section className="px-6 py-16">
          <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-12 items-center">
            <div>
              <h1 className="text-5xl font-bold text-foreground tracking-tight leading-tight">
                Your AI-powered financial command center.
              </h1>
              <p className="mt-6 text-lg text-muted max-w-xl">
                Specialized AI agents collaborate to analyze your portfolio,
                plan retirement scenarios, and generate clear reports with
                interactive charts.
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                <SignedOut>
                  <SignUpButton mode="modal">
                    <button className="px-6 py-3 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors shadow-lg">
                      Start Your Analysis
                    </button>
                  </SignUpButton>
                  <SignInButton mode="modal">
                    <button className="px-6 py-3 rounded-lg border border-border bg-surface text-foreground hover:bg-surface/80 transition-colors">
                      Sign In
                    </button>
                  </SignInButton>
                </SignedOut>

                <SignedIn>
                  <Link href="/dashboard">
                    <button className="px-6 py-3 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors shadow-lg">
                      Open Dashboard
                    </button>
                  </Link>
                </SignedIn>

                <button className="px-6 py-3 rounded-lg border border-border bg-surface-2 text-muted hover:text-foreground hover:bg-surface-2/80 transition-colors">
                  Watch Demo
                </button>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-2xl p-8 shadow-xl">
              <div className="grid grid-cols-2 gap-4">
                {[
                  {
                    icon: "🧠",
                    title: "Planner",
                    desc: "Orchestrates analysis end-to-end",
                  },
                  {
                    icon: "📝",
                    title: "Reporter",
                    desc: "Writes readable portfolio insights",
                  },
                  {
                    icon: "📊",
                    title: "Charter",
                    desc: "Builds interactive charts & breakdowns",
                  },
                  {
                    icon: "🧮",
                    title: "Retirement",
                    desc: "Runs projections and scenarios",
                  },
                ].map((item) => (
                  <div
                    key={item.title}
                    className="bg-surface-2 border border-border rounded-xl p-4"
                  >
                    <div className="text-2xl">{item.icon}</div>
                    <div className="mt-2 text-sm font-semibold text-foreground">
                      {item.title}
                    </div>
                    <div className="mt-1 text-xs text-muted">{item.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="px-6 py-8 border-t border-border bg-surface">
          <div className="max-w-7xl mx-auto text-center">
            <p className="text-sm text-muted">
              © 2025 Alex AI Financial Advisor. For informational purposes only.
            </p>
          </div>
        </footer>
      </div>
    </>
  );
}
