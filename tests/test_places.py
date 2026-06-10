import httpx
import pytest

from app.services.places import (
    _element_to_description,
    _sample_points,
    decode_polyline,
    get_route_beats,
)


def test_decode_polyline_simple():
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    coords = decode_polyline(encoded)
    assert len(coords) == 3
    assert abs(coords[0][0] - 38.5) < 0.1
    assert abs(coords[0][1] - (-120.2)) < 0.1


def test_decode_polyline_empty():
    assert decode_polyline("") == []


def test_sample_points_assigns_positions():
    coords = [(i * 0.001, 0.0) for i in range(100)]
    points = _sample_points(coords, n=3)
    assert len(points) == 3
    assert points[0]["position"] == "early"
    assert points[1]["position"] == "mid"
    assert points[2]["position"] == "late"


def test_sample_points_too_few_coords():
    assert _sample_points([(0, 0)]) == []
    assert _sample_points([]) == []


def test_element_to_description_park():
    element = {"tags": {"leisure": "park", "name": "Central Park"}}
    assert _element_to_description(element) == "a park"


def test_element_to_description_river():
    element = {"tags": {"waterway": "river", "name": "Thames"}}
    assert _element_to_description(element) == "a river"


def test_element_to_description_bridge():
    element = {"tags": {"bridge": "yes", "highway": "footway"}}
    assert _element_to_description(element) == "a bridge"


def test_element_to_description_no_match():
    element = {"tags": {"highway": "residential"}}
    assert _element_to_description(element) is None


def test_element_to_description_empty_tags():
    assert _element_to_description({"tags": {}}) is None
    assert _element_to_description({}) is None


def _overpass_transport(elements: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"elements": elements})
    return httpx.MockTransport(handler)


async def test_get_route_beats_with_results():
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    elements = [
        {"type": "way", "tags": {"leisure": "park"}},
        {"type": "node", "tags": {"waterway": "river"}},
    ]
    async with httpx.AsyncClient(transport=_overpass_transport(elements)) as client:
        beats = await get_route_beats(encoded, client)

    assert beats is not None
    assert len(beats) >= 1
    assert any(b["description"] == "a park" for b in beats)


async def test_get_route_beats_no_polyline():
    async with httpx.AsyncClient(transport=_overpass_transport([])) as client:
        assert await get_route_beats(None, client) is None
        assert await get_route_beats("", client) is None


async def test_get_route_beats_no_results():
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    async with httpx.AsyncClient(transport=_overpass_transport([])) as client:
        beats = await get_route_beats(encoded, client)
    assert beats is None


async def test_get_route_beats_deduplicates():
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    elements = [
        {"type": "way", "tags": {"leisure": "park"}},
        {"type": "node", "tags": {"leisure": "park"}},
        {"type": "way", "tags": {"leisure": "park"}},
    ]
    async with httpx.AsyncClient(transport=_overpass_transport(elements)) as client:
        beats = await get_route_beats(encoded, client)

    if beats:
        descriptions = [b["description"] for b in beats]
        assert descriptions.count("a park") <= 1


async def test_get_route_beats_max_five():
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    elements = [
        {"type": "way", "tags": {"leisure": "park"}},
        {"type": "node", "tags": {"waterway": "river"}},
        {"type": "way", "tags": {"natural": "wood"}},
        {"type": "node", "tags": {"tourism": "museum"}},
        {"type": "way", "tags": {"landuse": "cemetery"}},
        {"type": "node", "tags": {"historic": "castle"}},
        {"type": "way", "tags": {"natural": "beach"}},
    ]
    async with httpx.AsyncClient(transport=_overpass_transport(elements)) as client:
        beats = await get_route_beats(encoded, client)

    assert beats is not None
    assert len(beats) <= 5
