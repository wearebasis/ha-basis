"""Check that the schema subset of the fake backend matches the real API."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from graphql import parse, print_ast
from graphql.language import (
    DocumentNode,
    EnumTypeDefinitionNode,
    InputObjectTypeDefinitionNode,
    ObjectTypeDefinitionNode,
    ObjectTypeExtensionNode,
    ScalarTypeDefinitionNode,
)

SCHEMA_DIR = os.environ.get("BASIS_SCHEMA_DIR")


def signatures(document: DocumentNode) -> dict[tuple[str, str], str]:
    """Map (type, member) to the printed signature of the member."""
    result: dict[tuple[str, str], str] = {}
    for node in document.definitions:
        if isinstance(node, (ObjectTypeDefinitionNode, ObjectTypeExtensionNode)):
            for field in node.fields or []:
                args = ", ".join(
                    f"{arg.name.value}: {print_ast(arg.type)}" for arg in field.arguments or []
                )
                result[(node.name.value, field.name.value)] = f"({args}) {print_ast(field.type)}"
        elif isinstance(node, InputObjectTypeDefinitionNode):
            for field in node.fields or []:
                result[(node.name.value, field.name.value)] = print_ast(field.type)
        elif isinstance(node, EnumTypeDefinitionNode):
            for value in node.values or []:
                result[(node.name.value, value.name.value)] = "enum value"
        elif isinstance(node, ScalarTypeDefinitionNode):
            result[(node.name.value, "")] = "scalar"
    return result


@pytest.mark.skipif(
    not SCHEMA_DIR,
    reason="set BASIS_SCHEMA_DIR to a directory with the GraphQL schema files of the API",
)
def test_schema_subset_matches_backend() -> None:
    backend = signatures(
        parse("\n".join(p.read_text() for p in sorted(Path(SCHEMA_DIR).glob("*.graphql"))))
    )
    subset = signatures(parse((Path(__file__).parent / "schema.graphql").read_text()))

    mismatches = {
        member: (signature, backend.get(member))
        for member, signature in subset.items()
        if backend.get(member) != signature
    }
    assert not mismatches
