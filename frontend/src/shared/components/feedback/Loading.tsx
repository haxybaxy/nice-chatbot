import { cn } from "@/shared/utils";

import { Spinner } from "./Spinner";

interface LoadingProps {
  /** Spinner size. Defaults to `"md"` (h-8 w-8). */
  size?: "sm" | "md" | "lg";
  /** Optional text rendered beneath the spinner. */
  label?: string;
  /**
   * Fill the available height and guarantee a minimum, so the spinner sits in
   * the vertical center of a page/route rather than at the top.
   */
  fullHeight?: boolean;
  className?: string;
}

const sizeClasses: Record<NonNullable<LoadingProps["size"]>, string> = {
  sm: "h-5 w-5",
  md: "h-8 w-8",
  lg: "h-12 w-12",
};

/**
 * Centered block loading state for pages and sections. Wraps a {@link Spinner}
 * with consistent centering and an optional label, replacing the various
 * hand-rolled `<div className="flex justify-center"><Loader2 .../></div>`
 * blocks scattered across features.
 */
export function Loading({ size = "md", label, fullHeight = false, className }: LoadingProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-3",
        fullHeight && "h-full min-h-[50vh]",
        className
      )}
    >
      <Spinner className={cn("text-muted-foreground", sizeClasses[size])} />
      {label && <p className="text-sm text-muted-foreground">{label}</p>}
    </div>
  );
}
