# Удаление упоминаний Copilot из истории коммитов

GitHub Copilot добавляет в тело коммита трейлер вида:

```
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

Этот гайд описывает, как удалить такие строки из **всей** истории — как до, так и после `push`.

---

## Инструменты

| Инструмент        | Когда использовать                       |
|-------------------|------------------------------------------|
| `git-filter-repo` | Любое количество коммитов, рекомендуется |
| `git rebase -i`   | 1–5 коммитов, только локально            |

---

## Шаг 0. Установка git-filter-repo

```bash
pip install git-filter-repo
```

Проверка:

```bash
git-filter-repo --version
```

---

## Шаг 1. Проверить, сколько коммитов затронуто

Из корня репозитория:

```bash
git log --format="%H" | while read h; do
  git show -s --format="%B" "$h" | grep -qi "copilot" && echo "$h"
done
```

Если вывод пустой — история уже чистая.

---

## Шаг 2. Удалить упоминания (локально)

> [!IMPORTANT]
> `git-filter-repo` переписывает историю — все SHA коммитов изменятся.
> Перед запуском убедитесь, что нет незафиксированных изменений (`git status`).

```bash
git-filter-repo --force --message-callback '
import re
msg = message.decode("utf-8")
msg = re.sub(r"\nCo-authored-by: Copilot [^\n]*", "", msg)
msg = msg.rstrip() + "\n"
return msg.encode("utf-8")
'
```

После выполнения `git-filter-repo` **автоматически удаляет remote `origin`** (защита от случайного push). Это нормально.

---

## Шаг 3. Публикация изменений

### 3a. Если ещё не пушили (только локальные коммиты)

Верните remote и запушьте как обычно:

```bash
git remote add origin git@github.com:ВАШ_ЛОГИН/ВАШ_РЕПО.git
git push origin main
```

### 3b. Если уже пушили (история на GitHub уже есть)

Необходим **force-push** — он перезапишет удалённую историю:

```bash
git remote add origin git@github.com:ВАШ_ЛОГИН/ВАШ_РЕПО.git
git push --force origin main
```

> [!WARNING]
> Force-push переписывает публичную историю. Если репозиторий **публичный** или
> над ним работают другие люди — предупредите команду заранее.

#### Что делать коллегам после force-push

Каждый, кто уже склонировал репозиторий, должен выполнить:

```bash
git fetch origin
git reset --hard origin/main
```

> [!CAUTION]
> `git reset --hard` удалит все локальные незафиксированные изменения.
> Сначала сохраните незавершённую работу через `git stash`.

---

## Шаг 4. Проверка результата

```bash
git log --format="%H %B" | grep -i "copilot"
```

Если команда ничего не вывела — история чистая.

---

## Альтернатива: git rebase -i (для 1–5 коммитов)

Если затронуто несколько последних коммитов и вы не хотите ставить
дополнительные инструменты:

```bash
# Открыть интерактивный rebase для последних N коммитов
git rebase -i HEAD~N
```

В открывшемся редакторе замените `pick` на `reword` напротив нужных коммитов.
Git откроет каждое сообщение для редактирования — удалите строку с `Co-authored-by: Copilot`
вручную и сохраните файл.

После rebase force-push (если уже пушили):

```bash
git push --force origin main
```

---

## Быстрая шпаргалка

```bash
# 1. Установить инструмент
pip install git-filter-repo

# 2. Переписать историю
git-filter-repo --force --message-callback '
import re
msg = message.decode("utf-8")
msg = re.sub(r"\nCo-authored-by: Copilot [^\n]*", "", msg)
return (msg.rstrip() + "\n").encode("utf-8")
'

# 3. Вернуть remote и запушить
git remote add origin git@github.com:ВАШ_ЛОГИН/ВАШ_РЕПО.git
git push --force origin main

# 4. Проверить
git log --format="%H %B" | grep -i "copilot"
```
