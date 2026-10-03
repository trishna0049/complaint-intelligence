import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Card, EmptyState } from "@/components/ui";
import { ComplaintDetailPage } from "@/pages/ComplaintDetailPage";
import { ComplaintsPage } from "@/pages/ComplaintsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { NewComplaintPage } from "@/pages/NewComplaintPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="complaints" element={<ComplaintsPage />} />
        <Route path="complaints/new" element={<NewComplaintPage />} />
        <Route path="complaints/:id" element={<ComplaintDetailPage />} />
        <Route path="*" element={<Card><EmptyState title="Page not found" /></Card>} />
      </Route>
    </Routes>
  );
}
