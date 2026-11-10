import streamlit as st
import psycopg2
import pandas as pd
import io
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Angelmi Market Web POS",
    page_icon="🛒",
    layout="wide"
)

# ==========================================
# 2. CONTROL DE SESIÓN Y AUTENTICACIÓN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_actual" not in st.session_state:
    st.session_state.usuario_actual = None
if "carrito" not in st.session_state:
    st.session_state.carrito = []

# ==========================================
# 3. CONEXIÓN A BASE DE DATOS POSTGRESQL (SUPABASE)
# ==========================================
def get_connection():
    try:
        conn_uri = st.secrets["postgres"]["url"]
    except Exception:
        conn_uri = "postgresql://postgres.wfyyszjwcadmvwghjhqz:angelmi-market2026@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"
    
    return psycopg2.connect(conn_uri)

@st.cache_resource
def verificar_base_de_datos():
    try:
        conn = get_connection()
        cur = conn.cursor()

        ddl_queries = [
            """
            CREATE TABLE IF NOT EXISTS CATEGORIA (
                id_categoria SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                descripcion VARCHAR(255)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS PROVEEDOR (
                id_proveedor SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                ruc_dni VARCHAR(20),
                telefono VARCHAR(20),
                email VARCHAR(100)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS CLIENTE (
                id_cliente SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                documento VARCHAR(20),
                telefono VARCHAR(20),
                direccion VARCHAR(200),
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS EMPLEADO (
                id_empleado SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                cargo VARCHAR(50),
                usuario VARCHAR(50) UNIQUE,
                clave VARCHAR(50),
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS PRODUCTO (
                id_producto SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                precio NUMERIC(10,2) NOT NULL,
                stock INT NOT NULL,
                id_categoria INT REFERENCES CATEGORIA(id_categoria),
                id_proveedor INT REFERENCES PROVEEDOR(id_proveedor),
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS VENTA (
                id_venta SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                id_cliente INT REFERENCES CLIENTE(id_cliente),
                id_empleado INT REFERENCES EMPLEADO(id_empleado),
                total NUMERIC(10,2) NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS DETALLE_VENTA (
                id_detalle SERIAL PRIMARY KEY,
                id_venta SERIAL PRIMARY KEY,
                id_venta INT REFERENCES VENTA(id_venta),
                id_producto INT REFERENCES PRODUCTO(id_producto),
                cantidad INT NOT NULL,
                precio_unitario NUMERIC(10,2) NOT NULL,
                subtotal NUMERIC(10,2) NOT NULL
            );
            """
        ]

        for q in ddl_queries:
            try:
                cur.execute(q)
            except Exception:
                pass

        cur.execute("SELECT COUNT(*) FROM CATEGORIA;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO CATEGORIA (nombre, descripcion) VALUES ('Abarrotes', 'Productos de primera necesidad'), ('Bebidas', 'Gaseosas y jugos'), ('Lácteos', 'Leche, quesos y yogur'), ('Limpieza', 'Artículos para el hogar');")

        cur.execute("SELECT COUNT(*) FROM PROVEEDOR;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO PROVEEDOR (nombre, ruc_dni, telefono, email) VALUES ('Distribuidora Central S.A.C.', '20123456789', '987654321', 'ventas@distribuidora.pe'), ('Comercial San Juan', '20987654321', '912345678', 'contacto@sanjuan.pe');")

        cur.execute("SELECT COUNT(*) FROM CLIENTE;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO CLIENTE (nombre, documento, telefono, direccion) VALUES ('Público General', '00000000', '000000000', 'Tienda Local'), ('Juan Pérez', '45678912', '998877665', 'Av. Central 123');")

        cur.execute("SELECT COUNT(*) FROM EMPLEADO;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO EMPLEADO (nombre, cargo, usuario, clave) VALUES ('Admin Angelmi', 'Administrador', 'admin', 'admin123'), ('Cajero 1', 'Cajero', 'cajero1', '1234');")

        cur.execute("SELECT COUNT(*) FROM PRODUCTO;")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO PRODUCTO (nombre, precio, stock, id_categoria, id_proveedor) VALUES 
                ('Arroz Extra 1kg', 4.50, 50, 1, 1),
                ('Aceite Vegetal 1L', 8.20, 30, 1, 1),
                ('Leche Evaporada 400g', 3.80, 40, 3, 2),
                ('Inca Kola 1.5L', 6.50, 25, 2, 2);
            """)

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        return str(e)

verificar_base_de_datos()

# ==========================================
# 4. FUNCIÓN EXCEL OPTIMIZADA (CACHEADA)
# ==========================================
@st.cache_data(ttl=60)
def generar_reporte_excel():
    conn = get_connection()
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_v = pd.read_sql("SELECT v.id_venta, v.fecha, c.nombre as cliente, e.nombre as empleado, v.total FROM VENTA v LEFT JOIN CLIENTE c ON v.id_cliente = c.id_cliente LEFT JOIN EMPLEADO e ON v.id_empleado = e.id_empleado ORDER BY v.id_venta DESC", conn)
        df_v.to_excel(writer, sheet_name='Ventas', index=False)
        
        df_dv = pd.read_sql("SELECT d.id_detalle, d.id_venta, p.nombre as producto, d.cantidad, d.precio_unitario, d.subtotal FROM DETALLE_VENTA d LEFT JOIN PRODUCTO p ON d.id_producto = p.id_producto", conn)
        df_dv.to_excel(writer, sheet_name='Detalle_Ventas', index=False)
        
        df_p = pd.read_sql("SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre as categoria, pr.nombre as proveedor, p.fecha_registro FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria LEFT JOIN PROVEEDOR pr ON p.id_proveedor = pr.id_proveedor ORDER BY p.id_producto DESC", conn)
        df_p.to_excel(writer, sheet_name='Productos', index=False)
        
        df_c = pd.read_sql("SELECT id_cliente, nombre, documento, telefono, direccion, fecha_registro FROM CLIENTE", conn)
        df_c.to_excel(writer, sheet_name='Clientes', index=False)
        
        df_e = pd.read_sql("SELECT id_empleado, nombre, cargo, usuario, fecha_registro FROM EMPLEADO", conn)
        df_e.to_excel(writer, sheet_name='Empleados', index=False)
        
        df_cat = pd.read_sql("SELECT * FROM CATEGORIA", conn)
        df_cat.to_excel(writer, sheet_name='Categorias', index=False)
        
        df_prv = pd.read_sql("SELECT * FROM PROVEEDOR", conn)
        df_prv.to_excel(writer, sheet_name='Proveedores', index=False)
        
    conn.close()
    return output.getvalue()

# ==========================================
# 5. FORMULARIO DE LOGIN
# ==========================================
def validar_login(usuario, clave):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id_empleado, nombre, cargo FROM EMPLEADO WHERE usuario = %s AND clave = %s", (usuario, clave))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res

if not st.session_state.autenticado:
    st.markdown("<h2 style='text-align: center;'>🔐 Acceso al Sistema POS Angelmi Market</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        with st.form("form_login"):
            user_input = st.text_input("Usuario")
            pass_input = st.text_input("Contraseña", type="password")
            btn_login = st.form_submit_button("Iniciar Sesión", use_container_width=True)
            if btn_login:
                user_data = validar_login(user_input, pass_input)
                if user_data:
                    st.session_state.autenticado = True
                    st.session_state.usuario_actual = {"id": user_data[0], "nombre": user_data[1], "cargo": user_data[2]}
                    st.success(f"Bienvenido {user_data[1]}")
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
    st.stop()

# ==========================================
# 6. BARRA LATERAL Y NAVEGACIÓN
# ==========================================
st.sidebar.title("🏪 Angelmi Market")
st.sidebar.caption(f"👤 Conectado: **{st.session_state.usuario_actual['nombre']}** ({st.session_state.usuario_actual['cargo']})")

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.carrito = []
    st.rerun()

st.sidebar.divider()

st.sidebar.download_button(
    label="📊 Descargar Respaldo (Excel)",
    data=generar_reporte_excel(),
    file_name=f"Respaldo_AngelmiMarket_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)

st.sidebar.divider()

opcion = st.sidebar.radio(
    "Menú de Opciones",
    ["🛒 Punto de Venta (POS)", "📦 Gestión de Productos", "📁 Categorías y Proveedores", "👥 Clientes y Empleados", "📊 Histórico de Ventas", "📐 Modelo Entidad-Relación (MER)"]
)

# ==========================================
# MÓDULO 1: POS
# ==========================================
if opcion == "🛒 Punto de Venta (POS)":
    st.title("🛒 Punto de Venta")
    conn = get_connection()
    df_productos = pd.read_sql("SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre as categoria FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria", conn)
    df_clientes = pd.read_sql("SELECT id_cliente, nombre FROM CLIENTE", conn)
    conn.close()

    col_izq, col_der = st.columns([1, 1])
    with col_izq:
        st.subheader("1. Selección de Producto")
        prod_sel = st.selectbox(
            "Buscar Producto:",
            options=df_productos['id_producto'].tolist(),
            format_func=lambda x: f"{df_productos[df_productos['id_producto']==x]['nombre'].values[0]} - S/ {df_productos[df_productos['id_producto']==x]['precio'].values[0]:.2f} (Stock: {df_productos[df_productos['id_producto']==x]['stock'].values[0]})"
        )
        info_prod = df_productos[df_productos['id_producto'] == prod_sel].iloc[0]
        cantidad = st.number_input("Cantidad:", min_value=1, max_value=int(info_prod['stock']) if info_prod['stock'] > 0 else 1, value=1)
        
        if st.button("➕ Agregar al Carrito", use_container_width=True):
            if info_prod['stock'] < cantidad:
                st.error("Stock insuficiente.")
            else:
                encontrado = False
                for item in st.session_state.carrito:
                    if item['id_producto'] == info_prod['id_producto']:
                        if item['cantidad'] + cantidad <= info_prod['stock']:
                            item['cantidad'] += cantidad
                            item['subtotal'] = item['cantidad'] * item['precio']
                            encontrado = True
                            st.success(f"Se actualizó la cantidad de {info_prod['nombre']}.")
                        else:
                            st.warning("No hay suficiente stock disponible.")
                            encontrado = True
                        break
                if not strain := encontrado:
                    st.session_state.carrito.append({
                        'id_producto': int(info_prod['id_producto']),
                        'nombre': str(info_prod['nombre']),
                        'precio': float(info_prod['precio']),
                        'cantidad': int(cantidad),
                        'subtotal': float(info_prod['precio'] * cantidad)
                    })
                    st.success(f"{info_prod['nombre']} agregado al carrito.")

    with col_der:
        st.subheader("2. Detalle de la Venta")
        id_cli = st.selectbox("Cliente:", options=df_clientes['id_cliente'].tolist(), format_func=lambda x: df_clientes[df_clientes['id_cliente']==x]['nombre'].values[0])
        st.text_input("Atendido por:", value=st.session_state.usuario_actual['nombre'], disabled=True)
        
        if st.session_state.carrito:
            df_cart = pd.DataFrame(st.session_state.carrito)
            st.dataframe(df_cart[['nombre', 'precio', 'cantidad', 'subtotal']], use_container_width=True)
            total_venta = df_cart['subtotal'].sum()
            st.markdown(f"### **Total a Pagar: S/ {total_venta:.2f}**")
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Procesar Venta", use_container_width=True, type="primary"):
                    try:
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute("INSERT INTO VENTA (id_cliente, id_empleado, total) VALUES (%s, %s, %s) RETURNING id_venta;",
                                    (id_cli, st.session_state.usuario_actual['id'], total_venta))
                        id_venta = cur.fetchone()[0]
                        
                        for item in st.session_state.carrito:
                            cur.execute("INSERT INTO DETALLE_VENTA (id_venta, id_producto, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s);",
                                        (id_venta, item['id_producto'], item['cantidad'], item['precio'], item['subtotal']))
                            cur.execute("UPDATE PRODUCTO SET stock = stock - %s WHERE id_producto = %s;", (item['cantidad'], item['id_producto']))
                        conn.commit()
                        cur.close()
                        conn.close()
                        st.session_state.carrito = []
                        st.cache_data.clear() # Limpia el caché del Excel al hacer una venta nueva
                        st.balloons()
                        st.success(f"🎉 ¡Venta N° {id_venta} registrada con éxito!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error procesando venta: {e}")
            with c2:
                if st.button("🗑️ Vaciar Carrito", use_container_width=True):
                    st.session_state.carrito = []
                    st.rerun()
        else:
            st.info("El carrito de compras está vacío.")

# ==========================================
# MÓDULO 2: GESTIÓN DE PRODUCTOS
# ==========================================
elif opcion == "📦 Gestión de Productos":
    st.title("📦 Gestión de Inventario y Productos")
    conn = get_connection()
    df_prod = pd.read_sql("SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre as categoria, pr.nombre as proveedor, p.fecha_registro FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria LEFT JOIN PROVEEDOR pr ON p.id_proveedor = pr.id_proveedor ORDER BY p.id_producto DESC", conn)
    df_cat = pd.read_sql("SELECT id_categoria, nombre FROM CATEGORIA", conn)
    df_prov = pd.read_sql("SELECT id_proveedor, nombre FROM PROVEEDOR", conn)
    conn.close()

    st.subheader("Listado de Productos en Sistema")
    st.dataframe(df_prod, use_container_width=True)

    with st.expander("➕ Registrar Nuevo Producto"):
        with st.form("form_nuevo_prod"):
            nom = st.text_input("Nombre del Producto")
            pre = st.number_input("Precio (S/)", min_value=0.1, value=1.0, step=0.5)
            stk = st.number_input("Stock Inicial", min_value=1, value=10, step=1)
            cat = st.selectbox("Categoría", options=df_cat['id_categoria'].tolist(), format_func=lambda x: df_cat[df_cat['id_categoria']==x]['nombre'].values[0])
            prv = st.selectbox("Proveedor", options=df_prov['id_proveedor'].tolist(), format_func=lambda x: df_prov[df_prov['id_proveedor']==x]['nombre'].values[0])
            
            if st.form_submit_button("Guardar Producto"):
                if nom:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO PRODUCTO (nombre, precio, stock, id_categoria, id_proveedor) VALUES (%s, %s, %s, %s, %s)",
                                (nom, pre, stk, cat, prv))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.cache_data.clear()
                    st.success("Producto registrado exitosamente.")
                    st.rerun()
                else:
                    st.warning("El nombre del producto es obligatorio.")

# ==========================================
# MÓDULO 3: CATEGORÍAS Y PROVEEDORES
# ==========================================
elif opcion == "📁 Categorías y Proveedores":
    st.title("📁 Categorías y Proveedores")
    col1, col2 = st.columns(2)
    conn = get_connection()
    df_cat = pd.read_sql("SELECT * FROM CATEGORIA", conn)
    df_prov = pd.read_sql("SELECT * FROM PROVEEDOR", conn)
    conn.close()

    with col1:
        st.subheader("Categorías")
        st.dataframe(df_cat, use_container_width=True)
        with st.form("form_cat"):
            nom_cat = st.text_input("Nombre de Categoría")
            desc_cat = st.text_input("Descripción")
            if st.form_submit_button("Agregar Categoría"):
                if nom_cat:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO CATEGORIA (nombre, descripcion) VALUES (%s, %s)", (nom_cat, desc_cat))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.cache_data.clear()
                    st.success("Categoría agregada.")
                    st.rerun()

    with col2:
        st.subheader("Proveedores")
        st.dataframe(df_prov, use_container_width=True)
        with st.form("form_prov"):
            nom_prv = st.text_input("Nombre del Proveedor")
            ruc = st.text_input("RUC / DNI")
            tel = st.text_input("Teléfono")
            email = st.text_input("Email")
            if st.form_submit_button("Agregar Proveedor"):
                if nom_prv:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO PROVEEDOR (nombre, ruc_dni, telefono, email) VALUES (%s, %s, %s, %s)", (nom_prv, ruc, tel, email))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.cache_data.clear()
                    st.success("Proveedor agregado.")
                    st.rerun()

# ==========================================
# MÓDULO 4: CLIENTES Y EMPLEADOS
# ==========================================
elif opcion == "👥 Clientes y Empleados":
    st.title("👥 Clientes y Empleados")
    col1, col2 = st.columns(2)
    conn = get_connection()
    df_cli = pd.read_sql("SELECT id_cliente, nombre, documento, telefono, direccion, fecha_registro FROM CLIENTE ORDER BY id_cliente DESC", conn)
    df_emp = pd.read_sql("SELECT id_empleado, nombre, cargo, usuario, fecha_registro FROM EMPLEADO ORDER BY id_empleado DESC", conn)
    conn.close()

    with col1:
        st.subheader("Clientes")
        st.dataframe(df_cli, use_container_width=True)
        with st.form("form_cli"):
            nom = st.text_input("Nombre Completo")
            doc = st.text_input("DNI / RUC")
            tel = st.text_input("Teléfono")
            dir_cli = st.text_input("Dirección")
            if st.form_submit_button("Registrar Cliente"):
                if nom:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO CLIENTE (nombre, documento, telefono, direccion) VALUES (%s, %s, %s, %s)", (nom, doc, tel, dir_cli))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.cache_data.clear()
                    st.success("Cliente registrado.")
                    st.rerun()

    with col2:
        st.subheader("Empleados")
        st.dataframe(df_emp, use_container_width=True)
        with st.form("form_emp"):
            nom_emp = st.text_input("Nombre del Empleado")
            cargo = st.selectbox("Cargo", ["Administrador", "Cajero", "Almacenero"])
            user = st.text_input("Usuario")
            passw = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Registrar Empleado"):
                if nom_emp and user:
                    try:
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute("INSERT INTO EMPLEADO (nombre, cargo, usuario, clave) VALUES (%s, %s, %s, %s)", (nom_emp, cargo, user, passw))
                        conn.commit()
                        cur.close()
                        conn.close()
                        st.cache_data.clear()
                        st.success("Empleado registrado.")
                        st.rerun()
                    except Exception as e:
                        st.error("El usuario ya existe o hubo un error al registrar.")

# ==========================================
# MÓDULO 5: HISTÓRICO DE VENTAS
# ==========================================
elif opcion == "📊 Histórico de Ventas":
    st.title("📊 Reporte e Histórico de Ventas")
    conn = get_connection()
    df_ventas = pd.read_sql("SELECT v.id_venta, v.fecha, c.nombre as cliente, e.nombre as empleado, v.total FROM VENTA v LEFT JOIN CLIENTE c ON v.id_cliente = c.id_cliente LEFT JOIN EMPLEADO e ON v.id_empleado = e.id_empleado ORDER BY v.id_venta DESC", conn)
    df_detalles = pd.read_sql("SELECT d.id_venta, p.nombre as producto, d.cantidad, d.precio_unitario, d.subtotal FROM DETALLE_VENTA d LEFT JOIN PRODUCTO p ON d.id_producto = p.id_producto", conn)
    conn.close()

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Ventas (S/)", f"S/ {df_ventas['total'].sum():.2f}" if not df_ventas.empty else "S/ 0.00")
    m2.metric("N° Transacciones", len(df_ventas))
    m3.metric("Ticket Promedio", f"S/ {df_ventas['total'].mean():.2f}" if not df_ventas.empty else "S/ 0.00")

    st.subheader("Registro de Comprobantes")
    if not df_ventas.empty:
        st.dataframe(df_ventas, use_container_width=True)
        st.subheader("🔍 Consultar Detalle de una Venta")
        id_v_sel = st.selectbox("Seleccione ID de Venta:", df_ventas['id_venta'].tolist())
        st.dataframe(df_detalles[df_detalles['id_venta'] == id_v_sel][['producto', 'cantidad', 'precio_unitario', 'subtotal']], use_container_width=True)
    else:
        st.info("Aún no se han realizado ventas.")

# ==========================================
# MÓDULO 6: MODELO ENTIDAD-RELACIÓN (MER)
# ==========================================
elif opcion == "📐 Modelo Entidad-Relación (MER)":
    st.title("📐 Diagrama Entidad - Relación (MER)")
    st.markdown("Representación relacional completa de la base de datos **AngelmiMarketDB**.")
    
    graphviz_code = """
    digraph MER {
        rankdir=LR;
        node [shape=rectangle, style=filled, fillcolor="#EBF5FB", color="#1F618D", fontname="Helvetica"];
        edge [color="#2E4053", fontname="Helvetica", fontsize=10];

        CATEGORIA [label="CATEGORIA\\n- id_categoria (PK)\\n- nombre\\n- descripcion"];
        PROVEEDOR [label="PROVEEDOR\\n- id_proveedor (PK)\\n- nombre\\n- ruc_dni\\n- telefono\\n- email"];
        CLIENTE [label="CLIENTE\\n- id_cliente (PK)\\n- nombre\\n- documento\\n- fecha_registro"];
        EMPLEADO [label="EMPLEADO\\n- id_empleado (PK)\\n- nombre\\n- usuario\\n- clave\\n- fecha_registro"];
        PRODUCTO [label="PRODUCTO\\n- id_producto (PK)\\n- nombre\\n- precio\\n- stock\\n- id_categoria (FK)\\n- id_proveedor (FK)\\n- fecha_registro"];
        VENTA [label="VENTA\\n- id_venta (PK)\\n- fecha\\n- id_cliente (FK)\\n- id_empleado (FK)\\n- total"];
        DETALLE_VENTA [label="DETALLE_VENTA\\n- id_detalle (PK)\\n- id_venta (FK)\\n- id_producto (FK)\\n- cantidad\\n- precio_unitario\\n- subtotal"];

        CATEGORIA -> PRODUCTO [label="1 : N"];
        PROVEEDOR -> PRODUCTO [label="1 : N"];
        PRODUCTO -> DETALLE_VENTA [label="1 : N"];
        VENTA -> DETALLE_VENTA [label="1 : N"];
        CLIENTE -> VENTA [label="1 : N"];
        EMPLEADO -> VENTA [label="1 : N"];
    }
    """
    st.graphviz_chart(graphviz_code)
