(function () {
  "use strict";

  const contenedor = document.getElementById("botonWhatsapp");
  if (!contenedor) return;

  async function inicializar() {
    let numero = "51963119803";
    let mensaje = "Hola FarmaPulse, quisiera coordinar un pedido/consulta de medicamentos 🙂";

    try {
      const respuesta = await fetch("/api/config");
      const data = await respuesta.json();
      if (data.ok) {
        numero = data.whatsapp_numero || numero;
        mensaje = data.whatsapp_mensaje || mensaje;
      }
    } catch {
    }

    const enlace = document.createElement("a");
    enlace.href = `https://wa.me/${numero}?text=${encodeURIComponent(mensaje)}`;
    enlace.target = "_blank";
    enlace.rel = "noopener noreferrer";
    enlace.setAttribute("aria-label", "Chatear por WhatsApp");
    enlace.className =
      "fixed bottom-6 right-6 z-40 flex items-center gap-2 bg-[#25D366] hover:bg-[#1DA851] " +
      "transition rounded-full shadow-xl shadow-black/20 pl-4 pr-5 py-3 text-white font-semibold fp-pulse";
    enlace.innerHTML = `
      <i class="fa-brands fa-whatsapp text-2xl"></i>
      <span class="hidden sm:inline">Escríbenos</span>
    `;

    contenedor.appendChild(enlace);
  }

  inicializar();
})();
