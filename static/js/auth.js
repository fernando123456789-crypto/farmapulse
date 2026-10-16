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

  window.FarmaPulseAuth = {
    estaAutenticado: () => !!obtenerSesion()?.access_token,
    obtenerAccessToken: () => obtenerSesion()?.access_token || null,
    obtenerUsuarioIdActivo: () => obtenerSesion()?.usuario?.id || obtenerUsuarioAnonimo(),
    obtenerCorreoActivo: () => obtenerSesion()?.usuario?.email || null,
    headersAuth: () => {
      const token = obtenerSesion()?.access_token;
      return token ? { Authorization: `Bearer ${token}` } : {};
    },
  };

  const btnAbrirLogin = document.getElementById("btnAbrirLogin");
  const btnAbrirRegistro = document.getElementById("btnAbrirRegistro");
  const btnCerrarSesion = document.getElementById("btnCerrarSesion");
  const btnEliminarCuenta = document.getElementById("btnEliminarCuenta");
  const bloqueInvitado = document.getElementById("navAuthInvitado");
  const bloqueAutenticado = document.getElementById("navAuthAutenticado");
  const spanCorreoUsuario = document.getElementById("navCorreoUsuario");

  const modalLogin = document.getElementById("modalLogin");
  const modalRegistro = document.getElementById("modalRegistro");
  const modalEliminarCuenta = document.getElementById("modalEliminarCuenta");
  const formLogin = document.getElementById("formLogin");
  const formRegistro = document.getElementById("formRegistro");
  const formEliminarCuenta = document.getElementById("formEliminarCuenta");

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

  function validarContrasena(password) {
    if (password.length < 12) return "La contraseña debe tener al menos 12 caracteres.";
    if (password.length > 128) return "La contraseña no puede exceder 128 caracteres.";
    if (!/[A-Z]/.test(password)) return "La contraseña debe incluir al menos una mayúscula.";
    if (!/[a-z]/.test(password)) return "La contraseña debe incluir al menos una minúscula.";
    if (!/[0-9]/.test(password)) return "La contraseña debe incluir al menos un número.";
    if (![..."!@#$%^&*()_+-=[]{}|;:,.<>?"].some((caracter) => password.includes(caracter))) {
      return "La contraseña debe incluir al menos un símbolo (por ejemplo: ! o #).";
    }
    if (/\s/.test(password)) return "La contraseña no puede contener espacios.";
    return "";
  }

  async function leerRespuestaJson(respuesta) {
    const tipoContenido = respuesta.headers.get("content-type") || "";
    if (!tipoContenido.includes("application/json")) {
      throw new Error("El servidor respondió en un formato inesperado. Intenta nuevamente.");
    }
    try {
      return await respuesta.json();
    } catch {
      throw new Error("No se pudo leer la respuesta del servidor. Intenta nuevamente.");
    }
  }

  function mostrarAvisoConfirmacion(mensaje) {
    const aviso = document.createElement("div");
    aviso.setAttribute("role", "status");
    aviso.setAttribute("aria-live", "polite");
    aviso.className = "fixed top-4 right-4 z-[60] max-w-sm rounded-xl border border-fpGreen/30 bg-fpMint px-5 py-4 text-sm font-semibold text-fpGreenDark shadow-lg";
    aviso.textContent = mensaje;
    document.body.appendChild(aviso);
    window.setTimeout(() => aviso.remove(), 7000);
  }

  async function procesarConfirmacionCorreo() {
    if (!window.location.hash) return;

    const parametros = new URLSearchParams(window.location.hash.slice(1));
    const accessToken = parametros.get("access_token");
    const refreshToken = parametros.get("refresh_token");
    const errorCodigo = parametros.get("error_code");
    const errorDescripcion = parametros.get("error_description");

    if (errorCodigo || errorDescripcion) {
      window.history.replaceState(null, document.title, `${window.location.pathname}${window.location.search}`);
      abrirModal(modalLogin);
      mostrarErrorFormulario(
        formLogin,
        errorCodigo === "otp_expired"
          ? "El enlace de confirmación venció o ya fue utilizado. Solicita uno nuevo e inténtalo otra vez."
          : "No se pudo confirmar el correo. Solicita un nuevo enlace de confirmación.",
        false,
      );
      return;
    }

    if (!accessToken || !refreshToken || parametros.get("type") !== "signup") return;

    window.history.replaceState(null, document.title, `${window.location.pathname}${window.location.search}`);
    try {
      const respuesta = await fetch("/api/auth/sesion", {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const data = await leerRespuestaJson(respuesta);
      if (!data.autenticado || !data.usuario) {
        throw new Error("El correo se confirmó, pero no se pudo iniciar la sesión automáticamente. Inicia sesión para continuar.");
      }

      guardarSesion({ access_token: accessToken, refresh_token: refreshToken, usuario: data.usuario });
      actualizarNavbar();
      window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
      mostrarAvisoConfirmacion("Correo confirmado. Tu sesión ya está iniciada.");
    } catch (error) {
      abrirModal(modalLogin);
      mostrarErrorFormulario(formLogin, error.message, false);
    }
  }

  btnAbrirLogin?.addEventListener("click", () => abrirModal(modalLogin));
  btnAbrirRegistro?.addEventListener("click", () => abrirModal(modalRegistro));

  document.querySelectorAll("[data-cerrar-modal]").forEach((el) =>
    el.addEventListener("click", () => {
      cerrarModal(modalLogin);
      cerrarModal(modalRegistro);
      cerrarModal(modalEliminarCuenta);
    })
  );
  document.querySelectorAll("[data-cambiar-a-registro]").forEach((el) =>
    el.addEventListener("click", () => { cerrarModal(modalLogin); abrirModal(modalRegistro); })
  );
  document.querySelectorAll("[data-cambiar-a-login]").forEach((el) =>
    el.addEventListener("click", () => { cerrarModal(modalRegistro); abrirModal(modalLogin); })
  );

  btnEliminarCuenta?.addEventListener("click", () => {
    limpiarErrorFormulario(formEliminarCuenta);
    formEliminarCuenta?.reset();
    abrirModal(modalEliminarCuenta);
  });

  formEliminarCuenta?.addEventListener("submit", async (e) => {
    e.preventDefault();
    limpiarErrorFormulario(formEliminarCuenta);
    const password = formEliminarCuenta.querySelector('[name="password"]').value;
    const btn = formEliminarCuenta.querySelector('button[type="submit"]');
    const textoOriginal = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Eliminando cuenta...";

    try {
      const respuesta = await fetch("/api/auth/eliminar", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...window.FarmaPulseAuth.headersAuth() },
        body: JSON.stringify({ password }),
      });
      const data = await leerRespuestaJson(respuesta);
      if (!respuesta.ok || !data.ok) throw new Error(data.error || "No se pudo eliminar la cuenta");

      borrarSesion();
      actualizarNavbar();
      cerrarModal(modalEliminarCuenta);
      formEliminarCuenta.reset();
      window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
      mostrarAvisoConfirmacion("Tu cuenta fue eliminada.");
    } catch (error) {
      mostrarErrorFormulario(formEliminarCuenta, error.message, false);
    } finally {
      btn.disabled = false;
      btn.textContent = textoOriginal;
    }
  });

  formRegistro?.addEventListener("submit", async (e) => {
    e.preventDefault();
    limpiarErrorFormulario(formRegistro);

    const email = formRegistro.querySelector('[name="email"]').value.trim();
    const password = formRegistro.querySelector('[name="password"]').value;
    const btn = formRegistro.querySelector('button[type="submit"]');

    const errorContrasena = validarContrasena(password);
    if (errorContrasena) {
      mostrarErrorFormulario(formRegistro, errorContrasena, false);
      return;
    }

    btn.disabled = true;
    const textoOriginal = btn.textContent;
    btn.textContent = "Creando cuenta...";

    try {
      const respuesta = await fetch("/api/auth/registro", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await leerRespuestaJson(respuesta);
      if (!data.ok) throw new Error(data.error || "No se pudo crear la cuenta");

      if (data.requiere_confirmacion) {
        mostrarErrorFormulario(formRegistro, "¡Cuenta creada! Revisa tu correo para confirmarla antes de iniciar sesión.", true);
      } else {
        guardarSesion({ access_token: data.access_token, refresh_token: data.refresh_token, usuario: data.usuario });
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await leerRespuestaJson(respuesta);
      if (!data.ok) throw new Error(data.error || "No se pudo iniciar sesión");

      guardarSesion({ access_token: data.access_token, refresh_token: data.refresh_token, usuario: data.usuario });
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
        await fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
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

  procesarConfirmacionCorreo();
  verificarSesionVigente();
})();
