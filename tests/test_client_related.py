"""No-network tests for ``include()``, ``OptimadeStore.related()``, and depth-1
dotted relationship filters in the synchronous remote OPTIMADE client."""

import json
import logging
from urllib.parse import parse_qs, urlsplit

import pytest
from httk.atomistic import OptimadeStructure
from httk.core.optimade import OptimadeResource, parse_optimade_filter
from httk.store import UnsupportedQueryError
from test_client_query import (
    STRUCTURES,
    FakeResponse,
    QueryClient,
    make_files,
    page,
    resource,
    response,
    schema_properties,
)

from httk.serve.optimade import OptimadeClientError, OptimadeResponseError, OptimadeStore


def query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def page_with_included(resources: list[object], *, included: list[object], **kwargs: object) -> FakeResponse:
    """``page()`` extended with an ``included`` envelope member, for these tests only."""

    body = json.loads(page(resources, **kwargs).text)  # type: ignore[arg-type]
    body["included"] = included
    return response(body)


def make_multi(query_responses: list[FakeResponse]) -> tuple[OptimadeStore, QueryClient]:
    """Multi-endpoint discovery: a generic root ('materials'), a bound related
    'structures' endpoint, and a generic '_httk_records' related endpoint --
    for ``include()``, dotted relationship filters, and ``related()``.

    The discovery documents are mutated on the fake client before
    ``OptimadeStore`` is constructed, since discovery is eager at construction.
    """

    base = "https://example.test/v1"
    client = QueryClient(
        "materials",
        {"_anyterial_formula": {"type": "string"}},
        query_responses,
        describedby=None,
        base_url=base,
    )
    client.discovery[base + "/info"] = response(
        {
            "data": {
                "type": "info",
                "attributes": {"available_endpoints": ["materials", "structures", "_httk_records"]},
            }
        }
    )
    client.discovery[base + "/info/structures"] = response(
        {
            "data": {
                "type": "info",
                "properties": schema_properties(
                    STRUCTURES,
                    ("id", "type", "nelements", "elements", "chemical_formula_reduced"),
                    # chemical_formula_reduced's remote (wire) name differs from
                    # its local name; nelements is left unrenamed so filters
                    # against it match the plain "structures.nelements" spelling.
                    renames={"chemical_formula_reduced": "formula_reduced"},
                ),
            },
            "links": {"describedby": STRUCTURES},
        }
    )
    client.discovery[base + "/info/_httk_records"] = response(
        {"data": {"type": "info", "properties": {"_anyterial_kind": {"type": "string"}}}}
    )
    store = OptimadeStore(base, client=client)
    return store, client


def make_shadowed(query_responses: list[FakeResponse]) -> tuple[OptimadeStore, QueryClient]:
    """A root type whose own advertised property shares a name with a served type."""

    base = "https://example.test/v1"
    client = QueryClient(
        "widgets",
        {"references": {"type": "string"}},
        query_responses,
        describedby=None,
        base_url=base,
    )
    client.discovery[base + "/info"] = response(
        {"data": {"type": "info", "attributes": {"available_endpoints": ["widgets", "references"]}}}
    )
    client.discovery[base + "/info/references"] = response(
        {"data": {"type": "info", "properties": {"id": {"type": "string"}, "type": {"type": "string"}}}}
    )
    store = OptimadeStore(base, client=client)
    return store, client


# --------------------------------------------------------------- include()


def test_include_emits_ordered_deduplicated_parameter_and_survives_clone() -> None:
    store, client = make_multi(
        [
            page([resource("m1", "materials", {"_anyterial_formula": "Fe2O3"})]),
            page([], returned=3),
            page([resource("m2", "materials", {"_anyterial_formula": "Fe3O4"})]),
        ]
    )
    searcher = store.searcher()
    variable = searcher.variable(store.entry_type("materials"))
    searcher.include("structures", store.entry_type("_httk_records"), "structures")
    searcher.output(variable, "item")

    rows = list(searcher)
    assert len(rows) == 1
    assert query_params(client.requests[-1])["include"] == ["structures,_httk_records"]

    # count() builds its own URL and must never carry include=.
    assert searcher.count() == 3
    assert "include" not in query_params(client.requests[-1])

    # A derived plan (via _clone(), exercised through set_limit()/results())
    # keeps the include set.
    searcher.set_limit(5)
    cloned_rows = list(searcher.results(item=variable))
    assert len(cloned_rows) == 1
    assert query_params(client.requests[-1])["include"] == ["structures,_httk_records"]

    assert client.query_responses == []


def test_include_requires_targets_and_rejects_unknown_names_before_http() -> None:
    store, client = make_multi([])
    searcher = store.searcher()
    searcher.variable(store.entry_type("materials"))
    discovery_requests = len(client.requests)

    with pytest.raises(TypeError, match="at least one target"):
        searcher.include()
    with pytest.raises(UnsupportedQueryError, match="unknown entry type"):
        searcher.include("no-such-endpoint")
    with pytest.raises(UnsupportedQueryError, match="RemoteEntryType or entry-type name"):
        searcher.include(42)  # type: ignore[arg-type]

    assert len(client.requests) == discovery_requests


# --------------------------------------------------------- dotted traversal


def test_dotted_relationship_filter_uses_related_types_remote_names() -> None:
    store, client = make_multi([page([])])
    searcher = store.searcher()
    material = searcher.variable(store.entry_type("materials"))
    searcher.add((material.structures.nelements > 2) & (material.structures.chemical_formula_reduced == "Fe2O3"))
    searcher.output(material, "item")

    list(searcher)

    rendered = query_params(client.requests[-1])["filter"][0]
    assert "structures.nelements > 2" in rendered
    # chemical_formula_reduced is discovered under the wire name
    # "formula_reduced"; the rendered filter must use that remote name.
    assert 'structures.formula_reduced = "Fe2O3"' in rendered
    parse_optimade_filter(rendered)


def test_underscore_prefixed_served_type_traverses_via_relationship() -> None:
    store, client = make_multi([page([])])
    searcher = store.searcher()
    material = searcher.variable(store.entry_type("materials"))
    searcher.add(material._httk_records._anyterial_kind == "note")
    searcher.output(material, "item")

    list(searcher)

    rendered = query_params(client.requests[-1])["filter"][0]
    assert '_httk_records._anyterial_kind = "note"' in rendered


def test_related_field_errors_and_depth_limit_happen_before_http() -> None:
    store, client = make_multi([])
    searcher = store.searcher()
    material = searcher.variable(store.entry_type("materials"))
    discovery_requests = len(client.requests)

    with pytest.raises(UnsupportedQueryError, match=r"field 'bogus' for related type 'structures'"):
        _value = material.structures.bogus
    with pytest.raises(UnsupportedQueryError, match="traversal"):
        _value = material.structures.nelements.deeper
    with pytest.raises(UnsupportedQueryError, match="related fields as outputs"):
        searcher.output(material.structures.nelements, "x")
    with pytest.raises(UnsupportedQueryError, match="related fields as outputs"):
        searcher.add_sort(material.structures.nelements)
    with pytest.raises(UnsupportedQueryError, match="related fields as outputs"):
        searcher.results(x=material.structures.nelements)
    with pytest.raises(AttributeError):
        _value = material.structures._ipython_canary_method_should_not_exist_
    with pytest.raises(AttributeError):
        _value = material._ipython_canary_method_should_not_exist_

    assert len(client.requests) == discovery_requests


def test_root_field_shadows_a_same_named_served_type() -> None:
    store, client = make_shadowed([page([resource("w1", "widgets", {"references": "abc"})])])
    searcher = store.searcher()
    variable = searcher.variable(store.entry_type("widgets"))
    # If "references" had resolved as a relationship namespace instead of the
    # root's own field, this comparison would not yield a _RemoteExpression
    # and add() would reject it before any request was made.
    searcher.add(variable.references == "abc")
    searcher.output(variable, "item")

    list(searcher)

    assert 'references = "abc"' in query_params(client.requests[-1])["filter"][0]


# ------------------------------------------------------------------ related()


def test_related_resolves_by_identifier_wraps_backends_and_preserves_order() -> None:
    included = [
        resource("s1", "structures", {"nelements": 3, "elements": ["Fe", "O"], "formula_reduced": "Fe2O3"}),
        resource("r1", "_httk_records", {"_anyterial_kind": "note"}),
    ]
    relationships = {
        # The block key differs from the identifier's own "type" -- a
        # StrongLink-shaped edge -- so resolution must key off the
        # identifier, never this block key.
        "_httk_has_input": {"data": [{"type": "structures", "id": "s1"}]},
        "_httk_records": {"data": [{"type": "_httk_records", "id": "r1"}, {"type": "_httk_records", "id": "r2"}]},
        "empty_rel": {"data": []},
        "weird_rel": {"data": [{"type": "unknown-type", "id": "x"}]},
    }
    store, client = make_multi(
        [
            page_with_included(
                [resource("m1", "materials", {"_anyterial_formula": "Fe2O3"}, relationships=relationships)],
                included=included,
            ),
            page([resource("r2", "_httk_records", {"_anyterial_kind": "info2"})]),
        ]
    )
    searcher = store.searcher()
    variable = searcher.variable(store.entry_type("materials"))
    row = searcher.results(item=variable).one()

    (structure,) = store.related(row.item, "_httk_has_input")
    assert isinstance(structure, OptimadeStructure)
    assert structure.unwrap().id == "s1"
    assert structure.unwrap().member == "included"

    requests_before = len(client.requests)
    r1, r2 = store.related(row.item, "_httk_records")
    assert isinstance(r1, OptimadeResource)
    assert r1.id == "r1"
    assert r1.member == "included"
    assert isinstance(r2, OptimadeResource)
    assert r2.id == "r2"
    assert r2.member == "data"
    assert len(client.requests) == requests_before + 1
    fetch_url = client.requests[-1]
    assert urlsplit(fetch_url).path.endswith("/_httk_records")
    assert query_params(fetch_url)["filter"] == ['(id = "r2")']

    with pytest.raises(OptimadeClientError, match="no relationship 'no_such_rel'"):
        store.related(row.item, "no_such_rel")

    assert store.related(row.item, "empty_rel") == ()

    with pytest.raises(OptimadeClientError, match="unknown entry type 'unknown-type'"):
        store.related(row.item, "weird_rel")

    with pytest.raises(TypeError):
        store.related(object(), "x")

    assert client.query_responses == []


def test_related_rejects_malformed_included_member() -> None:
    relationships = {"rel": {"data": [{"type": "structures", "id": "sX"}]}}
    store, client = make_multi(
        [
            page_with_included(
                [resource("m2", "materials", {"_anyterial_formula": "Fe2O3"}, relationships=relationships)],
                included=[{"type": "structures"}],  # missing required 'id'
            )
        ]
    )
    searcher = store.searcher()
    variable = searcher.variable(store.entry_type("materials"))
    row = searcher.results(item=variable).one()

    with pytest.raises(OptimadeResponseError, match="included"):
        store.related(row.item, "rel")

    assert client.query_responses == []


def test_related_rejects_non_array_included() -> None:
    relationships = {"rel": {"data": [{"type": "structures", "id": "sX"}]}}
    body = json.loads(page([resource("m3", "materials", {}, relationships=relationships)]).text)
    body["included"] = {"not": "an array"}
    store, _client = make_multi([response(body)])
    searcher = store.searcher()
    variable = searcher.variable(store.entry_type("materials"))
    row = searcher.results(item=variable).one()

    with pytest.raises(OptimadeResponseError, match="'included' must be an array"):
        store.related(row.item, "rel")


# ------------------------------------------------------------- meta.warnings


def test_meta_warnings_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    store, _client = make_files(
        [
            response(
                {
                    "data": [resource("f-1", "renamed-files")],
                    "meta": {
                        "data_returned": 1,
                        "warnings": [{"detail": "filter references unknown property 'nope'"}],
                    },
                }
            )
        ]
    )
    searcher = store.searcher()
    variable = searcher.variable(store.entry_types[0])
    searcher.output(variable, "record")

    with caplog.at_level(logging.WARNING, logger="httk.serve.optimade.remote_query"):
        list(searcher)

    assert any("filter references unknown property" in message for message in caplog.messages)
    assert any(getattr(rec, "context", None) == "optimade" for rec in caplog.records)
    assert any(rec.name == "httk.serve.optimade.remote_query" for rec in caplog.records)
