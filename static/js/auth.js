/* =========================================================
   FarmaPulse - auth.js
   Módulo de autenticación (Supabase Auth vía endpoints Flask).
   ========================================================= */

(function () {
  "use strict";

  const CLAVE_SESION = "farmapulse_sesion";
  const CLAVE_USUARIO_ANONIMO = "farmapulse_usuario_id";

  function obtenerSesion() {
    try {
      const cruda = localStorage.getItem(CLAVE_SESION);
      return cruda ? JSON.parse(cruda) : null;
    } catch {
      return null;
    }
  }

  function guardarSesion(sesion) {
    localStorage.setItem(CLAVE_SESION, JSON.stringify(sesion));
  }

  function borrarSesion() {
    localStorage.removeItem(CLAVE_SESION);
  }

  function obtenerUsuarioAnonimo() {
    let id = localStorage.getItem(CLAVE_USUARIO_ANONIMO);
    if (!id) {
      id = "usr_" + Math.random().toString(36).slice(2, 11);
      localStorage.setItem(CLAVE_USUARIO_ANONIMO, id);
    }
    return id;
  }

  const csrfHeaders = () => ({
    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
  });

  window.FarmaPulseAuth = {
    csrfHeaders,
    estaAutenticado: () => !!obtenerSesion()?.access_token,
    obtenerAccessToken: () => obtenerSesion()?.access_token || null,
    obtenerUsuarioIdActivo: () => obtenerSesion()?.usuario?.id || obtenerUsuarioAnonimo(),
    obtenerCorreoActivo: () => obtenerSesion()?.usuario?.email || null,
    headersAuth: () => {
      const token = obtenerSesion()?.access_token;
      return { ...csrfHeaders(), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    },
  };

  const btnAbrirLogin = document.getElementById("btnAbrirLogin");
  const btnAbrirRegistro = document.getElementById("btnAbrirRegistro");
  const btnCerrarSesion = document.getElementById("btnCerrarSesion");
  const bloqueInvitado = document.getElementById("navAuthInvitado");
  const bloqueAutenticado = document.getElementById("navAuthAutenticado");
  const spanCorreoUsuario = document.getElementById("navCorreoUsuario");

  const modalLogin = document.getElementById("modalLogin");
  const modalRegistro = document.getElementById("modalRegistro");
  const formLogin = document.getElementById("formLogin");
  const formRegistro = document.getElementById("formRegistro");

  if (!bloqueInvitado || !bloqueAutenticado) return;

  function actualizarNavbar() {
    const autenticado = window.FarmaPulseAuth.estaAutenticado();
    bloqueInvitado.classList.toggle("hidden", autenticado);
    bloqueAutenticado.classList.toggle("hidden", !autenticado);
    if (autenticado && spanCorreoUsuario) {
      spanCorreoUsuario.textContent = window.FarmaPulseAuth.obtenerCorreoActivo() || "Mi cuenta";
    }
  }

  function abrirModal(modal) { if (modal) modal.classList.remove("hidden"); }
  function cerrarModal(modal) { if (modal) modal.classList.add("hidden"); }

  function mostrarErrorFormulario(form, mensaje, esExito) {
    const contenedor = form.querySelector("[data-error]");
    if (!contenedor) return;
    contenedor.textContent = mensaje;
    contenedor.classList.remove("hidden", "text-red-500", "bg-red-50", "border-red-100", "text-fpGreenDark", "bg-fpMint", "border-fpGreen/30");
    if (esExito) {
      contenedor.classList.add("text-fpGreenDark", "bg-fpMint", "border-fpGreen/30");
    } else {
      contenedor.classList.add("text-red-500", "bg-red-50", "border-red-100");
    }
  }

  function limpiarErrorFormulario(form) {
    const contenedor = form.querySelector("[data-error]");
    if (contenedor) {
      contenedor.textContent = "";
      contenedor.classList.add("hidden");
    }
  }

  btnAbrirLogin?.addEventListener("click", () => abrirModal(modalLogin));
  btnAbrirRegistro?.addEventListener("click", () => abrirModal(modalRegistro));

  document.querySelectorAll("[data-cerrar-modal]").forEach((el) =>
    el.addEventListener("click", () => { cerrarModal(modalLogin); cerrarModal(modalRegistro); })
  );
  document.querySelectorAll("[data-cambiar-a-registro]").forEach((el) =>
    el.addEventListener("click", () => { cerrarModal(modalLogin); abrirModal(modalRegistro); })
  );
  document.querySelectorAll("[data-cambiar-a-login]").forEach((el) =>
    el.addEventListener("click", () => { cerrarModal(modalRegistro); abrirModal(modalLogin); })
  );

  formRegistro?.addEventListener("submit", async (e) => {
    e.preventDefault();
    limpiarErrorFormulario(formRegistro);

    const email = formRegistro.querySelector('[name="email"]').value.trim();
    const password = formRegistro.querySelector('[name="password"]').value;
    const btn = formRegistro.querySelector('button[type="submit"]');

    btn.disabled = true;
    const textoOriginal = btn.textContent;
    btn.textContent = "Creando cuenta...";

    try {
      const respuesta = await fetch("/api/auth/registro", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ email, password }),
      });
      const data = await respuesta.json();
      if (!data.ok) throw new Error(data.error || "No se pudo crear la cuenta");

      if (data.requiere_confirmacion) {
        mostrarErrorFormulario(formRegistro, "¡Cuenta creada! Revisa tu correo para confirmarla antes de iniciar sesión.", true);
      } else {
        guardarSesion({ access_token: data.access_token, usuario: data.usuario });
        actualizarNavbar();
        cerrarModal(modalRegistro);
        formRegistro.reset();
        window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
      }
    } catch (error) {
      mostrarErrorFormulario(formRegistro, error.message, false);
    } finally {
      btn.disabled = false;
      btn.textContent = textoOriginal;
    }
  });

  formLogin?.addEventListener("submit", async (e) => {
    e.preventDefault();
    limpiarErrorFormulario(formLogin);

    const email = formLogin.querySelector('[name="email"]').value.trim();
    const password = formLogin.querySelector('[name="password"]').value;
    const btn = formLogin.querySelector('button[type="submit"]');

    btn.disabled = true;
    const textoOriginal = btn.textContent;
    btn.textContent = "Ingresando...";

    try {
      const respuesta = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ email, password }),
      });
      const data = await respuesta.json();
      if (!data.ok) throw new Error(data.error || "No se pudo iniciar sesión");

      guardarSesion({ access_token: data.access_token, usuario: data.usuario });
      actualizarNavbar();
      cerrarModal(modalLogin);
      formLogin.reset();
      window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
    } catch (error) {
      mostrarErrorFormulario(formLogin, error.message, false);
    } finally {
      btn.disabled = false;
      btn.textContent = textoOriginal;
    }
  });

  btnCerrarSesion?.addEventListener("click", async () => {
    const token = window.FarmaPulseAuth.obtenerAccessToken();
    borrarSesion();
    actualizarNavbar();
    window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
    if (token) {
      try {
        await fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}`, ...csrfHeaders() } });
      } catch { /* best-effort */ }
    }
  });

  async function verificarSesionVigente() {
    const sesion = obtenerSesion();
    if (!sesion?.access_token) { actualizarNavbar(); return; }
    try {
      const respuesta = await fetch("/api/auth/sesion", { headers: { Authorization: `Bearer ${sesion.access_token}` } });
      const data = await respuesta.json();
      if (!data.autenticado) borrarSesion();
    } catch { /* sin conexión: se mantiene la sesión local optimistamente */ }
    actualizarNavbar();
  }

  verificarSesionVigente();
})();
