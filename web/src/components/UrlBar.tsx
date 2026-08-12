import { type FormEvent } from "react";

interface Props {
  url: string;
  busy: boolean;
  onUrlChange: (url: string) => void;
  onFetch: () => void;
}

export function UrlBar({ url, busy, onUrlChange, onFetch }: Props) {
  function submit(event: FormEvent) {
    event.preventDefault();
    onFetch();
  }

  return (
    <form className="urlbar" onSubmit={submit}>
      <input
        className="urlbar__input"
        type="text"
        value={url}
        onChange={(event) => onUrlChange(event.target.value)}
        placeholder="Paste a video URL…"
        aria-label="Video URL"
        autoFocus
        spellCheck={false}
      />
      <button className="button button--primary" type="submit" disabled={busy}>
        {busy ? "Searching…" : "Fetch"}
      </button>
    </form>
  );
}
