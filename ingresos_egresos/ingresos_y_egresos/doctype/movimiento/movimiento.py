import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate
from ingresos_egresos.currency import calculate_amounts, get_base_currency


class Movimiento(Document):
    def get_invalid_links(self, is_submittable=False):
        invalid, cancelled = super().get_invalid_links(is_submittable)
        if not self.is_new():
            previous = frappe.db.get_value(self.doctype, self.name, ["asiento_contable", "estado_contable", "activo_fijo"], as_dict=True)
            if previous and previous.estado_contable == "Asiento anulado":
                cancelled = [row for row in cancelled if not (row[0] in ("asiento_contable", "activo_fijo") and row[1] == previous.get(row[0]))]
        return invalid, cancelled

    def validate(self):
        from ingresos_egresos.accounting import validate_movement
        validate_movement(self)
        from ingresos_egresos.asset_integration import validate_movement as validate_asset
        validate_asset(self)
        old_turn = frappe.db.get_value("Movimiento", self.name, "turno_pos") if not self.is_new() else None
        if (old_turn or self.turno_pos or self.origen_pos or self.clave_origen_pos) and not frappe.flags.ie_pos_internal:
            frappe.throw(_("Los movimientos POS se gestionan desde la integración y no se pueden desvincular."))
        self.ensure_currency_defaults()
        self.calculate_base_amount()
        self.validate_required_fields()
        if self.turno_pos:
            from ingresos_egresos.pos import validate_pos_movement
            validate_pos_movement(self)
        else:
            self.validate_against_closure_dates()
        self.prevent_manual_submission()

    def ensure_currency_defaults(self):
        self.moneda = self.moneda or get_base_currency()

    def calculate_base_amount(self):
        self.moneda, self.tasa_de_cambio, amount = calculate_amounts(
            self.moneda, self.tasa_de_cambio, self.importe, self.fecha_de_registro
        )
        self.moneda_base = get_base_currency()
        self.importe_base = flt(amount, self.precision("importe_base"))

    def validate_required_fields(self):
        if self.sucursal and self.fecha_de_registro:
            return

        frappe.throw(_("Debe definir una sucursal y una fecha de registro."))

    def validate_against_closure_dates(self):
        posting_date = getdate(self.fecha_de_registro)
        last_closure_date = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={"sucursal": self.sucursal, "moneda": self.moneda, "docstatus": 1, "turno_pos": ["is", "not set"]},
            fieldname="fecha_final", order_by="fecha_final desc",
        )
        if last_closure_date and posting_date <= getdate(last_closure_date):
            frappe.throw(_(
                "No se puede registrar o modificar el movimiento: la sucursal y moneda ya tienen un cierre hasta {0}."
            ).format(last_closure_date))

    def on_trash(self):
        if self.asiento_contable:
            frappe.throw(_("Los movimientos con historial contable no pueden eliminarse."))
        if self.turno_pos:
            frappe.throw(_("Los movimientos POS se anulan desde la operación de origen."))
        if self.docstatus < 2:
            self.validate_against_closure_dates()

    def before_cancel(self):
        from ingresos_egresos.accounting import prevent_source_cancel
        prevent_source_cancel(self)
        if self.turno_pos:
            frappe.throw(_("Los movimientos POS se anulan desde la operación de origen."))
        if self.cierre:
            frappe.throw(_("Debe cancelar el cierre para reabrir este movimiento."))

    def before_update_after_submit(self):
        from ingresos_egresos.accounting import validate_movement
        validate_movement(self)
        if (self.turno_pos or frappe.db.get_value(self.doctype, self.name, "turno_pos")) and not frappe.flags.ie_pos_internal:
            frappe.throw(_("Los movimientos POS se gestionan desde la integración."))

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
