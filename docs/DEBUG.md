# Руководство по отладке и работе с API

Типовые сценарии работы с запущенным бэкендом: запуск и журнал, правила, НПА, аудит и прямая проверка
базы. Полный список эндпоинтов и кодов ошибок описан в [`backend/README.md`](../backend/README.md).

Все команды выполняются из каталога `backend/`.

## 1. Запуск сервера

```bash
source .venv/bin/activate
uvicorn edm_auditor.api.app:create_app --factory --reload --port 8000
```

Без `EDM_MODEL_PRESET` сервер не запустится. Если в окружении уже есть другой `GEMINI_API_KEY`, он
скрывает ключ из `.env`, и модель отвечает ошибкой. В этом случае перед запуском выполните:

```bash
set -a; source .env; set +a
```

Проверка доступности:

```bash
curl -s http://127.0.0.1:8000/health | jq .
```

Swagger UI доступен на <http://127.0.0.1:8000/docs>.

### Обновление базы

Если схема устарела, сервер не запустится и назовёт команду. Сделайте копию базы и выполните миграции:

```bash
cp data/edm_auditor.sqlite3 data/edm_auditor.backup.sqlite3
# Только если в базе нет таблицы alembic_version:
alembic stamp 0005_rule_publication_metadata
alembic upgrade head
```

`alembic` не читает `EDM_DATABASE_URL`: команды всегда меняют `data/edm_auditor.sqlite3`. Чтобы
проверить миграцию на копии, создайте `alembic.config.Config` и задайте в нём `sqlalchemy.url`, как в
`tests/database/test_migrations.py`.

### Журнал `data/debug.log`

В терминал выводятся краткие сообщения сервера. Подробности пишутся в файл, путь к которому задаёт
`EDM_LOG_FILE`:

- каждый запрос: метод, адрес, `request_id`, заголовки и тело, если это JSON;
- каждый ответ: статус, заголовки и первые 4000 символов тела;
- размеры ответов моделей и статусы вызовов.

API-ключи моделей, полные запросы к моделям и их ответы в журнал не пишутся. Но тела запросов и ответов
API могут содержать текст НПА и документов, поэтому не публикуйте этот файл.

```bash
tail -f data/debug.log
```

Заголовок `X-Request-ID` ответа помогает найти запрос в журнале.

### Кириллица в JSON

`python -m json.tool` по умолчанию экранирует кириллицу (`усл...`). Используйте `jq`
или флаг `--no-ensure-ascii`:

```bash
curl -s http://127.0.0.1:8000/api/rules | jq .
curl -s http://127.0.0.1:8000/api/rules | python3 -m json.tool --no-ensure-ascii
```

## 2. Быстрая проверка всего сценария

Каждая загрузка и аудит обращаются к модели. На бесплатном тарифе Gemini делайте паузы между запросами,
иначе API ответит `429 model_rate_limited`.

```bash
# Загрузить НПА: модель извлекает правила
curl -sS -X POST http://127.0.0.1:8000/api/legal-acts/upload \
  -F code=ACT-REMOTE \
  -F title='Положение о дистанционной работе' \
  -F file=@examples/legal_act_remote_work.txt | jq .

curl -sS -X POST http://127.0.0.1:8000/api/legal-acts/upload \
  -F code=ACT-TRIP \
  -F title='Положение о служебных командировках' \
  -F file=@examples/legal_act_business_trip.txt | jq .

curl -sS -X POST http://127.0.0.1:8000/api/legal-acts/upload \
  -F code=ACT-PAYMENTS \
  -F title='Положение о выплате заработной платы' \
  -F file=@examples/legal_act_payments.txt | jq .

# Посмотреть правила
curl -s http://127.0.0.1:8000/api/rules | jq .

# Загрузить документ: модель определяет его тип
curl -sS -X POST http://127.0.0.1:8000/api/documents/upload \
  -F file=@examples/remote_work_agreement.txt | jq .

# Запустить аудит
curl -sS -X POST http://127.0.0.1:8000/api/documents/<DOCUMENT_ID>/audit | jq .

# Посмотреть отчёт
curl -s http://127.0.0.1:8000/api/documents/<DOCUMENT_ID>/report | jq .
```

## 3. Правила

### Просмотр

```bash
curl -s "http://127.0.0.1:8000/api/rules?is_active=true" | jq .
curl -s "http://127.0.0.1:8000/api/rules?check_type=duration" | jq .
curl -s "http://127.0.0.1:8000/api/rules?applicability_scope=universal" | jq .
curl -s "http://127.0.0.1:8000/api/rules?document_type=payroll_order" | jq .

# Постраничный вывод: общее число записей находится в заголовке X-Total-Count
curl -si "http://127.0.0.1:8000/api/rules?limit=10&offset=0"
```

### Создание

```bash
curl -s -X POST http://127.0.0.1:8000/api/rules \
  -H 'Content-Type: application/json' \
  -d '{
    "rule_code": "vacation-min-24-days",
    "name": "Минимальная продолжительность отпуска",
    "severity": "critical",
    "description": "Основной отпуск должен быть не менее 24 календарных дней.",
    "check_type": "duration",
    "parameters": {"min_days": 24},
    "applicability_scope": "typed",
    "document_types": ["vacation_order"]
  }' | jq .
```

Без `applicability_scope` и `document_types` правило становится универсальным. Допустимые значения:

- `severity`: `low`, `medium`, `high`, `critical`;
- `check_type`:
    - `keyword`: `{"keywords": ["слово"], "mode": "required", "match": "stem"}`;
    - `regex`: `{"pattern": "..."}`;
    - `numeric`: `{"entity": "money", "min": 100, "max": 500}`, где `entity` равен `number`, `duration`,
      `money` или `percent`;
    - `duration`: `{"min_days": 1, "max_days": 30}`;
    - `date`: `{"before": "2026-12-31"}` или `{"after": "2026-01-01"}`.

Тип `semantic` отклоняется кодом `422 unsupported_check_type`: семантический аудит перенесён в
дипломный проект.

### Изменение и отключение

```bash
curl -s -X PATCH http://127.0.0.1:8000/api/rules/1 \
  -H 'Content-Type: application/json' \
  -d '{"severity": "medium", "parameters": {"min_days": 28}}' | jq .

curl -s -X PATCH http://127.0.0.1:8000/api/rules/1 \
  -H 'Content-Type: application/json' \
  -d '{"is_active": false}' | jq .

curl -s -X PATCH http://127.0.0.1:8000/api/rules/1/applicability \
  -H 'Content-Type: application/json' \
  -d '{"applicability_scope": "typed", "document_types": ["payroll_order"]}' | jq .
```

Повторная обработка НПА пересоздаёт его правила, и эти правки теряются.

### Удаление

```bash
curl -i -X DELETE http://127.0.0.1:8000/api/rules/1
```

Правило удаляется, RAG-индекс пересобирается. Прежние отчёты сохраняются: у нарушения пропадает
`rule_id`, но остаются `rule_code`, `rule_name` и `norm_quote`.

## 4. Нормативно-правовые акты

Загрузка принимает только TXT и выполняется синхронно: запрос длится, пока модель не обработает все
фрагменты. Если хотя бы один фрагмент не обработан, ни одно правило не публикуется, а акт получает
статус `failed`.

```bash
curl -s http://127.0.0.1:8000/api/legal-acts | jq .          # без текста
curl -s http://127.0.0.1:8000/api/legal-acts/1 | jq .        # с текстом
curl -s http://127.0.0.1:8000/api/legal-acts/1/diagnostics | jq .

# Повторное извлечение правил, например при статусе failed или needs_reprocessing
curl -s -X POST http://127.0.0.1:8000/api/legal-acts/1/reprocess | jq .

curl -i -X DELETE http://127.0.0.1:8000/api/legal-acts/1
```

Значения `processing_status`:

| Статус               | Значение                                                |
|----------------------|---------------------------------------------------------|
| `uploaded`           | акт создан через JSON, правила не извлекались           |
| `processing`         | идёт извлечение правил                                  |
| `completed`          | правила опубликованы                                    |
| `partial`            | опубликованы не все: часть оказалась повторами          |
| `failed`             | извлечение не удалось, смотрите `diagnostics`           |
| `needs_reprocessing` | текст изменён, правила ещё соответствуют старому тексту |

Типы для всех правил акта можно задать вручную: они важнее ответа модели.

```bash
# При загрузке: -F document_types=business_trip_order,vacation_order
curl -s -X PATCH http://127.0.0.1:8000/api/legal-acts/1 \
  -H 'Content-Type: application/json' \
  -d '{"document_types": ["business_trip_order"]}' | jq .
```

## 5. Документы и настройка аудита

Модель определяет тип при загрузке, выбирая его из каталога по названию и описанию. Значения
`classification_status`:

| Статус         | Значение                                                |
|----------------|---------------------------------------------------------|
| `classified`   | тип подтверждён                                         |
| `needs_review` | уверенность ниже порога, нужно подтверждение            |
| `unknown`      | подходящего типа нет                                    |
| `pending`      | модель была недоступна, запрос повторится перед аудитом |

Если тип не подтверждён, автоматический аудит отвечает `409 audit_configuration_required` и не создаёт
отчёт.

```bash
# Документ с текстом и его удаление вместе с отчётами и файлом
curl -s http://127.0.0.1:8000/api/documents/1 | jq .
curl -i -X DELETE http://127.0.0.1:8000/api/documents/1

# Каталог типов
curl -s http://127.0.0.1:8000/api/document-types | jq .
curl -s -X POST http://127.0.0.1:8000/api/document-types \
  -H 'Content-Type: application/json' \
  -d '{"code": "travel_expense_report", "name": "Авансовый отчёт", "description": "Отчёт работника о расходах в командировке."}' | jq .
curl -s -X PATCH http://127.0.0.1:8000/api/document-types/travel_expense_report \
  -H 'Content-Type: application/json' \
  -d '{"description": "Отчёт о расходах работника."}' | jq .

# Новые типы, предложенные моделью: добавить в каталог или отклонить
curl -s http://127.0.0.1:8000/api/document-type-suggestions | jq .
curl -s -X POST http://127.0.0.1:8000/api/document-type-suggestions/1/accept \
  -H 'Content-Type: application/json' \
  -d '{"code": "travel_expense_report"}' | jq .
curl -s -X POST http://127.0.0.1:8000/api/document-type-suggestions/1/dismiss

# Классификация и ручное подтверждение
curl -s -X POST http://127.0.0.1:8000/api/documents/1/classify | jq .
curl -s -X PATCH http://127.0.0.1:8000/api/documents/1/classification \
  -H 'Content-Type: application/json' \
  -d '{"confirmed_document_types": ["business_trip_order"]}' | jq .

# Предпросмотр: тот же набор правил, что и при запуске
curl -s -X POST http://127.0.0.1:8000/api/documents/1/audit/preview | jq .

# Запуск с настройкой выбора
curl -s -X POST http://127.0.0.1:8000/api/documents/1/audit \
  -H 'Content-Type: application/json' \
  -d '{"selection_mode": "manual", "legal_act_ids": [1], "excluded_rule_ids": [5]}' | jq .
```

Режимы выбора описаны в [`backend/README.md`](../backend/README.md#rule-selection). В `warnings` и
`reason` предпросмотра и в поле `selection` отчёта встречаются:

| Код                                | Значение                                     |
|------------------------------------|----------------------------------------------|
| `document_type_unknown`            | тип определить не удалось                    |
| `classification_low_confidence`    | есть кандидаты, но тип не подтверждён        |
| `manual_selection_required`        | нужно подтвердить тип или выбрать правила    |
| `no_applicable_rules`              | подходящих правил нет (`409`)                |
| `rules_with_unknown_applicability` | есть правила с неизвестной применимостью     |
| `all_mode_false_positive_risk`     | режим `all` может дать ложные нарушения      |
| `rule_included_by_user`            | правило выбрано вручную                      |
| `rule_selected_by_legal_act`       | правило выбрано через его НПА                |
| `rule_selected_by_all_mode`        | правило выбрано режимом `all`                |
| `rule_universal`                   | правило универсальное                        |
| `rule_matched_document_type`       | правило совпало по типу документа            |
| `rule_excluded_by_user`            | правило исключено вручную                    |
| `rule_excluded_by_document_type`   | правило относится к другому типу             |
| `rule_excluded_by_legal_act_scope` | НПА правила не входит в выбранные            |
| `rule_manual_only`                 | правило применяется только при ручном выборе |
| `rule_applicability_unknown`       | применимость правила неизвестна              |
| `rule_inactive`                    | правило отключено                            |
| `rag_candidate_below_threshold`    | RAG-кандидат ниже порога; на выбор не влияет |
| `rag_unavailable`                  | RAG недоступен; проверки правил продолжаются |

RAG только показывает связанные НПА со `score` и `threshold` и никогда не включает правило.

## 6. Отчёт

```bash
curl -s http://127.0.0.1:8000/api/documents/1/report | jq .   # последний отчёт
curl -s http://127.0.0.1:8000/api/reports/1 | jq .
```

Что проверить, если результат неожиданный:

- `summary.rejected_candidates`: нарушения, которые отклонила модель, с причиной;
- `summary.diagnostics`: правила, которые не удалось проверить;
- `selection`: какие правила применялись и почему;
- `neural_analyses`: пояснения, связанные с нарушениями через `finding_key`.

Правила срока и числа сравнивают все значения своего вида в документе, поэтому кандидатов обычно больше,
чем итоговых нарушений.

## 7. Ошибки моделей

| Ответ                            | Что делать                                                     |
|----------------------------------|----------------------------------------------------------------|
| `429 model_rate_limited`         | Лимит запросов: повторите через минуту                         |
| `504 model_timeout`              | Модель не ответила вовремя: повторите запрос                   |
| `503 model_provider_error`       | Аудит не выполнен: проверьте ключ, пресет и журнал             |
| `503 classification_model_error` | Тип не определён: повторите запрос или подтвердите тип вручную |
| `503 rule_extraction_error`      | Смотрите `/api/legal-acts/{id}/diagnostics`, затем `reprocess` |
| `503 rag_index_error`            | Изменение сохранено, но индекс не пересобран                   |

## 8. Прямая проверка базы

```bash
sqlite3 data/edm_auditor.sqlite3 \
  "SELECT id, rule_code, severity, check_type, is_active, name FROM audit_rules;"

sqlite3 data/edm_auditor.sqlite3 "SELECT id, code, title, processing_status FROM legal_acts;"

sqlite3 data/edm_auditor.sqlite3 "SELECT version_num FROM alembic_version;"
```

## 9. RAG-индекс

```bash
python -m edm_auditor.rag count
python -m edm_auditor.rag search "продолжительность отпуска" --threshold 0.1
python -m edm_auditor.rag build
```

Команды `build` и `search` обращаются к модели эмбеддингов выбранного пресета.
