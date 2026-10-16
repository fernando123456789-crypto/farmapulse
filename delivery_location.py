"""Cobertura de reparto comprobada por coordenadas en el servidor."""

import json
import math
from functools import lru_cache
from pathlib import Path

DISTRICTS = {"150130": "San Borja", "150134": "San Luis", "150115": "La Victoria"}


@lru_cache(maxsize=1)
def delivery_areas():
    path = Path(__file__).resolve().parent / "static/data/area_reparto.geojson"
    return [feature for feature in json.loads(path.read_text(encoding="utf-8"))["features"]
            if feature["properties"].get("IDDIST") in DISTRICTS]


def _inside_ring(x, y, ring):
    inside = False
    for start, end in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = start[:2]
        x2, y2 = end[:2]
        if ((y1 > y) != (y2 > y)) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def district_for_point(latitude, longitude):
    if (isinstance(latitude, bool) or isinstance(longitude, bool)
            or not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float))
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        return None
    for feature in delivery_areas():
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for rings in polygons:
            if (_inside_ring(longitude, latitude, rings[0])
                    and not any(_inside_ring(longitude, latitude, hole) for hole in rings[1:])):
                return DISTRICTS[feature["properties"]["IDDIST"]]
    return None
