const assert = require("node:assert/strict");
const fs = require("node:fs");
require("../static/js/delivery-area.js");
const areas = JSON.parse(fs.readFileSync("static/data/area_reparto.geojson", "utf8"));
const district = globalThis.FarmaPulseDeliveryArea.districtForPoint;
for (const [lat, lon, expected] of [
  [-12.107, -76.999, "San Borja"], [-12.074, -76.999, "San Luis"],
  [-12.073, -77.019, "La Victoria"], [-12.12, -77.03, null],
  [-12.093, -77.036, null], [-16.4, -71.54, null], [40.71, -74, null],
]) assert.equal(district(areas, lat, lon), expected);
for (const invalid of [NaN, Infinity, null, true, "-12.107", 999]) {
  assert.equal(district(areas, invalid, -76.999), null);
}
assert.equal(district(null, -12.107, -76.999), null);
const foreignArea = structuredClone(areas);
foreignArea.features[0].properties.IDDIST = "otro-distrito";
assert.equal(district(foreignArea, -12.107, -76.999), null);
console.log("OK: cobertura del mapa limitada a los tres distritos; puntos externos y datos inválidos rechazados.");
