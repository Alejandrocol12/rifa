from models import Boleta, Cliente, HistorialPago, NumeroAsignado, Vendedor
from tests.conftest import login
from tests.test_features import crear_boleta


# --- Auditoría de pagos ---


def test_marcar_pago_crea_historial(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True)

    historial = HistorialPago.query.filter_by(boleta_id=boleta.id).all()
    assert len(historial) == 1
    assert historial[0].numero_premio == 1
    assert historial[0].marcado is True
    assert historial[0].vendedor_id == vendedor.id


def test_solo_registra_historial_de_cambios_reales(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True)
    # Reenviar el mismo estado (premio1 marcado) no debería crear una segunda fila.
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True)

    assert HistorialPago.query.filter_by(boleta_id=boleta.id).count() == 1


def test_desmarcar_pago_tambien_queda_en_el_historial(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio2": "on"}, follow_redirects=True)
    client.post(f"/boletas/{boleta.id}/pago", data={}, follow_redirects=True)

    historial = HistorialPago.query.filter_by(boleta_id=boleta.id, numero_premio=2).order_by(HistorialPago.id).all()
    assert len(historial) == 2
    assert historial[0].marcado is True
    assert historial[1].marcado is False


def test_historial_de_pago_visible_en_detalle(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio3": "on"}, follow_redirects=True)

    resp = client.get(f"/boletas/{boleta.id}")
    text = resp.get_data(as_text=True)
    assert "Vendedor Uno" in text
    assert "marcó como pagado" in text
    assert "Premio 3" in text


# --- Anular boleta ---


def test_anular_boleta_libera_los_numeros(client, vendedor):
    boleta = crear_boleta(client, numero1="0900", numero2="0901", numero3="0902")

    login(client, "vend1", "clave123")
    resp = client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)

    assert "anulada" in resp.get_data(as_text=True).lower()
    actualizada = Boleta.query.get(boleta.id)
    assert actualizada.anulada is True
    assert actualizada.numeros_anulados == "0900, 0901, 0902"
    assert NumeroAsignado.query.filter(NumeroAsignado.numero.in_(["0900", "0901", "0902"])).count() == 0


def test_numero_liberado_se_puede_volver_a_vender(client, vendedor):
    boleta = crear_boleta(client, documento="ANULAR-001", numero1="0910", numero2="0911", numero3="0912")

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)

    resp = client.post(
        "/registrar",
        data={
            "nombre_cliente": "Otro Cliente",
            "documento": "ANULAR-002",
            "telefono": "3000000001",
            "direccion": "",
            "email": "",
            "numero1": "0910",
            "numero2": "0920",
            "numero3": "0921",
        },
        follow_redirects=True,
    )
    assert "Boleta registrada con éxito" in resp.get_data(as_text=True)


def test_no_se_puede_anular_dos_veces(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)
    resp = client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)

    assert "ya estaba anulada" in resp.get_data(as_text=True)


def test_no_se_puede_pagar_una_boleta_anulada(client, vendedor):
    boleta = crear_boleta(client)

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)
    resp = client.post(f"/boletas/{boleta.id}/pago", data={"pagado_premio1": "on"}, follow_redirects=True)

    assert "está anulada" in resp.get_data(as_text=True)
    assert Boleta.query.get(boleta.id).pagado_premio1 is False


def test_otro_vendedor_no_puede_anular(client, vendedor, db):
    otro = Vendedor(username="vend2", nombre="Vendedor Dos", is_admin=False)
    otro.set_password("clave123")
    db.session.add(otro)
    db.session.commit()

    boleta = crear_boleta(client)

    login(client, "vend2", "clave123")
    resp = client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)
    assert "No tienes permiso" in resp.get_data(as_text=True)
    assert Boleta.query.get(boleta.id).anulada is False


def test_boleta_anulada_excluida_de_consulta_publica(client, vendedor):
    boleta = crear_boleta(client, documento="ANULAR-CONSULTA", numero1="0930", numero2="0931", numero3="0932")

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)
    client.get("/logout")

    resp = client.post("/consulta", data={"documento": "ANULAR-CONSULTA"}, follow_redirects=True)
    assert "No encontramos boletas" in resp.get_data(as_text=True)


def test_boleta_anulada_no_cuenta_en_filtro_de_pago_pero_aparece_en_todas(client, vendedor):
    boleta = crear_boleta(client, documento="ANULAR-FILTRO", numero1="0940", numero2="0941", numero3="0942")

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)

    resp_pendiente = client.get("/boletas?pago=pendiente")
    assert "ANULAR-FILTRO" not in resp_pendiente.get_data(as_text=True)

    resp_todas = client.get("/boletas")
    text_todas = resp_todas.get_data(as_text=True)
    assert "ANULAR-FILTRO" in text_todas
    assert "ANULADA" in text_todas


def test_csv_incluye_columna_anulada(client, vendedor, admin):
    boleta = crear_boleta(client, documento="ANULAR-CSV", numero1="0950", numero2="0951", numero3="0952")

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta.id}/anular", follow_redirects=True)
    client.get("/logout")

    login(client, "admin1", "clave123")
    resp = client.get("/admin/exportar.csv")
    text = resp.get_data(as_text=True)
    assert "Anulada" in text
    assert "Sí" in text


def test_dashboard_no_cuenta_boletas_anuladas(client, vendedor):
    crear_boleta(client, documento="DASH-001", numero1="0980", numero2="0981", numero3="0982")
    boleta_anulada = crear_boleta(client, documento="DASH-002", numero1="0990", numero2="0991", numero3="0992")

    login(client, "vend1", "clave123")
    client.post(f"/boletas/{boleta_anulada.id}/anular", follow_redirects=True)

    resp = client.get("/")
    text = resp.get_data(as_text=True)
    assert '<span class="card-value">1</span>' in text


# --- Fusionar clientes ---


def test_admin_fusiona_clientes_duplicados(client, vendedor, admin):
    crear_boleta(client, documento="FUS-001", numero1="0960", numero2="0961", numero3="0962")
    crear_boleta(client, documento="FUS-002", numero1="0970", numero2="0971", numero3="0972")

    login(client, "admin1", "clave123")
    resp = client.post(
        "/admin/clientes/fusionar",
        data={"documento_conservar": "FUS-001", "documento_fusionar": "FUS-002"},
        follow_redirects=True,
    )

    assert "fusionó" in resp.get_data(as_text=True)
    assert Cliente.query.get("FUS-002") is None
    assert Cliente.query.get("FUS-001") is not None
    assert Boleta.query.filter_by(cliente_documento="FUS-001").count() == 2


def test_fusionar_documento_inexistente_falla(client, admin):
    login(client, "admin1", "clave123")
    resp = client.post(
        "/admin/clientes/fusionar",
        data={"documento_conservar": "NO-EXISTE-1", "documento_fusionar": "NO-EXISTE-2"},
        follow_redirects=True,
    )
    assert "No se encontró" in resp.get_data(as_text=True)


def test_vendedor_no_admin_no_puede_fusionar(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.post(
        "/admin/clientes/fusionar",
        data={"documento_conservar": "A", "documento_fusionar": "B"},
        follow_redirects=True,
    )
    assert "No tienes permiso" in resp.get_data(as_text=True)


# --- Recuperar acceso (CLI) ---


def test_reset_admin_password_genera_clave_nueva(app, vendedor, db):
    clave_original = vendedor.password_hash
    runner = app.test_cli_runner()

    resultado = runner.invoke(args=["reset-admin-password", "vend1"])

    assert "Contraseña restablecida" in resultado.output
    actualizado = Vendedor.query.filter_by(username="vend1").first()
    assert actualizado.password_hash != clave_original


def test_reset_admin_password_reactiva_cuenta_desactivada(app, vendedor, db):
    vendedor.activo = False
    db.session.commit()

    runner = app.test_cli_runner()
    runner.invoke(args=["reset-admin-password", "vend1"])

    assert Vendedor.query.filter_by(username="vend1").first().activo is True


def test_reset_admin_password_usuario_inexistente(app):
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["reset-admin-password", "no-existe"])
    assert "No existe ningún vendedor" in resultado.output
