"""Cash acquisitions use the category's asset accounts and native depreciation."""
import frappe
from math import isfinite
from frappe import _
from frappe.utils import cint, flt, getdate, get_last_day

INPUT_FIELDS = ("es_activo", "item_activo", "nombre_activo", "categoria_activo", "ubicacion_activo",
    "fecha_uso_activo", "vida_util_meses", "valor_residual")


def item_details(name):
    item = frappe.get_doc("Item", name)
    if item.disabled or not item.is_fixed_asset or item.is_stock_item or not item.asset_category:
        frappe.throw(_("Seleccione un artículo activo, no inventariable y marcado como activo fijo, con categoría."))
    return item


@frappe.whitelist()
def get_options(item_activo):
    item = item_details(item_activo)
    item.check_permission("read")
    category = frappe.get_doc("Asset Category", item.asset_category)
    books = category.get("finance_books") or []
    months = cint(books[0].total_number_of_depreciations) * cint(books[0].frequency_of_depreciation) if books else 60
    return dict(categoria_activo=category.name, nombre_activo=item.item_name,
        depreciable=not category.non_depreciable_category, vida_util_meses=months or 60)


def validate_movement(doc):
    if not doc.es_activo:
        return
    if doc.tipo != "Egreso" or doc.origen_pos in ("Venta", "Devolucion"):
        frappe.throw(_("Es activo fijo solo se aplica a egresos manuales."))
    if not doc.item_activo or not doc.ubicacion_activo or not doc.fecha_uso_activo:
        frappe.throw(_("Complete el artículo, la ubicación y la fecha de uso del activo."))
    item = item_details(doc.item_activo)
    doc.categoria_activo = item.asset_category
    doc.nombre_activo = doc.nombre_activo or item.item_name
    frappe.get_doc("Location", doc.ubicacion_activo).check_permission("read")
    if getdate(doc.fecha_uso_activo) < getdate(doc.fecha_de_registro):
        frappe.throw(_("La fecha de uso no puede ser anterior a la adquisición."))
    if not isfinite(flt(doc.valor_residual)) or flt(doc.valor_residual) < 0 or flt(doc.valor_residual) >= flt(doc.importe):
        frappe.throw(_("El valor residual debe ser cero o positivo y menor que el importe del activo."))
    if not frappe.get_cached_value("Asset Category", item.asset_category, "non_depreciable_category"):
        if not 1 <= cint(doc.vida_util_meses) <= 1200 or flt(doc.vida_util_meses) != cint(doc.vida_util_meses):
            frappe.throw(_("Indique una vida útil entre 1 y 1200 meses."))


def accounts(doc, company):
    validate_movement(doc)
    category = frappe.get_doc("Asset Category", doc.categoria_activo)
    rows = [row for row in category.accounts if row.company_name == company]
    if len(rows) != 1 or not rows[0].fixed_asset_account:
        frappe.throw(_("Configure las cuentas de la categoría {0} para {1}.").format(category.name, company))
    row = rows[0]
    from ingresos_egresos.accounting import account_details
    currency = frappe.get_cached_value("Company", company, "default_currency")
    required = [row.fixed_asset_account]
    if not category.non_depreciable_category:
        if not row.accumulated_depreciation_account or not row.depreciation_expense_account:
            frappe.throw(_("Complete las cuentas de depreciación acumulada y gasto de depreciación en {0}.").format(category.name))
        required += [row.accumulated_depreciation_account, row.depreciation_expense_account]
    for name in required:
        account = account_details(name, company)
        account.check_permission("read")
        if account.currency != currency:
            frappe.throw(_("Las cuentas del activo deben usar la moneda de la empresa."))
    for doctype in ("Asset", "Asset Movement"):
        frappe.has_permission(doctype, "create", throw=True)
        frappe.has_permission(doctype, "submit", throw=True)
    return row, not category.non_depreciable_category


def create_asset(doc, plan, journal):
    _accounts, depreciable = accounts(doc, plan["company"])
    asset = frappe.get_doc(dict(doctype="Asset", company=plan["company"], item_code=doc.item_activo,
        asset_name=doc.nombre_activo, asset_category=doc.categoria_activo, location=doc.ubicacion_activo,
        purchase_date=doc.fecha_de_registro, available_for_use_date=doc.fecha_uso_activo,
        asset_quantity=1, net_purchase_amount=journal.total_debit, calculate_depreciation=depreciable,
        booked_fixed_asset=1, cost_center=plan["centro_de_costos"], custom_ie_movimiento=doc.name,
        custom_ie_asiento_contable=journal.name))
    if depreciable:
        asset.append("finance_books", dict(depreciation_method="Straight Line", frequency_of_depreciation=1,
            total_number_of_depreciations=cint(doc.vida_util_meses), depreciation_start_date=get_last_day(doc.fecha_uso_activo),
            expected_value_after_useful_life=flt(flt(doc.valor_residual) * plan["tasa_empresa"], 2)))
    asset.insert()
    asset.submit()
    return asset.name


def cancel_for_journal(source):
    if not source.activo_fijo:
        return
    asset = frappe.get_doc("Asset", source.activo_fijo, for_update=True)
    schedules = frappe.get_all("Asset Depreciation Schedule", filters={"asset": asset.name}, pluck="name")
    if schedules:
        journals = frappe.get_all("Depreciation Schedule", filters={"parent": ["in", schedules], "journal_entry": ["is", "set"]}, pluck="journal_entry")
        if journals and frappe.db.exists("Journal Entry", {"name": ["in", journals], "docstatus": 1}):
            frappe.throw(_("El activo ya tiene depreciaciones contabilizadas. Anúlelas antes de anular la adquisición."))
    if asset.docstatus == 1:
        from ingresos_egresos.accounting import internal_posting
        with internal_posting():
            asset.ignore_linked_doctypes = ["Movimiento"]
            asset.cancel()


def before_asset_cancel(doc, method=None):
    if doc.get("custom_ie_movimiento") and not frappe.flags.ie_accounting_internal:
        frappe.throw(_("Anule la adquisición desde el asiento contable vinculado para mantener ambos registros sincronizados."))


def after_asset_cancel(doc, method=None):
    if doc.get("custom_ie_movimiento"):
        doc.ignore_linked_doctypes = tuple(set(getattr(doc, "ignore_linked_doctypes", ()) or ()) | {"Movimiento"})


class MovementAssetMixin:
    def show_schedule_creation_message(self, schedules):
        if self.get("custom_ie_movimiento") and frappe.flags.ie_accounting_internal:
            # The reviewed posting flow submits the asset in this transaction
            # and reports its links once, after the entire batch succeeds.
            return
        return super().show_schedule_creation_message(schedules)

    def validate(self):
        old = self.get_doc_before_save()
        if self.get("custom_ie_movimiento") or (old and old.get("custom_ie_movimiento")):
            if (not old or not old.get("custom_ie_movimiento")) and not frappe.flags.ie_accounting_internal:
                frappe.throw(_("Los activos vinculados a movimientos se crean al contabilizar el egreso."))
            if old and (old.custom_ie_movimiento != self.custom_ie_movimiento or
                        old.custom_ie_asiento_contable != self.custom_ie_asiento_contable):
                frappe.throw(_("No se puede desvincular el activo de su adquisición."))
        return super().validate()

    def validate_asset_values(self):
        if not self.get("custom_ie_movimiento"):
            return super().validate_asset_values()
        # Direct cash purchases are already booked to Fixed Asset by our Journal
        # Entry, including categories with CWIP enabled. No fictitious purchase
        # invoice or opening balance, and no second capitalization GL entry.
        journal = frappe.get_doc("Journal Entry", self.custom_ie_asiento_contable)
        if journal.docstatus != 1 or journal.custom_ie_movimiento != self.custom_ie_movimiento or journal.company != self.company:
            frappe.throw(_("El activo requiere el asiento de adquisición confirmado de su movimiento."))
        if not self.net_purchase_amount or flt(self.net_purchase_amount) != flt(journal.total_debit) or not self.booked_fixed_asset:
            frappe.throw(_("El costo del activo debe coincidir con el asiento de adquisición."))
        if self.calculate_depreciation and (not self.finance_books or self.is_fully_depreciated):
            frappe.throw(_("Complete los datos de depreciación del activo."))
        if getdate(self.available_for_use_date) < getdate(self.purchase_date):
            frappe.throw(_("La fecha de uso no puede ser anterior a la adquisición."))
