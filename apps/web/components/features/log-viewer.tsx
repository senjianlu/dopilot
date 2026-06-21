"use client";

import * as React from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { buildStreamUrl, fetchStreamToken } from "@/lib/api/tasks";
import { getToken } from "@/lib/api/token";
import { ToneBadge } from "@/components/features/status-badge";

export interface LogViewerProps {
  taskId: string;
  executionId?: string;
  stream?: string;
}

// Live SSE log viewer. First version does NOT use WebSocket (fan-out to web is
// server->web SSE). EventSource cannot attach the bearer header, so when web auth
// is on (a token exists) we fetch a short-lived stream token and pass it as a
// query param.
export function LogViewer({ taskId, executionId, stream }: LogViewerProps) {
  const { t } = useTranslation();
  const [content, setContent] = React.useState("");
  const [completed, setCompleted] = React.useState(false);
  const [errored, setErrored] = React.useState(false);
  const bodyRef = React.useRef<HTMLPreElement | null>(null);
  const sourceRef = React.useRef<EventSource | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    function close() {
      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
    }

    function scrollToBottom() {
      const el = bodyRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }

    async function connect() {
      close();
      setContent("");
      setCompleted(false);
      setErrored(false);

      // When web auth is on, fetch a short-lived stream token for the EventSource.
      let streamToken: string | undefined;
      if (getToken() != null) {
        try {
          const res = await fetchStreamToken(taskId);
          streamToken = res.stream_token;
        } catch {
          if (!cancelled) setErrored(true);
          return;
        }
      }
      if (cancelled) return;

      const url = buildStreamUrl(taskId, { executionId, stream, streamToken });
      const source = new EventSource(url);
      sourceRef.current = source;

      source.addEventListener("log", (event: MessageEvent) => {
        try {
          const payload = JSON.parse(event.data) as { content?: string };
          if (payload.content) {
            setContent((prev) => prev + payload.content);
            // Defer scroll until after the state-driven re-render.
            requestAnimationFrame(scrollToBottom);
          }
        } catch {
          // Ignore malformed frames; the server controls the JSON shape.
        }
      });
      source.addEventListener("complete", () => {
        setCompleted(true);
        close();
      });
      source.addEventListener("error", () => {
        // EventSource auto-reconnects on transient errors; only surface a hard
        // failure once the stream is closed.
        if (source.readyState === EventSource.CLOSED) {
          setErrored(true);
        }
      });
    }

    void connect();
    return () => {
      cancelled = true;
      close();
    };
  }, [taskId, executionId, stream]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{t("logs.title")}</span>
        {completed && <ToneBadge tone="green">{t("logs.complete")}</ToneBadge>}
        {errored && <Badge variant="destructive">{t("logs.error")}</Badge>}
      </div>
      <pre
        ref={bodyRef}
        data-testid="log-body"
        className="m-0 max-h-90 overflow-auto rounded-md bg-zinc-900 p-3 font-mono text-xs whitespace-pre-wrap break-all text-zinc-100"
      >
        {content || t("logs.waiting")}
      </pre>
    </div>
  );
}
