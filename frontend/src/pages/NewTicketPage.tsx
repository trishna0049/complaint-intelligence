import { ArrowLeft, Sparkles, Wand2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAnalyze, useCreateTicket } from "@/api/client";
import type { TicketInput } from "@/api/types";
import { TriageView } from "@/components/TriageView";
import { Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";

const EXAMPLE = {
  subject: "Charged twice for my order",
  description: "I was charged twice for my order of ₹12,500 and have already contacted support three times. Nobody has fixed it and I am really frustrated.",
  channel: "Email",
  customer_name: "Ravi Kumar",
  order_id: "OD48213377",
  product: "Mobile",
  amount_inr: "",
  city: "Pune",
};

const EMPTY = { subject: "", description: "", channel: "Web", customer_name: "", order_id: "", product: "", amount_inr: "", city: "" };

export function NewTicketPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const preview = useAnalyze();
  const create = useCreateTicket();

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function payload(): TicketInput | null {
    if (form.description.trim().length < 5) {
      setError("Describe the complaint (at least 5 characters).");
      return null;
    }
    setError(null);
    return {
      subject: form.subject || undefined,
      description: form.description.trim(),
      channel: form.channel,
      customer_name: form.customer_name || undefined,
      order_id: form.order_id || undefined,
      product: form.product || undefined,
      amount_inr: form.amount_inr ? Number(form.amount_inr) : undefined,
      city: form.city || undefined,
    };
  }

  function analyze() {
    const body = payload();
    if (body) preview.mutate(body);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = payload();
    if (body) create.mutate(body, { onSuccess: (t) => navigate(`/tickets/${t.id}`) });
  }

  const p = preview.data;
  return (
    <div className="mx-auto max-w-6xl">
      <Link to="/tickets" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> Tickets
      </Link>
      <PageHeader
        title="Create ticket"
        description="The NLP pipeline classifies category, intent, sentiment and priority as soon as you save."
        actions={
          <Button variant="subtle" size="sm" type="button" icon={<Wand2 className="h-3.5 w-3.5" />}
            onClick={() => { setForm(EXAMPLE); preview.reset(); }}>
            Fill example
          </Button>
        }
      />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
        <form onSubmit={onSubmit} noValidate>
          <Card>
            <div className="space-y-4 p-4">
              <Field label="Complaint description" htmlFor="description" error={error ?? undefined} hint="Personal data is masked before any text is sent to the LLM.">
                <Textarea id="description" rows={7} value={form.description} onChange={set("description")} placeholder="What happened, in the customer's words…" />
              </Field>
              <Field label="Subject (optional)" htmlFor="subject">
                <Input id="subject" value={form.subject} onChange={set("subject")} maxLength={255} placeholder="Defaults to the first line" />
              </Field>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Channel" htmlFor="channel">
                  <Select id="channel" value={form.channel} onChange={set("channel")}>
                    {["Web", "Email", "Inbound", "Outcall"].map((c) => <option key={c}>{c}</option>)}
                  </Select>
                </Field>
                <Field label="Customer name" htmlFor="customer_name">
                  <Input id="customer_name" value={form.customer_name} onChange={set("customer_name")} />
                </Field>
                <Field label="City" htmlFor="city">
                  <Input id="city" value={form.city} onChange={set("city")} />
                </Field>
                <Field label="Order ID" htmlFor="order_id">
                  <Input id="order_id" value={form.order_id} onChange={set("order_id")} />
                </Field>
                <Field label="Product" htmlFor="product">
                  <Select id="product" value={form.product} onChange={set("product")}>
                    <option value="">—</option>
                    {["Electronics", "Mobile", "LifeStyle", "Home", "Home Appliences", "Furniture", "Books & General merchandise", "GiftCard"].map((x) => <option key={x}>{x}</option>)}
                  </Select>
                </Field>
                <Field label="Amount (₹)" htmlFor="amount_inr" hint="Optional — detected from the text if empty">
                  <Input id="amount_inr" type="number" min={0} value={form.amount_inr} onChange={set("amount_inr")} />
                </Field>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50/60 px-4 py-3">
              {create.error && <span className="mr-auto text-sm text-rose-600" role="alert">{create.error.message}</span>}
              <Button type="button" variant="secondary" icon={<Sparkles className="h-4 w-4" />} loading={preview.isPending} onClick={analyze}>
                Analyze
              </Button>
              <Button type="submit" loading={create.isPending}>Create ticket</Button>
            </div>
          </Card>
        </form>

        <Card>
          <CardHeader title="AI triage preview" icon={<Sparkles className="h-4 w-4 text-violet-500" />} subtitle={p?.model_version ?? "Run Analyze to see the result before saving"} />
          <div className="p-4">
            {preview.isError ? (
              <p className="text-sm text-rose-600" role="alert">{preview.error.message}</p>
            ) : p ? (
              <>
                {p.needs_review && (
                  <p className="mb-3 rounded-md bg-violet-50 px-3 py-2 text-xs text-violet-800">Low category confidence — this complaint will be flagged for human review.</p>
                )}
                <TriageView category={p.category} categoryConfidence={p.category_confidence} intent={p.intent} intentConfidence={p.intent_confidence}
                  sentiment={p.sentiment} sentimentScore={p.sentiment_score} priority={p.priority} reasons={p.priority_reasons}
                  entities={p.entities} topCategories={p.top_categories} />
              </>
            ) : (
              <EmptyState title="No analysis yet" description="Category, intent, sentiment, entities and priority will appear here." icon={<Sparkles className="h-6 w-6" />} />
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
