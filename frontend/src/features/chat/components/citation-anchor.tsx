import type { SourceUrlUIPart } from "ai";
import type { ComponentProps } from "react";
import { useContext } from "react";

import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationSource,
} from "@/shared/components/ai-elements/inline-citation";
import { HoverCardTrigger } from "@/shared/components/ui/hover-card";

import { CitationSourcesContext } from "../utils/citation-sources";
import { hostnameOf, stripTracking } from "../utils/citations";

/** `MessageResponse` hands its anchors a hast `node` too; it must not reach the DOM. */
type AnchorProps = ComponentProps<"a"> & { node?: unknown };

/** The source this link points at, tracking parameters aside (`utm_source=chatgpt.com` and the like). */
function citedSource(
  sources: readonly SourceUrlUIPart[],
  href: string
): SourceUrlUIPart | undefined {
  const target = stripTracking(href);
  return sources.find((source) => stripTracking(source.url) === target);
}

/**
 * The `a` renderer of assistant markdown. A link to one of the message's sources — the `[n]`
 * link `linkCitations` made, or an inline link the model wrote itself, as OpenAI's built-in
 * search does (`[title](url?utm_source=chatgpt.com)`) — becomes the `[n]` citation pill with a
 * hover card, whatever its own text; any other link opens in a new tab.
 */
export function CitationAnchor({ node: _node, href, children, className, ...props }: AnchorProps) {
  const sources = useContext(CitationSourcesContext);
  const source = href ? citedSource(sources, href) : undefined;

  if (!source) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={className} {...props}>
        {children}
      </a>
    );
  }

  return (
    <InlineCitation>
      <InlineCitationCard>
        <HoverCardTrigger asChild>
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            data-citation={source.sourceId}
            className="ml-0.5 inline-flex h-5 items-center rounded-full bg-secondary px-1.5 align-text-top text-xs font-medium text-secondary-foreground no-underline hover:bg-secondary/80"
            {...props}
          >
            [{source.sourceId}]
          </a>
        </HoverCardTrigger>
        <InlineCitationCardBody className="p-3">
          <InlineCitationSource title={source.title ?? hostnameOf(source.url)} url={source.url} />
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  );
}
