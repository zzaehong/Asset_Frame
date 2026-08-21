from __future__ import annotations

from types import TracebackType

from asset_frame.storage.repository import IngestionRepository


class IngestionRunSession:
    def __init__(self, repository: IngestionRepository, *, source_id: str, data_kind: str) -> None:
        self._repository = repository
        self.id = repository.start_ingestion_run(source_id=source_id, data_kind=data_kind)
        self._finished = False

    def succeed(
        self,
        *,
        records_received: int,
        records_accepted: int,
        records_quarantined: int = 0,
    ) -> None:
        if min(records_received, records_accepted, records_quarantined) < 0:
            raise ValueError("ingestion record counts must be non-negative")
        if records_accepted + records_quarantined > records_received:
            raise ValueError("accepted and quarantined records cannot exceed received records")
        self._repository.complete_ingestion_run(
            self.id,
            records_received=records_received,
            records_accepted=records_accepted,
            records_quarantined=records_quarantined,
        )
        self._finished = True

    def __enter__(self) -> IngestionRunSession:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exception is not None and not self._finished:
            self._repository.fail_ingestion_run(
                self.id,
                error_code=type(exception).__name__,
                error_message=str(exception) or type(exception).__name__,
            )
        elif exception is None and not self._finished:
            self._repository.fail_ingestion_run(
                self.id,
                error_code="IncompleteIngestionRun",
                error_message="ingestion run exited without success counts",
            )
            raise RuntimeError("ingestion run exited without success counts")
        return False
