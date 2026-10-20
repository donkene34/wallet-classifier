export type TopFeature = { feature: string; value: number; contribution: number };

export type AnalyzeResult = {
  address: string;
  bot_probability: number;
  label: "bot" | "human";
  top_features: TopFeature[];
  tx_analyzed: number;
};

export type Example = {
  address: string;
  dataset_label: "bot" | "human";
  category: string | null;
  tx_count: number;
};

export type ClusterPoint = {
  address: string;
  label: "bot" | "human";
  pc1: number;
  pc2: number;
  kmeans: number;
  dbscan: number;
};

export type ClustersData = {
  meta: {
    k: number;
    eps: number;
    min_samples: number;
    log1p: boolean;
    pca_explained_variance: number[];
    ari_kmeans: number;
    ari_dbscan: number;
  };
  points: ClusterPoint[];
};

export type CvMetrics = {
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  roc_auc: number;
  accuracy_std: number;
  cm: number[][];
};

export type ModelInfo = {
  features: string[];
  threshold: number;
  n_train: number;
  n_bots: number;
  importance: Record<string, number>;
  cv: Record<string, CvMetrics>;
};

export type PipelineStatus = {
  state: "idle" | "running" | "done" | "failed" | "cancelled";
  step: string | null;
  label: string | null;
  started_at: number | null;
  finished_at: number | null;
  returncode: number | null;
  lines_total: number;
};

export type PipelineStep = { step: string; label: string };
