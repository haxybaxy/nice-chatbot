import type * as React from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/shared/components/ui/card";

interface AuthCardProps {
  title: string;
  description: string;
  children: React.ReactNode;
}

/** The card every auth page renders inside `AuthLayout`: a level-1 heading, one line of context, the body. */
export function AuthCard({ title, description, children }: AuthCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle role="heading" aria-level={1}>
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
