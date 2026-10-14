import { MessageSquareIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ConversationEmptyState } from "@/shared/components/ai-elements/conversation";
import { FormAlert } from "@/shared/components/form/form-alert";
import { ROUTES } from "@/shared/constants/routes";

import { ChatComposer } from "./chat-composer";
import { ChatHeader } from "./chat-header";
import { useChatModels } from "../hooks/use-chat-models";
import { toRunRequestOptions, useComposerSettings } from "../hooks/use-composer-settings";
import { useCreateConversation } from "../hooks/use-conversations";

/**
 * `/app/teams/:teamId/chat`: an empty thread whose first message creates the conversation
 * (`POST /teams/{id}/conversations` with `message`), then navigates to it — the thread there
 * mounts with the run already active and resumes its stream.
 */
export function NewChatScreen({ teamId }: { teamId: string }) {
  const navigate = useNavigate();
  const models = useChatModels();
  const catalog = models.data ?? [];
  const [settings, updateSettings] = useComposerSettings();
  const create = useCreateConversation(teamId);

  const onSubmit = async (text: string) => {
    const conversation = await create.mutateAsync({
      message: { parts: [{ type: "text", text }], ...toRunRequestOptions(settings, catalog) },
    });
    navigate(ROUTES.app.conversation(teamId, conversation.id));
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChatHeader title="New chat" />
      <ConversationEmptyState
        className="min-h-0 flex-1"
        title="Start a conversation"
        description="Ask a question, search the web, run code or launch a deep research. Your team can see it."
        icon={<MessageSquareIcon className="size-8" />}
      />
      <div className="shrink-0 px-4 pb-4">
        <div className="mx-auto w-full max-w-3xl space-y-3">
          <FormAlert error={create.error} />
          <ChatComposer
            status={create.isPending ? "submitted" : "ready"}
            onSubmit={(text) => onSubmit(text).catch(() => undefined)}
            onStop={() => undefined}
            settings={settings}
            onSettingsChange={updateSettings}
            models={catalog}
            placeholder="Start a new conversation…"
          />
        </div>
      </div>
    </div>
  );
}
