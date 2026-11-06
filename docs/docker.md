# Запуск через Docker Compose

Так система запускается на защите: одна команда поднимает бэкенд и интерфейс. Для разработки удобнее запуск
без Docker, он описан в [`backend/README.md`](../backend/README.md) и [`frontend/README.md`](../frontend/README.md).

## Состав

| Сервис     | Образ                                           | Что делает                                                 |
|------------|-------------------------------------------------|------------------------------------------------------------|
| `backend`  | [`backend/Dockerfile`](../backend/Dockerfile)   | Применяет миграции и запускает API. Порт наружу не открыт  |
| `frontend` | [`frontend/Dockerfile`](../frontend/Dockerfile) | Nginx отдаёт собранный интерфейс и передаёт `/api` бэкенду |

Данные бэкенда (база, поисковый индекс, загруженные файлы и журнал `debug.log`) лежат в томе `edm-data` и
сохраняются между перезапусками. Сервер в контейнере работает не от root.

## Запуск

Нужны Docker и Docker Compose v2. Файл `backend/.env` с пресетом модели и ключом API обязателен, как и при
разработке: `cp backend/.env.example backend/.env` и заполнить его. В образ он не попадает, Compose передаёт
переменные при запуске.

```bash
docker compose up --build -d
```

Интерфейс открывается на <http://localhost:8080>, документация API на <http://localhost:8080/docs>. Другой
порт задаётся переменной: `EDM_PORT=9000 docker compose up --build -d`.

| Команда                          | Что делает                                       |
|----------------------------------|--------------------------------------------------|
| `docker compose ps`              | Состояние сервисов; бэкенд должен быть `healthy` |
| `docker compose logs -f backend` | Журнал бэкенда                                   |
| `docker compose down`            | Остановить; данные сохраняются                   |
| `docker compose down -v`         | Остановить и **удалить все данные**              |
| `docker compose up --build -d`   | Пересобрать после изменения кода                 |

Загрузка НПА и аудит ждут модель, поэтому nginx ждёт ответа бэкенда до 15 минут. Размер загружаемого файла
ограничен 25 МиБ в nginx и 20 МиБ в API.

## Перенос рабочей базы

На защите удобно показывать уже загруженные НПА. Новый том пустой, но в него можно скопировать базу, индекс и
файлы из `backend/data/`. Перед этим остановите сервер разработки, чтобы файл базы не менялся во время
копирования.

```bash
docker compose up -d
docker compose stop backend
docker compose cp backend/data/edm_auditor.sqlite3 backend:/app/data/
docker compose cp backend/data/rag-index.sqlite3 backend:/app/data/
docker compose cp backend/data/uploads/. backend:/app/data/uploads/
docker compose run --rm --no-deps -u root backend chown -R edm:edm /app/data
docker compose run --rm --no-deps backend sh -c 'alembic current 2>/dev/null | grep -q . || alembic stamp head'
docker compose start backend
```

`chown` возвращает файлы пользователю сервера: `docker compose cp` записывает их от root. Предпоследняя команда
нужна для базы, созданной сервером разработки без Alembic: в ней нет таблицы `alembic_version`, и миграции
попытались бы создать таблицы заново. Команда помечает такую базу последней версией. Это верно, только если
сервер разработки с этой базой запускался на текущем коде: иначе он сообщил бы об устаревшей схеме. Файлы в
`backend/data/` при переносе не меняются.

## Ограничения

- **Только пресет `google-ai-studio`.** Пресеты `lm-studio` и `openrouter` обращаются к локальному серверу
  моделей `localhost:1234`: у `openrouter` так получаются эмбеддинги. Внутри контейнера `localhost` означает
  сам контейнер. Чтобы обращаться к серверу на компьютере, нужны свой файл моделей с адресом
  `http://host.docker.internal:1234/v1`, подключённый в контейнер и указанный в `EDM_MODEL_CONFIG`, и строка
  `extra_hosts: ["host.docker.internal:host-gateway"]` у сервиса `backend`. Такой запуск не проверялся.
- **Без авторизации.** API и интерфейс открыты всем, кто видит порт. Запускайте только на своём компьютере или
  в доверенной сети. Авторизация перенесена в диплом, см. [`DIPLOMA.md`](DIPLOMA.md).
- **Один процесс сервера.** SQLite допускает одну запись за раз, поэтому `uvicorn` работает с одним
  процессом.
