import { ChevronDownIcon } from "lucide-react";

import { Shimmer } from "@/shared/components/ai-elements/shimmer";
import { cn } from "@/shared/utils";

interface DisclosureLabelProps {
  text: string;
  /** Still happening: the text shimmers. */
  busy: boolean;
  open: boolean;
}

/**
 * The inside of a quiet disclosure line — a tool call, the reasoning — in ChatGPT's style: the
 * sentence (shimmering while it is still happening) and a chevron that turns when open. The
 * parent is the trigger; this only renders what it says.
 */
export function DisclosureLabel({ text, busy, open }: DisclosureLabelProps) {
  return (
    <>
      {busy ? (
        // `as="span"`: the label sits inside a button, where a paragraph would not belong.
        <Shimmer duration={1} as="span" className="text-sm">
          {text}
        </Shimmer>
      ) : (
        <span>{text}</span>
      )}
      <ChevronDownIcon
        className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")}
        aria-hidden="true"
      />
    </>
  );
}
