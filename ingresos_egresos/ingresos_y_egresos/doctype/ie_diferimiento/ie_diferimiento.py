from frappe.model.document import Document
import frappe
from frappe import _


class IEDiferimiento(Document):
    def validate(self):
        if not frappe.flags.ie_accounting_internal:
            frappe.throw(_("El calendario se crea al contabilizar el movimiento. Use sus acciones para procesar o pausar las cuotas."))

    def on_trash(self):
        frappe.throw(_("El calendario conserva el historial contable y no puede eliminarse."))
