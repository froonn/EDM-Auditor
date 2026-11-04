"""Initial document type catalog; further types are added through the API."""

from dataclasses import dataclass

from .models import DocumentTypeProfile


@dataclass(frozen=True, slots=True)
class DefaultDocumentType:
    name: str
    description: str
    profile: DocumentTypeProfile


DEFAULT_DOCUMENT_TYPES = (
    DefaultDocumentType(
        "Трудовой договор",
        "Трудовой договор или контракт с работником.",
        DocumentTypeProfile(
            "employment_contract",
            title_terms=("трудовой договор", "трудового договора", "трудовой контракт", "employment"),
            body_terms=("наниматель", "испытательн", "трудовые обязанности", "должностной оклад"),
            structure_terms=("трудовой", "договор", "контракт"),
        ),
    ),
    DefaultDocumentType(
        "Приказ о командировке",
        "Приказ о направлении работника в служебную командировку.",
        DocumentTypeProfile(
            "business_trip_order",
            title_terms=("командировк", "business_trip"),
            body_terms=("направляется в командировку", "служебн", "отчет о командировке", "командировочн"),
            structure_terms=("приказ",),
        ),
    ),
    DefaultDocumentType(
        "Соглашение о дистанционной работе",
        "Соглашение или условия выполнения дистанционной работы.",
        DocumentTypeProfile(
            "remote_work_agreement",
            title_terms=("дистанционн", "удаленн", "remote_work"),
            body_terms=("дистанционн", "удаленн", "интернет", "уведомлени"),
            structure_terms=("соглашение", "договор"),
        ),
    ),
    DefaultDocumentType(
        "Приказ об оплате труда",
        "Приказ о выплате заработной платы и об оплате труда.",
        DocumentTypeProfile(
            "payroll_order",
            title_terms=("заработной плат", "заработная плата", "оплате труда", "оплата труда", "payroll"),
            body_terms=("заработн", "авансов", "окончательный расчет", "начисленн"),
            structure_terms=("приказ",),
        ),
    ),
    DefaultDocumentType(
        "Приказ об отпуске",
        "Приказ о предоставлении работнику отпуска.",
        DocumentTypeProfile(
            "vacation_order",
            title_terms=("об отпуске", "о предоставлении отпуска", "предоставлении отпуска", "vacation"),
            body_terms=("отпуск", "календарных дней"),
            structure_terms=("приказ",),
        ),
    ),
)
