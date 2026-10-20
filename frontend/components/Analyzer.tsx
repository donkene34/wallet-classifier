"use client";

import { useCallback, useEffect, useState } from "react";
import { api, featureLabel, formatFeature, shortAddr, takePendingAddress } from "@/lib/api";
import type { AnalyzeResult, Example } from "@/lib/types";
import Window from "@/components/Window";

const CATEGORY_LABELS: Record<string, string> = {
  mev_sandwich: "bot MEV",
  private_contract_caller: "contrat privé",
  dao_voter: "votant DAO",
  dao_contributor: "contributeur DAO",
  public_figure: "personnalité",
};

export default function Analyzer() {
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [examples, setExamples] = useState<Example[]>([]);

  const analyze = useCallback(async (addr: string) => {
    const a = addr.trim();
    if (!a) return;
    setAddress(a);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api<AnalyzeResult>(`/analyze/${encodeURIComponent(a)}`));
    } catch (e) {
      const err = e as { status?: number; message: string };
      setError({ status: err.status ?? 0, message: err.message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    api<Example[]>("/examples").then(setExamples).catch(() => {});
    const pending = takePendingAddress();
    if (pending) analyze(pending);
  }, [analyze]);

  return (
    <div className="space-y-8">
      <section className="mx-auto max-w-3xl pt-4 text-center">
        <p className="mx-auto inline-flex items-center gap-2 rounded-full border border-grid bg-surface px-3 py-1 text-xs text-ink2">
          <span className="h-1.5 w-1.5 rounded-full bg-brand" aria-hidden />
          Ethereum · 90 jours de transactions · XGBoost
        </p>
        <h1 className="display mt-5 text-5xl sm:text-6xl">Bot ou humain&nbsp;?</h1>
        <p className="mx-auto mt-4 max-w-xl text-lg leading-7 text-ink2">
          Colle une adresse Ethereum : le modèle lit son comportement on-chain et estime s&apos;il s&apos;agit d&apos;un
          bot.
        </p>
        <form
          className="card mx-auto mt-8 flex items-center gap-2 !rounded-full p-1.5 pl-5"
          onSubmit={(e) => {
            e.preventDefault();
            analyze(address);
          }}
        >
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="0x…"
            spellCheck={false}
            aria-label="Adresse Ethereum"
            className="min-w-0 flex-1 bg-transparent py-2 font-mono text-sm outline-none placeholder:text-muted"
          />
          <button
            type="submit"
            disabled={loading || !address.trim()}
            className="btn-primary shrink-0 px-6 py-2.5 text-sm"
          >
            {loading ? "Analyse…" : "Analyser"}
          </button>
        </form>

        {examples.length > 0 && (
          <div className="mt-6 space-y-2.5">
            <p className="text-xs text-muted">
              Essaie un exemple du dataset (le modèle l&apos;a vu à l&apos;entraînement : ce n&apos;est pas un test
              indépendant)
            </p>
            {(["bot", "human"] as const).map((cls) => (
              <div key={cls} className="flex flex-wrap items-center justify-center gap-2">
                <span className="w-16 text-right text-xs font-medium text-ink2">{cls === "bot" ? "Bots" : "Humains"}</span>
                {examples
                  .filter((x) => x.dataset_label === cls)
                  .map((x) => (
                    <button
                      key={x.address}
                      type="button"
                      disabled={loading}
                      onClick={() => analyze(x.address)}
                      title={x.address}
                      className="chip px-3 py-1 text-xs disabled:opacity-50"
                    >
                      <span className="font-mono">{shortAddr(x.address)}</span>
                      <span className="ml-1.5 text-muted">
                        {x.tx_count.toLocaleString("fr-FR")} tx
                        {x.category ? ` · ${CATEGORY_LABELS[x.category] ?? x.category}` : ""}
                      </span>
                    </button>
                  ))}
              </div>
            ))}
          </div>
        )}
      </section>

      {loading && (
        <div role="status" className="card mx-auto max-w-3xl p-5 text-sm text-ink2">
          Récupération des transactions sur Etherscan… Un wallet très actif peut prendre jusqu&apos;à une minute.
        </div>
      )}

      {error && <ErrorBox status={error.status} message={error.message} />}
      {result && <ResultCard r={result} />}
      {!result && !loading && !error && <HowItWorks />}
    </div>
  );
}

function ErrorBox({ status, message }: { status: number; message: string }) {
  const title =
    status === 422 ? "Pas assez de transactions" : status === 400 ? "Adresse invalide" : "Analyse impossible";
  return (
    <div role="alert" className="card mx-auto max-w-3xl !border-err p-5">
      <p className="font-medium text-err">
        <span aria-hidden>! </span>
        {title}
      </p>
      <p className="mt-1 text-sm text-ink2">{message}</p>
    </div>
  );
}

function ResultCard({ r }: { r: AnalyzeResult }) {
  const pct = r.bot_probability * 100;
  const isBot = r.label === "bot";
  const maxC = Math.max(...r.top_features.map((f) => Math.abs(f.contribution)), 1e-9);
  return (
    <Window title={`Analyse · ${r.address}`} className="mx-auto max-w-3xl">
    <section className="space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-sm text-ink2 break-all">{r.address}</p>
        <span
          className="rounded-full px-3.5 py-1 text-sm font-semibold text-white"
          style={{ background: isBot ? "var(--bot)" : "var(--human)" }}
        >
          {isBot ? "▲ Bot" : "● Humain"}
        </span>
      </div>

      <div>
        <div className="flex items-baseline justify-between">
          <p className="text-sm text-ink2">Probabilité d&apos;être un bot</p>
          <p className="display text-6xl">{pct.toFixed(1)} %</p>
        </div>
        <div className="relative mt-3 h-3.5 rounded-full bg-grid" role="img" aria-label={`${pct.toFixed(1)} % bot`}>
          <div
            className="h-3.5 rounded-full"
            style={{ width: `${pct}%`, background: isBot ? "var(--bot)" : "var(--human)" }}
          />
          <div className="absolute top-[-4px] h-[22px] w-0.5 rounded bg-ink" style={{ left: "50%" }} />
        </div>
        <div className="mt-1 flex justify-between text-xs text-muted">
          <span>0 % · humain</span>
          <span>seuil 50 %</span>
          <span>100 % · bot</span>
        </div>
      </div>

      <div>
        <p className="text-sm font-medium">Ce qui a pesé le plus</p>
        <div className="mt-1 flex justify-between text-xs text-muted">
          <span>← vers humain</span>
          <span>vers bot →</span>
        </div>
        <ul className="mt-1 space-y-3">
          {r.top_features.map((f) => {
            const w = (Math.abs(f.contribution) / maxC) * 50;
            const toBot = f.contribution > 0;
            return (
              <li key={f.feature}>
                <div className="flex justify-between text-sm">
                  <span>{featureLabel(f.feature)}</span>
                  <span className="text-ink2">{formatFeature(f.feature, f.value)}</span>
                </div>
                <div className="relative mt-1 h-2.5 rounded-full bg-grid">
                  <div className="absolute top-[-2px] left-1/2 h-[14px] w-px bg-axis" />
                  <div
                    className="absolute h-2.5 rounded-full"
                    style={{
                      width: `${w}%`,
                      left: toBot ? "50%" : `${50 - w}%`,
                      background: toBot ? "var(--bot)" : "var(--human)",
                    }}
                  />
                </div>
                <p className="mt-0.5 text-xs text-muted">{toBot ? "pousse vers bot" : "pousse vers humain"}</p>
              </li>
            );
          })}
        </ul>
      </div>

      <p className="text-xs text-muted">{r.tx_analyzed.toLocaleString("fr-FR")} transactions analysées sur 90 jours.</p>
    </section>
    </Window>
  );
}

const POINTS = [
  "Récupère les transactions sortantes des 90 derniers jours via Etherscan",
  "Calcule 8 features de comportement : rythme, régularité, diversité des contrats, heures d'activité…",
  "XGBoost donne une probabilité, avec les 3 features qui ont le plus pesé (SHAP)",
  "Refuse l'analyse en dessous de 10 transactions plutôt que de deviner",
];

function HowItWorks() {
  return (
    <section className="card mx-auto max-w-3xl p-6">
      <h2 className="display text-2xl">Comment ça marche</h2>
      <ul className="mt-4 space-y-3">
        {POINTS.map((t) => (
          <li key={t} className="flex gap-3 text-ink2">
            <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-ok/20 text-ok" aria-hidden>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12.5l4.5 4.5L19 7" />
              </svg>
            </span>
            {t}
          </li>
        ))}
      </ul>
    </section>
  );
}
