# План разработки: `feature/fastapi-api`

> **Статус:** начальная реализация завершена. API предоставляет HTTP-слой над готовыми
> document parser, database layer, RAG indexer и audit engine, не меняя их
> доменные контракты и не требуя внешней сети для обычного запуска и тестов.

## 1. Назначение этапа

Реализовать REST API на FastAPI для загрузки документов, запуска аудита,
получения отчётов и управления правилами и нормативными актами. API должен
преобразовывать HTTP-ввод в вызовы существующих сервисов, возвращать
структурированные ошибки и сохранять границы доступа между пользователями.

Первая версия API выполняет аудит синхронно в рамках запроса. Фоновые задачи,
очередь и распределённое выполнение остаются отдельным этапом; архитектура
эндпоинтов должна позволять добавить их позднее без изменения формата отчёта.

## 2. Цели и результат

После завершения этапа система должна:

1. Запускаться локально через ASGI-сервер с SQLite по умолчанию.
2. Принимать DOCX, текстовые PDF и UTF-8 TXT через multipart upload.
3. Сохранять файл в управляемое локальное хранилище, парсить его и создавать
   `Document` с абзацами и исходными диапазонами.
4. Запускать существующий `AuditPersistence` для выбранного документа.
5. Возвращать отчёт с findings, severity, цитатами, диапазонами, правилами и
   нормативными источниками.
6. Предоставлять чтение и создание правил аудита с валидацией параметров.
7. Предоставлять чтение нормативных актов без публикации секретных или
   внутренних путей файловой системы.
8. Возвращать стабильные JSON-ошибки для неверного файла, отсутствующих
   ресурсов, конфликтов статусов и ошибок валидации.
9. Работать в offline-режиме: тесты не должны требовать API-ключей, сети,
   production embeddings или внешнего LLM.
10. Иметь автоматически проверяемый OpenAPI-контракт и integration-тесты.

## 3. Границы этапа

### Входит в этап

- приложение FastAPI и фабрика приложения для тестов;
- конфигурация базы данных, файлового хранилища и лимита upload;
- upload и сохранение документов через существующий parser и repository;
- запуск аудита и получение последнего или указанного отчёта;
- DTO/Pydantic-схемы запросов и ответов;
- CRUD-минимум для правил: список и создание;
- список нормативных актов с пагинацией и безопасными полями;
- dependency для database session и настройки приложения;
- единый формат ошибок, request ID и базовое логирование без текста документов;
- unit- и integration-тесты на временной SQLite-базе и `TestClient`;
- документация запуска API и примеры curl.

### Не входит в этап

- React frontend;
- JWT/OAuth и полноценная система ролей, если отдельный auth-контракт ещё не
  согласован; до его появления API запускается в локальном доверенном режиме;
- фоновые очереди, Celery, Redis и WebSocket-прогресс;
- OCR и новые форматы документов;
- обязательный внешний LLM или production embedding provider;
- загрузка полного корпуса НПА;
- изменение domain-моделей audit engine ради HTTP-формата;
- экспорт отчётов в PDF.

## 4. Предлагаемая структура модулей

```text
backend/
  src/edm_auditor/api/
    __init__.py
    app.py              # create_app() и регистрация middleware/routes
    config.py           # API-настройки и environment overrides
    dependencies.py     # session, services, storage
    errors.py           # exception handlers и ErrorResponse
    schemas.py          # Pydantic request/response DTO
    storage.py          # безопасные имена и сохранение upload-файлов
    routers/
      documents.py      # upload, details, audit
      reports.py        # report response
      rules.py          # list/create rules
      legal_acts.py     # list legal acts
  tests/api/
    conftest.py
    test_documents.py
    test_reports.py
    test_rules.py
    test_legal_acts.py
```

Названия каталогов можно изменить, но routers не должны напрямую содержать
SQLAlchemy-запросы и логику парсинга. Сервисы должны переиспользовать
`DocumentRepository`, `parse_document` и `AuditPersistence`.

## 5. HTTP-контракт

### 5.1. Документы

`POST /api/documents/upload`

- multipart-поле `file`;
- необязательное поле `title`;
- проверка расширения, размера и читаемости файла;
- успешный ответ `201` с `id`, `title`, `file_type`, `status`, `created_at`;
- `400` для повреждённого или неподдерживаемого файла;
- `413` для превышения лимита размера.

`GET /api/documents/{document_id}`

- возвращает метаданные документа, статус, тип и время создания;
- не возвращает полный `raw_text` по умолчанию;
- отсутствие документа даёт `404`.

`POST /api/documents/{document_id}/audit`

- запускает аудит только для существующего документа;
- возвращает `200` с кратким результатом и идентификатором отчёта;
- повторный вызов создаёт новую версию отчёта согласно политике
  `AuditPersistence`;
- конфликт недопустимого состояния должен быть явно описан в ответе.

### 5.2. Отчёты

`GET /api/documents/{document_id}/report`

- по умолчанию возвращает последний отчёт;
- содержит `report_id`, счётчики severity, `summary`, `created_at` и findings;
- finding содержит severity, описание, цитату, диапазон, recommendation,
  `rule_id` и `legal_act_id`;
- если отчётов нет, возвращается `404`, а не успешный пустой объект.

При необходимости конкретная версия выбирается query-параметром
`report_id`. Поля RAG-контекста, сохранённые в summary, должны возвращаться
как структурированные данные, а не как неинтерпретируемная JSON-строка.

### 5.3. Правила

`GET /api/rules`

- фильтры: `is_active`, `document_type`, `check_type`;
- пагинация через `limit` и `offset`;
- сортировка по стабильному `id`.

`POST /api/rules`

- принимает rule code, name, severity, check type, description,
  document type, JSON parameters и optional legal act ID;
- валидирует enum-значения, уникальность `rule_code`, JSON-объект параметров
  и существование `legal_act_id`;
- возвращает `201` с созданным правилом;
- не принимает произвольные поля и не позволяет клиенту подменить `id`.

Изменение и удаление правил не входит в минимальный контракт, пока не
согласована политика аудита уже сохранённых отчётов. При необходимости они
добавляются отдельным расширением с soft-delete/deactivate semantics.

### 5.4. Нормативные акты

`GET /api/legal-acts`

- возвращает `id`, `code`, `title`, `number`, `source_url`;
- поддерживает поиск по `code` и `title`, а также пагинацию;
- не возвращает полный текст статьи без отдельного явно определённого
  endpoint и политики доступа;
- не раскрывает локальный путь исходного файла.

## 6. Безопасность и целостность

- Имя загруженного файла нельзя использовать как путь без нормализации;
  хранение выполняется под сгенерированным безопасным именем.
- Upload directory и database URL задаются конфигурацией, а не query-параметрами.
- Ограничение размера проверяется до полного чтения и дублируется проверкой
  parser-а.
- MIME type не считается достаточным: формат подтверждается parser-ом.
- API не пишет в логи raw text, API keys и содержимое файлов.
- Нельзя возвращать stack trace или внутренние пути в production-ответе.
- Операции с документами и отчётами должны быть ограничены владельцем после
  добавления authentication; до этого локальный режим должен быть явно
  обозначен в документации.
- Ошибка парсинга не должна оставлять частично созданный документ или
  невалидный отчёт.

## 7. План работ

### 7.1. Подготовка приложения и конфигурации

- [x] Добавить FastAPI и совместимый ASGI-инструмент в runtime зависимости.
  зависимости.
- [x] Создать `create_app()` без побочных эффектов при импорте.
- [x] Добавить настройки `EDM_DATABASE_URL`, `EDM_UPLOAD_DIR`,
  `EDM_MAX_UPLOAD_BYTES` и environment override.
- [x] Реализовать инъекцию session factory и сервисов через фабрику приложения.
- [x] Добавить health endpoint `GET /health` без проверки внешних провайдеров.

### 7.2. Upload и документы

- [x] Реализовать безопасное сохранение upload-файла под сгенерированным именем.
- [x] Вызвать `parse_document` и `DocumentRepository.save_parsed_document`.
- [x] Удалять файл при ошибке парсинга или сохранения.
- [x] Добавить document response schema без утечки raw text и внутренних путей.
- [x] Реализовать `POST /api/documents/upload` и `GET /api/documents/{id}`.
- [x] Сопоставить parser exceptions с HTTP status и ErrorResponse.

### 7.3. Аудит и отчёты

- [x] Реализовать `POST /api/documents/{id}/audit` поверх
  `AuditPersistence`.
- [x] Реализовать сериализацию отчёта и findings в стабильный DTO.
- [x] Разобрать `summary` в отдельные поля `diagnostics` и `rag_contexts`.
- [x] Реализовать `GET /api/documents/{id}/report` с выбором последнего
  или конкретного отчёта.
- [x] Сохранить поведение повторного аудита и ошибок транзакции существующего
  `AuditPersistence`.

### 7.4. Правила и нормативные акты

- [x] Реализовать read/query операции с пагинацией в API-слое.
- [x] Добавить Pydantic-схемы для `AuditRule` и `LegalAct`.
- [x] Реализовать `GET /api/rules` и `POST /api/rules`.
- [x] Реализовать `GET /api/legal-acts`.
- [x] Добавить проверку ссылок на НПА и понятные ответы `404`/`409`/`422`.

### 7.5. Тестирование и документация

- [x] Добавить API integration fixtures с временной SQLite-базой.
- [x] Проверить upload TXT и основные ошибки upload; DOCX/PDF добавляются
  отдельными fixtures при расширении API-тестов.
- [x] Проверить ошибки unsupported, too large и missing ID.
- [x] Проверить полный сценарий upload → audit → report.
- [x] Проверить создание правила и его использование следующим аудитом.
- [x] Проверить отсутствие сети, API-ключей и production embedding в тестах.
- [ ] Добавить OpenAPI-примеры и расширенные инструкции запуска в
  `backend/README.md`.
- [ ] Обновить `docs/TASK.md` и `docs/roadmap.md` после завершения этапа.

## 8. Критерии готовности

Этап считается завершённым, если:

- приложение запускается локально командой из документации;
- `/health` отвечает без базы внешних моделей и сети;
- upload поддерживает DOCX, PDF с text layer и UTF-8 TXT;
- parser errors преобразуются в документированные HTTP-ошибки;
- документ и его абзацы сохраняются атомарно;
- audit endpoint создаёт отчёт через существующий audit engine;
- report endpoint возвращает findings с корректными диапазонами и цитатами;
- rules и legal acts доступны через валидируемые paginated endpoints;
- отсутствующие ресурсы не превращаются в `500`;
- тесты проходят на временной SQLite-базе offline;
- API не раскрывает секреты, raw text в логах и локальные пути;
- OpenAPI-схема соответствует фактическим ответам.

## 9. Команды проверки

Из каталога `backend/` после реализации:

```bash
pytest tests/api -q
pytest tests/database tests/document_parser tests/rag tests/audit_engine tests/api -q
```

Для ручного запуска:

```bash
uvicorn edm_auditor.api.app:create_app --factory --reload
```

После запуска проверить `GET /health` и интерактивную документацию `/docs`.

## 10. Рекомендуемая последовательность коммитов

```text
docs(api): add FastAPI implementation plan
build(api): add FastAPI runtime dependencies
feat(api): create application factory and configuration
feat(api): add document upload endpoints
feat(api): add audit and report endpoints
feat(api): add rule and legal act endpoints
test(api): cover document and audit workflows
docs(api): document API usage and error contract
```

Все изменения этапа выполняются в ветке `feature/fastapi-api`. API должен
оставаться совместимым с offline deterministic provider и существующими
domain/persistence контрактами.
