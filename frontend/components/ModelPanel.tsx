"use client";

import { useEffect, useState } from "react";
import { api, featureLabel } from "@/lib/api";
import type { ModelInfo } from "@/lib/types";

const pct = (v: number) => `${(v * 100).toFixed(0)} %`;

export default function ModelPanel({ refreshKey }: { refreshKey: number }) {
  const [m, setM] = useState<ModelInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<ModelInfo>("/model")
      .then((x) => { setM(x); setErr(null); })
      .catch((e) => { setM(null); setErr(e.message); });
  }, [refreshKey]);

  if (err)
    return (
      <section className="card p-5 text-sm text-ink2">
        Modèle indisponible : {err}
      </section>
    );
  if (!m) return null;

  const rows = [
    { key: "all_features", label: "Toutes les features" },
    { key: "without_unique_contracts_ratio", label: "Sans diversité des contrats" },
  ];
  const imp = Object.entries(m.importance).sort((a, b) => b[1] - a[1]);
  const top = imp[0]?.[1] || 1;

  return (
    <section className="card space-y-5 p-6">
      <div>
        <h2 className="display text-2xl">Modèle actuel</h2>
        <p className="mt-2 text-sm text-ink2">
          Entraîné sur {m.n_train} wallets dont {m.n_bots} bots. Validation croisée par groupe de contrat.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1 pr-3">Jeu de features</th>
              <th className="px-3 py-1">Accuracy</th>
              <th className="px-3 py-1">Précision</th>
              <th className="px-3 py-1">Rappel</th>
              <th className="px-3 py-1">AUC</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const c = m.cv[r.key];
              if (!c) return null;
              return (
                <tr key={r.key} className="border-t border-grid">
                  <td className="py-1.5 pr-3">{r.label}</td>
                  <td className="px-3 py-1.5">{pct(c.accuracy)}</td>
                  <td className="px-3 py-1.5">{pct(c.precision)}</td>
                  <td className="px-3 py-1.5">{pct(c.recall)}</td>
                  <td className="px-3 py-1.5">{c.roc_auc.toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-muted">Référence : répondre toujours « humain » donne 74 % d&apos;accuracy.</p>
      </div>
      <div>
        <p className="text-sm font-medium">Importance des features</p>
        <ul className="mt-2 space-y-1.5">
          {imp.map(([f, v]) => (
            <li key={f} className="grid grid-cols-[11rem_1fr_3rem] items-center gap-2 text-sm">
              <span className="truncate">{featureLabel(f)}</span>
              <span className="h-2.5 rounded-full bg-grid">
                <span className="block h-2.5 rounded-full bg-brand" style={{ width: `${(v / top) * 100}%` }} />
              </span>
              <span className="text-right text-ink2">{pct(v)}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
