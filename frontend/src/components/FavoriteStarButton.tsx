import { useState } from "react";

type Props = {
  isFavorite: boolean;
  onToggle: (next: boolean) => Promise<unknown> | void;
};

/**
 * Star overlay used on media grid thumbnails. Shows an outline star on hover
 * for non-favorited items and a filled, always-visible star once favorited.
 * Toggles optimistically and rolls back if the API call fails.
 */
export function FavoriteStarButton({ isFavorite, onToggle }: Props) {
  const [favorite, setFavorite] = useState(isFavorite);
  const [busy, setBusy] = useState(false);

  const handleClick = async (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (busy) return;
    const next = !favorite;
    setFavorite(next);
    setBusy(true);
    try {
      await onToggle(next);
    } catch {
      setFavorite(!next);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      className={`media-favorite-btn${favorite ? " is-favorite" : ""}`}
      onClick={handleClick}
      title={favorite ? "Remove from favorites" : "Add to favorites"}
      aria-pressed={favorite}
    >
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <path d="M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279L12 19.771l-7.416 3.642 1.48-8.279L0 9.306l8.332-1.151z" />
      </svg>
    </button>
  );
}
