(function (root) {
  "use strict";
  const districts = { "150130": "San Borja", "150134": "San Luis", "150115": "La Victoria" };

  function insideRing(x, y, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [x1, y1] = ring[j];
      const [x2, y2] = ring[i];
      if ((y1 > y) !== (y2 > y) && x < ((x2 - x1) * (y - y1)) / (y2 - y1) + x1) inside = !inside;
    }
    return inside;
  }

  function districtForPoint(areas, latitude, longitude) {
    if (!areas || !Number.isFinite(latitude) || !Number.isFinite(longitude)
        || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
    for (const feature of areas.features) {
      const district = districts[feature.properties.IDDIST];
      if (!district) continue;
      const geometry = feature.geometry;
      const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
      for (const rings of polygons) {
        if (insideRing(longitude, latitude, rings[0])
            && !rings.slice(1).some((ring) => insideRing(longitude, latitude, ring))) return district;
      }
    }
    return null;
  }

  root.FarmaPulseDeliveryArea = { districtForPoint };
})(typeof window !== "undefined" ? window : globalThis);
