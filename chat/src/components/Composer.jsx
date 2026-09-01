import { SendHorizontal } from 'lucide-react';

export function Composer({ canSend, draft, onChange, onKeyDown, onSubmit }) {
  return (
    <form className="composer-wrap" onSubmit={onSubmit}>
      <div className="composer">
        <textarea
          value={draft}
          rows={1}
          placeholder="Напишите сообщение клиенту…"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="composer-toolbar">
          <span className="composer-hint">Enter — отправить, Shift + Enter — новая строка</span>
          <button className="send-button" type="submit" disabled={!canSend} aria-label="Отправить">
            <SendHorizontal size={18} />
          </button>
        </div>
      </div>
    </form>
  );
}
