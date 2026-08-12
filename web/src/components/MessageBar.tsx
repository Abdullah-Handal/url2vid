import type { Message } from "../types";

const GLYPH: Record<Message["kind"], string> = {
  info: "•",
  busy: "◐",
  ok: "✓",
  warn: "!",
  error: "✗",
};

/** The running commentary. Every action lands here so nothing fails quietly. */
export function MessageBar({ message }: { message: Message | null }) {
  if (!message) return null;
  return (
    <p className={`message message--${message.kind}`} role="status" aria-live="polite">
      <span className="message__glyph" aria-hidden="true">
        {GLYPH[message.kind]}
      </span>
      {message.text}
    </p>
  );
}
