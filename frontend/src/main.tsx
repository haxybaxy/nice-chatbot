import React from "react";
import ReactDOM from "react-dom/client";
import { ErrorBoundary } from "react-error-boundary";
import { BrowserRouter } from "react-router-dom";

import { GlobalErrorFallback } from "@/shared/components/error-boundary";

import App from "./App";
import { Providers } from "./providers";
import "./globals.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary fallbackRender={GlobalErrorFallback}>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <Providers>
          <App />
        </Providers>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
);
