import { useEffect, useState } from "react";

/**
 * Shape of a toast message used throughout the toast system.
 *
 * @property {string} id
 * Unique identifier for the toast (used for rendering and removal).
 *
 * @property {'success' | 'error' | 'info'} type
 * Visual style and semantic category of the toast.
 *
 * @property {string} message
 * Main text content shown inside the toast.
 *
 * @property {number} [duration]
 * Optional time (ms) before the toast auto-dismisses. Defaults to 3000ms.
 */
export interface ToastMessage {
  id: string;
  type: "success" | "error" | "info";
  message: string;
  duration?: number;
}

/**
 * Props for the individual Toast component.
 *
 * @property {ToastMessage} toast
 * The toast data to render.
 *
 * @property {(id: string) => void} onClose
 * Callback triggered when the toast should be removed.
 */
interface ToastProps {
  toast: ToastMessage;
  onClose: (id: string) => void;
}

/**
 * Toast is a single notification element with:
 * - Background colour based on `type`
 * - Icon based on `type`
 * - Auto-dismiss timer
 * - Manual close button
 */
const Toast = ({ toast, onClose }: ToastProps) => {
  // Set up auto-dismiss behaviour using the toast duration (default 3 seconds).
  useEffect(() => {
    const timer = setTimeout(() => {
      onClose(toast.id);
    }, toast.duration || 3000);

    return () => clearTimeout(timer);
  }, [toast, onClose]);

  // Background colour based on toast type
  const bgColor = {
    success: "bg-green-500",
    error: "bg-red-500",
    info: "bg-blue-500",
  }[toast.type];

  // Icon based on toast type
  const icon = {
    success: "✓",
    error: "✕",
    info: "ℹ",
  }[toast.type];

  return (
    <div
      className={`
        ${bgColor}
        text-white px-4 py-3 rounded-lg shadow-lg
        flex items-center gap-3
        animate-slide-in
      `}
    >
      <span className="text-xl">{icon}</span>
      <p className="flex-1">{toast.message}</p>
      <button
        onClick={() => onClose(toast.id)}
        className="hover:opacity-80 transition-opacity"
        aria-label="Dismiss notification"
      >
        ✕
      </button>
    </div>
  );
};

/**
 * ToastContainer is a global overlay that listens for `toast` CustomEvents
 * on `window` and renders a stack of Toasts in the top-right corner.
 *
 * Usage:
 * - Render <ToastContainer /> once near the root of your app (e.g. in Layout).
 * - Trigger toasts anywhere with `showToast(type, message, duration)`.
 */
export const ToastContainer = () => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
    /**
     * Event handler for incoming toast events.
     * Converts the event detail into a full ToastMessage with a generated id.
     */
    const handleToast = (event: Event) => {
      const customEvent = event as CustomEvent<Omit<ToastMessage, "id">>;
      const newToast: ToastMessage = {
        ...customEvent.detail,
        id: Date.now().toString(),
      };
      setToasts((prev) => [...prev, newToast]);
    };

    window.addEventListener("toast", handleToast as EventListener);
    return () =>
      window.removeEventListener("toast", handleToast as EventListener);
  }, []);

  /**
   * Removes a toast with the given id from the container state.
   */
  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onClose={removeToast} />
      ))}
    </div>
  );
};

/**
 * Helper function to dispatch a toast event globally.
 *
 * Call this from anywhere in client-side code to show a toast,
 * assuming <ToastContainer /> is mounted somewhere in the React tree.
 *
 * @param {'success' | 'error' | 'info'} type - Category/visual style of the toast.
 * @param {string} message - Text content to display in the toast.
 * @param {number} [duration] - Optional duration in ms before auto-dismiss.
 */
export const showToast = (
  type: "success" | "error" | "info",
  message: string,
  duration?: number
) => {
  window.dispatchEvent(
    new CustomEvent<Omit<ToastMessage, "id">>("toast", {
      detail: { type, message, duration },
    })
  );
};
