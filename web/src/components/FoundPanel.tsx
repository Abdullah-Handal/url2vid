import type { Probe } from "../types";

interface Props {
  found: Probe;
  height: string;
  onHeightChange: (height: string) => void;
  onDownload: () => void;
}

/** What the lookup turned up: the title, where it came from, and the choices. */
export function FoundPanel({ found, height, onHeightChange, onDownload }: Props) {
  const bits: string[] = [];
  if (found.extractor) bits.push(found.extractor);
  if (found.duration) {
    const total = Math.round(found.duration);
    bits.push(`${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`);
  }
  bits.push(
    found.formats.length
      ? `${found.formats.length} resolution${found.formats.length === 1 ? "" : "s"}`
      : "single stream",
  );
  if (found.note) bits.push(found.note);

  return (
    <section className="found">
      <h2 className="found__title">{found.title}</h2>
      <p className="found__detail">{bits.join(" · ")}</p>

      {found.formats.length > 0 && (
        <div className="found__actions">
          <select
            className="select"
            value={height}
            onChange={(event) => onHeightChange(event.target.value)}
            aria-label="Resolution"
          >
            <option value="best">Best available</option>
            {found.formats.map((format) => (
              <option key={format.height} value={String(format.height)}>
                {format.label}
                {format.size_label ? `  (${format.size_label})` : ""}
              </option>
            ))}
          </select>
          <button className="button button--go" type="button" onClick={onDownload}>
            Download
          </button>
        </div>
      )}
    </section>
  );
}
