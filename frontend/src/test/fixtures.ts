import type { TicketDetail } from "@/api/types";

/** A freshly created, triaged ticket as GET /tickets/{id} returns it. */
export const ticket: TicketDetail = {
  id: 1, ticket_number: "INC-00001", subject: "Charged twice for my order", channel: "Email", status: "TRIAGED",
  category: "Payments related", intent: "Online Payment Issues", sentiment: "Very Negative", priority: "Critical",
  category_confidence: 0.82, needs_review: false, source: "new", description_source: "customer", customer_name: "Ravi Kumar",
  city: "Pune", assignee: null, team: { id: 3, name: "Payments Support" }, escalated_at: null, created_at: new Date().toISOString(),
  description: "I was charged twice for my order of ₹12,500 and have already contacted support three times.",
  order_id: null, product: "Mobile", amount_inr: 12500, csat_score: null, updated_at: new Date().toISOString(),
  first_response_at: null, resolved_at: null, closed_at: null, resolution: null, reopen_count: 0, intent_confidence: 0.4,
  sentiment_score: 1.3, priority_reasons: [{ rule: "BASE", reason: "Base priority for Payments related", from: "", to: "High" },
    { rule: "R1", reason: "Very negative sentiment", from: "High", to: "Critical" }],
  entities: { amounts: [{ text: "₹12,500", value: 12500 }], max_amount_inr: 12500, order_ids: [], dates: [], products: [], repeat_contact: true },
  labels_from: "model", model_version: "triage-v1", copilot: null, customer: null,
  comments: [], attachments: [], previous_tickets: [], allowed_actions: ["assign", "escalate"], can_view: true,
  top_categories: [["Payments related", 0.82], ["Refund Related", 0.1]],
  timeline: [
    { id: 1, event_type: "created", actor: { id: 1, name: "Ada Admin" }, metadata: { channel: "Email" }, created_at: new Date().toISOString() },
    { id: 2, event_type: "triaged", actor: null, metadata: { category: "Payments related", priority: "Critical", confidence: 0.82 }, created_at: new Date().toISOString() },
  ],
};
