interface Props {
  supported: boolean;
  folderName: string | null;
  needsPermission: boolean;
  defaultDir: string;
  onPick: () => void;
  onReconnect: () => void;
  onForget: () => void;
}

/**
 * The save-location bar.
 *
 * Picked once, the folder is remembered across restarts and becomes the
 * default for every later download. Without one, videos stay in the server's
 * own folder and each finished row offers a Save button instead.
 */
export function FolderBar({
  supported,
  folderName,
  needsPermission,
  defaultDir,
  onPick,
  onReconnect,
  onForget,
}: Props) {
  if (!supported) {
    return (
      <div className="folderbar folderbar--plain">
        <span className="folderbar__label">Saving to</span>
        <code className="folderbar__path" title={defaultDir}>
          {defaultDir}
        </code>
        <span className="folderbar__hint">
          This browser cannot pick a folder — use Save on a finished video to choose where it goes.
        </span>
      </div>
    );
  }

  if (folderName && needsPermission) {
    return (
      <div className="folderbar folderbar--warn">
        <span className="folderbar__label">Saving to</span>
        <code className="folderbar__path">{folderName}</code>
        <span className="folderbar__hint">Access needs renewing after a restart.</span>
        <button className="button button--small" type="button" onClick={onReconnect}>
          Reconnect
        </button>
      </div>
    );
  }

  if (folderName) {
    return (
      <div className="folderbar folderbar--set">
        <span className="folderbar__label">Saving to</span>
        <code className="folderbar__path">{folderName}</code>
        <button className="button button--small" type="button" onClick={onPick}>
          Change…
        </button>
        <button className="button button--small button--quiet" type="button" onClick={onForget}>
          Use default
        </button>
      </div>
    );
  }

  return (
    <div className="folderbar">
      <span className="folderbar__label">Saving to</span>
      <code className="folderbar__path" title={defaultDir}>
        {defaultDir}
      </code>
      <span className="folderbar__hint">(default)</span>
      <button className="button button--small button--primary" type="button" onClick={onPick}>
        Choose folder…
      </button>
    </div>
  );
}
