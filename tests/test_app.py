from models import Boleta, Cliente, NumeroAsignado, Vendedor
from tests.conftest import login


def datos_boleta(**overrides):
    data = {
        "nombre_cliente": "Juan Perez",
        "documento": "123",
        "telefono": "3000000000",
        "direccion": "",
        "email": "",
        "numero1": "0001",
        "numero2": "0002",
        "numero3": "0003",
    }
    data.update(overrides)
    return data


def test_login_success(client, vendedor):
    resp = login(client, "vend1", "clave123")
    assert resp.status_code == 200
    assert "Resumen de la rifa" in resp.get_data(as_text=True)


def test_login_wrong_password(client, vendedor):
    resp = login(client, "vend1", "incorrecta")
    assert "incorrectos" in resp.get_data(as_text=True)


def test_login_inactive_vendedor_blocked(client, vendedor, db):
    vendedor.activo = False
    db.session.commit()
    resp = login(client, "vend1", "clave123")
    assert "Resumen de la rifa" not in resp.get_data(as_text=True)


def test_registrar_creates_boleta(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.post("/registrar", data=datos_boleta(), follow_redirects=True)

    assert "Boleta registrada con éxito" in resp.get_data(as_text=True)
    boleta = Boleta.query.filter_by(cliente_documento="123").first()
    assert boleta is not None
    assert {n.numero for n in boleta.numeros} == {"0001", "0002", "0003"}


def test_registrar_rejects_numero_ya_tomado(client, vendedor):
    login(client, "vend1", "clave123")
    client.post("/registrar", data=datos_boleta(numero1="0010"), follow_redirects=True)
    resp = client.post(
        "/registrar",
        data=datos_boleta(documento="999", numero1="0010", numero2="0011", numero3="0012"),
        follow_redirects=True,
    )

    assert "ya fue tomado" in resp.get_data(as_text=True)
    assert NumeroAsignado.query.filter_by(numero="0010").count() == 1
    assert Boleta.query.filter_by(cliente_documento="999").count() == 0


def test_registrar_rechaza_numeros_repetidos(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.post(
        "/registrar",
        data=datos_boleta(numero1="0001", numero2="0001", numero3="0002"),
        follow_redirects=True,
    )
    assert "deben ser diferentes" in resp.get_data(as_text=True)


def test_registrar_rechaza_email_invalido(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.post("/registrar", data=datos_boleta(email="no-es-un-correo"), follow_redirects=True)
    assert "correo electrónico" in resp.get_data(as_text=True)
    assert Boleta.query.count() == 0


def test_vendedor_no_puede_acceder_a_admin(client, vendedor):
    login(client, "vend1", "clave123")
    resp = client.get("/admin/vendedores", follow_redirects=True)
    assert "No tienes permiso" in resp.get_data(as_text=True)


def test_admin_username_duplicado_muestra_error(client, admin, db):
    login(client, "admin1", "clave123")
    client.post(
        "/admin/vendedores",
        data={"username": "dup", "nombre": "Uno", "password": "x"},
        follow_redirects=True,
    )
    resp = client.post(
        "/admin/vendedores",
        data={"username": "dup", "nombre": "Dos", "password": "y"},
        follow_redirects=True,
    )

    assert "ya existe" in resp.get_data(as_text=True)
    assert Vendedor.query.filter_by(username="dup").count() == 1


def test_csv_export_escapa_formula_injection(client, admin, vendedor, db):
    cliente = Cliente(documento="1", nombre="=cmd|'/c calc'!A1", telefono="1")
    db.session.add(cliente)
    boleta = Boleta(cliente_documento="1", vendedor_id=vendedor.id)
    db.session.add(boleta)
    db.session.flush()
    db.session.add(NumeroAsignado(numero="9999", boleta_id=boleta.id))
    db.session.commit()

    login(client, "admin1", "clave123")
    resp = client.get("/admin/exportar.csv")

    assert "'=cmd" in resp.get_data(as_text=True)


def test_boletas_paginacion(client, admin, vendedor, db, monkeypatch):
    import routes

    monkeypatch.setattr(routes, "BOLETAS_POR_PAGINA", 2)

    for i in range(5):
        db.session.add(Cliente(documento=str(i), nombre=f"Cliente {i}", telefono="1"))
        b = Boleta(cliente_documento=str(i), vendedor_id=vendedor.id)
        db.session.add(b)
        db.session.flush()
        db.session.add(NumeroAsignado(numero=f"{i:04d}", boleta_id=b.id))
    db.session.commit()

    login(client, "admin1", "clave123")
    resp1 = client.get("/boletas")
    assert "Página 1 de 3" in resp1.get_data(as_text=True)

    resp2 = client.get("/boletas?page=2")
    assert "Página 2 de 3" in resp2.get_data(as_text=True)


def test_api_estado_numero(client, vendedor):
    login(client, "vend1", "clave123")
    client.post("/registrar", data=datos_boleta(numero1="0500"), follow_redirects=True)

    libre = client.get("/api/numero/0501").get_json()
    ocupado = client.get("/api/numero/0500").get_json()
    invalido = client.get("/api/numero/abc")

    assert libre == {"valido": True, "libre": True}
    assert ocupado == {"valido": True, "libre": False}
    assert invalido.status_code == 400
