const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
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
vm.runInNewContext(fs.readFileSync("static/js/mercado-pago.js", "utf8"), { window: root, URL });

(async () => {
  const checkout = new root.FarmaPulseMercadoPago("TEST-public");
  await checkout.mount(15, "test@example.invalid", async (data, extra) => { receivedPayment = { data, extra }; }, () => errors++, { nombre: "JUAN GARCIA", dni: "12345678" });
  assert.equal(receivedKey, "TEST-public");
  assert.deepEqual(fields.map((field) => field.type), ["cardNumber", "expirationDate", "securityCode"]);
  assert.equal(element("mercadoPagoPagar").disabled, true);
  await fields[0].listeners.binChange({ bin: "40091753" });
  for (const field of fields) field.listeners.validityChange({ errorMessages: [] });
  assert.equal(element("mercadoPagoPagar").disabled, false);
  assert.equal(element("mercadoPagoPagar").textContent, "Pagar · S/ 15.00");
  const submit = element("mercadoPagoFormulario").listeners.submit;
  const first = submit({ preventDefault() {} });
  await submit({ preventDefault() {} });
  await first;
  assert.equal(tokens, 1);
  assert.equal(tokenData.cardholderName, "JUAN GARCIA");
  assert.equal(tokenData.identificationNumber, "12345678");
  assert.equal(receivedPayment.data.token, "test-token");
  assert.equal(receivedPayment.data.installments, 1);
  assert.equal(receivedPayment.extra.paymentTypeId, "credit_card");
  assert.equal(receivedPayment.data.cardNumber, undefined);
  assert.equal(receivedPayment.data.securityCode, undefined);
  await checkout.showStatus({ challenge_url: "https://www.mercadopago.com.pe/auth/test" });
  const frame = element("mercadoPagoEstado").children[0];
  assert.equal(frame.src, "https://www.mercadopago.com.pe/auth/test");
  await assert.rejects(checkout.showStatus({ challenge_url: "https://attacker.example/challenge" }));
  assert.ok(frame.removed);
  await checkout.unmount();
  assert.ok(fields.every((field) => field.removed));
  assert.equal(element("mercadoPagoFormulario").listeners.submit, undefined);
  await submit({ preventDefault() {} });
  assert.equal(tokens, 1);
  assert.equal(errors, 0);
  await checkout.mount(15, "test@example.invalid", async () => {}, () => errors++, {
    nombre: "JUAN GARCIA", dni: "12345678", nombre_tarjeta_prueba: "APRO-AUTH",
  });
  const latest = fields.slice(-3);
  await latest[0].listeners.binChange({ bin: "40091753" });
  for (const field of latest) field.listeners.validityChange({ errorMessages: [] });
  assert.match(element("mercadoPagoPagar").textContent, /Pagar de prueba/);
  await element("mercadoPagoFormulario").listeners.submit({ preventDefault() {} });
  assert.equal(tokenData.cardholderName, "APRO-AUTH");
  assert.equal(tokenData.identificationNumber, "12345678");
  await checkout.unmount();
  let validated = false;
  await checkout.mount(15, "test@example.invalid", async () => { assert.equal(validated, true); }, () => errors++, async () => {
    validated = true;
    return { nombre: "JUAN GARCIA", dni: "12345678" };
  });
  assert.equal(validated, false, "Mostrar la tarjeta no debe validar identidad");
  const direct = fields.slice(-3);
  await direct[0].listeners.binChange({ bin: "40091753" });
  for (const field of direct) field.listeners.validityChange({ errorMessages: [] });
  await element("mercadoPagoFormulario").listeners.submit({ preventDefault() {} });
  assert.equal(validated, true);
  assert.equal(tokenData.cardholderName, "JUAN GARCIA");
  await checkout.unmount();
  const tokensBeforeInvalidIdentity = tokens;
  let identityError;
  await checkout.mount(15, "test@example.invalid", async () => { assert.fail("No debe cobrar sin identidad válida"); },
    (error) => { identityError = error; }, async () => { throw new Error("Los nombres no coinciden con el DNI"); });
  const invalidIdentityFields = fields.slice(-3);
  await invalidIdentityFields[0].listeners.binChange({ bin: "40091753" });
  for (const field of invalidIdentityFields) field.listeners.validityChange({ errorMessages: [] });
  await element("mercadoPagoFormulario").listeners.submit({ preventDefault() {} });
  assert.equal(tokens, tokensBeforeInvalidIdentity);
  assert.match(identityError.message, /DNI/);
  await checkout.unmount();
  console.log("OK: tres campos seguros, identidad reutilizada, un solo pago y bloqueo de envíos duplicados.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
