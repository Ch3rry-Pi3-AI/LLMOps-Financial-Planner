/**
 * Event system for lightweight cross-component communication.
 *
 * This module defines:
 * - A set of strongly-typed event names for analysis workflows.
 * - A shared event payload interface (`AnalysisEventDetail`).
 * - Helper functions that emit CustomEvents from anywhere in the app.
 *
 * These events allow decoupled components (e.g. loaders, dashboards,
 * progress indicators) to react to analysis lifecycle changes without
 * direct prop drilling or global state.
 */

/**
 * Enumeration of event names for analysis lifecycle notifications.
 *
 * Components can subscribe using:
 * ```ts
 * window.addEventListener(AnalysisEvents.STARTED, handler)
 * ```
 */
export const AnalysisEvents = {
  STARTED: "analysis:started",
  COMPLETED: "analysis:completed",
  FAILED: "analysis:failed",
} as const;

/**
 * The standard payload structure included with every analysis event.
 *
 * @property jobId   - ID of the job that triggered the event.
 * @property timestamp - Time the event was emitted (ms since epoch).
 * @property status    - Optional status string ("completed", "failed", etc.).
 * @property error     - Optional error message for failed events.
 */
export interface AnalysisEventDetail {
  jobId: string;
  timestamp: number;
  status?: string;
  error?: string;
}

/**
 * Emit an event indicating that a new analysis job has started.
 *
 * @param jobId - ID of the job now in progress.
 *
 * Usage example:
 * ```ts
 * emitAnalysisStarted(job.id);
 * ```
 */
export function emitAnalysisStarted(jobId: string) {
  const event = new CustomEvent<AnalysisEventDetail>(AnalysisEvents.STARTED, {
    detail: {
      jobId,
      timestamp: Date.now(),
    },
  });

  window.dispatchEvent(event);
}

/**
 * Emit an event indicating that an analysis job has completed successfully.
 *
 * @param jobId - ID of the completed job.
 *
 * Components listening to this event may fetch updated results or refresh UI.
 */
export function emitAnalysisCompleted(jobId: string) {
  const event = new CustomEvent<AnalysisEventDetail>(AnalysisEvents.COMPLETED, {
    detail: {
      jobId,
      timestamp: Date.now(),
      status: "completed",
    },
  });

  window.dispatchEvent(event);
}

/**
 * Emit an event indicating that an analysis job has failed.
 *
 * @param jobId - ID of the failed job.
 * @param error - Optional error message describing the failure.
 *
 * Useful for triggering UI error messages or stopping loading indicators.
 */
export function emitAnalysisFailed(jobId: string, error?: string) {
  const event = new CustomEvent<AnalysisEventDetail>(AnalysisEvents.FAILED, {
    detail: {
      jobId,
      timestamp: Date.now(),
      status: "failed",
      error,
    },
  });

  window.dispatchEvent(event);
}
