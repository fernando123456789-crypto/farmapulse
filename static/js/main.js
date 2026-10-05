(function () {
  "use strict";

  const tablaResultados = document.getElementById("tablaResultados");
  if (!tablaResultados) return;

  const ubicaciones = JSON.parse(document.getElementById("ubicaciones-data").dataset.ubicaciones);

  const selectDepartamento = document.getElementById("selectDepartamento");
  const selectProvincia = document.getElementById("selectProvincia");
  const selectDistrito = document.getElementById("selectDistrito");
  const inputProducto = document.getElementById("inputProducto");
  const inputFarmacia = document.getElementById("inputFarmacia");
  const btnBuscar = document.getElementById("btnBuscar");
  const btnLimpiar = document.getElementById("btnLimpiar");
  const loadingState = document.getElementById("loadingState");
  const panelAhorro = document.getElementById("panelAhorro");
  const ahorroTexto = document.getElementById("ahorroTexto");

  const miCarritoContenedor = document.getElementById("miCarrito");
  const carritoTotalMini = document.getElementById("carritoTotalMini");
  const carritoContador = document.getElementById("carritoContador");
  const btnComprar = document.getElementById("btnComprar");

  const modalCheckout = document.getElementById("modalCheckout");
  const checkoutLista = document.getElementById("checkoutLista");
  const checkoutSubtotal = document.getElementById("checkoutSubtotal");
  const checkoutDelivery = document.getElementById("checkoutDelivery");
  const checkoutTotal = document.getElementById("checkoutTotal");
  const checkoutZona = document.getElementById("checkoutZona");
  const checkoutTiempo = document.getElementById("checkoutTiempo");
  const checkoutCostoEnvio = document.getElementById("checkoutCostoEnvio");
  const btnEnviarWhatsappPedido = document.getElementById("btnEnviarWhatsappPedido");
  const btnCopiarPedido = document.getElementById("btnCopiarPedido");

  const CLAVE_CARRITO = "farmapulse_carrito";

  let configServicio = {
    whatsapp_numero: "51963119803",
    zona_delivery: ["San Borja", "San Luis", "La Victoria"],
    tiempo_delivery_minutos: 35,
    costo_delivery: 5,
  };

  function cargarCarrito() {
    try {
      const crudo = localStorage.getItem(CLAVE_CARRITO);
      return crudo ? JSON.parse(crudo) : [];
    } catch {
      return [];
    }
  }

  function guardarCarritoStorage(carrito) {
    localStorage.setItem(CLAVE_CARRITO, JSON.stringify(carrito));
  }

  let carrito = cargarCarrito();

  function claveProducto(item) {
    return [item.medicamento, item.farmacia, item.presentacion, item.precio_empaque]
      .map((v) => String(v || "").toLowerCase().trim())
      .join("|");
  }

  function estaEnCarrito(item) {
    const clave = claveProducto(item);
    return carrito.some((p) => claveProducto(p) === clave);
  }

  function agregarAlCarrito(item) {
    if (estaEnCarrito(item)) return;
    carrito.push(item);
    guardarCarritoStorage(carrito);
    renderizarCarrito();
    actualizarBotonesFilaSegunCarrito();

    if (window.FarmaPulseAuth?.estaAutenticado()) {
      fetch("/api/receta/guardar", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
        body: JSON.stringify(item),
      }).catch(() => {});
    }
  }

  function quitarDelCarrito(item) {
    const clave = claveProducto(item);
    carrito = carrito.filter((p) => claveProducto(p) !== clave);
    guardarCarritoStorage(carrito);
    renderizarCarrito();
    actualizarBotonesFilaSegunCarrito();
  }

  function totalCarrito() {
    return carrito.reduce((suma, item) => suma + Number(item.precio_empaque || item.precio_unitario || 0), 0);
  }

  function renderizarCarrito() {
    const total = totalCarrito();
    carritoTotalMini.textContent = formatearSoles(total);

    if (carrito.length === 0) {
      miCarritoContenedor.innerHTML =
        '<p class="text-slate-400 text-sm col-span-full">Aún no has agregado productos a tu carrito.</p>';
      carritoContador.classList.add("hidden");
      btnComprar.classList.add("hidden");
      btnComprar.disabled = true;
      return;
    }

    carritoContador.textContent = String(carrito.length);
    carritoContador.classList.remove("hidden");
    btnComprar.classList.remove("hidden");
    btnComprar.disabled = false;

    miCarritoContenedor.innerHTML = carrito
      .map((item) => {
        const precioMostrado = item.precio_empaque != null ? item.precio_empaque : item.precio_unitario;
        return `
        <div class="receta-card fp-fade-in flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="font-semibold text-slate-800 truncate">${escaparHtml(item.medicamento)}</p>
            <p class="text-xs text-slate-400 mb-1">${escaparHtml(item.farmacia)} · ${escaparHtml(item.presentacion || "")}</p>
            <p class="precio-destacado text-sm">${formatearSoles(precioMostrado)}</p>
          </div>
          <button class="btn-quitar-carrito shrink-0" title="Quitar del carrito"
                  data-clave="${escaparHtml(claveProducto(item))}">
            <i class="fa-solid fa-trash-can"></i>
          </button>
        </div>`;
      })
      .join("");

    miCarritoContenedor.querySelectorAll(".btn-quitar-carrito").forEach((btn) => {
      btn.addEventListener("click", () => {
        const clave = btn.dataset.clave;
        const item = carrito.find((p) => claveProducto(p) === clave);
        if (item) quitarDelCarrito(item);
      });
    });
  }

  function poblarDepartamentos() {
    selectDepartamento.innerHTML = '<option value="">-- Seleccione --</option>';
    const departamentos = Object.keys(ubicaciones);
    departamentos.forEach((dep) => {
      const opt = document.createElement("option");
      opt.value = dep;
      opt.textContent = dep;
      selectDepartamento.appendChild(opt);
    });

    if (departamentos.length === 1) {
      selectDepartamento.value = departamentos[0];
      selectDepartamento.disabled = true;
      poblarProvincias(departamentos[0]);
    }
  }

  function poblarProvincias(departamento) {
    selectProvincia.innerHTML = '<option value="">-- Seleccione --</option>';
    selectDistrito.innerHTML = '<option value="">-- Seleccione --</option>';

    if (!departamento || !ubicaciones[departamento]) {
      selectProvincia.disabled = true;
      selectDistrito.disabled = true;
      return;
    }

    const provincias = Object.keys(ubicaciones[departamento]);
    provincias.forEach((prov) => {
      const opt = document.createElement("option");
      opt.value = prov;
      opt.textContent = prov;
      selectProvincia.appendChild(opt);
    });

    if (provincias.length === 1) {
      selectProvincia.value = provincias[0];
      selectProvincia.disabled = true;
      poblarDistritos(departamento, provincias[0]);
    } else {
      selectProvincia.disabled = false;
      selectDistrito.disabled = true;
    }
  }

  function poblarDistritos(departamento, provincia) {
    selectDistrito.innerHTML = '<option value="">-- Seleccione --</option>';

    if (!departamento || !provincia || !ubicaciones[departamento] || !ubicaciones[departamento][provincia]) {
      selectDistrito.disabled = true;
      return;
    }

    ubicaciones[departamento][provincia].forEach((dist) => {
      const opt = document.createElement("option");
      opt.value = dist;
      opt.textContent = dist;
      selectDistrito.appendChild(opt);
    });
    selectDistrito.disabled = false;
  }

  selectDepartamento.addEventListener("change", (e) => {
    poblarProvincias(e.target.value);
  });

  selectProvincia.addEventListener("change", (e) => {
    poblarDistritos(selectDepartamento.value, e.target.value);
  });

  poblarDepartamentos();

  function formatearSoles(valor) {
    const numero = Number(valor || 0);
    return "S/ " + numero.toFixed(2);
  }

  function escaparHtml(texto) {
    const div = document.createElement("div");
    div.textContent = texto == null ? "" : String(texto);
    return div.innerHTML;
  }

  function botonCarritoHtml(item) {
    const enCarrito = estaEnCarrito(item);
    const clase = enCarrito ? "btn-accion btn-quitar btn-carrito-toggle" : "btn-accion btn-agregar btn-carrito-toggle";
    const icono = enCarrito ? "fa-solid fa-cart-arrow-down" : "fa-solid fa-cart-plus";
    const texto = enCarrito ? "Quitar del carrito" : "Agregar al carrito";
    return `
      <button
        class="${clase}"
        data-medicamento="${escaparHtml(item.medicamento)}"
        data-dci="${escaparHtml(item.dci)}"
        data-farmacia="${escaparHtml(item.farmacia)}"
        data-distrito="${escaparHtml(item.distrito)}"
        data-presentacion="${escaparHtml(item.presentacion)}"
        data-precio-unitario="${item.precio_unitario}"
        data-precio-empaque="${item.precio_empaque}"
        data-tipo="${item.tipo}"
        data-en-carrito="${enCarrito}">
        <i class="${icono}"></i> ${texto}
      </button>`;
  }

  function renderizarResultados(resultados) {
    if (!resultados || resultados.length === 0) {
      tablaResultados.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-slate-400 py-14">
            <i class="fa-solid fa-triangle-exclamation text-3xl mb-3 block"></i>
            No se encontraron resultados para tu búsqueda. Intenta con otro término.
          </td>
        </tr>`;
      return;
    }

    const precioMinimo = Math.min(...resultados.map((r) => r.precio_unitario));

    tablaResultados.innerHTML = resultados
      .map((r) => {
        const esMejorPrecio = r.precio_unitario === precioMinimo;
        const badgeClase = r.tipo === "GENERICO" ? "badge-generico" : "badge-marca";
        const badgeTexto = r.tipo === "GENERICO" ? "Genérico" : "Marca";
        const filaClase = esMejorPrecio ? "fila-mejor-precio fp-fade-in" : "fp-fade-in";

        return `
        <tr class="${filaClase}">
          <td class="px-5 py-4">
            <p class="font-semibold text-slate-800">${escaparHtml(r.medicamento)}</p>
            <p class="text-xs text-slate-400">${escaparHtml(r.dci)}</p>
          </td>
          <td class="px-5 py-4"><span class="${badgeClase}">${badgeTexto}</span></td>
          <td class="px-5 py-4">
            <p class="font-medium text-slate-700">${escaparHtml(r.farmacia)}</p>
            <p class="text-xs text-slate-400">${escaparHtml(r.distrito)}</p>
          </td>
          <td class="px-5 py-4 text-slate-600">${escaparHtml(r.presentacion)}</td>
          <td class="px-5 py-4 text-slate-600">${formatearSoles(r.precio_empaque)}</td>
          <td class="px-5 py-4 precio-destacado">
            ${r.precio_unitario_estimado ? "≈ " : ""}${formatearSoles(r.precio_unitario)}
            ${r.precio_unitario_estimado
              ? '<span class="block text-[10px] font-normal text-slate-400" title="Precio por unidad estimado dividiendo el precio del empaque entre la cantidad de la presentación">estimado</span>'
              : ""}
          </td>
          <td class="px-5 py-4">
            ${botonCarritoHtml(r)}
          </td>
        </tr>`;
      })
      .join("");

    document.querySelectorAll(".btn-carrito-toggle").forEach((btn) => {
      btn.addEventListener("click", () => alternarCarritoDesdeBoton(btn));
    });
  }

  function itemDesdeBoton(btn) {
    return {
      medicamento: btn.dataset.medicamento,
      dci: btn.dataset.dci,
      farmacia: btn.dataset.farmacia,
      distrito: btn.dataset.distrito,
      presentacion: btn.dataset.presentacion,
      precio_unitario: parseFloat(btn.dataset.precioUnitario),
      precio_empaque: parseFloat(btn.dataset.precioEmpaque),
      tipo: btn.dataset.tipo,
    };
  }

  function alternarCarritoDesdeBoton(btn) {
    const item = itemDesdeBoton(btn);
    if (estaEnCarrito(item)) {
      quitarDelCarrito(item);
    } else {
      agregarAlCarrito(item);
    }
    btn.outerHTML = botonCarritoHtml(item);
    const nuevoBtn = tablaResultados.querySelector(
      `[data-medicamento="${CSS.escape(item.medicamento)}"][data-farmacia="${CSS.escape(item.farmacia)}"]`
    );
    if (nuevoBtn) nuevoBtn.addEventListener("click", () => alternarCarritoDesdeBoton(nuevoBtn));
  }

  function actualizarBotonesFilaSegunCarrito() {
    tablaResultados.querySelectorAll(".btn-carrito-toggle").forEach((btn) => {
      const item = itemDesdeBoton(btn);
      const nuevoHtml = botonCarritoHtml(item);
      const wrapper = document.createElement("div");
      wrapper.innerHTML = nuevoHtml;
      const nuevoBtn = wrapper.firstElementChild;
      btn.replaceWith(nuevoBtn);
      nuevoBtn.addEventListener("click", () => alternarCarritoDesdeBoton(nuevoBtn));
    });
  }

  function renderizarAhorro(ahorro) {
    if (!ahorro) {
      panelAhorro.classList.add("hidden");
      return;
    }
    ahorroTexto.innerHTML = `
      <strong>${escaparHtml(ahorro.medicamento)}</strong> en
      <strong>${escaparHtml(ahorro.farmacia)}</strong> a solo
      <span class="precio-destacado">${formatearSoles(ahorro.precio_unitario)}</span> por pastilla.
      ✨ ¡Ahorras un <strong>${ahorro.porcentaje_ahorro}%</strong> frente a las marcas comerciales!
    `;
    panelAhorro.classList.remove("hidden");
  }

  function mostrarBloqueoLogin() {
    const modalLogin = document.getElementById("modalLogin");
    if (modalLogin) modalLogin.classList.remove("hidden");
    loadingState.classList.add("hidden");
    tablaResultados.innerHTML = `
      <tr>
        <td colspan="7" class="text-center text-slate-400 py-14">
          <i class="fa-solid fa-lock text-3xl mb-3 block"></i>
          Debes iniciar sesión para comparar precios y guardar tu receta.
        </td>
      </tr>`;
  }

  function actualizarEstadoAccesoComparador() {
    const autenticado = !!window.FarmaPulseAuth?.estaAutenticado();
    btnBuscar.disabled = !autenticado;
    btnBuscar.classList.toggle("opacity-50", !autenticado);
    btnBuscar.classList.toggle("cursor-not-allowed", !autenticado);
    btnBuscar.title = autenticado ? "" : "Inicia sesión para buscar";
    if (!autenticado) {
      tablaResultados.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-slate-400 py-14">
            <i class="fa-solid fa-lock text-3xl mb-3 block"></i>
            Inicia sesión para comparar precios entre farmacias.
          </td>
        </tr>`;
    }
  }

  window.addEventListener("farmapulse:sesion-cambiada", actualizarEstadoAccesoComparador);
  actualizarEstadoAccesoComparador();

  async function buscarMedicamentos() {
    if (!window.FarmaPulseAuth?.estaAutenticado()) {
      mostrarBloqueoLogin();
      return;
    }

    loadingState.classList.remove("hidden");
    panelAhorro.classList.add("hidden");

    const payload = {
      producto: inputProducto.value.trim(),
      departamento: selectDepartamento.value,
      provincia: selectProvincia.value,
      distrito: selectDistrito.value,
      farmacia: inputFarmacia.value.trim(),
    };

    try {
      const respuesta = await fetch("/api/buscar", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
        body: JSON.stringify(payload),
      });

      if (respuesta.status === 401) {
        loadingState.classList.add("hidden");
        mostrarBloqueoLogin();
        return;
      }

      if (!respuesta.ok) throw new Error("Error de red al consultar /api/buscar");

      const data = await respuesta.json();
      renderizarResultados(data.resultados);
      renderizarAhorro(data.ahorro_maximo);
    } catch (error) {
      console.error("[FarmaPulse] Error en la búsqueda:", error);
      tablaResultados.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-red-400 py-14">
            <i class="fa-solid fa-circle-exclamation text-3xl mb-3 block"></i>
            Ocurrió un problema al buscar. Intenta nuevamente en unos segundos.
          </td>
        </tr>`;
    } finally {
      loadingState.classList.add("hidden");
    }
  }

  btnBuscar.addEventListener("click", buscarMedicamentos);

  inputProducto.addEventListener("keydown", (e) => {
    if (e.key === "Enter") buscarMedicamentos();
  });

  btnLimpiar.addEventListener("click", () => {
    inputProducto.value = "";
    inputFarmacia.value = "";
    selectDistrito.value = "";
    panelAhorro.classList.add("hidden");
    tablaResultados.innerHTML = `
      <tr>
        <td colspan="7" class="text-center text-slate-400 py-14">
          <i class="fa-solid fa-pills text-3xl mb-3 block"></i>
          Realiza una búsqueda para comparar precios entre farmacias.
        </td>
      </tr>`;
  });

  function construirMensajeWhatsapp() {
    const lineas = carrito.map((item, i) => {
      const precio = item.precio_empaque != null ? item.precio_empaque : item.precio_unitario;
      return `${i + 1}. ${item.medicamento} (${item.presentacion || "presentación única"}) - ${item.farmacia} - ${formatearSoles(precio)}`;
    });

    const total = totalCarrito() + Number(configServicio.costo_delivery || 0);

    return [
      "Hola FarmaPulse 👋, quiero hacer este pedido:",
      "",
      ...lineas,
      "",
      `Subtotal: ${formatearSoles(totalCarrito())}`,
      `Delivery: ${formatearSoles(configServicio.costo_delivery)}`,
      `Total: ${formatearSoles(total)}`,
      "",
      "📍 Mi ubicación: (la comparto en este chat)",
      "🧾 Adjunto la captura del pago del QR a continuación.",
    ].join("\n");
  }

  function abrirCheckout() {
    if (carrito.length === 0) return;

    checkoutLista.innerHTML = carrito
      .map((item) => {
        const precio = item.precio_empaque != null ? item.precio_empaque : item.precio_unitario;
        return `
        <div class="flex items-center justify-between text-sm border-b border-slate-50 pb-2">
          <div class="min-w-0 pr-2">
            <p class="font-medium text-slate-700 truncate">${escaparHtml(item.medicamento)}</p>
            <p class="text-xs text-slate-400">${escaparHtml(item.farmacia)}</p>
          </div>
          <span class="precio-destacado shrink-0">${formatearSoles(precio)}</span>
        </div>`;
      })
      .join("");

    const subtotal = totalCarrito();
    const costoEnvio = Number(configServicio.costo_delivery || 0);
    checkoutSubtotal.textContent = formatearSoles(subtotal);
    checkoutDelivery.textContent = formatearSoles(costoEnvio);
    checkoutTotal.textContent = formatearSoles(subtotal + costoEnvio);
    checkoutZona.textContent = (configServicio.zona_delivery || []).join(", ");
    checkoutTiempo.textContent = `${configServicio.tiempo_delivery_minutos} minutos`;
    checkoutCostoEnvio.textContent = formatearSoles(costoEnvio);

    btnEnviarWhatsappPedido.href = `https://wa.me/${configServicio.whatsapp_numero}`;

    modalCheckout.classList.remove("hidden");
  }

  function cerrarCheckout() {
    modalCheckout.classList.add("hidden");
  }

  btnComprar.addEventListener("click", abrirCheckout);
  document.querySelectorAll("[data-cerrar-checkout]").forEach((el) =>
    el.addEventListener("click", cerrarCheckout)
  );

  btnCopiarPedido.addEventListener("click", async () => {
    const mensaje = construirMensajeWhatsapp();
    const textoOriginal = btnCopiarPedido.innerHTML;
    try {
      await navigator.clipboard.writeText(mensaje);
      btnCopiarPedido.innerHTML = '<i class="fa-solid fa-check"></i> ¡Copiado!';
    } catch {
      btnCopiarPedido.innerHTML = '<i class="fa-solid fa-xmark"></i> No se pudo copiar';
    } finally {
      setTimeout(() => { btnCopiarPedido.innerHTML = textoOriginal; }, 1800);
    }
  });

  async function cargarConfigServicio() {
    try {
      const respuesta = await fetch("/api/config");
      const data = await respuesta.json();
      if (data.ok) {
        configServicio = {
          whatsapp_numero: data.whatsapp_numero || configServicio.whatsapp_numero,
          zona_delivery: data.zona_delivery || configServicio.zona_delivery,
          tiempo_delivery_minutos: data.tiempo_delivery_minutos || configServicio.tiempo_delivery_minutos,
          costo_delivery: data.costo_delivery != null ? data.costo_delivery : configServicio.costo_delivery,
        };
      }
    } catch (error) {
      console.warn("[FarmaPulse] No se pudo cargar /api/config, se usan valores por defecto:", error);
    }
  }

  cargarConfigServicio();
  renderizarCarrito();
})();
