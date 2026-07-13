from datetime import datetime

from models import Boleta, ConfiguracionRifa
from tests.conftest import login
from tests.test_features import crear_boleta


def test_consulta_muestra_estado_de_la_rifa(client):
    resp = client.get("/consulta")
    text = resp.get_data(as_text=True)

    assert "de 10000 números vendidos" in text
    assert "progreso-rifa-relleno" in text


def test_consulta_muestra_pago_de_la_boleta(client, vendedor, admin):
    crear_boleta(client, documento="PUB-001", numero1="0900", numero2="0901", numero3="0902")
    boleta = Boleta.query.filter_by(cliente_documento="PUB-001").first()

    login(client, "admin1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True)
    client.get("/logout")

    resp = client.post("/consulta", data={"documento": "PUB-001"}, follow_redirects=True)
    text = resp.get_data(as_text=True)

    assert "$25.000" in text
    assert "$100.000" in text
    assert "1 de 4 premios" in text


def test_consulta_muestra_premio_ganador_pagado(client, vendedor, admin):
    crear_boleta(client, documento="PUB-002", numero1="0910", numero2="0911", numero3="0912")
    boleta = Boleta.query.filter_by(cliente_documento="PUB-002").first()

    login(client, "admin1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True)
    client.post(
        "/admin/sorteo", data={"numero": "0910", "numero_premio": "1", "etiqueta": ""}, follow_redirects=True
    )
    client.get("/logout")

    resp = client.post("/consulta", data={"documento": "PUB-002"}, follow_redirects=True)
    assert "ganaste!" in resp.get_data(as_text=True)


def test_consulta_muestra_premio_ganador_sin_pago(client, vendedor, admin):
    crear_boleta(client, documento="PUB-003", numero1="0920", numero2="0921", numero3="0922")

    login(client, "admin1", "clave123")
    client.post(
        "/admin/sorteo", data={"numero": "0920", "numero_premio": "2", "etiqueta": ""}, follow_redirects=True
    )
    client.get("/logout")

    resp = client.post("/consulta", data={"documento": "PUB-003"}, follow_redirects=True)
    assert "no pagaste este premio" in resp.get_data(as_text=True)


def test_consulta_muestra_premio_no_ganador(client, vendedor, admin):
    crear_boleta(client, documento="PUB-004", numero1="0930", numero2="0931", numero3="0932")

    login(client, "admin1", "clave123")
    client.post(
        "/admin/sorteo", data={"numero": "9999", "numero_premio": "1", "etiqueta": ""}, follow_redirects=True
    )
    client.get("/logout")

    resp = client.post("/consulta", data={"documento": "PUB-004"}, follow_redirects=True)
    assert "No ganó (salió 9999)" in resp.get_data(as_text=True)


def test_consulta_muestra_premio_pendiente(client, vendedor):
    crear_boleta(client, documento="PUB-005", numero1="0940", numero2="0941", numero3="0942")

    resp = client.post("/consulta", data={"documento": "PUB-005"}, follow_redirects=True)
    text = resp.get_data(as_text=True)
    assert "Sin pagar" in text
    assert "Fecha del sorteo por confirmar" in text


def test_consulta_historial_sorteos_no_expone_nombre_ganador(client, vendedor, admin):
    crear_boleta(client, nombre_cliente="Secreto Ganador", documento="PUB-006", numero1="0950", numero2="0951", numero3="0952")

    login(client, "admin1", "clave123")
    client.post(
        "/admin/sorteo", data={"numero": "0950", "numero_premio": "3", "etiqueta": "Premio mayor"}, follow_redirects=True
    )
    client.get("/logout")

    resp = client.get("/consulta")
    text = resp.get_data(as_text=True)

    assert "Premio mayor" in text
    assert "0950" in text
    assert "Secreto Ganador" not in text


def test_admin_configura_fechas_por_premio(client, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        "/admin/sorteo/fechas",
        data={
            "fecha_premio1": "2030-12-31T20:00",
            "fecha_premio2": "2031-01-15T20:00",
            "fecha_premio3": "",
            "fecha_premio4": "",
        },
        follow_redirects=True,
    )
    assert "Fechas de sorteo actualizadas" in resp.get_data(as_text=True)

    config = ConfiguracionRifa.obtener()
    assert config.fecha_premio1.year == 2030
    assert config.fecha_premio2.year == 2031
    assert config.fecha_premio3 is None

    resp_publica = client.get("/consulta")
    text = resp_publica.get_data(as_text=True)
    assert "2030-12-31" in text
    assert "2031-01-15" in text
    assert "cuenta-regresiva" in text


def test_admin_quita_fecha_de_un_premio(client, admin, db):
    config = ConfiguracionRifa.obtener()
    config.fecha_premio1 = datetime(2030, 1, 1)
    db.session.commit()

    login(client, "admin1", "clave123")
    client.post(
        "/admin/sorteo/fechas",
        data={"fecha_premio1": "", "fecha_premio2": "", "fecha_premio3": "", "fecha_premio4": ""},
        follow_redirects=True,
    )

    config = ConfiguracionRifa.obtener()
    assert config.fecha_premio1 is None


def test_vendedor_no_admin_no_puede_configurar_fechas(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.post(
        "/admin/sorteo/fechas", data={"fecha_premio1": "2030-12-31T20:00"}, follow_redirects=True
    )
    assert "No tienes permiso" in resp.get_data(as_text=True)


def test_consulta_muestra_plazo_de_pago_pendiente(client, vendedor, admin, db):
    config = ConfiguracionRifa.obtener()
    config.fecha_premio1 = datetime(2030, 6, 1, 20, 0)
    db.session.commit()

    crear_boleta(client, documento="PUB-007", numero1="0960", numero2="0961", numero3="0962")

    resp = client.post("/consulta", data={"documento": "PUB-007"}, follow_redirects=True)
    text = resp.get_data(as_text=True)

    assert "Sin pagar" in text
    assert 'data-tipo="plazo"' in text
    assert "2030-06-01" in text


def test_consulta_no_muestra_plazo_para_premio_ya_sorteado(client, vendedor, admin, db):
    config = ConfiguracionRifa.obtener()
    config.fecha_premio1 = datetime(2030, 6, 1, 20, 0)
    db.session.commit()

    crear_boleta(client, documento="PUB-008", numero1="0970", numero2="0971", numero3="0972")
    boleta = Boleta.query.filter_by(cliente_documento="PUB-008").first()

    login(client, "admin1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True)
    client.post(
        "/admin/sorteo", data={"numero": "0970", "numero_premio": "1", "etiqueta": ""}, follow_redirects=True
    )
    client.get("/logout")

    resp = client.post("/consulta", data={"documento": "PUB-008"}, follow_redirects=True)
    text = resp.get_data(as_text=True)

    assert "ganaste!" in text
    # La fecha configurada sigue apareciendo en el resumen general de
    # "próximos sorteos" (data-tipo="sorteo"), pero el premio 1 de esta
    # boleta ya se jugó, así que no debe mostrar un plazo de pago pendiente.
    assert 'data-tipo="plazo"' not in text


def test_consulta_muestra_numero_grande_en_historial(client, vendedor, admin):
    crear_boleta(client, documento="PUB-009", numero1="0980", numero2="0981", numero3="0982")

    login(client, "admin1", "clave123")
    client.post(
        "/admin/sorteo", data={"numero": "0980", "numero_premio": "1", "etiqueta": "Gran premio"}, follow_redirects=True
    )
    client.get("/logout")

    resp = client.get("/consulta")
    text = resp.get_data(as_text=True)

    assert 'class="sorteo-card"' in text
    assert '<span class="numero-grande">0980</span>' in text


def test_pantalla_selector_carga_sin_login(client):
    resp = client.get("/pantalla")
    assert resp.status_code == 200
    assert "pantalla-selector-grid" in resp.get_data(as_text=True)


def test_pantalla_en_vivo_de_un_premio_carga_sin_login(client):
    resp = client.get("/pantalla/1")
    assert resp.status_code == 200
    assert "pantalla-live" in resp.get_data(as_text=True)


def test_pantalla_en_vivo_rechaza_premio_invalido(client):
    resp = client.get("/pantalla/9", follow_redirects=True)
    assert "Ese premio no existe" in resp.get_data(as_text=True)


def test_api_ultimo_sorteo_sin_sorteos(client):
    resp = client.get("/api/ultimo-sorteo")
    assert resp.get_json() == {"hay_sorteo": False}


def test_api_ultimo_sorteo_devuelve_el_mas_reciente(client, vendedor, admin):
    crear_boleta(client, documento="PUB-010", numero1="0990", numero2="0991", numero3="0992")

    login(client, "admin1", "clave123")
    client.post(
        "/admin/sorteo", data={"numero": "0990", "numero_premio": "4", "etiqueta": "Ultimo"}, follow_redirects=True
    )

    resp = client.get("/api/ultimo-sorteo")
    data = resp.get_json()

    assert data["hay_sorteo"] is True
    assert data["numero"] == "0990"
    assert data["numero_premio"] == 4
    assert data["etiqueta"] == "Ultimo"
