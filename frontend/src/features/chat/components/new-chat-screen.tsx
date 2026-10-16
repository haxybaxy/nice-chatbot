import { useNavigate } from "react-router-dom";

import { FormAlert } from "@/shared/components/form/form-alert";
import { ROUTES } from "@/shared/constants/routes";

import { ChatComposer } from "./chat-composer";
import { ChatHeader } from "./chat-header";
import { ModelSelect } from "./model-select";
import { useChatModels } from "../hooks/use-chat-models";
import { toRunRequestOptions, useComposerSettings } from "../hooks/use-composer-settings";
import { useCreateConversation } from "../hooks/use-conversations";
import type { ChatMessagePart, ComposerSubmission } from "../types";
import { toMessagePartsIn } from "../utils/message-parts";

/**
 * `/app/teams/:teamId/chat`: ChatGPT's empty screen — a greeting and the composer in the middle
 * of the page. The first message creates the conversation (`POST /teams/{id}/conversations`
 * with `message`), then navigates to it — the thread there mounts with the run already active
 * and resumes its stream.
 */
export function NewChatScreen({ teamId }: { teamId: string }) {
  const navigate = useNavigate();
  const models = useChatModels();
  const [settings, updateSettings] = useComposerSettings();
  const catalog = models.data ?? [];
  const create = useCreateConversation(teamId);

  // Rejects on failure so the composer keeps the text and the attachments (the alert shows why).
  const onSubmit = async ({ text, files }: ComposerSubmission) => {
    const parts: ChatMessagePart[] = [...files];
    if (text) {
      parts.push({ type: "text", text });
    }
    const conversation = await create.mutateAsync({
      message: { parts: toMessagePartsIn(parts), ...toRunRequestOptions(settings, catalog) },
    });
    navigate(ROUTES.app.conversation(teamId, conversation.id));
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChatHeader title="New chat">
        <ModelSelect settings={settings} onSettingsChange={updateSettings} models={catalog} />
      </ChatHeader>
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-4 pb-16">
        <div className="w-full max-w-3xl space-y-6">
          <h2 className="text-center text-3xl font-normal tracking-tight">What can I help with?</h2>
          <FormAlert error={create.error} />
          <ChatComposer
            teamId={teamId}
            status={create.isPending ? "submitted" : "ready"}
            onSubmit={onSubmit}
            onStop={() => undefined}
            settings={settings}
            onSettingsChange={updateSettings}
            models={catalog}
          />
        </div>
      </div>
    </div>
  );
}
