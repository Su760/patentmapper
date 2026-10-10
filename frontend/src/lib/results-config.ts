// Read-only status retries. Never retry a paid POST automatically.
export const RESULTS_POLLING = {
  intervalMs: 3000,
  timeoutMs: 15000,
  maxRequests: 120,
  maxErrors: 3,
};

export const GRAPH_VIEW = {
  minZoom: 0.5,
  maxZoom: 2,
  zoomStep: 0.25,
  initialZoom: 1,
  height: 400,
  expandedHeight: 640,
};
