/* =========================================================
   FarmaPulse - auth.js
   Módulo de autenticación (Supabase Auth vía endpoints Flask).
   ========================================================= */

(function () {
  "use strict";

  const CLAVE_SESION = "farmapulse_sesion";
  const CLAVE_USUARIO_ANONIMO = "farmapulse_usuario_id";
  const CLAVE_RECUPERACION = "farmapulse_recuperacion";
  let sesionRecuperacion = null;

  function obtenerSesion() {
    try {
      const cruda = sessionStorage.getItem(CLAVE_SESION) || localStorage.getItem(CLAVE_SESION);
      const sesion = cruda ? JSON.parse(cruda) : null;
      if (sesion?.access_token) {
        guardarSesion(sesion);
        localStorage.removeItem(CLAVE_SESION);
      }
      return sesion;
    } catch {
      return null;
    }
  }

  function guardarSesion(sesion) {
    // No conservo el refresh token ni dejo sesiones permanentes en el navegador.
    sessionStorage.setItem(CLAVE_SESION, JSON.stringify({ access_token: sesion.access_token, usuario: sesion.usuario }));
  }

  function borrarSesion() {
    localStorage.removeItem(CLAVE_SESION);
    sessionStorage.removeItem(CLAVE_SESION);
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
  const modalRecuperarCuenta = document.getElementById("modalRecuperarCuenta");
  const modalNuevaContrasena = document.getElementById("modalNuevaContrasena");
  const formLogin = document.getElementById("formLogin");
  const formRegistro = document.getElementById("formRegistro");
  const formEliminarCuenta = document.getElementById("formEliminarCuenta");
  const formRecuperarCuenta = document.getElementById("formRecuperarCuenta");
  const formNuevaContrasena = document.getElementById("formNuevaContrasena");

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

  function limpiarRecuperacion() {
    sesionRecuperacion = null;
    try { sessionStorage.removeItem(CLAVE_RECUPERACION); } catch { /* almacenamiento no disponible */ }
    formNuevaContrasena?.reset();
    cerrarModal(modalNuevaContrasena);
  }

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
    const parametros = new URLSearchParams(window.location.hash.slice(1));
    let tipo = parametros.get("type");
    let accessToken = parametros.get("access_token");
    let refreshToken = parametros.get("refresh_token");
    const errorCodigo = parametros.get("error_code");
    const errorDescripcion = parametros.get("error_description");

    if (errorCodigo || errorDescripcion) {
      window.history.replaceState(null, document.title, `${window.location.pathname}${window.location.search}`);
      limpiarRecuperacion();
      abrirModal(modalLogin);
      mostrarErrorFormulario(
        formLogin,
        errorCodigo === "otp_expired"
          ? "El enlace venció o ya fue utilizado. Solicita un nuevo correo de confirmación o recuperación."
          : "No se pudo validar el enlace. Solicita un nuevo correo de confirmación o recuperación.",
        false,
      );
      return true;
    }

    if (!window.location.hash) {
      try {
        const pendiente = JSON.parse(sessionStorage.getItem(CLAVE_RECUPERACION) || "null");
        if (pendiente?.access_token && pendiente?.refresh_token) {
          accessToken = pendiente.access_token;
          refreshToken = pendiente.refresh_token;
          tipo = "recovery";
        }
      } catch { limpiarRecuperacion(); }
    }
    if (!accessToken || !refreshToken || !["signup", "recovery"].includes(tipo)) return false;

    window.history.replaceState(null, document.title, `${window.location.pathname}${window.location.search}`);
    try {
      const respuesta = await fetch("/api/auth/sesion", {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const data = await leerRespuestaJson(respuesta);
      if (!respuesta.ok || !data.autenticado || !data.usuario) {
        throw new Error(tipo === "recovery"
          ? "El enlace de recuperación venció o no es válido. Solicita otro desde «Olvidé mi contraseña»."
          : "El correo se confirmó, pero no se pudo iniciar la sesión automáticamente. Inicia sesión para continuar.");
      }

      if (tipo === "recovery") {
        borrarSesion();
        actualizarNavbar();
        window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
        sesionRecuperacion = { access_token: accessToken, refresh_token: refreshToken, usuario: data.usuario };
        try { sessionStorage.setItem(CLAVE_RECUPERACION, JSON.stringify(sesionRecuperacion)); } catch { /* se conserva en memoria */ }
        [modalLogin, modalRegistro, modalRecuperarCuenta, modalEliminarCuenta].forEach(cerrarModal);
        limpiarErrorFormulario(formNuevaContrasena);
        abrirModal(modalNuevaContrasena);
        formNuevaContrasena.querySelector('[name="password"]').focus();
        return true;
      }
      limpiarRecuperacion();
      guardarSesion({ access_token: accessToken, refresh_token: refreshToken, usuario: data.usuario });
      actualizarNavbar();
      window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
      mostrarAvisoConfirmacion("Correo confirmado. Tu sesión ya está iniciada.");
    } catch (error) {
      limpiarRecuperacion();
      abrirModal(modalLogin);
      mostrarErrorFormulario(formLogin, error.message, false);
    }
    return true;
  }

  btnAbrirLogin?.addEventListener("click", () => abrirModal(modalLogin));
  btnAbrirRegistro?.addEventListener("click", () => abrirModal(modalRegistro));

  document.querySelectorAll("[data-recuperar-contrasena]").forEach((button) => {
    button.addEventListener("click", () => {
      formRecuperarCuenta.querySelector('[name="email"]').value = formLogin.querySelector('[name="email"]').value.trim();
      limpiarErrorFormulario(formRecuperarCuenta);
      cerrarModal(modalLogin);
      abrirModal(modalRecuperarCuenta);
    });
  });

  formRecuperarCuenta?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = formRecuperarCuenta.querySelector('button[type="submit"]');
    if (button.disabled) return;
    limpiarErrorFormulario(formRecuperarCuenta);
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Solicitando enlace…";
    try {
      const response = await fetch("/api/auth/recuperar-contrasena", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: formRecuperarCuenta.querySelector('[name="email"]').value.trim() }),
      });
      const data = await leerRespuestaJson(response);
      if (!response.ok || !data.ok) throw new Error(data.error || "No se pudo solicitar la recuperación");
      mostrarErrorFormulario(formRecuperarCuenta, data.mensaje, true);
    } catch (error) {
      mostrarErrorFormulario(formRecuperarCuenta, error.message, false);
    } finally {
      button.textContent = "Espera un minuto para volver a solicitarlo";
      window.setTimeout(() => { button.disabled = false; button.textContent = original; }, 60000);
    }
  });

  document.querySelectorAll("[data-cancelar-recuperacion]").forEach((button) => {
    button.addEventListener("click", () => { limpiarRecuperacion(); abrirModal(modalLogin); });
  });

  formNuevaContrasena?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = formNuevaContrasena.querySelector('button[type="submit"]');
    if (button.disabled) return;
    limpiarErrorFormulario(formNuevaContrasena);
    if (!sesionRecuperacion) {
      mostrarErrorFormulario(formNuevaContrasena, "Solicita otro enlace desde «Olvidé mi contraseña».", false);
      return;
    }
    const password = formNuevaContrasena.querySelector('[name="password"]').value;
    const repetida = formNuevaContrasena.querySelector('[name="password_confirmation"]').value;
    const error = validarContrasena(password) || (password !== repetida ? "Las contraseñas no coinciden." : "");
    if (error) { mostrarErrorFormulario(formNuevaContrasena, error, false); return; }
    const sesion = sesionRecuperacion;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Guardando contraseña…";
    try {
      const response = await fetch("/api/auth/nueva-contrasena", {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${sesion.access_token}` },
        body: JSON.stringify({ password }),
      });
      const data = await leerRespuestaJson(response);
      if (!response.ok || !data.ok) throw new Error(data.error || "No se pudo actualizar la contraseña");
      if (sesionRecuperacion !== sesion) return;
      guardarSesion({ ...sesion, usuario: data.usuario });
      limpiarRecuperacion();
      actualizarNavbar();
      window.dispatchEvent(new CustomEvent("farmapulse:sesion-cambiada"));
      mostrarAvisoConfirmacion("Contraseña actualizada. Tu sesión ya está iniciada.");
    } catch (error) {
      if (sesionRecuperacion === sesion) mostrarErrorFormulario(formNuevaContrasena, error.message, false);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  });

  document.querySelectorAll("[data-reenviar-confirmacion]").forEach((button) => {
    button.addEventListener("click", async () => {
      const form = button.closest("form");
      const input = form.querySelector('[name="email"]');
      if (!input.reportValidity()) return;
      limpiarErrorFormulario(form);
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "Solicitando confirmación…";
      try {
        const response = await fetch("/api/auth/reenviar-confirmacion", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: input.value.trim() }),
        });
        const data = await leerRespuestaJson(response);
        if (!response.ok || !data.ok) throw new Error(data.error || "No se pudo solicitar la confirmación");
        mostrarErrorFormulario(form, data.mensaje, true);
      } catch (error) {
        mostrarErrorFormulario(form, error.message, false);
      } finally {
        button.textContent = "Espera un minuto para reenviar";
        window.setTimeout(() => { button.disabled = false; button.textContent = original; }, 60000);
      }
    });
  });

  document.querySelectorAll("[data-cerrar-modal]").forEach((el) =>
    el.addEventListener("click", () => {
      cerrarModal(modalLogin);
      cerrarModal(modalRegistro);
      cerrarModal(modalEliminarCuenta);
      cerrarModal(modalRecuperarCuenta);
    })
  );
  document.querySelectorAll("[data-cambiar-a-registro]").forEach((el) =>
    el.addEventListener("click", () => { cerrarModal(modalLogin); abrirModal(modalRegistro); })
  );
  document.querySelectorAll("[data-cambiar-a-login]").forEach((el) =>
    el.addEventListener("click", () => { cerrarModal(modalRegistro); cerrarModal(modalRecuperarCuenta); abrirModal(modalLogin); })
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
        mostrarErrorFormulario(formRegistro, "Revisa tu correo para confirmar la cuenta. Si ya la confirmaste anteriormente, inicia sesión.", true);
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

  async function iniciarAutenticacion() {
    const enlaceProcesado = await procesarConfirmacionCorreo();
    if (!enlaceProcesado) await verificarSesionVigente();
  }
  iniciarAutenticacion();
})();
