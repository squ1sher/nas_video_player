import { Navigate, Route, Routes } from "react-router-dom";
import { GlobalStatusBar } from "./components/GlobalStatusBar";
import { LibraryPage } from "./pages/LibraryPage";
import { MaintenancePage } from "./pages/MaintenancePage";
import { SettingsPage } from "./pages/SettingsPage";
import { WatchPage } from "./pages/WatchPage";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<LibraryPage />} />
        <Route path="/watch/:id" element={<WatchPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/maintenance" element={<MaintenancePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <GlobalStatusBar />
    </>
  );
}
