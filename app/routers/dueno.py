"""Panel del dueño del SaaS (no del parqueadero).

Se protege con una clave suelta en ADMIN_MASTER_KEY, aparte de los roles de las
empresas. Si la variable no está definida, el panel queda apagado (503).
"""
import hmac
import logging

import bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from psycopg import errors

from app import config, db
from app.seguridad import ApiError
from app.utiles import AHORA, FECHA_ISO, HOY, cuerpo_json, entero

router = APIRouter(prefix="/api/dueno", tags=["panel del dueño"])
log = logging.getLogger("dueno")

# Tope de la fase actual: más allá de esto el plan gratuito de la base y del hosting no aguanta.
TOPE_EMPRESAS = 15

# nombre, código, valor minuto, hora, día
TIPOS_INICIALES = [
    ("Carro", "carro", 120, 6000, 30000),
    ("Moto", "moto", 60, 3000, 15000),
    ("Bicicleta", "bicicleta", 30, 1500, 7500),
]


def exigir_clave(request: Request, cuerpo: dict = Depends(cuerpo_json)):
    esperada = config.ADMIN_MASTER_KEY
    if not esperada:
        raise ApiError(503, "El panel no está habilitado en este servidor.")
    recibida = str(request.headers.get("x-admin-key") or cuerpo.get("clave") or "")
    # compare_digest compara sin cortar en el primer carácter distinto.
    if not hmac.compare_digest(recibida.encode(), esperada.encode()):
        log.warning("Intento de acceso con clave incorrecta desde %s", request.client.host if request.client else "?")
        raise ApiError(401, "Clave incorrecta.")


@router.post("/entrar", dependencies=[Depends(exigir_clave)])
def entrar():
    return {"success": True, "message": "Clave correcta"}


@router.get("/empresas", dependencies=[Depends(exigir_clave)])
def empresas():
    """Estado de pago calculado en SQL, sin depender de la hora del navegador."""
    filas = db.consultar(
        f"""SELECT e.id_empresa, e.nombre, e.nit, e.telefono, e.email,
                   e.plan, e.activa, e.fecha_vencimiento,
                   e.fecha_vencimiento::date - {HOY} AS dias_restantes,
                   (SELECT COUNT(*) FROM usuarios u WHERE u.id_empresa = e.id_empresa) AS usuarios,
                   (SELECT COUNT(*) FROM movimientos m
                     WHERE m.id_empresa = e.id_empresa
                       AND m.fecha_entrada >= {AHORA} - INTERVAL '30 days') AS movimientos_30d
            FROM empresas e
            ORDER BY e.activa DESC, e.fecha_vencimiento IS NULL, e.fecha_vencimiento ASC"""
    )

    lista = []
    for e in filas:
        d = e["dias_restantes"]
        if e["fecha_vencimiento"] is None:
            estado = "sin_fecha"
        elif d > 5:
            estado = "al_dia"
        elif d >= 0:
            estado = "por_vencer"
        elif d >= -5:
            estado = "gracia"
        else:
            estado = "vencida"
        lista.append({**db.fila(e), "estado": estado})

    activas = sum(1 for e in lista if e["activa"])
    return {"success": True, "data": lista, "resumen": {
        "total": len(lista), "activas": activas, "tope": TOPE_EMPRESAS,
        "cupos_libres": max(0, TOPE_EMPRESAS - activas),
    }}


@router.put("/empresas/{id_empresa}", dependencies=[Depends(exigir_clave)])
def actualizar(id_empresa: int, cuerpo: dict = Depends(cuerpo_json)):
    """Cambia vencimiento, estado o plan. Desactivar corta el acceso de una vez."""
    campos, valores = [], []

    if "fecha_vencimiento" in cuerpo:
        f = cuerpo["fecha_vencimiento"]
        if f in (None, ""):
            campos.append("fecha_vencimiento = NULL")
        elif FECHA_ISO.match(str(f)):
            campos.append("fecha_vencimiento = %s")
            valores.append(f"{f} 23:59:59")
        else:
            raise ApiError(400, "La fecha debe venir como AAAA-MM-DD")
    if "activa" in cuerpo:
        campos.append("activa = %s")
        valores.append(bool(cuerpo["activa"]))
    if "plan" in cuerpo:
        campos.append("plan = %s")
        valores.append(str(cuerpo["plan"])[:50])
    if not campos:
        raise ApiError(400, "Nada para actualizar")

    try:
        n = db.ejecutar(f"UPDATE empresas SET {', '.join(campos)} WHERE id_empresa = %s", (*valores, id_empresa))
    except errors.CheckViolation:
        raise ApiError(400, "Plan inválido (basico, premium o enterprise)")
    if n == 0:
        raise ApiError(404, "Parqueadero no encontrado")
    log.info("Empresa %s actualizada: %s", id_empresa, ", ".join(campos))
    return {"success": True, "message": "Actualizado"}


@router.post("/empresas/{id_empresa}/renovar", dependencies=[Depends(exigir_clave)])
def renovar(id_empresa: int, cuerpo: dict = Depends(cuerpo_json)):
    """Renueva N meses desde hoy, o desde el vencimiento si todavía no ha pasado."""
    meses = entero(cuerpo.get("meses"), minimo=0, maximo=1000)
    if not 1 <= meses <= 24:
        raise ApiError(400, "Los meses deben ir de 1 a 24")

    fila = db.uno(
        f"""UPDATE empresas
            SET fecha_vencimiento = GREATEST(COALESCE(fecha_vencimiento, {AHORA}), {AHORA})
                                    + make_interval(months => %s)
            WHERE id_empresa = %s RETURNING fecha_vencimiento""",
        (meses, id_empresa),
    )
    if not fila:
        raise ApiError(404, "Parqueadero no encontrado")
    return {"success": True, "message": f"Renovado por {meses} {'mes' if meses == 1 else 'meses'}",
            "fecha_vencimiento": db.a_json(fila["fecha_vencimiento"])}


@router.post("/empresas", dependencies=[Depends(exigir_clave)])
def crear_empresa(cuerpo: dict = Depends(cuerpo_json)):
    """Alta de un parqueadero listo para usar: empresa, configuración, admin,
    tipos de vehículo y tarifas. Todo en UNA transacción: o completo o nada."""
    def texto(k):
        return str(cuerpo.get(k) or "").strip()

    nombre, nit, usuario = texto("nombre"), texto("nit"), texto("usuario")
    clave = str(cuerpo.get("password") or "")
    meses = entero(cuerpo.get("meses"), minimo=0, maximo=1000) or 1

    if not nombre or not nit:
        raise ApiError(400, "El nombre y el NIT son obligatorios.")
    if not usuario or not clave:
        raise ApiError(400, "Hay que crear el usuario administrador.")
    if len(clave) < 6:
        raise ApiError(400, "La contraseña debe tener al menos 6 caracteres.")
    if not 1 <= meses <= 24:
        raise ApiError(400, "Los meses deben ir de 1 a 24.")

    if db.uno("SELECT COUNT(*) AS n FROM empresas WHERE activa = TRUE")["n"] >= TOPE_EMPRESAS:
        raise ApiError(409, f"Ya hay {TOPE_EMPRESAS} parqueaderos activos, que es el tope de este plan. "
                            "Apaga uno o sube de plan antes de vender otro.")
    if db.uno("SELECT 1 FROM empresas WHERE nit = %s", (nit,)):
        raise ApiError(409, f"Ya existe un parqueadero con el NIT {nit}.")

    hash_clave = bcrypt.hashpw(clave.encode(), bcrypt.gensalt(10)).decode()

    with db.transaccion() as conn:
        creada = conn.execute(
            f"""INSERT INTO empresas (nombre, nit, direccion, telefono, email, plan, activa, fecha_vencimiento)
                VALUES (%s, %s, %s, %s, %s, 'basico', TRUE, {AHORA} + make_interval(months => %s))
                RETURNING id_empresa, nombre, nit, fecha_vencimiento""",
            (nombre, nit, texto("direccion") or None, texto("telefono") or None, texto("email") or None, meses),
        ).fetchone()
        id_empresa = creada["id_empresa"]

        conn.execute(
            """INSERT INTO configuracion_empresa
                   (id_empresa, capacidad_total_carros, capacidad_total_motos, capacidad_total_bicicletas,
                    horario_apertura, horario_cierre, iva_porcentaje, moneda, zona_horaria, operacion_24h)
               VALUES (%s, 40, 30, 20, '06:00:00', '22:00:00', 0, 'COP', 'America/Bogota', FALSE)""",
            (id_empresa,),
        )
        conn.execute(
            """INSERT INTO usuarios (id_empresa, nombre, usuario_login, contrasena, rol, activo)
               VALUES (%s, 'Administrador', %s, %s, 'admin', TRUE)""",
            (id_empresa, usuario, hash_clave),
        )
        # Tipo y tarifa van juntos: un tipo sin tarifa no se puede cobrar.
        for nom, cod, v_min, v_hora, v_dia in TIPOS_INICIALES:
            id_tipo = conn.execute(
                "INSERT INTO tipos_vehiculos (id_empresa, nombre, codigo, activo) "
                "VALUES (%s, %s, %s, TRUE) RETURNING id_tipo",
                (id_empresa, nom, cod),
            ).fetchone()["id_tipo"]
            conn.execute(
                f"""INSERT INTO tarifas
                        (id_empresa, id_tipo, valor_hora, valor_minuto, valor_dia_completo,
                         fecha_vigencia_desde, modo_cobro, paso_minutos_a_horas,
                         paso_horas_a_dias, redondeo_horas, redondeo_dias, activa)
                    VALUES (%s, %s, %s, %s, %s, {AHORA}, 'mixto', 60, 5, 'arriba', 'arriba', TRUE)""",
                (id_empresa, id_tipo, v_hora, v_min, v_dia),
            )

    log.info("Parqueadero creado: %s (NIT %s, id %s)", nombre, nit, id_empresa)
    return JSONResponse({
        "success": True,
        "message": "Parqueadero creado. Ya puede entrar con su NIT y usuario.",
        "data": db.fila(creada),
    }, status_code=201)
