import type { JobStatusResponse } from "./api";
import { RESULTS_POLLING } from "./results-config";

interface PollCallbacks {
  read: (signal: AbortSignal) => Promise<JobStatusResponse>;
  onStatus: (
    status: JobStatusResponse,
    signal: AbortSignal,
  ) => Promise<void> | void;
  onError: (message: string, stopped: boolean, unauthorized: boolean) => void;
}

/** One request at a time, including result loading. Cleanup cancels I/O and timers. */
export function startJobPolling(
  callbacks: PollCallbacks,
  config = RESULTS_POLLING,
): () => void {
  let stopped = false;
  let requests = 0;
  let errors = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active: AbortController | undefined;

  async function poll() {
    active = new AbortController();
    const controller = active;
    const timeout = setTimeout(() => controller.abort(), config.timeoutMs);
    let terminal = false;
    try {
      const work = (async () => {
        const status = await callbacks.read(controller.signal);
        if (stopped || controller.signal.aborted) return true;
        await callbacks.onStatus(status, controller.signal);
        return !["queued", "running", "finalizing", "processing"].includes(status.status);
      })();
      // Also bound SDK/token waits that do not themselves honor AbortSignal.
      terminal = await new Promise<boolean>((resolve, reject) => {
        const abort = () => reject(new Error("Request cancelled."));
        controller.signal.addEventListener("abort", abort, { once: true });
        work
          .then(resolve, reject)
          .finally(() => controller.signal.removeEventListener("abort", abort));
      });
      if (stopped) return;
      errors = 0;
    } catch (error) {
      if (stopped) return;
      errors++;
      const code = (error as { status?: number })?.status;
      const unauthorized = code === 401 || code === 403 || code === 404;
      terminal = unauthorized || errors >= config.maxErrors;
      const message = controller.signal.aborted
        ? "The request timed out."
        : error instanceof Error
          ? error.message
          : "The request failed.";
      callbacks.onError(message, terminal, unauthorized);
    } finally {
      clearTimeout(timeout);
    }
    if (stopped || terminal) return;
    requests++;
    if (requests >= config.maxRequests) {
      callbacks.onError(
        "Status checks paused after the monitoring limit. The job may still be running.",
        true,
        false,
      );
      return;
    }
    timer = setTimeout(poll, config.intervalMs);
  }
  void poll();
  return () => {
    stopped = true;
    clearTimeout(timer);
    active?.abort();
  };
}
