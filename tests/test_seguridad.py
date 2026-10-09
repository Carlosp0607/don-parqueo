"""Pruebas de la autenticación. No necesitan base de datos.

Verifican las tres garantías del aislamiento multiempresa:
  1. Ninguna petición avanza sin token válido.
  2. Ninguna petición avanza sin id_empresa.
  3. El rol invitado del modo demostración no puede escribir.

Ejecutar:  pytest
"""
import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app import config
from app.seguridad import ApiError, Usuario, solo_admin, usuario_actual

# App mínima que usa las mismas dependencias que la API real.
app = FastAPI()


@app.exception_handler(ApiError)
async def _error(request, e):
    return JSONResponse({"success": False, "message": e.mensaje}, status_code=e.status)


@app.api_route("/protegida", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def protegida(u: Usuario = Depends(usuario_actual)):
    return {"id_empresa": u.id_empresa}


@app.get("/solo-admin")
def admin(u: Usuario = Depends(solo_admin)):
    return {"ok": True}


cliente = TestClient(app)

USUARIO_VALIDO = {"id_usuario": 7, "id_empresa": 3, "rol": "admin", "nombre": "Operador Prueba"}
INVITADO = {"id_usuario": 99, "id_empresa": 1, "rol": "invitado", "nombre": "Invitado"}


def firmar(carga, clave=None):
    return jwt.encode(carga, clave or config.JWT_SECRET, algorithm="HS256")


def pedir(token=None, metodo="GET", ruta="/protegida"):
    cabeceras = {"Authorization": f"Bearer {token}"} if token else {}
    return cliente.request(metodo, ruta, headers=cabeceras)


# 1. Autenticación

def test_sin_token_se_rechaza_con_401():
    r = pedir()
    assert r.status_code == 401
    assert r.json()["success"] is False


def test_token_firmado_con_otra_clave_se_rechaza():
    assert pedir(firmar(USUARIO_VALIDO, "clave-de-un-atacante")).status_code == 401


def test_token_valido_deja_pasar():
    assert pedir(firmar(USUARIO_VALIDO)).status_code == 200


# 2. Aislamiento por empresa

def test_token_sin_id_empresa_no_avanza():
    r = pedir(firmar({"id_usuario": 7, "rol": "admin", "nombre": "Sin empresa"}))
    assert r.status_code == 401
    assert "Token incompleto" in r.json()["message"]


def test_id_empresa_del_token_queda_disponible():
    assert pedir(firmar(USUARIO_VALIDO)).json()["id_empresa"] == 3


def test_token_sin_usuario_no_avanza():
    assert pedir(firmar({"id_empresa": 3, "rol": "admin"})).status_code == 401


# 3. Modo demostración: el invitado solo lee

def test_invitado_puede_consultar():
    assert pedir(firmar(INVITADO), "GET").status_code == 200


@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE"])
def test_invitado_no_puede_escribir(metodo):
    assert pedir(firmar(INVITADO), metodo).status_code == 403


def test_usuario_normal_puede_escribir():
    assert pedir(firmar(USUARIO_VALIDO), "POST").status_code == 200


# 4. Rol de administrador

def test_solo_admin_bloquea_al_operador():
    operador = {**USUARIO_VALIDO, "rol": "operador"}
    assert pedir(firmar(operador), ruta="/solo-admin").status_code == 403


def test_solo_admin_deja_pasar_al_administrador():
    assert pedir(firmar(USUARIO_VALIDO), ruta="/solo-admin").status_code == 200
