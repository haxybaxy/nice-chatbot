import {
  AlertTriangleIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleDotIcon,
  CircleXIcon,
} from "lucide-react";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
} from "@/shared/components/ai-elements/chain-of-thought";
import {
  Plan,
  PlanAction,
  PlanContent,
  PlanDescription,
  PlanHeader,
  PlanTitle,
  PlanTrigger,
} from "@/shared/components/ai-elements/plan";
import { Task, TaskContent, TaskItem, TaskTrigger } from "@/shared/components/ai-elements/task";
import { Badge } from "@/shared/components/ui/badge";

import type { ResearchCitations, ResearchTask, ResearchTaskStatus } from "../types";
import type { ResearchState } from "../utils/assistant-blocks";

const STEP_STATUS: Record<ResearchTaskStatus, "complete" | "active" | "pending"> = {
  pending: "pending",
  running: "active",
  done: "complete",
  failed: "complete",
  skipped: "complete",
};

const STEP_ICON: Record<ResearchTaskStatus, typeof CircleDotIcon> = {
  pending: CircleDashedIcon,
  running: CircleDotIcon,
  done: CircleCheckIcon,
  failed: CircleXIcon,
  skipped: CircleDashedIcon,
};

const SETTLED: readonly ResearchTaskStatus[] = ["done", "failed", "skipped"];

const STATUS_LABEL: Record<ResearchTaskStatus, string> = {
  pending: "Waiting",
  running: "Working…",
  done: "Done",
  failed: "Failed",
  skipped: "Skipped",
};

interface Row {
  id: string;
  title: string;
  objective?: string;
  status: ResearchTaskStatus;
  progress?: ResearchTask;
}

/** The plan's tasks, each with its latest progress; progress alone when no plan arrived (yet). */
function toRows({ plan, tasks }: ResearchState): Row[] {
  const progress = new Map(tasks.map((task) => [task.id, task]));
  if (plan) {
    return plan.tasks.map((task) => {
      const latest = progress.get(task.id);
      return { ...task, status: latest?.status ?? task.status, progress: latest };
    });
  }
  return tasks.map((task) => ({
    id: task.id,
    title: task.title,
    status: task.status,
    progress: task,
  }));
}

/**
 * A deep-research run, rendered from its data parts: the plan (`data-research-plan`), each
 * task's progress reconciled by id (`data-research-task`) and the citation check
 * (`data-research-citations`). The report itself is the message's text.
 */
export function DeepResearchPanel({
  research,
  isStreaming,
}: {
  research: ResearchState;
  isStreaming: boolean;
}) {
  const rows = toRows(research);
  const done = rows.filter((row) => row.status === "done").length;
  const settled = rows.length > 0 && rows.every((row) => SETTLED.includes(row.status));

  return (
    <Plan
      isStreaming={isStreaming && !settled}
      defaultOpen
      className="mb-2"
      data-testid="deep-research"
    >
      <PlanHeader>
        <div className="min-w-0 space-y-1">
          <PlanTitle>Deep research</PlanTitle>
          {research.plan && <PlanDescription>{research.plan.summary}</PlanDescription>}
        </div>
        <PlanAction>
          <div className="flex items-center gap-2">
            {research.plan && <Badge variant="outline">{research.plan.complexity}</Badge>}
            <PlanTrigger />
          </div>
        </PlanAction>
      </PlanHeader>
      <PlanContent className="space-y-4">
        <ChainOfThought defaultOpen>
          <ChainOfThoughtHeader>
            {rows.length > 0 ? `${done} of ${rows.length} tasks complete` : "Planning…"}
          </ChainOfThoughtHeader>
          <ChainOfThoughtContent>
            {rows.map((row) => (
              <ChainOfThoughtStep
                key={row.id}
                icon={STEP_ICON[row.status]}
                label={row.title}
                description={row.objective}
                status={STEP_STATUS[row.status]}
                data-task={row.id}
                data-task-status={row.status}
              >
                {row.progress && <ResearchTaskRow task={row.progress} />}
              </ChainOfThoughtStep>
            ))}
          </ChainOfThoughtContent>
        </ChainOfThought>
        {research.citations && <CitationWarnings citations={research.citations} />}
      </PlanContent>
    </Plan>
  );
}

/** A task's progress: what it is doing (or its status) as the headline, its summary and tool-call count inside. */
function ResearchTaskRow({ task }: { task: ResearchTask }) {
  return (
    <Task defaultOpen>
      <TaskTrigger title={task.lastAction ?? STATUS_LABEL[task.status]} />
      <TaskContent>
        {task.summary && <TaskItem>{task.summary}</TaskItem>}
        <ChainOfThoughtSearchResults>
          <ChainOfThoughtSearchResult>
            {task.toolCalls} tool call{task.toolCalls === 1 ? "" : "s"}
          </ChainOfThoughtSearchResult>
        </ChainOfThoughtSearchResults>
      </TaskContent>
    </Task>
  );
}

function CitationWarnings({ citations }: { citations: ResearchCitations }) {
  const unsupported = citations.unsupported.length;
  const unknown = citations.unknownNumbers.length;
  if (unsupported === 0 && unknown === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-2" role="status">
      {unsupported > 0 && (
        <Badge variant="destructive">
          <AlertTriangleIcon />
          {unsupported} unsupported citation{unsupported === 1 ? "" : "s"}
        </Badge>
      )}
      {unknown > 0 && (
        <Badge variant="destructive">
          <AlertTriangleIcon />
          {unknown} unknown citation number{unknown === 1 ? "" : "s"}
        </Badge>
      )}
    </div>
  );
}
