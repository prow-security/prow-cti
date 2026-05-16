import { useState } from "react";

const PLACEHOLDER =
  "Prow AI is coming in v0.3. For now, use the search and filter tools to explore your threat intelligence.";

export function ProwAI() {
  const [input, setInput] = useState("");

  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);

  function pushExchange(userText: string) {
    setMessages((prev) => [...prev, { role: "user", text: userText }, { role: "assistant", text: PLACEHOLDER }]);
  }

  function send() {
    const t = input.trim();
    if (!t) return;
    setInput("");
    pushExchange(t);
  }

  function chip(text: string) {
    pushExchange(text);
  }

  return (
    <aside className="ai-panel" aria-label="Prow AI assistant">
      <header className="ai-panel__header">
        <span className="ai-panel__sparkle" aria-hidden>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2l1.2 4.2L18 8l-4.8 1.8L12 14l-1.2-4.2L6 8l4.8-1.8L12 2zM5 16l.5 1.8L7 18l-1.5.6L5 20l-.5-1.8L3 18l1.5-.6L5 16z" />
          </svg>
        </span>
        <span className="ai-panel__title">Prow AI</span>
        <span className="ai-panel__chev" aria-hidden>
          ›
        </span>
      </header>
      <div className="ai-panel__body">
        <p className="ai-panel__intro">Hi, I&apos;m Prow. How can I help your threat analysis?</p>
        <div className="ai-panel__chips">
          <button type="button" className="ai-chip" onClick={() => chip("show me unpatched critical CVEs")}>
            show me unpatched critical CVEs
          </button>
          <button type="button" className="ai-chip" onClick={() => chip("summarize indicators from last 24h")}>
            summarize indicators from last 24h
          </button>
        </div>
        <div className="ai-panel__thread" role="log" aria-live="polite">
          {messages.map((m, i) => (
            <div key={`${i}-${m.text.slice(0, 12)}`} className={`ai-msg ai-msg--${m.role}`}>
              {m.text}
            </div>
          ))}
        </div>
      </div>
      <footer className="ai-panel__footer">
        <div className="ai-input-row">
          <input
            className="ai-input"
            placeholder="Ask Prow..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") send();
            }}
          />
          <button type="button" className="ai-send" aria-label="Send" onClick={send}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h12M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </footer>
    </aside>
  );
}
