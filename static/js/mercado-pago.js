(function (root) {
  "use strict";

  class MercadoPagoCheckout {
    constructor(publicKey) {
      this.sdk = new root.MercadoPago(publicKey, { locale: "es-PE" });
      this.fields = [];
      this.cleanup = null;
      this.challenge = null;
      this.generation = 0;
    }

    async mount(amount, email, onSubmit, onError, identity) {
      await this.unmount();
      const generation = this.generation;
      if (!identity?.nombre || !/^\d{8}$/.test(identity.dni || "")) throw new Error("Verifica los datos de la compra antes de pagar");
      const form = root.document.getElementById("mercadoPagoFormulario");
      const button = root.document.getElementById("mercadoPagoPagar");
      const validity = new Map();
      const pruebaAprobada = identity.nombre_tarjeta_prueba === "APRO-AUTH";
      const label = `${pruebaAprobada ? "Confirmar pago de prueba" : "Confirmar pago"} · S/ ${Number(amount).toFixed(2)}`;
      let method = null, binVersion = 0, processing = false;
      const current = () => generation === this.generation;
      const refresh = () => {
        button.disabled = processing || !method || validity.size !== 3 || [...validity.values()].some((valid) => !valid);
        button.textContent = processing ? "Procesando pago…" : label;
      };
      const types = [
        ["cardNumber", "mercadoPagoNumero", "Número de tarjeta", "1234 1234 1234 1234"],
        ["expirationDate", "mercadoPagoVencimiento", "Vencimiento", "MM/AA"],
        ["securityCode", "mercadoPagoSeguridad", "Código de seguridad", "CVV"],
      ];
      for (const [type, target, srLabel, placeholder] of types) {
        const field = this.sdk.fields.create(type, {
          placeholder, srLabel, ariaRequired: true,
          ...(type === "cardNumber" ? { enableLuhnValidation: true } : {}),
          style: { fontSize: "16px", fontFamily: "Arial, sans-serif", color: "#0c3b4b", padding: "0" },
        });
        field.on("validityChange", ({ errorMessages }) => {
          if (!current()) return;
          validity.set(type, Array.isArray(errorMessages) && errorMessages.length === 0);
          refresh();
        });
        this.fields.push(field);
        field.mount(target);
      }
      this.fields[0].on("binChange", async ({ bin }) => {
        const version = ++binVersion;
        method = null;
        refresh();
        if (!bin) return;
        try {
          const response = await this.sdk.getPaymentMethods({ bin });
          if (!current() || version !== binVersion) return;
          method = response.results?.find((item) => item.status === "active" && ["credit_card", "debit_card"].includes(item.payment_type_id));
          if (!method) throw new Error("Tarjeta no disponible");
          const settings = method.settings?.[0]?.security_code;
          if (settings && [3, 4].includes(settings.length)) this.fields[2].update({ settings: { length: settings.length, mode: "mandatory" } });
          refresh();
        } catch (error) {
          if (current() && version === binVersion) { method = null; refresh(); onError(); }
        }
      });
      const submit = async (event) => {
        event.preventDefault();
        if (!current() || processing || button.disabled) return;
        processing = true;
        refresh();
        const selected = method;
        try {
          const token = await this.sdk.fields.createCardToken({
            cardholderName: pruebaAprobada ? "APRO-AUTH" : identity.nombre,
            identificationType: "DNI", identificationNumber: identity.dni,
          });
          if (!current()) return;
          if (selected !== method) throw new Error("La tarjeta cambió mientras se preparaba el pago");
          if (!token?.id) throw new Error("Token no disponible");
          await onSubmit({ token: token.id, payment_method_id: selected.id, installments: 1 }, { paymentTypeId: selected.payment_type_id });
        } catch (error) {
          if (current()) onError();
        } finally {
          processing = false;
          if (current()) refresh();
        }
      };
      form.addEventListener("submit", submit);
      this.cleanup = () => form.removeEventListener("submit", submit);
      refresh();
    }

    async showStatus(payment) {
      if (this.challenge) this.challenge.remove();
      this.challenge = null;
      const container = root.document.getElementById("mercadoPagoEstado");
      container.replaceChildren();
      if (!payment.challenge_url) {
        container.textContent = "Esperando la confirmación de Mercado Pago…";
        return;
      }
      const url = new URL(payment.challenge_url);
      if (url.protocol !== "https:" || ![
        "www.mercadopago.com.pe", "www.mercadopago.com", "www.mercadopago.com.ar",
      ].includes(url.hostname) || url.username || url.password || (url.port && url.port !== "443")) {
        throw new Error("La verificación bancaria no es válida");
      }
      const frame = root.document.createElement("iframe");
      frame.src = url.href;
      frame.title = "Verificación de tu tarjeta";
      frame.className = "mercado-pago-challenge";
      frame.referrerPolicy = "strict-origin-when-cross-origin";
      container.appendChild(frame);
      this.challenge = frame;
    }

    async unmount() {
      this.generation += 1;
      if (this.cleanup) this.cleanup();
      this.cleanup = null;
      const fields = this.fields;
      this.fields = [];
      if (this.challenge) this.challenge.remove();
      this.challenge = null;
      for (const field of fields) await field.unmount();
    }
  }

  root.FarmaPulseMercadoPago = MercadoPagoCheckout;
})(window);
