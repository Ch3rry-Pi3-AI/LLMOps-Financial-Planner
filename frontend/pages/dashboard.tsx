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
import { API_URL } from "../lib/config";
import Layout from "../components/Layout";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { showToast } from "../components/Toast";
import Head from "next/head";

/**
 * UserData
 *
 * Shape of the user profile as stored in the backend:
 *  - Clerk user ID
 *  - Basic display details
 *  - Retirement horizon and income target
 *  - Target allocations for asset classes and regions
 */
interface UserData {
  clerk_user_id: string;
  display_name: string;
  years_until_retirement: number;
  target_retirement_income: number;
  asset_class_targets: Record<string, number>;
  region_targets: Record<string, number>;
}

/**
 * Account
 *
 * Represents an investment account (e.g. brokerage, pension wrapper).
 */
interface Account {
  account_id: string;
  clerk_user_id: string;
  account_name: string;
  account_type: string;
  account_purpose: string;
  cash_balance: number;
  created_at: string;
  updated_at: string;
}

/**
 * Position
 *
 * Represents a holding in a specific instrument within an account.
 */
interface Position {
  position_id: string;
  account_id: string;
  symbol: string;
  quantity: number;
  created_at: string;
  updated_at: string;
}

/**
 * Instrument
 *
 * Describes a tradable instrument (ETF, stock, fund, etc.), including:
 *  - Current price
 *  - Asset class / region / sector allocation breakdowns (in %)
 */
interface Instrument {
  symbol: string;
  name: string;
  instrument_type: string;
  current_price?: number;
  asset_class_allocation?: Record<string, number>;
  region_allocation?: Record<string, number>;
  sector_allocation?: Record<string, number>;
}

/**
 * Dashboard
 *
 * Main component responsible for:
 *  - Fetching and syncing user + portfolio data
 *  - Calculating aggregate portfolio metrics
 *  - Rendering summary cards, miniature charts, and settings UI
 */
export default function Dashboard() {
  const { user, isLoaded: userLoaded } = useUser();
  const { getToken } = useAuth();

  // Core data fetched from the backend
  const [userData, setUserData] = useState<UserData | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [positions, setPositions] = useState<Record<string, Position[]>>({});
  const [instruments, setInstruments] = useState<Record<string, Instrument>>({});

  // UI / status flags
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAnalysisDate, setLastAnalysisDate] = useState<string | null>(null);

  /**
   * Form state for editable user settings
   * (initialised separately to avoid flicker while loading).
   */
  const [displayName, setDisplayName] = useState("");
  const [yearsUntilRetirement, setYearsUntilRetirement] = useState(0);
  const [targetRetirementIncome, setTargetRetirementIncome] = useState(0);
  const [equityTarget, setEquityTarget] = useState(0);
  const [fixedIncomeTarget, setFixedIncomeTarget] = useState(0);
  const [northAmericaTarget, setNorthAmericaTarget] = useState(0);
  const [internationalTarget, setInternationalTarget] = useState(0);

  /**
   * calculatePortfolioSummary
   *
   * Aggregates across:
   *  - Cash balances in each account
   *  - Position values (quantity × current price)
   *
   * and returns:
   *  - totalValue: total portfolio market value
   *  - assetClassBreakdown: value by asset class (including cash)
   */
  const calculatePortfolioSummary = useCallback(() => {
    let totalValue = 0;
    const assetClassBreakdown: Record<string, number> = {
      equity: 0,
      fixed_income: 0,
      alternatives: 0,
      cash: 0,
    };

    // 1. Add cash balances per account
    accounts.forEach((account) => {
      const cashBalance = Number(account.cash_balance);
      totalValue += cashBalance;
      assetClassBreakdown.cash += cashBalance;
    });

    // 2. Add value of each position and allocate by instrument's asset_class_allocation
    Object.entries(positions).forEach(([, accountPositions]) => {
      accountPositions.forEach((position) => {
        const instrument = instruments[position.symbol];
        if (instrument?.current_price) {
          const positionValue =
            Number(position.quantity) * Number(instrument.current_price);
          totalValue += positionValue;

          if (instrument.asset_class_allocation) {
            Object.entries(instrument.asset_class_allocation).forEach(
              ([assetClass, percentage]) => {
                assetClassBreakdown[assetClass] =
                  (assetClassBreakdown[assetClass] || 0) +
                  (positionValue * percentage) / 100;
              }
            );
          }
        }
      });
    });

    return { totalValue, assetClassBreakdown };
  }, [accounts, positions, instruments]);

  /**
   * Initial load: sync/create user and fetch accounts, positions, instruments.
   *
   * Steps:
   *  1. Ensure Clerk user is loaded and authenticated
   *  2. Call `/api/user` to sync user and retrieve profile data
   *  3. Fetch `/api/accounts` to get account list
   *  4. For each account, fetch `/api/accounts/{id}/positions`
   *  5. Build positions and instruments maps for lookups
   */
  useEffect(() => {
    async function loadData() {
      if (!userLoaded || !user) return;

      try {
        const token = await getToken();
        if (!token) {
          setError("Not authenticated");
          setLoading(false);
          return;
        }

        // Sync / create user in backend and get profile data
        const userResponse = await fetch(`${API_URL}/api/user`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (!userResponse.ok) {
          throw new Error(`Failed to sync user: ${userResponse.status}`);
        }

        const response = await userResponse.json();
        const userData = response.user;
        setUserData(userData);

        // Initialise editable fields from user profile
        setDisplayName(userData.display_name || "");
        setYearsUntilRetirement(userData.years_until_retirement || 0);

        // Ensure target_retirement_income is a number
        const income = userData.target_retirement_income
          ? typeof userData.target_retirement_income === "string"
            ? parseFloat(userData.target_retirement_income)
            : userData.target_retirement_income
          : 0;
        setTargetRetirementIncome(income);

        setEquityTarget(userData.asset_class_targets?.equity || 0);
        setFixedIncomeTarget(userData.asset_class_targets?.fixed_income || 0);
        setNorthAmericaTarget(userData.region_targets?.north_america || 0);
        setInternationalTarget(userData.region_targets?.international || 0);

        // Fetch accounts
        const accountsResponse = await fetch(`${API_URL}/api/accounts`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (accountsResponse.ok) {
          const accountsData = await accountsResponse.json();
          setAccounts(accountsData);

          // Positions and instruments maps (by account ID / symbol)
          const positionsMap: Record<string, Position[]> = {};
          const instrumentsMap: Record<string, Instrument> = {};

          for (const account of accountsData) {
            // Defensive: skip any account that does not expose an ID
            // (API shape may differ from Account interface)
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const accountId = (account as any).id ?? account.account_id;
            if (!accountId) {
              console.warn("Account missing ID in dashboard:", account);
              continue;
            }

            const positionsResponse = await fetch(
              `${API_URL}/api/accounts/${accountId}/positions`,
              {
                headers: {
                  Authorization: `Bearer ${token}`,
                },
              }
            );

            if (positionsResponse.ok) {
              const positionsData = await positionsResponse.json();
              positionsMap[accountId] = positionsData.positions || [];

              // Extract instrument metadata for each position
              for (const position of positionsData.positions || []) {
                if (position.instrument) {
                  instrumentsMap[position.symbol] =
                    position.instrument as Instrument;
                }
              }
            }
          }

          setPositions(positionsMap);
          setInstruments(instrumentsMap);
        }

        // Placeholder for lastAnalysisDate – would be populated from jobs API
        setLastAnalysisDate(null);
      } catch (err) {
        console.error("Error loading data:", err);
        setError(
          err instanceof Error ? err.message : "Failed to load data"
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
   * so that the dashboard reflects the latest prices/allocations.
   */
  useEffect(() => {
    if (!userLoaded || !user) return;

    const handleAnalysisCompleted = async () => {
      try {
        const token = await getToken();
        if (!token) return;

        console.log("Analysis completed - refreshing dashboard data...");

        const accountsResponse = await fetch(`${API_URL}/api/accounts`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (accountsResponse.ok) {
          const accountsData = await accountsResponse.json();
          // Some APIs return { accounts: [...] }, others a bare array; handle both
          const accountsList = accountsData.accounts || accountsData;
          setAccounts(accountsList);

          const positionsData: Record<string, Position[]> = {};
          const instrumentsData: Record<string, Instrument> = {};

          for (const account of accountsList || []) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const accountId = (account as any).id ?? account.account_id;
            if (!accountId) continue;

            const positionsResponse = await fetch(
              `${API_URL}/api/accounts/${accountId}/positions`,
              {
                headers: {
                  Authorization: `Bearer ${token}`,
                },
              }
            );

            if (positionsResponse.ok) {
              const data = await positionsResponse.json();
              positionsData[accountId] = data.positions || [];

              for (const position of data.positions || []) {
                if (position.instrument) {
                  instrumentsData[position.symbol] = position.instrument;
                }
              }
            }
          }

          setPositions(positionsData);
          setInstruments(instrumentsData);

          // Portfolio summary will be recalculated on next render
        }
      } catch (err) {
        console.error("Error refreshing dashboard data:", err);
      }
    };

    window.addEventListener("analysis:completed", handleAnalysisCompleted);

    return () => {
      window.removeEventListener("analysis:completed", handleAnalysisCompleted);
    };
  }, [userLoaded, user, getToken, calculatePortfolioSummary]);

  /**
   * handleSaveSettings
   *
   * Validates and persists user settings (display name, horizon,
   * retirement income, target allocations) via `PUT /api/user`.
   * Displays success/error feedback using the toast system.
   */
  const handleSaveSettings = async () => {
    if (!userData) return;

    // Basic validation for required fields
    if (!displayName || displayName.trim().length === 0) {
      showToast("error", "Display name is required");
      return;
    }

    if (yearsUntilRetirement < 0 || yearsUntilRetirement > 50) {
      showToast(
        "error",
        "Years until retirement must be between 0 and 50"
      );
      return;
    }

    if (targetRetirementIncome < 0) {
      showToast("error", "Target retirement income must be positive");
      return;
    }

    // Validate asset-class allocation percentages
    const equityFixed = equityTarget + fixedIncomeTarget;
    if (Math.abs(equityFixed - 100) > 0.01) {
      showToast("error", "Equity and Fixed Income must sum to 100%");
      return;
    }

    // Validate regional allocation percentages
    const regionTotal = northAmericaTarget + internationalTarget;
    if (Math.abs(regionTotal - 100) > 0.01) {
      showToast(
        "error",
        "North America and International must sum to 100%"
      );
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const token = await getToken();
      if (!token) throw new Error("Not authenticated");

      const updateData = {
        display_name: displayName.trim(),
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
      };

      const response = await fetch(`${API_URL}/api/user`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(updateData),
      });

      if (!response.ok) {
        throw new Error(`Failed to save settings: ${response.status}`);
      }

      const updatedUser = await response.json();
      setUserData(updatedUser);

      // Report success via toast
      showToast("success", "Settings saved successfully!");
    } catch (err) {
      console.error("Error saving settings:", err);
      showToast(
        "error",
        err instanceof Error ? err.message : "Failed to save settings"
      );
    } finally {
      setSaving(false);
    }
  };

  // Compute aggregate portfolio metrics for summary cards and charts
  const { totalValue, assetClassBreakdown } = calculatePortfolioSummary();

  /**
   * Prepare data for main asset allocation pie chart:
   *  - Filter out zero-value buckets
   *  - Attach a percentage of total for each slice
   */
  const pieChartData = Object.entries(assetClassBreakdown)
    .filter(([, value]) => value > 0)
    .map(([key, value]) => ({
      name:
        key.charAt(0).toUpperCase() + key.slice(1).replace("_", " "),
      value: Math.round(value),
      percentage:
        totalValue > 0 ? Math.round((value / totalValue) * 100) : 0,
    }));

  // Local colour palette for the main portfolio allocation chart
  const COLORS = ["#209DD7", "#753991", "#FFB707", "#062147", "#10B981"];

  return (
    <>
      <Head>
        <title>Dashboard - Alex AI Financial Advisor</title>
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
                    <Skeleton className="h-8 w-1/2 mx-auto" />
                  </div>
                ))}
              </div>
              <SkeletonCard />
              <SkeletonCard />
            </div>
          ) : (
            <>
              {/* Portfolio Summary Cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
                {/* Total Portfolio Value */}
                <div className="bg-white rounded-lg shadow p-6 text-center">
                  <h3 className="text-sm font-medium text-gray-500 mb-3">
                    Total Portfolio Value
                  </h3>
                  <p className="text-3xl font-bold text-primary">
                    {totalValue % 1 === 0
                      ? `$${totalValue.toLocaleString("en-US")}`
                      : `$${totalValue.toLocaleString("en-US", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}`}
                  </p>
                </div>

                {/* Number of Accounts */}
                <div className="bg-white rounded-lg shadow p-6 text-center">
                  <h3 className="text-sm font-medium text-gray-500 mb-3">
                    Number of Accounts
                  </h3>
                  <p className="text-3xl font-bold text-dark">
                    {accounts.length}
                  </p>
                </div>

                {/* Asset Allocation Mini Chart */}
                <div className="bg-white rounded-lg shadow p-6">
                  <h3 className="text-sm font-medium text-gray-500 mb-2 text-center">
                    Asset Allocation
                  </h3>
                  {pieChartData.length > 0 ? (
                    <div className="h-24">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={pieChartData}
                            cx="50%"
                            cy="50%"
                            innerRadius={20}
                            outerRadius={40}
                            paddingAngle={2}
                            dataKey="value"
                          >
                            {pieChartData.map((entry, index) => (
                              <Cell
                                key={`cell-${index}`}
                                fill={COLORS[index % COLORS.length]}
                              />
                            ))}
                          </Pie>
                          <Tooltip
                            formatter={(value: number) =>
                              `$${value.toLocaleString()}`
                            }
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500">No positions yet</p>
                  )}
                </div>

                {/* Last Analysis Timestamp */}
                <div className="bg-white rounded-lg shadow p-6 text-center">
                  <h3 className="text-sm font-medium text-gray-500 mb-3">
                    Last Analysis
                  </h3>
                  <p className="text-3xl font-bold text-dark">
                    {lastAnalysisDate
                      ? new Date(lastAnalysisDate).toLocaleDateString()
                      : "Never"}
                  </p>
                </div>
              </div>

              {/* User Settings Section */}
              <div className="bg-white rounded-lg shadow p-6 mb-8">
                <h2 className="text-xl font-semibold text-dark mb-6">
                  User Settings
                </h2>

                {/* Error / success banner (when error state is reused for messaging) */}
                {loading ? (
                  <p className="text-gray-500">Loading...</p>
                ) : error && !error.includes("success") ? (
                  <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
                    <p className="text-red-600">{error}</p>
                  </div>
                ) : error && error.includes("success") ? (
                  <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
                    <p className="text-green-600">✅ {error}</p>
                  </div>
                ) : null}

                {/* Settings form grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Display Name */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Display Name
                    </label>
                    <input
                      type="text"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>

                  {/* Target Retirement Income */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Target Retirement Income (Annual)
                    </label>
                    <input
                      type="text"
                      value={
                        targetRetirementIncome
                          ? targetRetirementIncome.toLocaleString("en-US")
                          : ""
                      }
                      onChange={(e) => {
                        const value = e.target.value.replace(/,/g, "");
                        const num = parseInt(value) || 0;
                        if (!isNaN(num)) {
                          setTargetRetirementIncome(num);
                        }
                      }}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>

                  {/* Years Until Retirement slider */}
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Years Until Retirement: {yearsUntilRetirement}
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="50"
                      value={yearsUntilRetirement}
                      onChange={(e) =>
                        setYearsUntilRetirement(Number(e.target.value))
                      }
                      className="w-full"
                    />
                    <div className="flex justify-between text-xs text-gray-500">
                      <span>0</span>
                      <span>10</span>
                      <span>20</span>
                      <span>30</span>
                      <span>40</span>
                      <span>50</span>
                    </div>
                  </div>

                  {/* Target Asset Class Allocation */}
                  <div>
                    <h3 className="text-sm font-medium text-gray-700 mb-3">
                      Target Asset Class Allocation
                    </h3>
                    <div className="space-y-3">
                      <div>
                        <label className="text-sm text-gray-600">
                          Equity: {equityTarget}%
                        </label>
                        <input
                          type="range"
                          min="0"
                          max="100"
                          value={equityTarget}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setEquityTarget(val);
                            setFixedIncomeTarget(100 - val);
                          }}
                          className="w-full"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-600">
                          Fixed Income: {fixedIncomeTarget}%
                        </label>
                        <input
                          type="range"
                          min="0"
                          max="100"
                          value={fixedIncomeTarget}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setFixedIncomeTarget(val);
                            setEquityTarget(100 - val);
                          }}
                          className="w-full"
                        />
                      </div>
                    </div>

                    {/* Mini pie chart: asset-class targets */}
                    <div className="mt-4 h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={[
                              { name: "Equity", value: equityTarget },
                              { name: "Fixed Income", value: fixedIncomeTarget },
                            ]}
                            cx="50%"
                            cy="50%"
                            outerRadius={40}
                            dataKey="value"
                          >
                            <Cell fill="#209DD7" />
                            <Cell fill="#753991" />
                          </Pie>
                          <Tooltip formatter={(value) => `${value}%`} />
                          <Legend />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  {/* Target Regional Allocation */}
                  <div>
                    <h3 className="text-sm font-medium text-gray-700 mb-3">
                      Target Regional Allocation
                    </h3>
                    <div className="space-y-3">
                      <div>
                        <label className="text-sm text-gray-600">
                          North America: {northAmericaTarget}%
                        </label>
                        <input
                          type="range"
                          min="0"
                          max="100"
                          value={northAmericaTarget}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setNorthAmericaTarget(val);
                            setInternationalTarget(100 - val);
                          }}
                          className="w-full"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-600">
                          International: {internationalTarget}%
                        </label>
                        <input
                          type="range"
                          min="0"
                          max="100"
                          value={internationalTarget}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setInternationalTarget(val);
                            setNorthAmericaTarget(100 - val);
                          }}
                          className="w-full"
                        />
                      </div>
                    </div>

                    {/* Mini pie chart: regional targets */}
                    <div className="mt-4 h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={[
                              {
                                name: "North America",
                                value: northAmericaTarget,
                              },
                              {
                                name: "International",
                                value: internationalTarget,
                              },
                            ]}
                            cx="50%"
                            cy="50%"
                            outerRadius={40}
                            dataKey="value"
                          >
                            <Cell fill="#FFB707" />
                            <Cell fill="#062147" />
                          </Pie>
                          <Tooltip formatter={(value) => `${value}%`} />
                          <Legend />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>

                {/* Save button */}
                <div className="mt-6">
                  <button
                    onClick={handleSaveSettings}
                    disabled={saving || loading}
                    className={`px-6 py-2 rounded-lg font-medium transition-colors ${
                      saving || loading
                        ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                        : "bg-primary text-white hover:bg-blue-600"
                    }`}
                  >
                    {saving ? "Saving..." : "Save Settings"}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </Layout>
    </>
  );
}
