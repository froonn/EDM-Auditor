# План разработки: авторизация, групповая ролевая модель (Linux-style RBAC) и `super-admin` (FR-6.3)

Ветка `feature/auth-rbac`, ответвлена от `master`. Реализует требование **FR-6.3** из [`TASK.md`](TASK.md) и
раздела «Авторизация и роли (FR-6.3)» в [`DIPLOMA.md`](DIPLOMA.md).

---

## 1. Цель и зафиксированные архитектурные решения

Перевести `EDM-Auditor` из однопользовательского локального режима в многопользовательский режим с серверной
аутентификацией, **гибкой групповой моделью доступа (по принципу групп Linux)**, выделенным единственным
`super-admin`, изоляцией документов по владельцу, резолюциями аудиторов и защищённым логированием.

### 1.1. Способ аутентификации — серверные HttpOnly cookie-сессии

Выбраны **серверные сессии в БД с HttpOnly cookie** (а не stateless JWT) по следующим причинам:

1. **Мгновенный отзыв доступа:** при выходе, смене пароля, блокировке пользователя или передаче прав
   `super-admin` сессии инвалидируются сразу в БД.
2. **Защита от XSS:** cookie с флагами `HttpOnly; SameSite=Lax; Path=/` (и `Secure` при HTTPS через
   `EDM_AUTH_COOKIE_SECURE=true`) недоступна из JavaScript; в `localStorage` ничего не хранится.
3. **Совместимость с текущей архитектурой:** `frontend/src/api/client.ts` уже отправляет
   `credentials: "same-origin"`, а Nginx и Vite проксируют `/api` на одном origin — CORS для основного
   интерфейса не требуется.
4. **Защита хранилища сессий:** клиент получает случайный 256-битный токен (`secrets.token_urlsafe(32)`), а в
   таблице `user_sessions` хранится только его `SHA-256` хэш.

### 1.2. Хэширование паролей

- Алгоритм **Argon2id** (`argon2-cffi`, рекомендуемый OWASP стандарт для хранения паролей).
- Пароли никогда не возвращаются API и не попадают в логи.

### 1.3. Групповая модель доступа (Linux-style Group RBAC)

**Главный принцип: ВСЕ права в системе задаются исключительно для групп, а не напрямую для пользователей.**
У пользователя больше нет жёсткого поля `role` для расчёта прав — его итоговые (эффективные) права
вычисляются как **объединение (аддитивный `UNION`) прав всех групп, в которых он состоит**.

В системе предусмотрено три вида групп (`groups.kind`):

1. **Персональная группа пользователя (`kind = 'personal'`, аналог Linux User Private Group):**
    - Создаётся автоматически при создании пользователя с именем, совпадающим с его `username`, и привязкой
      `owner_user_id = user.id`.
    - По умолчанию имеет **пустой** набор прав (базовые права приходят из кастомных групп), но позволяет
      точечно выдать отдельному пользователю индивидуальные дополнительные права без создания новой общей
      группы (например, одному сотруднику разрешить `audit.run`).
    - В персональной группе состоит только её владелец; добавить туда других пользователей или удалить её
      вручную нельзя, пока существует пользователь.
    - Уникальность имён составная — `UNIQUE(kind, name)`, поэтому персональная группа пользователя `admin`
      и кастомная группа `admin` не конфликтуют друг с другом.

2. **Кастомные (общие) группы (`kind = 'custom'`):**
    - Пользователю можно назначить **несколько** кастомных групп одновременно — их права складываются
      (`permissions(user) = ⋃ permissions(g)` для всех групп `g` пользователя).
    - При инициализации БД создаются **4 стартовые кастомные группы**:
        - `employee` (Сотрудник) — загрузка и удаление своих документов, просмотр и экспорт отчётов и резолюций
          по своим документам (**без** запуска аудита по умолчанию);
        - `auditor` (Аудитор) — просмотр всех документов (включая старые `user_id IS NULL`), запуск аудита,
          экспорт отчётов, написание резолюций, просмотр НПА/правил/типов в режиме read-only;
        - `lawyer` (Юрист) — всё от `auditor` + редактирование нормативной базы (НПА, правила, типы документов
          и заявки типов);
        - `admin` (Администратор) — всё от `lawyer` + удаление любых документов и управление пользователями (создание
          пользователей, блокировка, сброс паролей, **назначение групп пользователям**).
    - Все 4 стартовые группы работают **как обычные кастомные группы**: их права можно свободно менять, можно
      создавать новые кастомные группы и удалять любые кастомные группы, **если в группе нет ни одного
      пользователя** (`members_count == 0`).

3. **Системная группа `super-admin` (`kind = 'system'`):**
    - В системе может существовать **ровно один** пользователь со статусом `super-admin` (гарантируется
      частичным уникальным индексом БД `WHERE is_super_admin = 1` в `users` + синхронным членством в
      системной группе `super-admin`).
    - `super-admin` всегда обладает **всеми правами системы** (права системной группы нельзя урезать или
      удалить — защита от lockout).
    - Только `super-admin` может:
        - **передать права `super-admin` другому активному пользователю** (атомарная операция в одной транзакции
          с подтверждением текущим паролем; при передаче предыдущий `super-admin` остаётся обычным пользователем
          со своими остальными группами, например `admin`);
        - **включать и отключать право `groups.manage`** у кастомных и персональных групп (в том числе
          делегировать группе `admin` право настраивать группы пользователей) и назначать пользователям группы,
          имеющие `groups.manage`.
    - Текущего `super-admin` нельзя заблокировать или удалить до передачи прав другому пользователю.

### 1.4. Создание первого `super-admin` и старые документы (`user_id IS NULL`)

- **Первый `super-admin`** создаётся идемпотентно через CLI (`python -m edm_auditor.auth.cli create-super-admin`)
  или при старте приложения из переменных окружения (`EDM_INITIAL_ADMIN_USERNAME`, `EDM_INITIAL_ADMIN_EMAIL`,
  `EDM_INITIAL_ADMIN_PASSWORD`), если в БД ещё нет `super-admin`. Ему автоматически создаётся персональная
  группа, статус `super-admin` и членство в кастомной группе `admin`.
- **Новых пользователей** создают пользователи с правом `users.manage` (`super-admin`, `admin`). Публичной
  саморегистрации нет. После создания `username` неизменяем (сохраняет консистентность персональной группы и
  истории), а физическое удаление пользователей не предусмотрено — используется деактивация (`is_active = False`) с
  мгновенным отзывом всех сессий.
- **Временные пароли (`must_change_password`):** при создании пользователя или сбросе его пароля админом
  выставляется `must_change_password = True`. До смены пароля сервер допускает только `/api/auth/me`,
  `/api/auth/change-password` и `/api/auth/logout` (на остальные маршруты — `403 password_change_required`),
  а интерфейс переводит пользователя на экран обязательной смены пароля.
- **Старые документы без владельца (`documents.user_id IS NULL`)** видны пользователям с правом
  `documents.read_all` (`super-admin`, `admin`, `lawyer`, `auditor`) и скрыты от пользователей без него (`employee`).
  При прямом обращении к чужому документу/отчёту возвращается **`404 not_found`** (защита от
  IDOR — не раскрывается сам факт существования чужого ID). Все новые загрузки записывают
  `documents.user_id = current_user.id`.

---

## 2. Каталог прав и стартовая матрица групп

Сервер всегда проверяет эффективные права пользователя (`user_permissions`). Названия кастомных групп в
проверках доступа не хардкодятся.

### 2.1. Перечень прав (`Permission`) и стартовые настройки групп

| Право (`Permission`)   | Описание                                                                  | `super-admin` *(фикс.)* | `admin` *(старт.)* | `lawyer` *(старт.)* | `auditor` *(старт.)* | `employee` *(старт.)* |
|------------------------|---------------------------------------------------------------------------|:-----------------------:|:------------------:|:-------------------:|:--------------------:|:---------------------:|
| `documents.upload`     | Загрузка новых документов                                                 |           ✓            |         ✓         |         ✓          |          ✓          |          ✓           |
| `documents.read_all`   | Доступ ко всем документам и отчётам (вкл. `user_id=NULL`); без — свои     |           ✓            |         ✓         |         ✓          |          ✓          |           —           |
| `documents.delete_own` | Удаление собственных документов                                           |           ✓            |         ✓         |         ✓          |          ✓          |          ✓           |
| `documents.delete_any` | Удаление любых документов                                                 |           ✓            |         ✓         |          —          |          —           |           —           |
| `audit.run`            | Классификация, настройка, предпросмотр, запуск аудита, линковка положений |           ✓            |         ✓         |         ✓          |          ✓          |           —           |
| `reports.read`         | Просмотр документов, отчётов аудита и резолюций                           |           ✓            |         ✓         |         ✓          |          ✓          |      ✓ *(свои)*      |
| `reports.export`       | Экспорт отчёта в HTML                                                     |           ✓            |         ✓         |         ✓          |          ✓          |      ✓ *(свои)*      |
| `resolutions.write`    | Написание резолюций аудитора по отчётам                                   |           ✓            |         ✓         |         ✓          |          ✓          |           —           |
| `legal_acts.read`      | Просмотр НПА, текста акта и диагностики извлечения                        |           ✓            |         ✓         |         ✓          |          ✓          |           —           |
| `legal_acts.edit`      | Загрузка, создание, правка, переобработка, удаление НПА                   |           ✓            |         ✓         |         ✓          |          —           |           —           |
| `rules.read`           | Просмотр правил и их применимости                                         |           ✓            |         ✓         |         ✓          |          ✓          |           —           |
| `rules.edit`           | Создание, редактирование, применимость, удаление правил                   |           ✓            |         ✓         |         ✓          |          —           |           —           |
| `document_types.read`  | Просмотр каталога типов и предложений новых типов                         |           ✓            |         ✓         |         ✓          |          ✓          |           —           |
| `document_types.edit`  | Создание/правка/деактивация типов, принятие/отклонение заявок             |           ✓            |         ✓         |         ✓          |          —           |           —           |
| `users.manage`         | Создание/правка/блокировка пользователей, сброс паролей, назначение групп |           ✓            |         ✓         |          —          |          —           |           —           |
| `groups.manage`        | Создание/удаление пустых кастомных групп и настройка прав групп           |           ✓            |    — *(делег.)*    |          —          |          —           |           —           |

> **Защита от эскалации привилегий (Privilege Ceiling):**
> - Изменять состав/права системной группы `super-admin` запрещено всем.
> - Включать/отключать право `groups.manage` у любой группы может **только `super-admin`**.
> - **Потолок прав:** любой пользователь без статуса `super-admin` может назначить пользователю группу или
>   изменить набор прав группы только в пределах подмножества собственных эффективных прав
>   (`group_perms ⊆ actor_perms`), а также не может деактивировать самого себя или снять с себя `users.manage`.
> - Не-суперадмин не может изменять, блокировать, сбрасывать пароль или отзывать сессии у `super-admin`.

### 2.2. Привязка эндпоинтов API к правам

| Группа / эндпоинт                                                                                                                                             | Требование доступа                                                                      |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| `GET /health`                                                                                                                                                 | Публичный (Docker healthcheck)                                                          |
| `POST /api/auth/login`, `POST /api/auth/logout`                                                                                                               | Публичный (rate-limited для `login`)                                                    |
| `GET /api/auth/me`, `POST /api/auth/logout-all`, `POST /api/auth/change-password`                                                                             | Любой активный авторизованный пользователь (работает и при `must_change_password=True`) |
| `POST /api/auth/transfer-super-admin`                                                                                                                         | Только текущий `super-admin` + подтверждение паролем                                    |
| `GET /api/auth/audit-log`                                                                                                                                     | `users.manage` или `groups.manage` (журнал событий безопасности)                        |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}`, `PUT /api/users/{id}/groups`, `POST /api/users/{id}/revoke-sessions`                            | `users.manage`                                                                          |
| `GET /api/groups`, `GET /api/permissions`                                                                                                                     | `groups.manage` или `users.manage` (для выбора групп в UI)                              |
| `POST /api/groups`, `PATCH /api/groups/{id}`, `PUT /api/groups/{id}/permissions`, `DELETE /api/groups/{id}`                                                   | `groups.manage` (`DELETE` — только для пустой `custom`-группы)                          |
| `GET /api/documents`, `GET /api/reports`                                                                                                                      | `reports.read` + фильтр по `user_id` без `documents.read_all`                           |
| `POST /api/documents/upload`                                                                                                                                  | `documents.upload` (ставит `user_id = current_user.id`)                                 |
| `GET /api/documents/{id}`, `.../statements`, `.../report`, `GET /api/reports/{id}`                                                                            | `reports.read` + проверка доступа к документу                                           |
| `GET /api/reports/{id}/export`                                                                                                                                | `reports.export` + проверка доступа к документу                                         |
| `DELETE /api/documents/{id}`                                                                                                                                  | `documents.delete_any` или (`documents.delete_own` и свой документ)                     |
| `POST .../classify`, `PATCH .../classification`, `POST .../statements/extract`, `PATCH .../statements/{sid}/link`, `POST .../audit/preview`, `POST .../audit` | `audit.run` + проверка доступа к документу                                              |
| `GET /api/reports/{id}/resolutions`                                                                                                                           | `reports.read` + проверка доступа к документу                                           |
| `POST /api/reports/{id}/resolutions`                                                                                                                          | `resolutions.write` + проверка доступа к документу                                      |
| `GET /api/legal-acts*`                                                                                                                                        | `legal_acts.read` или `audit.run` (для выбора актов при аудите)                         |
| `POST/PATCH/DELETE /api/legal-acts*`                                                                                                                          | `legal_acts.edit`                                                                       |
| `GET /api/rules*`                                                                                                                                             | `rules.read` или `audit.run` (для выбора правил при аудите)                             |
| `POST/PATCH/DELETE /api/rules*`                                                                                                                               | `rules.edit`                                                                            |
| `GET /api/document-types`                                                                                                                                     | Любой авторизованный пользователь (справочник названий типов)                           |
| `GET /api/document-type-suggestions`                                                                                                                          | `document_types.read`                                                                   |
| `POST/PATCH/DELETE /api/document-types*`, `POST /api/document-type-suggestions/*`                                                                             | `document_types.edit`                                                                   |

---

## 3. Изменения схемы данных (миграция `0013_auth_groups_rbac`)

1. **`users`** (обновление через `batch_alter_table` для совместимости с SQLite):
    - удалить устаревшую колонку `role` (при миграции существующих записей перенести `hr` → `employee`,
      `auditor` → `auditor`, `admin` → `admin`);
    - добавить поля: `full_name` (`String(255)`, default `""`), `is_active` (`Boolean`, default `True`),
      `is_super_admin` (`Boolean`, default `False`), `must_change_password` (`Boolean`, default `False`),
      `updated_at` (`DateTime`), `last_login_at` (`DateTime`, nullable);
    - создать частичный уникальный индекс `uq_users_single_super_admin` на `users(is_super_admin)` с условием
      `WHERE is_super_admin = 1` (инвариант БД: в системе максимум один `super-admin`).
2. **`groups`** (новая таблица):
    - `id`, `name` (`String(100)`), `kind` (`String(20)` — `CHECK kind IN ('system', 'custom', 'personal')`),
      `description` (`Text`, default `""`),
      `owner_user_id` (`FK users.id ON DELETE CASCADE`, nullable, unique — заполняется только для `personal`),
      `created_at` (`DateTime`), `updated_at` (`DateTime`);
    - ограничения: `UNIQUE(kind, name)` (исключает конфликт между кастомной группой `admin` и личной группой
      пользователя `admin`),
      `CHECK((kind = 'personal' AND owner_user_id IS NOT NULL) OR (kind <> 'personal' AND owner_user_id IS NULL))`.
3. **`group_permissions`** (новая таблица):
    - `group_id` (`FK groups.id ON DELETE CASCADE`, PK), `permission` (`String(64)`, PK).
4. **`user_groups`** (новая таблица many-to-many):
    - `user_id` (`FK users.id ON DELETE CASCADE`, PK), `group_id` (`FK groups.id ON DELETE CASCADE`, PK),
      `assigned_at` (`DateTime`).
5. **`user_sessions`** (новая таблица):
    - `id`, `user_id` (`FK users.id ON DELETE CASCADE`, index), `token_hash` (`String(64)`, unique, index),
      `created_at`, `expires_at` (index), `revoked_at` (nullable), `ip_address` (`String(64)`, nullable),
      `user_agent` (`String(500)`, nullable).
6. **`audit_resolutions`** (новая таблица — резолюции аудитора):
    - `id`, `report_id` (`FK audit_reports.id ON DELETE CASCADE`, index),
      `author_id` (`FK users.id ON DELETE SET NULL`, nullable),
      `author_name` (`String(255)` — снимок имени/логина),
      `decision` (`String(20)` — `CHECK decision IN ('approved', 'needs_revision', 'rejected')`),
      `comment` (`Text`), `created_at` (`DateTime`).
7. **`auth_audit_log`** (новая таблица — журнал событий безопасности):
    - `id`, `actor_user_id` (`FK users.id ON DELETE SET NULL`, nullable, index),
      `actor_username` (`String(100)`), `action` (`String(50)`, index — `login_success`, `login_failed`,
      `logout`, `password_changed`, `password_reset`, `user_created`, `user_updated`, `user_disabled`,
      `user_enabled`, `user_sessions_revoked`, `user_groups_updated`, `group_created`, `group_updated`,
      `group_permissions_updated`, `group_deleted`, `super_admin_transferred`),
      `target_type` (`String(30)`, nullable), `target_id` (`String(100)`, nullable),
      `details_json` (`Text`, default `"{}"`), `ip_address` (`String(64)`, nullable),
      `created_at` (`DateTime`, index).

---

## 4. Безопасность и эксплуатация вне доверенной среды

- **Защита `data/debug.log`:**
    - В `request_logging_middleware` (`api/app.py`) маскировать заголовки `Cookie`, `Set-Cookie`, `Authorization`
      (`"[REDACTED]"`).
    - Не логировать тела запросов/ответов для `/api/auth/*`, `/api/users*` и `/api/groups*`.
    - Добавить настройку `EDM_TRACE_LOG_BODIES` (по умолчанию `false`): в обычном режиме в `debug.log` пишутся
      только метод, путь, статус, время и `request_id`, без текстов загруженных документов.
- **Защита от CSRF и перебора паролей:**
    - Проверка заголовка `Origin` (если передан) для мутирующих запросов (`POST`, `PATCH`, `PUT`, `DELETE`)
      против `EDM_TRUSTED_ORIGINS` (или текущего `Host`).
    - Rate limiting на `POST /api/auth/login` (не более 10 неудачных попыток за 5 минут на пару `IP + username`
      → `429 too_many_requests`).
- **Защита файлов и документации API:**
    - `data/uploads/` не отдаётся статикой; доступ к данным документа — только через защищённые эндпоинты.
    - Флаг `EDM_EXPOSE_DOCS` (по умолчанию `true` в dev, `false` в prod) отключает `/docs`, `/redoc`,
      `/openapi.json` вне разработки.
- **Новые переменные окружения** (задокументировать в `backend/.env.example`):
    - `EDM_AUTH_COOKIE_NAME` (`edm_session`)
    - `EDM_AUTH_COOKIE_SECURE` (`false` локально / `true` за HTTPS)
    - `EDM_AUTH_SESSION_TTL_HOURS` (`24`)
    - `EDM_TRUSTED_ORIGINS` (опционально, список через запятую)
    - `EDM_TRACE_LOG_BODIES` (`false`)
    - `EDM_EXPOSE_DOCS` (`true`)
    - `EDM_INITIAL_ADMIN_USERNAME`, `EDM_INITIAL_ADMIN_EMAIL`, `EDM_INITIAL_ADMIN_PASSWORD`

---

## 5. Поэтапный план реализации

Каждый этап завершается прогоном тестов и отдельным коммитом (с записью в [`DEVLOG.md`](DEVLOG.md)).

### Этап 1. Бэкенд: схема БД, групповая модель, пароли, сессии и CLI-сид

- [x] Добавить `argon2-cffi` в `backend/pyproject.toml`.
- [x] Обновить `database/enums.py` (`GroupKind`, `ResolutionDecision`) и `database/models.py`: обновить `User`
  (включая `must_change_password`), добавить `Group`, `GroupPermission`, `UserGroup`, `UserSession`,
  `AuditResolution` и `AuthAuditLog`.
- [x] Написать миграцию Alembic `0013_auth_groups_rbac.py` (с `batch_alter_table`, частичным уникальным
  индексом `uq_users_single_super_admin`, таблицей `auth_audit_log`, сидом 4 стартовых кастомных групп
  `employee`, `auditor`, `lawyer`, `admin` и системной группы `super-admin`) и проверить `upgrade`/`downgrade`.
- [x] Создать пакет `backend/src/edm_auditor/auth/`:
    - `passwords.py` — Argon2id хэширование, проверка и валидация пароля (длина ≥ 8);
    - `permissions.py` — каталог 16 `Permission`, дефолтные пресеты стартовых групп, расчёт эффективных прав
      пользователя как `union` прав всех его групп (и полный набор для `super-admin`);
    - `service.py` — сервисные операции: создание пользователя (с автоматической персональной группой,
      неизменяемым `username` и `must_change_password = True`), создание/редактирование/удаление (только при
      `members_count == 0`) кастомных групп, настройка прав кастомных и персональных групп с проверкой потолка
      прав (`group_perms ⊆ actor_perms`), назначение групп пользователю, атомарная передача `super-admin`;
    - `audit_log.py` — запись структурированных событий безопасности в `auth_audit_log`;
    - `sessions.py` — создание, валидация, отзыв одной и всех сессий пользователя;
    - `rate_limit.py` — ограничитель попыток входа;
    - `cli.py` — команда создания первого `super-admin` и идемпотентный сид при старте из `EDM_INITIAL_ADMIN_*`.
- [x] Расширить `ApiSettings` новыми параметрами конфигурации и обновить `backend/.env.example`.
- [x] Написать юнит-тесты в `backend/tests/auth/` (`test_passwords.py`, `test_sessions.py`,
  `test_groups_and_permissions.py`, включая объединение прав нескольких групп, потолок прав против эскалации,
  запрет удаления непустой группы, передачу `super-admin` и невозможность создания второго `super-admin`).

### Этап 2. Бэкенд: API аутентификации, пользователей, групп и защита логов

- [ ] Добавить схемы Pydantic в `api/schemas.py` (`LoginRequest`, `AuthUserResponse`, `ChangePasswordRequest`,
  `TransferSuperAdminRequest`, `UserCreate`, `UserUpdate`, `UserGroupsUpdate`, `UserResponse`, `GroupCreate`,
  `GroupUpdate`, `GroupPermissionsUpdate`, `GroupResponse`, `PermissionInfoResponse`, `AuthAuditLogResponse`,
  `ResolutionCreate`, `ResolutionResponse`).
- [ ] Реализовать FastAPI-зависимости в `auth/dependencies.py`: `get_current_user` (с блокировкой
  `403 password_change_required`, если у пользователя `must_change_password=True`, кроме `/api/auth/me`,
  `/api/auth/change-password`, `/api/auth/logout`), `require_permission(...)`, `require_super_admin`.
- [ ] Реализовать эндпоинты:
    - `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/logout-all`, `GET /api/auth/me`
      (возвращает профиль, `is_super_admin`, `must_change_password`, список групп и итоговый массив `permissions`),
      `POST /api/auth/change-password` (снимает `must_change_password`), `POST /api/auth/transfer-super-admin`,
      `GET /api/auth/audit-log` (пагинация и фильтры по `action` / `actor`);
    - `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}`, `PUT /api/users/{id}/groups`,
      `POST /api/users/{id}/revoke-sessions` (`users.manage`; автосоздание персональной группы, запрет
      самоблокировки и блокировки/изменения `super-admin`, потолок прав при назначении групп, отзыв сессий при
      блокировке и `must_change_password=True` при сбросе пароля);
    - `GET /api/permissions` (каталог прав с описаниями для конструктора групп в UI);
    - `GET /api/groups?kind=custom|personal|system`, `POST /api/groups`, `PATCH /api/groups/{id}`,
      `PUT /api/groups/{id}/permissions`, `DELETE /api/groups/{id}` (`409 group_not_empty`, если есть участники;
      проверка потолка прав и `403` при попытке менять `groups.manage` без статуса `super-admin` или трогать
      группу `super-admin`).
- [ ] Писать события в `auth_audit_log` на всех критичных действиях (вход/неудачный вход, смена/сброс пароля,
  создание/блокировка пользователя, отзыв сессий, изменение групп и прав, передача `super-admin`).
- [ ] Обновить `request_logging_middleware` (редакция `Cookie`/`Set-Cookie`/`Authorization`, скрытие тел
  `/api/auth/*`, `/api/users*`, `/api/groups*`, флаг `EDM_TRACE_LOG_BODIES`) и добавить проверку `Origin`.
- [ ] Написать API-тесты аутентификации, `must_change_password`, управления пользователями, группами, потолка
  прав, делегирования `groups.manage`, отзыва сессий, передачи `super-admin`, журнала `auth_audit_log`, rate
  limit и безопасности логов.

### Этап 3. Бэкенд: RBAC на всех эндпоинтах, изоляция документов и резолюции аудитора

- [ ] Подключить `require_permission(...)` ко всем эндпоинтам `/api/*` согласно таблице из раздела 2.2.
- [ ] Заполнять `Document.user_id = current_user.id` в `POST /api/documents/upload`, добавить в
  `DocumentResponse` / `DocumentDetailResponse` поля `owner_id` и `owner_name`, а в `GET /api/documents` —
  фильтр `status` (в т.ч. `status=uploaded` для очереди «Ожидают аудита»).
- [ ] Внедрить helper `_ensure_document_access(document, user_perms)` (при отсутствии доступа — **`404 not_found`**
  для защиты от IDOR) и фильтрацию `GET /api/documents` и `GET /api/reports` для пользователей без
  `documents.read_all` (только свои документы; `user_id IS NULL` скрыты от `employee`).
- [ ] Реализовать эндпоинты резолюций:
    - `GET /api/reports/{report_id}/resolutions`;
    - `POST /api/reports/{report_id}/resolutions` (`resolutions.write`);
    - добавить `latest_resolution` в `ReportResponse` и `LatestReportSummary`.
- [ ] Адаптировать тестовые фикстуры в `backend/tests/api/` (авторизованный клиент по умолчанию) и добавить
  матричный тест `backend/tests/api/test_auth_rbac.py`, проверяющий анонима, `super-admin`, `admin`, `lawyer`,
  `auditor`, `employee` (включая `404` на чужие ID), пользователя в нескольких группах (`employee` + `auditor`)
  и пользователя с точечно выданным правом в его персональной группе.

### Этап 4. Фронтенд: живая сессия, экран входа, смена временного пароля и меню пользователя

- [ ] Обновить типы API (`frontend/src/api/types.ts`) и клиент (`frontend/src/api/client.ts`): глобальный
  обработчик `401` (сброс сессии и кэша TanStack Query, перевод на `/login`).
- [ ] Расширить `frontend/src/auth/permissions.ts` и `session.ts` под новый список из 16 прав и профиль
  пользователя (`id`, `username`, `fullName`, `email`, `isSuperAdmin`, `mustChangePassword`, `groups`,
  `permissions`).
- [ ] Переписать `AuthProvider.tsx`: запрос `GET /api/auth/me` через TanStack Query с
  `refetchOnWindowFocus: true` (изменившиеся права группы подтягиваются без ручного F5), состояния `loading` /
  `authenticated` / `unauthenticated`, методы `login`, `logout`, полная очистка `queryClient.clear()` при
  выходе.
- [ ] Реализовать страницу `/login` (`LoginPage.tsx`) и экран принудительной смены временного пароля
  (`ForceChangePasswordPage` при `mustChangePassword === true`): локализованные ошибки (`invalid_credentials`,
  `account_disabled`, `too_many_requests`, `password_change_required`), возврат на
  исходный путь после входа.
- [ ] Заполнить слот `data-slot="user-menu"` в `AppLayout.tsx`: имя, бейджи групп (и отметка `super-admin`),
  диалог смены пароля, кнопка «Выйти».
- [ ] Обновить и расширить тесты `frontend/src/auth/auth.test.tsx`, `frontend/src/api/client.test.ts` и
  `frontend/src/app/app.test.tsx`.

### Этап 5. Фронтенд: админ-панель пользователей и групп, журнал безопасности, ролевые экраны и резолюции

- [ ] Обновить `APP_ROUTES` и экраны документов/НПА/правил/типов:
    - маршруты просмотра открываются по `legal_acts.read` / `rules.read` / `document_types.read` (`auditor`
      видит нормативную базу в режиме только чтения);
    - кнопки создания/редактирования/переобработки/удаления обёрнуты в `<Can permission="...edit">`;
    - на `DocumentsPage`: для пользователей с `documents.read_all` — колонка **«Автор»** и быстрый фильтр **«Ожидают
      аудита»** (`status=uploaded`); для `employee` кнопка запуска/настройки аудита скрыта
      (`<Can permission="audit.run">`), а у загруженных документов без отчёта показывается понятная плашка
      «Загружен, ожидает проверки аудитором».
- [ ] Добавить раздел **«Пользователи»** (`/users`, право `users.manage`):
    - таблица пользователей (логин, имя, email, назначенные кастомные группы, статус, последний вход);
    - создание пользователя (сразу создаётся его персональная группа + выбор стартовых кастомных групп,
      временный пароль с `must_change_password = True`);
    - редактирование пользователя: multi-select назначение кастомных групп (с учётом потолка прав),
      блокировка/активация, сброс пароля, кнопка **«Завершить все сессии»**, просмотр итоговых эффективных прав;
    - для `super-admin` — действие **«Передать права супер-администратора»** с подтверждением текущим паролем;
    - вкладка/секция **«Журнал безопасности»** (`GET /api/auth/audit-log`) с фильтром по типу события.
- [ ] Добавить раздел **«Группы и права»** (`/groups`, право `groups.manage`):
    - **две раздельные вкладки:**
        1. **Кастомные группы** (`employee`, `auditor`, `lawyer`, `admin` и созданные вручную) — создание новой
           группы, матрица чекбоксов прав (переключатель `groups.manage` доступен только `super-admin`, остальные
           ограничены потолком прав), счётчик и список участников, удаление группы (только если участников `0`);
        2. **Личные группы пользователей** (именные группы по `username`) — поиск пользователя и точечная
           настройка индивидуальных дополнительных прав для конкретного пользователя.
- [ ] Добавить блок **«Резолюция аудитора»** на экран аудита (`AuditPage.tsx`):
    - лента резолюций с автором, датой, решением (`Согласовано` / `На доработку` / `Отклонено`) и комментарием;
    - форма добавления резолюции внутри `<Can permission="resolutions.write">`.
- [ ] Добавить все новые тексты в словарь `frontend/src/i18n/ru.ts`.
- [ ] Написать тесты Vitest для `LoginPage`, экрана обязательной смены пароля, `UsersPage` (включая отзыв
  сессий и журнал безопасности), `GroupsPage` (обе вкладки + удаление пустой/непустой группы), блока
  резолюций, read-only режима `auditor` и ограниченного режима `employee` (с колонкой «Автор» у проверяющих).

### Этап 6. Docker, документация и финальная проверка

- [ ] Обновить `docker-compose.yml`, `backend/.env.example`, `frontend/docker/nginx.conf` (проверка передачи
  `Cookie`/`Set-Cookie`, заголовки безопасности, `EDM_INITIAL_ADMIN_*`).
- [ ] Отметить закрытые пункты FR-6.3 в [`DIPLOMA.md`](DIPLOMA.md), актуализировать [`DEVLOG.md`](DEVLOG.md),
  `backend/README.md`, `frontend/README.md` и `docs/docker.md`.
- [ ] Прогнать полный набор проверок:
    - `pytest backend/tests -q`
    - `npm --prefix frontend run test` и `npm --prefix frontend run build`
    - сквозная ручная проверка: `super-admin` (делегирование `groups.manage` и передача `super-admin`), `admin`,
      `lawyer`, `auditor`, `employee`, `must_change_password`, отзыв сессий, журнал безопасности, пользователь в
      нескольких группах и настройка персональной группы.

---

## 6. Критерии готовности (Definition of Done)

- [ ] Ни один бизнес-эндпоинт `/api/*` не работает без валидной серверной сессии (`401`), а при
  `must_change_password=True` доступны только `/api/auth/me`, `/api/auth/change-password` и `/api/auth/logout`.
- [ ] Все права задаются исключительно через группы; эффективные права пользователя = объединение прав всех
  его групп (персональной + кастомных); соблюдается потолок прав (`group_perms ⊆ actor_perms`).
- [ ] В системе гарантированно ровно один `super-admin`; работает атомарная передача статуса другому активному
  пользователю с подтверждением пароля.
- [ ] Кастомные группы (`employee`, `auditor`, `lawyer`, `admin` и новые) свободно редактируются, а удаляются
  только при отсутствии участников (`409 group_not_empty`).
- [ ] Персональная группа создаётся автоматически для каждого пользователя (при неизменяемом `username`) и
  отображается в админ-панели отдельно от кастомных групп.
- [ ] `employee` по умолчанию загружает и смотрит/выгружает только свои документы и отчёты (с понятным статусом
  ожидания аудитора), без запуска аудита и с ответом `404` при обращении к чужим ID (включая `user_id IS NULL`).
- [ ] Ключевые события безопасности фиксируются в `auth_audit_log`; в `data/debug.log` не попадают cookie,
  пароли и (по умолчанию) тексты документов.
- [ ] Все тесты бэкенда и фронтенда, а также сборка фронтенда проходят без ошибок.
