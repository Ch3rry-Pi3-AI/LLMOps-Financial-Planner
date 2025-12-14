/**
 * Skeleton is a low-level loading placeholder used to indicate
 * that content is being fetched. It renders a pulsing block.
 */
export const Skeleton = ({ className = "" }: { className?: string }) => (
  <div className={`animate-pulse bg-surface-2 rounded ${className}`} />
);

export const SkeletonText = ({ lines = 1 }: { lines?: number }) => (
  <div className="space-y-2">
    {Array.from({ length: lines }).map((_, i) => (
      <Skeleton key={i} className="h-4 w-full" />
    ))}
  </div>
);

export const SkeletonCard = () => (
  <div className="bg-surface border border-border rounded-lg shadow p-6">
    <Skeleton className="h-6 w-1/3 mb-4" />
    <SkeletonText lines={3} />
  </div>
);

export const SkeletonTable = ({ rows = 3 }: { rows?: number }) => (
  <div className="bg-surface border border-border rounded-lg shadow overflow-hidden">
    <div className="border-b border-border p-4">
      <Skeleton className="h-6 w-1/4" />
    </div>

    {Array.from({ length: rows }).map((_, i) => (
      <div key={i} className="border-b border-border p-4 flex space-x-4">
        <Skeleton className="h-4 w-1/4" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-4 w-1/6" />
        <Skeleton className="h-4 w-1/6" />
      </div>
    ))}
  </div>
);
