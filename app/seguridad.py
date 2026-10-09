"""Autenticación con JWT, roles y aislamiento por empresa.

Garantías sobre las que se apoya el sistema multiempresa:
  1. Ninguna petición avanza sin token válido.
  2. Ninguna petición avanza sin id_empresa: es lo que impide que una
     consulta se ejecute sin saber a qué empresa pertenece.
  3. El rol invitado del modo demostración no puede escribir.
"""
import datetime as dt
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request

from app import config

METODOS_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}
COOKIE_SESION = "ps_session"


class ApiError(Exception):
    """Error que la API devuelve como {success: false, message}."""

    def __init__(self, status, mensaje, **extra):
        self.status = status
        self.mensaje = mensaje
        self.extra = extra


@dataclass
class Usuario:
    id: int
    id_empresa: int
    rol: str
    nombre: str


def firmar_token(datos):
    carga = dict(datos)
    carga["exp"] = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=config.HORAS_SESION)
    return jwt.encode(carga, config.JWT_SECRET, algorithm=config.JWT_ALGORITMO)


def leer_token(token):
    """Devuelve el Usuario del token o lanza ApiError 401."""
    try:
        datos = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITMO])
    except jwt.PyJWTError:
        raise ApiError(401, "Token inválido o expirado")

    id_usuario = datos.get("id_usuario", datos.get("id"))
    id_empresa = datos.get("id_empresa")
    if not id_usuario or not id_empresa:
        raise ApiError(401, "Token incompleto: vuelva a iniciar sesión")

    return Usuario(id=id_usuario, id_empresa=id_empresa, rol=datos.get("rol"), nombre=datos.get("nombre"))


def usuario_actual(request: Request) -> Usuario:
    """Dependencia de FastAPI: exige token Bearer y bloquea la escritura del invitado."""
    cabecera = request.headers.get("authorization", "")
    token = cabecera[7:].strip() if cabecera.startswith("Bearer ") else None
    if not token:
        raise ApiError(401, "Acceso denegado: Token no proporcionado")

    usuario = leer_token(token)

    if usuario.rol == "invitado" and request.method in METODOS_ESCRITURA:
        raise ApiError(403, "Modo demostración: solo lectura.")

    return usuario


def solo_admin(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    """Dependencia de FastAPI: además del token, exige rol administrador."""
    if usuario.rol != "admin":
        raise ApiError(403, "Acceso denegado: requiere rol de Administrador")
    return usuario


def sesion_de_pagina(request: Request):
    """Para las páginas HTML de /admin: valida la cookie. Devuelve Usuario o None."""
    token = request.cookies.get(COOKIE_SESION)
    if not token:
        return None
    try:
        return leer_token(token)
    except ApiError:
        return None
