import time

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from psycopg import errors

from app import db
from app.seguridad import ApiError, Usuario, solo_admin, usuario_actual
from app.utiles import como_bool, cuerpo_json

router = APIRouter(prefix="/api/empresa", tags=["empresa"])

MIMES_PERMITIDOS = {"image/png", "image/jpeg", "image/jpg", "image/gif"}
TAMANO_MAXIMO = 2 * 1024 * 1024  # 2 MB


def tipo_imagen(datos: bytes):
    """Detecta el tipo de imagen por los primeros bytes."""
    if datos[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if datos[:4] == b"GIF8":
        return "image/gif"
    return "image/png"


def leer_imagen(archivo: UploadFile):
    if archivo is None:
        raise ApiError(400, "Archivo no recibido")
    if archivo.content_type not in MIMES_PERMITIDOS:
        raise ApiError(400, "Tipo de archivo no permitido. Usa PNG o JPG.")
    datos = archivo.file.read(TAMANO_MAXIMO + 1)
    if not datos:
        raise ApiError(400, "Archivo no recibido")
    if len(datos) > TAMANO_MAXIMO:
        raise ApiError(413, "El archivo excede 2MB")
    return datos


@router.get("/me")
def mi_empresa(u: Usuario = Depends(usuario_actual)):
    fila = db.uno(
        "SELECT id_empresa, nombre, nit, direccion, telefono, email, plan, "
        "logo_url IS NOT NULL AS tiene_logo, qr_pago IS NOT NULL AS tiene_qr "
        "FROM empresas WHERE id_empresa = %s AND activa = TRUE",
        (u.id_empresa,),
    )
    if not fila:
        raise ApiError(404, "Empresa no encontrada")
    datos = db.fila(fila)
    # El logo no viaja en este JSON: las pantallas lo piden a /api/empresa/logo.
    datos["logo_url"] = None
    return {"success": True, "data": datos}


@router.get("/config")
def ver_configuracion(u: Usuario = Depends(usuario_actual)):
    fila = db.uno(
        "SELECT id_configuracion, id_empresa, horario_apertura, horario_cierre, "
        "iva_porcentaje, moneda, zona_horaria, operacion_24h "
        "FROM configuracion_empresa WHERE id_empresa = %s",
        (u.id_empresa,),
    )
    if not fila:
        raise ApiError(404, "Configuración no encontrada")
    return {"success": True, "data": db.fila(fila)}


def armar_update(cuerpo: dict, permitidos: dict):
    """Arma el SET solo con los campos que llegaron. Los nombres de columna salen
    de una lista fija, nunca del usuario."""
    campos, valores = [], []
    for nombre, convertir in permitidos.items():
        if cuerpo.get(nombre) is not None:
            campos.append(f"{nombre} = %s")
            valores.append(convertir(cuerpo[nombre]))
    if not campos:
        raise ApiError(400, "Nada para actualizar")
    return ", ".join(campos), valores


@router.put("")
def actualizar_empresa(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    texto = str
    sets, valores = armar_update(cuerpo, {
        "nombre": texto, "nit": texto, "direccion": texto, "telefono": texto, "email": texto,
    })
    try:
        n = db.ejecutar(f"UPDATE empresas SET {sets} WHERE id_empresa = %s", (*valores, u.id_empresa))
    except errors.UniqueViolation:
        raise ApiError(409, "El NIT ya está registrado")
    if n == 0:
        raise ApiError(404, "Empresa no encontrada")
    return {"success": True, "message": "Empresa actualizada"}


@router.put("/config")
def actualizar_configuracion(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    sets, valores = armar_update(cuerpo, {
        "horario_apertura": str, "horario_cierre": str, "iva_porcentaje": float,
        "moneda": str, "zona_horaria": str, "operacion_24h": como_bool,
    })
    n = db.ejecutar(f"UPDATE configuracion_empresa SET {sets} WHERE id_empresa = %s", (*valores, u.id_empresa))
    if n == 0:
        raise ApiError(404, "Configuración no encontrada")
    return {"success": True, "message": "Configuración actualizada"}


# --- Logo de la empresa (guardado en la base como binario) -------------------

@router.get("/logo")
def ver_logo(u: Usuario = Depends(usuario_actual)):
    fila = db.uno("SELECT logo_url FROM empresas WHERE id_empresa = %s", (u.id_empresa,))
    if not fila or fila["logo_url"] is None:
        raise ApiError(404, "Logo no configurado")
    datos = bytes(fila["logo_url"])
    return Response(datos, media_type=tipo_imagen(datos))


@router.post("/logo")
def subir_logo(logo: UploadFile = File(None), u: Usuario = Depends(solo_admin)):
    datos = leer_imagen(logo)
    db.ejecutar("UPDATE empresas SET logo_url = %s WHERE id_empresa = %s", (datos, u.id_empresa))
    return {"success": True, "url": f"/api/empresa/logo?ts={int(time.time() * 1000)}", "message": "Logo subido y guardado"}


# --- QR de pago ---------------------------------------------------------------
# Es la imagen del QR fijo que el parqueadero ya tiene en la caseta.
# NO es una pasarela de pago: el operador confirma a mano que llegó la plata.

@router.get("/qr-pago")
def ver_qr(u: Usuario = Depends(usuario_actual)):
    fila = db.uno("SELECT qr_pago FROM empresas WHERE id_empresa = %s", (u.id_empresa,))
    if not fila or fila["qr_pago"] is None:
        raise ApiError(404, "No hay QR de pago cargado")
    datos = bytes(fila["qr_pago"])
    return Response(datos, media_type=tipo_imagen(datos))


@router.post("/qr-pago")
def subir_qr(qr: UploadFile = File(None), u: Usuario = Depends(solo_admin)):
    datos = leer_imagen(qr)
    db.ejecutar("UPDATE empresas SET qr_pago = %s WHERE id_empresa = %s", (datos, u.id_empresa))
    return {"success": True, "url": f"/api/empresa/qr-pago?ts={int(time.time() * 1000)}", "message": "QR de pago guardado"}


@router.delete("/qr-pago")
def quitar_qr(u: Usuario = Depends(solo_admin)):
    db.ejecutar("UPDATE empresas SET qr_pago = NULL WHERE id_empresa = %s", (u.id_empresa,))
    return {"success": True, "message": "QR de pago eliminado"}
