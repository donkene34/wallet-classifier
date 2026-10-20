export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Appel JSON ; transforme les erreurs FastAPI ({detail}) en message lisible. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, `API injoignable sur ${API_URL}. Lance : python -m uvicorn main:app --reload`);
  }
  if (!res.ok) {
    let detail = `Erreur ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

/** Adresse transmise de la page Clusters à la page Analyser. */
const KEY = "wc_pending_address";
export function setPendingAddress(a: string) {
  try {
    sessionStorage.setItem(KEY, a);
  } catch {}
}
export function takePendingAddress(): string | null {
  try {
    const a = sessionStorage.getItem(KEY);
    if (a) sessionStorage.removeItem(KEY);
    return a;
  } catch {
    return null;
  }
}

export const FEATURE_LABELS: Record<string, string> = {
  tx_count: "Nombre de transactions",
  avg_time_between_tx: "Délai moyen entre tx",
  std_time_between_tx: "Irrégularité des délais",
  hour_entropy: "Étalement sur les 24 h",
  gas_price_std: "Variation du prix du gas",
  unique_contracts_ratio: "Diversité des contrats",
  round_amount_ratio: "Montants ronds",
  weekend_ratio: "Activité le week-end",
};

export function featureLabel(f: string) {
  return FEATURE_LABELS[f] ?? f;
}

function duration(s: number) {
  if (s < 90) return `${s.toFixed(0)} s`;
  if (s < 5400) return `${(s / 60).toFixed(0)} min`;
  if (s < 129600) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} j`;
}

export function formatFeature(f: string, v: number) {
  switch (f) {
    case "tx_count":
      return Math.round(v).toLocaleString("fr-FR");
    case "avg_time_between_tx":
    case "std_time_between_tx":
      return duration(v);
    case "hour_entropy":
      return `${v.toFixed(2)} bits`;
    case "gas_price_std":
      return `${v.toFixed(2)} gwei`;
    default:
      return `${(v * 100).toFixed(1)} %`;
  }
}

export const shortAddr = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`;
