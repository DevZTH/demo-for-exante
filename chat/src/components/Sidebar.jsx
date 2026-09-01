import { PanelLeftClose, Sparkles, Trash2 } from 'lucide-react';
import { formatScenarioMeta } from '../formatters';

export function Sidebar({
  activeScenarioId,
  isDeleting,
  isOpen,
  isScenarioActionInProgress,
  onClose,
  onDeleteScenario,
  onNewScenario,
  onSelectScenario,
  scenarios,
}) {
  return (
    <aside className={`sidebar ${isOpen ? 'sidebar-open' : ''}`}>
      <div className="sidebar-header">
        <button className="brand-button" aria-label="Новый сценарий" onClick={onNewScenario} disabled={isScenarioActionInProgress}>
          <Sparkles size={18} />
          <span>EXANTE Demo chat</span>
        </button>
        <button className="icon-button mobile-only" aria-label="Закрыть меню" onClick={onClose}>
          <PanelLeftClose size={18} />
        </button>
      </div>

      <div className="sidebar-actions">
        <button className="new-scenario-button" onClick={onNewScenario} disabled={isScenarioActionInProgress}>
          <Sparkles size={18} />
          <span>Новый сценарий</span>
        </button>
      </div>

      <nav className="chat-list" aria-label="История сценариев">
        {scenarios.map((scenario) => {
          const isActive = scenario.id === activeScenarioId;
          const title = scenario.title || 'Новый сценарий';

          return (
            <div className={`chat-list-item ${isActive ? 'active' : ''}`} key={scenario.id}>
              <button
                className="chat-item"
                onClick={() => onSelectScenario(scenario.id)}
                disabled={isDeleting}
              >
                <span>{title}</span>
                <small>{formatScenarioMeta(scenario.updated_at)}</small>
              </button>
              <button
                className="delete-chat-button"
                type="button"
                aria-label={`Удалить сценарий «${title}»`}
                title="Удалить сценарий"
                onClick={(event) => onDeleteScenario(event, scenario)}
                disabled={isScenarioActionInProgress}
              >
                <Trash2 size={16} />
              </button>
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
