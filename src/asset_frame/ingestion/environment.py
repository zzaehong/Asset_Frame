from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnvironmentRequirement:
    names: tuple[str, ...]
    capability: str
    phase: str
    secret: bool

    def configured(self) -> bool:
        return all(bool(os.getenv(name, "").strip()) for name in self.names)


ENVIRONMENT_REQUIREMENTS = (
    EnvironmentRequirement(
        ("DATABASE_URL",), "PostgreSQL persistence and job execution", "current", True
    ),
    EnvironmentRequirement(
        ("KRX_API_KEY",), "KRX assets and Korean market prices", "current", True
    ),
    EnvironmentRequirement(
        ("TIINGO_API_KEY",), "Tiingo US prices and corporate actions", "current", True
    ),
    EnvironmentRequirement(("SEC_USER_AGENT",), "SEC identifiers and filings", "current", False),
    EnvironmentRequirement(
        ("OPENDART_API_KEY",), "OpenDART identifiers and disclosures", "current", True
    ),
    EnvironmentRequirement(("FRED_API_KEY",), "FRED US macro series", "planned", True),
    EnvironmentRequirement(("ECOS_API_KEY",), "ECOS Korean macro series", "planned", True),
    EnvironmentRequirement(
        ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
        "Naver recent Korean news metadata",
        "planned",
        True,
    ),
)
