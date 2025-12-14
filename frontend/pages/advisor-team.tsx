/**
 * Advisor Team Page
 *
 * Shows the AI agent "team" and provides an Analysis Center to trigger and
 * monitor a new portfolio analysis job.
 */

import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useAuth } from "@clerk/nextjs";
import Layout from "../components/Layout";
import { API_URL } from "../lib/config";
import {
  emitAnalysisCompleted,
  emitAnalysisFailed,
  emitAnalysisStarted,
} from "../lib/events";
import Head from "next/head";

interface Agent {
  icon: string;
  name: string;
  role: string;
  description: string;
  color: string;
  bgColor: string;
}

interface Job {
  id: string;
  created_at: string;
  status: string;
  job_type: string;
}

interface AnalysisProgress {
  stage:
    | "idle"
    | "starting"
    | "planner"
    | "parallel"
    | "completing"
    | "complete"
    | "error";
  message: string;
  activeAgents: string[];
  error?: string;
}

const agents: Agent[] = [
  {
    icon: "🧠",
    name: "Financial Planner",
    role: "Orchestrator",
    description: "Coordinates your financial analysis end-to-end",
    color: "text-ai-accent",
    bgColor: "bg-ai-accent",
  },
  {
    icon: "📝",
    name: "Portfolio Analyst",
    role: "Reporter",
    description: "Writes clear portfolio insights and recommendations",
    color: "text-primary",
    bgColor: "bg-primary",
  },
  {
    icon: "📊",
    name: "Chart Specialist",
    role: "Charter",
    description: "Builds interactive portfolio charts and breakdowns",
    color: "text-success",
    bgColor: "bg-success",
  },
  {
    icon: "🧮",
    name: "Retirement Planner",
    role: "Retirement",
    description: "Projects retirement readiness and scenarios",
    color: "text-accent",
    bgColor: "bg-accent",
  },
];

export default function AdvisorTeam() {
  const router = useRouter();
  const { getToken } = useAuth();

  const [jobs, setJobs] = useState<Job[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<AnalysisProgress>({
    stage: "idle",
    message: "",
    activeAgents: [],
  });
  const [pollInterval, setPollInterval] = useState<NodeJS.Timeout | null>(null);

  useEffect(() => {
    fetchJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const checkJobStatusLocal = async (jobId: string) => {
      try {
        const token = await getToken();
        const response = await fetch(`${API_URL}/api/jobs/${jobId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (!response.ok) return;
        const job = await response.json();

        if (job.status === "completed") {
          setProgress({
            stage: "complete",
            message: "Analysis complete!",
            activeAgents: [],
          });

          if (pollInterval) {
            clearInterval(pollInterval);
            setPollInterval(null);
          }

          emitAnalysisCompleted(jobId);
          fetchJobs();

          setTimeout(() => {
            router.push(`/analysis?job_id=${jobId}`);
          }, 900);
        } else if (job.status === "failed") {
          setProgress({
            stage: "error",
            message: "Analysis failed",
            activeAgents: [],
            error: job.error || "Analysis encountered an error",
          });

          if (pollInterval) {
            clearInterval(pollInterval);
            setPollInterval(null);
          }

          emitAnalysisFailed(jobId, job.error);
          setIsAnalyzing(false);
          setCurrentJobId(null);
        }
      } catch (error) {
        console.error("Error checking job status:", error);
      }
    };

    if (currentJobId && !pollInterval) {
      const interval = setInterval(() => {
        checkJobStatusLocal(currentJobId);
      }, 2000);
      setPollInterval(interval);
    }

    return () => {
      if (pollInterval) {
        clearInterval(pollInterval);
        setPollInterval(null);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentJobId, pollInterval, router]);

  const fetchJobs = async () => {
    try {
      const token = await getToken();
      const response = await fetch(`${API_URL}/api/jobs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) return;
      const data = await response.json();
      setJobs(data.jobs || []);
    } catch (error) {
      console.error("Error fetching jobs:", error);
    }
  };

  const startAnalysis = async () => {
    try {
      setIsAnalyzing(true);
      setProgress({ stage: "starting", message: "Starting analysis...", activeAgents: [] });

      const token = await getToken();
      const response = await fetch(`${API_URL}/api/analyze`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ analysis_type: "portfolio" }),
      });

      if (!response.ok) throw new Error("Failed to start analysis");
      const data = await response.json();

      const jobId = data.job_id || data.id;
      if (!jobId) throw new Error("Backend did not return a job id");

      setCurrentJobId(jobId);
      emitAnalysisStarted(jobId);

      setTimeout(() => {
        setProgress({
          stage: "planner",
          message: "Planner agent is preparing tasks...",
          activeAgents: ["Financial Planner"],
        });
      }, 600);

      setTimeout(() => {
        setProgress({
          stage: "parallel",
          message: "Running specialist agents in parallel...",
          activeAgents: ["Portfolio Analyst", "Chart Specialist", "Retirement Planner"],
        });
      }, 4500);

      setTimeout(() => {
        setProgress({
          stage: "completing",
          message: "Finalizing results...",
          activeAgents: ["Financial Planner"],
        });
      }, 9500);
    } catch (error) {
      console.error("Error starting analysis:", error);
      setProgress({
        stage: "error",
        message: "Failed to start analysis",
        activeAgents: [],
        error: error instanceof Error ? error.message : "Unknown error",
      });
      setIsAnalyzing(false);
      setCurrentJobId(null);
    }
  };

  const formatDate = (dateString: string) =>
    new Date(dateString).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "text-success";
      case "failed":
        return "text-error";
      case "running":
        return "text-primary";
      default:
        return "text-muted-2";
    }
  };

  const isAgentActive = (agentName: string) => progress.activeAgents.includes(agentName);

  return (
    <>
      <Head>
        <title>Advisor Team - Alex AI Financial Advisor</title>
      </Head>

      <Layout>
        <div className="min-h-screen bg-background py-8">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="bg-surface border border-border rounded-xl px-8 py-6 mb-8 shadow">
              <h1 className="text-3xl font-bold text-foreground mb-2 tracking-tight">
                Your AI Advisory Team
              </h1>
              <p className="text-muted">
                Launch an analysis and watch the agents collaborate in real time.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              {agents.map((agent) => (
                <div
                  key={agent.name}
                  className={`bg-surface border border-border rounded-xl p-6 relative overflow-hidden transition-all duration-300 shadow ${
                    isAgentActive(agent.name)
                      ? "ring-2 ring-focus-ring ring-opacity-70"
                      : ""
                  }`}
                >
                  {isAgentActive(agent.name) && (
                    <div className="absolute inset-0 bg-gradient-to-br from-primary/10 to-transparent animate-strong-pulse" />
                  )}
                  <div className="relative">
                    <div className={`text-4xl mb-4 ${isAgentActive(agent.name) ? "animate-strong-pulse" : ""}`}>
                      {agent.icon}
                    </div>
                    <h3 className={`text-lg font-semibold mb-1 ${agent.color}`}>
                      {agent.name}
                    </h3>
                    <p className="text-xs text-muted-2 mb-3">{agent.role}</p>
                    <p className="text-sm text-muted">{agent.description}</p>

                    {isAgentActive(agent.name) && (
                      <div className={`mt-4 inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold text-white ${agent.bgColor} animate-strong-pulse`}>
                        <span className="mr-2">●</span>
                        Active
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="bg-surface border border-border rounded-xl px-8 py-6 shadow">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-2xl font-semibold text-foreground tracking-tight">
                  Analysis Center
                </h2>
                <button
                  onClick={startAnalysis}
                  disabled={isAnalyzing}
                  className={`px-6 py-3 rounded-lg font-semibold text-white transition-all ${
                    isAnalyzing
                      ? "bg-surface-2 text-muted cursor-not-allowed border border-border"
                      : "bg-primary hover:bg-primary/90 shadow-lg"
                  }`}
                >
                  {isAnalyzing ? "Analysis in Progress..." : "Start New Analysis"}
                </button>
              </div>

              {isAnalyzing && (
                <div className="mb-8 p-6 bg-surface-2 rounded-xl border border-border">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-foreground">
                      Analysis Progress
                    </h3>

                    {progress.stage !== "error" && progress.stage !== "complete" && (
                      <div className="flex space-x-2">
                        <div className="w-2.5 h-2.5 bg-primary rounded-full animate-strong-pulse" />
                        <div
                          className="w-2.5 h-2.5 bg-primary rounded-full animate-strong-pulse"
                          style={{ animationDelay: "0.35s" }}
                        />
                        <div
                          className="w-2.5 h-2.5 bg-primary rounded-full animate-strong-pulse"
                          style={{ animationDelay: "0.7s" }}
                        />
                      </div>
                    )}
                  </div>

                  <p className={`text-sm mb-4 ${progress.stage === "error" ? "text-error" : "text-muted"}`}>
                    {progress.message}
                  </p>

                  {progress.stage === "error" && progress.error && (
                    <div className="mt-4 p-4 bg-error/10 border border-error/30 rounded-lg">
                      <p className="text-sm text-error">{progress.error}</p>
                      <button
                        onClick={() => {
                          setIsAnalyzing(false);
                          setCurrentJobId(null);
                          setProgress({ stage: "idle", message: "", activeAgents: [] });
                        }}
                        className="mt-3 px-4 py-2 bg-error text-white rounded-lg hover:bg-error/90 text-sm font-semibold"
                      >
                        Try Again
                      </button>
                    </div>
                  )}

                  {progress.stage !== "idle" && progress.stage !== "error" && (
                    <div className="w-full bg-surface rounded-full h-2 border border-border overflow-hidden">
                      <div
                        className="bg-primary h-2 rounded-full transition-all duration-1000"
                        style={{
                          width:
                            progress.stage === "starting"
                              ? "10%"
                              : progress.stage === "planner"
                                ? "30%"
                                : progress.stage === "parallel"
                                  ? "70%"
                                  : progress.stage === "completing"
                                    ? "90%"
                                    : "100%",
                        }}
                      />
                    </div>
                  )}
                </div>
              )}

              <div>
                <h3 className="text-lg font-semibold text-foreground mb-4">
                  Previous Analyses
                </h3>

                {jobs.length === 0 ? (
                  <p className="text-muted italic">
                    No previous analyses found. Start your first analysis above!
                  </p>
                ) : (
                  <div className="space-y-3">
                    {jobs.slice(0, 5).map((job) => (
                      <div
                        key={job.id}
                        className="flex items-center justify-between p-4 bg-surface-2 border border-border rounded-lg hover:bg-surface-2/80 transition-colors"
                      >
                        <div className="flex-1">
                          <p className="text-sm font-medium text-foreground">
                            Analysis #{job.id.slice(0, 8)}
                          </p>
                          <p className="text-xs text-muted-2">
                            {formatDate(job.created_at)}
                          </p>
                        </div>

                        <div className="flex items-center space-x-4">
                          <span className={`text-sm font-medium ${getStatusColor(job.status)}`}>
                            {job.status.charAt(0).toUpperCase() + job.status.slice(1)}
                          </span>

                          {job.status === "completed" && (
                            <button
                              onClick={() => router.push(`/analysis?job_id=${job.id}`)}
                              className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 text-sm font-semibold"
                            >
                              View
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </Layout>
    </>
  );
}
