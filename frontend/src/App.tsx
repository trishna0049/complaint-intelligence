import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { RequireAuth, RequireRole } from "@/auth/guards";
import { homeFor } from "@/auth/home";
import { Layout } from "@/components/Layout";
import { Card, EmptyState } from "@/components/ui";
import { CategoriesPage } from "@/pages/admin/CategoriesPage";
import { TeamsPage } from "@/pages/admin/TeamsPage";
import { UsersPage } from "@/pages/admin/UsersPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { MyWorkPage } from "@/pages/MyWorkPage";
import { NewTicketPage } from "@/pages/NewTicketPage";
import { TicketDetailPage } from "@/pages/TicketDetailPage";
import { TicketsPage } from "@/pages/TicketsPage";

/** Old /complaints/:id links keep working. */
function LegacyComplaintRedirect() {
  const { id } = useParams();
  return <Navigate to={id ? `/tickets/${id}` : "/tickets"} replace />;
}

/** "/" is the admin dashboard; agents land on their queue. */
function Home() {
  const { user } = useAuth();
  if (user && user.role !== "ADMIN") return <Navigate to={homeFor(user.role)} replace />;
  return <DashboardPage />;
}

export default function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="my-work" element={<MyWorkPage />} />
          <Route path="tickets" element={<TicketsPage />} />
          <Route path="tickets/new" element={<NewTicketPage />} />
          <Route path="tickets/:id" element={<TicketDetailPage />} />
          <Route path="complaints" element={<Navigate to="/tickets" replace />} />
          <Route path="complaints/:id" element={<LegacyComplaintRedirect />} />
          <Route path="admin" element={<RequireRole role="ADMIN" />}>
            <Route path="users" element={<UsersPage />} />
            <Route path="teams" element={<TeamsPage />} />
            <Route path="categories" element={<CategoriesPage />} />
          </Route>
          <Route path="*" element={<Card><EmptyState title="Page not found" /></Card>} />
        </Route>
      </Route>
    </Routes>
  );
}
