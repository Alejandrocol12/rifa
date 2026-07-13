"""separar cliente de boleta y agregar pagos por premio

Revision ID: b7bbecb5b54c
Revises: 077943316377
Create Date: 2026-07-09 12:48:29.517658

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b7bbecb5b54c'
down_revision = '077943316377'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Tabla nueva para los datos de contacto del cliente, una fila por
    #    documento (es la llave que no se repite entre personas).
    op.create_table(
        'cliente',
        sa.Column('documento', sa.String(length=30), nullable=False),
        sa.Column('nombre', sa.String(length=150), nullable=False),
        sa.Column('telefono', sa.String(length=30), nullable=False),
        sa.Column('direccion', sa.String(length=200), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('fecha_creacion', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('documento'),
    )

    # 2. cliente_documento entra como nullable por ahora: hay que rellenarlo
    #    con datos existentes antes de poder exigir NOT NULL. Los 4 pagos
    #    por premio sí pueden ir NOT NULL de una vez (arrancan en "no pagado").
    with op.batch_alter_table('boleta', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cliente_documento', sa.String(length=30), nullable=True))
        batch_op.add_column(
            sa.Column('pagado_premio1', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        batch_op.add_column(
            sa.Column('pagado_premio2', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        batch_op.add_column(
            sa.Column('pagado_premio3', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        batch_op.add_column(
            sa.Column('pagado_premio4', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )

    # 3. Migrar los datos: por cada documento que ya existía en boleta, crear
    #    un Cliente (con los datos de su boleta más reciente) y enlazar todas
    #    sus boletas a ese cliente.
    conn = op.get_bind()
    filas = conn.execute(
        sa.text(
            "SELECT documento, nombre_cliente, telefono, direccion, email, fecha "
            "FROM boleta ORDER BY fecha ASC"
        )
    ).fetchall()

    clientes_por_documento = {}
    for fila in filas:
        clientes_por_documento[fila.documento] = {
            "nombre": fila.nombre_cliente,
            "telefono": fila.telefono,
            "direccion": fila.direccion,
            "email": fila.email,
        }

    for documento, datos in clientes_por_documento.items():
        conn.execute(
            sa.text(
                "INSERT INTO cliente (documento, nombre, telefono, direccion, email) "
                "VALUES (:documento, :nombre, :telefono, :direccion, :email)"
            ),
            {"documento": documento, **datos},
        )

    conn.execute(sa.text("UPDATE boleta SET cliente_documento = documento"))

    # 4. Ya con todas las boletas enlazadas, exigir NOT NULL, agregar la
    #    llave foránea y eliminar las columnas que ahora viven en Cliente.
    with op.batch_alter_table('boleta', schema=None) as batch_op:
        batch_op.alter_column('cliente_documento', existing_type=sa.String(length=30), nullable=False)
        batch_op.create_foreign_key('fk_boleta_cliente', 'cliente', ['cliente_documento'], ['documento'])
        batch_op.drop_column('direccion')
        batch_op.drop_column('telefono')
        batch_op.drop_column('email')
        batch_op.drop_column('nombre_cliente')
        batch_op.drop_column('documento')

    # 5. Sorteos ya registrados quedan asignados al premio 1 por defecto: no
    #    hay forma de saber retroactivamente a cuál correspondían.
    with op.batch_alter_table('sorteo', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('numero_premio', sa.Integer(), nullable=False, server_default='1')
        )


def downgrade():
    with op.batch_alter_table('sorteo', schema=None) as batch_op:
        batch_op.drop_column('numero_premio')

    with op.batch_alter_table('boleta', schema=None) as batch_op:
        batch_op.add_column(sa.Column('documento', sa.VARCHAR(length=30), nullable=True))
        batch_op.add_column(sa.Column('nombre_cliente', sa.VARCHAR(length=150), nullable=True))
        batch_op.add_column(sa.Column('email', sa.VARCHAR(length=120), nullable=True))
        batch_op.add_column(sa.Column('telefono', sa.VARCHAR(length=30), nullable=True))
        batch_op.add_column(sa.Column('direccion', sa.VARCHAR(length=200), nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE boleta SET "
            "documento = (SELECT documento FROM cliente WHERE cliente.documento = boleta.cliente_documento), "
            "nombre_cliente = (SELECT nombre FROM cliente WHERE cliente.documento = boleta.cliente_documento), "
            "telefono = (SELECT telefono FROM cliente WHERE cliente.documento = boleta.cliente_documento), "
            "direccion = (SELECT direccion FROM cliente WHERE cliente.documento = boleta.cliente_documento), "
            "email = (SELECT email FROM cliente WHERE cliente.documento = boleta.cliente_documento)"
        )
    )

    with op.batch_alter_table('boleta', schema=None) as batch_op:
        batch_op.alter_column('documento', existing_type=sa.VARCHAR(length=30), nullable=False)
        batch_op.alter_column('nombre_cliente', existing_type=sa.VARCHAR(length=150), nullable=False)
        batch_op.alter_column('telefono', existing_type=sa.VARCHAR(length=30), nullable=False)
        batch_op.drop_constraint('fk_boleta_cliente', type_='foreignkey')
        batch_op.drop_column('pagado_premio4')
        batch_op.drop_column('pagado_premio3')
        batch_op.drop_column('pagado_premio2')
        batch_op.drop_column('pagado_premio1')
        batch_op.drop_column('cliente_documento')

    op.drop_table('cliente')
