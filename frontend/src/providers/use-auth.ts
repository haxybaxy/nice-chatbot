import { createContext, useContext } from "react";

import type { SessionUser } from "@/features/auth/types";

interface AuthContextType {
  /** Either shape the auth cache can hold — see {@link SessionUser}. Treat the
   *  profile-only fields as possibly-absent right after sign-in. */
  user: SessionUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
