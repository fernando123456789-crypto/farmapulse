const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor() {
    this.value = "valid";
    this.dataset = {};
    this.listeners = {};
    this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((name) => this.classes.add(name)),
      remove: (...names) => names.forEach((name) => this.classes.delete(name)),
      contains: (name) => this.classes.has(name),
    };
  }
  set textContent(value) {
    this.text = String(value);
    this.html = this.text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  get textContent() { return this.text || ""; }
  set innerHTML(value) { this.html = value; }
  get innerHTML() { return this.html || ""; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  async emit(name) { for (const listener of this.listeners[name] || []) await listener({ target: this }); }
  querySelectorAll() { return []; }
  appendChild() {}
  reportValidity() { return true; }
}

async function run() {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const oldItem = { medicamento: "Paracetamol 500 mg", farmacia: "Inkafarma", presentacion: "Caja de 10", precio_empaque: 9 };
  const storage = new Map([["farmapulse_carrito", JSON.stringify([oldItem])]]);
  const calls = [];
  let submitCard, mountedAmount, tileOptions;
  const bounds = { pad() { return this; } };
  const map = {
    setView() { return this; }, attributionControl: { setPrefix() {} },
    on() {}, invalidateSize() {}, setMaxBounds() {}, setMinZoom() {}, fitBounds() {},
    getBoundsZoom() { return 14; },
  };
  const layer = () => ({ addTo() { return this; }, getBounds() { return bounds; } });
  const response = (data) => ({ ok: true, json: async () => data });
  const root = {
    FarmaPulseAuth: { estaAutenticado: () => true, headersAuth: () => ({}), obtenerCorreoActivo: () => "buyer@example.invalid" },
    MercadoPago: class {},
    FarmaPulseMercadoPago: class {
      async mount(amount, email, submit, onError, identity) {
        assert.equal(typeof identity, "function");
        mountedAmount = amount;
        submitCard = async (...args) => { const payer = await identity(); assert.equal(payer.nombre, "JUAN GARCIA"); await submit(...args); };
        assert.equal(email, "buyer@example.invalid");
      }
      async unmount() {}
    },
    L: {
      map: () => map,
      tileLayer(url, options) {
        assert.equal(url, "https://tile.openstreetmap.org/{z}/{x}/{y}.png");
        tileOptions = options;
        return layer();
      },
      geoJSON: layer, polygon: layer,
    },
    requestAnimationFrame(callback) { callback(); }, setTimeout() {},
  };
  const source = fs.readFileSync("static/js/main.js", "utf8").replace(/\}\)\(\);\s*$/, "window.testHelpers = { botonCarritoHtml, itemDesdeBoton }; })();");
  vm.runInNewContext(source, {
    window: root,
    document: { getElementById: get, createElement: () => new Element(), querySelectorAll: () => [], addEventListener() {} },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    clearTimeout() {}, console,
    fetch: async (url, options) => {
      const body = options?.body ? JSON.parse(options.body) : null;
      calls.push({ url, body });
      if (url === "/api/config") return response({ ok: true, pasarela_configurada: true, mercado_pago_public_key: "test-public", costo_delivery: 5 });
      if (url === "/static/data/area_reparto.geojson") return response(JSON.parse(fs.readFileSync("static/data/area_reparto.geojson", "utf8")));
      if (url === "/api/checkout/cotizar") return response({ ok: true, productos: [{ ...oldItem, precio_empaque: 12.5, cotizacion: "signed-price" }] });
      if (url === "/api/checkout/orden") {
        assert.equal(body.productos[0].cotizacion, "signed-price");
        assert.equal(body.productos[0].precio_empaque, 12.5);
        return response({ ok: true, orden_id: "order", orden_firma: "signed-order", amount: 1750, pagador: { nombre: "JUAN GARCIA", dni: "12345678" } });
      }
      if (url === "/api/checkout/pagar") return response({ ok: true, pago_confirmado: true, estado: "aprobado", comprobante_enviado: true, pago_id: "PAY-test" });
      throw new Error("Petición inesperada: " + url);
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  const helpers = root.testHelpers;
  const html = helpers.botonCarritoHtml({ ...oldItem, cotizacion: "signed-price" });
  assert.match(html, /data-cotizacion="signed-price"/);
  assert.equal(helpers.itemDesdeBoton({ dataset: { cotizacion: "signed-price" } }).cotizacion, "signed-price");
  assert.doesNotMatch(helpers.botonCarritoHtml({ ...oldItem, comprable: false }), /<button/);
  await get("btnComprar").emit("click");
  assert.equal(tileOptions.referrerPolicy, "strict-origin", "El mapa identifica únicamente el origen aunque la página use no-referrer");
  assert.match(tileOptions.attribution, /OpenStreetMap/);
  assert.equal(mountedAmount, 17.5);
  assert.equal(get("checkoutTotal").textContent, "S/ 17.50");
  assert.equal(get("btnPagarMercadoPago").classList.contains("hidden"), true);
  assert.equal(calls.filter(({ url }) => url === "/api/checkout/pagar").length, 0);
  assert.equal(calls.filter(({ url }) => url === "/api/checkout/orden").length, 0, "Escribir datos no debe consumir intentos de identidad");
  await get("checkoutNombres").emit("input");
  assert.equal(get("mercadoPagoTarjeta").classList.contains("hidden"), false, "Editar la entrega conserva los campos de tarjeta");
  await submitCard({ token: "card-token", payment_method_id: "visa", installments: 1 }, { paymentTypeId: "credit_card" });
  const payment = calls.find(({ url }) => url === "/api/checkout/pagar");
  assert.equal(payment.body.token, "card-token");
  assert.equal(payment.body.orden_firma, "signed-order");
  assert.equal(payment.body.productos[0].cotizacion, "signed-price");
  assert.equal(get("checkoutError").textContent, "Compra exitosa, revisa tu correo. Estamos en camino.");
  assert.equal(storage.has("farmapulse_carrito"), false);
  console.log("OK: mapa con origen limitado, carrito antiguo, cotización automática, tarjeta y confirmación del comprobante.");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
