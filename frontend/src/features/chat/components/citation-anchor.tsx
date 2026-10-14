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
import { CITATION_LABEL, hostnameOf } from "../utils/citations";

/** `MessageResponse` hands its anchors a hast `node` too; it must not reach the DOM. */
type AnchorProps = ComponentProps<"a"> & { node?: unknown };

function textOf(children: AnchorProps["children"]): string | null {
  if (typeof children === "string") return children;
  if (Array.isArray(children) && children.every((child) => typeof child === "string")) {
    return children.join("");
  }
  return null;
}

/**
 * The `a` renderer of assistant markdown: a `[n]` link to one of the message's sources becomes
 * an inline citation with a hover card; any other link opens in a new tab.
 */
export function CitationAnchor({ node: _node, href, children, className, ...props }: AnchorProps) {
  const sources = useContext(CitationSourcesContext);
  const label = textOf(children);
  const source = href ? sources.find((candidate) => candidate.url === href) : undefined;

  if (!source || !label || !CITATION_LABEL.test(label)) {
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
            {label}
          </a>
        </HoverCardTrigger>
        <InlineCitationCardBody className="p-3">
          <InlineCitationSource title={source.title ?? hostnameOf(source.url)} url={source.url} />
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  );
}
