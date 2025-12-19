import { useEffect, useMemo, useState } from "react";
import Head from "next/head";
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

type Instrument = {
  symbol: string;
  name: string;
  instrument_type?: string | null;
};

type RangeKey = "1D" | "5D" | "1M" | "6M" | "YTD" | "1Y" | "5Y" | "MAX";

type SeriesResponse = {
  symbol: string;
  range: RangeKey;
  points: Array<{ t: number; c: number }>;
};

const RANGES: RangeKey[] = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX"];

export default function Market() {
  const { getToken } = useAuth();
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [symbol, setSymbol] = useState<string>("SPY");
  const [range, setRange] = useState<RangeKey>("1M");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [series, setSeries] = useState<SeriesResponse | null>(null);

  useEffect(() => {
    const loadInstruments = async () => {
      try {
        const token = await getToken();
        if (!token) return;
        const list = await apiRequest<Instrument[]>("/api/instruments", token);
        setInstruments(Array.isArray(list) ? list : []);
      } catch {
        // Non-blocking
      }
    };
    loadInstruments();
  }, [getToken]);

  useEffect(() => {
    const loadSeries = async () => {
      try {
        setLoading(true);
        setError(null);
        const token = await getToken();
        if (!token) return;
        const resp = await apiRequest<SeriesResponse>(
          `/api/market/timeseries?symbol=${encodeURIComponent(symbol)}&range=${encodeURIComponent(range)}`,
          token,
        );
        setSeries(resp);
      } catch (e) {
        setSeries(null);
        setError(e instanceof Error ? e.message : "Failed to load series");
      } finally {
        setLoading(false);
      }
    };
    if (symbol) loadSeries();
  }, [symbol, range, getToken]);

  const instrumentName = useMemo(() => {
    const match = instruments.find(
      (i) => i.symbol?.toUpperCase() === symbol.toUpperCase(),
    );
    return match?.name || "";
  }, [instruments, symbol]);

  const chartData = useMemo(() => {
    const pts = series?.points || [];
    return pts.map((p) => ({
      t: p.t,
      price: p.c,
    }));
  }, [series?.points]);

  const yDomain = useMemo(() => {
    if (chartData.length === 0) return ["auto", "auto"] as const;
    const vals = chartData.map((d) => d.price);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const pad = (max - min) * 0.05;
    return [min - pad, max + pad] as const;
  }, [chartData]);

  return (
    <>
      <Head>
        <title>Alex AI Financial Advisor - Market</title>
      </Head>

      <Layout>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <h1 className="text-3xl font-bold text-dark mb-2">Instrument Performance</h1>
          <p className="text-gray-500 mb-8">
            View a simple price chart powered by Polygon. Coverage depends on your Polygon plan
            (US equities are most reliable). Indices often use a prefix like <code>I:SPX</code>.
          </p>

          <div className="bg-white rounded-lg shadow p-6 mb-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-end">
              <label className="block text-sm text-gray-600">
                Ticker
                <input
                  list="instrument-suggestions"
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.trim().toUpperCase())}
                  placeholder="e.g. SPY"
                />
                <datalist id="instrument-suggestions">
                  {instruments.slice(0, 200).map((i) => (
                    <option
                      key={i.symbol}
                      value={i.symbol}
                    >{`${i.symbol} · ${i.name}`}</option>
                  ))}
                </datalist>
                {instrumentName && (
                  <div className="mt-2 text-xs text-gray-500">{instrumentName}</div>
                )}
              </label>

              <div>
                <div className="text-sm text-gray-600 mb-2">Range</div>
                <div className="flex flex-wrap gap-2">
                  {RANGES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => setRange(r)}
                      className={`px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${
                        range === r
                          ? "bg-primary text-white border-primary"
                          : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                      }`}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-start justify-between gap-6 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-dark">
                  {symbol} {instrumentName ? `· ${instrumentName}` : ""}
                </h2>
                <div className="text-sm text-gray-500">Range: {range}</div>
              </div>
              {loading && <div className="text-sm text-gray-500">Loading…</div>}
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg mb-4">
                <div className="font-semibold mb-1">Could not load series</div>
                <div className="text-sm">{error}</div>
              </div>
            )}

            {chartData.length === 0 ? (
              <div className="text-gray-500 text-center py-12">
                No data available for this ticker/range.
              </div>
            ) : (
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="t"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      tickFormatter={(value) =>
                        new Date(Number(value)).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: range === "1D" || range === "5D" ? "2-digit" : undefined,
                          minute: range === "1D" || range === "5D" ? "2-digit" : undefined,
                        })
                      }
                    />
                    <YAxis
                      domain={yDomain as [number, number]}
                      tickFormatter={(v) => Number(v).toFixed(2)}
                    />
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
                      formatter={(value: number | string) => [
                        typeof value === "number" ? value.toFixed(2) : String(value),
                        "Price",
                      ]}
                    />
                    <Line type="monotone" dataKey="price" stroke="#627eff" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      </Layout>
    </>
  );
}
