/* FarmaPulse - panel de administración.
   La autorización real la hace el servidor en /api/admin/compras (sesión Bearer + rol).
   Este archivo solo muestra lo que el servidor decide devolver. Sin HTML dinámico: todo con textContent. */
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    const $ = (id) => document.getElementById(id);
    const ESTADOS = { approved: "Aprobado", pending: "Pendiente", processing: "Procesando", unknown: "Sin confirmar", rejected: "Rechazado" };
    const ORDEN_INICIAL = { fecha: "fecha_desc", producto: "producto_asc", cantidad: "cantidad_desc", importe: "importe_desc" };
    const estado = { pagina: 1, orden: "fecha_desc" };
    let graficoTiempo = null, graficoProductos = null, temporizador = null;

    const soles = (v) => "S/ " + (Number(v) || 0).toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const entero = (v) => (Number(v) || 0).toLocaleString("es-PE");
    const el = (tag, clase, texto) => { const n = document.createElement(tag); if (clase) n.className = clase; if (texto != null) n.textContent = texto; return n; };
    const fechaLima = (iso) => {
      const d = iso ? new Date(iso) : null;
      return d && !isNaN(d) ? d.toLocaleString("es-PE", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Lima" }) : "Sin fecha registrada";
    };

    function mostrarPuerta(titulo, texto, boton) {
      $("admPanel").hidden = true;
      $("admPuerta").hidden = false;
      $("admPuertaTitulo").textContent = titulo;
      $("admPuertaTexto").textContent = texto;
      const b = $("admPuertaBoton");
      b.hidden = !boton;
      if (boton) { b.textContent = boton.texto; b.onclick = boton.accion; }
    }
    function limpiarDatos() {
      $("admFilas").replaceChildren();
      ["admCompras", "admIngresos", "admUnidades", "admTicket"].forEach((id) => { $(id).textContent = "—"; });
      $("admEstados").replaceChildren();
      graficoTiempo?.destroy(); graficoProductos?.destroy(); graficoTiempo = graficoProductos = null;
    }
    function pedirLogin(texto) {
      limpiarDatos();
      mostrarPuerta("Inicia sesión como administrador", texto || "Usa la cuenta administradora para ver compras e ingresos.",
        { texto: "Iniciar sesión", accion: () => document.getElementById("btnAbrirLogin")?.click() });
    }
    const mostrarError = (m) => { $("admError").textContent = m || ""; $("admError").hidden = !m; };

    function parametros() {
      const p = new URLSearchParams();
      const campos = { desde: $("admDesde").value, hasta: $("admHasta").value, estado: $("admEstado").value, q: $("admBuscar").value.trim(), orden: estado.orden };
      Object.entries(campos).forEach(([k, v]) => { if (v) p.set(k, v); });
      p.set("pagina", String(estado.pagina));
      return p;
    }

    let solicitud = 0;
    async function cargar() {
      const auth = window.FarmaPulseAuth;
      if (!auth?.obtenerAccessToken()) { pedirLogin(); return; }
      const mia = ++solicitud;
      $("admSeccionTabla").classList.add("adm-loading");
      try {
        const r = await fetch("/api/admin/compras?" + parametros(), { headers: auth.headersAuth() });
        if (mia !== solicitud) return;
        let data = null;
        try { data = await r.json(); } catch { /* respuesta no JSON */ }
        if (r.status === 401) { pedirLogin("Tu sesión no es válida o venció. Inicia sesión de nuevo."); return; }
        if (r.status === 403) { limpiarDatos(); mostrarPuerta("Acceso restringido", "Esta sección es solo para la cuenta administradora.", { texto: "Volver al inicio", accion: () => window.location.assign("/") }); return; }
        if (!r.ok || !data?.ok) { mostrarError(data?.error || "No se pudo cargar el historial. Intenta nuevamente."); return; }
        $("admPuerta").hidden = true; $("admPanel").hidden = false;
        mostrarError("");
        pintar(data);
      } catch {
        if (mia === solicitud) { $("admPanel").hidden ? mostrarPuerta("Sin conexión", "No se pudo contactar al servidor.", { texto: "Reintentar", accion: cargar }) : mostrarError("No se pudo contactar al servidor."); }
      } finally {
        if (mia === solicitud) $("admSeccionTabla").classList.remove("adm-loading");
      }
    }

    function pintar(d) {
      const r = d.resumen;
      $("admCompras").textContent = entero(r.compras_aprobadas);
      $("admRegistros").textContent = `${entero(r.registros)} registro(s) en total`;
      $("admIngresos").textContent = soles(r.ingresos);
      $("admUnidades").textContent = entero(r.unidades);
      $("admTicket").textContent = soles(r.ticket_promedio);

      const tira = $("admEstados"); tira.replaceChildren();
      Object.entries(r.por_estado).forEach(([k, n]) => tira.append(el("span", "adm-pill " + k, `${ESTADOS[k] || k}: ${entero(n)}`)));

      const avisos = [];
      if (r.ilegibles) avisos.push(`${r.ilegibles} registro(s) no se pudieron descifrar (¿cambió SECRET_KEY?); se muestran sin cliente ni importe.`);
      if (r.sin_fecha) avisos.push(`${r.sin_fecha} registro(s) antiguos no tienen fecha y no aparecen en los gráficos.`);
      $("admAviso").textContent = avisos.join(" "); $("admAviso").hidden = !avisos.length;

      graficos(d);
      tabla(d);
    }

    function graficos(d) {
      const hayTiempo = d.serie.some((s) => s.compras > 0);
      $("admVacioTiempo").hidden = hayTiempo; $("admGraficoTiempo").parentElement.hidden = !hayTiempo;
      $("admVacioProductos").hidden = d.top_productos.length > 0; $("admGraficoProductos").parentElement.hidden = !d.top_productos.length;
      if (typeof Chart === "undefined") return;
      graficoTiempo?.destroy(); graficoProductos?.destroy(); graficoTiempo = graficoProductos = null;
      if (hayTiempo) {
        graficoTiempo = new Chart($("admGraficoTiempo"), {
          data: {
            labels: d.serie.map((s) => s.dia),
            datasets: [
              { type: "bar", label: "Compras", data: d.serie.map((s) => s.compras), backgroundColor: "rgba(31,169,113,.35)", borderRadius: 4, yAxisID: "y1", order: 2 },
              { type: "line", label: "Ingresos (S/)", data: d.serie.map((s) => Number(s.ingresos)), borderColor: "#0d3b4f", backgroundColor: "#0d3b4f", tension: .3, pointRadius: d.serie.length > 40 ? 0 : 3, yAxisID: "y", order: 1 },
            ],
          },
          options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
            scales: {
              y: { beginAtZero: true, position: "left", ticks: { callback: (v) => "S/ " + v } },
              y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, ticks: { precision: 0 } },
              x: { ticks: { maxTicksLimit: 10 } },
            },
            plugins: { tooltip: { callbacks: { label: (c) => c.dataset.yAxisID === "y" ? `Ingresos: ${soles(c.parsed.y)}` : `Compras: ${c.parsed.y}` } } },
          },
        });
      }
      if (d.top_productos.length) {
        graficoProductos = new Chart($("admGraficoProductos"), {
          type: "bar",
          data: { labels: d.top_productos.map((p) => p.nombre), datasets: [{ label: "Unidades", data: d.top_productos.map((p) => p.unidades), backgroundColor: "#1fa971", borderRadius: 6 }] },
          options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } },
        });
      }
    }

    function tabla(d) {
      const tbody = $("admFilas"); tbody.replaceChildren();
      if (!d.compras.length) {
        const tr = el("tr"), td = el("td", "adm-empty", "No hay compras que coincidan con los filtros."); td.colSpan = 7; tr.append(td); tbody.append(tr);
      }
      d.compras.forEach((c) => {
        const tr = el("tr");
        const tdFecha = el("td", null, fechaLima(c.fecha)); tdFecha.append(el("div", "adm-mono", c.id));
        const tdProd = el("td");
        if (!c.productos.length) tdProd.append(el("span", "adm-sub", "Detalle no disponible"));
        c.productos.forEach((p) => {
          const l = el("div", "adm-line"); l.append(el("strong", null, p.nombre));
          l.append(el("small", null, [p.presentacion, p.farmacia].filter(Boolean).join(" · "))); tdProd.append(l);
        });
        const tdEstado = el("td"); tdEstado.append(el("span", "adm-pill " + c.estado, ESTADOS[c.estado] || c.estado));
        const tdImp = el("td", "adm-num"); tdImp.append(el("strong", null, soles(c.total)));
        tr.append(tdFecha, tdProd, el("td", "adm-num", String(c.unidades)), el("td", null, c.cliente || "—"), el("td", null, c.email || "—"), tdEstado, tdImp);
        tbody.append(tr);
      });
      const pg = d.paginacion; estado.pagina = pg.pagina;
      $("admResumenTabla").textContent = `${entero(pg.total)} registro(s)`;
      $("admPagina").textContent = `Página ${pg.pagina} de ${pg.paginas}`;
      $("admPrev").disabled = pg.pagina <= 1; $("admNext").disabled = pg.pagina >= pg.paginas;
      $("admOrden").value = estado.orden;
      document.querySelectorAll("[data-flecha]").forEach((s) => {
        const base = s.dataset.flecha; s.textContent = estado.orden.startsWith(base + "_") ? (estado.orden.endsWith("_asc") ? "▲" : "▼") : "";
      });
    }

    const recargarDesdePrimera = () => { estado.pagina = 1; cargar(); };
    $("admFiltros").addEventListener("submit", (e) => { e.preventDefault(); recargarDesdePrimera(); });
    $("admLimpiar").addEventListener("click", () => { ["admDesde", "admHasta", "admEstado", "admBuscar"].forEach((id) => { $(id).value = ""; }); estado.orden = "fecha_desc"; recargarDesdePrimera(); });
    $("admRecargar").addEventListener("click", cargar);
    $("admDesde").addEventListener("change", recargarDesdePrimera);
    $("admHasta").addEventListener("change", recargarDesdePrimera);
    $("admEstado").addEventListener("change", recargarDesdePrimera);
    $("admOrden").addEventListener("change", () => { estado.orden = $("admOrden").value; recargarDesdePrimera(); });
    $("admBuscar").addEventListener("input", () => { clearTimeout(temporizador); temporizador = setTimeout(recargarDesdePrimera, 300); });
    $("admPrev").addEventListener("click", () => { estado.pagina = Math.max(1, estado.pagina - 1); cargar(); });
    $("admNext").addEventListener("click", () => { estado.pagina += 1; cargar(); });
    document.querySelectorAll("[data-orden]").forEach((b) => b.addEventListener("click", () => {
      const base = b.dataset.orden;
      estado.orden = estado.orden.startsWith(base + "_")
        ? base + (estado.orden.endsWith("_desc") ? "_asc" : "_desc") : ORDEN_INICIAL[base];
      recargarDesdePrimera();
    }));
    window.addEventListener("farmapulse:sesion-cambiada", cargar);
    cargar();
  });
})();
