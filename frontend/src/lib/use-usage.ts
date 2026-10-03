"use client";

import { useEffect, useState } from "react";
import { getUsageStatus, UsageStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export function useUsage() {
  const { session, loading } = useAuth();
  const token = session?.access_token;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    token?: string;
    data?: UsageStatus;
    error?: string;
  }>({});
  useEffect(() => {
    let cancelled = false;
    setState({});
    if (!loading && token) {
      getUsageStatus().then(
        (data) => {
          if (!cancelled) setState({ token, data });
        },
        (error) => {
          if (!cancelled)
            setState({
              token,
              error:
                error instanceof Error
                  ? error.message
                  : "Usage unavailable. Retry.",
            });
        },
      );
    }
    return () => {
      cancelled = true;
    };
  }, [token, loading, attempt]);
  const current = !loading && token && state.token === token ? state : {};
  return {
    ...current,
    signedIn: !!token,
    loading: loading || (!!token && !current.data && !current.error),
    retry: () => setAttempt((value) => value + 1),
  };
}
