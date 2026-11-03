# Руководство по отладке и работе с API (debug.md)

В данном руководстве описаны типовые сценарии работы с запущенным бэкендом `EDM-Auditor`: просмотр и управление
правилами проверки, решение проблемы отображения кириллицы в JSON, работа с нормативно-правовыми актами (НПА), запуск
аудита и диагностика базы данных.

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
Локальный графический веб-интерфейс доступен по адресу:
* **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

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
`lm-studio`, `openrouter` или `google-ai-studio`. Preset `offline` предназначен
для тестов и локальных компонентов и не является production-конфигурацией API.

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
