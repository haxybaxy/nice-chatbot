import { useCurrentUser } from "@/features/auth";

import { AuthContext } from "./use-auth";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading } = useCurrentUser();

  const value = {
    user: user ?? null,
    isLoading,
    isAuthenticated: !!user,
  };

  // Always render children, even while the session is loading or after an error —
  // ProtectedRoute / GuestRoute make the routing decision from `isLoading` + `user`.
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
