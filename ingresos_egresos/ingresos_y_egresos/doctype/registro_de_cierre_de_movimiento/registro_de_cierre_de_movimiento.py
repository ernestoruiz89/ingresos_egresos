# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate
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

    def on_submit(self):
        # Validar datos mínimos
        if not self.sucursal or not self.fecha_inicio or not self.fecha_final:
            frappe.throw("Debe definir una sucursal y un rango de fechas válido antes de validar el cierre.")

        # Verificar cantidad de movimientos a afectar
        count = frappe.db.count("Movimiento", filters={
            "sucursal": self.sucursal,
            "fecha_de_registro": ["between", [self.fecha_inicio, self.fecha_final]],
            "docstatus": 1,
            "vinculado": 0
        })

        if count == 0:
            frappe.msgprint(
                "No se encontraron movimientos para el rango de fechas seleccionado. "
                "Se registrará el cierre de todos modos."
            )
        else:
            # Actualización masiva (SQL es más eficiente para updates por rango)
            frappe.db.sql("""
                UPDATE `tabMovimiento`
                SET vinculado = 1, cierre = %s
                WHERE sucursal = %s
                AND fecha_de_registro BETWEEN %s AND %s
                AND docstatus = 1
                AND vinculado = 0
            """, (self.name, self.sucursal, self.fecha_inicio, self.fecha_final))

            frappe.msgprint(f"Se actualizaron {count} movimientos vinculados al cierre.")

    def on_cancel(self):
        self.ignore_linked_doctypes = ["Movimiento"]
        
        # Desvincular masivamente
        frappe.db.sql("""
            UPDATE `tabMovimiento`
            SET vinculado = 0, cierre = NULL
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





