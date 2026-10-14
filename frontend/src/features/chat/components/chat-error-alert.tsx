import { AlertTriangleIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/shared/components/ui/alert";
import { Button } from "@/shared/components/ui/button";

interface ChatErrorAlertProps {
  error: Error;
  onReconnect: () => void;
  onDismiss: () => void;
}

/** `useChat.error`: the stream broke or a request failed. Reconnect resumes the run if it is still active. */
export function ChatErrorAlert({ error, onReconnect, onDismiss }: ChatErrorAlertProps) {
  return (
    <Alert variant="destructive" className="mx-auto mb-3 w-full max-w-3xl">
      <AlertTriangleIcon />
      <AlertDescription>
        <p>{error.message}</p>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" onClick={onReconnect}>
            Reconnect
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
            Dismiss
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
