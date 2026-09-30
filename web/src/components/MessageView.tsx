import type { UiMessage, Usage } from "../types";
import { Markdown } from "./Markdown";
import { StoredImage } from "./StoredImage";

export function MessageView({ message }: { message: UiMessage }) {
  const hasImages = message.images.length > 0 || message.imageRefs.length > 0;
  const images = hasImages && (
    <div className="thumbs">
      {message.images.map((src, i) => (
        <img key={i} className="thumb" src={src} alt={`Attached image ${i + 1}`} />
      ))}
      {message.imageRefs.map((id) => (
        <StoredImage key={id} id={id} />
      ))}
    </div>
  );

  if (message.role === "user") {
    return (
      <div className="msg msg-user">
        <div className="bubble">
          {images}
          <div className="user-text">{message.content}</div>
        </div>
      </div>
    );
  }

  const waiting = message.streaming && !message.content;
  return (
    <div className="msg msg-assistant">
      <div className="avatar" aria-hidden="true">mX</div>
      <div className="assistant-body">
        {waiting ? (
          <div className="thinking" aria-label="mX is thinking">
            <span /><span /><span />
          </div>
        ) : (
          <Markdown text={message.content} />
        )}
        {message.streaming && message.content && <span className="caret" aria-hidden="true" />}
        {message.stopReason === "max_tokens" && (
          <div className="note warn">This reply hit its length limit and was cut off.</div>
        )}
        {message.error && <div className="note error">{message.error}</div>}
        {message.usage && <UsageLine usage={message.usage} />}
      </div>
    </div>
  );
}

function UsageLine({ usage }: { usage: Usage }) {
  const cost = usage.cost_usd === null ? "cost unknown" : `$${usage.cost_usd.toFixed(4)}`;
  return (
    <div className="usage" title="Model, tokens in / out, and the cost of this reply">
      {usage.model} · {usage.input_tokens.toLocaleString()} in / {usage.output_tokens.toLocaleString()} out · {cost}
    </div>
  );
}
