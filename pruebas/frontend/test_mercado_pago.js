const appPath = require('./app-path');
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

function setup() {
  const fields = [];
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      textContent: "", children: [], listeners: {},
      replaceChildren() { this.children = []; }, appendChild(child) { this.children.push(child); },
      addEventListener(name, handler) { this.listeners[name] = handler; },
      removeEventListener(name, handler) { if (this.listeners[name] === handler) delete this.listeners[name]; },
    });
    return elements.get(id);
  };
  let receivedKey, tokenData, receivedPayment, errors = 0, tokens = 0;
  const root = { MercadoPago: class {
    constructor(key, options) {
      receivedKey = key;
      assert.equal(options.locale, "es-PE");
      this.fields = {
        create(type, options) {
          const field = { type, options, listeners: {},
            on(event, handler) { this.listeners[event] = handler; },
            mount(target) { this.target = target; }, update() {},
            async unmount() { this.removed = true; },
          };
          fields.push(field);
          return field;
        },
        async createCardToken(data) { tokens++; tokenData = data; return { id: "test-token" }; },
      };
    }
    async getPaymentMethods() { return { results: [{ id: "visa", status: "active", payment_type_id: "credit_card" }] }; }
  }, document: {
    getElementById: element,
    createElement(type) { assert.equal(type, "iframe"); return { removed: false, remove() { this.removed = true; } }; },
  } };
  // El cobro con tarjeta debe permanecer en la página, sin Wallet ni login externo.
  const pageLocation = Object.freeze({
    href: "https://farmapulse.example.invalid/comparador",
    assign() { assert.fail("El pago con tarjeta no debe redirigir al comprador"); },
    replace() { assert.fail("El pago con tarjeta no debe redirigir al comprador"); },
  });
  Object.defineProperty(root, "location", {
    get: () => pageLocation,
    set() { assert.fail("El pago con tarjeta no debe redirigir al comprador"); },
  });
  root.open = () => assert.fail("El pago con tarjeta no debe abrir un login de Mercado Pago");
  vm.runInNewContext(fs.readFileSync(appPath('static/js/mercado-pago.js'), "utf8"), { window: root, URL });
  const checkout = new root.FarmaPulseMercadoPago("TEST-public");
  return {
    checkout, fields, element,
    get receivedKey() { return receivedKey; },
    get tokenData() { return tokenData; },
    get receivedPayment() { return receivedPayment; },
    get tokens() { return tokens; },
    get errors() { return errors; },
    async mount(identity = { nombre: "JUAN GARCIA", dni: "12345678" }, onError = () => errors++) {
      await checkout.mount(15, "test@example.invalid", async (data, extra) => { receivedPayment = { data, extra }; }, onError, identity);
    },
    async ready() {
      await fields[0].listeners.binChange({ bin: "40091753" });
      for (const field of fields) field.listeners.validityChange({ errorMessages: [] });
    },
    submit() { return element("mercadoPagoFormulario").listeners.submit({ preventDefault() {} }); },
  };
}

test("Tarjeta: habilita el pago al completar los tres campos seguros", async () => {
  const h = setup();
  await h.mount();
  assert.equal(h.receivedKey, "TEST-public");
  assert.deepEqual(h.fields.map((field) => field.type), ["cardNumber", "expirationDate", "securityCode"]);
  assert.equal(h.element("mercadoPagoPagar").disabled, true);

  await h.ready();

  assert.equal(h.element("mercadoPagoPagar").disabled, false);
  assert.equal(h.element("mercadoPagoPagar").textContent, "Pagar · S/ 15.00");
});

test("Tarjeta: un doble envío genera un solo token y omite los datos sensibles", async () => {
  const h = setup();
  await h.mount();
  await h.ready();
  const submit = h.element("mercadoPagoFormulario").listeners.submit;

  const first = submit({ preventDefault() {} });
  await submit({ preventDefault() {} });
  await first;

  assert.equal(h.tokens, 1);
  assert.equal(h.tokenData.cardholderName, "JUAN GARCIA");
  assert.equal(h.tokenData.identificationNumber, "12345678");
  assert.equal(h.receivedPayment.data.token, "test-token");
  assert.equal(h.receivedPayment.data.installments, 1);
  assert.equal(h.receivedPayment.extra.paymentTypeId, "credit_card");
  assert.equal(h.receivedPayment.data.cardNumber, undefined);
  assert.equal(h.receivedPayment.data.securityCode, undefined);
  assert.equal(h.errors, 0);
});

test("Tarjeta: admite la verificación bancaria y rechaza un dominio externo", async () => {
  const h = setup();
  await h.checkout.showStatus({ challenge_url: "https://www.mercadopago.com.pe/auth/test" });
  const frame = h.element("mercadoPagoEstado").children[0];
  assert.equal(frame.src, "https://www.mercadopago.com.pe/auth/test");

  await assert.rejects(h.checkout.showStatus({ challenge_url: "https://attacker.example/challenge" }));

  assert.ok(frame.removed);
});

test("Tarjeta: desmontar libera los campos y desactiva los envíos anteriores", async () => {
  const h = setup();
  await h.mount();
  await h.ready();
  const submit = h.element("mercadoPagoFormulario").listeners.submit;

  await h.checkout.unmount();
  await submit({ preventDefault() {} });

  assert.ok(h.fields.every((field) => field.removed));
  assert.equal(h.element("mercadoPagoFormulario").listeners.submit, undefined);
  assert.equal(h.tokens, 0);
});

test("Tarjeta: usa el nombre de aprobación únicamente en el modo de prueba", async () => {
  const h = setup();
  await h.mount({
    nombre: "JUAN GARCIA", dni: "12345678", nombre_tarjeta_prueba: "APRO-AUTH",
  });
  await h.ready();

  await h.submit();

  assert.match(h.element("mercadoPagoPagar").textContent, /Pagar de prueba/);
  assert.equal(h.tokenData.cardholderName, "APRO-AUTH");
  assert.equal(h.tokenData.identificationNumber, "12345678");
});

test("Tarjeta: consulta la identidad al enviar el pago y no al mostrar el formulario", async () => {
  const h = setup();
  let validated = false;
  await h.mount(async () => {
    validated = true;
    return { nombre: "JUAN GARCIA", dni: "12345678" };
  });
  assert.equal(validated, false, "Mostrar la tarjeta no debe validar identidad");
  await h.ready();

  await h.submit();

  assert.equal(validated, true);
  assert.equal(h.tokenData.cardholderName, "JUAN GARCIA");
  assert.equal(h.tokens, 1);
});

test("Tarjeta: rechaza una identidad inválida antes de generar el token", async () => {
  const h = setup();
  let identityError;
  await h.mount(async () => { throw new Error("Los nombres no coinciden con el DNI"); },
    (error) => { identityError = error; });
  await h.ready();

  await h.submit();

  assert.equal(h.tokens, 0);
  assert.equal(h.receivedPayment, undefined);
  assert.match(identityError.message, /DNI/);
});
