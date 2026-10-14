import { Loader2, type LucideProps } from "lucide-react";

import { cn } from "@/shared/utils";

/**
 * Inline loading spinner — a spinning `Loader2` icon. Decorative by default
 * (`aria-hidden`); pass an `aria-label` (and `aria-hidden={false}`) to announce
 * it to assistive tech.
 *
 * Size, color, and margin come from `className` exactly like the inline
 * `<Loader2 ... animate-spin />` it replaces, e.g.
 * `<Spinner className="mr-2 h-4 w-4 text-muted-foreground" />`. For full-page
 * or section loading states use {@link Loading} instead.
 */
export function Spinner({ className, ...props }: LucideProps) {
  return <Loader2 aria-hidden className={cn("animate-spin", className)} {...props} />;
}
