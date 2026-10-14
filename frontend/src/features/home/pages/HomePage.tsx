import { useAuth } from "@/providers/use-auth";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/shared/components/ui/card";

const memberSince = new Intl.DateTimeFormat(undefined, { dateStyle: "long" });

export default function HomePage() {
  const { user } = useAuth();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome{user?.fullName ? `, ${user.fullName}` : ""}
        </h1>
        <p className="text-sm text-muted-foreground">You are signed in.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your account</CardTitle>
          <CardDescription>
            What <code>GET /api/users/me</code> knows about you.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-3 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-8">
            <dt className="text-muted-foreground">Email</dt>
            <dd>{user?.email}</dd>
            <dt className="text-muted-foreground">Full name</dt>
            <dd>{user?.fullName ?? <span className="text-muted-foreground">Not set</span>}</dd>
            <dt className="text-muted-foreground">Member since</dt>
            <dd>{user?.createdAt ? memberSince.format(new Date(user.createdAt)) : "—"}</dd>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
