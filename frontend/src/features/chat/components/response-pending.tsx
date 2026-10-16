/**
 * The pulsing dot ChatGPT shows where an answer is about to appear: the message was sent (or
 * the thread reopened on a run still queued or running) and nothing has arrived yet. The live
 * region announces the wait once; the dot itself is decoration.
 */
export function ResponsePending() {
  return (
    <div
      role="status"
      aria-label="Waiting for a response"
      className="flex h-7 items-center"
      data-testid="response-pending"
    >
      <span
        aria-hidden="true"
        className="size-3 animate-thinking-dot rounded-full bg-foreground motion-reduce:animate-none"
      />
    </div>
  );
}
