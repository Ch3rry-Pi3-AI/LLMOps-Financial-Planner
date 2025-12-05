/**
 * Skeleton is a low-level loading placeholder used to indicate
 * that content is being fetched. It renders a pulsing grey block.
 *
 * @param {string} [className] - Additional Tailwind classes for size/shape control.
 */
export const Skeleton = ({
  className = "",
}: {
  className?: string;
}) => (
  <div
    className={`animate-pulse bg-gray-200 rounded ${className}`}
  />
);

/**
 * SkeletonText renders one or more horizontal text-like skeleton lines.
 *
 * @param {number} [lines=1] - Number of skeleton lines to render.
 */
export const SkeletonText = ({
  lines = 1,
}: {
  lines?: number;
}) => (
  <div className="space-y-2">
    {Array.from({ length: lines }).map((_, i) => (
      <Skeleton key={i} className="h-4 w-full" />
    ))}
  </div>
);

/**
 * SkeletonCard provides a card-shaped placeholder layout:
 * - A heading skeleton
 * - A few lines of text skeletons underneath
 *
 * Useful for loading dashboard cards or widgets.
 */
export const SkeletonCard = () => (
  <div className="bg-white rounded-lg shadow p-6">
    <Skeleton className="h-6 w-1/3 mb-4" />
    <SkeletonText lines={3} />
  </div>
);

/**
 * SkeletonTable renders a table-like skeleton layout,
 * useful for loading states of data tables or lists.
 *
 * @param {number} [rows=3] - Number of table rows to display.
 */
export const SkeletonTable = ({
  rows = 3,
}: {
  rows?: number;
}) => (
  <div className="bg-white rounded-lg shadow overflow-hidden">
    {/* Table Header */}
    <div className="border-b p-4">
      <Skeleton className="h-6 w-1/4" />
    </div>

    {/* Table Rows */}
    {Array.from({ length: rows }).map((_, i) => (
      <div
        key={i}
        className="border-b p-4 flex space-x-4"
      >
        <Skeleton className="h-4 w-1/4" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-4 w-1/6" />
        <Skeleton className="h-4 w-1/6" />
      </div>
    ))}
  </div>
);
