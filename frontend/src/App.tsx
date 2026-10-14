import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { GuestRoute } from "@/features/auth";
import { AppIndexRedirect } from "@/features/teams";
import { PageLoadingFallback } from "@/shared/components/error-boundary";
import { ROUTES } from "@/shared/constants/routes";

// Layouts stay eager (shared shells)
import AuthLayout from "./layouts/AuthLayout";
import ChatLayout from "./layouts/ChatLayout";
import ProtectedLayout from "./layouts/ProtectedLayout";

// Pages are lazy (default exports) so each route is its own chunk
const LoginPage = lazy(() => import("@/features/auth/pages/LoginPage"));
const SignUpPage = lazy(() => import("@/features/auth/pages/SignUpPage"));
const ForgotPasswordPage = lazy(() => import("@/features/auth/pages/ForgotPasswordPage"));
const ResetPasswordPage = lazy(() => import("@/features/auth/pages/ResetPasswordPage"));
const ChatPage = lazy(() => import("@/features/chat/pages/ChatPage"));

function App() {
  return (
    <Suspense fallback={<PageLoadingFallback />}>
      <Routes>
        {/* Auth routes (guest only) */}
        <Route path={ROUTES.auth.root} element={<AuthLayout />}>
          <Route index element={<Navigate to={ROUTES.auth.login} replace />} />
          <Route
            path="login"
            element={
              <GuestRoute>
                <LoginPage />
              </GuestRoute>
            }
          />
          <Route
            path="sign-up"
            element={
              <GuestRoute>
                <SignUpPage />
              </GuestRoute>
            }
          />
          <Route
            path="forgot-password"
            element={
              <GuestRoute>
                <ForgotPasswordPage />
              </GuestRoute>
            }
          />
          {/* Not guest-only: the mailed link must work whatever session the browser holds. */}
          <Route path="reset-password" element={<ResetPasswordPage />} />
        </Route>

        {/* Protected routes: /app → last team's chat; the chat shell is team-scoped */}
        <Route path={ROUTES.app.root} element={<ProtectedLayout />}>
          <Route index element={<AppIndexRedirect />} />
          <Route path="teams/:teamId" element={<ChatLayout />}>
            <Route index element={<Navigate to="chat" replace />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:conversationId" element={<ChatPage />} />
          </Route>
        </Route>

        {/* Everything else */}
        <Route path="*" element={<Navigate to={ROUTES.auth.login} replace />} />
      </Routes>
    </Suspense>
  );
}

export default App;
