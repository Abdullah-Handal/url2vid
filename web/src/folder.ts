/**
 * Remembering the folder the user picked.
 *
 * The File System Access API hands back a live handle, not a path, and for
 * good reason: a page must never learn where things are on disk. A handle
 * survives a reload only if it is stored in IndexedDB (localStorage takes
 * strings and would flatten it), and even then the browser may downgrade the
 * permission to "prompt", which can only be re-granted from a click. All of
 * that is contained here so the components never have to think about it.
 */

// Minimal declarations: these APIs are not in TypeScript's DOM lib yet.
export interface FileSystemWritable {
  write(data: Blob | BufferSource | string): Promise<void>;
  close(): Promise<void>;
}
export interface FileHandle {
  createWritable(options?: { keepExistingData?: boolean }): Promise<FileSystemWritable>;
}
export interface DirectoryHandle {
  readonly name: string;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FileHandle>;
  queryPermission(options?: { mode?: "read" | "readwrite" }): Promise<PermissionState>;
  requestPermission(options?: { mode?: "read" | "readwrite" }): Promise<PermissionState>;
}

declare global {
  interface Window {
    showDirectoryPicker?: (options?: {
      mode?: "read" | "readwrite";
      startIn?: string;
      id?: string;
    }) => Promise<DirectoryHandle>;
  }
}

const DB_NAME = "url2vid";
const STORE = "handles";
const KEY = "download-folder";

export const isSupported = (): boolean => typeof window.showDirectoryPicker === "function";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = run(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result as T);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

export const saveHandle = (handle: DirectoryHandle) =>
  withStore<void>("readwrite", (store) => store.put(handle, KEY));

export const forgetHandle = () => withStore<void>("readwrite", (store) => store.delete(KEY));

export async function loadHandle(): Promise<DirectoryHandle | null> {
  try {
    return (await withStore<DirectoryHandle | undefined>("readonly", (s) => s.get(KEY))) ?? null;
  } catch {
    // A private-browsing window can refuse IndexedDB outright. Losing the
    // remembered folder is a downgrade, not a failure worth surfacing.
    return null;
  }
}

/** Ask the user for a folder. Returns null if they dismiss the dialog. */
export async function pickFolder(): Promise<DirectoryHandle | null> {
  if (!window.showDirectoryPicker) throw new Error("This browser cannot pick a folder.");
  try {
    const handle = await window.showDirectoryPicker({ mode: "readwrite", id: "url2vid" });
    await saveHandle(handle);
    return handle;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return null;
    throw error;
  }
}

/**
 * Whether the handle is still usable, without prompting.
 *
 * "prompt" means the folder is remembered but the browser wants a click
 * before writing again, which is why the UI offers a Reconnect button rather
 * than silently failing on the next finished download.
 */
export async function checkPermission(handle: DirectoryHandle): Promise<PermissionState> {
  try {
    return await handle.queryPermission({ mode: "readwrite" });
  } catch {
    return "denied";
  }
}

/** Re-request write access. Must be called from a user gesture. */
export async function regrant(handle: DirectoryHandle): Promise<PermissionState> {
  try {
    return await handle.requestPermission({ mode: "readwrite" });
  } catch {
    return "denied";
  }
}

/** Stream a URL's body into `name` inside the chosen folder. */
export async function writeInto(handle: DirectoryHandle, name: string, sourceUrl: string): Promise<void> {
  const response = await fetch(sourceUrl);
  if (!response.ok || !response.body) {
    throw new Error(`The server would not hand over the file (${response.status}).`);
  }
  const fileHandle = await handle.getFileHandle(name, { create: true });
  const writable = await fileHandle.createWritable();
  try {
    // Piped rather than buffered: a 1 GB video must not have to fit in memory.
    await response.body.pipeTo(writable as unknown as WritableStream<Uint8Array>);
  } catch (error) {
    await writable.close().catch(() => {});
    throw error;
  }
}
