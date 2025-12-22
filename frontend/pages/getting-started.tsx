import Head from "next/head";
import Layout from "../components/Layout";

export default function GettingStarted() {
  return (
    <>
      <Head>
        <title>Getting Started - Alex AI Financial Advisor</title>
      </Head>
      <Layout>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="bg-surface border border-border rounded-lg shadow p-6">
            <h2 className="text-3xl font-bold text-foreground">Getting Started</h2>
            <p className="text-muted mt-2">
              A quick guide to setting up your accounts and running your first portfolio
              analysis.
            </p>

            <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-6">
              <section className="bg-surface-2 border border-border rounded-lg p-5">
                <h3 className="text-xl font-semibold text-foreground">
                  1) Add Your Accounts
                </h3>
                <ul className="mt-3 text-sm text-muted space-y-2 list-disc list-inside">
                  <li>
                    Go to <span className="font-mono">Accounts</span>.
                  </li>
                  <li>
                    Use <span className="font-mono">Add Account</span> to create an ISA/SIPP/GIA
                    (or any custom account).
                  </li>
                  <li>
                    Add positions manually, or use <span className="font-mono">Import CSV</span>.
                  </li>
                </ul>
                <div className="mt-4 text-sm text-muted">
                  Tip: for UK tickers, prefer an exchange suffix when possible (e.g.{" "}
                  <span className="font-mono">VUAG.L</span>) to reduce ambiguity.
                </div>
              </section>

              <section className="bg-surface-2 border border-border rounded-lg p-5">
                <h3 className="text-xl font-semibold text-foreground">
                  2) Import Holdings via CSV (Optional)
                </h3>
                <ul className="mt-3 text-sm text-muted space-y-2 list-disc list-inside">
                  <li>
                    In <span className="font-mono">Accounts</span>, click{" "}
                    <span className="font-mono">Import CSV</span>.
                  </li>
                  <li>
                    Download the template and fill one row per holding (instrument) per account.
                  </li>
                  <li>
                    Upload the CSV and confirm the preview before importing.
                  </li>
                </ul>
                <div className="mt-4 text-xs text-muted-2">
                  The template supports both tickers and ISINs. ISINs are the most stable
                  identifier for UK/EU instruments; tickers can differ by data vendor.
                </div>
              </section>

              <section className="bg-surface-2 border border-border rounded-lg p-5">
                <h3 className="text-xl font-semibold text-foreground">
                  3) Run An Analysis
                </h3>
                <ul className="mt-3 text-sm text-muted space-y-2 list-disc list-inside">
                  <li>
                    Go to <span className="font-mono">Analysis</span> and start a{" "}
                    <span className="font-mono">New Analysis</span>.
                  </li>
                  <li>
                    The system prices instruments and generates a report across multiple tabs.
                  </li>
                  <li>
                    Use <span className="font-mono">Export Tab PDF</span> to print/save a PDF via
                    your browser.
                  </li>
                </ul>
              </section>

              <section className="bg-surface-2 border border-border rounded-lg p-5">
                <h3 className="text-xl font-semibold text-foreground">
                  4) Explore Trends and Market Data
                </h3>
                <ul className="mt-3 text-sm text-muted space-y-2 list-disc list-inside">
                  <li>
                    <span className="font-mono">History</span> shows previous runs and changes over
                    time.
                  </li>
                  <li>
                    <span className="font-mono">Market</span> shows instrument price performance
                    (powered by Polygon, coverage depends on plan).
                  </li>
                </ul>
              </section>
            </div>

            <section className="mt-8 bg-surface-2 border border-border rounded-lg p-5">
              <h3 className="text-xl font-semibold text-foreground">Notes & Limitations</h3>
              <ul className="mt-3 text-sm text-muted space-y-2 list-disc list-inside">
                <li>
                  Some instruments may have missing or stale prices; the app surfaces data quality
                  indicators when defaults/heuristics are used.
                </li>
                <li>
                  Market coverage is best for US equities; UK/EU instruments may require exchange
                  suffixes or ISIN-based mapping.
                </li>
                <li>
                  This app provides educational analysis and workflow tooling, not regulated
                  financial advice.
                </li>
              </ul>
            </section>
          </div>
        </div>
      </Layout>
    </>
  );
}

