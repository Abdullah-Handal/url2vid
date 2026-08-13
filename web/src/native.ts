/**
 * Bridge to the desktop shell.
 *
 * When url2vid runs in its own window, pywebview injects `window.pywebview.api`
 * with methods that run in the Python process. That process *is* the download
 * server, so it can simply be told which folder to write to -- no File System
 * Access API, no per-file Save button, and no browser-support caveat.
 *
 * In a plain browser none of this exists and `isNative()` stays false, which
 * leaves the existing web behaviour untouched.
 */

export interface FolderResult {
  ok: boolean;
  cancelled?: boolean;
  error?: string;
  download_dir?: string;
}

interface PywebviewApi {
  choose_folder: () => Promise<FolderResult>;
  reveal_downloads: () => Promise<{ ok: boolean; error?: string }>;
}

declare global {
  interface Window {
    pywebview?: { api?: Partial<PywebviewApi> };
  }
}

export function isNative(): boolean {
  return typeof window.pywebview?.api?.choose_folder === "function";
}

/**
 * Resolve once the bridge exists, or false if it never turns up.
 *
 * pywebview attaches its API after the page loads and announces it with a
 * `pywebviewready` event, so checking synchronously on first render can miss
 * it and wrongly fall back to browser mode.
 */
export function whenReady(timeoutMs = 3000): Promise<boolean> {
  if (isNative()) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value: boolean) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("pywebviewready", onReady);
      clearTimeout(timer);
      resolve(value);
    };
    const onReady = () => finish(isNative());
    window.addEventListener("pywebviewready", onReady);
    const timer = setTimeout(() => finish(isNative()), timeoutMs);
  });
}

export async function chooseFolder(): Promise<FolderResult> {
  const api = window.pywebview?.api;
  if (!api?.choose_folder) return { ok: false, error: "Not running in the desktop app." };
  return api.choose_folder();
}

export async function revealDownloads(): Promise<void> {
  await window.pywebview?.api?.reveal_downloads?.();
}
