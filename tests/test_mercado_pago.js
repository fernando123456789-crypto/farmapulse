const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const calls = [];
const controllers = [];
const builder = {
  async create(type, target, settings) {
    calls.push({ type, target, settings });
    const controller = { removed: false, async unmount() { this.removed = true; } };
    controllers.push(controller);
    return controller;
  },
};
let receivedKey;
const container = { textContent: "", children: [], replaceChildren() { this.children = []; }, appendChild(child) { this.children.push(child); } };
const root = { MercadoPago: class {
  constructor(key, options) { receivedKey = key; assert.equal(options.locale, "es-PE"); }
  bricks() { return builder; }
}, document: {
  getElementById() { return container; },
  createElement(type) { assert.equal(type, "iframe"); return { removed: false, remove() { this.removed = true; } }; },
} };
vm.runInNewContext(fs.readFileSync("static/js/mercado-pago.js", "utf8"), { window: root, URL });

(async () => {
  const checkout = new root.FarmaPulseMercadoPago("TEST-public");
  const submit = async (data) => data;
  await checkout.mount(15, "test@example.invalid", submit, () => {});
  assert.equal(receivedKey, "TEST-public");
  assert.equal(calls[0].type, "cardPayment");
  assert.equal(calls[0].settings.initialization.amount, 15);
  assert.equal(calls[0].settings.initialization.payer.email, "test@example.invalid");
  assert.equal(calls[0].settings.callbacks.onSubmit, submit);
  await checkout.showStatus({ challenge_url: "https://www.mercadopago.com.pe/auth/test" });
  const frame = container.children[0];
  assert.equal(frame.src, "https://www.mercadopago.com.pe/auth/test");
  assert.equal(frame.title, "Verificación de tu tarjeta");
  await assert.rejects(checkout.showStatus({ challenge_url: "https://attacker.example/challenge" }));
  assert.ok(frame.removed);
  await checkout.unmount();
  assert.ok(controllers.every((controller) => controller.removed));
  console.log("OK: formulario de Mercado Pago, verificación bancaria y limpieza de componentes.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
