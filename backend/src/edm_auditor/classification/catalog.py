"""Initial document type catalog; further types are added through the API.

The classification model chooses types by these names and descriptions.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DefaultDocumentType:
    code: str
    name: str
    description: str


DEFAULT_DOCUMENT_TYPES = (
    DefaultDocumentType(
        "employment_contract",
        "Трудовой договор",
        "Трудовой договор или контракт между нанимателем и работником.",
    ),
    DefaultDocumentType(
        "business_trip_order",
        "Приказ о командировке",
        "Приказ о направлении работника в служебную командировку.",
    ),
    DefaultDocumentType(
        "remote_work_agreement",
        "Соглашение о дистанционной работе",
        "Соглашение или условия выполнения работником дистанционной работы.",
    ),
    DefaultDocumentType(
        "payroll_order",
        "Приказ об оплате труда",
        "Приказ о выплате заработной платы и об оплате труда.",
    ),
    DefaultDocumentType(
        "vacation_order",
        "Приказ об отпуске",
        "Приказ о предоставлении работнику отпуска.",
    ),
)
