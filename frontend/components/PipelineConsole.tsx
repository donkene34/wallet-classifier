"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ModelInfo, PipelineStatus, PipelineStep } from "@/lib/types";
import ModelPanel from "@/components/ModelPanel";
import Window from "@/components/Window";

const DESCRIPTIONS: Record<string, string> = {
  collect: "Télécharge les transactions des 179 wallets de labels.csv via Etherscan. Long (plusieurs minutes) et consomme ton quota.",
  features: "Calcule les 8 features depuis le cache local (aucun appel Etherscan).",
  clustering: "KMeans + DBSCAN + PCA, régénère les images et clusters.json.",
  train: "Entraîne XGBoost, évalue en validation croisée et sauvegarde le modèle.",
  rebuild: "Enchaîne features, clustering et entraînement (sans la collecte).",
};

const STATE_LABELS: Record<PipelineStatus["state"], string> = {
  idle: "Aucune tâche",
  running: "En cours",
  done: "Terminé",
  failed: "Échec",
  cancelled: "Annulé",
};
const STATE_MARK: Record<PipelineStatus["state"], string> = { idle: "○", running: "◔", done: "✓", failed: "✕", cancelled: "■" };

export default function PipelineConsole() {
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmCollect, setConfirmCollect] = useState(false);
  const next = useRef(0);
  const box = useRef<HTMLPreElement>(null);

  const poll = useCallback(async () => {
    try {
      const s = await api<PipelineStatus>("/pipeline/status");
      setStatus(s);
      if (s.lines_total < next.current) {
        next.current = 0; // nouvelle tâche : on repart de zéro
        setLines([]);
      }
      const l = await api<{ lines: string[]; next: number }>(`/pipeline/logs?since=${next.current}`);
      if (l.lines.length) setLines((prev) => [...prev, ...l.lines].slice(-3000));
      next.current = l.next;
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    api<PipelineStep[]>("/pipeline/steps").then(setSteps).catch(() => {});
    poll();
    const id = setInterval(poll, 1000);
    return () => clearInterval(id);
  }, [poll]);

  useEffect(() => {
    const el = box.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const running = status?.state === "running";

  async function start(step: string) {
    setConfirmCollect(false);
    try {
      next.current = 0;
      setLines([]);
      await api(`/pipeline/${step}`, { method: "POST" });
      await poll();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function cancel() {
    try {
      await api("/pipeline/cancel", { method: "POST" });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="display text-4xl sm:text-5xl">Pipeline</h1>
        <p className="mt-3 text-ink2">Lance les étapes du projet sans passer par le terminal. Une seule tâche à la fois.</p>
      </header>

      {error && (
        <div role="alert" className="card !border-err p-4 text-sm">
          <span className="font-medium text-err">! </span>
          {error}
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-2">
        {steps.map((s) => {
          const isCollect = s.step === "collect";
          const mine = status?.step === s.step && running;
          return (
            <div key={s.step} className="card flex flex-col justify-between p-5">
              <div>
                <p className="font-medium">{s.label}</p>
                <p className="mt-1 text-sm text-ink2">{DESCRIPTIONS[s.step]}</p>
              </div>
              <div className="mt-3 flex items-center gap-2">
                {isCollect && confirmCollect ? (
                  <>
                    <button
                      onClick={() => start(s.step)}
                      className="rounded-full bg-bot px-5 py-2 text-sm font-medium text-white"
                    >
                      Confirmer la collecte
                    </button>
                    <button onClick={() => setConfirmCollect(false)} className="text-sm text-ink2 underline">
                      Annuler
                    </button>
                  </>
                ) : (
                  <button
                    disabled={running}
                    onClick={() => (isCollect ? setConfirmCollect(true) : start(s.step))}
                    className="btn-primary px-5 py-2 text-sm"
                  >
                    {mine ? "En cours…" : "Lancer"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </section>

      <section>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm">
            <span aria-hidden>{status ? STATE_MARK[status.state] : "○"} </span>
            <span className="font-medium">{status ? STATE_LABELS[status.state] : "…"}</span>
            {status?.label && <span className="text-ink2"> · {status.label}</span>}
          </p>
          {running && (
            <button onClick={cancel} className="rounded-full border border-err px-3.5 py-1 text-sm text-err">
              Annuler la tâche
            </button>
          )}
        </div>
        <Window title="terminal · python" className="mt-3">
          <pre
            ref={box}
            aria-live="off"
            className="h-80 overflow-auto p-4 font-mono text-xs leading-5 text-ink2 whitespace-pre-wrap"
          >
            {lines.length ? lines.join("\n") : "Les logs apparaîtront ici."}
          </pre>
        </Window>
      </section>

      <ModelPanel refreshKey={status?.finished_at ?? 0} />
    </div>
  );
}

export type { ModelInfo };
