import { Alert, AlertDescription } from "@/shared/components/ui/alert";

/** The server's rejection of a submission (a mutation's error), or nothing. */
export function FormAlert({ error }: { error: Error | null }) {
  if (!error) {
    return null;
  }
  return (
    <Alert variant="destructive">
      <AlertDescription>{error.message}</AlertDescription>
    </Alert>
  );
}
