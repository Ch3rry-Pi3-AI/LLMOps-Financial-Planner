import { useEffect, useState } from "react";

/**
 * Shape of a toast message used throughout the toast system.
 */
export interface ToastMessage {
  id: string;
  type: "success" | "error" | "info";
  message: string;
  duration?: number;
}

interface ToastProps {
  toast: ToastMessage;
  onClose: (id: string) => void;
}

const iconByType: Record<ToastMessage["type"], string> = {
  success: "✓",
  error: "✕",
  info: "i",
};

const accentByType: Record<ToastMessage["type"], string> = {
  success: "border-l-success",
  error: "border-l-error",
  info: "border-l-primary",
};

const Toast = ({ toast, onClose }: ToastProps) => {
  useEffect(() => {
    const timer = setTimeout(() => {
      onClose(toast.id);
    }, toast.duration || 3000);

    return () => clearTimeout(timer);
  }, [toast, onClose]);

  return (
    <div
      className={[
        "bg-surface border border-border border-l-4",
        accentByType[toast.type],
        "text-foreground px-4 py-3 rounded-lg shadow-lg",
        "flex items-center gap-3",
        "animate-slide-in",
      ].join(" ")}
    >
      <span className="text-sm font-semibold w-5 text-center text-muted">
        {iconByType[toast.type]}
      </span>
      <p className="flex-1 text-sm text-foreground">{toast.message}</p>
      <button
        onClick={() => onClose(toast.id)}
        className="text-muted hover:text-foreground transition-colors"
        aria-label="Dismiss notification"
      >
        ✕
      </button>
    </div>
  );
};

/**
 * ToastContainer is a global overlay that listens for `toast` CustomEvents.
 */
export const ToastContainer = () => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
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

export const showToast = (
  type: "success" | "error" | "info",
  message: string,
  duration?: number,
) => {
  window.dispatchEvent(
    new CustomEvent<Omit<ToastMessage, "id">>("toast", {
      detail: { type, message, duration },
    }),
  );
};
