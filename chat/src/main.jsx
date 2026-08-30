import React, { useEffect, useMemo, useRef, useState } from 'react';
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

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1';

const suggestions = [
  'Запомни, что меня зовут Алекс',
  'Что ты помнишь?',
  'О чем мой проект?',
];

const DEFAULT_SCENARIO_MESSAGE = 'Здравствуйте.';

const welcomeMessage = {
  id: 'welcome',
  role: 'assistant',
  text: 'Привет! Я готов к диалогу. Сообщения сохраняются в SQLite, а история подключена к LangChain memory.',
  time: nowTime(),
};

function formatTime(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) {
    return nowTime();
  }

  return new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function nowTime() {
  return formatTime();
}

function formatChatMeta(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  const today = new Date();
  const isToday = date.toDateString() === today.toDateString();

  if (isToday) {
    return formatTime(date);
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
  }).format(date);
}

function extractVisibleAssistantText(content) {
  if (!content || typeof content !== 'string') {
    return '';
  }

  try {
    const parsed = JSON.parse(content);
    if (parsed && typeof parsed.reply === 'string') {
      return parsed.reply;
    }
  } catch {
    // Plain chat messages are not JSON; keep the original text.
  }

  return content;
}

function mapMessage(message) {
  return {
    id: message.id,
    role: message.role,
    text:
      message.role === 'assistant'
        ? extractVisibleAssistantText(message.content)
        : message.content,
    time: formatTime(message.created_at),
  };
}

async function apiFetch(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  });

  if (!response.ok) {
    const details = await response.text();
    throw new Error(details || `HTTP ${response.status}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

function App() {
  const [messages, setMessages] = useState([welcomeMessage]);
  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [settings, setSettings] = useState(null);
  const [draft, setDraft] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState('chat');
  const [scenarioChatIds, setScenarioChatIds] = useState([]);
  const textareaRef = useRef(null);
  const messagesRef = useRef(null);

  const canSend = draft.trim().length > 0 && !isTyping;
  const groupedMessages = useMemo(() => messages, [messages]);
  const activeChat = chats.find((chat) => chat.id === activeChatId);
  const activeMode = mode === 'scenario' || scenarioChatIds.includes(activeChatId);

  useEffect(() => {
    let ignore = false;

    async function loadInitialState() {
      try {
        setIsLoading(true);
        const [runtimeSettings, chatList] = await Promise.all([
          apiFetch('/settings'),
          apiFetch('/chats'),
        ]);

        if (ignore) {
          return;
        }

        setSettings(runtimeSettings);
        setChats(chatList);

        if (chatList.length > 0) {
          await selectChat(chatList[0].id, { silent: true });
        }
      } catch (loadError) {
        if (!ignore) {
          setError(`Backend недоступен: ${loadError.message}`);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    loadInitialState();

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    messagesRef.current?.scrollTo({
      top: messagesRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, isTyping]);

  async function refreshChats(nextActiveChatId = activeChatId) {
    const chatList = await apiFetch('/chats');
    setChats(chatList);

    if (nextActiveChatId) {
      setActiveChatId(nextActiveChatId);
    }
  }

  async function selectChat(chatId, options = {}) {
    try {
      if (!options.silent) {
        setIsLoading(true);
      }
      setError('');
      setActiveChatId(chatId);
      setMode(scenarioChatIds.includes(chatId) ? 'scenario' : 'chat');
      const loadedMessages = await apiFetch(`/chats/${chatId}/messages`);
      setMessages(loadedMessages.map(mapMessage));
      setIsSidebarOpen(false);
    } catch (loadError) {
      setError(`Не удалось загрузить чат: ${loadError.message}`);
    } finally {
      if (!options.silent) {
        setIsLoading(false);
      }
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();

    if (!canSend) {
      return;
    }

    const prompt = draft.trim();
    const optimisticId = `pending-${Date.now()}`;
    const userMessage = {
      id: optimisticId,
      role: 'user',
      text: prompt,
      time: nowTime(),
    };

    setMessages((current) => [...current, userMessage]);
    setDraft('');
    setIsTyping(true);
    setError('');

    try {
      const endpoint = activeMode ? '/agent/chat' : '/chat';
      const turn = await apiFetch(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          chat_id: activeChatId,
          message: prompt,
        }),
      });

      if (endpoint === '/agent/chat') {
        setScenarioChatIds((current) =>
          current.includes(turn.chat.id) ? current : [...current, turn.chat.id],
        );
      }

      setActiveChatId(turn.chat.id);
      setMode(endpoint === '/agent/chat' ? 'scenario' : 'chat');
      setMessages((current) => {
        const savedTurn = [mapMessage(turn.user_message), mapMessage(turn.assistant_message)];
        if (!activeChatId) {
          return savedTurn;
        }
        return [
          ...current.filter((message) => message.id !== optimisticId),
          ...savedTurn,
        ];
      });
      await refreshChats(turn.chat.id);
    } catch (sendError) {
      setMessages((current) => [
        ...current.filter((message) => message.id !== optimisticId),
        userMessage,
        {
          id: `error-${Date.now()}`,
          role: 'assistant',
          text: `Не удалось получить ответ backend: ${sendError.message}`,
          time: nowTime(),
        },
      ]);
      setError('Проверьте, что backend запущен на 127.0.0.1:8000.');
    } finally {
      setIsTyping(false);
    }
  }

  function handleTextareaKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(event);
    }
  }

  function startNewChat() {
    setMode('chat');
    setActiveChatId(null);
    setMessages([
      {
        ...welcomeMessage,
        id: `welcome-${Date.now()}`,
        time: nowTime(),
      },
    ]);
    setDraft('');
    setError('');
    setIsSidebarOpen(false);
  }

  async function startNewScenario() {
    setMode('scenario');
    setError('');
    setDraft('');
    setIsTyping(true);

    try {
      const turn = await apiFetch('/agent/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: DEFAULT_SCENARIO_MESSAGE,
          chat_id: null,
        }),
      });

      setScenarioChatIds((current) =>
        current.includes(turn.chat.id) ? current : [...current, turn.chat.id],
      );
      setActiveChatId(turn.chat.id);
      setMessages([mapMessage(turn.user_message), mapMessage(turn.assistant_message)]);
      await refreshChats(turn.chat.id);
    } catch (scenarioError) {
      setMessages([
        {
          id: `scenario-error-${Date.now()}`,
          role: 'assistant',
          text: `Не удалось запустить сценарий: ${scenarioError.message}`,
          time: nowTime(),
        },
      ]);
      setError('Проверьте, что backend запущен на 127.0.0.1:8000.');
    } finally {
      setIsTyping(false);
    }
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

        <div className="sidebar-actions">
          <button className="new-chat-button" onClick={startNewChat}>
            <Plus size={18} />
            <span>Новый чат</span>
          </button>
          <button className="new-scenario-button" onClick={startNewScenario}>
            <Sparkles size={18} />
            <span>Новый сценарий</span>
          </button>
        </div>

        <label className="search-field">
          <Search size={16} />
          <input type="search" placeholder="Поиск" />
        </label>

        <nav className="chat-list" aria-label="История чатов">
          {chats.map((chat) => (
            <button
              className={`chat-item ${chat.id === activeChatId ? 'active' : ''}`}
              key={chat.id}
              onClick={() => selectChat(chat.id)}
            >
              <span>{chat.title || 'Новый чат'}</span>
              <small>{formatChatMeta(chat.updated_at)}</small>
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

          <button className={`model-select ${activeMode ? 'scenario-mode' : ''}`} aria-label="Выбор модели">
            <span className="model-dot" />
            <span>{activeMode ? 'EXANTE scenario' : settings?.llm_model ?? 'backend'}</span>
            <ChevronDown size={16} />
          </button>

          <button className="icon-button" aria-label="Новый чат" onClick={startNewChat}>
            <SquarePen size={18} />
          </button>
        </header>

        <div className="messages" aria-live="polite" ref={messagesRef}>
          <div className="day-divider">
            <span>{activeChat?.title || (activeMode ? 'Новый сценарий' : 'Новый диалог')}</span>
          </div>

          {isLoading && (
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

          {error && (
            <article className="message-row assistant">
              <div className="avatar" aria-hidden="true">
                <Bot size={18} />
              </div>
              <div className="message-body error">
                <div className="message-meta">
                  <strong>System</strong>
                  <span>{nowTime()}</span>
                </div>
                <p>{error}</p>
              </div>
            </article>
          )}

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
              placeholder={activeMode ? 'Напишите сообщение продавцу...' : 'Напишите сообщение...'}
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
