import { Bot, ClipboardCheck, User } from 'lucide-react';
import { nowTime } from '../formatters';

export function MessageList({
  activeScenario,
  error,
  isLoading,
  isTyping,
  messages,
  messagesRef,
  supervisorReport,
}) {
  return (
    <div className="messages" aria-live="polite" ref={messagesRef}>
      <div className="day-divider">
        <span>{activeScenario?.title || 'Новый сценарий'}</span>
      </div>

      {isLoading && <TypingIndicator />}

      {messages.map((message) => (
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

      {error && <ErrorMessage error={error} />}
      {isTyping && <TypingIndicator />}
      {supervisorReport && <SupervisorReport report={supervisorReport} />}
    </div>
  );
}

function ErrorMessage({ error }) {
  return (
    <article className="message-row assistant">
      <div className="avatar" aria-hidden="true"><Bot size={18} /></div>
      <div className="message-body error">
        <div className="message-meta"><strong>Система</strong><span>{nowTime()}</span></div>
        <p>{error}</p>
      </div>
    </article>
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
