import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class Movimiento(Document):
    def validate(self):
        self.ensure_currency_defaults()
        self.calculate_base_amount()
        self.validate_required_fields()
        self.validate_against_closure_dates()
        self.prevent_manual_submission()

    def ensure_currency_defaults(self):
        if self.moneda:
            return

        base_currency = frappe.db.get_single_value("IE Configuracion", "moneda_base")
        if not base_currency:
            frappe.throw(_("Debe configurar la moneda base en IE Configuración antes de guardar movimientos."))

        self.moneda = base_currency

    def calculate_base_amount(self):
        if not self.tasa_de_cambio or self.tasa_de_cambio <= 0:
            self.tasa_de_cambio = 1.0

        self.importe_base = flt(self.importe) * flt(self.tasa_de_cambio)

    def validate_required_fields(self):
        if self.sucursal and self.fecha_de_registro:
            return

        frappe.throw(_("Debe definir una sucursal y una fecha de registro."))

    def validate_against_closure_dates(self):
        posting_date = getdate(self.fecha_de_registro)
        first_closure_date = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={"sucursal": self.sucursal, "docstatus": 1},
            fieldname="fecha_inicio",
            order_by="fecha_inicio asc",
        )

        if first_closure_date:
            first_closure_date = getdate(first_closure_date)
            if posting_date < first_closure_date:
                frappe.throw(
                    _(
                        "No se puede agregar el movimiento porque la fecha {0} es anterior al primer cierre registrado ({1})."
                    ).format(posting_date, first_closure_date)
                )

        existing_closure = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={
                "sucursal": self.sucursal,
                "docstatus": 1,
                "fecha_inicio": ["<=", posting_date],
                "fecha_final": [">=", posting_date],
            },
            fieldname=["name", "fecha_inicio", "fecha_final"],
            as_dict=True,
        )

        if existing_closure:
            frappe.throw(
                _(
                    "No se puede agregar el movimiento porque la fecha {0} ya está incluida en el cierre {1} ({2} - {3})."
                ).format(
                    posting_date,
                    existing_closure.name,
                    existing_closure.fecha_inicio,
                    existing_closure.fecha_final,
                )
            )

    def prevent_manual_submission(self):
        if self.docstatus != 1 or self.vinculado:
            return

        frappe.throw(
            _(
                "No se pueden enviar movimientos manualmente. Deben procesarse mediante un cierre de movimientos."
            )
        )


@frappe.whitelist()
def get_code_name_options(code_name):
    if not code_name:
        return []

    query = """
        SELECT cv.code_value
        FROM `tabIE Codigo` c
        INNER JOIN `tabIE Codigo Detalle` cv ON c.name = cv.parent
        WHERE c.code_name = %s AND cv.active = 1
        ORDER BY cv.idx ASC
    """
    options = frappe.db.sql(query, (code_name,), as_dict=True)
    return [option.code_value for option in options]
