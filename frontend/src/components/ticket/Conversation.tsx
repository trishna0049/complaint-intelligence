import { Download, MessageSquare, Paperclip, Send, Sparkles } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { ApiError } from "@/api/http";
import { downloadAttachment, useAddComment, useUploadAttachment } from "@/api/client";
import type { Attachment, TicketDetail } from "@/api/types";
import { Avatar, Badge, Button, Card, CardHeader, EmptyState, Textarea } from "@/components/ui";
import { fmtDateTime, fmtRelative } from "@/lib/format";

const ACCEPT = ".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.log,.csv,.docx,.xlsx";

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Comments thread, composer and attachments. */
export function Conversation({ ticket }: { ticket: TicketDetail }) {
  const add = useAddComment(ticket.id);
  const upload = useUploadAttachment(ticket.id);
  const [body, setBody] = useState("");
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    add.mutate(body.trim(), { onSuccess: () => setBody("") });
  }

  async function download(att: Attachment) {
    setDownloadError(null);
    try {
      await downloadAttachment(ticket.id, att);
    } catch (err) {
      setDownloadError(err instanceof ApiError ? err.message : "Download failed.");
    }
  }

  return (
    <Card>
      <CardHeader title="Conversation" icon={<MessageSquare className="h-4 w-4" />}
        subtitle={`${ticket.comments.length} comment${ticket.comments.length === 1 ? "" : "s"} · ${ticket.attachments.length} attachment${ticket.attachments.length === 1 ? "" : "s"}`} />
      <div className="divide-y divide-slate-100">
        {ticket.comments.length === 0 ? (
          <EmptyState title="No comments yet" description="Replies and notes from the team appear here." icon={<MessageSquare className="h-6 w-6" />} />
        ) : (
          ticket.comments.map((c) => (
            <article key={c.id} className="flex gap-3 px-4 py-3">
              <Avatar name={c.author?.name ?? "System"} size="sm" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="font-medium text-slate-800">{c.author?.name ?? "System"}</span>
                  <time dateTime={c.created_at} title={fmtDateTime(c.created_at)}>{fmtRelative(c.created_at)}</time>
                  {c.ai_assisted && <Badge tone="violet" title="Drafted by the AI copilot, reviewed and accepted by the agent"><Sparkles className="h-3 w-3" />AI-assisted</Badge>}
                </div>
                <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{c.body}</p>
              </div>
            </article>
          ))
        )}
      </div>

      {ticket.attachments.length > 0 && (
        <div className="border-t border-slate-100 px-4 py-3">
          <p className="mb-2 text-xs font-medium text-slate-500">Attachments</p>
          <ul className="flex flex-wrap gap-2">
            {ticket.attachments.map((a) => (
              <li key={a.id}>
                <button onClick={() => void download(a)} className="flex items-center gap-2 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
                  title={`Uploaded by ${a.uploaded_by?.name ?? "unknown"} ${fmtRelative(a.created_at)}`}>
                  <Download className="h-3.5 w-3.5 text-slate-400" />
                  <span className="max-w-[200px] truncate">{a.filename}</span>
                  <span className="text-slate-400">{fmtSize(a.size_bytes)}</span>
                </button>
              </li>
            ))}
          </ul>
          {downloadError && <p className="mt-2 text-xs text-rose-700" role="alert">{downloadError}</p>}
        </div>
      )}

      <form onSubmit={submit} className="border-t border-slate-100 bg-slate-50/60 p-3">
        <label htmlFor="comment" className="sr-only">Add a comment</label>
        <Textarea id="comment" rows={3} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write a reply or an internal note…" maxLength={10_000} />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input ref={file} type="file" className="hidden" accept={ACCEPT} aria-label="Attach a file"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
          <Button type="button" variant="ghost" size="sm" icon={<Paperclip className="h-3.5 w-3.5" />} loading={upload.isPending} onClick={() => file.current?.click()}>
            Attach file
          </Button>
          <span className="text-xs text-slate-400">PNG, JPG, PDF, TXT, CSV, DOCX, XLSX · up to 10 MB</span>
          <Button type="submit" size="sm" className="ml-auto" icon={<Send className="h-3.5 w-3.5" />} loading={add.isPending} disabled={!body.trim()}>
            Add comment
          </Button>
        </div>
        {(add.error || upload.error) && (
          <p className="mt-2 text-xs text-rose-700" role="alert">{(add.error ?? upload.error)!.message}</p>
        )}
      </form>
    </Card>
  );
}
