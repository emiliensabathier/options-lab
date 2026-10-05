"""The pipeline on the frozen fixture must reproduce the numbers it produced when frozen.

Regenerate with ``python scripts/build_fixture.py`` after an intended change, and say why
in the commit.
"""

import importlib.util
import json

import pytest

from conftest import FIXTURES, ROOT

FLOAT_TOLERANCE = 1e-4  # relative, for numbers computed in closed form
# Fitted models come out of a local optimiser whose last iterations differ across
# platforms and BLAS builds: 1.3001 on Linux against 1.3011 on Windows for one max error.
FIT_TOLERANCE = 5e-3
COUNT_TOLERANCE = 1e-2


def _builder():
    spec = importlib.util.spec_from_file_location("build_fixture",
                                                  ROOT / "scripts" / "build_fixture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_matches(actual, expected, path="root"):
    if isinstance(expected, dict):
        assert set(actual) == set(expected), path
        for key in expected:
            _assert_matches(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, float):
        rel = FIT_TOLERANCE if ".models." in path else FLOAT_TOLERANCE
        assert actual == pytest.approx(expected, rel=rel, abs=1e-9), path
    elif isinstance(expected, int) and ".models." in path:
        # arbitrage counts of a fitted wing move by a few grid points with the optimiser
        # (1295 on Linux, 1298 on Windows); a zero must stay exactly zero
        assert actual == pytest.approx(expected, rel=COUNT_TOLERANCE, abs=0), path
    else:
        assert actual == expected, path


@pytest.fixture(scope="module")
def expected():
    return json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


def test_surface_numbers_are_unchanged(surface_output, expected):
    actual = json.loads(json.dumps(_builder().surface_numbers(surface_output)))
    _assert_matches(actual, expected["surface"])


def test_premium_numbers_are_unchanged(premium_output, expected):
    actual = json.loads(json.dumps(_builder().premium_numbers(premium_output)))
    _assert_matches(actual, expected["premium"])


def test_fixture_reproduces_the_published_vix_to_within_half_a_point(surface_output):
    assert surface_output.cboe["vix"] == pytest.approx(
        surface_output.snapshot.levels["^VIX"], abs=0.5)


def test_arbitrage_free_models_are_clean_and_the_free_fit_is_closest(surface_output):
    models = surface_output.models
    for name in ("SSVI", "eSSVI"):
        assert sum(models[name].violations.values()) == 0, name
        found = surface_output.between_pillars[name]
        assert found["butterfly"] == found["calendar"] == 0, name
    rmse = {name: m.errors["rmse_vol_points"] for name, m in models.items()}
    assert min(rmse, key=rmse.get) == "SVI per slice"
