import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SEARCH_RADIUS_M = 150


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    i = 0
    lat = 0
    lng = 0
    while i < len(encoded):
        for field in range(2):
            shift = 0
            result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            value = ~(result >> 1) if (result & 1) else (result >> 1)
            if field == 0:
                lat += value
            else:
                lng += value
        coords.append((lat / 1e5, lng / 1e5))
    return coords


def _sample_points(
    coords: list[tuple[float, float]], n: int = 3,
) -> list[dict]:
    if len(coords) < 2:
        return []

    fractions = [0.2, 0.5, 0.8] if n == 3 else [i / (n + 1) for i in range(1, n + 1)]
    labels = {0: "early", 1: "mid", 2: "late"}
    if n != 3:
        labels = {}
        for idx in range(n):
            f = fractions[idx]
            if f <= 0.33:
                labels[idx] = "early"
            elif f <= 0.66:
                labels[idx] = "mid"
            else:
                labels[idx] = "late"

    points = []
    for idx, frac in enumerate(fractions):
        pos = int(frac * (len(coords) - 1))
        lat, lon = coords[pos]
        points.append({"lat": lat, "lon": lon, "position": labels[idx]})
    return points


TAG_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("leisure", "park"): "a park",
    ("leisure", "garden"): "a garden",
    ("leisure", "playground"): "a playground",
    ("leisure", "sports_centre"): "a sports center",
    ("leisure", "stadium"): "a stadium",
    ("natural", "water"): "a body of water",
    ("natural", "wood"): "woods",
    ("natural", "tree_row"): "a tree-lined path",
    ("natural", "hill"): "a hill",
    ("natural", "cliff"): "a cliff",
    ("natural", "beach"): "a beach",
    ("natural", "wetland"): "wetland",
    ("waterway", "river"): "a river",
    ("waterway", "stream"): "a stream",
    ("waterway", "canal"): "a canal",
    ("landuse", "cemetery"): "a cemetery",
    ("landuse", "farmland"): "farmland",
    ("landuse", "vineyard"): "a vineyard",
    ("landuse", "orchard"): "an orchard",
    ("landuse", "forest"): "forest",
    ("amenity", "place_of_worship"): "a church",
    ("amenity", "library"): "a library",
    ("amenity", "hospital"): "a hospital",
    ("amenity", "school"): "a school",
    ("amenity", "university"): "a university",
    ("amenity", "marketplace"): "a market",
    ("tourism", "museum"): "a museum",
    ("tourism", "viewpoint"): "a viewpoint",
    ("tourism", "monument"): "a monument",
    ("tourism", "artwork"): "public art",
    ("historic", "castle"): "a castle",
    ("historic", "monument"): "a monument",
    ("historic", "ruins"): "ruins",
    ("building", "church"): "a church",
    ("building", "cathedral"): "a cathedral",
    ("building", "train_station"): "a train station",
    ("railway", "station"): "a train station",
    ("bridge", "yes"): "a bridge",
    ("man_made", "bridge"): "a bridge",
    ("man_made", "lighthouse"): "a lighthouse",
    ("man_made", "tower"): "a tower",
}

QUERY_TAGS = [
    'node(around:{r},{lat},{lon})["leisure"~"park|garden|playground|stadium"];',
    'way(around:{r},{lat},{lon})["leisure"~"park|garden|playground|stadium"];',
    'node(around:{r},{lat},{lon})["natural"~"water|wood|hill|cliff|beach|wetland"];',
    'way(around:{r},{lat},{lon})["natural"~"water|wood|hill|cliff|beach|wetland"];',
    'node(around:{r},{lat},{lon})["waterway"~"river|stream|canal"];',
    'way(around:{r},{lat},{lon})["waterway"~"river|stream|canal"];',
    'node(around:{r},{lat},{lon})["landuse"~"cemetery|farmland|vineyard|orchard|forest"];',
    'way(around:{r},{lat},{lon})["landuse"~"cemetery|farmland|vineyard|orchard|forest"];',
    'node(around:{r},{lat},{lon})["tourism"~"museum|viewpoint|monument|artwork"];',
    'way(around:{r},{lat},{lon})["tourism"~"museum|viewpoint|monument|artwork"];',
    'node(around:{r},{lat},{lon})["historic"];',
    'way(around:{r},{lat},{lon})["historic"];',
    'way(around:{r},{lat},{lon})["bridge"="yes"];',
    'way(around:{r},{lat},{lon})["man_made"~"bridge|lighthouse|tower"];',
    'way(around:{r},{lat},{lon})["building"~"church|cathedral|train_station"];',
    'way(around:{r},{lat},{lon})["railway"="station"];',
    'node(around:{r},{lat},{lon})["amenity"~"place_of_worship|library|hospital|university|marketplace"];',
    'way(around:{r},{lat},{lon})["amenity"~"place_of_worship|library|hospital|university|marketplace"];',
]


def _build_overpass_query(lat: float, lon: float) -> str:
    lines = ["[out:json][timeout:8];", "("]
    for tag_line in QUERY_TAGS:
        lines.append("  " + tag_line.format(r=SEARCH_RADIUS_M, lat=lat, lon=lon))
    lines.append(");")
    lines.append("out center 5;")
    return "\n".join(lines)


def _element_to_description(element: dict) -> str | None:
    tags = element.get("tags", {})

    for (key, value), description in TAG_DESCRIPTIONS.items():
        if tags.get(key) == value:
            return description

    for key in ("leisure", "natural", "waterway", "landuse", "tourism", "historic"):
        if key in tags:
            val = tags[key]
            match = TAG_DESCRIPTIONS.get((key, val))
            if match:
                return match
            return val.replace("_", " ")

    if tags.get("bridge") == "yes":
        return "a bridge"

    return None


async def _query_point(
    lat: float, lon: float, position: str, client: httpx.AsyncClient,
) -> list[dict]:
    query = _build_overpass_query(lat, lon)
    try:
        response = await client.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        logger.debug("Overpass query failed for point (%s, %s)", lat, lon)
        return []

    seen: set[str] = set()
    beats: list[dict] = []
    for element in data.get("elements", []):
        desc = _element_to_description(element)
        if desc and desc not in seen:
            seen.add(desc)
            beats.append({"description": desc, "position": position})
    return beats


async def get_route_beats(
    polyline: str | None,
    client: httpx.AsyncClient,
) -> list[dict] | None:
    if not polyline:
        return None

    try:
        coords = decode_polyline(polyline)
    except (ValueError, IndexError) as exc:
        logger.debug("Failed to decode polyline: %s", exc)
        return None

    if len(coords) < 2:
        return None

    points = _sample_points(coords)
    if not points:
        return None

    tasks = [
        _query_point(p["lat"], p["lon"], p["position"], client)
        for p in points
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_beats: list[dict] = []
    seen: set[str] = set()
    for result in results:
        if isinstance(result, Exception):
            continue
        for beat in result:
            if beat["description"] not in seen:
                seen.add(beat["description"])
                all_beats.append(beat)

    if not all_beats:
        return None

    return all_beats[:5]
