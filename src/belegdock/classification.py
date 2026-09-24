from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Final, Literal
import unicodedata


DocumentType = Literal["invoice", "credit_note", "receipt", "unknown"]
Recommendation = Literal["likely", "unclear", "unlikely"]

DOCUMENT_TYPE_INVOICE: Final[DocumentType] = "invoice"
DOCUMENT_TYPE_CREDIT_NOTE: Final[DocumentType] = "credit_note"
DOCUMENT_TYPE_RECEIPT: Final[DocumentType] = "receipt"
DOCUMENT_TYPE_UNKNOWN: Final[DocumentType] = "unknown"
RECOMMENDATION_LIKELY: Final[Recommendation] = "likely"
RECOMMENDATION_UNCLEAR: Final[Recommendation] = "unclear"
RECOMMENDATION_UNLIKELY: Final[Recommendation] = "unlikely"

_DOCUMENT_TOKENS: Final[dict[DocumentType, tuple[str, ...]]] = {
    DOCUMENT_TYPE_INVOICE: (
        "rechnung",
        "rechnungen",
        "rechnungsnummer",
        "invoice",
        "invoices",
        "invoice number",
    ),
    DOCUMENT_TYPE_CREDIT_NOTE: (
        "gutschrift",
        "gutschriften",
        "stornorechnung",
        "credit note",
        "credit notes",
        "credit memo",
    ),
    DOCUMENT_TYPE_RECEIPT: (
        "beleg",
        "belege",
        "quittung",
        "kassenbon",
        "receipt",
        "receipts",
    ),
}
_SENDER_TOKENS: Final[dict[DocumentType, tuple[str, ...]]] = {
    DOCUMENT_TYPE_INVOICE: (
        "billing",
        "invoice",
        "accounts payable",
        "accounting",
        "buchhaltung",
    ),
    DOCUMENT_TYPE_CREDIT_NOTE: ("credit memo", "gutschrift", "storno"),
    DOCUMENT_TYPE_RECEIPT: ("receipt", "kassenbon", "quittung", "point of sale"),
}
_NON_DOCUMENT_TOKENS: Final = (
    "advertisement",
    "agb",
    "datenschutz",
    "impressum",
    "marketing",
    "newsletter",
    "nutzungsbedingungen",
    "privacy",
    "terms and conditions",
    "unsubscribe",
    "werbung",
)
_TYPE_PHRASES: Final[dict[DocumentType, str]] = {
    DOCUMENT_TYPE_INVOICE: "eine Rechnung",
    DOCUMENT_TYPE_CREDIT_NOTE: "eine Gutschrift",
    DOCUMENT_TYPE_RECEIPT: "einen Beleg",
}
_MAX_HEADER_LENGTH = 4096


@dataclass(frozen=True)
class CandidateClassification:
    document_type: DocumentType
    recommendation: Recommendation
    signals: tuple[str, ...]

    def as_dict(self) -> dict[str, str | list[str]]:
        return {
            "documentType": self.document_type,
            "recommendation": self.recommendation,
            "signals": list(self.signals),
        }


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value[:_MAX_HEADER_LENGTH]).casefold()
    words = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE).strip()
    return f" {words} "


def _matching_types(
    value: str, tokens: Mapping[DocumentType, tuple[str, ...]]
) -> tuple[DocumentType, ...]:
    normalized = _normalize(value)
    return tuple(
        document_type
        for document_type, phrases in tokens.items()
        if any(f" {_normalize(phrase).strip()} " in normalized for phrase in phrases)
    )


def _positive_signal(source: str, document_type: DocumentType) -> str:
    return f"{source} enthält einen Hinweis auf {_TYPE_PHRASES[document_type]}."


def _has_non_document_signal(*values: str) -> bool:
    return any(
        any(
            f" {_normalize(phrase).strip()} " in _normalize(value)
            for phrase in _NON_DOCUMENT_TOKENS
        )
        for value in values
    )


def classify_candidate(
    candidate: str | Mapping[str, Any],
    *,
    subject: str = "",
    sender: str = "",
) -> CandidateClassification:
    filename = candidate if isinstance(candidate, str) else candidate.get("filename", "")
    if not isinstance(filename, str):
        filename = ""
    filename_types = _matching_types(filename, _DOCUMENT_TOKENS)
    subject_types = _matching_types(subject, _DOCUMENT_TOKENS)
    sender_types = _matching_types(sender, _SENDER_TOKENS)
    positive_types = tuple(
        document_type
        for document_type in _DOCUMENT_TOKENS
        if document_type in (*filename_types, *subject_types, *sender_types)
    )
    signals: list[str] = []
    for document_type in filename_types:
        signals.append(_positive_signal("Dateiname", document_type))
    for document_type in subject_types:
        signals.append(_positive_signal("Betreff", document_type))
    for document_type in sender_types:
        signals.append(_positive_signal("Absender", document_type))

    non_document = _has_non_document_signal(filename, subject, sender)
    if non_document:
        signals.append("Hinweis auf Inhalte, die üblicherweise kein Beleg sind.")

    if len(positive_types) > 1 or (positive_types and non_document):
        return CandidateClassification(DOCUMENT_TYPE_UNKNOWN, RECOMMENDATION_UNCLEAR, tuple(signals))
    if len(positive_types) == 1:
        document_type = positive_types[0]
        strong_signal = document_type in filename_types or document_type in subject_types
        recommendation = RECOMMENDATION_LIKELY if strong_signal else RECOMMENDATION_UNCLEAR
        return CandidateClassification(document_type, recommendation, tuple(signals))
    if non_document:
        return CandidateClassification(DOCUMENT_TYPE_UNKNOWN, RECOMMENDATION_UNLIKELY, tuple(signals))
    return CandidateClassification(DOCUMENT_TYPE_UNKNOWN, RECOMMENDATION_UNCLEAR, ())


def lookup_candidate_classification(
    provider: Any, candidate: Mapping[str, Any]
) -> CandidateClassification:
    provider_type = type(provider)
    if not callable(getattr(provider_type, "candidate_classification", None)):
        return classify_candidate(candidate)
    try:
        candidate_id = candidate.get("id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("Gmail candidate identity is invalid")
        result = provider.candidate_classification(candidate_id)
    except Exception:
        return classify_candidate(candidate)
    if not isinstance(result, CandidateClassification):
        return classify_candidate(candidate)
    return result


def classify_candidate_mapping(
    provider: Any, candidate: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "message_id": candidate["message_id"],
        "part_id": candidate["part_id"],
        "filename": candidate["filename"],
        "size": candidate["size"],
        **lookup_candidate_classification(provider, candidate).as_dict(),
    }
