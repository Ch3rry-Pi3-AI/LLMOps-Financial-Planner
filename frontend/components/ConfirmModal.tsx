import { ReactNode } from "react";

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: string | ReactNode;
  confirmText?: string;
  cancelText?: string;
  confirmButtonClass?: string;
  onConfirm: () => void;
  onCancel: () => void;
  isProcessing?: boolean;
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = "Confirm",
  cancelText = "Cancel",
  confirmButtonClass = "bg-error hover:bg-error/90",
  onConfirm,
  onCancel,
  isProcessing = false,
}: ConfirmModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-border rounded-xl max-w-md w-full p-6 shadow-2xl">
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-foreground">{title}</h3>
        </div>

        <div className="mb-6 text-sm text-muted">{message}</div>

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={isProcessing}
            className="flex-1 bg-surface-2 hover:bg-surface-2/80 border border-border text-foreground px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            {cancelText}
          </button>

          <button
            onClick={onConfirm}
            disabled={isProcessing}
            className={`flex-1 text-white px-4 py-2 rounded-lg transition-colors disabled:opacity-50 ${confirmButtonClass}`}
          >
            {isProcessing ? "Processing..." : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
