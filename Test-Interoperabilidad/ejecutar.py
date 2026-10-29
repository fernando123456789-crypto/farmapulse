"""Ejecuto unittest y registro resultados sin respuestas ni credenciales."""
import json
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent

class Resultado(unittest.TextTestResult):
    registros = []
    def startTest(self, test):
        self.inicio = time.perf_counter()
        super().startTest(test)

    def guardar(self, test, estado, detalle=""):
        self.registros.append({"caso":test.id(), "objetivo":test.shortDescription(), "estado":estado,
                               "segundos":round(time.perf_counter()-getattr(self,"inicio",time.perf_counter()), 3),
                               "consultas":getattr(test,"mediciones",[]), "observacion":detalle})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.guardar(test,"APROBADO")

    def addFailure(self, test, err):
        super().addFailure(test,err)
        self.guardar(test,"FALLO","Una comprobación no cumplió el resultado esperado; reviso la salida local de unittest.")

    def addError(self, test, err):
        super().addError(test,err)
        self.guardar(test,"ERROR",err[0].__name__)

    def addSkip(self, test, reason):
        super().addSkip(test,reason)
        self.guardar(test,"OMITIDO",reason)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2,resultclass=Resultado).run(suite)
    report = {"fecha_utc":datetime.now(timezone.utc).isoformat(),"url":"https://farmapulse.onrender.com",
              "ejecutados":result.testsRun,"fallos":len(result.failures),"errores":len(result.errors),
              "omitidos":len(result.skipped),"casos":result.registros}
    output = ROOT / "resultados"
    output.mkdir(exist_ok=True)
    (output / "ultima_ejecucion.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
