# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt
from frappe.model.naming import make_autoname

class RegistrodeCierredeMovimiento(Document):

    def autoname(self):
        # 1) Obtener la abreviatura y el color de la sucursal (Branch)
        if self.sucursal:
            # get_value con lista de campos devuelve una tupla
            branch_abbr, branch_color = frappe.db.get_value(
                "Branch",
                self.sucursal,
                ["custom_abreviatura", "custom_color"]
            ) or ("NA", "#000000")
        else:
            # Si no hay sucursal, asignamos valores por defecto
            branch_abbr = "NA"
            branch_color = "#000000"

        # 2) Generar la parte numérica con 5 dígitos (00001, 00002, etc.)
        numeric_part = make_autoname(".####")

        # 3) Construir el nombre final
        self.name = f"CIERRE-{branch_abbr}-{numeric_part}"

        # 4) Guardar el color en un campo del doc
        self.color = branch_color
        
    def validate(self):
        # Asegurarnos de tener objetos date
        self.fecha_inicio = getdate(self.fecha_inicio)
        self.fecha_final = getdate(self.fecha_final)

        # Validar que la fecha inicial sea menor o igual a la fecha final
        if self.fecha_inicio > self.fecha_final:
            frappe.throw("La fecha inicial debe ser antes o igual a la fecha final.")

        # ***** VALIDACIÓN DE QUE NO CRUCE MESES *****
        if (self.fecha_inicio.month != self.fecha_final.month) or (self.fecha_inicio.year != self.fecha_final.year):
            frappe.throw(
                f"No se permite un cierre que abarque meses distintos. "
                f"Este cierre va de {self.fecha_inicio} a {self.fecha_final}, lo cual cruza de mes."
            )

        # Validacion de traslapes optimizada
        overlap = frappe.db.sql("""
            SELECT name, fecha_inicio, fecha_final FROM `tabRegistro de Cierre de Movimiento`
            WHERE sucursal = %s
            AND docstatus = 1
            AND name != %s
            AND (
                (fecha_inicio BETWEEN %s AND %s) OR
                (fecha_final BETWEEN %s AND %s) OR
                (fecha_inicio <= %s AND fecha_final >= %s)
            )
            LIMIT 1
        """, (
            self.sucursal, self.name or "new",
            self.fecha_inicio, self.fecha_final,
            self.fecha_inicio, self.fecha_final,
            self.fecha_inicio, self.fecha_final
        ), as_dict=True)

        if overlap:
            cierre = overlap[0]
            frappe.throw(
                f"El rango de fechas ({self.fecha_inicio} - {self.fecha_final}) "
                f"se traslapa con un cierre existente ({cierre.name}): "
                f"{cierre.fecha_inicio} - {cierre.fecha_final}."
            )

        # Validacion de orden cronologico (no cerrar antes del primer cierre)
        # Obtenemos solo el primer cierre por fecha
        primer_cierre_fecha = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={"sucursal": self.sucursal, "docstatus": 1},
            fieldname="fecha_inicio",
            order_by="fecha_inicio asc"
        )
        
        if primer_cierre_fecha:
            primer_cierre_fecha = getdate(primer_cierre_fecha)
            if self.fecha_inicio < primer_cierre_fecha:
                frappe.throw(
                    f"No se puede hacer un cierre antes del primer cierre registrado ({primer_cierre_fecha})."
                )
        
        # Poblar tablas y calcular totales automáticamente
        self.poblar_y_calcular()

    def poblar_y_calcular(self):
        # Solo poblar y calcular si es un borrador. 
        # Si ya está sometido (1) o cancelado (2), no tocamos las tablas.
        if self.docstatus != 0:
            return

        # Limpiar tablas actuales para regenerarlas según el rango
        self.set("ingresos", [])
        self.set("egresos", [])
        
        # Buscar movimientos pendientes (vinculado=0) en el rango y sucursal
        # Si el documento ya fue "sometido" (docstatus=1), los movimientos ya están vinculados a este cierre
        # pero validate no suele correr en docstatus=1 salvo en on_submit.
        # Asumimos que esto corre principalmente en borrador (docstatus=0).
        
        filtros = {
            "sucursal": self.sucursal,
            "docstatus": ["<", 2], # Borrador (0) o Enviado (1)
            "fecha_de_registro": ["between", [self.fecha_inicio, self.fecha_final]],
            "vinculado": 0 
        }

        movs = frappe.get_all("Movimiento", filters=filtros, fields=["name", "fecha_de_registro", "clasificacion", "importe", "descripcion", "tipo"])
        
        total_ing = 0.0
        total_egr = 0.0

        for m in movs:
            row = {
                "registro": m.name,
                "fecha": m.fecha_de_registro,
                "clasificación": m.clasificacion, # Nota: campo con tilde en tabla hija
                "importe": m.importe,
                "descripcion": m.descripcion
            }
            
            if m.tipo == "Ingreso":
                self.append("ingresos", row)
                total_ing += flt(m.importe)
            elif m.tipo == "Egreso":
                self.append("egresos", row)
                total_egr += flt(m.importe)
        
        self.total_ingresos = total_ing
        self.total_egresos = total_egr

        # --- Calculo de Saldo Final ---
        # Saldo Final = Saldo Anterior + Ingresos Actuales - Egresos Actuales
        
        saldo_anterior = 0.0

        # 1. Buscar último cierre anterior a este
        ultimo_cierre = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={
                "sucursal": self.sucursal,
                "docstatus": 1,
                "fecha_final": ["<", self.fecha_inicio]
            },
            fieldname="saldo_final",
            order_by="fecha_final desc"
        )

        if ultimo_cierre is not None:
            saldo_anterior = flt(ultimo_cierre)
        else:
            # 2. Si no hay cierre previo, calcular histórico desde el principio hasta antes de fecha_inicio
            # Sumar todos los Ingresos - Egresos anteriores a este periodo
            hist_moves = frappe.db.sql("""
                SELECT SUM(CASE WHEN tipo = 'Ingreso' THEN importe ELSE -importe END)
                FROM `tabMovimiento`
                WHERE sucursal = %s
                AND docstatus = 1
                AND fecha_de_registro < %s
            """, (self.sucursal, self.fecha_inicio))
            
            if hist_moves and hist_moves[0][0]:
                saldo_anterior = flt(hist_moves[0][0])

        self.saldo_final = saldo_anterior + self.total_ingresos - self.total_egresos

    def on_submit(self):
        # Validar datos mínimos
        if not self.sucursal or not self.fecha_inicio or not self.fecha_final:
            frappe.throw("Debe definir una sucursal y un rango de fechas válido antes de validar el cierre.")

        # Verificar cantidad de movimientos a afectar
        count = frappe.db.count("Movimiento", filters={
            "sucursal": self.sucursal,
            "fecha_de_registro": ["between", [self.fecha_inicio, self.fecha_final]],
            "docstatus": ["<", 2],
            "vinculado": 0
        })

        if count == 0:
            frappe.msgprint(
                f"No se encontraron movimientos para el rango de fechas seleccionado. "
                f"Se registró el cierre: {self.get_title_auth()}"
            )
        else:
            # Actualización masiva (SQL es más eficiente para updates por rango)
            # Al cerrar, SUBMITIMOS todos los movimientos (docstatus=1) y los vinculamos
            frappe.db.sql("""
                UPDATE `tabMovimiento`
                SET vinculado = 1, cierre = %s, docstatus = 1
                WHERE sucursal = %s
                AND fecha_de_registro BETWEEN %s AND %s
                AND docstatus < 2
                AND vinculado = 0
            """, (self.name, self.sucursal, self.fecha_inicio, self.fecha_final))

            frappe.msgprint(f"Se actualizaron {count} movimientos vinculados al cierre {self.get_title_auth()}.")

    def get_title_auth(self):
        from frappe.utils import get_link_to_form
        return get_link_to_form(self.doctype, self.name)

    def on_cancel(self):
        self.ignore_linked_doctypes = ["Movimiento"]
        
        # Desvincular masivamente y devolver a Borrador (0) si se cancela el cierre
        frappe.db.sql("""
            UPDATE `tabMovimiento`
            SET vinculado = 0, cierre = NULL, docstatus = 0
            WHERE cierre = %s
        """, (self.name,))

        frappe.msgprint(f"Se desvincularon los movimientos del cierre cancelado.")



@frappe.whitelist()
def get_events(start, end, filters=None):
    from frappe.desk.reportview import get_filters_cond
    
    conditions = get_filters_cond("Registro de Cierre de Movimiento", filters, [])
    conditions = conditions.replace("`tabRegistro de Cierre de Movimiento`.", "rcm.")

    data = frappe.db.sql(f"""
        SELECT
            rcm.name,
            CONCAT(rcm.fecha_inicio, ' 00:00:00') AS fecha_inicio,
            CONCAT(rcm.fecha_final, ' 23:59:59') AS fecha_final,
            rcm.sucursal,
            ROUND(IFNULL(rcm.total_ingresos, 0), 2) AS total_ingresos,
            ROUND(IFNULL(rcm.total_egresos, 0), 2) AS total_egresos,
            0 AS allDay,

            -- Asegúrate de que en la tabla exista rcm.color (o custom_color).
            rcm.color AS color,

            CONCAT(
                rcm.name, ' | Ingresos: ', FORMAT(IFNULL(rcm.total_ingresos, 0), 2),
                ' | Egresos: ', FORMAT(IFNULL(rcm.total_egresos, 0), 2)
            ) AS title

        FROM `tabRegistro de Cierre de Movimiento` rcm
        WHERE rcm.docstatus != 2
        {conditions}
    """, as_dict=True)

    return data





