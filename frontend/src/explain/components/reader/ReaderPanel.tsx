/** 右侧阅读器:概念精读 + 伴读追问(布局参考 Claude Code 会话面板)。
 * 签名元素:Agent 回答前的「芽标」——追问即浇灌。 */
import { useEffect, useMemo, useState } from "react";
import { useIsMobile } from "../../../utils/useIsMobile";
import { useReaderStore } from "../../store/readerStore";
import { ReaderArticle } from "./ReaderArticle";
import { ReaderThread } from "./ReaderThread";
import { ReaderComposer } from "./ReaderComposer";

export function ReaderPanel() {
  const open = useReaderStore((s) => s.open);
  const entries = useReaderStore((s) => s.entries);
  const activeNodeId = useReaderStore((s) => s.activeNodeId);
  const activate = useReaderStore((s) => s.activate);
  const close = useReaderStore((s) => s.close);
  const isMobile = useIsMobile(); // 移动端整屏阅读态:关闭语义是"返回概念图"
  const version = useReaderStore((s) => s.version); // 流式增量驱动重渲染
  const [historyOpen, setHistoryOpen] = useState(false);

  // Escape 收起(与 EdgeBubble 同款模式)
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  const sorted = useMemo(() => [...entries].sort((a, b) => b.updatedAt - a.updatedAt), [entries, version]);
  const active = entries.find((e) => e.nodeId === activeNodeId) ?? null;
  if (!open || !active) return null;

  return (
    <aside className="reader-panel" role="complementary" aria-label="概念精读阅读器">
      <header className="reader-header">
        <div className="reader-header-text">
          <p className="reader-eyebrow">概念精读</p>
          <h2 className="reader-title">{active.title}</h2>
          <p className="reader-path">{active.path.join(" › ")}</p>
        </div>
        <div className="reader-header-actions">
          <div className="reader-history-wrap">
            <button
              className="reader-icon-btn"
              onClick={() => setHistoryOpen((v) => !v)}
              aria-label="精读记录"
              title="精读记录"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <circle cx="12" cy="12" r="8.5" />
                <path d="M12 7v5l3.2 2" />
              </svg>
            </button>
            {historyOpen && (
              <ul className="reader-history" role="menu">
                {sorted.map((e) => (
                  <li key={e.nodeId}>
                    <button
                      className={`reader-history-item ${e.nodeId === activeNodeId ? "current" : ""}`}
                      onClick={() => {
                        activate(e.nodeId);
                        setHistoryOpen(false);
                      }}
                    >
                      <span className="reader-history-title">{e.title}</span>
                      <span className="reader-history-path">{e.path[e.path.length - 2] ?? "中心概念"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            className="reader-icon-btn"
            onClick={close}
            aria-label={isMobile ? "返回概念图" : "收起阅读器"}
            title={isMobile ? "返回概念图" : "收起阅读器"}
          >
            {isMobile ? (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5" />
                <path d="M12 19l-7-7 7-7" />
              </svg>
            ) : (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M9 5l7 7-7 7" />
              </svg>
            )}
          </button>
        </div>
      </header>

      <div className="reader-scroll">
        <ReaderArticle entry={active} />
        <ReaderThread entry={active} />
      </div>

      <ReaderComposer />
    </aside>
  );
}
