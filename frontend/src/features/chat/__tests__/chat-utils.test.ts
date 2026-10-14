import { describe, expect, it } from "vitest";

import { linkCitations } from "@/features/chat/utils/citations";
import { groupConversationsByDay } from "@/features/chat/utils/conversations";
import { makeConversation } from "@/test/msw/fixtures/chat";

const sources = [
  { type: "source-url" as const, sourceId: "1", url: "https://a.example/1" },
  { type: "source-url" as const, sourceId: "2", url: "https://b.example/2" },
];

describe("linkCitations", () => {
  it("links every [n] with a source and leaves the others as written", () => {
    expect(linkCitations("A [1], B [2] and C [3].", sources)).toBe(
      "A [[1]](https://a.example/1), B [[2]](https://b.example/2) and C [3]."
    );
  });

  it("does not touch existing links or fenced code", () => {
    const text = "See [1](https://x) and\n```py\nx = a[1]\n```\nthen [1].";
    expect(linkCitations(text, sources)).toBe(
      "See [1](https://x) and\n```py\nx = a[1]\n```\nthen [[1]](https://a.example/1)."
    );
  });

  it("is the identity without sources", () => {
    expect(linkCitations("plain [1]", [])).toBe("plain [1]");
  });
});

describe("groupConversationsByDay", () => {
  it("buckets by the local day of the last message, dropping empty groups", () => {
    const now = new Date(2026, 9, 14, 15, 0, 0);
    const at = (daysAgo: number, hour = 9) =>
      new Date(2026, 9, 14 - daysAgo, hour, 0, 0).toISOString();
    const groups = groupConversationsByDay(
      [
        makeConversation({ id: "a", lastMessageAt: at(0, 1) }),
        makeConversation({ id: "b", lastMessageAt: at(1, 23) }),
        makeConversation({ id: "c", lastMessageAt: at(2) }),
        makeConversation({ id: "d", lastMessageAt: at(30) }),
      ],
      now
    );

    expect(groups.map((group) => [group.label, group.items.map((item) => item.id)])).toEqual([
      ["Today", ["a"]],
      ["Yesterday", ["b"]],
      ["Earlier", ["c", "d"]],
    ]);
  });
});
