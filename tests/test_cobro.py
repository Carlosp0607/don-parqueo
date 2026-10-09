"""Pruebas de las reglas de negocio que mueven plata. No necesitan base de datos."""
import datetime as dt

import pytest

from app.routers.mensualidades import meses_entre
from app.routers.movimientos import normalizar_metodo
from app.routers.turnos import parsear_pesos
from app.tarifa import calcular_total
from app.utiles import redondear, sumar_meses

ENTRADA = dt.datetime(2026, 10, 9, 8, 0)


def tarifa(**cambios):
    base = {"valor_minuto": 120, "valor_hora": 6000, "valor_dia_completo": 30000,
            "modo_cobro": "mixto", "paso_minutos_a_horas": 0, "paso_horas_a_dias": 0,
            "redondeo_horas": "arriba", "redondeo_dias": "arriba"}
    return {**base, **cambios}


def cobrar(t, minutos):
    return calcular_total(t, ENTRADA, ENTRADA + dt.timedelta(minutes=minutos))


# --- Cálculo del cobro ----------------------------------------------------------

def test_cobro_minimo_de_un_minuto():
    assert cobrar(tarifa(modo_cobro="minuto"), 0)["total"] == 120


def test_modo_minuto():
    assert cobrar(tarifa(modo_cobro="minuto"), 45)["total"] == 45 * 120


def test_modo_hora_redondea_hacia_arriba():
    # 61 minutos son 2 horas cobradas
    assert cobrar(tarifa(modo_cobro="hora"), 61)["total"] == 12000


def test_modo_hora_exacto_cobra_la_fraccion():
    assert cobrar(tarifa(modo_cobro="hora", redondeo_horas="exacto"), 90)["total"] == 9000


def test_modo_dia():
    assert cobrar(tarifa(modo_cobro="dia"), 25 * 60)["total"] == 60000


def test_mixto_sin_escalones_suma_dias_horas_y_minutos():
    # 1 día, 2 horas y 5 minutos
    r = cobrar(tarifa(), 24 * 60 + 2 * 60 + 5)
    assert r["total"] == 30000 + 2 * 6000 + 5 * 120
    assert r["detalleTiempo"] == {"dias": 1, "horas": 2, "minutos": 5}


def test_mixto_con_escalones():
    t = tarifa(paso_minutos_a_horas=60, paso_horas_a_dias=5)
    assert cobrar(t, 30)["total"] == 30 * 120          # antes de 60 min: por minuto
    assert cobrar(t, 90)["total"] == 2 * 6000          # desde 60 min: por hora
    assert cobrar(t, 6 * 60)["total"] == 30000         # desde 5 horas: por día


def test_redondeo_comercial_como_javascript():
    assert redondear(2.5) == 3
    assert redondear(3.5) == 4  # round(2.5) de Python da 2; aquí .5 siempre sube


# --- Métodos de pago --------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("qr", "QR"), ("QR", "QR"), ("Efectivo", "efectivo"), (" nequi ", "nequi"), ("bitcoin", None), ("", None),
])
def test_normalizar_metodo(entrada, esperado):
    assert normalizar_metodo(entrada) == esperado


# --- Base y arqueo de caja ----------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    (50000, 50000), ("50000", 50000), ("50.000", 50000), ("$ 50.000", 50000), ("", 0), (None, 0),
    ("2,71", None), (12.5, None), (-1, None), ("abc", None),
])
def test_parsear_pesos(entrada, esperado):
    assert parsear_pesos(entrada) == esperado


# --- Mensualidades ------------------------------------------------------------------

def test_meses_vencidos():
    assert meses_entre(dt.date(2026, 10, 9), dt.date(2026, 8, 15)) == 2
    assert meses_entre(dt.date(2026, 10, 15), dt.date(2026, 8, 15)) == 3


def test_sumar_meses_como_javascript():
    assert sumar_meses(dt.date(2026, 1, 15), 1) == dt.date(2026, 2, 15)
    assert sumar_meses(dt.date(2026, 1, 31), 1) == dt.date(2026, 3, 3)  # 31 de febrero no existe
    assert sumar_meses(dt.date(2026, 11, 10), 3) == dt.date(2027, 2, 10)
