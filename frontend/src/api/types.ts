export type Priority = "Low" | "Medium" | "High" | "Critical";
export type Status = "NEW" | "TRIAGED" | "ASSIGNED" | "IN_PROGRESS" | "WAITING_CUSTOMER" | "ESCALATED" | "RESOLVED" | "CLOSED";
export const STATUSES: Status[] = ["NEW", "TRIAGED", "ASSIGNED", "IN_PROGRESS", "WAITING_CUSTOMER", "ESCALATED", "RESOLVED", "CLOSED"];
export const OPEN_STATUSES: Status[] = ["NEW", "TRIAGED", "ASSIGNED", "IN_PROGRESS", "WAITING_CUSTOMER", "ESCALATED"];

export type TicketAction = "assign" | "auto_assign" | "start" | "wait_customer" | "resume" | "escalate" | "resolve" | "close" | "reopen";

export interface UserRef {
  id: number;
  name: string;
}

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
  assignee: UserRef | null;
  team: TeamRef | null;
  escalated_at: string | null;
  created_at: string;
  updated_at: string;
  /** The classifier's top categories from the latest triage run, best first. */
  top_categories: [string, number][];
  sla: SlaView | null;
}

export type SlaState = "none" | "running" | "at_risk" | "paused" | "breached" | "met";

/** The ticket's SLA clock; the live countdown is computed in the browser from `deadline`. */
export interface SlaView {
  state: SlaState;
  deadline: string | null;
  remaining_seconds: number | null;
  ratio: number | null;
  target_seconds: number | null;
  paused: boolean;
  started_at: string | null;
  breached_at: string | null;
  warned_at: string | null;
  policy: { id: number; name: string; target_minutes: number } | null;
}

export interface SlaPolicy {
  id: number;
  name: string;
  priority: Priority;
  category: string | null;
  target_minutes: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SlaBreakdown {
  name: string;
  with_sla: number;
  breached: number;
  breach_rate: number | null;
}

export interface SlaAnalytics {
  window_days: number;
  with_sla: number;
  breached: number;
  met: number;
  breach_rate: number | null;
  avg_resolution_minutes: number | null;
  avg_target_minutes: number | null;
  open: { at_risk: number; breached: number; paused: number; running: number };
  by_priority: SlaBreakdown[];
  by_category: SlaBreakdown[];
  by_team: SlaBreakdown[];
  trend: { date: string; with_sla: number; breached: number; breach_rate: number | null }[];
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
  root_cause: string | null;
  key_issues: string[] | null;
  recommendations: string[] | null;
  draft_response: string | null;
  provider: string | null;
  model: string | null;
  model_version: string | null;
  prompt_version: string | null;
  usage: Usage | null;
  /** Human review of the draft: nothing reaches the customer unless an agent accepts it. */
  /** RAG references given to the copilot and whether it cited each. */
  grounding: GroundingRef[] | null;
  draft_status: DraftStatus | null;
  reviewed_by: UserRef | null;
  reviewed_at: string | null;
  final_response: string | null;
  edited: boolean | null;
  comment_id: number | null;
  discard_reason: string | null;
  created_at: string;
}

export type DraftStatus = "pending" | "accepted" | "discarded" | "superseded";

/** A reference given to the copilot (RAG): a help article A1.. or a similar past ticket T1.. */
export interface GroundingRef {
  ref: string;
  type: "article" | "ticket";
  id: number;
  title: string;
  ticket_number?: string;
  similarity: number | null;
  cited: boolean;
}

export type MatchedBy = "meaning" | "keywords" | "both";

export interface SimilarTicket {
  id: number;
  ticket_number: string;
  subject: string;
  snippet: string;
  status: Status;
  category: string | null;
  intent: string | null;
  priority: Priority | null;
  resolution: string | null;
  csat_score: number | null;
  source: "dataset" | "new";
  created_at: string;
  score: number;
  similarity: number | null;
  matched_by: MatchedBy;
}

export interface ArticleSummary {
  id: number;
  title: string;
  category: string | null;
  snippet: string;
  usage_count: number;
  updated_at: string;
}

export interface ArticleHit extends ArticleSummary {
  score: number;
  similarity: number | null;
  matched_by: MatchedBy;
}

export interface Article {
  id: number;
  title: string;
  body: string;
  category: string | null;
  usage_count: number;
  updated_by: UserRef | null;
  created_at: string;
  updated_at: string;
}

export interface ArticleInput {
  title: string;
  body: string;
  category: string | null;
}

export interface Comment {
  id: number;
  body: string;
  ai_assisted: boolean;
  author: UserRef | null;
  created_at: string;
}

export interface Attachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_by: UserRef | null;
  created_at: string;
}

export interface TimelineEvent {
  id: number;
  event_type: string;
  actor: UserRef | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface Customer {
  id: number;
  customer_code: string;
  name: string;
  segment: string;
  region: string | null;
  created_at: string;
}

export interface PreviousTicket {
  id: number;
  ticket_number: string;
  subject: string;
  status: Status;
  category: string | null;
  created_at: string;
}

export interface TicketDetail extends Ticket {
  description: string;
  order_id: string | null;
  product: string | null;
  amount_inr: number | null;
  csat_score: number | null;
  resolution: string | null;
  reopen_count: number;
  first_response_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  intent_confidence: number | null;
  sentiment_score: number | null;
  priority_reasons: PriorityReason[] | null;
  entities: Entities | null;
  labels_from: "model" | "dataset" | "human";
  model_version: string | null;
  customer: Customer | null;
  copilot: Analysis | null;
  comments: Comment[];
  attachments: Attachment[];
  timeline: TimelineEvent[];
  previous_tickets: PreviousTicket[];
  allowed_actions: TicketAction[];
  /** False only in the response to a change that moved the ticket out of the caller's scope. */
  can_view: boolean;
  /** Background work (Kafka workers): triage by the AI worker, the copilot draft by the LLM worker. */
  pipeline: { triage: "pending" | "done" | "failed"; copilot: "ready" | "drafting" | "failed" | "manual" };
}

export interface DeadLetter {
  id: number;
  consumer: string;
  event_id: string;
  event_type: string;
  ticket_id: number | null;
  envelope: Record<string, unknown>;
  error: string;
  attempts: number;
  status: "waiting" | "replayed" | "discarded";
  failed_at: string;
  resolved_at: string | null;
  resolved_by_id: number | null;
}

export interface PipelineStatus {
  mode: "kafka" | "inline";
  prefix: string;
  kafka_bootstrap_servers: string | null;
  retries: number;
  kafka_ui_url: string | null;
  outbox: { pending: number; oldest_pending_seconds: number | null; failing: number; last_published_at: string | null };
  consumers: {
    name: string;
    description: string;
    events: string[];
    processed_total: number;
    processed_last_hour: number;
    last_processed_at: string | null;
    dead_letters_waiting: number;
  }[];
}

export interface TicketSummary {
  by_status: Record<Status, number>;
  open: number;
}

export interface TeamMember {
  id: number;
  name: string;
  role: Role;
  open_tickets: number;
}

export interface TicketInput {
  subject?: string;
  description: string;
  channel: string;
  customer_code?: string;
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

// ------------------------------------------------------------------ auth & organisation
export type Role = "ADMIN" | "AGENT";

export interface TeamRef {
  id: number;
  name: string;
}

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  team: TeamRef | null;
  is_active: boolean;
  source: "app" | "dataset";
  supervisor: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface AuthSession {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface Department {
  id: number;
  name: string;
}

export interface TeamInfo {
  id: number;
  name: string;
  description: string | null;
  department: Department;
  member_count: number;
  categories: string[];
}

export interface CategoryInfo {
  id: number;
  name: string;
  description: string | null;
  team: TeamRef | null;
  base_priority: Priority;
  /** Dataset category: the classifier and the priority rules use its name, so it can't be renamed or deleted. */
  builtin: boolean;
}

export interface UserInput {
  name: string;
  email: string;
  password: string;
  role: Role;
  team_id: number | null;
}

export interface UserPatch {
  name?: string;
  role?: Role;
  team_id?: number | null;
  clear_team?: boolean;
  is_active?: boolean;
  password?: string;
}

export type NotificationType = "ticket_assigned" | "ticket_escalated" | "sla_warning" | "sla_breached";

export interface AppNotification {
  id: number;
  type: NotificationType | string;
  title: string;
  message: string;
  ticket_id: number | null;
  severity: "info" | "warning" | "critical";
  read_at: string | null;
  created_at: string;
}

export interface NotificationPage {
  items: AppNotification[];
  total: number;
  page: number;
  page_size: number;
  unread: number;
}
