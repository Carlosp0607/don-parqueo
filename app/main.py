"""Don Parqueo: sistema multiempresa para parqueaderos (FastAPI + PostgreSQL).

Arranque local:  uvicorn app.main:app --reload
"""
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.routers import (auth, dueno, empresa, mensualidades, movimientos, reportes, tarifas,
                         tipos_vehiculos, turnos, usuarios, vehiculos)
from app.seguridad import COOKIE_SESION, ApiError, sesion_de_pagina

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

PUBLIC = Path(__file__).resolve().parent.parent / "public"
NOMBRE_PAGINA = re.compile(r"^[a-zA-Z0-9_-]+$")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.abrir()
    db.migrar_si_hace_falta()
    yield
    db.cerrar()


app = FastAPI(title="Don Parqueo", lifespan=ciclo_de_vida)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --- Errores: el frontend espera siempre {success: false, message} -----------

@app.exception_handler(ApiError)
async def manejar_api_error(request: Request, e: ApiError):
    return JSONResponse({"success": False, "message": e.mensaje, **e.extra}, status_code=e.status)


@app.exception_handler(RequestValidationError)
async def manejar_validacion(request: Request, e: RequestValidationError):
    return JSONResponse({"success": False, "message": "Datos inválidos"}, status_code=400)


@app.exception_handler(Exception)
async def manejar_error(request: Request, e: Exception):
    log.exception("Error no controlado")
    return JSONResponse({"success": False, "message": "Error interno del servidor"}, status_code=500)


# --- Rutas de la API ------------------------------------------------------------

for r in (auth.router, usuarios.router, empresa.router, vehiculos.router, tipos_vehiculos.router,
          movimientos.router, tarifas.router, movimientos.pagos_router, mensualidades.router,
          turnos.router, reportes.dashboard_router, reportes.router, dueno.router):
    app.include_router(r)


@app.get("/api/salud", tags=["salud"])
def salud():
    """Para el ping que mantiene despierto el servicio en el plan gratuito."""
    db.uno("SELECT 1")  # toca la base para que no se apague por inactividad
    return {"success": True, "message": "ok"}


@app.api_route("/api/{ruta:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_no_encontrada(ruta: str):
    return JSONResponse({"success": False, "message": "Endpoint no encontrado"}, status_code=404)


# --- Páginas HTML ------------------------------------------------------------

@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(PUBLIC / "index.html")


@app.get("/gestion-ps-2026", include_in_schema=False)
def panel_dueno():
    # Panel del dueño del SaaS: va fuera de /admin porque no tiene empresa.
    # No muestra nada hasta que la clave se valida contra el servidor.
    return FileResponse(PUBLIC / "gestion-ps-2026.html")


@app.get("/admin/{pagina}", include_in_schema=False)
def pagina_admin(pagina: str, request: Request):
    # Sin cookie de sesión válida, se manda al login en vez de entregar el HTML.
    if sesion_de_pagina(request) is None:
        respuesta = RedirectResponse("/")
        respuesta.delete_cookie(COOKIE_SESION)
        return respuesta

    nombre = re.sub(r"\.html$", "", pagina, flags=re.IGNORECASE)
    archivo = PUBLIC / "admin" / f"{nombre}.html"
    if not NOMBRE_PAGINA.match(nombre) or not archivo.is_file():
        return FileResponse(PUBLIC / "404.html", status_code=404)
    return FileResponse(archivo)


# CSS, JS e imágenes. Va de último para no tapar las rutas de arriba.
app.mount("/", StaticFiles(directory=PUBLIC), name="public")
