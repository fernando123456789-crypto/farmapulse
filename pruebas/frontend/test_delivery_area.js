const appPath = require('./app-path');
const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
require(appPath('static/js/delivery-area.js'));
const areas = JSON.parse(fs.readFileSync(appPath('static/data/area_reparto.geojson'), "utf8"));
const district = globalThis.FarmaPulseDeliveryArea.districtForPoint;

test("Cobertura: acepta un punto dentro de San Borja", () => {
  const latitude = -12.107, longitude = -76.999;

  const result = district(areas, latitude, longitude);

  assert.equal(result, "San Borja");
});

test("Cobertura: acepta un punto dentro de San Luis", () => {
  assert.equal(district(areas, -12.074, -76.999), "San Luis");
});

test("Cobertura: acepta un punto dentro de La Victoria", () => {
  assert.equal(district(areas, -12.073, -77.019), "La Victoria");
});

test("Cobertura: rechaza puntos fuera de los distritos admitidos", () => {
  for (const [lat, lon] of [[-12.12, -77.03], [-12.093, -77.036], [-16.4, -71.54], [40.71, -74]]) {
    assert.equal(district(areas, lat, lon), null, `Punto externo: ${lat}, ${lon}`);
  }
});

test("Cobertura: rechaza coordenadas inválidas", () => {
  for (const invalid of [NaN, Infinity, null, true, "-12.107", 999]) {
    assert.equal(district(areas, invalid, -76.999), null, `Latitud: ${String(invalid)}`);
  }
});

test("Cobertura: devuelve ausencia de reparto cuando faltan las áreas", () => {
  assert.equal(district(null, -12.107, -76.999), null);
});

test("Cobertura: ignora un distrito no autorizado", () => {
  const foreignArea = structuredClone(areas);
  foreignArea.features[0].properties.IDDIST = "otro-distrito";

  assert.equal(district(foreignArea, -12.107, -76.999), null);
});
