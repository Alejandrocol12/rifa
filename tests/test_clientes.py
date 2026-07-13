from models import Boleta, Cliente, Vendedor
from tests.conftest import login
from tests.test_app import datos_boleta
from tests.test_features import crear_boleta


def crear_vendedor_dos(db):
    otro = Vendedor(username="vend2", nombre="Vendedor Dos", is_admin=False)
    otro.set_password("clave123")
    db.session.add(otro)
    db.session.commit()
    return otro


def test_api_buscar_cliente_encontrado(client, vendedor):
    crear_boleta(client, documento="CLI-001", numero1="0700", numero2="0701", numero3="0702")

    login(client, "vend1", "clave123")
    resp = client.get("/api/cliente/CLI-001")
    data = resp.get_json()

    assert data["encontrado"] is True
    assert data["nombre_cliente"] == "Juan Perez"
    assert data["telefono"] == "3000000000"
    assert data["total_boletas"] == 1


def test_api_buscar_cliente_no_encontrado(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.get("/api/cliente/NO-EXISTE")
    assert resp.get_json() == {"encontrado": False}


def test_api_buscar_cliente_no_visible_para_otro_vendedor(client, vendedor, db):
    crear_boleta(client, documento="CLI-002", numero1="0710", numero2="0711", numero3="0712")
    crear_vendedor_dos(db)

    login(client, "vend2", "clave123")
    resp = client.get("/api/cliente/CLI-002")
    assert resp.get_json() == {"encontrado": False}


def test_api_buscar_cliente_admin_ve_cualquier_vendedor(client, vendedor, admin):
    crear_boleta(client, documento="CLI-002b", numero1="0713", numero2="0714", numero3="0715")

    login(client, "admin1", "clave123")
    resp = client.get("/api/cliente/CLI-002b")
    assert resp.get_json()["encontrado"] is True


def test_registrar_mismo_documento_no_duplica_cliente_entre_vendedores(client, vendedor, db):
    crear_vendedor_dos(db)
    crear_boleta(
        client, documento="CLI-006", nombre_cliente="Original",
        numero1="0800", numero2="0801", numero3="0802",
    )

    # vend2 no ve el cliente en su búsqueda (está fuera de su alcance)...
    login(client, "vend2", "clave123")
    assert client.get("/api/cliente/CLI-006").get_json() == {"encontrado": False}

    # ...pero si igual le vende, no se duplica el registro del cliente:
    # se reutiliza el mismo Cliente y solo se agrega una boleta nueva.
    client.post(
        "/registrar",
        data=datos_boleta(
            documento="CLI-006", nombre_cliente="Original Actualizado",
            numero1="0810", numero2="0811", numero3="0812",
        ),
        follow_redirects=True,
    )

    assert Cliente.query.filter_by(documento="CLI-006").count() == 1
    assert Boleta.query.filter_by(cliente_documento="CLI-006").count() == 2
    cliente = Cliente.query.get("CLI-006")
    assert cliente.nombre == "Original Actualizado"


def test_clientes_agrupa_boletas_del_mismo_documento(client, vendedor):
    crear_boleta(client, documento="CLI-003", numero1="0720", numero2="0721", numero3="0722")
    crear_boleta(client, documento="CLI-003", numero1="0730", numero2="0731", numero3="0732")

    login(client, "vend1", "clave123")
    resp = client.get("/clientes")
    text = resp.get_data(as_text=True)

    assert "1 cliente" in text
    assert ">2<" in text or "2</td>" in text


def test_clientes_busqueda_por_nombre(client, vendedor):
    crear_boleta(client, nombre_cliente="Pedro Gomez", documento="CLI-004", numero1="0740", numero2="0741", numero3="0742")

    login(client, "vend1", "clave123")
    resp = client.get("/clientes?q=Pedro")
    assert "Pedro Gomez" in resp.get_data(as_text=True)

    resp2 = client.get("/clientes?q=NoExiste")
    assert "No hay clientes registrados" in resp2.get_data(as_text=True)


def test_clientes_no_incluye_los_de_otro_vendedor(client, vendedor, db):
    crear_vendedor_dos(db)
    crear_boleta(client, nombre_cliente="Solo De Vend1", documento="CLI-007", numero1="0820", numero2="0821", numero3="0822")

    login(client, "vend2", "clave123")
    resp = client.get("/clientes")
    assert "Solo De Vend1" not in resp.get_data(as_text=True)


def test_cliente_detalle_lista_todas_sus_boletas(client, vendedor):
    crear_boleta(client, documento="CLI-005", numero1="0750", numero2="0751", numero3="0752")
    crear_boleta(client, documento="CLI-005", numero1="0760", numero2="0761", numero3="0762")

    login(client, "vend1", "clave123")
    resp = client.get("/clientes/CLI-005")
    text = resp.get_data(as_text=True)

    assert "0750" in text and "0760" in text
    assert "2" in text  # total de boletas en las tarjetas de resumen


def test_cliente_detalle_documento_inexistente_redirige(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.get("/clientes/NO-EXISTE", follow_redirects=True)
    assert "No se encontró ningún cliente" in resp.get_data(as_text=True)


def test_cliente_detalle_no_visible_para_otro_vendedor(client, vendedor, db):
    crear_vendedor_dos(db)
    crear_boleta(client, documento="CLI-008", numero1="0830", numero2="0831", numero3="0832")

    login(client, "vend2", "clave123")
    resp = client.get("/clientes/CLI-008", follow_redirects=True)
    assert "No se encontró ningún cliente" in resp.get_data(as_text=True)
