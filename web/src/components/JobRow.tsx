import type { Job, SaveInfo } from "../types";
import { fileUrl } from "../api";

interface Props {
  job: Job;
  save?: SaveInfo;
  folderName: string | null;
  onCancel: (id: string) => void;
}

const STATUS_WORD: Record<Job["status"], string> = {
  queued: "waiting",
  downloading: "",
  merging: "merging",
  done: "done",
  error: "failed",
  cancelled: "cancelled",
};

export function JobRow({ job, save, folderName, onCancel }: Props) {
  const running = job.status === "downloading";
  const pct = job.percent;
  const finished = job.status === "done";

  return (
    <li className={`job job--${job.status}`}>
      <div className="job__head">
        <span className="job__title" title={job.title}>
          {job.title}
        </span>
        <span className="job__res">{job.height ? `${job.height}p` : "best"}</span>
      </div>

      {job.status === "error" ? (
        <p className="job__error">{job.error ?? "The download failed."}</p>
      ) : (
        <>
          <div
            className="bar"
            role="progressbar"
            aria-valuenow={pct ?? undefined}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            {/* An unknown total shows a moving stripe rather than a fake width. */}
            <div
              className={`bar__fill ${pct === null ? "bar__fill--unknown" : ""}`}
              style={{ width: pct === null ? "100%" : `${pct}%` }}
            />
          </div>

          <div className="job__meta">
            <span className="job__pct">{pct === null ? "—" : `${pct.toFixed(1)}%`}</span>
            <span className="job__word">
              {running ? job.eta_label || "…" : STATUS_WORD[job.status]}
              {running && job.speed_label ? ` · ${job.speed_label}` : ""}
            </span>
            <span className="job__size">{job.size_label}</span>
          </div>
        </>
      )}

      <div className="job__actions">
        {!finished && job.status !== "error" && job.status !== "cancelled" && (
          <button className="button button--small button--quiet" type="button" onClick={() => onCancel(job.id)}>
            Cancel
          </button>
        )}

        {finished && save?.state === "saving" && <span className="job__save">Saving to {folderName}…</span>}
        {finished && save?.state === "saved" && (
          <span className="job__save job__save--ok">✓ Saved to {folderName}</span>
        )}
        {finished && save?.state === "error" && (
          <span className="job__save job__save--bad">Could not write to {folderName}: {save.detail}</span>
        )}

        {/* Always offered: it is the only route when no folder is set, and the
            way to put a second copy somewhere else when one is. */}
        {finished && (
          <a className="button button--small" href={fileUrl(job.id)} download={job.filename ?? undefined}>
            Save…
          </a>
        )}
      </div>
    </li>
  );
}
