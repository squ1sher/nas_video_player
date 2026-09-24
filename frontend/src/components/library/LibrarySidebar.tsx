type LibraryMode = "videos" | "photos" | "all";
type Tab = "all" | "folders" | "playlists" | "favorites";

type NavTarget = {
  id: string;
  label: string;
  mode: LibraryMode;
  tab: Tab;
  icon: string;
};

type Props = {
  mode: LibraryMode;
  tab: Tab;
  onNavigate: (mode: LibraryMode, tab: Tab) => void;
};

const LIBRARY_ITEMS: NavTarget[] = [
  { id: "library", label: "Library", mode: "all", tab: "all", icon: "🖼️" },
  { id: "videos", label: "Videos", mode: "videos", tab: "all", icon: "🎬" },
  { id: "photos", label: "Photos", mode: "photos", tab: "all", icon: "📷" },
  { id: "favorites", label: "Favorites", mode: "all", tab: "favorites", icon: "⭐" },
];

const FOLDER_ITEMS: NavTarget[] = [
  { id: "video-folders", label: "Video Folders", mode: "videos", tab: "folders", icon: "📁" },
  { id: "photo-folders", label: "Photo Folders", mode: "photos", tab: "folders", icon: "📁" },
];

const PLAYLIST_ITEMS: NavTarget[] = [
  { id: "playlists", label: "Playlists", mode: "videos", tab: "playlists", icon: "🎵" },
];

/** macOS Photos-style left sidebar: flat single-select navigation grouped into sections. */
export function LibrarySidebar({ mode, tab, onNavigate }: Props) {
  const isActive = (item: NavTarget) => mode === item.mode && tab === item.tab;

  const renderGroup = (title: string, items: NavTarget[]) => (
    <div className="photos-sidebar-section" key={title}>
      <div className="photos-sidebar-heading">{title}</div>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className={isActive(item) ? "photos-sidebar-item active" : "photos-sidebar-item"}
          onClick={() => onNavigate(item.mode, item.tab)}
        >
          <span className="photos-sidebar-icon" aria-hidden="true">{item.icon}</span>
          <span>{item.label}</span>
        </button>
      ))}
    </div>
  );

  return (
    <aside className="photos-sidebar">
      {renderGroup("Library", LIBRARY_ITEMS)}
      {renderGroup("Folders", FOLDER_ITEMS)}
      {renderGroup("Playlists", PLAYLIST_ITEMS)}
    </aside>
  );
}
