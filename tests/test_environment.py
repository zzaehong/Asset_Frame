from asset_frame.ingestion.environment import ENVIRONMENT_REQUIREMENTS


def test_environment_requirements_report_groups_without_values(monkeypatch) -> None:
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    naver = next(item for item in ENVIRONMENT_REQUIREMENTS if "NAVER_CLIENT_ID" in item.names)

    assert not naver.configured()
    assert naver.phase == "planned"
    assert not any(hasattr(item, "value") for item in ENVIRONMENT_REQUIREMENTS)
