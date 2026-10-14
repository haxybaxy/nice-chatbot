import type { SourceUrlUIPart } from "ai";
import { createContext } from "react";

/**
 * The `source-url` parts of the assistant message being rendered, read by `CitationAnchor`
 * (which `MessageResponse` instantiates for every link, so it cannot take them as a prop).
 */
export const CitationSourcesContext = createContext<readonly SourceUrlUIPart[]>([]);
