// Lee los datos de ubicaciones (Departamento -> Provincia -> Distrito) que Flask
// deja en un bloque JSON, y los expone como window.__UBICACIONES__ para main.js.
(function () {
  var el = document.getElementById("ubicaciones-data");
  try {
    window.__UBICACIONES__ = el ? JSON.parse(el.textContent) : {};
  } catch (e) {
    window.__UBICACIONES__ = {};
  }
})();
