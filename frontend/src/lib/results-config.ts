// Read-only status retries. Never retry a paid POST automatically.
export const RESULTS_POLLING = {
  intervalMs: 3000,
  timeoutMs: 15000,
  maxRequests: 120,
  maxErrors: 3,
};
