import { useState } from "react";

import type { DownloadOptions, Probe } from "../types";

interface Props {
  found: Probe;
  options: DownloadOptions;
  onChange: (options: DownloadOptions) => void;
  onDownload: () => void;
}

function runtime(seconds: number): string {
  const total = Math.round(seconds);
  const mins = Math.floor(total / 60);
  const secs = String(total % 60).padStart(2, "0");
  if (mins < 60) return `${mins}:${secs}`;
  return `${Math.floor(mins / 60)}:${String(mins % 60).padStart(2, "0")}:${secs}`;
}

/**
 * The result of a lookup: what was found, and how to take it.
 *
 * Thumbnail to the right, everything you choose on the left, and one action at
 * the bottom. Picking a resolution is a row of buttons rather than a dropdown
 * so every option is visible without a click.
 */
export function FoundPanel({ found, options, onChange, onDownload }: Props) {
  const [thumbFailed, setThumbFailed] = useState(false);

  const meta: string[] = [];
  if (found.extractor) meta.push(found.extractor);
  if (found.duration) meta.push(runtime(found.duration));
  if (!found.formats.length) meta.push("single stream");

  const set = (patch: Partial<DownloadOptions>) => onChange({ ...options, ...patch });
  const showThumb = found.thumbnail && !thumbFailed;

  return (
    <section className="found">
      <div className="found__top">
        <div className="found__info">
          <h2 className="found__title" title={found.title}>
            {found.title}
          </h2>
          {meta.length > 0 && <p className="found__meta">{meta.join(" · ")}</p>}
          {found.note && <p className="found__note">{found.note}</p>}

          {found.formats.length > 0 && (
            <div className="quality" data-disabled={options.audioOnly || undefined}>
              <span className="quality__label">Quality</span>
              <div className="quality__row">
                {found.formats.map((format) => (
                  <button
                    key={format.height}
                    type="button"
                    className={`chip ${
                      options.height === String(format.height) ? "chip--on" : ""
                    }`}
                    disabled={options.audioOnly}
                    onClick={() => set({ height: String(format.height) })}
                    title={format.size_label ? `about ${format.size_label}` : undefined}
                  >
                    {format.label}
                  </button>
                ))}
                <button
                  type="button"
                  className={`chip ${options.height === "best" ? "chip--on" : ""}`}
                  disabled={options.audioOnly}
                  onClick={() => set({ height: "best" })}
                >
                  Best
                </button>
              </div>
            </div>
          )}
        </div>

        {showThumb && (
          <div className="found__thumb">
            <img
              src={found.thumbnail ?? ""}
              alt=""
              loading="lazy"
              onError={() => setThumbFailed(true)}
            />
          </div>
        )}
      </div>

      <div className="found__options">
        <button
          type="button"
          className={`toggle ${options.audio && !options.audioOnly ? "toggle--on" : ""}`}
          disabled={options.audioOnly}
          aria-pressed={options.audio && !options.audioOnly}
          onClick={() => set({ audio: !options.audio })}
        >
          <span className="toggle__dot" />
          {options.audio ? "Audio on" : "Audio off"}
        </button>

        <button
          type="button"
          className={`toggle ${options.audioOnly ? "toggle--on" : ""}`}
          aria-pressed={options.audioOnly}
          onClick={() => set({ audioOnly: !options.audioOnly })}
        >
          <span className="toggle__dot" />
          Audio only
        </button>
      </div>

      <button className="button button--go" type="button" onClick={onDownload}>
        {options.audioOnly ? "Download audio" : "Download"}
      </button>
    </section>
  );
}
