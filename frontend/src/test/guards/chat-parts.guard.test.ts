/**
 * Pins the chat's wire ↔ AI SDK part mapping at the type level (`expectTypeOf` is checked by
 * `tsc`), so a backend schema change or an `ai` upgrade that moves the two apart fails
 * `just typecheck` here before it fails a user.
 *
 * What is pinned: the roles agree; the four structural parts the backend persists are SDK
 * parts once the wire's nullable `state` / `title` are dropped (what `toChatMessage` does); the
 * tool states the backend persists are a subset of the SDK's; the tool part types the UI
 * renders are spelled by the SDK's `tool-${name}` template over `ChatTools`. What cannot be
 * pinned, and why: the wire's `tool-*` / `data-*` discriminators are plain `string`
 * (`ToolPartOut.type`, `DataPartOut.type` — the `^tool-` / `^data-` patterns are regexes, not
 * types), so `WirePart` as a whole is NOT assignable to the SDK's part union; the runtime guards
 * in `features/chat/utils/payload-guards.ts` and the `toChatMessage` tests carry that half.
 */
import type {
  ReasoningUIPart,
  SourceUrlUIPart,
  StepStartUIPart,
  TextUIPart,
  UIMessage,
  UIMessagePart,
} from "ai";
import { describe, expectTypeOf, it } from "vitest";

import type {
  ChatDataParts,
  ChatMessage,
  ChatMessagePart,
  ChatToolPart,
  ChatTools,
  WireDataPart,
  WireMessage,
  WireReasoningPart,
  WireSourceUrlPart,
  WireStepStartPart,
  WireTextPart,
  WireToolPart,
} from "@/features/chat/types";
import { TOOL_PART_TYPES, toChatMessage } from "@/features/chat/utils/wire-parts";

/** The wire's `x?: T | null` as the SDK's `x?: T`. */
type DropNull<T, K extends keyof T> = Omit<T, K> & { [P in K]?: Exclude<T[P], null> };

describe("chat wire parts vs the AI SDK's UIMessage", () => {
  it("roles agree: the backend persists what the SDK renders, never `system`", () => {
    expectTypeOf<WireMessage["role"]>().toEqualTypeOf<Exclude<UIMessage["role"], "system">>();
    expectTypeOf<ChatMessage["role"]>().toEqualTypeOf<UIMessage["role"]>();
  });

  it("the structural parts are SDK parts once the wire's nullables are dropped", () => {
    expectTypeOf<DropNull<WireTextPart, "state">>().toExtend<TextUIPart>();
    expectTypeOf<DropNull<WireReasoningPart, "state">>().toExtend<ReasoningUIPart>();
    expectTypeOf<DropNull<WireSourceUrlPart, "title">>().toExtend<SourceUrlUIPart>();
    expectTypeOf<WireStepStartPart>().toExtend<StepStartUIPart>();
    expectTypeOf<WireTextPart["state"]>().toEqualTypeOf<"streaming" | "done" | null | undefined>();
  });

  it("the tool states the backend persists are SDK states, and the UI's tool types are the SDK's template", () => {
    expectTypeOf<WireToolPart["state"]>().toExtend<ChatToolPart["state"]>();
    expectTypeOf<ChatToolPart["type"]>().toEqualTypeOf<`tool-${keyof ChatTools}`>();
    expectTypeOf(TOOL_PART_TYPES.code).toEqualTypeOf<"tool-run_code">();
    expectTypeOf<(typeof TOOL_PART_TYPES)[keyof typeof TOOL_PART_TYPES]>().toEqualTypeOf<
      ChatToolPart["type"]
    >();
  });

  it("the wire discriminators of tool and data parts are open strings — the guards narrow them", () => {
    expectTypeOf<WireToolPart["type"]>().toEqualTypeOf<string>();
    expectTypeOf<WireDataPart["type"]>().toEqualTypeOf<string>();
    expectTypeOf<WireToolPart["input"]>().toEqualTypeOf<unknown>();
    expectTypeOf<WireDataPart["data"]>().toEqualTypeOf<unknown>();
    expectTypeOf<`data-${keyof ChatDataParts}`>().toExtend<ChatMessagePart["type"]>();
  });

  it("toChatMessage builds the SDK message without a cast", () => {
    expectTypeOf(toChatMessage).returns.toEqualTypeOf<ChatMessage>();
    expectTypeOf<ChatMessagePart>().toEqualTypeOf<UIMessagePart<ChatDataParts, ChatTools>>();
  });
});
