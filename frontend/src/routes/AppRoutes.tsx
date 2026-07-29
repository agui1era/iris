import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "../components/Layout";
import { AdminPage } from "../pages/AdminPage";
import { HistoryPage } from "../pages/HistoryPage";
import { LatestPage } from "../pages/LatestPage";
import { LoginPage } from "../pages/LoginPage";
import { AdminRoute, ProtectedRoute } from "./ProtectedRoute";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<LatestPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route element={<AdminRoute />}>
            <Route path="/admin" element={<AdminPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
