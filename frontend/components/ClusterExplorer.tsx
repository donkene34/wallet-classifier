"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setPendingAddress, shortAddr } from "@/lib/api";
import type { ClusterPoint, ClustersData } from "@/lib/types";
import Window from "@/components/Window";

type Mode = "labels" | "kmeans" | "dbscan";
const MODES: { id: Mode; label: string }[] = [
  { id: "labels", label: "Vrais labels" },
  { id: "kmeans", label: "KMeans" },
  { id: "dbscan", label: "DBSCAN" },
];

const W = 760;
const H = 480;
const M = { l: 52, r: 16, t: 14, b: 44 };
const CLUSTER_COLORS = ["var(--c1)", "var(--c2)", "var(--c3)"];
const CLUSTER_SHAPES = ["circle", "square", "triangle"] as const;
type Shape = "circle" | "square" | "triangle" | "cross";

type Style = { color: string; shape: Shape; key: string; name: string };

function styleOf(p: ClusterPoint, mode: Mode): Style {
  if (mode === "labels")
    return p.label === "bot"
      ? { color: "var(--bot)", shape: "triangle", key: "bot", name: "Bot" }
      : { color: "var(--human)", shape: "circle", key: "human", name: "Humain" };
  const c = mode === "kmeans" ? p.kmeans : p.dbscan;
  if (c < 0) return { color: "var(--muted)", shape: "cross", key: "noise", name: "Bruit" };
  const r = Math.min(c, 2);
  return { color: CLUSTER_COLORS[r], shape: CLUSTER_SHAPES[r], key: `c${c}`, name: `Cluster ${c}` };
}

function Mark({ x, y, s, size = 6, ring = true }: { x: number; y: number; s: Style; size?: number; ring?: boolean }) {
  const stroke = ring ? "var(--surface)" : "none";
  switch (s.shape) {
    case "square":
      return <rect x={x - size} y={y - size} width={size * 2} height={size * 2} fill={s.color} stroke={stroke} strokeWidth={1.5} />;
    case "triangle":
      return (
        <polygon
          points={`${x},${y - size - 1} ${x + size + 1},${y + size} ${x - size - 1},${y + size}`}
          fill={s.color}
          stroke={stroke}
          strokeWidth={1.5}
        />
      );
    case "cross":
      return (
        <path d={`M${x - size} ${y - size}L${x + size} ${y + size}M${x - size} ${y + size}L${x + size} ${y - size}`} stroke={s.color} strokeWidth={2} />
      );
    default:
      return <circle cx={x} cy={y} r={size} fill={s.color} stroke={stroke} strokeWidth={1.5} />;
  }
}

function ticks(min: number, max: number, n = 9) {
  const raw = (max - min) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

export default function ClusterExplorer() {
  const router = useRouter();
  const [data, setData] = useState<ClustersData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("labels");
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hover, setHover] = useState<ClusterPoint | null>(null);
  const [selected, setSelected] = useState<ClusterPoint | null>(null);

  useEffect(() => {
    api<ClustersData>("/clusters").then(setData).catch((e) => setError(e.message));
  }, []);

  const scale = useMemo(() => {
    if (!data) return null;
    const xs = data.points.map((p) => p.pc1);
    const ys = data.points.map((p) => p.pc2);
    const padX = (Math.max(...xs) - Math.min(...xs)) * 0.06 || 1;
    const padY = (Math.max(...ys) - Math.min(...ys)) * 0.06 || 1;
    const x0 = Math.min(...xs) - padX, x1 = Math.max(...xs) + padX;
    const y0 = Math.min(...ys) - padY, y1 = Math.max(...ys) + padY;
    return {
      x0, x1, y0, y1,
      sx: (v: number) => M.l + ((v - x0) / (x1 - x0)) * (W - M.l - M.r),
      sy: (v: number) => H - M.b - ((v - y0) / (y1 - y0)) * (H - M.t - M.b),
    };
  }, [data]);

  const legend = useMemo(() => {
    if (!data) return [];
    const map = new Map<string, { s: Style; n: number }>();
    for (const p of data.points) {
      const s = styleOf(p, mode);
      map.set(s.key, { s, n: (map.get(s.key)?.n ?? 0) + 1 });
    }
    return [...map.values()].sort((a, b) => a.s.key.localeCompare(b.s.key));
  }, [data, mode]);

  if (error)
    return (
      <div role="alert" className="card !border-err p-5 text-sm">
        <p className="font-medium text-err">! Clusters indisponibles</p>
        <p className="mt-1 text-ink2">{error}</p>
        <p className="mt-2 text-ink2">Lance le clustering depuis la page Pipeline (ou : python clustering.py).</p>
      </div>
    );
  if (!data || !scale) return <p className="text-sm text-ink2">Chargement…</p>;

  const var1 = (data.meta.pca_explained_variance[0] * 100).toFixed(0);
  const var2 = (data.meta.pca_explained_variance[1] * 100).toFixed(0);
  const nearest = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const mx = ((e.clientX - r.left) / r.width) * W;
    const my = ((e.clientY - r.top) / r.height) * H;
    let best: ClusterPoint | null = null;
    let bd = 22 * 22;
    for (const p of data.points) {
      const d = (scale.sx(p.pc1) - mx) ** 2 + (scale.sy(p.pc2) - my) ** 2;
      if (d < bd) { bd = d; best = p; }
    }
    return best;
  };
  const active = hover ?? selected;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="display text-4xl sm:text-5xl">Clusters de wallets</h1>
        <p className="mt-3 max-w-2xl text-ink2">
          Regroupement non supervisé de {data.points.length} wallets, projeté en 2D (PCA). Clique sur un point pour
          l&apos;analyser.
        </p>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Colorer par" className="flex gap-1 rounded-full border border-grid bg-surface2 p-1">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              aria-pressed={mode === m.id}
              className={`rounded-full px-3.5 py-1 text-sm ${mode === m.id ? "bg-page font-medium shadow-sm" : "text-ink2"}`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Affichage" className="flex gap-1 rounded-full border border-grid bg-surface2 p-1">
          {(["chart", "table"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              aria-pressed={view === v}
              className={`rounded-full px-3.5 py-1 text-sm ${view === v ? "bg-page font-medium shadow-sm" : "text-ink2"}`}
            >
              {v === "chart" ? "Graphique" : "Tableau"}
            </button>
          ))}
        </div>
      </div>

      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink2" aria-label="Légende">
        {legend.map(({ s, n }) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <svg width="16" height="16" viewBox="-8 -8 16 16" aria-hidden>
              <Mark x={0} y={0} s={s} size={5} ring={false} />
            </svg>
            {s.name} <span className="text-muted">({n})</span>
          </li>
        ))}
      </ul>

      {view === "chart" ? (
        <Window title={`PCA 2D · ${data.points.length} wallets · coloré par ${MODES.find((m) => m.id === mode)?.label}`}>
        <div className="relative p-2">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full"
            role="img"
            aria-label={`Nuage de points PCA, coloré par ${MODES.find((m) => m.id === mode)?.label}`}
            onMouseMove={(e) => setHover(nearest(e))}
            onMouseLeave={() => setHover(null)}
            onClick={(e) => setSelected(nearest(e))}
          >
            {ticks(scale.y0, scale.y1).map((t) => (
              <g key={`y${t}`}>
                <line x1={M.l} x2={W - M.r} y1={scale.sy(t)} y2={scale.sy(t)} stroke="var(--grid)" />
                <text x={M.l - 8} y={scale.sy(t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">{t}</text>
              </g>
            ))}
            {ticks(scale.x0, scale.x1).map((t) => (
              <g key={`x${t}`}>
                <line y1={M.t} y2={H - M.b} x1={scale.sx(t)} x2={scale.sx(t)} stroke="var(--grid)" />
                <text x={scale.sx(t)} y={H - M.b + 16} textAnchor="middle" fontSize="11" fill="var(--muted)">{t}</text>
              </g>
            ))}
            <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} stroke="var(--axis)" />
            <line x1={M.l} x2={M.l} y1={M.t} y2={H - M.b} stroke="var(--axis)" />
            <text x={(M.l + W - M.r) / 2} y={H - 8} textAnchor="middle" fontSize="12" fill="var(--ink2)">PC1 ({var1} % de la variance)</text>
            <text transform={`translate(14 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle" fontSize="12" fill="var(--ink2)">PC2 ({var2} % de la variance)</text>

            {data.points.map((p) => (
              <Mark key={p.address} x={scale.sx(p.pc1)} y={scale.sy(p.pc2)} s={styleOf(p, mode)} />
            ))}
            {active && (
              <circle cx={scale.sx(active.pc1)} cy={scale.sy(active.pc2)} r={11} fill="none" stroke="var(--ink)" strokeWidth={1.5} />
            )}
          </svg>
          {hover && (
            <div
              className="pointer-events-none absolute rounded-md border border-grid bg-surface px-2.5 py-1.5 text-xs shadow"
              style={{
                left: `${(scale.sx(hover.pc1) / W) * 100}%`,
                top: `${(scale.sy(hover.pc2) / H) * 100}%`,
                transform: "translate(12px, -110%)",
              }}
            >
              <p className="font-mono">{shortAddr(hover.address)}</p>
              <p className="text-ink2">
                {hover.label === "bot" ? "Bot" : "Humain"} · KMeans {hover.kmeans} · DBSCAN {hover.dbscan < 0 ? "bruit" : hover.dbscan}
              </p>
            </div>
          )}
        </div>
        </Window>
      ) : (
        <div className="card max-h-[480px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2">Adresse</th>
                <th className="px-3 py-2">Vrai label</th>
                <th className="px-3 py-2">KMeans</th>
                <th className="px-3 py-2">DBSCAN</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {[...data.points].sort((a, b) => a.kmeans - b.kmeans || a.label.localeCompare(b.label)).map((p) => (
                <tr key={p.address} className="border-t border-grid">
                  <td className="px-3 py-1.5 font-mono">{shortAddr(p.address)}</td>
                  <td className="px-3 py-1.5">{p.label === "bot" ? "Bot" : "Humain"}</td>
                  <td className="px-3 py-1.5">{p.kmeans}</td>
                  <td className="px-3 py-1.5">{p.dbscan < 0 ? "bruit" : p.dbscan}</td>
                  <td className="px-3 py-1.5 text-right">
                    <button
                      className="text-human underline"
                      onClick={() => { setPendingAddress(p.address); router.push("/"); }}
                    >
                      Analyser
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="card flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="text-sm">
            <p className="font-mono break-all">{selected.address}</p>
            <p className="text-ink2">
              Label du dataset : {selected.label === "bot" ? "Bot" : "Humain"} · KMeans {selected.kmeans} · DBSCAN{" "}
              {selected.dbscan < 0 ? "bruit" : selected.dbscan}
            </p>
          </div>
          <button
            className="btn-primary px-5 py-2 text-sm"
            onClick={() => { setPendingAddress(selected.address); router.push("/"); }}
          >
            Analyser ce wallet
          </button>
        </div>
      )}

      <p className="text-xs text-muted">
        Accord avec les vrais labels (ARI, 1 = parfait, 0 = hasard) : KMeans {data.meta.ari_kmeans.toFixed(2)}, DBSCAN{" "}
        {data.meta.ari_dbscan.toFixed(2)}. Un groupe de bots très actifs ressort, mais les bots peu actifs se mélangent
        aux humains.
      </p>
    </div>
  );
}
