import { ReactNode } from 'react';

/**
 * Props for the ConfirmModal component.
 *
 * @property {boolean} isOpen  
 * Determines whether the modal is visible.
 *
 * @property {string} title  
 * Heading displayed at the top of the modal.
 *
 * @property {string | ReactNode} message  
 * Main modal content: may be plain text or any ReactNode.
 *
 * @property {string} [confirmText='Confirm']  
 * Label for the confirmation button.
 *
 * @property {string} [cancelText='Cancel']  
 * Label for the cancellation button.
 *
 * @property {string} [confirmButtonClass='bg-red-600 hover:bg-red-700']  
 * Tailwind classes applied to the confirm button to control its colour scheme.
 *
 * @property {() => void} onConfirm  
 * Callback fired when the user confirms the action.
 *
 * @property {() => void} onCancel  
 * Callback fired when the user cancels the action or dismisses the modal.
 *
 * @property {boolean} [isProcessing=false]  
 * If true, disables buttons and replaces confirm text with a loading state.
 */
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

/**
 * A reusable confirmation modal used for destructive or important actions.
 * Displays a title, descriptive message, and two actions:
 * a confirm button and a cancel button.  
 *
 * The modal appears centred with a dark backdrop, blocking interaction
 * with the rest of the interface until either action is triggered.
 */
export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  confirmButtonClass = 'bg-red-600 hover:bg-red-700',
  onConfirm,
  onCancel,
  isProcessing = false,
}: ConfirmModalProps) {
  // Do not render anything if the modal is closed
  if (!isOpen) return null;

  return (
    <div
      className="
        fixed inset-0
        bg-black bg-opacity-50
        flex items-center justify-center
        z-50 p-4
      "
    >
      <div className="bg-white rounded-lg max-w-md w-full p-6 shadow-xl">
        
        {/* Modal Header */}
        <div className="mb-4">
          <h3 className="text-xl font-bold text-dark">{title}</h3>
        </div>

        {/* Modal Message */}
        <div className="mb-6 text-gray-600">
          {message}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          {/* Cancel Button */}
          <button
            onClick={onCancel}
            disabled={isProcessing}
            className="
              flex-1 bg-gray-200 hover:bg-gray-300
              text-gray-700 px-4 py-2 rounded-lg
              transition-colors disabled:opacity-50
            "
          >
            {cancelText}
          </button>

          {/* Confirm Button */}
          <button
            onClick={onConfirm}
            disabled={isProcessing}
            className={`
              flex-1 text-white px-4 py-2
              rounded-lg transition-colors
              disabled:opacity-50
              ${confirmButtonClass}
            `}
          >
            {isProcessing ? 'Processing...' : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
