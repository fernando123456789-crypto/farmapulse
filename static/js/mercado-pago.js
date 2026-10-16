(function (root) {
  "use strict";

  class MercadoPagoCheckout {
    constructor(publicKey) {
      this.bricks = new root.MercadoPago(publicKey, { locale: "es-PE" }).bricks();
      this.card = null;
      this.challenge = null;
      this.generation = 0;
    }

    async mount(amount, email, onSubmit, onError) {
      await this.unmount();
      const generation = this.generation;
      const controller = await this.bricks.create("cardPayment", "mercadoPagoTarjeta", {
        initialization: { amount, payer: { email } },
        callbacks: { onReady: () => {}, onSubmit, onError },
      });
      if (generation !== this.generation) await controller.unmount();
      else this.card = controller;
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
      const current = this.card;
      this.card = null;
      if (this.challenge) this.challenge.remove();
      this.challenge = null;
      if (current) await current.unmount();
    }
  }

  root.FarmaPulseMercadoPago = MercadoPagoCheckout;
})(window);
