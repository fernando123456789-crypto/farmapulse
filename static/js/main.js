/* =========================================================
   FarmaPulse - main.js
   Lógica de filtros en cascada, consumo de /api/buscar,
   renderizado dinámico de la tabla comparativa y manejo
   del carrito de compra + checkout con Mercado Pago.
   ========================================================= */

(function () {
  "use strict";

  // Solo se ejecuta la lógica del comparador si estamos en esa vista.
  const tablaResultados = document.getElementById("tablaResultados");
  if (!tablaResultados) return;

  const ubicaciones = window.__UBICACIONES__ || {};

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

  // Carrito
  const miCarritoContenedor = document.getElementById("miCarrito");
  const carritoTotalMini = document.getElementById("carritoTotalMini");
  const carritoContador = document.getElementById("carritoContador");
  const btnComprar = document.getElementById("btnComprar");

  // Checkout (modal)
  const modalCheckout = document.getElementById("modalCheckout");
  const checkoutLista = document.getElementById("checkoutLista");
  const checkoutSubtotal = document.getElementById("checkoutSubtotal");
  const checkoutDelivery = document.getElementById("checkoutDelivery");
  const checkoutTotal = document.getElementById("checkoutTotal");
  const checkoutApellidos = document.getElementById("checkoutApellidos");
  const checkoutNombres = document.getElementById("checkoutNombres");
  const checkoutDni = document.getElementById("checkoutDni");
  const checkoutTelefono = document.getElementById("checkoutTelefono");
  const checkoutDistrito = document.getElementById("checkoutDistrito");
  const checkoutDireccion = document.getElementById("checkoutDireccion");
  const checkoutPlaceId = document.getElementById("checkoutPlaceId");
  const checkoutDireccionValidacion = document.getElementById("checkoutDireccionValidacion");
  const checkoutDireccionEstado = document.getElementById("checkoutDireccionEstado");
  const checkoutDireccionSugerencias = document.getElementById("checkoutDireccionSugerencias");
  const checkoutEmail = document.getElementById("checkoutEmail");
  const checkoutError = document.getElementById("checkoutError");
  const btnPagarMercadoPago = document.getElementById("btnPagarMercadoPago");

  const CLAVE_CARRITO = "farmapulse_carrito";
  let temporizadorDireccion = null;
  let cobroEnCurso = false;
  let pagoSinConfirmar = false;
  let versionCheckout = 0;
  let checkoutMercadoPago = null;
  let temporizadorEstadoPago = null;
  let ordenPendiente = null;
  let pagoPendiente = null;
  const tarjetaMercadoPago = document.getElementById("mercadoPagoTarjeta");
  const estadoMercadoPago = document.getElementById("mercadoPagoEstado");
  let versionDireccion = 0;

  // Configuración del servicio y pasarela.
  // Se pide una sola vez a /api/config para no hardcodear nada en el JS.
  let configServicio = {
    mercado_pago_public_key: "",
    pasarela_configurada: false,
    geocodificador_configurado: true,
    zona_delivery: ["San Borja", "San Luis", "La Victoria"],
    tiempo_delivery_minutos: 35,
    costo_delivery: 5,
  };

  // -------------------------------------------------------
  // Carrito: persistido en localStorage para que sobreviva a un
  // refresh de página (misma idea que el id anónimo de auth.js).
  // -------------------------------------------------------
  function cargarCarrito() {
    try {
      const crudo = localStorage.getItem(CLAVE_CARRITO);
      const items = crudo ? JSON.parse(crudo) : [];
      return Array.isArray(items) ? items.filter((item) => item && typeof item === "object") : [];
    } catch {
      return [];
    }
  }

  function guardarCarritoStorage(carrito) {
    localStorage.setItem(CLAVE_CARRITO, JSON.stringify(carrito));
  }

  let carrito = cargarCarrito();

  // Clave estable para identificar "el mismo producto" entre distintas
  // búsquedas (el id que manda el backend es un uuid nuevo cada vez).
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

    // Se registra también en el historial de Supabase (best-effort, no
    // bloquea el carrito si Supabase no está disponible o falla).
    // Solo se guarda en Supabase si hay sesión; sin sesión queda en el carrito local.
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

  // -------------------------------------------------------
  // Poblar select de Departamentos / Provincias / Distritos
  // Como el servicio hoy solo cubre Lima > Lima > 3 distritos,
  // se autoseleccionan Departamento y Provincia (no tiene sentido
  // pedirle al usuario que elija entre una sola opción) y solo
  // queda por elegir el Distrito.
  // -------------------------------------------------------
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

  // -------------------------------------------------------
  // Helpers de formato
  // -------------------------------------------------------
  function formatearSoles(valor) {
    const numero = Number(valor || 0);
    return "S/ " + numero.toFixed(2);
  }

  function escaparHtml(texto) {
    return String(texto == null ? "" : texto)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  checkoutDni.addEventListener("input", () => {
    checkoutDni.value = checkoutDni.value.replace(/\D/g, "").slice(0, 8);
  });

  function estadoDireccion(mensaje, error = false, exito = false) {
    checkoutDireccionEstado.textContent = mensaje;
    checkoutDireccionEstado.classList.remove("text-slate-500", "text-red-600", "text-fpGreenDark");
    checkoutDireccionEstado.classList.add(error ? "text-red-600" : exito ? "text-fpGreenDark" : "text-slate-500");
  }

  function invalidarDireccionSeleccionada() {
    invalidarFormularioPago();
    checkoutPlaceId.value = "";
    checkoutDireccionValidacion.value = "";
    delete checkoutDireccionValidacion.dataset.distrito;
  }

  let mapaEntrega = null;
  let areasReparto = null;
  let marcadorEntrega = null;
  let temporizadorPunto = null;
  const centrosDistritos = {
    "San Borja": [-12.107, -76.999], "San Luis": [-12.074, -76.999],
    "La Victoria": [-12.073, -77.019],
  };

  function prepararMapaEntrega() {
    if (!window.L) {
      estadoDireccion("No se pudo cargar el mapa. Recarga la página para continuar.", true);
      return;
    }
    if (!mapaEntrega) {
      mapaEntrega = window.L.map("checkoutMapa", { scrollWheelZoom: false, maxBoundsViscosity: 1 })
        .setView(centrosDistritos[checkoutDistrito.value] || [-12.085, -77.01], 14);
      mapaEntrega.attributionControl.setPrefix(false);
      window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        // OSM exige Referer: comparto solo el origen HTTPS, nunca la ruta ni parámetros.
        referrerPolicy: "strict-origin",
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(mapaEntrega);
      mapaEntrega.on("click", (evento) => elegirPuntoEntrega(evento.latlng));
      fetch("/static/data/area_reparto.geojson")
        .then((respuesta) => { if (!respuesta.ok) throw new Error(); return respuesta.json(); })
        .then((areas) => {
          areasReparto = areas;
          const cobertura = window.L.geoJSON(areas, {
            interactive: false, style: { color: "#0f766e", weight: 2, fillOpacity: 0.1 },
          }).addTo(mapaEntrega);
          const limites = cobertura.getBounds().pad(0.05);
          mapaEntrega.setMaxBounds(limites);
          mapaEntrega.setMinZoom(mapaEntrega.getBoundsZoom(limites));
          mapaEntrega.fitBounds(limites);
          const exteriores = areas.features.flatMap((feature) => {
            const geometry = feature.geometry;
            const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
            return polygons.map((rings) => rings[0].map(([lon, lat]) => [lat, lon]));
          });
          window.L.polygon([
            [[-85, -180], [-85, 180], [85, 180], [85, -180]], ...exteriores,
          ], { interactive: false, stroke: false, fillColor: "#f8fafc", fillOpacity: 0.85, fillRule: "evenodd" })
            .addTo(mapaEntrega);
        })
        .catch(() => estadoDireccion("No se pudo cargar la cobertura. Recarga la página antes de elegir una ubicación.", true));
    }
    mapaEntrega.invalidateSize();
  }

  function colocarMarcador(punto) {
    if (!marcadorEntrega) {
      marcadorEntrega = window.L.marker(punto, {
        draggable: true, title: "Punto de entrega: arrastra hasta tu puerta",
        icon: window.L.divIcon({ className: "checkout-pin", html: "•", iconSize: [30, 30], iconAnchor: [15, 15] }),
      }).addTo(mapaEntrega);
      marcadorEntrega.on("dragstart", () => {
        ++versionDireccion;
        clearTimeout(temporizadorPunto);
        invalidarDireccionSeleccionada();
      });
      marcadorEntrega.on("dragend", () => elegirPuntoEntrega(marcadorEntrega.getLatLng()));
    } else {
      marcadorEntrega.setLatLng(punto);
    }
  }

  function elegirPuntoEntrega(punto) {
    clearTimeout(temporizadorDireccion);
    clearTimeout(temporizadorPunto);
    const version = ++versionDireccion;
    invalidarDireccionSeleccionada();
    checkoutDireccionSugerencias.classList.add("hidden");
    if (!areasReparto || !window.FarmaPulseDeliveryArea) {
      estadoDireccion("Espera a que se cargue la cobertura del mapa.", true);
      return;
    }
    if (!window.FarmaPulseDeliveryArea.districtForPoint(areasReparto, punto.lat, punto.lng)) {
      if (marcadorEntrega) {
        marcadorEntrega.remove();
        marcadorEntrega = null;
      }
      estadoDireccion("Solo entregamos en San Borja, San Luis y La Victoria. Elige un punto dentro del área resaltada.", true);
      return;
    }
    colocarMarcador(punto);
    if (checkoutDireccion.value.trim().length < 5) {
      estadoDireccion("Escribe la calle, número o referencia y vuelve a marcar el punto de entrega.");
      return;
    }
    estadoDireccion("Comprobando cobertura del punto de entrega...");
    temporizadorPunto = window.setTimeout(() => confirmarPuntoEntrega(punto, version), 350);
  }

  async function confirmarPuntoEntrega(punto, version) {
    try {
      const respuesta = await fetch("/api/direcciones/validar", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
        body: JSON.stringify({ latitud: punto.lat, longitud: punto.lng, direccion: checkoutDireccion.value.trim() }),
      });
      const datos = await respuesta.json();
      if (version !== versionDireccion) return;
      if (!respuesta.ok || !datos.ok) throw new Error(datos.error || "No se pudo comprobar la cobertura");
      checkoutDistrito.value = datos.distrito;
      checkoutPlaceId.value = datos.place_id;
      checkoutDireccionValidacion.value = datos.validacion;
      checkoutDireccionValidacion.dataset.distrito = datos.distrito;
      estadoDireccion(`Punto de entrega seleccionado en ${datos.distrito}.`, false, true);
    } catch (error) {
      if (version !== versionDireccion) return;
      invalidarDireccionSeleccionada();
      estadoDireccion(error.message, true);
    }
  }

  async function cargarSugerenciasDireccion(texto, version) {
    try {
      const respuesta = await fetch("/api/direcciones/sugerencias", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
        body: JSON.stringify({ texto, distrito: checkoutDistrito.value }),
      });
      const datos = await respuesta.json();
      if (version !== versionDireccion || checkoutDireccion.value.trim() !== texto) return;
      if (!respuesta.ok || !datos.ok) throw new Error(datos.error || "No se pudieron buscar direcciones");
      checkoutDireccionSugerencias.replaceChildren();
      for (const sugerencia of datos.sugerencias || []) {
        const opcion = document.createElement("button");
        opcion.type = "button";
        opcion.setAttribute("role", "option");
        opcion.className = "block w-full border-b border-slate-100 px-4 py-3 text-left text-sm text-slate-700 hover:bg-fpMint last:border-b-0";
        opcion.textContent = sugerencia.descripcion;
        opcion.addEventListener("click", () => {
          if (version !== versionDireccion) return;
          prepararMapaEntrega();
          if (!mapaEntrega) return;
          const punto = window.L.latLng(sugerencia.latitud, sugerencia.longitud);
          mapaEntrega.setView(punto, 18);
          colocarMarcador(punto);
          checkoutDireccionSugerencias.classList.add("hidden");
          if (sugerencia.direccion_precisa) {
            elegirPuntoEntrega(punto);
          } else {
            ++versionDireccion;
            estadoDireccion("Calle encontrada. Mueve el marcador hasta el punto exacto de entrega.");
          }
        });
        checkoutDireccionSugerencias.appendChild(opcion);
      }
      checkoutDireccionSugerencias.classList.toggle("hidden", checkoutDireccionSugerencias.childElementCount === 0);
      estadoDireccion(checkoutDireccionSugerencias.childElementCount
        ? "Elige tu calle y revisa el punto de entrega en el mapa."
        : "Tu dirección no aparece. Puedes marcarla directamente en el mapa.");
    } catch (error) {
      if (version !== versionDireccion) return;
      checkoutDireccionSugerencias.classList.add("hidden");
      estadoDireccion("La búsqueda no está disponible. Puedes marcar tu dirección directamente en el mapa.");
    }
  }

  checkoutDireccion.addEventListener("input", () => {
    const texto = checkoutDireccion.value.trim();
    const version = ++versionDireccion;
    clearTimeout(temporizadorDireccion);
    clearTimeout(temporizadorPunto);
    invalidarDireccionSeleccionada();
    checkoutDireccionSugerencias.classList.add("hidden");
    if (texto.length < 3) {
      estadoDireccion("Escribe tu dirección y marca el punto de entrega en el mapa.");
      return;
    }
    estadoDireccion("Buscando tu calle...");
    temporizadorDireccion = window.setTimeout(() => cargarSugerenciasDireccion(texto, version), 650);
  });

  checkoutDistrito.addEventListener("change", () => {
    ++versionDireccion;
    clearTimeout(temporizadorDireccion);
    clearTimeout(temporizadorPunto);
    invalidarDireccionSeleccionada();
    checkoutDireccionSugerencias.classList.add("hidden");
    if (mapaEntrega && centrosDistritos[checkoutDistrito.value]) {
      mapaEntrega.setView(centrosDistritos[checkoutDistrito.value], 15);
    }
    estadoDireccion("Marca el punto exacto de entrega en el mapa.");
  });
  document.getElementById("checkoutUsarCentro").addEventListener("click", () => {
    if (mapaEntrega) elegirPuntoEntrega(mapaEntrega.getCenter());
  });

  document.addEventListener("click", (evento) => {
    if (!checkoutDireccionSugerencias.contains(evento.target) && evento.target !== checkoutDireccion) {
      checkoutDireccionSugerencias.classList.add("hidden");
    }
  });

  // -------------------------------------------------------
  // Renderizado de la tabla comparativa
  // -------------------------------------------------------
  function botonCarritoHtml(item) {
    if (item.comprable === false) {
      return '<span class="text-xs text-slate-500">No disponible para compra</span>';
    }
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
        data-precio-unitario="${escaparHtml(item.precio_unitario)}"
        data-precio-empaque="${escaparHtml(item.precio_empaque)}"
        data-tipo="${escaparHtml(item.tipo)}"
        data-cotizacion="${escaparHtml(item.cotizacion || "")}"
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
      cotizacion: btn.dataset.cotizacion || "",
    };
  }

  function alternarCarritoDesdeBoton(btn) {
    const item = itemDesdeBoton(btn);
    if (estaEnCarrito(item)) {
      quitarDelCarrito(item);
    } else {
      agregarAlCarrito(item);
    }
    // Refresca este botón puntual sin tener que re-renderizar toda la tabla.
    btn.outerHTML = botonCarritoHtml(item);
    const nuevoBtn = tablaResultados.querySelector(
      `[data-medicamento="${CSS.escape(item.medicamento)}"][data-farmacia="${CSS.escape(item.farmacia)}"]`
    );
    if (nuevoBtn) nuevoBtn.addEventListener("click", () => alternarCarritoDesdeBoton(nuevoBtn));
  }

  // Tras una nueva búsqueda, o al agregar/quitar desde la tarjeta del
  // carrito, hay que refrescar el estado visual (Agregar/Quitar) de
  // todos los botones de la tabla que correspondan a productos ya en
  // el carrito.
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

  // -------------------------------------------------------
  // Panel de "Máximo ahorro encontrado"
  // -------------------------------------------------------
  function renderizarAhorro(ahorro) {
    if (!ahorro) {
      panelAhorro.classList.add("hidden");
      return;
    }
    ahorroTexto.innerHTML = `
      <strong>${escaparHtml(ahorro.medicamento)}</strong> en
      <strong>${escaparHtml(ahorro.farmacia)}</strong> a solo
      <span class="precio-destacado">${formatearSoles(ahorro.precio_unitario)}</span> por pastilla.
      ✨ ¡Ahorras un <strong>${escaparHtml(ahorro.porcentaje_ahorro)}%</strong> frente a las marcas comerciales!
    `;
    panelAhorro.classList.remove("hidden");
  }

  // -------------------------------------------------------
  // Sugerencia (NO obligatoria) de iniciar sesión.
  // Buscar es libre para todos. Después de una búsqueda, a quien no
  // tiene sesión se le muestra un aviso que se cierra con la X, con
  // "Seguir sin cuenta", tocando fuera de la ventana o con Esc.
  // -------------------------------------------------------
  // true  = el aviso sale después de CADA búsqueda
  // false = sale solo una vez por visita (por pestaña del navegador)
  const SUGERIR_LOGIN_EN_CADA_BUSQUEDA = false;
  const CLAVE_SUGERENCIA_VISTA = "farmapulse_sugerencia_login_vista";

  const modalSugerencia = document.getElementById("modalSugerenciaLogin");

  function cerrarSugerenciaLogin() {
    if (modalSugerencia) modalSugerencia.classList.add("hidden");
  }

  function mostrarSugerenciaLogin() {
    if (!modalSugerencia) return;
    if (window.FarmaPulseAuth?.estaAutenticado()) return;

    if (!SUGERIR_LOGIN_EN_CADA_BUSQUEDA) {
      try {
        if (sessionStorage.getItem(CLAVE_SUGERENCIA_VISTA)) return;
        sessionStorage.setItem(CLAVE_SUGERENCIA_VISTA, "1");
      } catch {
        /* sin sessionStorage: se muestra igual */
      }
    }
    modalSugerencia.classList.remove("hidden");
  }

  function abrirModalAuthDesdeSugerencia(idModal) {
    cerrarSugerenciaLogin();
    document.getElementById(idModal)?.classList.remove("hidden");
  }

  document.querySelectorAll("[data-cerrar-sugerencia]").forEach((el) =>
    el.addEventListener("click", cerrarSugerenciaLogin)
  );
  document.getElementById("btnSugerenciaIniciarSesion")?.addEventListener("click", () =>
    abrirModalAuthDesdeSugerencia("modalLogin")
  );
  document.getElementById("btnSugerenciaCrearCuenta")?.addEventListener("click", () =>
    abrirModalAuthDesdeSugerencia("modalRegistro")
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") cerrarSugerenciaLogin();
  });

  // -------------------------------------------------------
  // Llamada a la API /api/buscar
  // -------------------------------------------------------
  async function buscarMedicamentos() {
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

      if (!respuesta.ok) throw new Error("Error de red al consultar /api/buscar");

      const data = await respuesta.json();
      renderizarResultados(data.resultados);
      renderizarAhorro(data.ahorro_maximo);
      // Los resultados ya están a la vista; el aviso aparece apenas después.
      setTimeout(mostrarSugerenciaLogin, 600);
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

  // -------------------------------------------------------
  // Checkout: abrir modal con el resumen del carrito
  // -------------------------------------------------------
  async function abrirCheckout() {
    if (carrito.length === 0) return;
    if (!window.FarmaPulseAuth?.estaAutenticado()) {
      document.getElementById("btnAbrirLogin")?.click();
      return;
    }
    checkoutError.classList.add("hidden");
    checkoutEmail.textContent = `Comprobante para: ${window.FarmaPulseAuth.obtenerCorreoActivo() || "tu correo de cuenta"}`;
    btnPagarMercadoPago.disabled = pagoSinConfirmar;
    if (!pagoSinConfirmar) btnPagarMercadoPago.textContent = "Preparando los campos de tarjeta…";
    btnPagarMercadoPago.classList.remove("hidden");
    if (ordenPendiente && pagoPendiente) iniciarSeguimientoPago(ordenPendiente, pagoPendiente);
    renderizarResumenCheckout();
    modalCheckout.classList.remove("hidden");
    window.requestAnimationFrame(prepararMapaEntrega);
    if (!pagoSinConfirmar) await prepararTarjetaPago();
  }

  function renderizarResumenCheckout() {
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
  }

  async function cerrarCheckout() {
    if (cobroEnCurso) return;
    modalCheckout.classList.add("hidden");
    ++versionCheckout;
    clearTimeout(temporizadorEstadoPago);
    if (checkoutMercadoPago) await checkoutMercadoPago.unmount();
    tarjetaMercadoPago.classList.add("hidden");
    estadoMercadoPago.classList.add("hidden");
  }

  function invalidarFormularioPago() {
    if (cobroEnCurso || pagoSinConfirmar) return;
    checkoutError.classList.add("hidden");
  }

  [checkoutDni, checkoutApellidos, checkoutNombres, checkoutTelefono, checkoutDistrito, checkoutDireccion]
    .forEach((campo) => campo.addEventListener("input", invalidarFormularioPago));

  function mostrarResultadoPago(data) {
    checkoutError.classList.remove("hidden");
    if (data.ok && data.pago_confirmado && data.estado === "aprobado") {
      pagoSinConfirmar = false;
      ordenPendiente = pagoPendiente = null;
      localStorage.removeItem(CLAVE_CARRITO);
      carrito = [];
      renderizarCarrito();
      tarjetaMercadoPago.classList.add("hidden");
      checkoutError.textContent = data.comprobante_enviado
        ? "Compra exitosa, revisa tu correo. Estamos en camino."
        : `${data.mensaje} Operación: ${data.pago_id}.`;
      checkoutError.classList.remove("border-red-200", "bg-red-50", "text-red-700");
      checkoutError.classList.add("border-green-200", "bg-green-50", "text-green-700");
      btnPagarMercadoPago.disabled = true;
      btnPagarMercadoPago.textContent = "Pago aprobado";
      clearTimeout(temporizadorEstadoPago);
      return true;
    }
    checkoutError.textContent = data.error || "No se pudo confirmar el pago";
    pagoSinConfirmar = ["pendiente", "sin_confirmar", "procesando"].includes(data.estado);
    btnPagarMercadoPago.disabled = pagoSinConfirmar;
    btnPagarMercadoPago.textContent = pagoSinConfirmar ? "Pago pendiente de confirmación" : "Revisa los datos e intenta pagar nuevamente";
    return false;
  }

  async function iniciarSeguimientoPago(orden, pago) {
    ordenPendiente = orden;
    pagoPendiente = pago;
    tarjetaMercadoPago.classList.add("hidden");
    estadoMercadoPago.classList.remove("hidden");
    if (checkoutMercadoPago) {
      try {
        await checkoutMercadoPago.showStatus(pago, () => {
          checkoutError.textContent = "No se pudo mostrar la verificación bancaria. El pago sigue pendiente; no vuelvas a pagar.";
        });
      } catch (error) {
        checkoutError.textContent = "El pago sigue pendiente de confirmación. No vuelvas a pagar.";
      }
    }
    clearTimeout(temporizadorEstadoPago);
    let consultas = 0;
    async function consultar() {
      if (modalCheckout.classList.contains("hidden") || ordenPendiente !== orden) return;
      try {
        const response = await fetch(`/api/checkout/estado/${encodeURIComponent(orden.orden_id)}`, {
          headers: window.FarmaPulseAuth.headersAuth(),
        });
        const data = await response.json();
        if (data.estado === "aprobado" || data.estado === "rechazado") {
          mostrarResultadoPago(data);
          ordenPendiente = pagoPendiente = null;
          return;
        }
      } catch (error) { /* El webhook puede confirmar el pago aunque falle esta consulta. */ }
      if (++consultas < 100) temporizadorEstadoPago = window.setTimeout(consultar, 4000);
    }
    temporizadorEstadoPago = window.setTimeout(consultar, 4000);
  }

  btnComprar.addEventListener("click", abrirCheckout);
  document.querySelectorAll("[data-cerrar-checkout]").forEach((el) =>
    el.addEventListener("click", cerrarCheckout)
  );

  async function prepararTarjetaPago() {
    if (cobroEnCurso || pagoSinConfirmar || carrito.length === 0) return;
    checkoutError.classList.add("hidden");
    checkoutError.classList.remove("border-green-200", "bg-green-50", "text-green-700");
    checkoutError.classList.add("border-red-200", "bg-red-50", "text-red-700");
    await cargaConfigServicio;
    if (cobroEnCurso || modalCheckout.classList.contains("hidden")) return;
    if (!configServicio.pasarela_configurada || !configServicio.mercado_pago_public_key) {
      checkoutError.textContent = "Mercado Pago todavía no está configurado. Contacta a soporte.";
      checkoutError.classList.remove("hidden");
      return;
    }
    if (!window.MercadoPago || !window.FarmaPulseMercadoPago) {
      checkoutError.textContent = "No se pudo cargar Mercado Pago. Recarga la página.";
      checkoutError.classList.remove("hidden");
      return;
    }
    cobroEnCurso = true;
    const versionActual = ++versionCheckout;
    btnPagarMercadoPago.disabled = true;
    btnPagarMercadoPago.textContent = "Preparando pago...";
    const leerDatosCheckout = () => ({
      apellidos: checkoutApellidos.value.trim(), nombres: checkoutNombres.value.trim(),
      dni: checkoutDni.value.trim(), telefono: checkoutTelefono.value.trim(), distrito: checkoutDistrito.value,
      direccion: checkoutDireccion.value.trim(), place_id: checkoutPlaceId.value,
      direccion_validacion: checkoutDireccionValidacion.value, productos: carrito.map((item) => ({ ...item })),
    });
    let datosCheckout;
    async function actualizarPreciosCarrito() {
      const anterior = JSON.stringify(carrito);
      const response = await fetch("/api/checkout/cotizar", {
        method: "POST", headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
        body: JSON.stringify({ productos: carrito.map((item) => ({ ...item })) }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "No pudimos preparar tu compra. Intenta nuevamente.");
      if (versionActual !== versionCheckout || anterior !== JSON.stringify(carrito)) {
        throw new Error("El carrito cambió mientras preparábamos el pago. Revisa el resumen y continúa.");
      }
      carrito = data.productos;
      guardarCarritoStorage(carrito);
      renderizarCarrito();
      actualizarBotonesFilaSegunCarrito();
      renderizarResumenCheckout();
    }
    async function prepararOrden() {
      if (![checkoutDni, checkoutApellidos, checkoutNombres, checkoutTelefono, checkoutDistrito, checkoutDireccion].every((campo) => campo.reportValidity())) {
        throw new Error("Completa tus datos de entrega antes de pagar.");
      }
      if (!checkoutPlaceId.value || !checkoutDireccionValidacion.value) {
        throw new Error("Marca el punto exacto de entrega dentro de la zona de reparto.");
      }
      cobroEnCurso = true;
      datosCheckout = leerDatosCheckout();
      const response = await fetch("/api/checkout/orden", {
        method: "POST", headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
        body: JSON.stringify(datosCheckout),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "No se pudo preparar el pago");
      return data;
    }
    try {
      await actualizarPreciosCarrito();
      let orden;
      const importeMostrado = Math.round((totalCarrito() + Number(configServicio.costo_delivery || 0)) * 100);
      if (!checkoutMercadoPago) checkoutMercadoPago = new window.FarmaPulseMercadoPago(configServicio.mercado_pago_public_key);
      tarjetaMercadoPago.classList.remove("hidden");
      estadoMercadoPago.classList.add("hidden");
      await checkoutMercadoPago.mount(importeMostrado / 100, window.FarmaPulseAuth.obtenerCorreoActivo(), async (formData, additionalData) => {
        if (pagoSinConfirmar || versionActual !== versionCheckout || carrito.length === 0) return;
        cobroEnCurso = true;
        btnPagarMercadoPago.disabled = true;
        try {
          if (!orden || JSON.stringify(datosCheckout) !== JSON.stringify(leerDatosCheckout())) {
            throw new Error("Los datos del pedido cambiaron. Revísalos y vuelve a pulsar Pagar.");
          }
          let response, data;
          try {
            response = await fetch("/api/checkout/pagar", {
              method: "POST", headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
              body: JSON.stringify({ ...datosCheckout, orden_firma: orden.orden_firma,
                token: formData.token, payment_method_id: formData.payment_method_id,
                payment_type_id: additionalData?.paymentTypeId,
                issuer_id: formData.issuer_id, installments: formData.installments,
              }),
            });
            data = await response.json();
          } catch (error) {
            mostrarResultadoPago({ estado: "sin_confirmar", error: `No se recibió la confirmación. No repitas el pago; contacta a soporte con la referencia ${orden.orden_id}.` });
            return;
          }
          if (mostrarResultadoPago(data)) return;
          if (data.estado === "pendiente" && data.pago_id) {
            await iniciarSeguimientoPago(orden, data);
          } else if (!pagoSinConfirmar) {
            orden = null;
          }
        } catch (error) {
          checkoutError.textContent = error.message;
          checkoutError.classList.remove("hidden");
        } finally {
          cobroEnCurso = false;
          btnPagarMercadoPago.disabled = pagoSinConfirmar || carrito.length === 0;
        }
      }, (error) => {
        cobroEnCurso = false;
        checkoutError.textContent = error?.message || "No se pudo completar el pago. Revisa los datos de la tarjeta e inténtalo nuevamente.";
        checkoutError.classList.remove("hidden");
      }, async () => {
        orden = await prepararOrden();
        if (orden.amount !== importeMostrado) throw new Error("El total cambió. Vuelve a abrir el pedido para revisar el importe antes de pagar.");
        return orden.pagador;
      });
      btnPagarMercadoPago.classList.add("hidden");
    } catch (error) {
      checkoutError.textContent = error.message;
      checkoutError.classList.remove("hidden");
    } finally {
      cobroEnCurso = false;
      btnPagarMercadoPago.disabled = pagoSinConfirmar;
    }
  }


  // -------------------------------------------------------
  // Cargar la configuración de pago y delivery.
  // -------------------------------------------------------
  async function cargarConfigServicio() {
    try {
      const respuesta = await fetch("/api/config");
      const data = await respuesta.json();
      if (data.ok) {
        configServicio = {
          mercado_pago_public_key: data.mercado_pago_public_key || "",
          pasarela_configurada: data.pasarela_configurada === true,
          geocodificador_configurado: data.geocodificador_configurado === true,
          zona_delivery: data.zona_delivery || configServicio.zona_delivery,
          tiempo_delivery_minutos: data.tiempo_delivery_minutos || configServicio.tiempo_delivery_minutos,
          costo_delivery: data.costo_delivery != null ? data.costo_delivery : configServicio.costo_delivery,
        };
      }
    } catch (error) {
      console.warn("[FarmaPulse] No se pudo cargar /api/config, se usan valores por defecto:", error);
    }
  }

  const cargaConfigServicio = cargarConfigServicio();
  renderizarCarrito();
})();
