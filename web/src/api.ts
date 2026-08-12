import type { Job, Probe } from "./types";

/** Pull the server's own explanation out of a failed response. */
async function fail(response: Response): Promise<never> {
  let detail = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // A non-JSON body means the server died rather than refused; the status
    // line is all there is to report.
  }
  throw new Error(detail);
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) await fail(response);
  return response.json() as Promise<T>;
}

export const probe = (url: string) => post<Probe>("/api/probe", { url });

export const startDownload = (url: string, height: number | null, title: string) =>
  post<{ id: string }>("/api/download", { url, height, title });

export const cancelJob = (id: string) => post<{ ok: boolean }>(`/api/jobs/${id}/cancel`);

export const clearFinished = () => post<{ cleared: number }>("/api/jobs/clear");

export const getConfig = async (): Promise<{ download_dir: string; max_concurrent: number }> => {
  const response = await fetch("/api/config");
  if (!response.ok) await fail(response);
  return response.json();
};

export const fileUrl = (id: string) => `/api/jobs/${id}/file`;

/**
 * Subscribe to the job table. Returns an unsubscribe function.
 *
 * The server pushes the whole table on every change rather than diffs, so a
 * dropped frame or a reconnect can never leave the page showing stale rows.
 */
export function subscribeJobs(onJobs: (jobs: Job[]) => void, onError: (down: boolean) => void) {
  const source = new EventSource("/api/events");
  source.onmessage = (event) => {
    onError(false);
    const payload = JSON.parse(event.data) as { jobs: Job[] };
    onJobs(payload.jobs);
  };
  // EventSource reconnects on its own; this only surfaces the gap in the UI.
  source.onerror = () => onError(true);
  return () => source.close();
}
