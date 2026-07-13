from models import Boleta, Vendedor
from tests.conftest import login
from tests.test_features import crear_boleta


def test_admin_crea_vendedor_con_telefono(client, admin):
    login(client, "admin1", "clave123")
    client.post(
        "/admin/vendedores",
        data={"username": "vtel", "nombre": "Vendedor Con Telefono", "telefono": "3000000099", "password": "clave123"},
        follow_redirects=True,
    )
    v = Vendedor.query.filter_by(username="vtel").first()
    assert v.telefono == "3000000099"


def test_admin_edita_telefono_de_vendedor(client, vendedor, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        f"/admin/vendedores/{vendedor.id}/editar",
        data={"nombre": "Vendedor Uno", "telefono": "3005551234"},
        follow_redirects=True,
    )
    assert "actualizado correctamente" in resp.get_data(as_text=True)

    v = Vendedor.query.get(vendedor.id)
    assert v.telefono == "3005551234"


def test_admin_elimina_vendedor_sin_boletas(client, vendedor, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        f"/admin/vendedores/{vendedor.id}/eliminar", follow_redirects=True
    )
    assert "eliminado" in resp.get_data(as_text=True)
    assert Vendedor.query.get(vendedor.id) is None


def test_admin_no_puede_eliminar_vendedor_con_boletas(client, vendedor, admin):
    crear_boleta(client, documento="ELIMINAR-001", numero1="0800", numero2="0801", numero3="0802")

    login(client, "admin1", "clave123")
    resp = client.post(
        f"/admin/vendedores/{vendedor.id}/eliminar", follow_redirects=True
    )
    assert "tiene boletas registradas" in resp.get_data(as_text=True)
    assert Vendedor.query.get(vendedor.id) is not None


def test_admin_no_puede_eliminarse_a_si_mismo(client, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        f"/admin/vendedores/{admin.id}/eliminar", follow_redirects=True
    )
    assert "No puedes eliminarte a ti mismo" in resp.get_data(as_text=True)
    assert Vendedor.query.get(admin.id) is not None


def test_vendedor_no_admin_no_puede_eliminar_vendedores(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.post(
        f"/admin/vendedores/{vendedor.id}/eliminar", follow_redirects=True
    )
    assert "No tienes permiso" in resp.get_data(as_text=True)


def test_boton_eliminar_no_aparece_si_tiene_boletas(client, vendedor, admin):
    crear_boleta(client, documento="ELIMINAR-002", numero1="0810", numero2="0811", numero3="0812")

    login(client, "admin1", "clave123")
    resp = client.get("/admin/vendedores")
    text = resp.get_data(as_text=True)

    assert f"/admin/vendedores/{vendedor.id}/eliminar" not in text


def test_vendedor_no_admin_no_puede_editar_vendedores(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.get(f"/admin/vendedores/{vendedor.id}/editar", follow_redirects=True)
    assert "No tienes permiso" in resp.get_data(as_text=True)


def test_consulta_muestra_contacto_del_vendedor_si_falta_pagar(client, vendedor, admin, db):
    vendedor.telefono = "3009998877"
    db.session.commit()

    crear_boleta(client, documento="CONTACTO-001", numero1="0700", numero2="0701", numero3="0702")

    resp = client.post("/consulta", data={"documento": "CONTACTO-001"}, follow_redirects=True)
    text = resp.get_data(as_text=True)

    assert "Contacta a" in text
    assert "Vendedor Uno" in text
    assert "3009998877" in text


def test_consulta_no_muestra_contacto_si_ya_pago_todo(client, vendedor, admin):
    crear_boleta(client, documento="CONTACTO-002", numero1="0710", numero2="0711", numero3="0712")
    boleta = Boleta.query.filter_by(cliente_documento="CONTACTO-002").first()

    login(client, "admin1", "clave123")
    client.post(
        f"/boletas/{boleta.id}/pago",
        data={"pagado_premio1": "on", "pagado_premio2": "on", "pagado_premio3": "on", "pagado_premio4": "on"},
        follow_redirects=True,
    )
    client.get("/logout")

    resp = client.post("/consulta", data={"documento": "CONTACTO-002"}, follow_redirects=True)
    assert "Contacta a" not in resp.get_data(as_text=True)


def test_boletas_filtro_pago_pendiente(client, vendedor, admin):
    crear_boleta(client, documento="FILTRO-001", numero1="0720", numero2="0721", numero3="0722")
    crear_boleta(client, documento="FILTRO-002", numero1="0730", numero2="0731", numero3="0732")
    boleta_pagada = Boleta.query.filter_by(cliente_documento="FILTRO-002").first()

    login(client, "admin1", "clave123")
    client.post(
        f"/boletas/{boleta_pagada.id}/pago",
        data={"pagado_premio1": "on", "pagado_premio2": "on", "pagado_premio3": "on", "pagado_premio4": "on"},
        follow_redirects=True,
    )

    resp_pendiente = client.get("/boletas?pago=pendiente")
    text_pendiente = resp_pendiente.get_data(as_text=True)
    assert "FILTRO-001" in text_pendiente
    assert "FILTRO-002" not in text_pendiente

    resp_completo = client.get("/boletas?pago=completo")
    text_completo = resp_completo.get_data(as_text=True)
    assert "FILTRO-002" in text_completo
    assert "FILTRO-001" not in text_completo

    resp_todas = client.get("/boletas")
    text_todas = resp_todas.get_data(as_text=True)
    assert "FILTRO-001" in text_todas and "FILTRO-002" in text_todas


def test_como_funciona_carga_sin_login(client):
    resp = client.get("/como-funciona")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "100.000" in text
    assert "25.000" in text


def test_pantalla_en_vivo_incluye_fecha_del_premio(client, admin, db):
    from datetime import datetime
    from models import ConfiguracionRifa

    config = ConfiguracionRifa.obtener()
    config.fecha_premio1 = datetime(2030, 5, 20, 19, 0)
    config.fecha_premio2 = datetime(2030, 6, 1, 19, 0)
    db.session.commit()

    resp1 = client.get("/pantalla/1")
    assert "2030-05-20T19:00:00" in resp1.get_data(as_text=True)

    resp2 = client.get("/pantalla/2")
    assert "2030-06-01T19:00:00" in resp2.get_data(as_text=True)

    resp_selector = client.get("/pantalla")
    text_selector = resp_selector.get_data(as_text=True)
    assert "2030-05-20 19:00" in text_selector
    assert "2030-06-01 19:00" in text_selector


def test_api_ultimo_sorteo_filtra_por_premio(client, vendedor, admin):
    crear_boleta(client, documento="API-PREMIO-001", numero1="0740", numero2="0741", numero3="0742")

    login(client, "admin1", "clave123")
    client.post(
        "/admin/sorteo", data={"numero": "0740", "numero_premio": "2", "etiqueta": ""}, follow_redirects=True
    )

    resp_premio1 = client.get("/api/ultimo-sorteo?premio=1")
    assert resp_premio1.get_json() == {"hay_sorteo": False}

    resp_premio2 = client.get("/api/ultimo-sorteo?premio=2")
    data = resp_premio2.get_json()
    assert data["hay_sorteo"] is True
    assert data["numero"] == "0740"
