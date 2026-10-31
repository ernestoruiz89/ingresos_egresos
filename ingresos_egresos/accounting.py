"""Explicit, transactional posting of cash movements to ERPNext Journal Entries."""
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from ingresos_egresos.currency import valid_rate

SNAPSHOT_FIELDS = (
    "asiento_contable", "estado_contable", "cuenta_caja", "cuenta_contrapartida",
    "centro_de_costos", "party_type", "party", "activo_fijo", "fecha_contabilizacion", "contabilizado_por",
)
COMPANY_FIELDS = ("company", "moneda_empresa", "tasa_empresa", "importe_empresa")
FINANCIAL_FIELDS = (
    "sucursal", "fecha_de_registro", "tipo", "clasificacion", "referencia", "descripcion",
    "importe", "moneda", "tasa_de_cambio", "importe_base", "moneda_base",
    "turno_pos", "fecha_operacion", "medio_pago", "origen_pos",
    "documento_origen_tipo", "documento_origen",
) + COMPANY_FIELDS + ("es_activo", "item_activo", "nombre_activo", "categoria_activo", "ubicacion_activo",
    "fecha_uso_activo", "vida_util_meses", "valor_residual")
POSTED, CANCELLED, POS = "Contabilizado", "Asiento anulado", "Gestionado por POS"


@contextmanager
def internal_posting():
    previous = frappe.flags.ie_accounting_internal
    frappe.flags.ie_accounting_internal = True
    try:
        yield
    finally:
        frappe.flags.ie_accounting_internal = previous


def validate_configuration(config):
    seen = set()
    for row in config.get("cuentas_caja", []):
        key = (row.sucursal, row.moneda)
        if key in seen:
            frappe.throw(_("Configure una sola cuenta de caja por sucursal y moneda: {0}, {1}.").format(*key))
        seen.add(key)
        account = account_details(row.cuenta_caja, row.company)
        if account.account_type not in ("Cash", "Bank") or account.root_type != "Asset":
            frappe.throw(_("La cuenta {0} debe ser una cuenta de caja o banco de activo.").format(row.cuenta_caja))
        if account.currency != row.moneda:
            frappe.throw(_("La moneda de la cuenta {0} debe ser {1}.").format(row.cuenta_caja, row.moneda))
        if row.centro_de_costos:
            validate_cost_center(row.centro_de_costos, row.company)


def account_details(name, company):
    doc = frappe.get_doc("Account", name)
    if doc.company != company or doc.is_group or doc.disabled:
        frappe.throw(_("La cuenta {0} debe estar habilitada, ser de detalle y pertenecer a {1}.").format(name, company))
    doc.currency = doc.account_currency or frappe.get_cached_value("Company", company, "default_currency")
    return doc


def validate_cost_center(name, company, permissions=False):
    doc = frappe.get_doc("Cost Center", name)
    if doc.company != company or doc.is_group or doc.disabled:
        frappe.throw(_("Seleccione un centro de costos activo de la empresa {0}.").format(company))
    if permissions:
        doc.check_permission("read")


def require_posting_permissions():
    frappe.has_permission("Journal Entry", "create", throw=True)
    frappe.has_permission("Journal Entry", "submit", throw=True)


def movement(name, lock=False):
    doc = frappe.get_doc("Movimiento", name, for_update=lock)
    doc.check_permission("write")
    if doc.turno_pos:
        from ingresos_egresos.pos import check_scope
        check_scope(frappe.get_doc("IE Turno POS", doc.turno_pos))
    return doc


def cash_configuration(doc):
    rows = frappe.get_all("IE Cuenta Caja", filters={"parent": "IE Configuracion", "parenttype": "IE Configuracion",
        "sucursal": doc.sucursal, "moneda": doc.moneda}, fields=["company", "cuenta_caja", "centro_de_costos"])
    if len(rows) != 1:
        frappe.throw(_("Configure una cuenta de caja para {0} / {1} en IE Configuración.").format(doc.sucursal, doc.moneda))
    row = rows[0]
    frappe.has_permission("Company", "read", doc=row.company, throw=True)
    if doc.turno_pos and row.company != doc.company:
        frappe.throw(_("La empresa de la cuenta de caja debe coincidir con la empresa del turno POS."))
    account = account_details(row.cuenta_caja, row.company)
    account.check_permission("read")
    if account.account_type not in ("Cash", "Bank") or account.root_type != "Asset" or account.currency != doc.moneda:
        frappe.throw(_("La cuenta de caja configurada no es válida para la moneda del movimiento."))
    row.voucher_type = "Cash Entry" if account.account_type == "Cash" else "Journal Entry"
    return row


def default_counterpart(doc, company):
    name = frappe.db.get_value("IE Codigo Detalle", {"parent": doc.tipo, "code_value": doc.clasificacion, "active": 1}, "cuenta_contable")
    if name and frappe.db.get_value("Account", name, "company") == company:
        return name


def company_rate(doc, company_currency):
    if doc.moneda == company_currency:
        return 1.0, False
    if doc.turno_pos:
        return flt(doc.tasa_empresa), False
    if company_currency == doc.moneda_base:
        return flt(doc.tasa_de_cambio), False
    from erpnext.setup.utils import get_exchange_rate
    rate = get_exchange_rate(doc.moneda, company_currency, getdate(doc.fecha_de_registro))
    return flt(rate) if valid_rate(rate) else None, True


def preview_row(doc):
    result = dict(name=doc.name, modified=doc.modified, tipo=doc.tipo, clasificacion=doc.clasificacion,
        sucursal=doc.sucursal, fecha=doc.fecha_de_registro, moneda=doc.moneda, importe=doc.importe,
        asiento_contable=doc.asiento_contable, estado=doc.estado_contable or "Pendiente", eligible=False)
    if doc.docstatus == 2:
        result["motivo"] = _("Movimiento anulado")
        return result
    if doc.asiento_contable and doc.estado_contable == POSTED:
        result["motivo"] = _("Ya contabilizado")
        return result
    if doc.origen_pos in ("Venta", "Devolucion"):
        result.update(estado=POS, motivo=_("El cobro o devolución ya se contabiliza mediante la factura POS."))
        return result
    if doc.tipo not in ("Ingreso", "Egreso") or not valid_rate(doc.importe):
        frappe.throw(_("El movimiento {0} requiere un tipo válido y un importe positivo.").format(doc.name))
    row = cash_configuration(doc)
    currency = frappe.get_cached_value("Company", row.company, "default_currency")
    rate, editable = company_rate(doc, currency)
    cost_center = row.centro_de_costos or frappe.get_cached_value("Company", row.company, "cost_center")
    if cost_center:
        center = frappe.get_doc("Cost Center", cost_center)
        if center.company != row.company or center.is_group or center.disabled or not frappe.has_permission("Cost Center", "read", doc=center):
            cost_center = None
    result.update(eligible=True, company=row.company, moneda_empresa=currency, cuenta_caja=row.cuenta_caja,
        cuenta_contrapartida=default_counterpart(doc, row.company),
        centro_de_costos=cost_center,
        tasa_empresa=rate, tasa_editable=editable, raiz_cuenta="Income" if doc.tipo == "Ingreso" else "Expense")
    result["voucher_type"] = row.voucher_type
    if doc.es_activo:
        from ingresos_egresos.asset_integration import accounts
        asset_accounts, _depreciable = accounts(doc, row.company)
        result.update(es_activo=True, cuenta_contrapartida=asset_accounts.fixed_asset_account,
            nombre_activo=doc.nombre_activo, categoria_activo=doc.categoria_activo)
    return result


def parse_names(names):
    names = frappe.parse_json(names) if isinstance(names, str) else names
    if not isinstance(names, list) or not names or len(names) > 100 or any(not isinstance(name, str) or not name for name in names):
        frappe.throw(_("Seleccione entre 1 y 100 movimientos."))
    return sorted(set(names))


@frappe.whitelist()
def get_preview(names):
    require_posting_permissions()
    return [preview_row(movement(name)) for name in parse_names(names)]


def prepare(doc, options):
    plan = preview_row(doc)
    if not plan["eligible"]:
        return plan
    if not options.get("modified") or get_datetime(options["modified"]) != get_datetime(doc.modified):
        frappe.throw(_("El movimiento {0} cambió. Actualice la vista previa antes de contabilizar.").format(doc.name))
    name = options.get("cuenta_contrapartida") or plan["cuenta_contrapartida"]
    if doc.es_activo and name != plan["cuenta_contrapartida"]:
        frappe.throw(_("La cuenta del activo se toma de su categoría y no se puede sustituir por una cuenta de gasto."))
    plan["faltantes"] = []
    if not name:
        plan["faltantes"].append("cuenta_contrapartida")
        return plan
    counterpart = account_details(name, plan["company"])
    counterpart.check_permission("read")
    party_required = counterpart.account_type in ("Receivable", "Payable")
    if doc.es_activo:
        if counterpart.root_type != "Asset":
            frappe.throw(_("La cuenta de la categoría debe ser una cuenta de activo fijo."))
    elif not party_required and (counterpart.root_type != plan["raiz_cuenta"] or counterpart.report_type != "Profit and Loss"):
        frappe.throw(_("La contrapartida de {0} debe ser una cuenta de {1}.").format(doc.name, _("ingreso") if doc.tipo == "Ingreso" else _("gasto")))
    if counterpart.currency not in (doc.moneda, plan["moneda_empresa"]):
        frappe.throw(_("La cuenta de ingreso o gasto debe usar la moneda del movimiento o la de la empresa."))
    cost_center = options.get("centro_de_costos") or plan["centro_de_costos"]
    cost_center_required = bool(doc.es_activo) or counterpart.report_type == "Profit and Loss"
    if cost_center:
        validate_cost_center(cost_center, plan["company"], permissions=True)
    elif cost_center_required:
        plan["faltantes"].append("centro_de_costos")
    party_types = frappe.get_all("Party Type", filters={"account_type": counterpart.account_type}, pluck="name") if party_required else []
    if party_required and frappe.db.exists("Party Type", "Employee"):
        party_types.append("Employee")
    default_party = "Customer" if counterpart.account_type == "Receivable" else "Supplier"
    party_types = sorted(set(party_types))
    party_type = options.get("party_type") or (default_party if default_party in party_types else None)
    party = options.get("party")
    if not party_required:
        party_type = party = None
    if party_required and not party_type:
        plan["faltantes"].append("party_type")
    if party_required and not party:
        plan["faltantes"].append("party")
    if party_type:
        if not frappe.db.exists("Party Type", party_type) or (party_required and party_type not in party_types):
            frappe.throw(_("El tipo de tercero no corresponde a la cuenta seleccionada."))
        if party:
            frappe.get_doc(party_type, party).check_permission("read")
    elif party:
        plan["faltantes"].append("party_type")
    rate = options.get("tasa_empresa") if plan["tasa_editable"] else plan["tasa_empresa"]
    if rate in (None, ""):
        rate = plan["tasa_empresa"]
    if rate in (None, "", 0):
        plan["faltantes"].append("tasa_empresa")
    elif not valid_rate(rate):
        frappe.throw(_("Indique una tasa contable positiva para {0}.").format(doc.name))
    if not plan["tasa_editable"] and options.get("tasa_empresa") not in (None, "") and flt(options["tasa_empresa"]) != flt(rate):
        frappe.throw(_("La tasa contable de {0} debe conservar la tasa guardada del movimiento.").format(doc.name))
    plan.update(cuenta_contrapartida=name, centro_de_costos=cost_center, tasa_empresa=flt(rate),
        moneda_contrapartida=counterpart.currency, party_type=party_type, party=party,
        requiere_tercero=party_required, tipos_tercero=party_types, requiere_centro=cost_center_required)
    return plan


@frappe.whitelist()
def get_requirements(name, cuenta_contrapartida=None, centro_de_costos=None, party_type=None, party=None, tasa_empresa=None):
    require_posting_permissions()
    doc = movement(name)
    return prepare(doc, dict(modified=doc.modified, cuenta_contrapartida=cuenta_contrapartida,
        centro_de_costos=centro_de_costos, party_type=party_type, party=party, tasa_empresa=tasa_empresa))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def account_query(doctype, txt, searchfield, start, page_len, filters=None):
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    roots = ["Income"] if filters.get("tipo") == "Ingreso" else ["Expense"] if filters.get("tipo") == "Egreso" else ["Income", "Expense"]
    conditions = {"is_group": 0, "disabled": 0, "name": ["like", "%" + txt + "%"]}
    if filters.get("company"):
        conditions["company"] = filters["company"]
    return frappe.get_list("Account", filters=conditions,
        or_filters=[["root_type", "in", roots], ["account_type", "in", ["Receivable", "Payable"]]],
        fields=["name", "account_name", "company", "account_currency"], as_list=True,
        limit_start=max(0, cint(start)), limit_page_length=min(100, max(1, cint(page_len))))


def post_one(doc, plan):
    amount = flt(doc.importe)
    company_amount = flt(amount * plan["tasa_empresa"], cint(frappe.get_system_settings("currency_precision") or 2))
    if not valid_rate(company_amount):
        frappe.throw(_("El importe contable de {0} debe ser positivo después de redondear.").format(doc.name))
    cash = dict(account=plan["cuenta_caja"], account_currency=doc.moneda, exchange_rate=plan["tasa_empresa"],
        debit_in_account_currency=amount if doc.tipo == "Ingreso" else 0,
        credit_in_account_currency=amount if doc.tipo == "Egreso" else 0)
    same_currency = plan["moneda_contrapartida"] == doc.moneda
    counterpart_amount = amount if same_currency else company_amount
    counterpart = dict(account=plan["cuenta_contrapartida"], account_currency=plan["moneda_contrapartida"],
        cost_center=plan["centro_de_costos"], exchange_rate=plan["tasa_empresa"] if same_currency else 1,
        party_type=plan.get("party_type"), party=plan.get("party"),
        credit_in_account_currency=counterpart_amount if doc.tipo == "Ingreso" else 0,
        debit_in_account_currency=counterpart_amount if doc.tipo == "Egreso" else 0)
    if plan.get("party_type") == "Customer" and doc.tipo == "Ingreso" or plan.get("party_type") == "Supplier" and doc.tipo == "Egreso":
        counterpart["is_advance"] = "Yes"
    journal = frappe.get_doc(dict(doctype="Journal Entry", voucher_type=plan["voucher_type"], company=plan["company"],
        posting_date=doc.fecha_de_registro, multi_currency=doc.moneda != plan["moneda_empresa"],
        custom_ie_movimiento=doc.name, user_remark=" · ".join(str(value) for value in
            (doc.name, doc.sucursal, doc.clasificacion, doc.referencia, doc.descripcion) if value),
        accounts=[cash, counterpart]))
    journal.flags.ignore_exchange_rate = True
    with internal_posting():
        journal.insert()
        journal.submit()
        asset = None
        if doc.es_activo:
            from ingresos_egresos.asset_integration import create_asset
            asset = create_asset(doc, plan, journal)
    values = dict(asiento_contable=journal.name, estado_contable=POSTED, company=plan["company"],
        cuenta_caja=plan["cuenta_caja"], cuenta_contrapartida=plan["cuenta_contrapartida"],
        centro_de_costos=plan["centro_de_costos"], moneda_empresa=plan["moneda_empresa"],
        party_type=plan.get("party_type"), party=plan.get("party"),
        tasa_empresa=plan["tasa_empresa"], importe_empresa=journal.total_debit,
        fecha_contabilizacion=now_datetime(), contabilizado_por=frappe.session.user, activo_fijo=asset)
    frappe.db.set_value("Movimiento", doc.name, values)
    frappe.get_doc("Movimiento", doc.name).notify_update()
    return journal.name


@frappe.whitelist(methods=["POST"])
def post_movements(entries):
    require_posting_permissions()
    entries = frappe.parse_json(entries) if isinstance(entries, str) else entries
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        frappe.throw(_("El lote de contabilización no es válido."))
    names = parse_names([row.get("name") for row in entries])
    if len(names) != len(entries):
        frappe.throw(_("No repita movimientos en el lote."))
    options = {row["name"]: row for row in entries}
    frappe.db.savepoint("ie_accounting_batch")
    try:
        from ingresos_egresos.pos import lock_configuration
        lock_configuration()
        # One lock order for overlapping selections. Validate the entire batch before posting.
        docs = [movement(name, lock=True) for name in names]
        plans = [prepare(doc, options[doc.name]) for doc in docs]
        if any(plan.get("faltantes") for plan in plans):
            return dict(status="needs_input", rows=plans)
        result = []
        for doc, plan in zip(docs, plans, strict=True):
            if plan["eligible"]:
                journal = post_one(doc, plan)
                result.append(dict(name=doc.name, asiento_contable=journal, resultado="Contabilizado"))
                result[-1]["activo_fijo"] = frappe.db.get_value("Movimiento", doc.name, "activo_fijo")
            else:
                result.append(dict(name=doc.name, asiento_contable=doc.asiento_contable,
                    resultado="Omitido", motivo=plan["motivo"]))
        return dict(status="posted", results=result)
    except Exception:
        frappe.db.rollback(save_point="ie_accounting_batch")
        raise


def normalized(doc, name):
    value = doc.get(name)
    field = doc.meta.get_field(name)
    if field.fieldtype in ("Currency", "Float", "Percent"):
        return flt(value)
    if value and field.fieldtype == "Date":
        return getdate(value)
    if value and field.fieldtype == "Datetime":
        return get_datetime(value)
    return value or None


def validate_movement(doc):
    if frappe.flags.ie_accounting_internal:
        return
    old = frappe.get_doc("Movimiento", doc.name, for_update=True) if not doc.is_new() else None
    if old:
        if any(normalized(doc, field) != normalized(old, field) for field in SNAPSHOT_FIELDS):
            frappe.throw(_("El asiento y los datos contables se actualizan únicamente mediante Contabilizar o la anulación del asiento."))
        if old.estado_contable == POSTED and any(normalized(doc, field) != normalized(old, field) for field in FINANCIAL_FIELDS):
            frappe.throw(_("Anule el asiento contable antes de modificar los datos de este movimiento."))
        if not doc.turno_pos and any(normalized(doc, field) != normalized(old, field) for field in COMPANY_FIELDS):
            frappe.throw(_("La empresa y los importes contables se asignan al contabilizar."))
    else:
        if any(doc.get(field) for field in SNAPSHOT_FIELDS if field != "estado_contable"):
            frappe.throw(_("No puede asignar manualmente un asiento contable a un movimiento nuevo."))
        if doc.get("estado_contable") not in (None, "", "Pendiente"):
            frappe.throw(_("El estado contable se asigna desde el servidor."))
        if not doc.turno_pos:
            # Frappe can prefill Company from user defaults. Pending movements
            # get their accounting company exclusively from the cash mapping.
            doc.company = doc.moneda_empresa = None
            doc.tasa_empresa = doc.importe_empresa = 0
    if doc.origen_pos in ("Venta", "Devolucion"):
        doc.estado_contable = POS


def prevent_source_cancel(doc):
    if doc.asiento_contable and doc.estado_contable == POSTED:
        frappe.throw(_("Anule primero el asiento contable {0}.").format(doc.asiento_contable))


def journal_source(doc):
    if not doc.meta.has_field("custom_ie_movimiento"):
        return None
    old_name = frappe.db.get_value("Journal Entry", doc.name, "custom_ie_movimiento") if not doc.is_new() else None
    if old_name and old_name != doc.get("custom_ie_movimiento"):
        frappe.throw(_("No se puede desvincular el asiento de su movimiento."))
    return old_name or doc.get("custom_ie_movimiento")


def validate_journal(doc, method=None):
    name = journal_source(doc)
    if not name or frappe.flags.ie_accounting_internal:
        return
    if doc.is_new() or doc.docstatus != 1:
        frappe.throw(_("Los asientos vinculados a movimientos se crean desde Contabilizar."))
    old = frappe.get_doc("Journal Entry", doc.name, for_update=True)
    headers = ("company", "posting_date", "multi_currency", "voucher_type")
    fields = ("account", "account_currency", "exchange_rate", "debit_in_account_currency", "credit_in_account_currency",
        "debit", "credit", "cost_center", "project", "party_type", "party", "reference_type", "reference_name")
    if any(str(doc.get(key) or "") != str(old.get(key) or "") for key in headers) or (
        [tuple(row.get(key) for key in fields) for row in doc.accounts] !=
        [tuple(row.get(key) for key in fields) for row in old.accounts]
    ):
        frappe.throw(_("Anule el asiento y vuelva a contabilizar desde el movimiento para cambiar sus cuentas o importes."))


def before_journal_cancel(doc, method=None):
    if name := journal_source(doc):
        source = movement(name, lock=True)
        if source.asiento_contable != doc.name:
            frappe.throw(_("Este asiento no es el asiento vigente del movimiento."))
        from ingresos_egresos.asset_integration import cancel_for_journal
        cancel_for_journal(source)
        doc.ignore_linked_doctypes = tuple(set(getattr(doc, "ignore_linked_doctypes", ()) or ()) | {"Movimiento", "Asset"})


def after_journal_cancel(doc, method=None):
    if name := journal_source(doc):
        if frappe.db.get_value("Movimiento", name, "asiento_contable") == doc.name:
            frappe.db.set_value("Movimiento", name, "estado_contable", CANCELLED)
            frappe.get_doc("Movimiento", name).notify_update()


def before_journal_delete(doc, method=None):
    if journal_source(doc):
        frappe.throw(_("El asiento conserva el historial del movimiento y no puede eliminarse."))
