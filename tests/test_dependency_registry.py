import tomllib
from pathlib import Path


def test_direct_dependencies_are_registered() -> None:
    with Path("pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    with Path("docs/dependency-sources.toml").open("rb") as registry_file:
        registry = tomllib.load(registry_file)

    registered = {item["distribution"] for item in registry["dependencies"]}
    declared = {
        requirement.split("[")[0].split(">=")[0]
        for requirement in project["project"]["dependencies"]
    }
    declared.update(
        requirement.split(">=")[0] for requirement in project["dependency-groups"]["dev"]
    )
    assert declared <= registered
    url_fields = {"official_docs", "changelog", "source_repository"}
    assert all(
        url.startswith("https://")
        for item in registry["dependencies"]
        for key, url in item.items()
        if key in url_fields
    )
