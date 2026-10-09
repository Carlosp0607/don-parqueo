import logging
import re

import bcrypt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import config, db
from app.seguridad import COOKIE_SESION, ApiError, firmar_token
from app.utiles import AHORA, HOY

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("auth")

MAX_INTENTOS = 5
DIAS_DE_GRACIA = 5
PATRON_USUARIO = re.compile(r"^[a-zA-Z0-9_.-]+$")


class Login(BaseModel):
    empresa: str | None = None
    usuario: str | None = None
    password: str | None = None


def validar_login(datos: Login):
    usuario, password = (datos.usuario or "").strip(), datos.password or ""
    if not usuario or not password:
        raise ApiError(400, "Todos los campos son obligatorios")
    if not 3 <= len(usuario) <= 50:
        raise ApiError(400, "El usuario debe tener entre 3 y 50 caracteres")
    if len(password) < 6:
        raise ApiError(400, "La contraseña debe tener al menos 6 caracteres")
    if not PATRON_USUARIO.match(usuario):
        raise ApiError(400, "El usuario solo puede contener letras, números, guiones y puntos")
    return (datos.empresa or "").strip(), usuario, password


def ip_cliente(request: Request):
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


def registrar_intento(id_empresa, usuario, exitoso, ip):
    try:
        db.ejecutar(
            "INSERT INTO login_attempts (id_empresa, usuario_login, exitoso, ip_address, fecha_intento) "
            f"VALUES (%s, %s, %s, %s, {AHORA})",
            (id_empresa, usuario, exitoso, ip),
        )
    except Exception as e:
        log.error("No se pudo registrar el intento de login: %s", e)


def intentos_fallidos(id_empresa, usuario, ip):
    """Intentos fallidos de los últimos 15 minutos, por usuario o por IP."""
    fila = db.uno(
        "SELECT COUNT(*) AS n FROM login_attempts "
        "WHERE id_empresa = %s AND (usuario_login = %s OR ip_address = %s) "
        f"AND exitoso = FALSE AND fecha_intento > {AHORA} - INTERVAL '15 minutes'",
        (id_empresa, usuario, ip),
    )
    return fila["n"]


def estado_suscripcion(id_empresa):
    """Reglas del vencimiento del plan:
    - Sin fecha de vencimiento: no se corta nada.
    - Vencida hace 0 a 5 días: entra, pero se le avisa.
    - Vencida hace más de 5 días: no entra.
    """
    fila = db.uno(
        f"SELECT fecha_vencimiento, {HOY} - fecha_vencimiento::date AS dias_vencida "
        "FROM empresas WHERE id_empresa = %s",
        (id_empresa,),
    )
    if not fila or fila["fecha_vencimiento"] is None:
        return {"bloquear": False, "avisar": False}

    dias = int(fila["dias_vencida"])

    if dias < 0:
        faltan = -dias
        return {
            "bloquear": False,
            "avisar": faltan <= 5,
            "mensaje": f"Tu plan vence en {faltan} {'día' if faltan == 1 else 'días'}.",
        }
    if dias == 0:
        return {"bloquear": False, "avisar": True, "mensaje": "Tu plan vence hoy."}
    if dias <= DIAS_DE_GRACIA:
        quedan = DIAS_DE_GRACIA - dias
        return {
            "bloquear": False,
            "avisar": True,
            "mensaje": f"Tu plan está vencido. Tienes {quedan} {'día' if quedan == 1 else 'días'} "
                       "para ponerte al día antes de que se suspenda el acceso.",
        }
    return {
        "bloquear": True,
        "mensaje": "El plan de este parqueadero está vencido y el acceso quedó "
                   "suspendido. Comunícate para reactivarlo.",
    }


@router.get("/demo")
def demo():
    """Credenciales del demo público. Si DEMO_* no está definido, el botón no aparece."""
    if not (config.DEMO_NIT and config.DEMO_USER and config.DEMO_PASS):
        raise ApiError(404, "Demo no disponible")
    return {
        "success": True,
        "data": {"empresa": config.DEMO_NIT, "usuario": config.DEMO_USER, "password": config.DEMO_PASS},
    }


@router.post("/login")
def login(datos: Login, request: Request):
    nit, usuario, password = validar_login(datos)
    ip = ip_cliente(request)

    empresa = db.uno(
        "SELECT id_empresa FROM empresas WHERE nit = %s AND activa = TRUE", (nit,)
    )
    if not empresa:
        raise ApiError(401, "Empresa no encontrada o inactiva")
    id_empresa = empresa["id_empresa"]

    if intentos_fallidos(id_empresa, usuario, ip) >= MAX_INTENTOS:
        registrar_intento(id_empresa, usuario, False, ip)
        raise ApiError(429, "Demasiados intentos fallidos. Por favor, intente más tarde.")

    user = db.uno(
        "SELECT * FROM usuarios WHERE lower(usuario_login) = lower(%s) AND id_empresa = %s AND activo = TRUE",
        (usuario, id_empresa),
    )
    if not user or not bcrypt.checkpw(password.encode(), user["contrasena"].encode()):
        registrar_intento(id_empresa, usuario, False, ip)
        raise ApiError(401, "Usuario o contraseña incorrectos")

    # El vencimiento se revisa DESPUÉS de la contraseña, para no revelarle a un
    # extraño el estado de pago de un parqueadero ajeno solo probando NITs.
    try:
        suscripcion = estado_suscripcion(id_empresa)
    except Exception as e:
        log.error("No se pudo verificar el vencimiento: %s", e)
        suscripcion = {"bloquear": False, "avisar": False}

    if suscripcion["bloquear"]:
        registrar_intento(id_empresa, usuario, False, ip)
        raise ApiError(402, suscripcion["mensaje"], codigo="PLAN_VENCIDO")

    configuracion = db.uno("SELECT * FROM configuracion_empresa WHERE id_empresa = %s", (id_empresa,))

    token = firmar_token({
        "id": user["id_usuario"],
        "nombre": user["nombre"],
        "rol": user["rol"],
        "id_empresa": user["id_empresa"],
        "empresa": {"id_empresa": id_empresa},
    })

    db.ejecutar(f"UPDATE usuarios SET ultimo_acceso = {AHORA} WHERE id_usuario = %s", (user["id_usuario"],))
    registrar_intento(id_empresa, usuario, True, ip)

    respuesta = JSONResponse({
        "success": True,
        "data": {
            "id": user["id_usuario"],
            "nombre": user["nombre"],
            "rol": user["rol"],
            "id_empresa": user["id_empresa"],
            "empresa": {"id_empresa": id_empresa},
            "config": db.fila(configuracion),
            "token": token,
            "aviso_plan": suscripcion.get("mensaje") if suscripcion.get("avisar") else None,
        },
        "message": "Inicio de sesión exitoso",
    })
    # Cookie httpOnly: la usa el servidor para proteger las páginas de /admin.
    respuesta.set_cookie(
        COOKIE_SESION, token, httponly=True, samesite="lax",
        secure=config.PRODUCCION, max_age=config.HORAS_SESION * 3600,
    )
    return respuesta


@router.post("/logout")
def logout():
    respuesta = JSONResponse({"success": True, "message": "Sesión cerrada"})
    respuesta.delete_cookie(COOKIE_SESION)
    return respuesta
