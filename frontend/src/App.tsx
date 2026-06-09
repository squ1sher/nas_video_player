import { Navigate, Route, Routes } from "react-router-dom";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { GlobalStatusBar } from "./components/GlobalStatusBar";
import { LibraryPage } from "./pages/LibraryPage";
import { MaintenancePage } from "./pages/MaintenancePage";
import { PhotoPage } from "./pages/PhotoPage";
import { PlaylistDetailPage } from "./pages/PlaylistDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WatchPage } from "./pages/WatchPage";

export default function App() {
  return (
    <>
      <AppErrorBoundary>
        <Routes>
          <Route path="/" element={<LibraryPage />} />
          <Route path="/playlist/:id" element={<PlaylistDetailPage />} />
          <Route path="/watch/:id" element={<WatchPage />} />
          <Route path="/photo/:id" element={<PhotoPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/maintenance" element={<MaintenancePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppErrorBoundary>
      <GlobalStatusBar />
    </>
  );
}
