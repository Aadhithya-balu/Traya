import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { Emergency } from "./pages/Emergency";
import { EmergencyHub } from "./pages/EmergencyHub";
import { Demo } from "./pages/Demo";
import { Dashboard } from "./pages/Dashboard";
import { Profile } from "./pages/Profile";
import { Privacy } from "./pages/Privacy";
import { Admin } from "./pages/Admin";
import { Protected, AdminOnly } from "./components/Guards";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/emergency" element={<Emergency />} />
        <Route path="/emergency/:sessionId" element={<EmergencyHub />} />
        <Route path="/demo" element={<Demo />} />
        <Route
          path="/dashboard"
          element={
            <Protected>
              <Dashboard />
            </Protected>
          }
        />
        <Route
          path="/profile"
          element={
            <Protected>
              <Profile />
            </Protected>
          }
        />
        <Route
          path="/admin"
          element={
            <AdminOnly>
              <Admin />
            </AdminOnly>
          }
        />
        <Route path="*" element={<Landing />} />
      </Route>
    </Routes>
  );
}
