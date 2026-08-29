import React, { useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Archive,
  Bot,
  Check,
  ChevronDown,
  Copy,
  Menu,
  Mic,
  PanelLeftClose,
  Paperclip,
  Plus,
  Search,
  SendHorizontal,
  Settings,
  Sparkles,
  SquarePen,
  User,
} from 'lucide-react';
import './styles.css';

const initialMessages = [
  {
    id: 1,
    role: 'assistant',
    text: 'Привет! Я небольшой React-чат в стиле OpenWebUI. Напишите сообщение, и я отвечу локальной демо-заготовкой.',
    time: '15:04',
  },
  {
    id: 2,
    role: 'user',
    text: 'Покажи, как может выглядеть компактный интерфейс чата.',
    time: '15:05',
  },
  {
    id: 3,
    role: 'assistant',
    text: 'Вот пример: слева история диалогов, сверху выбор модели, в центре сообщения, снизу composer с кнопками действий. Логику можно подключить к любому API.',
    time: '15:05',
  },
];

const chats = [
  { title: 'Демо чат', meta: 'Только что' },
  { title: 'React UI пример', meta: 'Сегодня' },
  { title: 'Идеи для ассистента', meta: 'Вчера' },
];

const suggestions = [
  'Сделай ответ короче',
  'Добавь поддержку API',
  'Покажи светлую тему',
];

function nowTime() {
  return new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date());
}

function createDemoAnswer(prompt) {
  const cleanPrompt = prompt.trim();

  return `Получил: «${cleanPrompt}».

В реальном проекте здесь обычно вызывают backend endpoint, который стримит ответ модели. В этом примере состояние хранится в React, поэтому его легко заменить на WebSocket, SSE или обычный fetch.`;
}

function App() {
  const [messages, setMessages] = useState(initialMessages);
  const [draft, setDraft] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const textareaRef = useRef(null);

  const canSend = draft.trim().length > 0 && !isTyping;

  const groupedMessages = useMemo(() => messages, [messages]);

  function handleSubmit(event) {
    event.preventDefault();

    if (!canSend) {
      return;
    }

    const prompt = draft.trim();
    const userMessage = {
      id: Date.now(),
      role: 'user',
      text: prompt,
      time: nowTime(),
    };

    setMessages((current) => [...current, userMessage]);
    setDraft('');
    setIsTyping(true);

    window.setTimeout(() => {
      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          role: 'assistant',
          text: createDemoAnswer(prompt),
          time: nowTime(),
        },
      ]);
      setIsTyping(false);
      textareaRef.current?.focus();
    }, 700);
  }

  function handleTextareaKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(event);
    }
  }

  function startNewChat() {
    setMessages([
      {
        id: Date.now(),
        role: 'assistant',
        text: 'Новый чат готов. Спросите что-нибудь, и я покажу демо-ответ.',
        time: nowTime(),
      },
    ]);
    setDraft('');
  }

  return (
    <main className="app-shell">
      <aside className={`sidebar ${isSidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-header">
          <button className="brand-button" aria-label="Новый чат" onClick={startNewChat}>
            <Sparkles size={18} />
            <span>Open Chat</span>
          </button>
          <button className="icon-button mobile-only" aria-label="Закрыть меню" onClick={() => setIsSidebarOpen(false)}>
            <PanelLeftClose size={18} />
          </button>
        </div>

        <button className="new-chat-button" onClick={startNewChat}>
          <Plus size={18} />
          <span>Новый чат</span>
        </button>

        <label className="search-field">
          <Search size={16} />
          <input type="search" placeholder="Поиск" />
        </label>

        <nav className="chat-list" aria-label="История чатов">
          {chats.map((chat, index) => (
            <button className={`chat-item ${index === 0 ? 'active' : ''}`} key={chat.title}>
              <span>{chat.title}</span>
              <small>{chat.meta}</small>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button className="utility-button">
            <Archive size={17} />
            <span>Архив</span>
          </button>
          <button className="utility-button">
            <Settings size={17} />
            <span>Настройки</span>
          </button>
        </div>
      </aside>

      <section className="chat-panel">
        <header className="topbar">
          <button className="icon-button desktop-hidden" aria-label="Открыть меню" onClick={() => setIsSidebarOpen(true)}>
            <Menu size={19} />
          </button>

          <button className="model-select" aria-label="Выбор модели">
            <span className="model-dot" />
            <span>gpt-demo</span>
            <ChevronDown size={16} />
          </button>

          <button className="icon-button" aria-label="Новый чат" onClick={startNewChat}>
            <SquarePen size={18} />
          </button>
        </header>

        <div className="messages" aria-live="polite">
          <div className="day-divider">
            <span>Сегодня</span>
          </div>

          {groupedMessages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              <div className="avatar" aria-hidden="true">
                {message.role === 'assistant' ? <Bot size={18} /> : <User size={18} />}
              </div>
              <div className="message-body">
                <div className="message-meta">
                  <strong>{message.role === 'assistant' ? 'Assistant' : 'You'}</strong>
                  <span>{message.time}</span>
                </div>
                <p>{message.text}</p>
                {message.role === 'assistant' && (
                  <div className="message-actions" aria-label="Действия сообщения">
                    <button className="ghost-icon" aria-label="Скопировать">
                      <Copy size={15} />
                    </button>
                    <button className="ghost-icon" aria-label="Принять">
                      <Check size={15} />
                    </button>
                  </div>
                )}
              </div>
            </article>
          ))}

          {isTyping && (
            <article className="message-row assistant">
              <div className="avatar" aria-hidden="true">
                <Bot size={18} />
              </div>
              <div className="message-body compact">
                <div className="typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </article>
          )}
        </div>

        <form className="composer-wrap" onSubmit={handleSubmit}>
          <div className="suggestions" aria-label="Быстрые подсказки">
            {suggestions.map((suggestion) => (
              <button type="button" key={suggestion} onClick={() => setDraft(suggestion)}>
                {suggestion}
              </button>
            ))}
          </div>

          <div className="composer">
            <textarea
              ref={textareaRef}
              value={draft}
              rows={1}
              placeholder="Напишите сообщение..."
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleTextareaKeyDown}
            />

            <div className="composer-toolbar">
              <div className="composer-actions">
                <button className="icon-button subtle" type="button" aria-label="Прикрепить файл">
                  <Paperclip size={18} />
                </button>
                <button className="icon-button subtle" type="button" aria-label="Голосовой ввод">
                  <Mic size={18} />
                </button>
              </div>

              <button className="send-button" type="submit" disabled={!canSend} aria-label="Отправить">
                <SendHorizontal size={18} />
              </button>
            </div>
          </div>
        </form>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
