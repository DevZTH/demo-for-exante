"""Shared, machine-readable contract for supervisor reports."""

from __future__ import annotations

import re

from backend.app.schemas import SupervisorAnalysisData


_CYRILLIC_LETTER = re.compile(r"[А-Яа-яЁё]")


INITIAL_SUPERVISOR_ANALYSIS_CONTRACT = """
Критически важный контракт ответа:

* В ``message_analyses`` должна быть ровно одна запись для КАЖДОЙ строки
  диалога, включая и ``[rm]``, и ``[client]``.
* Сохраняй исходные номер, говорящего и порядок: если диалог содержит строки
  1. [rm], 2. [client], 3. [rm], ответ должен содержать именно эти три записи
  в таком же порядке с ``message_number`` 1, 2, 3 и ``speaker`` rm, client, rm.
* Не пропускай реплики клиента и не добавляй записи, которых нет в диалоге.
* Верни объект строго по структурированной схеме: используй только поля
  ``overall_score``, ``overall_assessment``, ``message_analyses`` и
  ``priority_recommendations``. В каждой записи ``message_analyses`` используй
  поля ``message_number``, ``speaker``, ``score``, ``assessment`` и
  ``recommendation``.
* ``overall_score`` оценивает только работу RM. Для реплики клиента ``score``
  означает уровень его вовлечённости, а не качество работы RM.
* Весь человекочитаемый текст отчёта обязан быть написан по-русски: итог,
  разборы и рекомендации. Английскими могут быть только технические имена
  полей и значения ``rm``/``client`` в JSON.
""".strip()


RETRY_SUPERVISOR_ANALYSIS_CONTRACT = (
    INITIAL_SUPERVISOR_ANALYSIS_CONTRACT
    + "\n\nПроверь список перед отправкой: число записей и пары "
    "``message_number``/``speaker`` должны в точности совпасть с диалогом. "
    "Перед отправкой переведи весь человекочитаемый текст отчёта на русский язык."
)


def validate_supervisor_report_language(analysis: SupervisorAnalysisData) -> None:
    """Reject a report when a required text field contains no Russian text."""
    text_fields = [
        analysis.overall_assessment,
        *analysis.priority_recommendations,
    ]
    for item in analysis.message_analyses:
        text_fields.extend((item.assessment, item.recommendation))

    if any(not _CYRILLIC_LETTER.search(text) for text in text_fields):
        raise ValueError("супервайзер должен вернуть весь текст отчёта на русском языке")
