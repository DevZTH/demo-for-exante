import { useEffect, useState } from 'react';
import { apiFetch } from '../api';
import { formatTime, nowTime } from '../formatters';

function mapMessage(message) {
  return {
    id: message.id,
    role: message.role,
    text: message.content,
    time: formatTime(message.created_at),
  };
}

export function useScenarios() {
  const [messages, setMessages] = useState([]);
  const [scenarios, setScenarios] = useState([]);
  const [activeScenarioId, setActiveScenarioId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isTyping, setIsTyping] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [deletingScenarioId, setDeletingScenarioId] = useState(null);
  const [supervisorReport, setSupervisorReport] = useState(null);
  const [error, setError] = useState('');

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

  async function refreshScenarios(nextActiveScenarioId = activeScenarioId) {
    const scenarioList = await apiFetch('/scenarios');
    setScenarios(scenarioList);
    if (nextActiveScenarioId) {
      setActiveScenarioId(nextActiveScenarioId);
    }
  }

  async function selectScenario(scenarioId, { silent = false } = {}) {
    try {
      if (!silent) {
        setIsLoading(true);
      }
      setError('');
      setSupervisorReport(null);
      setActiveScenarioId(scenarioId);
      const loadedMessages = await apiFetch(`/scenarios/${scenarioId}/messages`);
      setMessages(loadedMessages.map(mapMessage));
      return true;
    } catch (loadError) {
      setError(`Не удалось загрузить сценарий: ${loadError.message}`);
      return false;
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  }

  function startNewScenario() {
    setError('');
    setSupervisorReport(null);
    setActiveScenarioId(null);
    setMessages([]);
  }

  async function analyzeScenario(scenarioId = activeScenarioId) {
    if (!scenarioId || isAnalyzing || deletingScenarioId !== null) {
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

  async function sendMessage(message) {
    const optimisticId = `pending-${Date.now()}`;
    const userMessage = { id: optimisticId, role: 'user', text: message, time: nowTime() };

    setMessages((current) => [...current, userMessage]);
    setIsTyping(true);
    setSupervisorReport(null);
    setError('');

    try {
      const turn = await apiFetch('/scenarios/turns', {
        method: 'POST',
        body: JSON.stringify({ scenario_id: activeScenarioId, message }),
      });

      setActiveScenarioId(turn.scenario.id);
      setMessages((current) => {
        const savedTurn = [mapMessage(turn.user_message), mapMessage(turn.assistant_message)];
        if (!activeScenarioId) {
          return savedTurn;
        }
        return [...current.filter((currentMessage) => currentMessage.id !== optimisticId), ...savedTurn];
      });
      await refreshScenarios(turn.scenario.id);
      if (turn.agent_response.done) {
        await analyzeScenario(turn.scenario.id);
      }
    } catch (sendError) {
      setMessages((current) => [
        ...current.filter((currentMessage) => currentMessage.id !== optimisticId),
        userMessage,
      ]);
      setError(`Не удалось получить ответ клиента: ${sendError.message}`);
    } finally {
      setIsTyping(false);
    }
  }

  async function deleteScenario(scenario) {
    setDeletingScenarioId(scenario.id);
    setError('');

    try {
      await apiFetch(`/scenarios/${scenario.id}`, { method: 'DELETE' });
      const remainingScenarios = await apiFetch('/scenarios');
      setScenarios(remainingScenarios);

      if (scenario.id !== activeScenarioId) {
        return { activeScenarioDeleted: false };
      }

      setSupervisorReport(null);
      if (remainingScenarios.length > 0) {
        return {
          activeScenarioDeleted: true,
          hasRemaining: true,
          selectedScenario: await selectScenario(remainingScenarios[0].id),
        };
      }

      setActiveScenarioId(null);
      setMessages([]);
      return {
        activeScenarioDeleted: true,
        hasRemaining: false,
        selectedScenario: false,
      };
    } catch (deleteError) {
      setError(`Не удалось удалить сценарий: ${deleteError.message}`);
      return null;
    } finally {
      setDeletingScenarioId(null);
    }
  }

  return {
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
  };
}
