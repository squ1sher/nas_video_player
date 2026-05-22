import { useEffect, useMemo, useState } from "react";

import type { TagItem } from "../../types/video";

type Props = {
  open: boolean;
  title: string;
  tagsFlat: TagItem[];
  defaultParentId?: number | null;
  onClose: () => void;
  onConfirm: (payload: { name: string; parent_id: number | null; assignToVideo: boolean }) => Promise<void>;
  allowAssignToVideo?: boolean;
};

export function CreateTagDialog({
  open,
  title,
  tagsFlat,
  defaultParentId = null,
  onClose,
  onConfirm,
  allowAssignToVideo = false,
}: Props) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState<number | null>(defaultParentId);
  const [assignToVideo, setAssignToVideo] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setParentId(defaultParentId);
    }
  }, [defaultParentId, open]);

  const parentOptions = useMemo(() => {
    return tagsFlat.map((tag) => ({
      id: tag.id,
      label: `${"  ".repeat(tag.depth)}${tag.path}`,
    }));
  }, [tagsFlat]);

  if (!open) return null;

  const handleConfirm = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Tag name cannot be empty.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onConfirm({ name: trimmed, parent_id: parentId, assignToVideo });
      setName("");
      setParentId(defaultParentId);
      setAssignToVideo(true);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create tag.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box modal-box-sm" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="modal-close" onClick={onClose}>x</button>
        </div>
        <div className="modal-body">
          {error ? <div className="settings-error">{error}</div> : null}
          <label className="form-label">
            Name
            <input
              className="form-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Family"
            />
          </label>
          <label className="form-label">
            Parent
            <select
              className="form-input"
              value={parentId === null ? "" : String(parentId)}
              onChange={(event) => {
                const value = event.target.value;
                setParentId(value ? Number(value) : null);
              }}
            >
              <option value="">Top level</option>
              {parentOptions.map((option) => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>
          {allowAssignToVideo ? (
            <label className="form-label form-label-inline">
              <input
                type="checkbox"
                checked={assignToVideo}
                onChange={(event) => setAssignToVideo(event.target.checked)}
              />
              Assign to this video after create
            </label>
          ) : null}
        </div>
        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn-primary" onClick={() => void handleConfirm()} disabled={busy}>
            {busy ? "Creating..." : "Create tag"}
          </button>
        </div>
      </div>
    </div>
  );
}

