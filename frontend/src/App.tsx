import { ConnectScreen } from "./components/ConnectScreen";
import { AuthProvider, useAuth } from "./context/AuthContext";
import Dashboard from "./Dashboard";

function AppShell() {
  const { phase } = useAuth();
  if (phase !== "ready") {
    return <ConnectScreen />;
  }
  return <Dashboard />;
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}
