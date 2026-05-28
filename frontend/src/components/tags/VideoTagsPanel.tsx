import { useEffect, useMemo, useState } from "react";

import { addVideoTags, getVideoTags, removeVideoTag } from "../../api/client";
import type { VideoTag } from "../../types/video";
import { TagChip } from "./TagChip";
import { TagSelectorDialog } from "./TagSelectorDialog";

type Props = {
  videoId: number;
  onTagsChanged?: (tags: VideoTag[]) => void;
};

export function VideoTagsPanel({ videoId, onTagsChanged }: Props) {
  const [assignedTags, setAssignedTags] = useState<VideoTag[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [selectorOpen, setSelectorOpen] = useState(false);

  const assignedIds = useMemo(() => new Set(assignedTags.map((tag) => tag.id)), [assignedTags]);

  const loadAll = async () => {
    setLoading(true);
    try {
      const videoTags = await getVideoTags(videoId);
      setAssignedTags(videoTags);
      onTagsChanged?.(videoTags);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tags.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  const handleAssignSelected = async (selectedToAdd: number[]) => {
    const newTagIds = selectedToAdd.filter((id) => !assignedIds.has(id));
    if (newTagIds.length === 0) {
      return;
    }
    const updated = await addVideoTags(videoId, newTagIds);
    setAssignedTags(updated);
    onTagsChanged?.(updated);
    setMessage(`Added ${newTagIds.length} tag(s).`);
  };

  const handleTreeSaved = async () => {
    const updated = await getVideoTags(videoId);
    setAssignedTags(updated);
    onTagsChanged?.(updated);
    setMessage("Tag tree updated.");
  };

  const handleRemove = async (tagId: number) => {
    setBusy(true);
    setError(null);
    try {
      await removeVideoTag(videoId, tagId);
      const updated = await getVideoTags(videoId);
      setAssignedTags(updated);
      onTagsChanged?.(updated);
      setMessage("Tag removed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove tag.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="watch-tags-panel">
      <div className="watch-tags-header">
        <h2>Tags</h2>
        <div className="watch-tags-actions">
          <button className="btn-secondary" onClick={() => setSelectorOpen(true)} disabled={loading || busy}>Add tags</button>
        </div>
      </div>

      {loading ? <div className="settings-loading">Loading tags...</div> : null}
      {error ? <div className="settings-error">{error}</div> : null}
      {message ? <div className="settings-notice">{message}</div> : null}

      <div className="watch-tag-chip-list">
        {assignedTags.length === 0 ? (
          <span className="watch-tag-empty">No tags assigned.</span>
        ) : (
          assignedTags.map((tag) => (
            <TagChip key={tag.id} tag={tag} removable onRemove={(tagId) => void handleRemove(tagId)} />
          ))
        )}
      </div>

      <TagSelectorDialog
        open={selectorOpen}
        title="Add tags"
        confirmLabel="Add selected"
        disabledIds={assignedIds}
        onClose={() => setSelectorOpen(false)}
        onApply={handleAssignSelected}
        onTreeSaved={handleTreeSaved}
      />
    </section>
  );
}

