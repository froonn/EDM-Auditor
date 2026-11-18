# Переработка тестов бэкенда

Ветка `feature/tests-rework`, ответвлена от `feature/rules-audit-rework`. После завершения вливается
обратно в `feature/rules-audit-rework`.

## 1. Зачем

После переработки аудита (этапы 0–6 в [`feature-rules-audit-rework.md`](feature-rules-audit-rework.md))
тесты отстают от реализации:

- [`conftest.py`](../backend/tests/conftest.py) для всех тестов включает прежний режим сравнения по
  сущностям (`EDM_AUDIT_MATCHING=off`). Основной путь аудита (`RuleMatcher`, положения документа) покрыт
  только `test_matching.py`, `test_stage3_statements.py` и парой API-тестов.
- Регрессионный тест [`test_multi_legal_act_regression.py`](../backend/tests/api/test_multi_legal_act_regression.py)
  и один тест в [`test_engine.py`](../backend/tests/audit_engine/test_engine.py) читают файлы из
  `backend/examples/`. Записанные ответы модели
  ([`recorded_gemini_audit.json`](../backend/tests/fixtures/recorded_gemini_audit.json)) описывают старый
  формат: правила `check_type`, сущности, вердикты по парам.
- Прежний путь (`entity_extractor` в `AuditEngine`, ветка `matching.enabled = false` в
  `model_config.py` и `api/app.py`) нужен только этим тестам.

Цель: тесты проверяют текущую реализацию, не зависят от `backend/examples/` и от устаревшего кода, а
после ветки устаревший код можно удалить.

## 2. Принципы

- Тесты работают без сети и ключей, на дублёрах из `backend/tests/fakes.py`.
- Исходные тексты берутся из `backend/evaluation/corpus/` (акты и документы с разметкой `labels.toml`).
- Записанные ответы модели обновляются под текущие контракты: правило со `subject`, `constraint_text`,
  `constraint_json`, `condition`; положения документа; ответы сопоставления.
- Число тестов не должно уменьшиться без причины: удалять можно только тесты, которые проверяют
  исключительно прежний режим.
- Каждый этап заканчивается зелёным `pytest backend/tests -q -p no:cacheprovider`.

## 3. Этапы

### Этап 0. Инвентаризация

- [x] Включить `EDM_AUDIT_MATCHING=on` для всех тестов локально и составить список упавших, отдельно
  отметить тесты, которые зависают.
- [x] Разбить тесты на три группы: проверяют только прежний режим, проверяют поведение, не зависящее от
  режима, проверяют новый режим.
- [x] Записать список в этот файл.

**Результат.** Тесты запускались по файлам, с ограничением 120 с на файл. Ни один файл не превысил
ограничение (самый долгий `test_evaluation.py`, 31 с). Причина зависания при пробном прогоне всего набора
не установлена: при запуске по файлам оно не воспроизвелось.

Из 31 файла упали только три, все по одной причине: `FakeLLMProvider` и дублёры в тестах знают только
запрос пояснений (`findings`), а в новом режиме первым идёт запрос сопоставления (`rules`, схема
`MATCHING_RESPONSE_SCHEMA`), и аудит завершается ошибкой `LLM matching failed` (`503`).

| Файл | Упало | Всего | Причина |
|------|-------|-------|---------|
| `api/test_api.py` | 18 | 93 | аудит через API, фейковая модель не отвечает на сопоставление |
| `api/test_multi_legal_act_regression.py` | 9 | 9 | то же; плюс записанные ответы старого формата |
| `evaluation/test_evaluation.py` | 1 | 8 | `test_runner_records_rules_findings_and_requests`: аудит завершается ошибкой |

Остальные 28 файлов проходят и в новом режиме без изменений (`test_engine.py` 24, `test_matching.py` 26,
`test_dates_and_rag.py` 4, `test_stage2_rule_contract.py` 4, `test_stage3_statements.py` 6 и др.).

Группы:

- **Проверяют новый режим:** `test_matching.py`, `test_stage3_statements.py`, `test_stage2_rule_contract.py`,
  `test_manual_statement_link_updates_report_pairs_and_findings`.
- **Не зависят от режима, но запускают аудит через API** (нужны ответы сопоставления у фейка): остальные
  17 упавших тестов `test_api.py` (отчёт, выгрузка, удаление, снимок выбора, лимиты и таймауты модели),
  `test_runner_records_rules_findings_and_requests`.
- **Привязаны к прежнему режиму и записанным ответам:** все 9 тестов `test_multi_legal_act_regression.py`
  (сущности и вердикты пар в `recorded_gemini_audit.json`), а также тест
  `test_audit_fails_without_report_when_model_is_unavailable[create_llm_provider-...]`: он ожидает сообщение
  `LLM analysis failed`, а в новом режиме модель падает на сопоставлении (`LLM matching failed`).
- Файлы, не зависящие от аудита (парсер, классификация, база, RAG, экспорт, структура НПА, провайдеры,
  конфигурация): без изменений.

Вывод для этапа 1: достаточно научить фейковую модель отвечать на запрос сопоставления, остальное в
`test_api.py` заработает без переписывания.


### Этап 1. Фейки нового режима

- [ ] Добавить в `backend/tests/fakes.py` дублёры: извлечение положений документа и ответ сопоставления
  правил с положениями (по заданной таблице «положение → правило → вердикт»).
- [ ] Сделать фабрику тестового приложения, где эти дублёры подключены вместо реальных провайдеров, и
  использовать её вместо ручной подмены в отдельных тестах.
- [ ] Выяснить и устранить причину зависания полного набора при включённом сопоставлении.

### Этап 2. Регрессионный тест на корпусе

- [ ] Переписать `test_multi_legal_act_regression.py` на файлы `backend/evaluation/corpus/`: акты `payments`,
  `remote`, `trip`, `vacation` и документы `*_violating`, `*_compliant`, `payroll_paraphrase`, `remote_child`.
- [ ] Заменить `recorded_gemini_audit.json` записанными ответами текущего формата: правила, положения и
  ответы сопоставления. Записать их с одного прогона `python -m edm_auditor.evaluation run`, сохранив лог
  запросов, либо составить вручную по `labels.toml` с пометкой, что это не запись модели.
- [ ] Сохранить проверенные свойства: нарушения только своего документа, применение только своего акта,
  режим `all` показывает больше ложных находок, соответствующие документы без нарушений, ссылка на норму
  в пояснении, день месяца и частота выплат.
- [ ] Заменить файл `remote_work_agreement.txt` в `test_engine.py` документом из корпуса.

### Этап 3. Перевод остальных тестов

- [ ] Убрать `EDM_AUDIT_MATCHING=off` из `conftest.py`.
- [ ] Перевести тесты `test_api.py`, `test_engine.py`, `test_dates_and_rag.py`,
  `test_stage2_rule_contract.py`, `test_stage3_statements.py`, `evaluation/test_evaluation.py` на новый
  режим: вместо `entity_extractor` и `no_entities` использовать дублёры положений из этапа 1.
- [ ] Тесты, проверявшие только сравнение сущностей, удалить или заменить аналогами для
  `compare_structured` и `RuleMatcher`; перечень записать в журнал.

### Этап 4. Удаление устаревшего кода

- [ ] Удалить из `AuditEngine` параметр `entity_extractor` и из `AuditPersistence` ветку прежнего режима.
- [ ] Удалить переключатель `EDM_AUDIT_MATCHING` и поле `enabled` из `[audit_matching]` в `model_config.py`
  и `models.toml`; обновить `test_model_config.py`.
- [ ] Удалить `backend/examples/`, если на него не осталось ссылок, либо оставить только файлы, на которые
  ссылаются `README.md` и `docs/DEBUG.md`, и заменить остальные ссылки файлами из корпуса.
- [ ] Обновить `README.md`, `backend/README.md`, `docs/DEBUG.md`, `docs/model-configuration.md`,
  `backend/examples/README.md` (если остаётся), `docs/TODO.md`.

### Этап 5. Проверка и слияние

- [ ] Прогнать `pytest backend/tests -q -p no:cacheprovider`, `npm --prefix frontend test -- --run`,
  `npm --prefix frontend run build`.
- [ ] Проверить, что `python -m edm_auditor.evaluation run` по-прежнему запускается (без реальной модели
  достаточно запуска `tests/evaluation`).
- [ ] Записать итоги в `docs/DEVLOG.md`, слить ветку в `feature/rules-audit-rework`.

## 4. Риски

- Без прежнего режима эталонное поведение теряется: после удаления тесты проверяют только новый путь, и
  регрессии в логике сопоставления ловит лишь замер на реальной модели.
- Записанные ответы нового формата можно получить только реальным прогоном: он требует сети и квоты
  Gemini. Если квоты нет, ответы составляются вручную и не считаются записью модели.
- Удаление `backend/examples/` затрагивает демонстрационный сценарий на защите: заменить его надо до
  удаления.
