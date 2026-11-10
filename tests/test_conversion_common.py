import importlib.util
import json
from pathlib import Path

import pytest

COMMON = Path(__file__).resolve().parent.parent / "conversion" / "common.py"


@pytest.fixture(scope="module")
def unwrap():
    spec = importlib.util.spec_from_file_location("conversion_common", COMMON)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.unwrap_metricsDict


def device(**extra):
    return {"Date": "2016-01-01", "Time": "12:00:00", **extra}


# --- structure of the names --------------------------------------------------


def test_unwrap_yields_the_dotted_path_and_the_attributes(unwrap):
    attrs = device(Pac=1.0)

    assert list(unwrap({"inverters": {"7F104920": attrs}})) == [
        ("inverters.7F104920", attrs)
    ]


def test_unwrap_yields_a_top_level_device_without_a_prefix(unwrap):
    attrs = device()

    assert list(unwrap({"7F104920": attrs})) == [("7F104920", attrs)]


def test_unwrap_follows_arbitrarily_deep_nesting(unwrap):
    attrs = device()

    assert list(unwrap({"a": {"b": {"c": {"d": attrs}}}})) == [
        ("a.b.c.d", attrs)
    ]


def test_unwrap_yields_every_device_of_every_type(unwrap):
    inv, opt, evt = device(Pac=1), device(Vmod=2), device(Type=3)
    data = {
        "events": {"E1": evt},
        "inverters": {"I1": inv, "I2": inv},
        "optimizers": {"O1": opt},
    }

    assert list(unwrap(data)) == [
        ("events.E1", evt),
        ("inverters.I1", inv),
        ("inverters.I2", inv),
        ("optimizers.O1", opt),
    ]


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"inverters": {}},
        {"events": {}, "inverters": {}, "optimizers": {}},
        {"a": {"b": {}}},
    ],
)
def test_unwrap_of_nothing_yields_nothing(unwrap, data):
    assert list(unwrap(data)) == []


def test_unwrap_is_lazy(unwrap):
    generator = unwrap({"inverters": {"I1": device()}})

    assert iter(generator) is generator
    assert next(generator)[0] == "inverters.I1"
    with pytest.raises(StopIteration):
        next(generator)


# --- Date marker -------------------------------------------------------------


def test_unwrap_stops_at_the_first_dict_with_a_date(unwrap):
    inner = {"Date": "2016-01-01", "Nested": {"Date": "x"}}

    assert list(unwrap({"top": inner})) == [("top", inner)]


def test_unwrap_does_not_modify_the_input(unwrap):
    data = {"inverters": {"I 1": device(Pac=1.0)}}
    before = json.dumps(data, sort_keys=True)

    list(unwrap(data))

    assert json.dumps(data, sort_keys=True) == before


# --- cleaning the names ------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "name"),
    [
        ("with space", "inverters.with_space"),
        ("two  spaces", "inverters.two__spaces"),
        ("a\x00b", "inverters.ab"),
        ("\x00\x00trailing", "inverters.trailing"),
        (1234, "inverters.1234"),
        ("plain", "inverters.plain"),
    ],
)
def test_unwrap_cleans_the_names_for_graphite_and_filesystems(
    unwrap, key, name
):
    attrs = device()

    assert list(unwrap({"inverters": {key: attrs}})) == [(name, attrs)]


def test_unwrap_removes_the_devices_level_of_naming(unwrap):
    attrs = device()

    assert list(unwrap({"devices": {"inverters": {"I1": attrs}}})) == [
        ("inverters.I1", attrs)
    ]


def test_unwrap_removes_devices_when_it_is_the_innermost_level(unwrap):
    attrs = device()

    assert list(unwrap({"inverters": {"devices": attrs}})) == [
        ("inverters", attrs)
    ]


def test_unwrap_drops_a_name_that_is_empty_after_cleaning(unwrap):
    attrs = device()

    assert list(unwrap({"\x00": {"I1": attrs}})) == [("I1", attrs)]


def test_unwrap_drops_an_empty_name_on_both_sides(unwrap):
    attrs = device()

    assert list(unwrap({"devices": {"\x00": attrs}})) == [("", attrs)]


def test_unwrap_works_on_what_json_loads_returns(unwrap):
    line = json.dumps({"inverters": {"7F104920": device(Pac=1.5)}})

    assert [name for name, _ in unwrap(json.loads(line))] == [
        "inverters.7F104920"
    ]
