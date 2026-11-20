import ast
import pathlib
import unittest

from app.domain.schema_revision import (
    EXPECTED_SCHEMA_REVISION,
    KNOWN_SCHEMA_REVISIONS,
    SchemaReading,
    SchemaState,
    compare_schema,
)

VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"


def migration_chain() -> list[str]:
    """The revisions in backend/migrations/versions/, base first, read from
    each file's `revision` / `down_revision` without importing Alembic."""
    parents: dict[str, str | None] = {}
    for path in VERSIONS.glob("*.py"):
        values = {}
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ("revision", "down_revision"):
                    values[node.targets[0].id] = ast.literal_eval(node.value)
        if "revision" in values:
            parents[values["revision"]] = values.get("down_revision")
    children = {parent: child for child, parent in parents.items()}
    if len(children) != len(parents):
        raise AssertionError("the migration chain branches")
    chain, current = [], children.get(None)
    while current is not None:
        chain.append(current)
        current = children.get(current)
    return chain


class ExpectedRevisionTests(unittest.TestCase):
    def test_expected_revision_is_the_migrations_head(self) -> None:
        # Fails when a migration lands without bumping domain/schema_revision.py.
        self.assertEqual(EXPECTED_SCHEMA_REVISION, migration_chain()[-1])

    def test_known_revisions_are_the_whole_chain_in_order(self) -> None:
        self.assertEqual(list(KNOWN_SCHEMA_REVISIONS), migration_chain())


class CompareTests(unittest.TestCase):
    def test_states(self) -> None:
        cases = [
            (SchemaReading(revisions=(EXPECTED_SCHEMA_REVISION,)), SchemaState.OK, EXPECTED_SCHEMA_REVISION),
            (SchemaReading(revisions=("0006_saved_history",)), SchemaState.BEHIND, "0006_saved_history"),
            (SchemaReading(revisions=("0011_from_the_future",)), SchemaState.AHEAD, "0011_from_the_future"),
            (SchemaReading(table_present=False), SchemaState.MISSING, None),
            (SchemaReading(readable=False), SchemaState.UNREADABLE, None),
            (SchemaReading(revisions=()), SchemaState.UNREADABLE, None),
            (SchemaReading(reachable=False), SchemaState.UNREACHABLE, None),
        ]
        for reading, state, found in cases:
            with self.subTest(reading=reading):
                self.assertEqual(compare_schema(reading), (state, found))


if __name__ == "__main__":
    unittest.main()
