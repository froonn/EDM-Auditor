"""Texts of an exported report.

They repeat the wording of the audit screen (`frontend/src/i18n/ru.ts`), so a report reads the same in
the browser and in a file. Another language is another dictionary with the same keys.
"""

RU: dict[str, str] = {
    "lang": "ru",
    "title": "Отчёт аудита",
    "file_type": "Формат",
    "report": "Отчёт",
    "audited_at": "Дата аудита",
    "exported_at": "Дата выгрузки",
    "timezone": "Часовой пояс",
    "selection_mode": "Режим выбора правил",
    "applied_rules": "Применено правил",
    "applied_acts": "НПА",
    "neural_status": "Анализ моделью",
    "summary": "Вывод модели",
    "no_summary": "Модель не дала общего вывода.",
    "findings_total": "Нарушения",
    "findings_by_severity": "По критичности",
    "no_findings": "Нарушений не найдено.",
    "document_text": "Текст документа",
    "no_text": "Текст документа недоступен.",
    "findings": "Список нарушений",
    "unpositioned": "без привязки к тексту",
    "to_text": "к тексту",
    "to_finding": "к нарушению",
    "severity": "Критичность",
    "rule": "Правило",
    "legal_act": "НПА",
    "description": "Требование",
    "quote": "Фрагмент документа",
    "explanation": "Пояснение модели",
    "confidence": "уверенность",
    "norm": "Норма",
    "recommendation": "Рекомендация",
    "passed": "Правила без нарушений",
    "passed_empty": "Все применённые правила нарушены или не проверены.",
    "passed_unknown": (
        "Отчёт создан до сохранения набора правил, поэтому список правил без нарушений недоступен."
    ),
    "passed_rejected": "Проверка нашла значение, но модель решила, что норма соблюдена",
    "rejected": "Отклонённые моделью кандидаты",
    "rejected_hint": (
        "Автоматическая проверка нашла эти значения, но модель решила, что норма не нарушена."
    ),
    "diagnostics": "Правила, которые не удалось проверить",
    "no_selection": "Отчёт создан до сохранения набора правил.",
    "disclaimer": (
        "Отчёт сформирован автоматически системой EDM-Auditor и не заменяет юридическую проверку."
        " Документ не изменялся: исправьте его по рекомендациям и проверьте заново."
    ),
    "severity.critical": "Критическая",
    "severity.high": "Высокая",
    "severity.medium": "Средняя",
    "severity.low": "Низкая",
    "mode.automatic": "Автоматически",
    "mode.manual": "Вручную",
    "mode.combined": "Автоматически и вручную",
    "mode.all": "Все правила",
    "neural.completed": "выполнен",
    "neural.not_requested": "не проводился",
    "neural.failed": "завершился ошибкой",
    "file_name": "Отчёт аудита",
}
