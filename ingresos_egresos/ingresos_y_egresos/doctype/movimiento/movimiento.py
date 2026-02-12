import frappe
from frappe.model.document import Document
from frappe.utils import getdate

class Movimiento(Document):
    def validate(self):
        # Verificar que la sucursal y la fecha de registro estén definidas
        if not self.sucursal or not self.fecha_de_registro:
            frappe.throw("Debe definir una sucursal y una fecha de registro.")

        # Asegurar objeto date
        fecha_de_registro = getdate(self.fecha_de_registro)

        # 1. Validar que la fecha no sea anterior al primer cierre
        # Obtenemos solo la fecha del primer cierre para esta sucursal
        primer_cierre_fecha = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={"sucursal": self.sucursal, "docstatus": 1},
            fieldname="fecha_inicio",
            order_by="fecha_inicio asc"
        )

        if primer_cierre_fecha:
            primer_cierre_fecha = getdate(primer_cierre_fecha)
            if fecha_de_registro < primer_cierre_fecha:
                frappe.throw(
                    f"No se puede agregar el movimiento porque la fecha {fecha_de_registro} es anterior al primer cierre "
                    f"realizado ({primer_cierre_fecha})."
                )

        # 2. Validar que la fecha no esté incluida en un cierre existente
        # Buscamos si existe UN cierre que cubra esta fecha. frappe.db.exists no soporta filtros complejos facilmente en todas las versiones
        # pero get_value con filtros de rango es eficiente.
        cierre_existente = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={
                "sucursal": self.sucursal,
                "docstatus": 1,
                "fecha_inicio": ["<=", fecha_de_registro],
                "fecha_final": [">=", fecha_de_registro]
            },
            fieldname=["name", "fecha_inicio", "fecha_final"],
            as_dict=True
        )

        if cierre_existente:
            frappe.throw(
                f"No se puede agregar el movimiento porque la fecha {fecha_de_registro} está incluida en el cierre {cierre_existente.name} "
                f"({cierre_existente.fecha_inicio} - {cierre_existente.fecha_final})."
            )

        # 3. Validar que no se pueda enviar manualmente (docstatus=1) si no tiene 'vinculado'
        # Nota: El proceso de Cierre utiliza SQL directo para actualizar docstatus, lo que evita llamar a validate()
        # y permite que se marquen como enviados sin pasar por este bloqueo manual.
        if self.docstatus == 1 and not self.vinculado:
            frappe.throw("No se pueden enviar movimientos manualmente. Deben ser procesados mediante un Cierre de Movimientos.")

@frappe.whitelist()
def get_code_name_options(code_name):
    if not code_name:
        return []
    
    sql_query = """
        SELECT cv.code_value
        FROM `tabIE Codigo` c
        INNER JOIN `tabIE Codigo Detalle` cv ON c.name = cv.parent
        WHERE c.code_name = %s AND cv.active = 1
        ORDER BY cv.idx ASC
    """
    options = frappe.db.sql(sql_query, (code_name), as_dict=True)
    return [option.code_value for option in options]
