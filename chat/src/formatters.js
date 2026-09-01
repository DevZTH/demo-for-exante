export function formatTime(value) {
  const date = value ? new Date(value) : new Date();
  const formattedDate = Number.isNaN(date.getTime()) ? new Date() : date;

  return new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(formattedDate);
}

export function nowTime() {
  return formatTime();
}

export function formatScenarioMeta(value) {
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
