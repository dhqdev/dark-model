import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, type ReactNode } from "react";
import { api } from "./api";

interface AuthStatus {
  configured: boolean;
  authenticated: boolean;
  app_name: string;
}

interface AuthCtx {
  status: AuthStatus | undefined;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["auth"],
    queryFn: () => api.get<AuthStatus>("/auth/status"),
    staleTime: 60_000,
  });

  useEffect(() => {
    const onUnauthorized = () => qc.setQueryData<AuthStatus>(["auth"], (s) => (s ? { ...s, authenticated: false } : s));
    window.addEventListener("dm:unauthorized", onUnauthorized);
    return () => window.removeEventListener("dm:unauthorized", onUnauthorized);
  }, [qc]);

  const login = useCallback(
    async (username: string, password: string) => {
      await api.post("/auth/login", { username, password });
      await qc.invalidateQueries();
    },
    [qc],
  );

  const logout = useCallback(async () => {
    await api.post("/auth/logout");
    qc.clear();
    qc.setQueryData<AuthStatus>(["auth"], { configured: true, authenticated: false, app_name: "Dark Model" });
  }, [qc]);

  return <Ctx.Provider value={{ status: data, loading: isLoading, login, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth fora do AuthProvider");
  return ctx;
}
