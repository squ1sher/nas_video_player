import { Navigate, Route, Routes } from "react-router-dom";
import { LibraryPage } from "./pages/LibraryPage";
import { WatchPage } from "./pages/WatchPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LibraryPage />} />
      <Route path="/watch/:id" element={<WatchPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

