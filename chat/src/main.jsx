import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bot,
  ClipboardCheck,
  Menu,
  PanelLeftClose,
  SendHorizontal,
  Sparkles,
  SquarePen,
  User,
} from 'lucide-react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1';

const suggestions = [
  'Здравствуйте, Андрей. Чем вы довольны у текущего брокера?',
  'Какие рынки и инструменты для вас сейчас наиболее важны?',
  'Давайте разберём комиссии и условия открытия счёта.',
];

const DEFAULT_SCENARIO_MESSAGE = 'Здравствуйте, Андрей. Я ваш Relationship Manager в EXANTE.';

const welcomeMessage = {
  id: 'welcome',
  role: 'assistant',
  text: 'Начните EXANTE-сценарий: вы — Relationship Manager, а я отвечу от лица потенциального клиента.',
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

function formatScenarioMeta(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  if (date.toDateString() === new Date().toDateString()) {
    return formatTime(date);
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
  }).format(date);
}

function mapMessage(message) {
  return {
    id: message.id,
    role: message.role,
    text: message.content,
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
  const [scenarios, setScenarios] = useState([]);
  const [activeScenarioId, setActiveScenarioId] = useState(null);
  const [draft, setDraft] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isTyping, setIsTyping] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [supervisorReport, setSupervisorReport] = useState(null);
  const [error, setError] = useState('');
  const messagesRef = useRef(null);

  const canSend = draft.trim().length > 0 && !isTyping;
  const canAnalyze = Boolean(activeScenarioId) && !isTyping && !isAnalyzing;
  const groupedMessages = useMemo(() => messages, [messages]);
  const activeScenario = scenarios.find((scenario) => scenario.id === activeScenarioId);

  useEffect(() => {
    let ignore = false;

    async function loadInitialState() {
      try {
        setIsLoading(true);
        const scenarioList = await apiFetch('/scenarios');
        if (ignore) {
          return;
        }

        setScenarios(scenarioList);
        if (scenarioList.length > 0) {
          await selectScenario(scenarioList[0].id, { silent: true });
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
  }, [messages, isTyping, supervisorReport]);

  async function refreshScenarios(nextActiveScenarioId = activeScenarioId) {
    const scenarioList = await apiFetch('/scenarios');
    setScenarios(scenarioList);
    if (nextActiveScenarioId) {
      setActiveScenarioId(nextActiveScenarioId);
    }
  }

  async function selectScenario(scenarioId, options = {}) {
    try {
      if (!options.silent) {
        setIsLoading(true);
      }
      setError('');
      setSupervisorReport(null);
      setActiveScenarioId(scenarioId);
      const loadedMessages = await apiFetch(`/scenarios/${scenarioId}/messages`);
      setMessages(loadedMessages.map(mapMessage));
      setIsSidebarOpen(false);
    } catch (loadError) {
      setError(`Не удалось загрузить сценарий: ${loadError.message}`);
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
    const userMessage = { id: optimisticId, role: 'user', text: prompt, time: nowTime() };

    setMessages((current) => [...current, userMessage]);
    setDraft('');
    setIsTyping(true);
    setSupervisorReport(null);
    setError('');

    try {
      const turn = await apiFetch('/scenarios/turns', {
        method: 'POST',
        body: JSON.stringify({ scenario_id: activeScenarioId, message: prompt }),
      });

      setActiveScenarioId(turn.scenario.id);
      setMessages((current) => {
        const savedTurn = [mapMessage(turn.user_message), mapMessage(turn.assistant_message)];
        if (!activeScenarioId) {
          return savedTurn;
        }
        return [...current.filter((message) => message.id !== optimisticId), ...savedTurn];
      });
      await refreshScenarios(turn.scenario.id);
      if (turn.agent_response.done) {
        await runSupervisor(turn.scenario.id);
      }
    } catch (sendError) {
      setMessages((current) => [
        ...current.filter((message) => message.id !== optimisticId),
        userMessage,
      ]);
      setError(`Не удалось получить ответ клиента: ${sendError.message}`);
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

  async function startNewScenario() {
    setError('');
    setDraft('');
    setSupervisorReport(null);
    setIsTyping(true);

    try {
      const turn = await apiFetch('/scenarios/turns', {
        method: 'POST',
        body: JSON.stringify({ message: DEFAULT_SCENARIO_MESSAGE }),
      });

      setActiveScenarioId(turn.scenario.id);
      setMessages([mapMessage(turn.user_message), mapMessage(turn.assistant_message)]);
      await refreshScenarios(turn.scenario.id);
      if (turn.agent_response.done) {
        await runSupervisor(turn.scenario.id);
      }
      setIsSidebarOpen(false);
    } catch (scenarioError) {
      setError(`Не удалось запустить сценарий: ${scenarioError.message}`);
    } finally {
      setIsTyping(false);
    }
  }

  async function runSupervisor(scenarioId = activeScenarioId) {
    if (!scenarioId || isAnalyzing) {
      return;
    }

    setIsAnalyzing(true);
    setError('');
    try {
      const report = await apiFetch(`/scenarios/${scenarioId}/analysis`, {
        method: 'POST',
      });
      setSupervisorReport(report);
    } catch (analysisError) {
      setError(`Не удалось получить отчёт супервайзера: ${analysisError.message}`);
    } finally {
      setIsAnalyzing(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className={`sidebar ${isSidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-header">
          <button className="brand-button" aria-label="Новый сценарий" onClick={startNewScenario}>
            <Sparkles size={18} />
            <span>EXANTE Trainer</span>
          </button>
          <button className="icon-button mobile-only" aria-label="Закрыть меню" onClick={() => setIsSidebarOpen(false)}>
            <PanelLeftClose size={18} />
          </button>
        </div>

        <div className="sidebar-actions">
          <button className="new-scenario-button" onClick={startNewScenario}>
            <Sparkles size={18} />
            <span>Новый сценарий</span>
          </button>
        </div>

        <nav className="chat-list" aria-label="История сценариев">
          {scenarios.map((scenario) => (
            <button
              className={`chat-item ${scenario.id === activeScenarioId ? 'active' : ''}`}
              key={scenario.id}
              onClick={() => selectScenario(scenario.id)}
            >
              <span>{scenario.title || 'Новый сценарий EXANTE'}</span>
              <small>{formatScenarioMeta(scenario.updated_at)}</small>
            </button>
          ))}
        </nav>
      </aside>

      <section className="chat-panel">
        <header className="topbar">
          <button className="icon-button desktop-hidden" aria-label="Открыть меню" onClick={() => setIsSidebarOpen(true)}>
            <Menu size={19} />
          </button>

          <div className="model-select scenario-mode" aria-label="Активный сценарий">
            <span className="model-dot" />
            <span>EXANTE · клиентский сценарий</span>
          </div>

          <div className="topbar-actions">
            <button
              className="analysis-button"
              type="button"
              onClick={() => runSupervisor()}
              disabled={!canAnalyze}
            >
              <ClipboardCheck size={17} />
              <span>{isAnalyzing ? 'Супервайзер анализирует…' : 'Отчёт супервайзера'}</span>
            </button>
            <button className="icon-button" aria-label="Новый сценарий" onClick={startNewScenario}>
              <SquarePen size={18} />
            </button>
          </div>
        </header>

        <div className="messages" aria-live="polite" ref={messagesRef}>
          <div className="day-divider">
            <span>{activeScenario?.title || 'Новый сценарий EXANTE'}</span>
          </div>

          {isLoading && <TypingIndicator />}

          {groupedMessages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              <div className="avatar" aria-hidden="true">
                {message.role === 'assistant' ? <Bot size={18} /> : <User size={18} />}
              </div>
              <div className="message-body">
                <div className="message-meta">
                  <strong>{message.role === 'assistant' ? 'Клиент' : 'Relationship Manager'}</strong>
                  <span>{message.time}</span>
                </div>
                <p>{message.text}</p>
              </div>
            </article>
          ))}

          {error && (
            <article className="message-row assistant">
              <div className="avatar" aria-hidden="true"><Bot size={18} /></div>
              <div className="message-body error">
                <div className="message-meta"><strong>Система</strong><span>{nowTime()}</span></div>
                <p>{error}</p>
              </div>
            </article>
          )}

          {isTyping && <TypingIndicator />}

          {supervisorReport && <SupervisorReport report={supervisorReport} />}
        </div>

        <form className="composer-wrap" onSubmit={handleSubmit}>
          <div className="suggestions" aria-label="Подсказки для диалога">
            {suggestions.map((suggestion) => (
              <button type="button" key={suggestion} onClick={() => setDraft(suggestion)}>
                {suggestion}
              </button>
            ))}
          </div>

          <div className="composer">
            <textarea
              value={draft}
              rows={1}
              placeholder="Напишите сообщение клиенту…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleTextareaKeyDown}
            />
            <div className="composer-toolbar">
              <span className="composer-hint">Enter — отправить, Shift + Enter — новая строка</span>
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

function SupervisorReport({ report }) {
  return (
    <article className="supervisor-report" aria-label="Отчёт супервайзера">
      <div className="supervisor-report-header">
        <div>
          <span>Отчёт супервайзера</span>
          <h2>Оценка RM: {report.overall_score}/100</h2>
        </div>
        <ClipboardCheck size={22} aria-hidden="true" />
      </div>
      <p className="supervisor-summary">{report.overall_assessment}</p>

      <section className="report-section">
        <h3>Разбор реплик</h3>
        <div className="report-messages">
          {report.message_analyses.map((item) => (
            <article className="report-message" key={`${item.message_number}-${item.speaker}`}>
              <div className="report-message-heading">
                <strong>{item.message_number}. {item.speaker === 'rm' ? 'RM' : 'Клиент'}</strong>
                <span>{item.speaker === 'rm' ? 'Оценка' : 'Сигнал'}: {item.score}/10</span>
              </div>
              <p>{item.assessment}</p>
              <p className="report-recommendation">Следующий шаг: {item.recommendation}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="report-section">
        <h3>Приоритетные рекомендации</h3>
        <ol className="report-recommendations">
          {report.priority_recommendations.map((recommendation, index) => (
            <li key={`${index}-${recommendation}`}>{recommendation}</li>
          ))}
        </ol>
      </section>
    </article>
  );
}

function TypingIndicator() {
  return (
    <article className="message-row assistant">
      <div className="avatar" aria-hidden="true"><Bot size={18} /></div>
      <div className="message-body compact">
        <div className="typing"><span /><span /><span /></div>
      </div>
    </article>
  );
}

createRoot(document.getElementById('root')).render(<App />);
