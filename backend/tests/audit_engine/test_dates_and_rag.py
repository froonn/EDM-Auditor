from edm_auditor.audit_engine import AuditEngine, RuleSpec, StatementSpec


def test_duration_and_frequency_and_day_of_month_constraints_compare_normalized_values() -> None:
    result = AuditEngine().audit(
        "Выплата один раз в месяц 8 числа следующего месяца. Испытательный срок 4 месяца.",
        [
            RuleSpec(
                rule_id=1,
                rule_code="pay-frequency",
                subject="Частота выплаты",
                constraint_text="Заработная плата выплачивается не реже двух раз в месяц.",
                constraint_json={
                    "kind": "frequency",
                    "operator": "gte",
                    "count": 2,
                    "period": "month",
                },
                severity="high",
            ),
            RuleSpec(
                rule_id=2,
                rule_code="pay-day",
                subject="Срок окончательного расчета",
                constraint_text="Не позднее 5 числа следующего месяца.",
                constraint_json={
                    "kind": "day_of_month",
                    "operator": "lte",
                    "day": 5,
                    "month_offset": 1,
                },
                severity="high",
            ),
            RuleSpec(
                rule_id=3,
                rule_code="probation-limit",
                subject="Probation limit",
                constraint_text="Испытательный срок не более 90 дней.",
                constraint_json={
                    "kind": "value",
                    "operator": "lte",
                    "value": 90,
                    "unit": "day",
                },
                severity="high",
            ),
        ],
    )

    assert [finding.rule_code for finding in result.findings] == [
        "pay-frequency",
        "pay-day",
        "probation-limit",
    ]
    assert result.findings[0].quote == "один раз в месяц"
    assert result.findings[1].quote == "8 числа следующего месяца"
    assert result.findings[2].quote == "4 месяца"


def test_provider_statements_support_qualifying_words_in_durations() -> None:
    text = "Работнику предоставляется отпуск 14 календарных дней."
    start = text.index("14 календарных дней")
    statements = (
        StatementSpec(
            subject="Продолжительность отпуска",
            statement_text=text,
            source_quote="14 календарных дней",
            start_char=start,
            end_char=start + len("14 календарных дней"),
            constraint_json={"kind": "value", "operator": "eq", "value": 14, "unit": "day"},
        ),
    )

    result = AuditEngine(statement_extractor=lambda _: statements).audit(
        text,
        [
            RuleSpec(
                rule_id=9,
                rule_code="annual-leave-minimum",
                subject="Minimum annual leave",
                constraint_text="Отпуск не менее 24 дней.",
                constraint_json={"kind": "value", "operator": "gte", "value": 24, "unit": "day"},
                severity="high",
            )
        ],
    )

    assert result.findings[0].quote == "14 календарных дней"


def test_duration_rule_checks_date_interval_when_duration_is_not_written() -> None:
    result = AuditEngine().audit(
        "Изменение действует с 01.03.2027. Уведомление направлено 25.02.2027.",
        [
            RuleSpec(
                rule_id=10,
                rule_code="notice-period",
                subject="Notice period",
                constraint_text="Уведомление не менее чем за 10 дней.",
                constraint_json={"kind": "value", "operator": "gte", "value": 10, "unit": "day"},
                severity="high",
            )
        ],
    )

    assert len(result.findings) == 1
    assert result.findings[0].quote == "01.03.2027. Уведомление направлено 25.02.2027"


def test_textual_rule_without_structure_produces_no_deterministic_finding() -> None:
    result = AuditEngine().audit(
        "Соглашение о работе.",
        [
            RuleSpec(
                rule_id=11,
                rule_code="textual-rule",
                subject="Режим рабочего времени",
                constraint_text="В соглашении указывается режим рабочего времени.",
                constraint_json=None,
                severity="medium",
            )
        ],
    )

    assert result.findings == ()
