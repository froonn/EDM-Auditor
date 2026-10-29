# Настройка моделей

Файл `backend/config/models.toml` описывает доступные профили embedding-моделей
и LLM, а также готовые пресеты для окружений. Секреты в этот файл не
записываются: API-ключ передаётся через переменную окружения, указанную в
`api_key_env`.

## Структура файла

В файле используются два раздела:

```toml
[profiles.embedding.<name>]
...

[profiles.llm.<name>]
...

[presets.<name>]
embedding = "<embedding-profile>"
llm = "<llm-profile>"
```

Профиль описывает одну модель, а preset связывает одну embedding-модель с одной
LLM. Приложение выбирает preset через `EDM_MODEL_PRESET`. По умолчанию
используется `offline`.

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

| Поле | Обязательно | Описание |
|---|---:|---|
| `provider` | да | `deterministic` или `openai-compatible` |
| `model` | да | Точное имя модели на выбранном сервере |
| `base_url` | для `openai-compatible` | Адрес OpenAI-compatible API без `/embeddings` |
| `dimension` | да для embedding | Размерность вектора, которую возвращает модель |
| `api_key_env` | нет | Имя переменной окружения с API-ключом |

`dimension` должна точно соответствовать ответу модели. После смены модели или
размерности существующий RAG-индекс необходимо пересобрать: старый индекс
намеренно отклоняется как несовместимый.

Для `deterministic` используется offline-провайдер. Он предназначен для тестов
и локальной разработки, а не для production-поиска.

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
```

Поля:

| Поле | Обязательно | Описание |
|---|---:|---|
| `provider` | да | `stub` или `openai-compatible` |
| `model` | да | Имя модели в LM Studio, OpenRouter или другом совместимом API |
| `base_url` | для `openai-compatible` | Адрес API без `/chat/completions` |
| `api_key_env` | для облачного API | Имя переменной с ключом |
| `temperature` | нет | Температура генерации, по умолчанию `0.1` |
| `max_tokens` | нет | Максимальный размер ответа, по умолчанию `2000` |

`stub` не выполняет сетевые запросы и возвращает технический ответ
`not_configured`. Это безопасный вариант для тестов.

## Пресеты

Готовый offline-пресет:

```toml
[presets.offline]
embedding = "deterministic"
llm = "stub"
```

Чтобы добавить пресет, сначала создайте необходимые профили, затем свяжите их:

```toml
[presets.local-dev]
embedding = "local-multilingual"
llm = "lm-studio"
```

Имена в `embedding` и `llm` должны точно совпадать с именами профилей
соответствующего раздела. Один preset не должен ссылаться на embedding-профиль
как на LLM-профиль или наоборот.

## Секреты и запуск

Скопируйте пример окружения и задайте секреты только в локальном окружении:

```bash
cd backend
export EDM_MODEL_PRESET=offline
export OPENROUTER_API_KEY="your-key"
```

Для другого конфигурационного файла:

```bash
export EDM_MODEL_CONFIG=/absolute/path/to/models.toml
```

Путь по умолчанию: `backend/config/models.toml`. Файл `.env.example` содержит
только имена переменных и не является хранилищем ключей. В текущей реализации
`.env` автоматически не загружается, поэтому переменные нужно экспортировать
через оболочку, IDE или менеджер секретов.

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
- LLM-адаптер доступен, но пока не встроен в `AuditEngine` и не принимает
  юридические решения сам по себе.
- Базовые тесты используют `offline` и не требуют сети или API-ключей.
- Нельзя хранить реальные ключи в `models.toml`, `.env.example`, Git или
  сообщениях об ошибках.
