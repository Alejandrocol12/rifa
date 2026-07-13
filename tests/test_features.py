from models import Boleta, NumeroAsignado, Sorteo
from tests.conftest import login
from tests.test_app import datos_boleta


def crear_boleta(client, **overrides):
    login(client, "vend1", "clave123")
    client.post("/registrar", data=datos_boleta(**overrides), follow_redirects=True)
    client.get("/logout")
    return Boleta.query.order_by(Boleta.id.desc()).first()


# --- Editar boleta ---


def test_vendedor_edita_su_propia_boleta(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    resp = client.post(
        f"/boletas/{boleta.id}/editar",
        data={
            "nombre_cliente": "Juan Perez Editado",
            "telefono": "3000000001",
            "direccion": "",
            "email": "",
        },
        follow_redirects=True,
    )

    assert "actualizados correctamente" in resp.get_data(as_text=True)
    actualizada = Boleta.query.get(boleta.id)
    assert actualizada.cliente.nombre == "Juan Perez Editado"
    assert actualizada.cliente.telefono == "3000000001"
    assert {n.numero for n in actualizada.numeros} == {"0001", "0002", "0003"}


def test_vendedor_no_puede_editar_boleta_de_otro(client, vendedor, db):
    from models import Vendedor

    otro = Vendedor(username="vend2", nombre="Vendedor Dos", is_admin=False)
    otro.set_password("clave123")
    db.session.add(otro)
    db.session.commit()

    boleta = crear_boleta(client)

    login(client, "vend2", "clave123")
    resp = client.get(f"/boletas/{boleta.id}/editar", follow_redirects=True)
    assert "No tienes permiso" in resp.get_data(as_text=True)


def test_admin_puede_editar_boleta_de_cualquier_vendedor(client, vendedor, admin):
    boleta = crear_boleta(client)

    login(client, "admin1", "clave123")
    resp = client.post(
        f"/boletas/{boleta.id}/editar",
        data={
            "nombre_cliente": "Editado por Admin",
            "telefono": "3000000000",
            "direccion": "",
            "email": "",
        },
        follow_redirects=True,
    )
    assert "actualizados correctamente" in resp.get_data(as_text=True)


def test_editar_boleta_rechaza_email_invalido(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    resp = client.post(
        f"/boletas/{boleta.id}/editar",
        data={
            "nombre_cliente": "Juan Perez",
            "telefono": "3000000000",
            "direccion": "",
            "email": "no-es-correo",
        },
        follow_redirects=True,
    )
    assert "correo electrónico" in resp.get_data(as_text=True)


def test_no_se_puede_editar_el_documento(client, vendedor):
    boleta = crear_boleta(client)
    login(client, "vend1", "clave123")
    resp = client.get(f"/boletas/{boleta.id}/editar")
    assert 'name="documento"' not in resp.get_data(as_text=True)


# --- Pago por premio ---


def test_marcar_pago_de_premios(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    resp = client.post(
        f"/boletas/{boleta.id}/pago",
        data={"pagado_premio1": "on", "pagado_premio3": "on"},
        follow_redirects=True,
    )

    assert "Pago actualizado" in resp.get_data(as_text=True)
    actualizada = Boleta.query.get(boleta.id)
    assert actualizada.pagado_premio1 is True
    assert actualizada.pagado_premio2 is False
    assert actualizada.pagado_premio3 is True
    assert actualizada.premios_pagados == 2
    assert actualizada.monto_pagado == 50000
    assert actualizada.pago_completo is False


def test_otro_vendedor_no_puede_marcar_pago(client, vendedor, db):
    from models import Vendedor

    otro = Vendedor(username="vend2", nombre="Vendedor Dos", is_admin=False)
    otro.set_password("clave123")
    db.session.add(otro)
    db.session.commit()

    boleta = crear_boleta(client)

    login(client, "vend2", "clave123")
    resp = client.post(
        f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True
    )
    assert "No tienes permiso" in resp.get_data(as_text=True)


# --- Historial de vendedor (admin) ---


def test_admin_ve_historial_de_vendedor(client, vendedor, admin):
    crear_boleta(client, numero1="0010", numero2="0011", numero3="0012")
    crear_boleta(client, documento="456", numero1="0020", numero2="0021", numero3="0022")

    login(client, "admin1", "clave123")
    resp = client.get(f"/admin/vendedores/{vendedor.id}/historial")
    text = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Vendedor Uno" in text
    assert "0010" in text and "0020" in text


def test_vendedor_no_puede_ver_historial_ajeno(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.get(f"/admin/vendedores/{vendedor.id}/historial", follow_redirects=True)
    assert "No tienes permiso" in resp.get_data(as_text=True)


# --- Sorteo ---


def test_admin_registra_sorteo_y_encuentra_ganador(client, vendedor, admin):
    crear_boleta(client, numero1="0500", numero2="0501", numero3="0502")

    login(client, "admin1", "clave123")
    resp = client.post(
        "/admin/sorteo",
        data={"numero": "0500", "numero_premio": "1", "etiqueta": "Primer premio"},
        follow_redirects=True,
    )
    text = resp.get_data(as_text=True)

    assert "registrado para el premio 1" in text
    assert "Juan Perez" in text
    assert "No pagó este premio" in text  # todavía no se marcó como pagado
    assert Sorteo.query.filter_by(numero="0500").count() == 1


def test_sorteo_muestra_pagado_cuando_el_premio_esta_al_dia(client, vendedor, admin):
    crear_boleta(client, numero1="0510", numero2="0511", numero3="0512")
    boleta = Boleta.query.order_by(Boleta.id.desc()).first()

    login(client, "admin1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio2": "on"}, follow_redirects=True)

    resp = client.post(
        "/admin/sorteo", data={"numero": "0510", "numero_premio": "2", "etiqueta": ""}, follow_redirects=True
    )
    assert "✓ Pagó este premio" in resp.get_data(as_text=True)


def test_sorteo_numero_no_vendido_muestra_sin_ganador(client, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        "/admin/sorteo", data={"numero": "9999", "numero_premio": "1", "etiqueta": ""}, follow_redirects=True
    )
    assert "Sin ganador" in resp.get_data(as_text=True)


def test_sorteo_rechaza_numero_invalido(client, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        "/admin/sorteo", data={"numero": "12", "numero_premio": "1", "etiqueta": ""}, follow_redirects=True
    )
    assert "debe tener 4 cifras" in resp.get_data(as_text=True)
    assert Sorteo.query.count() == 0


def test_sorteo_rechaza_sin_numero_de_premio(client, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        "/admin/sorteo", data={"numero": "0500", "numero_premio": "", "etiqueta": ""}, follow_redirects=True
    )
    assert "a cuál de los 4 premios" in resp.get_data(as_text=True)
    assert Sorteo.query.count() == 0


def test_vendedor_no_admin_no_accede_a_sorteo(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.get("/admin/sorteo", follow_redirects=True)
    assert "No tienes permiso" in resp.get_data(as_text=True)


# --- Consulta pública ---


def test_consulta_publica_encuentra_boletas_sin_login(client, vendedor):
    crear_boleta(client, documento="777888", numero1="0300", numero2="0301", numero3="0302")

    resp = client.post("/consulta", data={"documento": "777888"}, follow_redirects=True)
    text = resp.get_data(as_text=True)

    assert "Juan Perez" in text
    assert "0300" in text and "0301" in text and "0302" in text


def test_consulta_publica_no_expone_telefono_ni_email(client, vendedor):
    crear_boleta(
        client,
        documento="999111",
        telefono="3019999999",
        email="secreto@correo.com",
        numero1="0600",
        numero2="0601",
        numero3="0602",
    )

    resp = client.post("/consulta", data={"documento": "999111"}, follow_redirects=True)
    text = resp.get_data(as_text=True)

    assert "3019999999" not in text
    assert "secreto@correo.com" not in text


def test_consulta_publica_documento_inexistente(client):
    resp = client.post("/consulta", data={"documento": "000000"}, follow_redirects=True)
    assert "No encontramos boletas" in resp.get_data(as_text=True)
