/**
 * Dashboard Page
 *
 * This is the main landing page for logged-in users. It:
 *  - Syncs/creates the user in the backend via `/api/user`
 *  - Loads accounts, positions, and instrument metadata
 *  - Computes a portfolio-level asset allocation summary
 *  - Lets the user store retirement preferences and allocation targets
 *  - Reacts to "analysis completed" events to refresh portfolio data
 */

import { useUser, useAuth } from "@clerk/nextjs";
import { useEffect, useState, useCallback } from "react";
import Head from "next/head";
import Layout from "../components/Layout";
import { apiRequest } from "../lib/api";
import {
  normaliseInstrumentFromBackend,
  type NormalizedInstrument,
} from "../lib/normalizers";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { showToast } from "../components/Toast";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  Legend,
} from "recharts";

/**
 * UserData
 *
 * Shape of the user profile as stored in the backend:
 *  - Clerk user ID
 *  - Basic display details
 *  - Retirement horizon and income target
 *  - Target allocations by asset class and region
 */
interface UserData {
  clerk_user_id: string;
  display_name?: string;
  years_until_retirement?: number;
  target_retirement_income?: number | string;
  asset_class_targets?: Record<string, number>;
  region_targets?: Record<string, number>;
  user_preferences?: Record<string, unknown>;
}

/**
 * Account
 *
 * High-level representation of an investment account:
 *  - ID and user linkage
 *  - Human-friendly name and purpose
 *  - Cash balance (in base currency)
 */
interface Account {
  id: string;
  clerk_user_id: string;
  account_name: string;
  account_purpose?: string;
  cash_balance?: number;
}

/**
 * Position
 *
 * Representation of a holding within an account:
 *  - ID and account linkage
 *  - Symbol and quantity
 *  - Optional instrument metadata (pricing + allocations)
 */
interface Position {
  id: string;
  account_id: string;
  symbol: string;
  quantity: number;
  instrument?: Instrument | null;
}

type Instrument = NormalizedInstrument;

/**
 * Job
 *
 * Minimal job shape used for extracting the last completed analysis time.
 */
interface Job {
  status?: string;
  completed_at?: string;
}

/**
 * Colour palette used for pie charts.
 */
const COLORS = [
  "#209DD7",
  "#FFB707",
  "#753991",
  "#10b981",
  "#ef4444",
  "#6366f1",
];

/**
 * Format numeric values as GBP currency.
 */
const formatCurrency = (value: number): string =>
  new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);

/**
 * Convert keys like "fixed_income" or "cash" into "Fixed Income" / "Cash".
 */
const formatAssetClassName = (name: string): string =>
  name
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

/**
 * Props Recharts passes into the custom Pie label renderer.
 */
type AssetPieLabelProps = {
  name?: string | number;
  value?: number | string;
  percent?: number;
};

/**
 * Dashboard
 *
 * Main component responsible for:
 *  - Fetching and syncing user + portfolio data
 *  - Calculating aggregate portfolio metrics
 *  - Displaying allocation charts and retirement targets
 *  - Reacting to analysis completion events
 */
export default function Dashboard() {
  /**
   * Authentication / user context
   */
  const { user, isLoaded: userLoaded } = useUser();
  const { getToken } = useAuth();

  /**
   * Local state for:
   *  - accounts: list of accounts
   *  - positions: positions grouped by account
   *  - instruments: instrument metadata keyed by symbol
   *  - loading / error flags
   *  - derived portfolio summary
   *  - user-editable retirement + allocation targets
   *  - lastAnalysisDate: most recent completed analysis job
   */
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [positions, setPositions] = useState<Record<string, Position[]>>({});
  const [instruments, setInstruments] = useState<Record<string, Instrument>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [totalPortfolioValue, setTotalPortfolioValue] = useState(0);
  const [assetAllocationData, setAssetAllocationData] = useState<
    { name: string; value: number }[]
  >([]);

  const [displayName, setDisplayName] = useState("");
  const [yearsUntilRetirement, setYearsUntilRetirement] = useState(0);
  const [targetRetirementIncome, setTargetRetirementIncome] = useState(0);
  const [equityTarget, setEquityTarget] = useState(0);
  const [fixedIncomeTarget, setFixedIncomeTarget] = useState(0);
  const [northAmericaTarget, setNorthAmericaTarget] = useState(0);
  const [internationalTarget, setInternationalTarget] = useState(0);
  const [maxDrawdownTolerancePct, setMaxDrawdownTolerancePct] = useState(20);
  const [esgPreference, setEsgPreference] = useState("neutral");

  const [lastAnalysisDate, setLastAnalysisDate] = useState<Date | null>(null);

  /**
   * calculatePortfolioSummary
   *
   * Aggregates across:
   *  - Cash balances in each account
   *  - Position values (quantity Ã— current price)
   *
   * and returns:
   *  - totalValue: total portfolio market value
   *  - assetClassBreakdown: value by asset class (including cash)
   */
  const calculatePortfolioSummary = useCallback(
    (
      accountsData: Account[],
      positionsData: Record<string, Position[]>,
      instrumentsData: Record<string, Instrument>,
    ) => {
      let totalValue = 0;

      // Track intermediate amounts by asset class
      const assetClassValues: Record<string, number> = {
        cash: 0,
        equity: 0,
        fixed_income: 0,
        other: 0,
      };

      // 1) Add cash balances
      for (const account of accountsData) {
        const rawCash = account.cash_balance ?? 0;
        const cashNumber =
          typeof rawCash === "string" ? parseFloat(rawCash) : rawCash;

        const cash = Number.isFinite(cashNumber) ? cashNumber : 0;

        totalValue += cash;
        assetClassValues.cash += cash;
      }

      // 2) Add positions (using instrument allocations)
      Object.entries(positionsData).forEach(([accountId, accountPositions]) => {
        if (!accountId) return;
        for (const position of accountPositions) {
          const symbol = position.symbol;
          const instrument = instrumentsData[symbol];
          const quantity = Number(position.quantity) || 0;
          const price = instrument?.current_price ?? 0;
          const positionValue = quantity * price;
          totalValue += positionValue;

          // If we have allocation info, use it; otherwise classify as 'other'
          const allocation = instrument?.asset_class_allocation ?? {};
          const equityPct = allocation.equity ?? 0;
          const fixedIncomePct = allocation.fixed_income ?? 0;
          const otherPct = 100 - equityPct - fixedIncomePct;

          assetClassValues.equity += (positionValue * equityPct) / 100;
          assetClassValues.fixed_income +=
            (positionValue * fixedIncomePct) / 100;
          assetClassValues.other += (positionValue * otherPct) / 100;
        }
      });

      // Convert asset-class amounts into chart-friendly data
      const allocationData = Object.entries(assetClassValues)
        .filter(([, value]) => value > 0)
        .map(([name, value]) => ({
          name,
          value,
        }));

      setTotalPortfolioValue(totalValue);
      setAssetAllocationData(allocationData);
    },
    [],
  );

  /**
   * Initial data load:
   *  - Fetch backend user (sync with Clerk)
   *  - Load accounts
   *  - Load positions and instrument metadata
   *  - Calculate initial portfolio summary
   *  - Fetch latest completed analysis job for "Last analysis" badge
   */
  useEffect(() => {
    async function loadData() {
      if (!userLoaded) return;

      if (!user) {
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);

        const token = await getToken();
        if (!token) {
          setError("Missing auth token");
          setLoading(false);
          return;
        }

        // Sync / create user in backend and get profile data
        const responseJson = await apiRequest<{ user: UserData }>(
          "/api/user",
          token,
        );
        const backendUser = responseJson.user;

        // Initialise editable fields from user profile
        setDisplayName(backendUser.display_name ?? "");
        setYearsUntilRetirement(backendUser.years_until_retirement ?? 0);

        const incomeRaw = backendUser.target_retirement_income ?? 0;
        const income =
          typeof incomeRaw === "string" ? parseFloat(incomeRaw) : incomeRaw;
        setTargetRetirementIncome(income);

        setEquityTarget(backendUser.asset_class_targets?.equity ?? 0);
        setFixedIncomeTarget(
          backendUser.asset_class_targets?.fixed_income ?? 0,
        );
        setNorthAmericaTarget(
          backendUser.region_targets?.north_america ?? 0,
        );
        setInternationalTarget(
          backendUser.region_targets?.international ?? 0,
        );

        const prefs = backendUser.user_preferences;
        const goalsRaw =
          prefs && typeof prefs === "object" && "goals" in prefs
            ? (prefs as Record<string, unknown>).goals
            : undefined;
        const goals =
          goalsRaw && typeof goalsRaw === "object"
            ? (goalsRaw as Record<string, unknown>)
            : {};

        const drawdown = Number(goals.max_drawdown_tolerance_pct);
        setMaxDrawdownTolerancePct(Number.isFinite(drawdown) ? drawdown : 20);
        setEsgPreference(
          typeof goals.esg_preference === "string"
            ? goals.esg_preference
            : "neutral",
        );

        // Fetch most recent completed job to populate the "Last analysis" badge
        try {
          const jobsPayload = await apiRequest<{ jobs?: Job[] }>(
            "/api/jobs",
            token,
          );
          const jobsList = jobsPayload.jobs ?? [];
          const completedJob = jobsList.find((job) => job.status === "completed");
          if (completedJob?.completed_at) {
            setLastAnalysisDate(new Date(completedJob.completed_at));
          }
        } catch (jobsErr) {
          console.error("Error loading jobs for last analysis date:", jobsErr);
        }

        // Fetch accounts
        const accountsData = await apiRequest<Account[] | { accounts: Account[] }>(
          "/api/accounts",
          token,
        );
        const accountsList: Account[] = Array.isArray(accountsData)
          ? accountsData
          : accountsData.accounts;

        setAccounts(accountsList);

        // Fetch positions + instrument metadata for each account
        const positionsMap: Record<string, Position[]> = {};
        const instrumentsMap: Record<string, Instrument> = {};

        for (const account of accountsList) {
          const accountId = account.id;
          if (!accountId) {
            console.warn("Account missing ID in dashboard:", account);
            continue;
          }

          const positionsPayload = await apiRequest<{ positions?: Position[] }>(
            `/api/accounts/${accountId}/positions`,
            token,
          );
          const accountPositions = positionsPayload.positions ?? [];
          positionsMap[accountId] = accountPositions;

          for (const position of accountPositions) {
            if (position.instrument) {
              instrumentsMap[position.symbol] = normaliseInstrumentFromBackend(
                position.instrument,
              );
            }
          }
        }

        setPositions(positionsMap);
        setInstruments(instrumentsMap);
      } catch (err) {
        console.error("Error loading data:", err);
        setError(
          err instanceof Error ? err.message : "Failed to load data",
        );
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [userLoaded, user, getToken]);

  /**
   * Analysis completion listener
   *
   * When a separate page triggers a portfolio analysis and emits
   * an `analysis:completed` event, this handler:
   *  - Re-fetches accounts
   *  - Reloads positions and instrument data
   *  - Refreshes the "last analysis" badge
   * so that the dashboard reflects the latest prices/allocations.
   */
  useEffect(() => {
    if (!userLoaded || !user) return;

    const handleAnalysisCompleted = async () => {
      try {
        const token = await getToken();
        if (!token) return;

        console.log("Analysis completed - refreshing dashboard data...");

        const accountsData = await apiRequest<
          | Account[]
          | { accounts: Account[] }
        >("/api/accounts", token);
        const accountsList: Account[] = Array.isArray(accountsData)
          ? accountsData
          : accountsData.accounts;

        setAccounts(accountsList);

        const positionsData: Record<string, Position[]> = {};
        const instrumentsData: Record<string, Instrument> = {};

        for (const account of accountsList) {
          const accountId = account.id;
          if (!accountId) continue;

          const payload = await apiRequest<{ positions?: Position[] }>(
            `/api/accounts/${accountId}/positions`,
            token,
          );
          const accountPositions = payload.positions ?? [];
          positionsData[accountId] = accountPositions;

          for (const position of accountPositions) {
            if (position.instrument) {
              instrumentsData[position.symbol] = normaliseInstrumentFromBackend(
                position.instrument,
              );
            }
          }
        }

        setPositions(positionsData);
        setInstruments(instrumentsData);

        // Refresh "last analysis" timestamp from jobs API so the badge updates
        try {
          const jobsPayload = await apiRequest<{ jobs?: Job[] }>("/api/jobs", token);
          const jobsList = jobsPayload.jobs ?? [];
          const completedJob = jobsList.find((job) => job.status === "completed");
          if (completedJob?.completed_at) {
            setLastAnalysisDate(new Date(completedJob.completed_at));
          }
        } catch (jobsErr) {
          console.error("Error refreshing last analysis date:", jobsErr);
        }
      } catch (err) {
        console.error("Error refreshing dashboard data:", err);
      }
    };

    window.addEventListener("analysis:completed", handleAnalysisCompleted);

    return () => {
      window.removeEventListener(
        "analysis:completed",
        handleAnalysisCompleted,
      );
    };
  }, [userLoaded, user, getToken]);

  /**
   * handleSaveSettings
   *
   * Persists updated user settings (display name, retirement horizon,
   * income target, allocation targets) to the backend via `/api/user`.
   */
  const handleSaveSettings = async () => {
    if (!user) return;

    try {
      const token = await getToken();
      if (!token) {
        showToast("error", "Missing auth token");
        return;
      }

      if (!displayName || displayName.trim().length === 0) {
        showToast("error", "Display name is required");
        return;
      }

      if (yearsUntilRetirement < 0 || yearsUntilRetirement > 50) {
        showToast(
          "error",
          "Years until retirement must be between 0 and 50",
        );
        return;
      }

      if (targetRetirementIncome < 0) {
        showToast("error", "Target retirement income must be positive");
        return;
      }

      if (maxDrawdownTolerancePct < 0 || maxDrawdownTolerancePct > 100) {
        showToast("error", "Max drawdown tolerance must be between 0 and 100%");
        return;
      }

      // Validate asset-class allocation percentages
      const equityFixed = equityTarget + fixedIncomeTarget;
      if (Math.abs(equityFixed - 100) > 0.01) {
        showToast("error", "Equity and Fixed Income must sum to 100%");
        return;
      }

      // Validate region allocation percentages
      const regionsTotal = northAmericaTarget + internationalTarget;
      if (Math.abs(regionsTotal - 100) > 0.01) {
        showToast(
          "error",
          "North America and International must sum to 100%",
        );
        return;
      }

      const payload = {
        display_name: displayName,
        years_until_retirement: yearsUntilRetirement,
        target_retirement_income: targetRetirementIncome,
        asset_class_targets: {
          equity: equityTarget,
          fixed_income: fixedIncomeTarget,
        },
        region_targets: {
          north_america: northAmericaTarget,
          international: internationalTarget,
        },
        user_preferences: {
          goals: {
            income_floor: targetRetirementIncome,
            max_drawdown_tolerance_pct: maxDrawdownTolerancePct,
            esg_preference: esgPreference,
          },
        },
      };

      await apiRequest("/api/user", token, {
        method: "PUT",
        body: JSON.stringify(payload),
      });

      showToast("success", "Settings updated successfully");
    } catch (err) {
      console.error("Error updating user:", err);
      showToast(
        "error",
        err instanceof Error ? err.message : "Failed to update settings",
      );
    }
  };

  /**
   * Update handlers for sliders (keep local state in sync with inputs)
   */
  const handleEquityChange = (value: number) => {
    setEquityTarget(value);
    setFixedIncomeTarget(100 - value);
  };

  const handleFixedIncomeChange = (value: number) => {
    setFixedIncomeTarget(value);
    setEquityTarget(100 - value);
  };

  const handleNorthAmericaChange = (value: number) => {
    setNorthAmericaTarget(value);
    setInternationalTarget(100 - value);
  };

  const handleInternationalChange = (value: number) => {
    setInternationalTarget(value);
    setNorthAmericaTarget(100 - value);
  };

  /**
   * Derived label for the last analysis timestamp
   */
  const lastAnalysisLabel = lastAnalysisDate
    ? lastAnalysisDate.toLocaleString()
    : "Never";

  /**
   * Recompute summary whenever accounts/positions/instruments change
   */
  useEffect(() => {
    if (accounts.length === 0) {
      setTotalPortfolioValue(0);
      setAssetAllocationData([]);
      return;
    }
    calculatePortfolioSummary(accounts, positions, instruments);
  }, [accounts, positions, instruments, calculatePortfolioSummary]);

  /**
   * Render
   */
  return (
    <>
      <Head>
        <title>Alex AI Financial Advisor - Dashboard</title>
      </Head>

      <Layout>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <h1 className="text-3xl font-bold text-dark mb-8">Dashboard</h1>

          {loading ? (
            /**
             * Skeleton state:
             * Generic loading placeholders while user + portfolio data is fetched.
             */
            <div className="space-y-8">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="bg-white rounded-lg shadow p-6">
                    <Skeleton className="h-4 w-3/4 mx-auto mb-3" />
                    <Skeleton className="h-8 w-1/2 mx-auto mb-4" />
                    <Skeleton className="h-4 w-full mb-2" />
                    <Skeleton className="h-4 w-5/6 mx-auto" />
                  </div>
                ))}
              </div>
              <SkeletonCard />
            </div>
          ) : error ? (
            /**
             * Error state:
             * Display a user-friendly error message when something goes wrong.
             */
            <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
              <h2 className="font-semibold mb-1">Something went wrong</h2>
              <p className="text-sm">{error}</p>
            </div>
          ) : (
            /**
             * Main dashboard content:
             *  - Portfolio overview cards
             *  - Allocation charts
             *  - User settings / retirement goals
             */
            <div className="space-y-8">
              {/* Top stats cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                {/* Total Portfolio Value */}
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-sm font-medium text-gray-500">
                    Total Portfolio Value
                  </h2>
                  <p className="mt-2 text-2xl font-semibold text-dark">
                    {formatCurrency(totalPortfolioValue)}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
                    Includes cash + market value of all positions
                  </p>
                </div>

                {/* Number of Accounts */}
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-sm font-medium text-gray-500">
                    Accounts
                  </h2>
                  <p className="mt-2 text-2xl font-semibold text-dark">
                    {accounts.length}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
                    Investment accounts linked to your profile
                  </p>
                </div>

                {/* Last Analysis */}
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-sm font-medium text-gray-500">
                    Last Analysis
                  </h2>
                  <p className="mt-2 text-2xl font-semibold text-dark">
                    {lastAnalysisLabel}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
                    Updated when an analysis job completes
                  </p>
                </div>

                {/* Years until retirement */}
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-sm font-medium text-gray-500">
                    Years Until Retirement
                  </h2>
                  <p className="mt-2 text-2xl font-semibold text-dark">
                    {yearsUntilRetirement}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
                    Based on your saved preferences
                  </p>
                </div>
              </div>

              {/* Middle section: Asset allocation + retirement targets */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Asset Allocation Chart */}
                <div className="bg-white rounded-lg shadow p-6 lg:col-span-2">
                  <h2 className="text-lg font-semibold text-dark mb-4">
                    Asset Allocation (Actual)
                  </h2>
                  {assetAllocationData.length === 0 ? (
                    <p className="text-sm text-gray-500">
                      No allocation data available yet. Add positions to your
                      accounts or run an analysis.
                    </p>
                  ) : (
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={assetAllocationData}
                            dataKey="value"
                            nameKey="name"
                            cx="50%"
                            cy="50%"
                            outerRadius={80}
                            label={(props: AssetPieLabelProps) => {
                              const { name, value, percent } = props;
                              const safeName =
                                name !== undefined ? String(name) : "";
                              const safeValue = Number(value ?? 0);
                              const pct =
                                typeof percent === "number"
                                  ? percent * 100
                                  : 0;

                              return `${formatAssetClassName(
                                safeName,
                              )}: ${formatCurrency(
                                safeValue,
                              )} (${pct.toFixed(1)}%)`;
                            }}
                          >
                            {assetAllocationData.map((entry, index) => (
                              <Cell
                                key={entry.name}
                                fill={COLORS[index % COLORS.length]}
                              />
                            ))}
                          </Pie>
                          <Tooltip
                            formatter={(value: number | string) =>
                              typeof value === "number"
                                ? formatCurrency(value)
                                : formatCurrency(Number(value))
                            }
                            labelFormatter={(name) =>
                              formatAssetClassName(String(name))
                            }
                          />
                          <Legend
                            formatter={(value) =>
                              formatAssetClassName(String(value))
                            }
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>

                {/* Target Allocation Controls */}
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-lg font-semibold text-dark mb-4">
                    Target Allocation
                  </h2>

                  {/* Asset Class Targets */}
                  <div className="mb-6">
                    <h3 className="text-sm font-medium text-gray-700 mb-2">
                      Asset Class Targets
                    </h3>
                    <div className="space-y-3">
                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span>Equity</span>
                          <span>{equityTarget}%</span>
                        </div>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={equityTarget}
                          onChange={(e) =>
                            handleEquityChange(Number(e.target.value))
                          }
                          className="w-full"
                        />
                      </div>
                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span>Fixed Income</span>
                          <span>{fixedIncomeTarget}%</span>
                        </div>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={fixedIncomeTarget}
                          onChange={(e) =>
                            handleFixedIncomeChange(Number(e.target.value))
                          }
                          className="w-full"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Region Targets */}
                  <div className="mb-6">
                    <h3 className="text-sm font-medium text-gray-700 mb-2">
                      Region Targets
                    </h3>
                    <div className="space-y-3">
                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span>North America</span>
                          <span>{northAmericaTarget}%</span>
                        </div>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={northAmericaTarget}
                          onChange={(e) =>
                            handleNorthAmericaChange(
                              Number(e.target.value),
                            )
                          }
                          className="w-full"
                        />
                      </div>
                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span>International</span>
                          <span>{internationalTarget}%</span>
                        </div>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={internationalTarget}
                          onChange={(e) =>
                            handleInternationalChange(
                              Number(e.target.value),
                            )
                          }
                          className="w-full"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Personalization */}
                  <div className="mb-6">
                    <h3 className="text-sm font-medium text-gray-700 mb-2">
                      Goals & Preferences
                    </h3>
                    <label className="block text-xs text-gray-600 mb-3">
                      Max drawdown tolerance (%)
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
                        value={maxDrawdownTolerancePct}
                        onChange={(e) =>
                          setMaxDrawdownTolerancePct(Number(e.target.value || 0))
                        }
                      />
                    </label>
                    <label className="block text-xs text-gray-600">
                      ESG preference
                      <select
                        className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
                        value={esgPreference}
                        onChange={(e) => setEsgPreference(e.target.value)}
                      >
                        <option value="neutral">Neutral</option>
                        <option value="prefer_esg">Prefer ESG</option>
                        <option value="strict_esg">Strict ESG</option>
                      </select>
                    </label>
                    <p className="mt-2 text-xs text-gray-400">
                      These preferences are stored with your profile and can drive
                      future analysis outputs.
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={handleSaveSettings}
                    className="w-full py-2 px-4 bg-primary text-white rounded-md text-sm font-medium hover:bg-primary/90"
                  >
                    Save Settings
                  </button>
                </div>
              </div>

              {/* User Details + Retirement Target */}
              <div className="bg-white rounded-lg shadow p-6">
                <h2 className="text-lg font-semibold text-dark mb-4">
                  Profile &amp; Retirement Goals
                </h2>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {/* Display Name */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Display Name
                    </label>
                    <input
                      type="text"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm text-sm"
                    />
                  </div>

                  {/* Years until retirement */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Years Until Retirement
                    </label>
                    <input
                      type="number"
                      value={yearsUntilRetirement}
                      onChange={(e) =>
                        setYearsUntilRetirement(Number(e.target.value))
                      }
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm text-sm"
                    />
                  </div>

                  {/* Target retirement income */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Target Annual Retirement Income (£)
                    </label>
                    <input
                      type="number"
                      value={targetRetirementIncome}
                      onChange={(e) =>
                        setTargetRetirementIncome(Number(e.target.value))
                      }
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm text-sm"
                    />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </Layout>
    </>
  );
}
