export type JobStatus =
  | "queued"
  | "downloading"
  | "merging"
  | "done"
  | "error"
  | "cancelled";

/** One row of the download table, mirroring `Job.as_dict()` on the server. */
export interface Job {
  id: string;
  url: string;
  title: string;
  height: number | null;
  status: JobStatus;
  percent: number | null;
  eta_label: string;
  size_label: string;
  downloaded_label: string;
  speed_label: string;
  estimated: boolean;
  error: string | null;
  filename: string | null;
  created_at: number;
}

export interface Format {
  height: number;
  label: string;
  size_label: string;
}

export interface Probe {
  title: string;
  duration: number | null;
  extractor: string | null;
  webpage_url: string;
  formats: Format[];
  note: string | null;
  /** True when there is no resolution to choose, so the download can just start. */
  auto: boolean;
}

export type MessageKind = "info" | "busy" | "ok" | "warn" | "error";

export interface Message {
  kind: MessageKind;
  text: string;
}

/** Where a finished video has got to on its way to the chosen folder. */
export type SaveState = "saving" | "saved" | "error";

export interface SaveInfo {
  state: SaveState;
  detail?: string;
}
