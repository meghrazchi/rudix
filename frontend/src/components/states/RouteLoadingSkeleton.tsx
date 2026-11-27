import { SkeletonBlock } from "@/components/states/SkeletonBlock";

/**
 * Shown by `loading.tsx` while a route segment streams in: a page header and
 * two cards, inside the existing app shell.
 */
export function RouteLoadingSkeleton() {
  return (
    <div className="space-y-6">
      <div aria-hidden="true" className="space-y-3">
        <div className="h-7 w-56 animate-pulse rounded-md bg-[#e8e5f5]" />
        <div className="h-3 w-80 max-w-full animate-pulse rounded-full bg-[#e8e5f5]" />
      </div>
      <SkeletonBlock rows={4} />
      <SkeletonBlock rows={5} />
    </div>
  );
}
