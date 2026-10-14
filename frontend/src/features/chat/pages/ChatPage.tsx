import { Link, useParams } from "react-router-dom";

import { Loading } from "@/shared/components/feedback";
import { Alert, AlertDescription } from "@/shared/components/ui/alert";
import { Button } from "@/shared/components/ui/button";
import { ROUTES } from "@/shared/constants/routes";
import { ApiError } from "@/shared/services/api-error";

import { ChatHeader } from "../components/chat-header";
import { ChatThread } from "../components/chat-thread";
import { NewChatScreen } from "../components/new-chat-screen";
import { useConversation } from "../hooks/use-conversations";
import { conversationTitle } from "../utils/conversations";

/** `/app/teams/:teamId/chat` (a new chat) and `/app/teams/:teamId/chat/:conversationId` (a thread). */
export default function ChatPage() {
  const { teamId = "", conversationId } = useParams();
  if (!conversationId) {
    return <NewChatScreen key={teamId} teamId={teamId} />;
  }
  return <ConversationView key={conversationId} teamId={teamId} conversationId={conversationId} />;
}

function ConversationView({ teamId, conversationId }: { teamId: string; conversationId: string }) {
  const query = useConversation(conversationId);

  if (query.isPending) {
    return (
      <>
        <ChatHeader title="Conversation" />
        <Loading fullHeight label="Loading conversation…" />
      </>
    );
  }
  if (query.isError) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <>
        <ChatHeader title={notFound ? "Not found" : "Conversation"} />
        <div className="mx-auto w-full max-w-md p-6">
          <Alert variant={notFound ? "default" : "destructive"}>
            <AlertDescription>
              {notFound
                ? "This conversation does not exist or is not visible to you."
                : query.error.message}
              <div className="flex gap-2">
                {notFound ? (
                  <Button asChild size="sm" variant="outline">
                    <Link to={ROUTES.app.teamChat(teamId)}>Start a new chat</Link>
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
                    Try again
                  </Button>
                )}
              </div>
            </AlertDescription>
          </Alert>
        </div>
      </>
    );
  }

  return (
    <>
      <ChatHeader title={conversationTitle(query.data.conversation)} />
      <div className="min-h-0 flex-1">
        <ChatThread teamId={teamId} detail={query.data} />
      </div>
    </>
  );
}
