# План разработки: авторизация, роли и разграничение доступа (FR-6.3)

Ветка `feature/auth-rbac`, ответвлена от `master`. Реализует требование **FR-6.3** из [`TASK.md`](TASK.md) и
раздела «Авторизация и роли (FR-6.3)» в [`DIPLOMA.md`](DIPLOMA.md).

---

## 1. Цель и зафиксированные архитектурные решения

Перевести `EDM-Auditor` из однопользовательского локального режима в многопользовательский режим с серверной
аутентификацией, ролевой моделью доступа (RBAC), изоляцией документов по владельцу, резолюциями аудиторов и
защищённым логированием.

### 1.1. Способ аутентификации — серверные HttpOnly cookie-сессии

Выбраны **серверные сессии в БД с HttpOnly cookie** (а не stateless JWT) по следующим причинам:

1. **Мгновенный отзыв доступа:** при выходе, смене пароля, смене роли или блокировке пользователя сессии
   инвалидируются сразу в БД (без ожидания истечения access-токена и без отдельного blacklist).
2. **Защита от XSS:** cookie с флагами `HttpOnly; SameSite=Lax; Path=/` (и `Secure` при HTTPS через
   `EDM_COOKIE_SECURE=true`) недоступна из JavaScript; в `localStorage` ничего не хранится.
3. **Совместимость с текущей архитектурой:** `frontend/src/api/client.ts` уже отправляет
   `credentials: "same-origin"`, а Nginx и Vite проксируют `/api` на одном origin — дополнительная настройка
   CORS для основного веб-интерфейса не требуется.
4. **Защита хранилища сессий:** клиент получает случайный 256-битный токен (`secrets.token_urlsafe(32)`), а в
   таблице `user_sessions` хранится только его `SHA-256` хэш.

### 1.2. Хэширование паролей

- Алгоритм **Argon2id** (`argon2-cffi`, рекомендуемый OWASP стандарт для хранения паролей).
- Пароли никогда не возвращаются API и не попадают в логи.

### 1.3. Ролевая модель (4 роли)

Расширяем существующее перечисление `UserRole` с 3 до **4 ролей**, выделив отдельную группу юристов для
ведения нормативной базы:

| Роль      | Название                | Назначение и зона ответственности                                                                                                    |
|-----------|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `admin`   | Администратор           | Полный доступ ко всем ресурсам системы, управление пользователями и ролями, настройка безопасности.                                  |
| `lawyer`  | Юрист                   | Ведение нормативной базы (НПА, правила, типы документов и заявки типов), просмотр всех документов, запуск аудита, резолюции.         |
| `auditor` | Аудитор                 | Просмотр всех документов (включая старые без владельца), запуск аудита, просмотр/экспорт отчётов, резолюции; НПА/правила — read-only. |
| `hr`      | Сотрудник / Кадровик    | Загрузка своих документов, запуск аудита и просмотр/экспорт отчётов **только по своим документам**, чтение резолюций по ним.         |

### 1.4. Создание пользователей и старые документы (`user_id IS NULL`)

- **Первый администратор** создаётся идемпотентно через CLI (`python -m edm_auditor.auth.cli create-admin`)
  или при старте приложения из переменных окружения (`EDM_INITIAL_ADMIN_USERNAME`, `EDM_INITIAL_ADMIN_EMAIL`,
  `EDM_INITIAL_ADMIN_PASSWORD`), если в БД ещё нет ни одного пользователя с ролью `admin`.
- **Новых пользователей** создаёт, изменяет (роль, активность, сброс пароля) только `admin`. Публичной
  саморегистрации нет.
- **Старые документы без владельца (`documents.user_id IS NULL`)** видны ролям `admin`, `lawyer` и `auditor`,
  и скрыты от роли `hr`. Все новые загрузки записывают `documents.user_id = current_user.id`.

---

## 2. Матрица прав (RBAC)

Сервер проверяет права (permissions), а не «захардкоженные» имена ролей в каждом обработчике. Фронтенд
получает набор прав текущего пользователя из `GET /api/auth/me` и использует его только для отображения UI.

### 2.1. Соответствие ролей и прав

| Право (`Permission`)    | Описание                                                     | `admin` | `lawyer` | `auditor` | `hr` |
|-------------------------|--------------------------------------------------------------|:-------:|:--------:|:---------:|:----:|
| `documents.upload`      | Загрузка новых документов                                    |    ✓    |    ✓     |     ✓     |  ✓   |
| `documents.read_all`    | Доступ ко всем документам и отчётам (включая `user_id=NULL`) |    ✓    |    ✓     |     ✓     |  —   |
| `documents.delete_any`  | Удаление любого документа (без права — только своих)         |    ✓    |    —     |     —     |  —   |
| `audit.run`             | Классификация, настройка, предпросмотр, запуск аудита, линковка положений | ✓ | ✓ | ✓ | ✓ *(свои)* |
| `reports.read`          | Просмотр документов и отчётов аудита                         |    ✓    |    ✓     |     ✓     | ✓ *(свои)* |
| `reports.export`        | Экспорт отчёта в HTML                                        |    ✓    |    ✓     |     ✓     | ✓ *(свои)* |
| `resolutions.write`     | Написание резолюций аудитора по отчётам                      |    ✓    |    ✓     |     ✓     |  —   |
| `legal_acts.read`       | Просмотр НПА, текста акта и диагностики извлечения           |    ✓    |    ✓     |     ✓     |  —   |
| `legal_acts.edit`       | Загрузка, создание, правка, переобработка, удаление НПА      |    ✓    |    ✓     |     —     |  —   |
| `rules.read`            | Просмотр правил и их применимости                            |    ✓    |    ✓     |     ✓     |  —   |
| `rules.edit`            | Создание, редактирование, применимость, удаление правил      |    ✓    |    ✓     |     —     |  —   |
| `document_types.read`   | Просмотр каталога типов и предложений новых типов            |    ✓    |    ✓     |     ✓     | ✓ *(каталог)* |
| `document_types.edit`   | Создание/правка/деактивация типов, принятие/отклонение заявок |   ✓    |    ✓     |     —     |  —   |
| `users.manage`          | Просмотр, создание, смена ролей, блокировка, сброс паролей   |    ✓    |    —     |     —     |  —   |

> **Уточнение по `hr` и справочникам:** `GET /api/document-types` и `GET /api/rules`/`GET /api/legal-acts`
> используются на экране настройки аудита (`/documents/:id/configure`) при ручном/комбинированном выборе
> правил. Поэтому при реализации проверим, какие read-эндпоинты нужны `AuditConfigPage` для `hr`: либо дадим
> `hr` чтение активного каталога типов/списка НПА/правил для селектора (оставив вкладки управления скрытыми),
> либо отделим `audit_catalog.read` от экранов администрирования НПА.

### 2.2. Привязка эндпоинтов API к правам

| Группа / эндпоинт                                                            | Требование доступа                                           |
|------------------------------------------------------------------------------|--------------------------------------------------------------|
| `GET /health`                                                                | Публичный (для Docker healthcheck)                           |
| `POST /api/auth/login`, `POST /api/auth/logout`                              | Публичный (rate-limited для `login`)                         |
| `GET /api/auth/me`, `POST /api/auth/logout-all`, `POST /api/auth/change-password` | Любой активный авторизованный пользователь               |
| `GET/POST/PATCH /api/users*`                                                 | `users.manage` (`admin`)                                     |
| `GET /api/documents`, `GET /api/reports`                                     | `reports.read` + фильтр по `user_id` без `documents.read_all` |
| `POST /api/documents/upload`                                                 | `documents.upload` (ставит `user_id = current_user.id`)      |
| `GET /api/documents/{id}`, `.../statements`, `.../report`, `GET /api/reports/{id}` | `reports.read` + проверка доступа к документу          |
| `GET /api/reports/{id}/export`                                               | `reports.export` + проверка доступа к документу              |
| `DELETE /api/documents/{id}`                                                 | Владелец документа или `documents.delete_any` (`admin`)      |
| `POST .../classify`, `PATCH .../classification`, `POST .../statements/extract`, `PATCH .../statements/{sid}/link`, `POST .../audit/preview`, `POST .../audit` | `audit.run` + проверка доступа к документу |
| `GET /api/reports/{id}/resolutions`                                          | `reports.read` + проверка доступа к документу                |
| `POST /api/reports/{id}/resolutions`                                         | `resolutions.write` + проверка доступа к документу           |
| `GET /api/legal-acts*`                                                       | `legal_acts.read` (или каталог аудита)                       |
| `POST/PATCH/DELETE /api/legal-acts*`                                         | `legal_acts.edit` (`admin`, `lawyer`)                        |
| `GET /api/rules*`                                                            | `rules.read` (или каталог аудита)                            |
| `POST/PATCH/DELETE /api/rules*`                                              | `rules.edit` (`admin`, `lawyer`)                             |
| `GET /api/document-types`                                                    | Любой авторизованный пользователь                            |
| `GET /api/document-type-suggestions`                                         | `document_types.read` (`admin`, `lawyer`, `auditor`)         |
| `POST/PATCH/DELETE /api/document-types*`, `POST /api/document-type-suggestions/*` | `document_types.edit` (`admin`, `lawyer`)               |

---

## 3. Изменения схемы данных (миграция `0013_auth_rbac`)

1. **`users`** (расширение существующей таблицы через `batch_alter_table` для совместимости с SQLite):
   - обновить `CHECK`-ограничение роли: `role IN ('admin', 'lawyer', 'auditor', 'hr')`;
   - добавить поля: `full_name` (`String(255)`, default `""`), `is_active` (`Boolean`, default `True`),
     `updated_at` (`DateTime`), `last_login_at` (`DateTime`, nullable).
2. **`user_sessions`** (новая таблица):
   - `id`, `user_id` (`FK users.id ON DELETE CASCADE`, index), `token_hash` (`String(64)`, unique, index),
     `created_at`, `expires_at` (index), `revoked_at` (nullable), `ip_address` (`String(64)`, nullable),
     `user_agent` (`String(500)`, nullable).
3. **`audit_resolutions`** (новая таблица — резолюции аудитора):
   - `id`, `report_id` (`FK audit_reports.id ON DELETE CASCADE`, index),
     `author_id` (`FK users.id ON DELETE SET NULL`, nullable),
     `author_name` (`String(255)` — снимок имени/логина, чтобы история сохранялась даже при удалении),
     `decision` (`String(20)` — `approved` / `needs_revision` / `rejected`, `CHECK`-ограничение),
     `comment` (`Text`), `created_at` (`DateTime`).

---

## 4. Безопасность и эксплуатация вне доверенной среды

- **Защита `data/debug.log`:**
  - В `request_logging_middleware` (`api/app.py`) маскировать заголовки `Cookie`, `Set-Cookie`, `Authorization`
    (`"[REDACTED]"`).
  - Не логировать тела запросов/ответов для `/api/auth/*` и `/api/users*` (защита от утечки паролей).
  - Добавить настройку `EDM_TRACE_LOG_BODIES` (по умолчанию `false`): в обычном режиме в `debug.log` пишутся
    метод, путь, статус, время и `request_id`, без текстов загруженных документов.
- **Защита от CSRF и перебора паролей:**
  - Проверка заголовка `Origin` (если передан) для мутирующих запросов (`POST`, `PATCH`, `PUT`, `DELETE`)
    против списка `EDM_TRUSTED_ORIGINS` (или текущего `Host`).
  - Rate limiting на `POST /api/auth/login` (например, не более 10 неудачных попыток за 5 минут на пару
    `IP + username` → `429 too_many_requests`).
- **Защита файлов и документации API:**
  - `data/uploads/` не публикуется через Nginx и не имеет публичных маршрутов; загрузка и чтение идут только
    через авторизованные эндпоинты.
  - Флаг `EDM_EXPOSE_DOCS` (по умолчанию `true` в dev, `false` в prod) отключает `/docs`, `/redoc`,
    `/openapi.json` вне разработки.
- **Новые переменные окружения** (задокументировать в `backend/.env.example`):
  - `EDM_AUTH_COOKIE_NAME` (по умолчанию `edm_session`)
  - `EDM_AUTH_COOKIE_SECURE` (по умолчанию `false` для локального HTTP, `true` за HTTPS)
  - `EDM_AUTH_SESSION_TTL_HOURS` (по умолчанию `24`)
  - `EDM_TRUSTED_ORIGINS` (опционально, список через запятую)
  - `EDM_TRACE_LOG_BODIES` (по умолчанию `false`)
  - `EDM_EXPOSE_DOCS` (по умолчанию `true`)
  - `EDM_INITIAL_ADMIN_USERNAME`, `EDM_INITIAL_ADMIN_EMAIL`, `EDM_INITIAL_ADMIN_PASSWORD`

---

## 5. Поэтапный план реализации

Каждый этап завершается прогоном тестов и отдельным коммитом (с записью в [`DEVLOG.md`](DEVLOG.md)).

### Этап 1. Бэкенд: схема БД, пароли, сессии и CLI-сид
- [ ] Добавить `argon2-cffi` в `backend/pyproject.toml`.
- [ ] Обновить `UserRole` (`admin`, `lawyer`, `auditor`, `hr`), расширить `User`, добавить модели `UserSession`
  и `AuditResolution` в `backend/src/edm_auditor/database/models.py`.
- [ ] Написать миграцию Alembic `0013_auth_rbac.py` (с `batch_alter_table` для SQLite) и проверить `upgrade`/`downgrade`.
- [ ] Создать пакет `backend/src/edm_auditor/auth/`:
  - `passwords.py` — хэширование и проверка Argon2id, базовые требования к паролю (длина ≥ 8);
  - `permissions.py` — перечень `Permission`, таблица `ROLE_PERMISSIONS`, вспомогательные функции проверки;
  - `sessions.py` — создание, валидация, продление/отзыв одной и всех сессий пользователя;
  - `rate_limit.py` — ограничитель попыток входа;
  - `cli.py` — команда создания администратора и идемпотентный сид при старте из `EDM_INITIAL_ADMIN_*`.
- [ ] Расширить `ApiSettings` новыми параметрами конфигурации и обновить `backend/.env.example`.
- [ ] Написать юнит-тесты в `backend/tests/auth/` (`test_passwords.py`, `test_sessions.py`, `test_permissions.py`).

### Этап 2. Бэкенд: API аутентификации, управления пользователями и защита логов
- [ ] Добавить схемы Pydantic в `api/schemas.py` (`LoginRequest`, `AuthUserResponse`, `ChangePasswordRequest`,
  `UserCreate`, `UserUpdate`, `UserResponse`, `ResolutionCreate`, `ResolutionResponse`).
- [ ] Реализовать FastAPI-зависимости в `auth/dependencies.py`: `get_current_user`, `require_permission(...)`.
- [ ] Реализовать эндпоинты:
  - `POST /api/auth/login` (установка `HttpOnly` cookie + обновление `last_login_at`, rate limit);
  - `POST /api/auth/logout`, `POST /api/auth/logout-all`;
  - `GET /api/auth/me` (данные пользователя + его эффективный список `permissions`);
  - `POST /api/auth/change-password` (проверка текущего пароля, отзыв остальных сессий);
  - `GET /api/users`, `POST /api/users`, `PATCH /api/users/{user_id}` (смена роли, `is_active`, сброс пароля;
    запрет деактивировать/разжаловать последнего активного `admin`; автоматический отзыв сессий при блокировке
    или смене роли).
- [ ] Обновить `request_logging_middleware` (редакция `Cookie`/`Set-Cookie`/`Authorization`, скрытие тел
  `/api/auth/*` и `/api/users*`, флаг `EDM_TRACE_LOG_BODIES`) и добавить проверку `Origin` для CSRF-защиты.
- [ ] Написать API-тесты аутентификации, управления пользователями, rate limit и безопасности логов.

### Этап 3. Бэкенд: RBAC на всех эндпоинтах, изоляция документов и резолюции аудитора
- [ ] Подключить `require_permission(...)` ко всем эндпоинтам `/api/*` согласно таблице из раздела 2.2.
- [ ] Заполнять `Document.user_id = current_user.id` в `POST /api/documents/upload`.
- [ ] Внедрить helper `_ensure_document_access(document, user)` и фильтрацию списков `GET /api/documents` и
  `GET /api/reports` для роли `hr` (только свои документы; `user_id IS NULL` скрыты от `hr`, но видны
  `admin`/`lawyer`/`auditor`).
- [ ] Реализовать эндпоинты резолюций:
  - `GET /api/reports/{report_id}/resolutions`;
  - `POST /api/reports/{report_id}/resolutions` (`resolutions.write`);
  - добавить `latest_resolution` в `ReportResponse` (и при необходимости в `LatestReportSummary`).
- [ ] Адаптировать тестовые фикстуры в `backend/tests/api/` (авторизованный клиент по умолчанию) и добавить
  матричный интеграционный тест `backend/tests/api/test_auth_rbac.py`, проверяющий доступ анонима и всех
  4 ролей (`admin`, `lawyer`, `auditor`, `hr`) ко всем ключевым эндпоинтам и изоляцию чужих документов.

### Этап 4. Фронтенд: живая сессия, экран входа и меню пользователя
- [ ] Обновить типы API (`frontend/src/api/types.ts`) и клиент (`frontend/src/api/client.ts`): глобальный
  обработчик `401` (сброс сессии и кэша TanStack Query, перевод на `/login`).
- [ ] Расширить `frontend/src/auth/permissions.ts` и `session.ts` под новый список прав и поля пользователя
  (`id`, `username`, `fullName`, `email`, `role`, `permissions`).
- [ ] Переписать `AuthProvider.tsx`: запрос `GET /api/auth/me` при инициализации, состояния `loading` /
  `authenticated` / `unauthenticated`, методы `login`, `logout`, полная очистка `queryClient.clear()` при
  выходе.
- [ ] Реализовать страницу `/login` (`LoginPage.tsx`): форма входа, локализованные ошибки
  (`invalid_credentials`, `account_disabled`, `too_many_requests`), возврат на исходный путь после входа.
- [ ] Заполнить слот `data-slot="user-menu"` в `AppLayout.tsx`: отображение имени и роли, диалог смены пароля,
  кнопка «Выйти».
- [ ] Обновить и расширить тесты `frontend/src/auth/auth.test.tsx`, `frontend/src/api/client.test.ts` и
  `frontend/src/app/app.test.tsx`.

### Этап 5. Фронтенд: ролевые экраны, управление пользователями и резолюции
- [ ] Обновить `APP_ROUTES` и страницы НПА/правил/типов:
  - маршруты просмотра открываются по `legal_acts.read` / `rules.read` / `document_types.read` (роль `auditor`
    видит нормативную базу в режиме только чтения);
  - все кнопки создания/редактирования/переобработки/удаления обёрнуты в `<Can permission="...edit">`.
- [ ] Добавить страницу `/users` (`UsersPage.tsx`, право `users.manage`, пункт меню только для `admin`):
  - таблица пользователей (логин, имя, email, роль, статус, последний вход);
  - создание пользователя;
  - изменение роли (`admin`, `lawyer`, `auditor`, `hr`), блокировка/активация, сброс пароля.
- [ ] Добавить блок **«Резолюция аудитора»** на экран аудита (`AuditPage.tsx`):
  - лента резолюций с автором, датой, решением (`Согласовано` / `На доработку` / `Отклонено`) и комментарием;
  - форма добавления резолюции внутри `<Can permission="resolutions.write">`.
- [ ] Добавить все новые тексты в словарь `frontend/src/i18n/ru.ts` (без хардкода строк в компонентах).
- [ ] Написать тесты Vitest для `LoginPage`, `UsersPage`, блока резолюций и read-only режима `auditor`.

### Этап 6. Docker, документация и финальная проверка
- [ ] Обновить `docker-compose.yml`, `backend/.env.example`, `frontend/docker/nginx.conf` (проверка передачи
  `Cookie`/`Set-Cookie` и заголовков безопасности, настройки `EDM_INITIAL_ADMIN_*`).
- [ ] Отметить закрытые пункты FR-6.3 в [`DIPLOMA.md`](DIPLOMA.md), актуализировать [`DEVLOG.md`](DEVLOG.md),
  `backend/README.md`, `frontend/README.md` и `docs/docker.md`.
- [ ] Прогнать полный набор проверок:
  - `pytest backend/tests -q`
  - `npm --prefix frontend run test` и `npm --prefix frontend run build`
  - сквозная ручная проверка сценариев входа и работы под всеми 4 ролями (`admin`, `lawyer`, `auditor`, `hr`).

---

## 6. Критерии готовности (Definition of Done)

- [ ] Ни один бизнес-эндпоинт `/api/*` не работает без валидной серверной сессии (`401`).
- [ ] Все 4 роли (`admin`, `lawyer`, `auditor`, `hr`) проверяются на сервере и покрыты матричными тестами.
- [ ] `hr` не может прочитать, проаудировать, выгрузить или удалить чужие документы и документы с `user_id = NULL`.
- [ ] `lawyer` редактирует НПА, правила и типы документов, но получает `403` на `/api/users`.
- [ ] `auditor` читает НПА/правила и пишет резолюции, но получает `403` на изменение НПА/правил/типов и `/api/users`.
- [ ] В `data/debug.log` не попадают cookie, пароли и (при настройках по умолчанию) тексты документов.
- [ ] Все тесты бэкенда и фронтенда, а также сборка фронтенда проходят без ошибок.
