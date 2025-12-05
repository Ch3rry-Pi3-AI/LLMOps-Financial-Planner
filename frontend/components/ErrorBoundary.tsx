import React, { Component, ErrorInfo, ReactNode } from 'react';

/**
 * Props for the ErrorBoundary component.
 *
 * @property {ReactNode} children
 * The child React nodes that this boundary should wrap and monitor for errors.
 */
interface Props {
  children: ReactNode;
}

/**
 * Internal state for the ErrorBoundary component.
 *
 * @property {boolean} hasError
 * Flag indicating whether an error has been caught.
 *
 * @property {Error | null} error
 * The error instance that was caught, if any.
 */
interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * ErrorBoundary is a React class component that catches runtime errors
 * in its descendant component tree and displays a fallback UI.
 *
 * It prevents the entire application from crashing by:
 * - Updating internal state when an error is thrown
 * - Rendering a user-friendly error screen
 * - Providing basic error details for debugging
 *
 * Wrap this around parts of the app that may throw at render-time, in
 * lifecycle methods, or in constructors of child components.
 */
export default class ErrorBoundary extends Component<Props, State> {
  /**
   * Initial state: no error has been detected.
   */
  public state: State = {
    hasError: false,
    error: null,
  };

  /**
   * React lifecycle method invoked after an error has been thrown
   * by a descendant component.
   *
   * This method is used to update state so that the next render
   * shows the fallback UI instead of the broken subtree.
   *
   * @param {Error} error - The error that was thrown.
   * @returns {State} Updated state indicating an error has occurred.
   */
  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  /**
   * React lifecycle method for side-effects when an error is caught.
   *
   * Use this hook to log errors to an external service (e.g. Sentry,
   * Datadog) or to the browser console for debugging.
   *
   * @param {Error} error - The error that was thrown.
   * @param {ErrorInfo} errorInfo - Component stack trace information.
   */
  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Replace this with integration to your logging/monitoring provider if needed.
    console.error('Error boundary caught:', error, errorInfo);
  }

  /**
   * Resets the error boundary state and redirects the user.
   *
   * Currently this:
   * - Clears the error state
   * - Navigates to the `/dashboard` route using a full page reload
   *
   * This is useful when the app is in an unknown/broken state and
   * a fresh load is safer than attempting to re-render in place.
   */
  private handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = '/dashboard';
  };

  /**
   * Renders either the fallback error UI (if an error has been caught),
   * or the wrapped children (normal execution path).
   */
  public render() {
    const { hasError, error } = this.state;

    if (hasError) {
      return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
          <div className="text-center max-w-md">
            <h1 className="text-4xl font-bold text-red-500 mb-4">
              Something went wrong
            </h1>
            <p className="text-gray-600 mb-6">
              An unexpected error occurred. The error has been logged and we&apos;ll look into it.
            </p>

            {/* Optional: show the error details for debugging (primarily dev use) */}
            {error && (
              <details className="mb-6 text-left bg-gray-100 p-4 rounded-lg">
                <summary className="cursor-pointer font-medium">
                  Error details
                </summary>
                <pre className="mt-2 text-xs overflow-auto">
                  {error.toString()}
                </pre>
              </details>
            )}

            <button
              onClick={this.handleReset}
              className="bg-primary hover:bg-blue-600 text-white px-6 py-3 rounded-lg transition-colors"
            >
              Return to Dashboard
            </button>
          </div>
        </div>
      );
    }

    // Normal render path: no error has occurred, render children as-is.
    return this.props.children;
  }
}
