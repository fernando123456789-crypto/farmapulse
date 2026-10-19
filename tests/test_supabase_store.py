"""Pruebas del almacenamiento en Supabase (supabase_store.py) y del envío de correo (mailer.py).

* Las pruebas con ``Mock`` corren siempre y no tocan la red.
* ``SupabaseIntegrationTests`` solo corre si defines FP_TEST_POSTGREST_URL (un PostgREST con el
  esquema de sql/05_pagos_y_seguridad.sql) y FP_TEST_SERVICE_JWT; nunca usa tu proyecto real.
"""

import json
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mailer  # noqa: E402
import supabase_store  # noqa: E402
from supabase_store import StoreError, SupabaseIdentitySecurity, SupabasePaymentLedger, SupabaseRest  # noqa: E402


def respuesta(status=200, cuerpo=None):
    r = Mock(status_code=status)
    r.content = b"" if cuerpo is None else json.dumps(cuerpo).encode()
    r.json.return_value = cuerpo
    return r


class SupabaseRestTests(unittest.TestCase):
    def test_exige_https_y_clave(self):
        with self.assertRaises(ValueError):
            SupabaseRest("http://x.supabase.co", "clave")
        with self.assertRaises(ValueError):
            SupabaseRest("https://x.supabase.co", "")

    def test_clave_nueva_solo_va_en_apikey_y_la_jwt_tambien_en_authorization(self):
        nueva = SupabaseRest("https://x.supabase.co", "sb_secret_prueba")
        self.assertEqual(nueva.headers["apikey"], "sb_secret_prueba")
        self.assertNotIn("Authorization", nueva.headers)
        jwt = SupabaseRest("https://x.supabase.co", "eyJhbGciOi.prueba.firma")
        self.assertEqual(jwt.headers["Authorization"], "Bearer eyJhbGciOi.prueba.firma")

    def test_errores_de_red_y_http_son_store_error_sin_filtrar_el_cuerpo(self):
        sesion = Mock()
        rest = SupabaseRest("https://x.supabase.co", "sb_secret_prueba", session=sesion)
        sesion.request.side_effect = requests.ConnectionError("boom")
        with self.assertRaises(StoreError):
            rest.request("GET", "fp_payments")
        sesion.request.side_effect = None
        sesion.request.return_value = respuesta(401, {"message": "JWT SECRETO filtrado"})
        with self.assertRaises(StoreError) as contexto:
            rest.request("GET", "fp_payments")
        self.assertNotIn("SECRETO", str(contexto.exception))

    def test_reintenta_una_vez_las_lecturas(self):
        sesion = Mock()
        rest = SupabaseRest("https://x.supabase.co", "sb_secret_prueba", session=sesion)
        sesion.request.side_effect = [requests.ConnectionError(), respuesta(200, [])]
        with patch("supabase_store.time.sleep"):
            self.assertEqual(rest.request("GET", "fp_payments", retries=1), [])


class LedgerMockTests(unittest.TestCase):
    def setUp(self):
        self.rest = Mock()
        self.ledger = SupabasePaymentLedger(self.rest, "secreto-de-prueba")

    def test_claim_mapea_cada_resultado_de_la_funcion(self):
        self.rest.rpc.return_value = {"kind": "new"}
        self.assertIsNone(self.ledger.claim("o1", "tok", "", "user"))
        enviados = self.rest.rpc.call_args.args[1]
        self.assertNotIn("tok", enviados.values())          # solo viajan hashes, nunca el token
        self.assertNotIn("user", enviados.values())
        self.rest.rpc.return_value = {"kind": "response", "response": {"ok": True}, "status": 200}
        self.assertEqual(self.ledger.claim("o1", "tok", "", "user"), ({"ok": True}, 200))
        for tipo, estado in (("processing", "procesando"), ("pending", "sin_confirmar"), ("conflict", "conflicto")):
            self.rest.rpc.return_value = {"kind": tipo, "referencia": "o0"}
            cuerpo, status = self.ledger.claim("o1", "tok", "", "user")
            self.assertEqual((cuerpo["estado"], status), (estado, 409))

    def test_finish_no_degrada_una_orden_aprobada(self):
        self.ledger.finish("o1", "rejected", {"ok": False}, 402)
        self.assertIn(("state", "neq.approved"), self.rest.request.call_args.kwargs["params"])
        self.ledger.finish("o1", "approved", {"ok": True}, 200)
        self.assertNotIn(("state", "neq.approved"), self.rest.request.call_args.kwargs["params"])

    def test_el_contexto_se_guarda_cifrado(self):
        self.ledger.set_context("o1", {"email": "cliente@example.com", "cliente": {"dni": "12345678"}})
        guardado = self.rest.request.call_args.kwargs["body"]["context"]
        self.assertTrue(guardado.startswith("fernet:"))
        self.assertNotIn("12345678", guardado)
        self.assertNotIn("cliente@example.com", guardado)

    def test_get_respeta_al_propietario(self):
        contexto = self.ledger._encrypt_context("o1", {"total": "10"})
        self.rest.request.return_value = [{"state": "approved", "response": {"ok": True}, "status": 200,
                                           "context": contexto, "owner_hash": self.ledger._hash("dueño")}]
        self.assertEqual(self.ledger.get("o1", "dueño")["context"], {"total": "10"})
        self.assertIsNone(self.ledger.get("o1", "otro"))

    def test_admin_list_pagina_filtra_y_entrega_formato_del_panel(self):
        contexto = self.ledger._encrypt_context("o1", {"email": "a@b.c", "cliente": {"nombre": "Ana"},
                                                       "productos": [{"medicamento": "Paracetamol", "precio": "5.00"}],
                                                       "subtotal": "5.00", "delivery": "3.00", "total": "8.00"})
        fila = {"order_id": "o1", "state": "approved", "context": contexto, "created_at": "2026-10-18T15:30:00.123456+00:00"}
        with patch.object(supabase_store, "_PAGINA_ADMIN", 2):
            self.rest.request.side_effect = [[fila, fila], [fila]]
            filas = self.ledger.admin_list("2026-10-18 05:00:00", "2026-10-19 05:00:00")
        self.assertEqual(len(filas), 3)
        self.assertEqual(filas[0]["created_at"], "2026-10-18 15:30:00")
        self.assertEqual((filas[0]["cliente"], filas[0]["total"]), ("Ana", "8.00"))
        parametros = self.rest.request.call_args_list[0].kwargs["params"]
        self.assertIn(("created_at", "gte.2026-10-18T05:00:00Z"), parametros)
        self.assertIn(("created_at", "lt.2026-10-19T05:00:00Z"), parametros)

    def test_pending_receipts(self):
        self.rest.request.return_value = [{"order_id": "a", "response": {"comprobante_enviado": True}},
                                          {"order_id": "b", "response": {"comprobante_enviado": False}}]
        self.assertEqual(self.ledger.pending_receipts(), ["b"])


class MailerTests(unittest.TestCase):
    RESEND = {"provider": "resend", "resend_api_key": "re_prueba", "resend_from": "FarmaPulse <onboarding@resend.dev>"}

    def test_proveedor_por_defecto(self):
        self.assertEqual(mailer.proveedor({"resend_api_key": "re_x"}), "resend")
        self.assertEqual(mailer.proveedor({"host": "smtp.gmail.com"}), "smtp")
        self.assertEqual(mailer.proveedor({"provider": "smtp", "resend_api_key": "re_x"}), "smtp")

    def test_configuracion_requerida(self):
        self.assertTrue(mailer.correo_configurado(self.RESEND))
        self.assertFalse(mailer.correo_configurado({"provider": "resend", "resend_api_key": "re_x"}))
        self.assertFalse(mailer.correo_configurado({"provider": "smtp", "host": "h", "username": "u"}))
        with self.assertRaises(mailer.MailError):
            mailer.enviar_correo({"provider": "resend"}, "a@b.c", "x", "y")

    def test_resend_envia_por_https_con_idempotencia(self):
        with patch("mailer.requests.post", return_value=Mock(status_code=200)) as post:
            mailer.enviar_correo(self.RESEND, "cliente@example.com", "Asunto", "Texto", idempotency_key="comprobante-1")
        self.assertEqual(post.call_args.args[0], "https://api.resend.com/emails")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer re_prueba")
        self.assertEqual(post.call_args.kwargs["headers"]["Idempotency-Key"], "comprobante-1")
        self.assertEqual(post.call_args.kwargs["json"], {"from": self.RESEND["resend_from"],
                         "to": ["cliente@example.com"], "subject": "Asunto", "text": "Texto"})

    def test_resend_error_no_filtra_la_clave(self):
        malo = Mock(status_code=403)
        malo.json.return_value = {"message": "You can only send testing emails to your own email address"}
        with patch("mailer.requests.post", return_value=malo):
            with self.assertRaises(mailer.MailError) as contexto:
                mailer.enviar_correo(self.RESEND, "otro@example.com", "A", "B")
        self.assertIn("403", str(contexto.exception))
        self.assertNotIn("re_prueba", str(contexto.exception))
        with patch("mailer.requests.post", side_effect=requests.Timeout()):
            with self.assertRaises(mailer.MailError):
                mailer.enviar_correo(self.RESEND, "a@b.c", "A", "B")

    def test_smtp_sigue_disponible_en_local(self):
        config = {"provider": "smtp", "host": "smtp.example.com", "port": 587, "username": "u", "password": "p", "from": "u@example.com"}
        with patch("mailer.smtplib.SMTP") as smtp:
            mailer.enviar_correo(config, "a@b.c", "Asunto", "Texto")
        servidor = smtp.return_value.__enter__.return_value
        servidor.starttls.assert_called_once()
        servidor.login.assert_called_once_with("u", "p")
        self.assertEqual(servidor.send_message.call_args.args[0]["To"], "a@b.c")


@unittest.skipUnless(os.getenv("FP_TEST_POSTGREST_URL") and os.getenv("FP_TEST_SERVICE_JWT"),
                     "Define FP_TEST_POSTGREST_URL y FP_TEST_SERVICE_JWT para probar contra PostgREST")
class SupabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ["FP_TEST_POSTGREST_URL"].rstrip("/")
        cls.rest = SupabaseRest("https://placeholder.invalid", os.environ["FP_TEST_SERVICE_JWT"])
        cls.rest.base = cls.url          # PostgREST local no usa el prefijo /rest/v1
        for tabla, columna in (("fp_payments", "order_id"), ("fp_identity_attempts", "identifier"),
                               ("fp_revoked_tokens", "token_hash")):
            cls.rest.request("DELETE", tabla, params={columna: "neq.__nada__"})
        cls.ledger = SupabasePaymentLedger(cls.rest, "secreto-de-prueba")
        cls.identity = SupabaseIdentitySecurity(cls.rest, "secreto-de-prueba")

    def test_ciclo_de_pago_aprobado_y_comprobante(self):
        L = self.ledger
        self.assertIsNone(L.claim("fp_ok", "tok-ok", "", "user-ok"))
        L.set_context("fp_ok", {"email": "a@b.c", "cliente": {"nombre": "Ana", "dni": "12345678"},
                                "productos": [{"medicamento": "Paracetamol", "precio": "5.00"}],
                                "subtotal": "5.00", "delivery": "3.00", "total": "8.00"})
        L.set_context("fp_ok", {"email": "otro"})            # no pisa el contexto existente
        self.assertEqual(L.get("fp_ok", "user-ok")["context"]["email"], "a@b.c")
        self.assertIsNone(L.get("fp_ok", "otro-usuario"))
        cuerpo, status = L.claim("fp_ok", "tok-ok", "", "user-ok")      # reintento: aún procesando
        self.assertEqual((cuerpo["estado"], status), ("procesando", 409))
        self.assertEqual(L.claim("fp_ok", "tok-ok", "", "intruso")[0]["estado"], "conflicto")
        respuesta_ok = {"ok": True, "pago_id": "1", "comprobante_enviado": False}
        self.assertEqual(L.settle("fp_ok", "approved", respuesta_ok, 200), (respuesta_ok, 200, True))
        L.finish("fp_ok", "rejected", {"ok": False}, 402)                # no degrada
        self.assertEqual(L.get("fp_ok")["state"], "approved")
        _, _, nueva = L.settle("fp_ok", "rejected", {"ok": False}, 402)
        self.assertFalse(nueva)
        self.assertEqual(L.claim("fp_ok", "tok-ok", "", "user-ok"), (respuesta_ok, 200))
        self.assertIn("fp_ok", L.pending_receipts())
        self.assertTrue(L.claim_receipt("fp_ok"))
        self.assertFalse(L.claim_receipt("fp_ok"))                       # candado de 120 s
        L.release_receipt("fp_ok")
        self.assertTrue(L.claim_receipt("fp_ok"))
        L.release_receipt("fp_ok")
        L.finish("fp_ok", "approved", {**respuesta_ok, "comprobante_enviado": True}, 200)
        self.assertNotIn("fp_ok", L.pending_receipts())
        self.assertFalse(L.claim_receipt("fp_ok"))

    def test_un_comprador_no_puede_tener_dos_pagos_en_curso(self):
        L = self.ledger
        self.assertIsNone(L.claim("fp_a", "tok-a", "", "user-doble"))
        cuerpo, status = L.claim("fp_b", "tok-b", "", "user-doble")
        self.assertEqual((cuerpo["estado"], cuerpo["referencia"], status), ("sin_confirmar", "fp_a", 409))

    def test_admin_list_lee_de_supabase_con_filtros_y_sin_pii(self):
        L = self.ledger
        L.claim("fp_adm", "tok-adm", "", "user-adm")
        L.set_context("fp_adm", {"email": "adm@b.c", "cliente": {"nombre": "Luis", "dni": "87654321", "direccion": "Calle 1"},
                                 "productos": [{"medicamento": "Ibuprofeno", "precio": "10.00"}],
                                 "subtotal": "10.00", "delivery": "3.00", "total": "13.00"})
        L.settle("fp_adm", "approved", {"ok": True}, 200)
        todas = {f["id"]: f for f in L.admin_list()}
        self.assertEqual(todas["fp_adm"]["total"], "13.00")
        self.assertNotIn("87654321", json.dumps(todas["fp_adm"]))
        self.assertNotIn("Calle 1", json.dumps(todas["fp_adm"]))
        self.assertRegex(todas["fp_adm"]["created_at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertEqual([f["id"] for f in L.admin_list("2000-01-01 00:00:00", "2000-01-02 00:00:00")], [])
        with patch.object(supabase_store, "_PAGINA_ADMIN", 1):
            self.assertEqual({f["id"] for f in L.admin_list()}, set(todas))

    def test_bloqueo_de_identidad_tras_cinco_fallos_y_concurrencia(self):
        ids = {"usuario": "u-bloq", "cliente": "c-bloq"}
        self.assertEqual(self.identity.status(ids), {"blocked": False, "remaining": 5})
        self.assertEqual(self.identity.record_failure(ids), {"blocked": False, "remaining": 4})
        for _ in range(4):
            resultado = self.identity.record_failure(ids)
        self.assertEqual(resultado, {"blocked": True, "remaining": 0})
        self.assertEqual(self.identity.status(ids), {"blocked": True, "remaining": 0})
        self.assertEqual(self.identity.status({"usuario": "u-bloq"})["blocked"], True)
        concurrente = {"usuario": "u-conc"}
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda _: self.identity.record_failure(concurrente), range(12)))
        self.assertEqual(self.identity.status(concurrente), {"blocked": True, "remaining": 0})
        self.assertEqual(self.identity.status({}), {"blocked": False, "remaining": 5})

    def test_sesion_revocada(self):
        self.assertFalse(self.identity.token_revoked("token-vivo"))
        self.identity.revoke_token("token-muerto")
        self.assertTrue(self.identity.token_revoked("token-muerto"))
        self.assertFalse(self.identity.token_revoked("token-vivo"))
        guardado = self.rest.request("GET", "fp_revoked_tokens", params={"select": "token_hash"})
        self.assertNotIn("token-muerto", json.dumps(guardado))        # solo se guarda el hash


if __name__ == "__main__":
    unittest.main()
