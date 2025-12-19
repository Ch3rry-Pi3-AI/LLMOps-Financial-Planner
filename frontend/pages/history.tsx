import { useEffect, useMemo, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import Layout from "../components/Layout";
import { apiRequest } from "../lib/api";

type Job = {
  id: string;
  created_at: string;
  status: string;
  job_type: string;
  report_payload?: {
    recommendations?: Array<{
      recommendation: string;
      reasoning: string;
      priority: string;
    }>;
  };
  retirement_payload?: {
    metrics?: Record<string, unknown>;
  };
  charts_payload?: Record<string, unknown> | null;
};

const safeNumber = (value: unknown): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
};

const formatDate = (dateString: string) =>
  new Date(dateString).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const formatTime = (dateString: string) =>
  new Date(dateString).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });

const titleCase = (name: string): string =>
  name
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");

function getSuccessRate(job?: Job | null): number | null {
  const metrics = job?.retirement_payload?.metrics;
  const mc =
    metrics && typeof metrics === "object"
      ? (metrics as Record<string, unknown>).monte_carlo
      : undefined;
  const sr =
    mc && typeof mc === "object"
      ? (mc as Record<string, unknown>).success_rate
      : undefined;
  const n = safeNumber(sr);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function getAssetClassPct(job?: Job | null): Record<string, number> {
  const charts = job?.charts_payload;
  const asset =
    charts && typeof charts === "object"
      ? (charts as Record<string, unknown>).asset_class_allocation
      : undefined;
  const data =
    asset && typeof asset === "object"
      ? (asset as Record<string, unknown>).data
      : undefined;
  if (!Array.isArray(data)) return {};
  const total = data.reduce((sum: number, item: unknown) => {
    if (!item || typeof item !== "object") return sum;
    return sum + safeNumber((item as Record<string, unknown>).value);
  }, 0);
  if (total <= 0) return {};
  const out: Record<string, number> = {};
  for (const item of data) {
    if (!item || typeof item !== "object") continue;
    const obj = item as Record<string, unknown>;
    const key = String(obj.name || "").toLowerCase();
    if (!key) continue;
    out[key] = (safeNumber(obj.value) / total) * 100;
  }
  return out;
}

function diffRecommendations(a?: Job | null, b?: Job | null) {
  const aRows = a?.report_payload?.recommendations || [];
  const bRows = b?.report_payload?.recommendations || [];
  const aSet = new Set(aRows.map((r) => String(r.recommendation || "").trim()).filter(Boolean));
  const bSet = new Set(bRows.map((r) => String(r.recommendation || "").trim()).filter(Boolean));
  const added = Array.from(bSet).filter((x) => !aSet.has(x));
  const removed = Array.from(aSet).filter((x) => !bSet.has(x));
  return { added, removed };
}

export default function History() {
  const { getToken } = useAuth();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filterDate, setFilterDate] = useState("");
  const [leftId, setLeftId] = useState<string>("");
  const [rightId, setRightId] = useState<string>("");

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError(null);

        if (typeof window !== "undefined") {
          try {
            const cached = window.sessionStorage.getItem("history:jobs");
            if (cached) {
              const parsed = JSON.parse(cached);
              if (Array.isArray(parsed)) setJobs(parsed);
            }
          } catch {
            // ignore
          }
        }

        const token = await getToken();
        if (!token) {
          setError("Missing auth token");
          return;
        }
        const resp = await apiRequest<{ jobs?: Job[] }>("/api/jobs", token);
        const list = Array.isArray(resp.jobs) ? resp.jobs : [];
        setJobs(list);
        if (typeof window !== "undefined") {
          try {
            window.sessionStorage.setItem("history:jobs", JSON.stringify(list));
          } catch {
            // ignore
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load history");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [getToken]);

  const completed = useMemo(() => {
    const q = query.trim().toLowerCase();
    const dateFilter = filterDate.trim();
    return jobs
      .filter((j) => j.status === "completed" && j.job_type === "portfolio_analysis")
      .filter((j) => {
        if (!dateFilter) return true;
        try {
          const d = new Date(j.created_at).toISOString().slice(0, 10);
          return d === dateFilter;
        } catch {
          return false;
        }
      })
      .filter((j) => (q ? `${j.id} ${j.created_at}`.toLowerCase().includes(q) : true))
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  }, [jobs, query, filterDate]);

  const leftJob = useMemo(
    () => completed.find((j) => j.id === leftId) || null,
    [completed, leftId],
  );
  const rightJob = useMemo(
    () => completed.find((j) => j.id === rightId) || null,
    [completed, rightId],
  );

  useEffect(() => {
    if (completed.length < 2) return;
    if (!leftId && !rightId) {
      setRightId(completed[0].id);
      setLeftId(completed[1].id);
    }
  }, [completed, leftId, rightId]);

  const trend = useMemo(() => {
    const points = completed
      .map((j) => ({
        id: j.id,
        created_at: j.created_at,
        ts: new Date(j.created_at).getTime(),
        successRate: getSuccessRate(j),
      }))
      .filter((d) => d.successRate != null)
      .sort((a, b) => a.ts - b.ts);

    const spanMs =
      points.length >= 2 ? points[points.length - 1].ts - points[0].ts : 0;
    const showTime = Boolean(filterDate) || spanMs <= 24 * 60 * 60 * 1000;

    return points.map((p) => ({
      ...p,
      xLabel: showTime ? formatTime(p.created_at) : formatDate(p.created_at),
    }));
  }, [completed, filterDate]);

  const trendUseTimeAxis = useMemo(() => {
    if (trend.length <= 1) return Boolean(filterDate);
    const spanMs = trend[trend.length - 1].ts - trend[0].ts;
    return Boolean(filterDate) || spanMs <= 24 * 60 * 60 * 1000;
  }, [trend, filterDate]);

  const recDiff = useMemo(() => diffRecommendations(leftJob, rightJob), [leftJob, rightJob]);
  const leftAlloc = useMemo(() => getAssetClassPct(leftJob), [leftJob]);
  const rightAlloc = useMemo(() => getAssetClassPct(rightJob), [rightJob]);
  const allAllocKeys = useMemo(() => {
    return Array.from(new Set([...Object.keys(leftAlloc), ...Object.keys(rightAlloc)])).sort();
  }, [leftAlloc, rightAlloc]);

  const leftSr = getSuccessRate(leftJob);
  const rightSr = getSuccessRate(rightJob);

  return (
    <>
      <Head>
        <title>Alex AI Financial Advisor - History</title>
      </Head>

      <Layout>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex items-start justify-between gap-6 mb-8">
            <div>
              <h1 className="text-3xl font-bold text-dark">History & Comparison</h1>
              <p className="text-gray-500 mt-2">
                Compare two analysis runs, view trends, and see what changed.
              </p>
            </div>
            <Link
              href="/analysis"
              className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 font-semibold"
            >
              Go to Analysis
            </Link>
          </div>

          {loading ? (
            <div className="bg-white rounded-lg shadow p-8 animate-pulse">
              <div className="h-6 bg-gray-200 rounded w-1/3 mb-4" />
              <div className="h-4 bg-gray-200 rounded w-2/3" />
            </div>
          ) : error ? (
            <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
              <h2 className="font-semibold mb-1">Something went wrong</h2>
              <p className="text-sm">{error}</p>
            </div>
          ) : (
            <div className="space-y-8">
              <div className="bg-white rounded-lg shadow p-6">
                <div className="flex flex-col md:flex-row md:items-center gap-4 justify-between">
                  <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm text-gray-600 mb-2">
                        Search jobs
                      </label>
                      <input
                        list="job-suggestions"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        className="w-full rounded border border-gray-300 px-3 py-2"
                        placeholder="Type a job id (or partial)…"
                      />
                      <datalist id="job-suggestions">
                        {completed.slice(0, 50).map((j) => (
                          <option
                            key={j.id}
                            value={j.id}
                          >{`${j.id} · ${formatDate(j.created_at)}`}</option>
                        ))}
                      </datalist>
                      <div className="mt-1 text-xs text-gray-400">
                        Pick from suggestions or paste a job id.
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 mb-2">
                        Filter by date
                      </label>
                      <input
                        type="date"
                        value={filterDate}
                        onChange={(e) => setFilterDate(e.target.value)}
                        className="w-full rounded border border-gray-300 px-3 py-2"
                      />
                      <div className="mt-1 text-xs text-gray-400">
                        Uses your browser’s calendar picker.
                      </div>
                    </div>
                  </div>
                  <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-4">
                    <label className="block text-sm text-gray-600">
                      Baseline
                      <select
                        className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
                        value={leftId}
                        onChange={(e) => setLeftId(e.target.value)}
                      >
                        <option value="">Select…</option>
                        {completed.map((j) => (
                          <option key={j.id} value={j.id}>
                            {formatDate(j.created_at)} · {j.id.slice(0, 8)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block text-sm text-gray-600">
                      Compare to
                      <select
                        className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
                        value={rightId}
                        onChange={(e) => setRightId(e.target.value)}
                      >
                        <option value="">Select…</option>
                        {completed.map((j) => (
                          <option key={j.id} value={j.id}>
                            {formatDate(j.created_at)} · {j.id.slice(0, 8)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>

                <div className="mt-4 text-sm text-gray-500">
                  {completed.length} completed analysis job(s) found.
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-lg font-semibold text-dark mb-3">
                    Trend: Retirement Success Rate
                  </h2>
                  {trend.length === 0 ? (
                    <p className="text-sm text-gray-500">
                      No retirement success-rate data found yet.
                    </p>
                  ) : (
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={trend}>
                          <CartesianGrid strokeDasharray="3 3" />
                          <XAxis
                            dataKey="ts"
                            type="number"
                            domain={["dataMin", "dataMax"]}
                            tickFormatter={(value) => {
                              const d = new Date(Number(value));
                              return trendUseTimeAxis
                                ? d.toLocaleTimeString("en-US", {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                  })
                                : d.toLocaleDateString("en-US", {
                                    month: "short",
                                    day: "numeric",
                                  });
                            }}
                          />
                          <YAxis domain={[0, 100]} />
                          <Tooltip
                            labelFormatter={(value) =>
                              new Date(Number(value)).toLocaleString("en-US", {
                                month: "short",
                                day: "numeric",
                                year: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })
                            }
                          />
                          <Line
                            type="monotone"
                            dataKey="successRate"
                            stroke="#627eff"
                            strokeWidth={2}
                            dot={{ r: 3 }}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>

                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-lg font-semibold text-dark mb-3">
                    What changed since last run
                  </h2>
                  {completed.length < 2 ? (
                    <p className="text-sm text-gray-500">
                      Run at least two analyses to see changes over time.
                    </p>
                  ) : (
                    <div className="text-sm text-gray-600 space-y-2">
                      <div>
                        Baseline:{" "}
                        <Link
                          className="text-primary hover:underline"
                          href={`/analysis?job_id=${(leftJob ?? completed[1]).id}`}
                        >
                          {(leftJob ?? completed[1]).id.slice(0, 8)}
                        </Link>{" "}
                        · {formatDate((leftJob ?? completed[1]).created_at)}
                      </div>
                      <div>
                        Compare to:{" "}
                        <Link
                          className="text-primary hover:underline"
                          href={`/analysis?job_id=${(rightJob ?? completed[0]).id}`}
                        >
                          {(rightJob ?? completed[0]).id.slice(0, 8)}
                        </Link>{" "}
                        · {formatDate((rightJob ?? completed[0]).created_at)}
                      </div>
                      <div className="pt-2 border-t border-gray-200">
                        {(() => {
                          const baseline = leftJob ?? completed[1];
                          const compare = rightJob ?? completed[0];
                          const d = diffRecommendations(baseline, compare);
                          const added = d.added.length;
                          const removed = d.removed.length;
                          const baseSr = getSuccessRate(baseline);
                          const compSr = getSuccessRate(compare);
                          return (
                            <ul className="list-disc ml-6 space-y-1">
                              <li>Recommendations added: {added}</li>
                              <li>Recommendations removed: {removed}</li>
                              <li>
                                Retirement success rate:{" "}
                                {baseSr != null ? baseSr.toFixed(1) : "-"}% →{" "}
                                {compSr != null ? compSr.toFixed(1) : "-"}%
                              </li>
                            </ul>
                          );
                        })()}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="bg-white rounded-lg shadow p-6">
                <h2 className="text-lg font-semibold text-dark mb-4">
                  Side-by-side comparison
                </h2>

                {!leftJob || !rightJob ? (
                  <p className="text-sm text-gray-500">
                    Select two jobs above to compare.
                  </p>
                ) : (
                  <div className="space-y-6">
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <div className="border border-gray-200 rounded-lg p-4">
                        <div className="text-xs text-gray-500 mb-1">Baseline</div>
                        <div className="font-semibold text-gray-900">
                          {leftJob.id}
                        </div>
                        <div className="text-sm text-gray-500">
                          {formatDate(leftJob.created_at)}
                        </div>
                        <Link
                          className="inline-block mt-3 text-primary hover:underline text-sm"
                          href={`/analysis?job_id=${leftJob.id}`}
                        >
                          Open analysis
                        </Link>
                      </div>
                      <div className="border border-gray-200 rounded-lg p-4">
                        <div className="text-xs text-gray-500 mb-1">Compare to</div>
                        <div className="font-semibold text-gray-900">
                          {rightJob.id}
                        </div>
                        <div className="text-sm text-gray-500">
                          {formatDate(rightJob.created_at)}
                        </div>
                        <Link
                          className="inline-block mt-3 text-primary hover:underline text-sm"
                          href={`/analysis?job_id=${rightJob.id}`}
                        >
                          Open analysis
                        </Link>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      <div className="border border-gray-200 rounded-lg p-4">
                        <h3 className="font-semibold text-gray-900 mb-2">
                          Retirement success rate
                        </h3>
                        <div className="text-sm text-gray-600">
                          {leftSr?.toFixed(1) ?? "-"}% → {rightSr?.toFixed(1) ?? "-"}%
                          {leftSr != null && rightSr != null && (
                            <span className="ml-2 text-gray-500">
                              ({(rightSr - leftSr).toFixed(1)} pts)
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="border border-gray-200 rounded-lg p-4">
                        <h3 className="font-semibold text-gray-900 mb-2">
                          Recommendation changes
                        </h3>
                        <div className="text-sm text-gray-600">
                          Added: {recDiff.added.length} · Removed: {recDiff.removed.length}
                        </div>
                      </div>
                    </div>

                    <div className="border border-gray-200 rounded-lg p-4">
                      <h3 className="font-semibold text-gray-900 mb-3">
                        Asset class allocation (approx.)
                      </h3>
                      {allAllocKeys.length === 0 ? (
                        <p className="text-sm text-gray-500">
                          Missing chart data for one or both jobs.
                        </p>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="w-full border-collapse">
                            <thead className="bg-gray-800 text-gray-100">
                              <tr>
                                <th className="p-3 text-left border border-gray-700">
                                  Asset class
                                </th>
                                <th className="p-3 text-right border border-gray-700">
                                  Baseline
                                </th>
                                <th className="p-3 text-right border border-gray-700">
                                  Compare
                                </th>
                                <th className="p-3 text-right border border-gray-700">
                                  Δ
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {allAllocKeys.map((k) => {
                                const aRaw = safeNumber(leftAlloc[k]);
                                const bRaw = safeNumber(rightAlloc[k]);
                                const a = Math.round(aRaw * 10) / 10;
                                const b = Math.round(bRaw * 10) / 10;
                                const d = Math.round((b - a) * 10) / 10;
                                return (
                                  <tr key={k} className="hover:bg-gray-50">
                                    <td className="p-3 border border-gray-700">
                                      {titleCase(k)}
                                    </td>
                                    <td className="p-3 border border-gray-700 text-right">
                                      {a.toFixed(1)}%
                                    </td>
                                    <td className="p-3 border border-gray-700 text-right">
                                      {b.toFixed(1)}%
                                    </td>
                                    <td className="p-3 border border-gray-700 text-right">
                                      {d >= 0 ? "+" : ""}
                                      {d.toFixed(1)}%
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>

                    <div className="border border-gray-200 rounded-lg p-4">
                      <h3 className="font-semibold text-gray-900 mb-3">
                        Recommendation diff (text)
                      </h3>
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        <div>
                          <div className="text-sm font-semibold text-gray-800 mb-2">
                            Added
                          </div>
                          {recDiff.added.length === 0 ? (
                            <div className="text-sm text-gray-500">None</div>
                          ) : (
                            <ul className="list-disc ml-6 text-sm text-gray-600 space-y-1">
                              {recDiff.added.slice(0, 10).map((x) => (
                                <li key={x}>{x}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-gray-800 mb-2">
                            Removed
                          </div>
                          {recDiff.removed.length === 0 ? (
                            <div className="text-sm text-gray-500">None</div>
                          ) : (
                            <ul className="list-disc ml-6 text-sm text-gray-600 space-y-1">
                              {recDiff.removed.slice(0, 10).map((x) => (
                                <li key={x}>{x}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      </div>
                      {(recDiff.added.length > 10 || recDiff.removed.length > 10) && (
                        <div className="mt-3 text-xs text-gray-500">
                          Showing up to 10 added/removed items.
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </Layout>
    </>
  );
}
