# Настройка моделей

Файл `backend/config/models.toml` описывает доступные профили embedding-моделей
и LLM, а также готовые пресеты для окружений. Секреты в этот файл не
записываются: API-ключ передаётся через переменную окружения, указанную в
`api_key_env`.

## Структура файла

В файле также задаются общие ограничения обработки НПА:

```toml
[legal_act_processing.chunking]
max_chars = 4000
overlap_chars = 0
max_rules_per_chunk = 20

[legal_act_processing]
max_prompt_chars = 12000
max_response_tokens = 2000
source_language = "auto"
extraction_schema_version = "1"
prompt_version = "1"
processing_version = "1"
```

`source_language` принимает `auto`, `ru` или `en`. Для доверенного локального
запуска его можно переопределить через `EDM_SOURCE_LANGUAGE`. Неподдерживаемые
значения отклоняются до запуска обработки.

Профили экстракторов также поддерживают `request_timeout_seconds`,
`retry_attempts`, `retry_backoff_factor` и `inter_chunk_delay_seconds`. Эти
параметры валидируются при загрузке конфигурации и будут использоваться
orchestration-слоем обработки chunks.

В файле используются следующие разделы:

```toml
[profiles.embedding.<name>]
...

[profiles.llm.<name>]
...

[profiles.extractor.<name>]
...

[presets.<name>]
embedding = "<embedding-profile>"
llm = "<llm-profile>"
extractor = "<extractor-profile>"
```

Профиль описывает одну модель, а preset связывает embedding-модель, LLM и
модель извлечения сущностей и правил. Приложение выбирает preset через
`EDM_MODEL_PRESET`. Эта переменная обязательна: пресета по умолчанию и
offline-режима нет, без неё API не запускается.

## Профиль извлечения сущностей

NuExtract3 можно подключить через OpenAI-compatible endpoint LM Studio:

```toml
[profiles.extractor.nuextract]
provider = "openai-compatible"
model = "numind/NuExtract3"
base_url = "http://localhost:1234/v1"
temperature = 0.2
max_tokens = 2000
```

Модель получает текст документа и JSON-шаблон, а затем возвращает сущности с
verbatim-значениями. Их позиции восстанавливаются по исходному тексту, поэтому
формулировки вроде `14 календарных дней` сохраняются без потери контекста.
Если модель недоступна или возвращает некорректный JSON, аудит использует
локальный extractor и добавляет диагностическое сообщение
`entity-extraction` в отчёт.

## Профиль embedding-модели

Пример:

```toml
[profiles.embedding.local-multilingual]
provider = "openai-compatible"
model = "text-embedding-model"
base_url = "http://localhost:1234/v1"
dimension = 768
```

Поля:

| Поле          |             Обязательно | Описание                                                    |
|---------------|------------------------:|-------------------------------------------------------------|
| `provider`    |                      да | `openai-compatible` или `google-ai-studio`                  |
| `model`       |                      да | Точное имя модели на выбранном сервере                      |
| `base_url`    | для `openai-compatible` | Адрес OpenAI-compatible API без `/embeddings`               |
| `dimension`   |        да для embedding | Размерность вектора, которую возвращает модель              |
| `api_key_env` |                     нет | Имя переменной окружения с API-ключом                       |

`dimension` должна точно соответствовать ответу модели. После смены модели или
размерности существующий RAG-индекс необходимо пересобрать: старый индекс
намеренно отклоняется как несовместимый.

Для `google-ai-studio` используется официальный пакет `google-genai`, модель
`gemini-embedding-2` и API-ключ из `GEMINI_API_KEY`. При сбое провайдера
пересборка индекса завершается ошибкой, а прежний индекс остаётся активным:
подменные векторы в индекс не попадают.

## Профиль LLM

Пример:

```toml
[profiles.llm.openrouter]
provider = "openai-compatible"
model = "provider/model-name"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
temperature = 0.1
max_tokens = 2000
structured_output = "json_schema"
```

Google AI Studio использует официальный SDK, а не OpenAI-compatible endpoint:

```toml
[profiles.llm.google-ai-studio]
provider = "google-ai-studio"
model = "gemma-4-31b-it"
api_key_env = "GEMINI_API_KEY"
structured_output = "json_schema"
```

Для включения Google AI Studio используйте:

```bash
export GEMINI_API_KEY="your-api-key"
export EDM_MODEL_PRESET="google-ai-studio"
```

Этот preset использует `gemma-4-31b-it` для анализа, извлечения сущностей и
создания правил из НПА, а `gemini-embedding-2` — для RAG-индекса. После смены
embedding-модели старый RAG-индекс нужно пересобрать.

Поля:

| Поле                |             Обязательно | Описание                                                      |
|---------------------|------------------------:|---------------------------------------------------------------|
| `provider`          |                      да | `openai-compatible` или `google-ai-studio`                    |
| `model`             |                      да | Имя модели в LM Studio, OpenRouter или другом совместимом API |
| `base_url`          | для `openai-compatible` | Адрес API без `/chat/completions`                             |
| `api_key_env`       |       для облачного API | Имя переменной с ключом                                       |
| `temperature`       |                     нет | Температура генерации, по умолчанию `0.1`                     |
| `max_tokens`        |                     нет | Максимальный размер ответа, по умолчанию `2000`               |
| `structured_output` |                      да | `false`, `"json_object"` или `"json_schema"`                  |

`structured_output` обязателен для каждого LLM-профиля. Для Gemma 4 в LM
Studio используйте `"json_schema"`:

```json
{
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "audit_analysis",
      "strict": true,
      "schema": "..."
    }
  }
}
```

Значение `"json_object"` используется только для endpoint, который поддерживает
JSON mode без схемы. Значение `false` отключает параметр. Приложение всё равно
валидирует ответ самостоятельно и не доверяет модели без проверки.

LLM вызывается при каждом аудите, в том числе когда правила не нашли findings:
в этом случае модель возвращает только `general_summary`. Если ответ ссылается
на неизвестный `finding_key`, он отклоняется и аудит завершается ошибкой.

## Пресеты

Чтобы добавить пресет, сначала создайте необходимые профили, затем свяжите их:

```toml
[presets.local-dev]
embedding = "local-multilingual"
llm = "lm-studio"
extractor = "nuextract"
```

Имена в `embedding`, `llm` и `extractor` должны точно совпадать с именами
профилей соответствующего раздела. Один preset не должен ссылаться на embedding-профиль
как на LLM-профиль или наоборот.

## Секреты и запуск

Скопируйте пример окружения и задайте секреты только в локальном окружении:

```bash
cd backend
export EDM_MODEL_PRESET=openrouter
export OPENROUTER_API_KEY="your-key"
```

Для другого конфигурационного файла:

```bash
export EDM_MODEL_CONFIG=/absolute/path/to/models.toml
```

Путь по умолчанию: `backend/config/models.toml`. Файл `.env.example` содержит
только имена переменных и не является хранилищем ключей. При запуске API файл
`backend/.env` загружается автоматически. Уже экспортированные переменные
окружения имеют приоритет над значениями из `.env`.

## LM Studio

1. Запустите OpenAI-compatible server в LM Studio.
2. Укажите фактические имена embedding- и chat-моделей.
3. Проверьте `base_url`, обычно это `http://localhost:1234/v1`.
4. Выберите preset:

```bash
EDM_MODEL_PRESET=lm-studio python -m edm_auditor.rag build
```

Embedding-модель должна поддерживаться сервером отдельно от chat-модели.
Подстановка произвольного имени из примера без загруженной модели приведёт к
ошибке удалённого API.

## OpenRouter

Задайте `OPENROUTER_API_KEY` и используйте preset:

```bash
export EDM_MODEL_PRESET=openrouter
export OPENROUTER_API_KEY="your-key"
python -m edm_auditor.rag build
```

В текущей конфигурации embedding-профиль `local-multilingual` всё ещё указывает
на локальный OpenAI-compatible endpoint, а LLM работает через OpenRouter. Если
embedding должен также работать через облачный API, создайте отдельный
embedding-профиль с его endpoint и размерностью и укажите его в preset.

## Ограничения текущей версии

- Конфигурация моделей уже типизирована и провайдеры подключаются через
  registry-функции.
- Production embedding-модель и её окончательная размерность ещё не выбраны.
- LLM-адаптер встроен в persistence/API как вспомогательный слой и
  интерпретирует только уже найденные findings; он не принимает юридические
  решения сам по себе.
- Тесты не требуют сети или API-ключей: дублёры провайдеров находятся в
  `tests/fakes.py` и в рабочий код не входят.
- Нельзя хранить реальные ключи в `models.toml`, `.env.example`, Git или
  сообщениях об ошибках.

## Neural-анализ API

API всегда инициализирует настроенные LLM и extractor-провайдеры. Заглушек и
резервных режимов нет. Если модель недоступна, ключ отсутствует или ответ не
прошёл проверку, аудит прерывается: API возвращает `503` с кодом
`model_provider_error`, отчёт не сохраняется, документ получает статус `error`.
Временные ошибки (429, 500, 503) предварительно повторяются согласно
`retry_attempts` и `retry_backoff_factor` профиля. `EDM_NEURAL_MODE` больше не
используется.

Для локального LM Studio:

```bash
export EDM_MODEL_CONFIG="$PWD/config/models.toml"
export EDM_MODEL_PRESET=lm-studio
uvicorn edm_auditor.api.app:create_app --factory --reload
```

Для production выберите online preset и задайте его ключ.

`GET /api/documents/{id}/report` содержит `neural_status` и
`neural_analyses`. Модель получает только findings и связанные RAG-контексты;
она не может изменить severity, диапазоны, rule IDs или добавить неизвестные
нормативные ссылки.
