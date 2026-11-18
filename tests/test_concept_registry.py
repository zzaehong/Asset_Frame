import importlib
import tomllib
from pathlib import Path

REGISTRY = tomllib.loads(Path("config/concepts.toml").read_text())


def test_concept_ids_are_unique() -> None:
    ids = [concept["id"] for concept in REGISTRY["concepts"]]
    assert len(ids) == len(set(ids))


def test_implemented_concepts_have_module_tests_and_card() -> None:
    implemented = [c for c in REGISTRY["concepts"] if c["status"] == "implemented"]

    assert implemented
    for concept in implemented:
        importlib.import_module(concept["module"])
        assert concept["tests"], concept["id"]
        assert all(Path(path).is_file() for path in concept["tests"]), concept["id"]
        assert Path(concept["card"]).is_file(), concept["id"]
