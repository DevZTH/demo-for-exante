import React, { useEffect, useRef, useState } from 'react';
import { ClipboardCheck, Menu, SquarePen } from 'lucide-react';
import { createRoot } from 'react-dom/client';
import { Composer } from './components/Composer';
import { MessageList } from './components/MessageList';
import { Sidebar } from './components/Sidebar';
import { useScenarios } from './hooks/useScenarios';
import './styles.css';

function App() {
  const [draft, setDraft] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const messagesRef = useRef(null);
  const {
    activeScenarioId,
    analyzeScenario,
    deleteScenario,
    deletingScenarioId,
    error,
    isAnalyzing,
    isLoading,
    isTyping,
    messages,
    scenarios,
    selectScenario,
    sendMessage,
    startNewScenario,
    supervisorReport,
  } = useScenarios();

  const isDeleting = deletingScenarioId !== null;
  const isScenarioActionInProgress = isTyping || isAnalyzing || isDeleting;
  const canSend = draft.trim().length > 0 && !isTyping && !isDeleting;
  const canAnalyze = Boolean(activeScenarioId) && !isScenarioActionInProgress;
  const activeScenario = scenarios.find((scenario) => scenario.id === activeScenarioId);

  useEffect(() => {
    messagesRef.current?.scrollTo({
      top: messagesRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, isTyping, supervisorReport]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canSend) {
      return;
    }

    const prompt = draft.trim();
    setDraft('');
    await sendMessage(prompt);
  }

  function handleTextareaKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(event);
    }
  }

  function handleNewScenario() {
    if (isScenarioActionInProgress) {
      return;
    }

    setDraft('');
    startNewScenario();
    setIsSidebarOpen(false);
  }

  async function handleSelectScenario(scenarioId) {
    if (await selectScenario(scenarioId)) {
      setIsSidebarOpen(false);
    }
  }

  async function handleDeleteScenario(event, scenario) {
    event.stopPropagation();
    if (isScenarioActionInProgress) {
      return;
    }

    const title = scenario.title || 'Новый сценарий';
    if (!window.confirm(`Удалить сценарий «${title}»? Это действие нельзя отменить.`)) {
      return;
    }

    const result = await deleteScenario(scenario);
    if (!result?.activeScenarioDeleted) {
      return;
    }

    setDraft('');
    if (!result.hasRemaining || result.selectedScenario) {
      setIsSidebarOpen(false);
    }
  }

  return (
    <main className="app-shell">
      <Sidebar
        activeScenarioId={activeScenarioId}
        isDeleting={isDeleting}
        isOpen={isSidebarOpen}
        isScenarioActionInProgress={isScenarioActionInProgress}
        onClose={() => setIsSidebarOpen(false)}
        onDeleteScenario={handleDeleteScenario}
        onNewScenario={handleNewScenario}
        onSelectScenario={handleSelectScenario}
        scenarios={scenarios}
      />

      <section className="chat-panel">
        <header className="topbar">
          <button className="icon-button desktop-hidden" aria-label="Открыть меню" onClick={() => setIsSidebarOpen(true)}>
            <Menu size={19} />
          </button>

          <div className="topbar-actions">
            <button
              className="analysis-button"
              type="button"
              onClick={() => analyzeScenario()}
              disabled={!canAnalyze}
            >
              <ClipboardCheck size={17} />
              <span>{isAnalyzing ? 'Супервайзер анализирует…' : 'Отчёт супервайзера'}</span>
            </button>
            <button className="icon-button" aria-label="Новый сценарий" onClick={handleNewScenario} disabled={isScenarioActionInProgress}>
              <SquarePen size={18} />
            </button>
          </div>
        </header>

        <MessageList
          activeScenario={activeScenario}
          error={error}
          isLoading={isLoading}
          isTyping={isTyping}
          messages={messages}
          messagesRef={messagesRef}
          supervisorReport={supervisorReport}
        />

        <Composer
          canSend={canSend}
          draft={draft}
          onChange={setDraft}
          onKeyDown={handleTextareaKeyDown}
          onSubmit={handleSubmit}
        />
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
