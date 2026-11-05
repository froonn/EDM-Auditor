/**
 * Russian interface texts. Every text shown to the user comes from here through `t()`.
 * A new language is another object of type `Messages` with the same keys.
 */
export const ru = {
  "app.name": "EDM-Auditor",
  "app.tagline": "Аудит документов на соответствие НПА",
  "app.disclaimer":
    "Результат аудита является автоматической технической проверкой и не заменяет юридическую экспертизу.",

  "nav.main": "Основное меню",
  "nav.home": "Состояние системы",

  "home.title": "Состояние системы",
  "home.description":
    "Интерфейс подключается к API бэкенда. Здесь видно, отвечает ли сервер.",
  "home.checking": "Проверяем подключение к серверу…",
  "home.ok": "Сервер API отвечает.",
  "home.checkAgain": "Проверить ещё раз",

  "page.notFound.title": "Страница не найдена",
  "page.notFound.description": "Такого адреса нет. Проверьте ссылку или вернитесь на главную.",
  "page.forbidden.title": "Недостаточно прав",
  "page.forbidden.description": "У вашей учётной записи нет доступа к этому разделу.",
  "page.crash.title": "Ошибка интерфейса",
  "page.crash.description":
    "Страница не смогла отобразиться. Обновите её; если ошибка повторяется, сообщите разработчику.",
  "page.backHome": "На главную",

  "action.retry": "Повторить",
  "action.cancel": "Отмена",
  "action.confirm": "Подтвердить",
  "action.close": "Закрыть",
  "action.details": "Технические подробности",

  "operation.running": "Операция выполняется",
  "operation.elapsed": "Прошло {seconds} с",
  "operation.keepOpen":
    "Не закрывайте и не обновляйте страницу: сервер обрабатывает запрос, и это может занять несколько минут.",

  "table.empty": "Записей нет",
  "table.loading": "Загрузка…",
  "table.range": "{from}–{to} из {total}",
  "table.previous": "Предыдущая страница",
  "table.next": "Следующая страница",

  "severity.critical": "Критическое",
  "severity.high": "Высокое",
  "severity.medium": "Среднее",
  "severity.low": "Низкое",

  "status.document.uploaded": "Загружен",
  "status.document.processing": "Идёт аудит",
  "status.document.audited": "Проверен",
  "status.document.error": "Ошибка",
  "status.classification.pending": "Тип не определён",
  "status.classification.classified": "Тип определён",
  "status.classification.needs_review": "Нужно подтвердить тип",
  "status.classification.unknown": "Тип неизвестен",
  "status.legalAct.uploaded": "Загружен",
  "status.legalAct.processing": "Обрабатывается",
  "status.legalAct.completed": "Обработан",
  "status.legalAct.partial": "Обработан частично",
  "status.legalAct.failed": "Ошибка обработки",
  "status.legalAct.needs_reprocessing": "Нужна повторная обработка",

  "error.title": "Не удалось выполнить действие",
  "error.warningTitle": "Действие выполнено с предупреждением",
  "error.unknown": "Произошла непредвиденная ошибка.",
  "error.network_error":
    "Сервер API недоступен. Проверьте, что бэкенд запущен, и повторите попытку.",
  "error.unexpected_response": "Сервер вернул ответ в неожиданном формате.",
  "error.unauthorized": "Нужно войти в систему.",
  "error.forbidden": "Недостаточно прав для этого действия.",
  "error.empty_document": "Файл пустой.",
  "error.invalid_document": "Файл повреждён или не является документом этого формата.",
  "error.document_access_error": "Сервер не смог прочитать загруженный файл.",
  "error.document_parse_error":
    "Не удалось извлечь текст. Если это скан PDF без текстового слоя, его нужно распознать заранее.",
  "error.document_not_found": "Документ не найден. Возможно, его удалили.",
  "error.report_not_found": "Отчёт не найден.",
  "error.rule_not_found": "Правило не найдено. Возможно, его удалили.",
  "error.legal_act_not_found": "НПА не найден. Возможно, его удалили.",
  "error.document_type_not_found": "Тип документа не найден.",
  "error.document_type_suggestion_not_found": "Предложение типа не найдено.",
  "error.not_found": "Запрошенные данные не найдены.",
  "error.audit_configuration_required":
    "Тип документа не подтверждён. Подтвердите тип или выберите правила вручную.",
  "error.no_applicable_rules": "Для документа нет подходящих правил. Загрузите НПА или выберите правила вручную.",
  "error.rule_conflict": "Правило с таким кодом уже существует.",
  "error.legal_act_conflict": "НПА с таким кодом уже существует.",
  "error.document_type_conflict": "Тип документа с таким кодом уже существует.",
  "error.document_type_in_use": "Тип документа используется, поэтому его нельзя отключить.",
  "error.document_type_suggestion_closed": "По этому предложению уже принято решение.",
  "error.document_too_large": "Файл слишком большой.",
  "error.document_too_large_for_audit": "Документ слишком длинный для аудита.",
  "error.unsupported_document_format": "Формат не поддерживается. Загрузите TXT, DOCX или PDF.",
  "error.unsupported_legal_act_format": "НПА загружается только в формате TXT.",
  "error.validation_error": "Данные заполнены неверно.",
  "error.invalid_severity": "Недопустимая важность.",
  "error.invalid_check_type": "Недопустимый тип проверки.",
  "error.unsupported_check_type": "Этот тип проверки пока не выполняется.",
  "error.invalid_rule_parameters": "Параметры правила заполнены неверно.",
  "error.invalid_applicability_scope": "Недопустимая область применимости.",
  "error.unknown_document_type": "Указан неизвестный тип документа.",
  "error.reserved_document_type": "Этот код типа зарезервирован системой.",
  "error.unknown_rule": "Выбрано несуществующее правило.",
  "error.unknown_legal_act": "Выбран несуществующий НПА.",
  "error.all_mode_not_confirmed": "Запуск по всем правилам нужно подтвердить явно.",
  "error.audit_configuration_error": "Настройка аудита некорректна.",
  "error.model_rate_limited":
    "Превышен лимит запросов к языковой модели. Подождите минуту и повторите.",
  "error.model_timeout": "Языковая модель не ответила вовремя. Повторите попытку.",
  "error.model_provider_error": "Языковая модель недоступна. Отчёт не создан, повторите позже.",
  "error.classification_model_error":
    "Модель не смогла определить тип документа. Повторите позже или укажите тип вручную.",
  "error.rule_extraction_error": "Модель не смогла извлечь правила из НПА. Правила не опубликованы.",
  "error.rag_index_error":
    "Изменение сохранено, но поисковый индекс не обновился. Он обновится при следующем изменении.",
  "error.internal_error": "Внутренняя ошибка сервера.",
  "error.rule_persistence_error": "Сервер не смог сохранить правила.",
  "error.invalid_report_summary": "Отчёт сохранён в повреждённом виде.",
} as const satisfies Record<string, string>;

export type MessageKey = keyof typeof ru;
export type Messages = Record<MessageKey, string>;
