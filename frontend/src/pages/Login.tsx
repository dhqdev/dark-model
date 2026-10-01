import { useState, type FormEvent } from "react";
import { Logo } from "../components/Layout";
import { ErrorBox } from "../components/ui";
import { useAuth } from "../lib/auth";

export function Login({ configured }: { configured: boolean }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen md:grid-cols-[1.15fr_1fr]">
      <div className="relative hidden flex-col justify-between overflow-hidden border-r border-line bg-coal p-12 md:flex">
        <Logo />
        <div>
          <div className="kicker mb-4">Rolo 01 · Cena 01 · Take 01</div>
          <h1 className="display max-w-xl text-[64px] leading-[0.98] font-light tracking-tight">
            Do roteiro ao <em className="text-amber">corte final</em>, sem aparecer na câmera.
          </h1>
          <p className="mt-6 max-w-md text-[14px] leading-relaxed text-muted">
            Canais, Skills, cenas, imagens, vídeos, narração, thumbnails e metadados num só estúdio — com custo real de cada etapa.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-px border border-line bg-line font-mono text-[10px] tracking-[0.16em] text-dim uppercase">
          {["Roteiro", "Cenas", "Visuais", "Narração", "Thumbnail", "Exportação"].map((s, i) => (
            <div key={s} className="bg-coal px-3 py-2.5">
              <span className="text-amber">{String(i + 1).padStart(2, "0")}</span> {s}
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="panel w-full max-w-sm p-7">
          <div className="mb-6 md:hidden">
            <Logo />
          </div>
          <div className="kicker mb-2">Acesso restrito</div>
          <h2 className="display mb-6 text-[30px] font-light">Entrar no estúdio</h2>
          {!configured && (
            <div className="mb-4 border-l-2 border-amber bg-amber/5 px-3 py-2 text-[13px]">
              Defina <code className="font-mono text-amber">APP_USERNAME</code> e <code className="font-mono text-amber">APP_PASSWORD</code> na Stack do Portainer para liberar o acesso.
            </div>
          )}
          <label className="mb-4 block">
            <span className="label">Usuário</span>
            <input className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label className="mb-6 block">
            <span className="label">Senha</span>
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error ? (
            <div className="mb-4">
              <ErrorBox error={error} title="Falha" />
            </div>
          ) : null}
          <button type="submit" className="btn btn-primary w-full" disabled={busy || !configured}>
            {busy ? <span className="led led-run" /> : null} Entrar
          </button>
        </form>
      </div>
    </div>
  );
}
