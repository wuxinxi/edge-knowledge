from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    path: str
    fingerprint: str
    document_id: str
