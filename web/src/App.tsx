import { useCallback, useEffect, useState } from "react";

import * as api from "./api";
import * as folders from "./folder";
import * as native from "./native";
import type { DirectoryHandle } from "./folder";
import { FolderBar } from "./components/FolderBar";
import { FoundPanel } from "./components/FoundPanel";
import { JobRow } from "./components/JobRow";
import { MessageBar } from "./components/MessageBar";
import { UrlBar } from "./components/UrlBar";
import type { DownloadOptions, Job, Message, Probe, SaveInfo } from "./types";

const reason = (error: unknown) => (error instanceof Error ? error.message : String(error));

// Jobs already handed to the folder writer. Module-level, not a ref: React
// StrictMode remounts the component in development, which would rebuild a ref
// and let a second writable stream open on a file already being written.
const attempted = new Set<string>();

const DEFAULT_OPTIONS: DownloadOptions = { height: "best", audio: true, audioOnly: false };

export default function App() {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>({
    kind: "info",
    text: "Paste a link and press Enter, or click Fetch.",
  });
  const [found, setFound] = useState<Probe | null>(null);
  const [options, setOptions] = useState<DownloadOptions>(DEFAULT_OPTIONS);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [offline, setOffline] = useState(false);
  const [isNative, setIsNative] = useState(false);

  const [handle, setHandle] = useState<DirectoryHandle | null>(null);
  const [needsPermission, setNeedsPermission] = useState(false);
  const [defaultDir, setDefaultDir] = useState("the server's downloads folder");
  const [saves, setSaves] = useState<Record<string, SaveInfo>>({});

  const say = useCallback((kind: Message["kind"], text: string) => setMessage({ kind, text }), []);

  useEffect(() => {
    api.getConfig().then(
      (config) => setDefaultDir(config.download_dir),
      () => undefined, // a missing config is cosmetic; the app still works
    );
  }, []);

  useEffect(() => api.subscribeJobs(setJobs, setOffline), []);

  // pywebview attaches its API after load, so this cannot be decided on the
  // first render without sometimes falling back to browser mode by mistake.
  useEffect(() => {
    void native.whenReady().then(setIsNative);
  }, []);

  // Restore the remembered folder, and find out whether it still lets us write.
  useEffect(() => {
    if (isNative) return;
    let cancelled = false;
    void (async () => {
      const restored = await folders.loadHandle();
      if (cancelled || !restored) return;
      const permission = await folders.checkPermission(restored);
      if (cancelled) return;
      if (permission === "denied") {
        await folders.forgetHandle();
        return;
      }
      setHandle(restored);
      setNeedsPermission(permission !== "granted");
    })();
    return () => {
      cancelled = true;
    };
  }, [isNative]);

  // Write finished videos into the chosen folder, one attempt each.
  useEffect(() => {
    if (isNative || !handle || needsPermission) return;
    for (const job of jobs) {
      if (job.status !== "done" || !job.filename || attempted.has(job.id)) continue;
      attempted.add(job.id);
      const name = job.filename;
      setSaves((current) => ({ ...current, [job.id]: { state: "saving" } }));
      void folders
        .writeInto(handle, name, api.fileUrl(job.id))
        .then(() => {
          setSaves((current) => ({ ...current, [job.id]: { state: "saved" } }));
          say("ok", `Saved ${name} to ${handle.name}`);
        })
        .catch((error) => {
          setSaves((current) => ({
            ...current,
            [job.id]: { state: "error", detail: reason(error) },
          }));
          say("error", `Could not write ${name} to ${handle.name} — ${reason(error)}`);
        });
    }
  }, [jobs, handle, needsPermission, isNative, say]);

  const startDownload = useCallback(
    async (target: Probe, chosen: DownloadOptions) => {
      try {
        await api.startDownload(
          target.webpage_url,
          chosen.audioOnly || chosen.height === "best" ? null : Number(chosen.height),
          target.title,
          { audio: chosen.audio, audioOnly: chosen.audioOnly },
        );
        const what = chosen.audioOnly
          ? "audio only"
          : `${chosen.height === "best" ? "best quality" : `${chosen.height}p`}${
              chosen.audio ? "" : ", no audio"
            }`;
        say("ok", `Downloading “${target.title}” — ${what}…`);
        setFound(null);
        setUrl("");
      } catch (error) {
        say("error", reason(error));
      }
    },
    [say],
  );

  const fetchUrl = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      say("warn", "Nothing to fetch — paste a video URL in the box first.");
      return;
    }
    setFound(null);
    setBusy(true);
    say("busy", "Searching that link for a video…");
    try {
      const result = await api.probe(trimmed);
      setFound(result);
      setOptions(DEFAULT_OPTIONS);
      // Nothing to choose means nothing to ask about.
      if (result.auto) {
        await startDownload(result, DEFAULT_OPTIONS);
        setFound(result);
      } else {
        say("ok", `Found “${result.title}” — pick a resolution and press Download.`);
      }
    } catch (error) {
      say("error", reason(error));
    } finally {
      setBusy(false);
    }
  }, [url, say, startDownload]);

  const pickFolder = useCallback(async () => {
    if (isNative) {
      const result = await native.chooseFolder();
      if (result.cancelled) return;
      if (!result.ok || !result.download_dir) {
        say("error", result.error ?? "Could not change the folder.");
        return;
      }
      setDefaultDir(result.download_dir);
      say("ok", `Videos will be saved to ${result.download_dir} from now on.`);
      return;
    }
    try {
      const picked = await folders.pickFolder();
      if (!picked) return;
      setHandle(picked);
      setNeedsPermission(false);
      say("ok", `Videos will be saved to ${picked.name} from now on.`);
    } catch (error) {
      say("error", `Could not open the folder picker — ${reason(error)}`);
    }
  }, [isNative, say]);

  const reconnect = useCallback(async () => {
    if (!handle) return;
    const permission = await folders.regrant(handle);
    if (permission === "granted") {
      setNeedsPermission(false);
      say("ok", `Reconnected to ${handle.name}.`);
    } else {
      say("warn", `${handle.name} is still not writable. Pick the folder again.`);
    }
  }, [handle, say]);

  const forgetFolder = useCallback(async () => {
    await folders.forgetHandle();
    setHandle(null);
    setNeedsPermission(false);
    say("info", `Videos will stay in ${defaultDir}.`);
  }, [defaultDir, say]);

  const revealFolder = useCallback(() => {
    void native.revealDownloads();
  }, []);

  const cancel = useCallback(
    async (id: string) => {
      try {
        await api.cancelJob(id);
        say("busy", "Cancelling…");
      } catch (error) {
        say("warn", reason(error));
      }
    },
    [say],
  );

  const clear = useCallback(async () => {
    try {
      const { cleared } = await api.clearFinished();
      say("info", `Cleared ${cleared} finished download${cleared === 1 ? "" : "s"}.`);
    } catch (error) {
      say("warn", reason(error));
    }
  }, [say]);

  const finishedCount = jobs.filter((job) => ["done", "error", "cancelled"].includes(job.status)).length;

  return (
    <div className="app">
      <header className="header">
        <h1 className="header__title">url2vid</h1>
        <p className="header__tag">paste a link, get the video</p>
      </header>

      <UrlBar url={url} busy={busy} onUrlChange={setUrl} onFetch={fetchUrl} />

      <FolderBar
        native={isNative}
        supported={folders.isSupported()}
        folderName={handle?.name ?? null}
        needsPermission={needsPermission}
        defaultDir={defaultDir}
        onPick={pickFolder}
        onReconnect={reconnect}
        onForget={forgetFolder}
        onReveal={revealFolder}
      />

      <MessageBar message={message} />

      {offline && (
        <p className="message message--error" role="alert">
          <span className="message__glyph" aria-hidden="true">✗</span>
          Lost contact with the server. Is it still running?
        </p>
      )}

      {found && !found.auto && (
        <FoundPanel
          found={found}
          options={options}
          onChange={setOptions}
          onDownload={() => void startDownload(found, options)}
        />
      )}

      <section className="downloads">
        <div className="downloads__head">
          <h2 className="downloads__title">Downloads</h2>
          {finishedCount > 0 && (
            <button className="button button--small button--quiet" type="button" onClick={clear}>
              Clear finished
            </button>
          )}
        </div>

        {jobs.length === 0 ? (
          <p className="empty">Nothing yet. Paste a link above to get started.</p>
        ) : (
          <ul className="downloads__list">
            {jobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                save={saves[job.id]}
                folderName={handle?.name ?? null}
                native={isNative}
                onCancel={(id) => void cancel(id)}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
