import { createBrowserRouter, isRouteErrorResponse, Link, RouterProvider, useRouteError } from "react-router";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { useAuth } from "./lib/auth";
import { ChannelDetail } from "./pages/ChannelDetail";
import { Channels } from "./pages/Channels";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Project } from "./pages/Project";
import { Queue } from "./pages/Queue";
import { Settings } from "./pages/Settings";
import { Usage } from "./pages/Usage";

function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "Erro inesperado";
  return (
    <div className="panel mx-auto mt-16 max-w-xl p-6">
      <div className="kicker mb-2">Falha de projeção</div>
      <h1 className="display mb-3 text-3xl font-light">Esta tela encontrou um erro</h1>
      <p className="mb-5 font-mono text-[12px] text-signal">{message}</p>
      <Link className="btn" to="/">
        Voltar ao console
      </Link>
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Dashboard />, errorElement: <RouteError /> },
      { path: "canais", element: <Channels />, errorElement: <RouteError /> },
      { path: "canais/:channelId", element: <ChannelDetail />, errorElement: <RouteError /> },
      { path: "projetos/:projectId", element: <Project />, errorElement: <RouteError /> },
      { path: "fila", element: <Queue />, errorElement: <RouteError /> },
      { path: "consumo", element: <Usage />, errorElement: <RouteError /> },
      { path: "ajustes", element: <Settings />, errorElement: <RouteError /> },
      { path: "*", element: <RouteError /> },
    ],
  },
]);

export function App() {
  const { status, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading label="Iniciando estúdio" />
      </div>
    );
  }
  if (!status?.authenticated) return <Login configured={status?.configured ?? true} />;
  return <RouterProvider router={router} />;
}
