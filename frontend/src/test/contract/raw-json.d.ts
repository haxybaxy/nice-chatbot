// Vite returns the file's raw text for a `?raw` import. tsconfig restricts
// `types` to vitest/globals (no vite/client), so declare the one we use.
declare module "*.json?raw" {
  const content: string;
  export default content;
}
