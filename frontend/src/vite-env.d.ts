/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin. Empty/unset means http://localhost:8000 (see shared/config/api-endpoints.ts). */
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
