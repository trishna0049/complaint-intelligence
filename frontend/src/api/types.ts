export type Priority = "Low" | "Medium" | "High" | "Critical";
export type Status = "Open" | "In Progress" | "Resolved";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Ticket {
  id: number;
  ticket_number: string;
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
  description_source: "customer" | "dataset_remark" | "template";
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

export interface Usage {
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  latency_s: number;
}

/** One AI run on a ticket: "triage" (classification) or "copilot" (triage snapshot + LLM output). */
export interface Analysis {
  id: number;
  kind: "triage" | "copilot";
  category: string | null;
  intent: string | null;
  sentiment: string | null;
  priority: Priority | null;
  confidence: number | null;
  summary: string | null;
  key_issues: string[] | null;
  recommendations: string[] | null;
  draft_response: string | null;
  provider: string | null;
  model: string | null;
  model_version: string | null;
  prompt_version: string | null;
  usage: Usage | null;
  created_at: string;
}

export interface TicketDetail extends Ticket {
  description: string;
  order_id: string | null;
  product: string | null;
  amount_inr: number | null;
  csat_score: number | null;
  updated_at: string;
  first_response_at: string | null;
  resolved_at: string | null;
  intent_confidence: number | null;
  sentiment_score: number | null;
  priority_reasons: PriorityReason[] | null;
  entities: Entities | null;
  labels_from: "model" | "dataset" | "human";
  model_version: string | null;
  copilot: Analysis | null;
}

export interface TicketInput {
  subject?: string;
  description: string;
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
  negative_share: number | null;
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

export interface Kpis {
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
}

export interface Overview {
  window_days: number;
  generated_at: string;
  kpis: Kpis;
  high_priority_open: { id: number; ticket_number: string; subject: string; category: string | null; priority: Priority;
    sentiment: string | null; created_at: string }[];
  insights: string[];
}

export type Granularity = "day" | "week" | "month";

export interface Trends {
  window_days: number;
  granularity: Granularity;
  points: TrendPoint[];
}

export interface CategoryBreakdowns {
  window_days: number;
  categories: Breakdown[];
  intents: Breakdown[];
  channels: Breakdown[];
  priorities: Breakdown[];
  sentiment: { name: string; count: number }[];
}

export interface EmergingIssue {
  category: string;
  this_week: number;
  last_week: number;
  change_pct: number | null;
  negative_share: number | null;
}

export interface Emerging {
  generated_at: string;
  emerging: EmergingIssue[];
}
