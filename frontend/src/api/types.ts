export type Priority = "Low" | "Medium" | "High" | "Critical";
export type Status = "Open" | "In Progress" | "Resolved";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Complaint {
  id: number;
  reference: string;
  subject: string;
  channel: string;
  status: Status;
  category: string | null;
  intent: string | null;
  sentiment: string | null;
  priority: Priority;
  category_confidence: number | null;
  needs_review: boolean;
  source: "dataset" | "new";
  text_is_template: boolean;
  customer_name: string | null;
  city: string | null;
  created_at: string;
}

export interface Entities {
  amounts: { text: string; value: number }[];
  max_amount_inr: number | null;
  order_ids: string[];
  dates: string[];
  products: string[];
  repeat_contact: boolean;
}

export interface PriorityReason {
  rule: string;
  reason: string;
  from: string;
  to: string;
}

export interface Insight {
  id: number;
  summary: string;
  key_issues: string[];
  recommended_actions: string[];
  customer_reply: string;
  provider: string;
  model: string;
  prompt_version: string;
  created_at: string;
}

export interface ComplaintDetail extends Complaint {
  text: string;
  order_id: string | null;
  product: string | null;
  amount_inr: number | null;
  csat_score: number | null;
  resolved_at: string | null;
  intent_confidence: number | null;
  sentiment_score: number | null;
  priority_reasons: PriorityReason[] | null;
  entities: Entities | null;
  labels_from: "model" | "dataset" | "human";
  model_version: string | null;
  insight: Insight | null;
}

export interface ComplaintInput {
  subject?: string;
  text: string;
  channel: string;
  customer_name?: string;
  order_id?: string;
  product?: string;
  amount_inr?: number;
  city?: string;
}

export interface TriagePreview {
  category: string | null;
  category_confidence: number | null;
  top_categories: [string, number][];
  intent: string | null;
  intent_confidence: number | null;
  sentiment: string;
  sentiment_score: number;
  priority: Priority;
  priority_reasons: PriorityReason[];
  entities: Entities;
  needs_review: boolean;
  model_version: string;
}

export interface Breakdown {
  name: string;
  count: number;
  negative_share: number;
  high_priority: number;
}

export interface TrendPoint {
  date: string;
  total: number;
  "Very Negative": number;
  Negative: number;
  Neutral: number;
  Positive: number;
  "Very Positive": number;
  high_priority: number;
  avg_csat: number | null;
}

export interface Dashboard {
  window_days: number;
  generated_at: string;
  kpis: {
    total: number;
    open: number;
    high_priority: number;
    critical: number;
    negative_share: number | null;
    avg_csat: number | null;
    avg_sentiment_score: number | null;
    total_change_pct: number | null;
    high_priority_change_pct: number | null;
    needs_review: number;
    open_high_priority: number;
  };
  trend: TrendPoint[];
  categories: Breakdown[];
  intents: Breakdown[];
  channels: Breakdown[];
  priorities: Breakdown[];
  sentiment: { name: string; count: number }[];
  high_priority_open: { id: number; reference: string; subject: string; category: string | null; priority: Priority; sentiment: string | null; created_at: string }[];
  emerging: { category: string; this_week: number; last_week: number; change_pct: number | null; negative_share: number | null }[];
  insights: string[];
}
