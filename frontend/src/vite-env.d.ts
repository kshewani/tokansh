/// <reference types="vite/client" />
interface ImportMetaEnv {
  /** Base URL of the TokANSH API. Empty = same origin (the Vite dev server proxies /api to the backend). */
  readonly VITE_API_BASE_URL?: string;
}
interface ImportMeta {readonly env: ImportMetaEnv;}
