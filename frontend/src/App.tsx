import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Card, EmptyState } from "@/components/ui";
import { DashboardPage } from "@/pages/DashboardPage";
import { NewTicketPage } from "@/pages/NewTicketPage";
import { TicketDetailPage } from "@/pages/TicketDetailPage";
import { TicketsPage } from "@/pages/TicketsPage";

/** Old /complaints/:id links keep working. */
function LegacyComplaintRedirect() {
  const { id } = useParams();
  return <Navigate to={id ? `/tickets/${id}` : "/tickets"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="tickets/new" element={<NewTicketPage />} />
        <Route path="tickets/:id" element={<TicketDetailPage />} />
        <Route path="complaints" element={<Navigate to="/tickets" replace />} />
        <Route path="complaints/:id" element={<LegacyComplaintRedirect />} />
        <Route path="*" element={<Card><EmptyState title="Page not found" /></Card>} />
      </Route>
    </Routes>
  );
}
