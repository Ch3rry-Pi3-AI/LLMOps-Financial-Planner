/**
 * Advisor Team Page
 *
 * This page introduces the user's AI advisory agents and provides an
 * "Analysis Center" where the user can:
 *  - Trigger a new portfolio analysis job
 *  - See live progress feedback (stages + active agents)
 *  - View a short history of recent analyses and their status
 *
 * It coordinates with the backend async job system and emits custom events
 * so other parts of the app can react to analysis lifecycle changes.
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

/**
 * Agent
 *
 * Describes a single AI "team member" shown in the UI, including display
 * icon, name, role, and colours used for styling and active-state highlights.
 */
interface Agent {
  icon: string;
  name: string;
  role: string;
  description: string;
  color: string;
  bgColor: string;
}

/**
 * Job
 *
 * Represents a backend analysis job:
 *  - id: unique identifier for the job
 *  - created_at: timestamp when the job was created
 *  - status: current job status
 *  - job_type: type/category of the job
 */
interface Job {
  id: string;
  created_at: string;
  status: string;
  job_type: string;
}

/**
 * AnalysisProgress
 *
 * Local representation of the current analysis state used to drive the
 * progress UI, including:
 *  - stage: coarse-grained step in the analysis pipeline
 *  - message: user-facing description
 *  - activeAgents: which agents are currently "active" for highlighting
 *  - error: optional error message when a failure occurs
 */
interface AnalysisProgress {
  stage: "idle" | "starting" | "planner" | "parallel" | "completing" | "complete" | "error";
  message: string;
  activeAgents: string[];
  error?: string;
}

/**
 * Static list of AI agents displayed on the page.
 * These map to different roles in the analysis pipeline.
 */
const agents: Agent[] = [
  {
    icon: "🎯",
    name: "Financial Planner",
    role: "Orchestrator",
    description: "Coordinates your financial analysis",
    color: "text-ai-accent",
    bgColor: "bg-ai-accent",
  },
  {
    icon: "📊",
    name: "Portfolio Analyst",
    role: "Reporter",
    description: "Analyzes your holdings and performance",
    color: "text-primary",
    bgColor: "bg-primary",
  },
  {
    icon: "📈",
    name: "Chart Specialist",
    role: "Charter",
    description: "Visualizes your portfolio composition",
    color: "text-green-600",
    bgColor: "bg-green-600",
  },
  {
    icon: "🎯",
    name: "Retirement Planner",
    role: "Retirement",
    description: "Projects your retirement readiness",
    color: "text-accent",
    bgColor: "bg-accent",
  },
];

/**
 * AdvisorTeam
 *
 * Main page component that:
 *  - Displays the AI advisory team cards
 *  - Starts a new portfolio analysis job on demand
 *  - Polls the backend for job status updates
 *  - Shows a progress bar and active agents
 *  - Lists a few of the most recent analysis jobs
 */
export default function AdvisorTeam() {
  const router = useRouter();
  const { getToken } = useAuth();

  // Recent analysis jobs fetched from the backend
  const [jobs, setJobs] = useState<Job[]>([]);

  // Whether a new analysis has been started and is currently running
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // ID of the currently running job (if any)
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);

  // User-facing progress state for the current analysis
  const [progress, setProgress] = useState<AnalysisProgress>({
    stage: "idle",
    message: "",
    activeAgents: [],
  });

  // Interval handle used to poll the backend for job status updates
  const [pollInterval, setPollInterval] = useState<NodeJS.Timeout | null>(null);

  /**
   * Initial fetch of previous jobs when the page first mounts.
   */
  useEffect(() => {
    fetchJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Effect to manage polling of the current job's status.
   *
   * When `currentJobId` is set and there is no existing interval:
   *  - Start a polling interval that checks the job status every 2 seconds
   *  - Stop polling when the job completes or fails
   *  - Emit lifecycle events for other parts of the app
   */
  useEffect(() => {
    const checkJobStatusLocal = async (jobId: string) => {
      try {
        const token = await getToken();
        const response = await fetch(`${API_URL}/api/jobs/${jobId}`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (response.ok) {
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

            // Notify other components so they can refresh state
            emitAnalysisCompleted(jobId);

            // Refresh our local job history
            fetchJobs();

            // Redirect the user to the detailed analysis page
            setTimeout(() => {
              router.push(`/analysis?job_id=${jobId}`);
            }, 1500);
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

            // Emit failure event
            emitAnalysisFailed(jobId, job.error);

            setIsAnalyzing(false);
            setCurrentJobId(null);
          }
        }
      } catch (error) {
        console.error("Error checking job status:", error);
      }
    };

    // Start polling when a job is active and not already being polled
    if (currentJobId && !pollInterval) {
      const interval = setInterval(() => {
        checkJobStatusLocal(currentJobId);
      }, 2000);
      setPollInterval(interval);
    }

    // Clean up polling on unmount or when dependencies change
    return () => {
      if (pollInterval) {
        clearInterval(pollInterval);
        setPollInterval(null);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentJobId, pollInterval, router]);

  /**
   * fetchJobs
   *
   * Loads the list of previous analysis jobs from the backend.
   */
  const fetchJobs = async () => {
    try {
      const token = await getToken();
      const response = await fetch(`${API_URL}/api/jobs`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (response.ok) {
        const data = await response.json();
        setJobs(data.jobs || []);
      }
    } catch (error) {
      console.error("Error fetching jobs:", error);
    }
  };

  /**
   * startAnalysis
   *
   * Starts a new portfolio analysis job via the backend API and sets up
   * local progress state & job polling.
   */
  const startAnalysis = async () => {
    setIsAnalyzing(true);
    setProgress({
      stage: "starting",
      message: "Initializing analysis...",
      activeAgents: [],
    });

    try {
      const token = await getToken();
      const response = await fetch(`${API_URL}/api/analyze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          analysis_type: "portfolio",
          options: {},
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setCurrentJobId(data.job_id);

        // Notify the rest of the app that a new job has started
        emitAnalysisStarted(data.job_id);

        // Move progress into the planner stage
        setProgress({
          stage: "planner",
          message: "Financial Planner coordinating analysis...",
          activeAgents: ["Financial Planner"],
        });

        // Transition to the parallel agent stage after a short delay
        setTimeout(() => {
          setProgress({
            stage: "parallel",
            message: "Agents working in parallel...",
            activeAgents: ["Portfolio Analyst", "Chart Specialist", "Retirement Planner"],
          });
        }, 5000);
      } else {
        throw new Error("Failed to start analysis");
      }
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

  /**
   * formatDate
   *
   * Formats an ISO date string into a short, human-readable string
   * (e.g. "Jan 12, 2025, 14:30").
   */
  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  /**
   * getStatusColor
   *
   * Maps a job status string to a Tailwind text colour class.
   */
  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "text-green-600";
      case "failed":
        return "text-red-500";
      case "running":
        return "text-blue-600";
      default:
        return "text-gray-500";
    }
  };

  /**
   * isAgentActive
   *
   * Returns true if the given agent is currently marked as active
   * in the progress state.
   */
  const isAgentActive = (agentName: string) => {
    return progress.activeAgents.includes(agentName);
  };

  return (
    <>
      <Head>
        <title>Advisor Team - Alex AI Financial Advisor</title>
      </Head>

      <Layout>
        <div className="min-h-screen bg-gray-50 py-8">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            {/* Intro card */}
            <div className="bg-white rounded-lg shadow px-8 py-6 mb-8">
              <h1 className="text-3xl font-bold text-dark mb-2">Your AI Advisory Team</h1>
              <p className="text-gray-600">
                Meet your team of specialized AI agents that work together to provide
                comprehensive financial analysis.
              </p>
            </div>

            {/* Agent cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              {agents.map((agent) => (
                <div
                  key={agent.name}
                  className={`bg-white rounded-lg shadow-lg p-6 relative overflow-hidden transition-all duration-300 ${
                    isAgentActive(agent.name) ? "ring-4 ring-ai-accent ring-opacity-50" : ""
                  }`}
                >
                  {isAgentActive(agent.name) && (
                    <div className="absolute inset-0 bg-gradient-to-br from-ai-accent/20 to-transparent animate-strong-pulse" />
                  )}
                  <div className="relative">
                    <div
                      className={`text-5xl mb-4 ${
                        isAgentActive(agent.name) ? "animate-strong-pulse" : ""
                      }`}
                    >
                      {agent.icon}
                    </div>
                    <h3 className={`text-xl font-semibold mb-1 ${agent.color}`}>
                      {agent.name}
                    </h3>
                    <p className="text-sm text-gray-500 mb-3">{agent.role}</p>
                    <p className="text-gray-600 text-sm">{agent.description}</p>

                    {isAgentActive(agent.name) && (
                      <div
                        className={`mt-4 inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold text-white ${agent.bgColor} animate-strong-pulse`}
                      >
                        <span className="mr-2">●</span>
                        Active
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Analysis Center card */}
            <div className="bg-white rounded-lg shadow px-8 py-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-2xl font-semibold text-dark">Analysis Center</h2>
                <button
                  onClick={startAnalysis}
                  disabled={isAnalyzing}
                  className={`px-8 py-4 rounded-lg font-semibold text-white transition-all ${
                    isAnalyzing
                      ? "bg-gray-400 cursor-not-allowed"
                      : "bg-ai-accent hover:bg-purple-700 shadow-lg hover:shadow-xl transform hover:-translate-y-0.5"
                  }`}
                >
                  {isAnalyzing ? "Analysis in Progress..." : "Start New Analysis"}
                </button>
              </div>

              {/* Live analysis progress UI */}
              {isAnalyzing && (
                <div className="mb-8 p-6 bg-gradient-to-r from-ai-accent/10 to-primary/10 rounded-lg border border-ai-accent/20">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-dark">Analysis Progress</h3>

                    {/* Animated dots while analysis is running */}
                    {progress.stage !== "error" && progress.stage !== "complete" && (
                      <div className="flex space-x-2">
                        <div className="w-3 h-3 bg-ai-accent rounded-full animate-strong-pulse" />
                        <div
                          className="w-3 h-3 bg-ai-accent rounded-full animate-strong-pulse"
                          style={{ animationDelay: "0.5s" }}
                        />
                        <div
                          className="w-3 h-3 bg-ai-accent rounded-full animate-strong-pulse"
                          style={{ animationDelay: "1s" }}
                        />
                      </div>
                    )}
                  </div>

                  <p
                    className={`text-sm mb-4 ${
                      progress.stage === "error" ? "text-red-600" : "text-gray-600"
                    }`}
                  >
                    {progress.message}
                  </p>

                  {/* Error details and retry button */}
                  {progress.stage === "error" && progress.error && (
                    <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                      <p className="text-sm text-red-800">{progress.error}</p>
                      <button
                        onClick={() => {
                          setIsAnalyzing(false);
                          setCurrentJobId(null);
                          setProgress({ stage: "idle", message: "", activeAgents: [] });
                        }}
                        className="mt-3 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm font-semibold"
                      >
                        Try Again
                      </button>
                    </div>
                  )}

                  {/* Progress bar (shown for all non-idle, non-error stages) */}
                  {progress.stage !== "idle" && progress.stage !== "error" && (
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-ai-accent h-2 rounded-full transition-all duration-1000"
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

              {/* Job history section */}
              <div>
                <h3 className="text-lg font-semibold text-dark mb-4">Previous Analyses</h3>

                {jobs.length === 0 ? (
                  <p className="text-gray-500 italic">
                    No previous analyses found. Start your first analysis above!
                  </p>
                ) : (
                  <div className="space-y-3">
                    {jobs.slice(0, 5).map((job) => (
                      <div
                        key={job.id}
                        className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
                      >
                        <div className="flex-1">
                          <p className="text-sm font-medium text-gray-900">
                            Analysis #{job.id.slice(0, 8)}
                          </p>
                          <p className="text-xs text-gray-500">
                            {formatDate(job.created_at)}
                          </p>
                        </div>

                        <div className="flex items-center space-x-4">
                          <span
                            className={`text-sm font-medium ${getStatusColor(job.status)}`}
                          >
                            {job.status.charAt(0).toUpperCase() + job.status.slice(1)}
                          </span>

                          {job.status === "completed" && (
                            <button
                              onClick={() =>
                                router.push(`/analysis?job_id=${job.id}`)
                              }
                              className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-blue-600 text-sm font-semibold"
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
