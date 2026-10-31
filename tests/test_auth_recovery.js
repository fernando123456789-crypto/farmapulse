const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor() {
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    this.listeners = {};
    this.children = new Map();
    const classes = new Set(["hidden"]);
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
      toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
    };
  }
  querySelector(selector) {
    if (!this.children.has(selector)) this.children.set(selector, new Element());
    return this.children.get(selector);
  }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  async emit(name) { for (const handler of this.listeners[name] || []) await handler({ preventDefault() {} }); }
  reset() { for (const element of this.children.values()) element.value = ""; }
  focus() {}
  setAttribute() {}
  appendChild() {}
}

const settle = async () => { for (let i = 0; i < 3; i++) await new Promise(setImmediate); };
const response = (data, status = 200) => ({ ok: status < 400, status, headers: { get: () => "application/json" }, json: async () => data });
const storage = (map) => ({ getItem: (key) => map.get(key) || null, setItem: (key, value) => map.set(key, value), removeItem: (key) => map.delete(key) });
const user = { id: "buyer", email: "buyer@example.invalid" };

async function setup({ fragment = "", pending = null, verify = true, send = response({ ok: true, mensaje: "Revisa tu correo" }), update } = {}) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const buttons = new Map(["data-recuperar-contrasena", "data-cancelar-recuperacion"].map((name) => [name, new Element()]));
  const local = new Map();
  const tab = new Map(pending ? [["farmapulse_recuperacion", JSON.stringify(pending)]] : []);
  const calls = [];
  const location = { hash: fragment, pathname: "/comparador", search: "" };
  const window = {
    location, history: { replaceState() { location.hash = ""; } },
    setTimeout() {}, dispatchEvent() {},
  };
  vm.runInNewContext(fs.readFileSync("static/js/auth.js", "utf8"), {
    window, URLSearchParams, CustomEvent: class {},
    localStorage: storage(local), sessionStorage: storage(tab),
    document: {
      title: "FarmaPulse", getElementById: get, createElement: () => new Element(), body: new Element(),
      addEventListener() {},
      querySelectorAll: (selector) => { const button = buttons.get(selector.slice(1, -1)); return button ? [button] : []; },
    },
    fetch: async (url, options) => {
      calls.push({ url, options });
      if (url === "/api/auth/sesion") return response({ autenticado: verify, usuario: verify ? user : null });
      if (url === "/api/auth/recuperar-contrasena") return send;
      if (url === "/api/auth/nueva-contrasena") return update ? update() : response({ ok: true, usuario: user });
      throw new Error("Petición inesperada: " + url);
    },
  });
  await settle();
  return { get, buttons, calls, local, tab, location, window };
}

const fragment = "#access_token=verified-recovery&refresh_token=refresh&type=recovery";
const passwordFields = (h, password = "ClaveNueva123!") => {
  const form = h.get("formNuevaContrasena");
  form.querySelector('[name="password"]').value = password;
  form.querySelector('[name="password_confirmation"]').value = password;
  return form;
};

async function run() {
  {
    const h = await setup();
    h.get("formLogin").querySelector('[name="email"]').value = " buyer@example.invalid ";
    await h.buttons.get("data-recuperar-contrasena").emit("click");
    assert.equal(h.get("modalRecuperarCuenta").classList.contains("hidden"), false);
    const form = h.get("formRecuperarCuenta");
    assert.equal(form.querySelector('[name="email"]').value, user.email);
    await form.emit("submit");
    await form.emit("submit");
    assert.equal(h.calls.length, 1, "Un doble clic no debe enviar dos correos");
    assert.deepEqual(JSON.parse(h.calls[0].options.body), { email: user.email });
    assert.equal(h.calls[0].url, "/api/auth/recuperar-contrasena");
    assert.match(form.querySelector("[data-error]").textContent, /Revisa tu correo/);
    assert.equal(h.local.size, 0);
  }
  {
    const h = await setup({ fragment });
    assert.equal(h.location.hash, "", "Los tokens se retiran de la URL");
    assert.equal(h.get("modalNuevaContrasena").classList.contains("hidden"), false);
    assert.equal(h.local.size, 0, "La recuperación no inicia sesión antes de cambiar la clave");
    assert.equal(h.tab.has("farmapulse_recuperacion"), true);
    const form = passwordFields(h);
    form.querySelector('[name="password_confirmation"]').value = "NoCoincide123!";
    await form.emit("submit");
    assert.match(form.querySelector("[data-error]").textContent, /no coinciden/);
    assert.equal(h.calls.length, 1);
    passwordFields(h, "corta");
    await form.emit("submit");
    assert.equal(h.calls.length, 1);
    passwordFields(h);
    await form.emit("submit");
    const change = h.calls.find(({ url }) => url === "/api/auth/nueva-contrasena");
    assert.equal(change.options.headers.Authorization, "Bearer verified-recovery");
    assert.deepEqual(JSON.parse(change.options.body), { password: "ClaveNueva123!" });
    assert.equal(JSON.parse(h.tab.get("farmapulse_sesion")).usuario.id, user.id);
    assert.equal(h.local.has("farmapulse_sesion"), false);
    assert.equal(JSON.parse(h.tab.get("farmapulse_sesion")).refresh_token, undefined);
    assert.equal(h.tab.has("farmapulse_recuperacion"), false);
    assert.equal(h.get("modalNuevaContrasena").classList.contains("hidden"), true);
    assert.equal(form.querySelector('[name="password"]').value, "");
  }
  {
    const h = await setup({ fragment, verify: false });
    assert.equal(h.get("modalNuevaContrasena").classList.contains("hidden"), true);
    assert.equal(h.local.size, 0);
    assert.equal(h.tab.size, 0);
    assert.match(h.get("formLogin").querySelector("[data-error]").textContent, /venció/);
  }
  {
    const h = await setup({ pending: { access_token: "saved-recovery", refresh_token: "refresh" } });
    assert.equal(h.calls[0].options.headers.Authorization, "Bearer saved-recovery");
    assert.equal(h.get("modalNuevaContrasena").classList.contains("hidden"), false);
  }
  {
    const h = await setup({ fragment: "#access_token=signup-token&refresh_token=refresh&type=signup" });
    assert.equal(JSON.parse(h.tab.get("farmapulse_sesion")).access_token, "signup-token");
    assert.equal(h.get("modalNuevaContrasena").classList.contains("hidden"), true);
  }
  {
    const h = await setup({ fragment: "#error_code=otp_expired&error_description=expired" });
    assert.equal(h.location.hash, "");
    assert.equal(h.calls.length, 0);
    assert.match(h.get("formLogin").querySelector("[data-error]").textContent, /enlace venció/);
  }
  {
    let resolveUpdate;
    const h = await setup({ fragment, update: () => new Promise((resolve) => { resolveUpdate = resolve; }) });
    const form = passwordFields(h);
    const pending = form.emit("submit");
    await settle();
    await form.emit("submit");
    assert.equal(h.calls.filter(({ url }) => url === "/api/auth/nueva-contrasena").length, 1);
    await h.buttons.get("data-cancelar-recuperacion").emit("click");
    resolveUpdate(response({ ok: true, usuario: user }));
    await pending;
    assert.equal(h.local.size, 0, "Una respuesta tardía no restaura la sesión cancelada");
  }
  console.log("OK: recuperación por correo, tokens verificados, clave segura, sesión al guardar, enlaces vencidos y duplicados.");
}
run().catch((error) => { console.error(error); process.exitCode = 1; });
