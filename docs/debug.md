# Руководство по отладке и работе с API (debug.md)

В данном руководстве описаны типовые сценарии работы с запущенным бэкендом `EDM-Auditor`: просмотр и управление
правилами проверки, решение проблемы отображения кириллицы в JSON, работа с нормативно-правовыми актами (НПА), запуск
аудита и диагностика базы данных.

---

## 0. Обновление существующей базы

Этап настройки аудита меняет схему. Если база устарела, сервер не запустится и
подскажет команду. Сделайте резервную копию и выполните из `backend/`:

```bash
cp data/edm_auditor.sqlite3 data/edm_auditor.sqlite3.bak
# Только если в базе нет таблицы alembic_version:
alembic stamp 0005_rule_publication_metadata
alembic upgrade head
```

Ручные правила без типа остаются универсальными, правила с типом становятся
`typed`, а сгенерированные правила без типа получают область `unknown`: задайте
типы их НПА через `PATCH /api/legal-acts/{id}`. Старые отчёты не изменяются.

---

## 1. Запуск сервера для отладки

Сервер запускается из каталога [`backend/`](file:///home/froonn/Documents/BSIUR/cw/EDM-Auditor/backend):

```bash
cd backend
source .venv/bin/activate
uvicorn edm_auditor.api.app:create_app --factory --reload --port 8000
```

Проверка доступности сервиса:

```bash
curl -s http://127.0.0.1:8000/health | jq .
```
Ожидаемый ответ: `{"status": "ok"}`.

Интерактивная документация Swagger UI доступна по адресу:
* **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

### 1.1. Файл детального журнала (`data/debug.log`)

Чтобы не перегружать консоль терминала сырыми JSON-структурами и заголовками, логирование разделено:
* **В терминал** выводятся стандартные краткие системные сообщения сервера.
* **В файл [`backend/data/debug.log`](file:///home/froonn/Documents/BSIUR/cw/EDM-Auditor/backend/data/debug.log)** (путь настраивается через `EDM_LOG_FILE`) записываются диагностические сведения:
  * Каждый входящий HTTP-запрос (метод, URL, `request_id`, заголовки и тело);
  * Каждый исходящий ответ (статус-код, заголовки, тело ответа);
  * Размеры prompt/response, идентификаторы моделей и статусы provider-вызовов;
  * Статусы обработки чанков и результаты валидации правил.

Содержимое НПА, API-ключи, полные prompt и raw response моделей в лог не
записываются. Не публикуйте `debug.log`, если в HTTP-телах присутствуют
чувствительные данные.

Для просмотра лога в реальном времени:
```bash
tail -f backend/data/debug.log
```

---

## 2. Просмотр правил аудита (корректное отображение кириллицы)

Эндпоинт **`GET /api/rules`** возвращает список зарегистрированных правил аудита.

### Почему кириллица отображается как `\u0443\u0441\u043b...`?

Сервер FastAPI возвращает данные в кодировке UTF-8. Если при запросе через `curl` перенаправить вывод в утилиту
`python -m json.tool`, она по умолчанию экранирует все не-ASCII символы (`ensure_ascii=True`).

### Способы корректного отображения:

#### Способ A: `python -m json.tool` с флагом `--no-ensure-ascii`

```bash
curl -s http://127.0.0.1:8000/api/rules | python3 -m json.tool --no-ensure-ascii
```

#### Способ B: Использование `jq` (рекомендуется)

Утилита `jq` по умолчанию корректно выводит UTF-8 с подсветкой синтаксиса:

```bash
curl -s http://127.0.0.1:8000/api/rules | jq .
```

#### Способ C: Просмотр через однострочник Python

```bash
curl -s http://127.0.0.1:8000/api/rules | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, indent=2))"
```

#### Способ D: Через браузер (Swagger UI)

Откройте в браузере [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs), разверните блок `GET /api/rules`, нажмите
**Try it out** → **Execute**. Браузер отобразит читаемый русский текст без экранирования.

---

### Фильтрация списка правил

Эндпоинт поддерживает параметры фильтрации в query-параметрах:

* **Только активные правила:**
  ```bash
  curl -s "http://127.0.0.1:8000/api/rules?is_active=true" | jq .
  ```
* **Фильтр по типу проверки (`check_type`):**
  ```bash
  curl -s "http://127.0.0.1:8000/api/rules?check_type=duration" | jq .
  ```
* **Пагинация (`limit`, `offset`):**
  ```bash
  curl -s "http://127.0.0.1:8000/api/rules?limit=10&offset=0" | jq .
  ```

---

## 3. Удаление правила аудита

Для удаления правила используется метод **`DELETE /api/rules/{rule_id}`**:

```bash
curl -i -X DELETE http://127.0.0.1:8000/api/rules/1
```

* **Код ответа:** `204 No Content` при успешном удалении, `404 Not Found`, если правило не найдено.
* **Что происходит внутри системы:**
    1. Правило удаляется из таблицы `audit_rules`.
    2. Автоматически пересобирается векторный RAG-индекс (`rag-index.sqlite3`), исключая контекст удаленного правила.
    3. Существующие отчеты об аудитах **сохраняются**: в таблице `audit_findings` поле `rule_id` сбрасывается в `NULL`
       (благодаря внешнему ключу `ondelete="SET NULL"`), поэтому текст ранее найденных нарушений не теряется.

---

## 4. Добавление правила вручную

Правила создаются через **`POST /api/rules`**.

### Пример: Создание правила на минимальную продолжительность отпуска (числовое)

```bash
curl -s -X POST http://127.0.0.1:8000/api/rules \
  -H "Content-Type: application/json" \
  -d '{
    "rule_code": "vacation-min-24-days",
    "name": "Минимальная продолжительность отпуска",
    "severity": "critical",
    "description": "Основной отпуск должен быть не менее 24 календарных дней (ст. 155 ТК РБ).",
    "check_type": "duration",
    "parameters": {
      "min_days": 24
    },
    "is_active": true
  }' | jq .
```

### Допустимые значения параметров:

* **`severity`**: `low`, `medium`, `high`, `critical`.
* **`check_type`**:
    * `keyword` — поиск ключевых слов (параметр: `{"keywords": ["слово1", "слово2"]}`);
    * `regex` — регулярное выражение (параметр: `{"pattern": "..."}`);
    * `numeric` — ограничение на числовые величины (параметр:
      `{"entity": "money"|"percent"|"number"|"duration", "min": 100, "max": 500}`);
    * `duration` — ограничение на количество дней (параметр: `{"min_days": 1, "max_days": 30}`);
    * `date` — ограничение даты (параметр: `{"before": "2026-12-31"}` или
      `{"after": "2026-01-01"}`);
    * `semantic` — проверка через семантический поиск (параметр:
      `{"query": "условия оплаты", "k": 3, "threshold": 0.5}`).

---

## 5. Работа с нормативно-правовыми актами (НПА)

Загрузка НПА запускает online extraction правил синхронно. Для этого API
должен быть запущен с preset, содержащим online extractor, например
`lm-studio`, `openrouter` или `google-ai-studio`. Без `EDM_MODEL_PRESET` API не
запускается, а при сбое модели отвечает `503` и не создаёт отчёт.

### Просмотр списка НПА

```bash
curl -s http://127.0.0.1:8000/api/legal-acts | jq .
```

*(Список не включает полный текст статей для экономии трафика)*.

### Просмотр детальной информации по конкретному НПА (с полным текстом статьи)

```bash
curl -s http://127.0.0.1:8000/api/legal-acts/1 | jq .
```

### Загрузка НПА из текстового файла

```bash
curl -s -X POST http://127.0.0.1:8000/api/legal-acts/upload \
  -F "code=TK-RB" \
  -F "title=Трудовой кодекс Республики Беларусь" \
  -F "number=218-З" \
  -F "file=@examples/legal_act.txt" | jq .
```

Ответ содержит `processing_status`, счётчики чанков и правил. После загрузки
диагностику можно получить так:

```bash
curl -s http://127.0.0.1:8000/api/legal-acts/1/diagnostics | jq .
```

Для повторной обработки уже сохранённого НПА:

```bash
curl -s -X POST http://127.0.0.1:8000/api/legal-acts/1/reprocess | jq .
```

Команду выше нужно выполнять из каталога `backend/`. Если текущий каталог —
корень репозитория, используйте `-F "file=@backend/examples/legal_act.txt"`.

> [!NOTE]
> При настроенном online нейросетевом провайдере при загрузке текстового файла НПА
система может автоматически извлечь и создать машиночитаемые правила аудита.

### Удаление НПА

```bash
curl -i -X DELETE http://127.0.0.1:8000/api/legal-acts/1
```

После удаления акта RAG-индекс автоматически пересобирается.

---

## 6. Проведение аудита документов через API

### Шаг 1: Загрузка документа (`.txt`, `.pdf`, `.docx`)

```bash
curl -s -X POST http://127.0.0.1:8000/api/documents/upload \
  -F "title=Трудовой договор Иванов" \
  -F "file=@backend/examples/contract.txt" | jq .
```

Команда вернет JSON с метаданными документа, например `{"id": 1, "status": "uploaded", ...}`.

### Шаг 2: Запуск аудита

```bash
curl -s -X POST http://127.0.0.1:8000/api/documents/1/audit | jq .
```

### Шаг 3: Получение структурированного отчета

```bash
curl -s http://127.0.0.1:8000/api/documents/1/report | jq .
```

В отчете возвращаются:

* Общее количество нарушений (`total_findings`) и статистика по `severity`;
* Список нарушений (`findings`): точный диапазон символов в тексте (`start_char`, `end_char`), цитата (`quote`),
  описание проблемы и рекомендация по исправлению;
* Статус нейросетевого анализа (`neural_status`: `completed`, `skipped`, `failed` или `not_requested`).

---

## 6.1. Настройка аудита: классификация и выбор правил

При загрузке документ автоматически классифицируется: LLM выбирает типы из каталога
по их названиям и описаниям. Если модель недоступна, документ сохраняется со статусом
`pending`, а тип запрашивается повторно перед аудитом. Это подсказка, а не юридическое
решение: тип и набор правил нужно проверять, а результат аудита не заменяет проверку
юристом.

Если тип не подтверждён (`classification_status` равен `needs_review` или
`unknown`), автоматический аудит отвечает `409 audit_configuration_required` и не
создаёт отчёт. Кандидаты модели сами по себе правила не включают.

```bash
# Каталог типов
curl -s http://127.0.0.1:8000/api/document-types | jq .
curl -s -X POST http://127.0.0.1:8000/api/document-types \
  -H 'Content-Type: application/json' \
  -d '{"code":"travel_expense_report","name":"Авансовый отчёт","description":"Отчёт работника о расходах в командировке."}' | jq .

# Новые типы, предложенные моделью: добавить в каталог или отклонить
curl -s http://127.0.0.1:8000/api/document-type-suggestions | jq .
curl -s -X POST http://127.0.0.1:8000/api/document-type-suggestions/1/accept \
  -H 'Content-Type: application/json' \
  -d '{"code":"travel_expense_report"}' | jq .
curl -s -X POST http://127.0.0.1:8000/api/document-type-suggestions/1/dismiss

# Классификация документа и её ручное подтверждение
curl -s -X POST http://127.0.0.1:8000/api/documents/1/classify | jq .
curl -s -X PATCH http://127.0.0.1:8000/api/documents/1/classification \
  -H 'Content-Type: application/json' \
  -d '{"confirmed_document_types":["business_trip_order"]}' | jq .

# Предпросмотр: тот же набор правил, что и при запуске
curl -s -X POST http://127.0.0.1:8000/api/documents/1/audit/preview | jq .

# Запуск с настройкой выбора
curl -s -X POST http://127.0.0.1:8000/api/documents/1/audit \
  -H 'Content-Type: application/json' \
  -d '{"selection_mode":"manual","legal_act_ids":[1],"excluded_rule_ids":[5]}' | jq .
```

Режимы выбора:

| `selection_mode` | Какие правила применяются                                                 |
|------------------|---------------------------------------------------------------------------|
| `automatic`      | универсальные и совпавшие по подтверждённому типу; `legal_act_ids` сужает выбор |
| `manual`         | только `included_rule_ids` и правила из `legal_act_ids`                   |
| `combined`       | автоматический набор плюс ручной выбор                                    |
| `all`            | все активные правила; нужен `"confirm_all": true`, возможны ложные нарушения |

Исключение всегда сильнее включения, а неактивные правила не применяются никогда.
Правила с областью `manual_only` применяются только через `included_rule_ids`.

Область применимости сгенерированных правил берётся из типов НПА. Если типы не
заданы, НПА классифицируется так же, как документ, а при недостаточной
уверенности правила получают область `unknown` и автоматически не применяются:

```bash
# Типы при загрузке НПА: добавьте -F document_types=business_trip_order,vacation_order
# Типы существующего НПА: обновляются и его сгенерированные правила
curl -s -X PATCH http://127.0.0.1:8000/api/legal-acts/1 \
  -H 'Content-Type: application/json' \
  -d '{"document_types":["business_trip_order"]}' | jq .

# Ручная применимость отдельного правила
curl -s -X PATCH http://127.0.0.1:8000/api/rules/1/applicability \
  -H 'Content-Type: application/json' \
  -d '{"applicability_scope":"typed","document_types":["payroll_order"]}' | jq .
```

В `warnings` и `reason` предпросмотра и поля `selection` отчёта встречаются:

| Код                                | Значение                                         |
|------------------------------------|--------------------------------------------------|
| `document_type_unknown`            | тип определить не удалось                        |
| `classification_low_confidence`    | есть кандидаты, но тип не подтверждён            |
| `manual_selection_required`        | нужно подтвердить тип или выбрать правила        |
| `no_applicable_rules`              | подходящих правил нет (`409`)                    |
| `rule_excluded_by_document_type`   | правило относится к другому типу                 |
| `rule_excluded_by_legal_act_scope` | НПА правила не входит в выбранные                |
| `rule_excluded_by_user`            | правило исключено вручную                        |
| `rule_applicability_unknown`       | применимость правила неизвестна                  |
| `rag_candidate_below_threshold`    | RAG-кандидат ниже порога; на выбор не влияет     |
| `rag_unavailable`                  | RAG недоступен; проверки правил продолжаются     |

RAG только показывает связанные НПА со `score` и `threshold` и никогда не включает
правило. Правила типа `semantic` через API пока не выполняются: движку не передан
поисковик, поэтому такое правило попадает в `summary.diagnostics`.

---

## 7. Прямая диагностика базы данных SQLite

Если сервер остановлен или нужно проверить сырые записи:

Файл базы данных находится по пути [
`backend/data/edm_auditor.sqlite3`](file:///home/froonn/Documents/BSIUR/cw/EDM-Auditor/backend/data/edm_auditor.sqlite3).

### Быстрый просмотр правил через консоль SQLite:

```bash
sqlite3 backend/data/edm_auditor.sqlite3 \
  "SELECT id, rule_code, severity, check_type, is_active, name FROM audit_rules;"
```

### Быстрый просмотр загруженных НПА:

```bash
sqlite3 backend/data/edm_auditor.sqlite3 \
  "SELECT id, code, title, number FROM legal_acts;"
```

### Скрипт быстрой проверки состояния через Python:

```bash
cd backend
python - <<'PY'
import sqlite3

conn = sqlite3.connect("data/edm_auditor.sqlite3")
cur = conn.cursor()

for table in ["legal_acts", "audit_rules", "documents", "audit_reports", "audit_findings"]:
    count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"Таблица {table:16}: {count} записей")
PY
```

---

## 8. Проверка RAG-индекса через CLI

Векторный индекс хранится в `backend/data/rag-index.sqlite3`. Для его инспекции доступен встроенный CLI-модуль:

```bash
cd backend

# Проверить количество проиндексированных фрагментов
python -m edm_auditor.rag count

# Выполнить тестовый поиск по нормативной базе
python -m edm_auditor.rag search "продолжительность отпуска" --threshold 0.1

# Принудительная полная пересборка индекса из базы
python -m edm_auditor.rag build
```


## быстрая проверка 

Загрузить НПА
```bash
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
```

Посмотреть доступные правила
```bash
curl -s http://127.0.0.1:8000/api/rules | jq .
```

Загрузить документ
```bash
curl -sS -X POST http://127.0.0.1:8000/api/documents/upload \
  -F file=@examples/remote_work_agreement.txt | jq .
```

Отправить документ на аудит
```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/documents/<DOCUMENT_ID>/audit | jq .
```

Посмотреть отчет аудита документа
```bash
curl -s \
  http://127.0.0.1:8000/api/documents/<DOCUMENT_ID>/report?report_id=<REPORT_ID> \
  | jq .
```
