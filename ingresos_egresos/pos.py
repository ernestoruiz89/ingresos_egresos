"""POS integration services. All public writes are scoped to one authorized opening."""
from contextlib import contextmanager
from hashlib import sha256
from math import isfinite

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from ingresos_egresos.currency import get_base_currency, valid_rate

TURN = "IE Turno POS"
CLOSURE = "Registro de Cierre de Movimiento"
OPEN, CLOSED, CANCELLED = "Abierto", "Cerrado", "Cancelado"


@contextmanager
def internal_operation():
    # A request-local server flag, never a flag accepted in a client document.
    previous = frappe.flags.ie_pos_internal
    frappe.flags.ie_pos_internal = True
    try:
        yield
    finally:
        frappe.flags.ie_pos_internal = previous


def precision():
    return int(frappe.db.get_single_value("System Settings", "currency_precision") or 2)


def lock_configuration():
    return frappe.db.sql("""SELECT value FROM `tabSingles`
        WHERE doctype='IE Configuracion' AND field='integrar_pos' FOR UPDATE""")


def enabled():
    rows=frappe.db.sql("""SELECT value FROM `tabSingles`
        WHERE doctype='IE Configuracion' AND field='integrar_pos' LOCK IN SHARE MODE""")
    return cint(rows[0][0]) if rows else 0


def lock_profile(profile):
    frappe.db.sql("SELECT name FROM `tabPOS Profile` WHERE name=%s FOR UPDATE", profile)


def lock_turn(name):
    return frappe.get_doc(TURN, name, for_update=True)


def current_rows(doctype, filters=None, fields=None, limit=None, order_by=None):
    """A locking current read, for services that already hold their scope lock."""
    return frappe.qb.get_query(doctype,filters=filters,fields=fields or ["name"],
        limit=limit,order_by=order_by,for_update=True).run(as_dict=True)


def supervisor():
    return frappe.session.user == "Administrator" or bool(
        {"System Manager", "IE Supervisor POS"} & set(frappe.get_roles()))


def require_operator():
    if not supervisor() and "IE Cajero POS" not in frappe.get_roles():
        frappe.throw(_("Requiere el rol IE Cajero POS."), frappe.PermissionError)


def profile_accessible(profile, user=None):
    # ERPNext's POS accepts native select-only profiles as well (Sales Manager).
    user=user or frappe.session.user
    ptype="select" if frappe.only_has_select_perm("POS Profile",user=user) else "read"
    if not frappe.has_permission("POS Profile",ptype,doc=profile,user=user):return False
    if user=="Administrator" or "System Manager" in frappe.get_roles(user):return True
    allowed=frappe.get_all("POS Profile User",filters={"parent":profile},pluck="user")
    return not allowed or user in allowed


def check_scope(turn, manage=False):
    require_operator()
    if turn.cajero != frappe.session.user and not supervisor():
        frappe.throw(_("Solo puede acceder a su propio turno POS."), frappe.PermissionError)
    if manage and not supervisor():
        frappe.throw(_("La anulación conjunta requiere un supervisor."), frappe.PermissionError)
    if not profile_accessible(turn.pos_profile):
        frappe.throw(_("No tiene acceso a este perfil POS."),frappe.PermissionError)
    # Branch belongs to HR in ERPNext. Operating a POS must not grant HR master
    # access, but must still respect Branch/Company/Profile User Permissions.
    if not frappe.permissions.has_user_permission(turn, user=frappe.session.user):
        frappe.throw(_("El turno está fuera de sus sucursales o empresas autorizadas."), frappe.PermissionError)


def get_turn(opening, lock=False):
    if not opening or not frappe.db.exists(TURN, opening):
        frappe.throw(_("La apertura no tiene un turno integrado."))
    turn = lock_turn(opening) if lock else frappe.get_doc(TURN, opening)
    check_scope(turn)
    return turn


def assert_open(turn):
    if turn.estado != OPEN:
        frappe.throw(_("El turno no admite operaciones: {0}. Termine o reintente el cierre conjunto.").format(turn.estado))
    if frappe.db.get_value("POS Opening Entry", turn.pos_opening_entry, "status") != "Open":
        frappe.throw(_("La apertura de ERPNext ya no está abierta."))


def exchange_rate(currency, target, date):
    if currency == target:
        return 1.0
    from erpnext.setup.utils import get_exchange_rate
    rate = get_exchange_rate(currency, target, getdate(date))
    if not valid_rate(rate):
        frappe.throw(_("No hay una tasa válida de {0} a {1} para {2}.").format(currency, target, getdate(date)))
    return flt(rate)


def payment_modes(turn):
    modes = set(frappe.parse_json(turn.get("medios_pago") or "[]"))
    if not modes:
        modes = set(frappe.get_all("POS Payment Method", filters={"parent": turn.pos_profile}, pluck="mode_of_payment"))
    modes.update(row["medio_pago"] for row in frappe.parse_json(turn.fondos_apertura or "[]"))
    return sorted(modes)


def concepts(kind):
    return frappe.get_all("IE Codigo Detalle", filters={"parent": kind, "active": 1},
                          pluck="code_value", order_by="idx asc")


def set_state(turn, state, **values):
    values["estado"] = state
    frappe.db.set_value(TURN, turn.name, values)
    turn.update(values)


def publish(turn):
    for user in {turn.cajero, turn.solicitado_por} - {None, ""}:
        frappe.publish_realtime("ie_pos_turn", {"opening": turn.name, "estado": turn.estado},
                                user=user, after_commit=True)


@frappe.whitelist()
def context(opening=None):
    if not enabled() and not (opening and frappe.db.exists(TURN, opening)):
        return {"enabled": False}
    require_operator()
    if not opening:
        return {"enabled": bool(enabled())}
    turn = get_turn(opening)
    return {"enabled": True, "turno": turn.name, "estado": turn.estado,
            "sucursal": turn.sucursal, "perfil": turn.pos_profile, "cajero": turn.cajero,
            "inicio": turn.fecha_inicio, "moneda_base": turn.moneda_base,
            "moneda_empresa": turn.moneda_empresa, "medios_pago": payment_modes(turn),
            "conceptos": {kind: concepts(kind) for kind in ("Ingreso", "Egreso")},
            "puede_cerrar": bool(frappe.has_permission("POS Closing Entry", "create") and
                                  frappe.has_permission("POS Closing Entry", "submit")),
            "puede_anular": supervisor() and bool(frappe.has_permission("POS Closing Entry", "cancel"))}


@frappe.whitelist()
def rates(opening, moneda, fecha=None):
    turn = get_turn(opening)
    date = now_datetime()
    from erpnext.setup.utils import get_exchange_rate
    def lookup(target):
        rate=1 if moneda==target else get_exchange_rate(moneda,target,getdate(date))
        return flt(rate) if valid_rate(rate) else None
    return {"tasa_de_cambio":lookup(turn.moneda_base),"tasa_empresa":lookup(turn.moneda_empresa)}


@frappe.whitelist(methods=["POST"])
def register_movement(opening, tipo, clasificacion, importe, moneda, medio_pago,
                      tasa_de_cambio=None, tasa_empresa=None, referencia=None, descripcion=None, request_id=None):
    turn = get_turn(opening, lock=True)
    assert_open(turn)
    if tipo not in ("Ingreso", "Egreso") or clasificacion not in concepts(tipo):
        frappe.throw(_("Seleccione un tipo y concepto activos."))
    if medio_pago not in payment_modes(turn):
        frappe.throw(_("El medio de pago no pertenece al perfil POS."))
    if not valid_rate(importe):
        frappe.throw(_("El importe debe ser positivo y finito."))
    if not request_id or len(str(request_id)) > 100:
        frappe.throw(_("Falta el identificador de la operación. Vuelva a abrir el formulario."))
    key = sha256(f"manual|{turn.name}|{frappe.session.user}|{request_id}".encode()).hexdigest()
    if existing := frappe.db.get_value("Movimiento", {"clave_origen_pos": key}, "name"):
        return {"name": existing}
    date = now_datetime()
    rate = 1 if moneda == turn.moneda_base else tasa_de_cambio
    company_rate = 1 if moneda == turn.moneda_empresa else (
        rate if turn.moneda_base == turn.moneda_empresa else tasa_empresa)
    if not valid_rate(rate) or not valid_rate(company_rate):
        frappe.throw(_("Indique tasas de cambio positivas y válidas."))
    return {"name": insert_movement(turn, dict(tipo=tipo, clasificacion=clasificacion,
        importe=flt(importe), moneda=moneda, tasa_de_cambio=flt(rate), tasa_empresa=flt(company_rate),
        importe_empresa=flt(flt(importe) * flt(company_rate), precision()), medio_pago=medio_pago,
        origen_pos="Manual", referencia=referencia, descripcion=descripcion,
        fecha_operacion=date, clave_origen_pos=key)).name}


def insert_movement(turn, values):
    doc = frappe.get_doc(dict(doctype="Movimiento", turno_pos=turn.name, sucursal=turn.sucursal,
        company=turn.company, moneda_empresa=turn.moneda_empresa,
        fecha_de_registro=getdate(values["fecha_operacion"]), **values))
    try:
        with internal_operation():
            doc.insert(ignore_permissions=True)
    except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
        # A unique-key conflict can be a request that committed after this transaction's
        # original snapshot. Read the winning row with a current read, not that snapshot.
        existing=frappe.db.sql("SELECT name FROM `tabMovimiento` WHERE clave_origen_pos=%s FOR UPDATE",values["clave_origen_pos"])
        if not existing:raise
        frappe.clear_last_message()
        return frappe.get_doc("Movimiento",existing[0][0],for_update=True)
    return doc


def opening_funds(turn):
    return frappe.parse_json(turn.fondos_apertura or "[]")


def totals(turn, moneda=None, medio_pago=None, for_update=False):
    filters = {"turno_pos": turn.name, "docstatus": ["<", 2]}
    if moneda:
        filters["moneda"] = moneda
    if medio_pago:
        filters["medio_pago"] = medio_pago
    query=current_rows if for_update else frappe.get_all
    rows = query("Movimiento", filters=filters,
        fields=["moneda", "medio_pago", "origen_pos", "tipo", "importe", "importe_base", "importe_empresa"])
    groups = {}
    expected_company = {mode:0.0 for mode in payment_modes(turn) if not medio_pago or mode==medio_pago}
    base = dict(apertura=0.0, ventas=0.0, devoluciones=0.0, ingresos=0.0, egresos=0.0)
    for fund in opening_funds(turn):
        if moneda and moneda != fund["moneda"] or medio_pago and medio_pago != fund["medio_pago"]:
            continue
        key = (fund["moneda"], fund["medio_pago"])
        entry = groups.setdefault(key, dict(apertura=0.0, ventas=0.0, devoluciones=0.0, ingresos=0.0, egresos=0.0))
        entry["apertura"] += flt(fund["importe"])
        base["apertura"] += flt(fund["importe_base"])
        expected_company[fund["medio_pago"]] = expected_company.get(fund["medio_pago"], 0) + flt(fund["importe"])
    for row in rows:
        entry = groups.setdefault((row.moneda, row.medio_pago), dict(apertura=0.0, ventas=0.0, devoluciones=0.0, ingresos=0.0, egresos=0.0))
        kind = "ventas" if row.origen_pos == "Venta" else "devoluciones" if row.origen_pos == "Devolucion" else "ingresos" if row.tipo == "Ingreso" else "egresos"
        entry[kind] += flt(row.importe)
        base[kind] += flt(row.importe_base)
        expected_company[row.medio_pago] = expected_company.get(row.medio_pago, 0) + flt(row.importe_empresa) * (1 if row.tipo == "Ingreso" else -1)
    for entry in [base, *groups.values()]:
        entry["saldo"] = flt(entry["apertura"] + entry["ventas"] - entry["devoluciones"] + entry["ingresos"] - entry["egresos"], precision())
    return {"por_medio_moneda": [dict(moneda=key[0], medio_pago=key[1], **entry) for key, entry in sorted(groups.items())],
            "base": base, "esperado_empresa": expected_company}


@frappe.whitelist()
def report(opening, moneda=None, medio_pago=None, start=0, page_length=25):
    turn = get_turn(opening)
    filters = {"turno_pos": turn.name, "docstatus": ["<", 2]}
    if moneda: filters["moneda"] = moneda
    if medio_pago: filters["medio_pago"] = medio_pago
    result = totals(turn, moneda, medio_pago)
    result.update(inicio=turn.fecha_inicio, corte=turn.fecha_final or now_datetime(),
        moneda_base=turn.moneda_base, moneda_empresa=turn.moneda_empresa, estado=turn.estado,
        ultimo_error=turn.ultimo_error, total=frappe.db.count("Movimiento", filters),
        movimientos=frappe.get_all("Movimiento", filters=filters,
            fields=["name", "fecha_operacion", "tipo", "clasificacion", "origen_pos", "medio_pago", "moneda", "importe", "importe_base", "referencia"],
            order_by="fecha_operacion desc, creation desc", limit_start=max(0,cint(start)), limit_page_length=min(100,max(1,cint(page_length)))))
    return result


@frappe.whitelist()
def status(opening):
    turn = get_turn(opening)
    return status_data(turn)


def status_data(turn):
    erp=frappe.db.get_value("POS Closing Entry",turn.pos_closing_entry,["status","error_message"],as_dict=True) if turn.pos_closing_entry else None
    return {"opening": turn.name, "estado": turn.estado, "error": turn.ultimo_error,
            "pos_closing_entry": turn.pos_closing_entry, "operacion": turn.operacion,
            "erp_estado": erp.status if erp else None,
            "erp_error": erp.error_message if erp and erp.status=="Failed" else None}


def check_no_later_turn(turn):
    later=frappe.db.sql("""SELECT name FROM `tabPOS Opening Entry`
        WHERE pos_profile=%s AND docstatus=1 AND name!=%s AND creation>%s LIMIT 1 FOR UPDATE""",
        (turn.pos_profile,turn.name,turn.creation))
    if later:
        frappe.throw(_("Ya existe un turno posterior de este perfil POS. No se puede reabrir este turno."))


def make_erp_closing(turn, cutoff):
    """Use the immutable opening link, never recapture another turn by date alone.

    Current reads matter under MariaDB REPEATABLE READ: an invoice may have
    committed while this request was waiting for the turn lock.
    """
    doc=frappe.get_doc(dict(doctype="POS Closing Entry",pos_opening_entry=turn.name,
        period_start_date=turn.fecha_inicio,period_end_date=cutoff,pos_profile=turn.pos_profile,
        user=turn.cajero,company=turn.company))
    taxes={}
    for kind,table,link in (("POS Invoice","pos_invoices","pos_invoice"),("Sales Invoice","sales_invoices","sales_invoice")):
        invoices=current_rows(kind,filters={"custom_ie_turno_pos":turn.name,"docstatus":1},
            fields=["name","posting_date","grand_total","net_total","total_qty","total_taxes_and_charges","customer","is_return","return_against"],
            order_by="creation asc")
        for invoice in invoices:
            doc.append(table,{link:invoice.name,**{key:invoice[key] for key in
                ("posting_date","grand_total","customer","is_return","return_against")}})
            for target,source in (("grand_total","grand_total"),("net_total","net_total"),
                                  ("total_quantity","total_qty"),("total_taxes_and_charges","total_taxes_and_charges")):
                doc.set(target,flt(doc.get(target))+flt(invoice[source]))
        if invoices:
            for row in current_rows("Sales Taxes and Charges",filters={"parenttype":kind,"parent":["in",[inv.name for inv in invoices]]},
                    fields=["account_head","tax_amount"]):
                taxes[row.account_head]=taxes.get(row.account_head,0)+flt(row.tax_amount)
    for account,amount in taxes.items():doc.append("taxes",dict(account_head=account,amount=amount))
    return doc


@frappe.whitelist(methods=["POST"])
def start_closing(opening, counted=None):
    turn = get_turn(opening, lock=True)
    frappe.has_permission("POS Closing Entry", "create", throw=True)
    frappe.has_permission("POS Closing Entry", "submit", throw=True)
    if turn.estado == CLOSED:
        return status_data(turn)
    if turn.estado != OPEN:
        return retry(opening)
    assert_open(turn)
    data = totals(turn,for_update=True)
    counted = frappe.parse_json(counted or "{}")
    if not isinstance(counted, dict) or set(counted) != set(data["esperado_empresa"]):
        frappe.throw(_("Indique el importe contado para cada medio de pago del arqueo."))
    for value in counted.values():
        try:
            valid = value is not None and value != "" and isfinite(float(value))
        except (ValueError, TypeError): valid = False
        if not valid: frappe.throw(_("Los importes contados deben ser números finitos."))
    cutoff = now_datetime()
    # Both expected figures and linked invoice lists are built on the server while the turn is locked.
    pce = make_erp_closing(turn,cutoff)
    pce.set("payment_reconciliation", [])
    initial = {row["medio_pago"]: row["importe"] for row in opening_funds(turn)}
    for mode, amount in data["esperado_empresa"].items():
        pce.append("payment_reconciliation", dict(mode_of_payment=mode, opening_amount=initial.get(mode,0),
            expected_amount=flt(amount,precision()), closing_amount=flt(counted[mode],precision()),
            difference=flt(flt(counted[mode])-amount,precision())))
    with internal_operation():
        pce.insert()
    set_state(turn, "Cerrando POS", fecha_final=cutoff, operacion="Cierre", solicitado_por=frappe.session.user,
              pos_closing_entry=pce.name, ultimo_error="")
    # ERPNext may commit its consolidation independently. Persist the saga before entering it.
    frappe.db.commit()
    advance(turn.name)
    return status(opening)


@frappe.whitelist(methods=["POST"])
def retry(opening):
    turn = get_turn(opening, lock=True)
    if turn.estado in (OPEN, CLOSED, CANCELLED):
        return status_data(turn)
    if turn.operacion == "Anulacion":
        check_scope(turn, manage=True)
        frappe.has_permission("POS Closing Entry", "cancel", throw=True)
        check_no_later_turn(turn)
    else:
        frappe.has_permission("POS Closing Entry", "submit", throw=True)
    frappe.db.set_value(TURN, turn.name, "solicitado_por", frappe.session.user)
    frappe.db.commit()
    advance(turn.name, retry_failed=True)
    return status(opening)


@frappe.whitelist(methods=["POST"])
def cancel_closing(opening):
    turn = get_turn(opening)
    lock_profile(turn.pos_profile)
    turn = get_turn(opening, lock=True)
    check_scope(turn, manage=True)
    frappe.has_permission("POS Closing Entry", "cancel", throw=True)
    check_no_later_turn(turn)
    if turn.operacion == "Anulacion" and turn.estado != OPEN:
        return retry(opening)
    if turn.estado != CLOSED:
        frappe.throw(_("Solo puede anular un turno cuyo cierre conjunto haya finalizado."))
    set_state(turn, "Anulando", operacion="Anulacion", solicitado_por=frappe.session.user, ultimo_error="")
    frappe.db.commit()
    advance(turn.name)
    return status(opening)


def record_error(name, error):
    frappe.db.rollback()
    turn = lock_turn(name)
    set_state(turn, "Error", ultimo_error=str(error)[:1500])
    publish(turn)
    frappe.db.commit()
    frappe.log_error(title=f"IE POS {name}", message=frappe.get_traceback())


def advance(name, retry_failed=False):
    """Reconcile durable state with the real ERP status; safe after callbacks, retries or lost tabs."""
    from redis.exceptions import LockError
    try:
        with frappe.cache.lock(frappe.cache.make_key(f"ie-pos:{name}"), timeout=900, blocking_timeout=0):
            _advance(name, retry_failed=retry_failed)
    except LockError:
        return
    except Exception as exc:
        record_error(name, exc)


def _advance(name, retry_failed=False):
    turn = lock_turn(name)
    if turn.estado in (OPEN, CLOSED, CANCELLED) or not turn.pos_closing_entry:
        return
    pce = frappe.get_doc("POS Closing Entry", turn.pos_closing_entry,for_update=True)
    actor = frappe.session.user
    try:
        frappe.set_user(turn.solicitado_por or turn.cajero)
        with internal_operation():
            if turn.operacion == "Anulacion":
                check_no_later_turn(turn)
                if pce.docstatus == 1:
                    frappe.has_permission("POS Closing Entry", "cancel", doc=pce, throw=True)
                    pce.cancel()
                elif pce.docstatus == 2 and pce.status not in ("Cancelled", "Queued") and retry_failed:
                    from erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log import unconsolidate_pos_invoices
                    unconsolidate_pos_invoices(closing_entry=pce)
                pce.reload()
                if pce.docstatus == 2 and pce.status == "Cancelled" and frappe.db.get_value("POS Opening Entry",turn.name,"status") == "Open":
                    # ERP may have committed already; persist its completion before reversing IE.
                    set_state(turn,"Anulando",ultimo_error="")
                    frappe.db.commit();turn=lock_turn(name)
                    # All IE currencies are reversed in one transaction, after ERP reversal succeeds.
                    for name_ in frappe.get_all(CLOSURE, filters={"turno_pos":turn.name,"docstatus":1}, pluck="name"):
                        doc = frappe.get_doc(CLOSURE,name_);doc.flags.ignore_permissions=True;doc.cancel()
                    set_state(turn, OPEN, fecha_final=None, operacion="", ultimo_error="")
                elif pce.status == "Failed":
                    set_state(turn,"Error",ultimo_error=pce.error_message or _("Falló la anulación de ERPNext."))
            else:
                if pce.docstatus == 0:
                    frappe.has_permission("POS Closing Entry", "submit", doc=pce, throw=True)
                    pce.submit()
                elif pce.docstatus == 1 and pce.status == "Failed" and retry_failed:
                    from erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log import consolidate_pos_invoices
                    consolidate_pos_invoices(closing_entry=pce)
                pce.reload()
                if pce.docstatus == 1 and pce.status == "Submitted" and frappe.db.get_value("POS Opening Entry",turn.name,"status") == "Closed":
                    set_state(turn,"Cerrando app",ultimo_error="")
                    frappe.db.commit();turn=lock_turn(name)
                    finalize_closures(turn)
                    set_state(turn,CLOSED,operacion="",ultimo_error="")
                elif pce.status == "Failed":
                    set_state(turn,"Error",ultimo_error=pce.error_message or _("Falló la consolidación de ERPNext."))
        publish(turn)
        frappe.db.commit()
    finally:
        frappe.set_user(actor)


def reconcile_pending():
    for name in frappe.get_all(TURN, filters={"estado":["not in",[OPEN,CLOSED,CANCELLED]]}, pluck="name"):
        advance(name)


def enqueue_reconcile(doc, method=None):
    if not frappe.db.exists(TURN,doc.name): return
    frappe.enqueue("ingresos_egresos.pos.advance", name=doc.name,
                   job_id=f"ie-pos-finalize:{doc.name}", deduplicate=True, enqueue_after_commit=True)


def finalize_closures(turn):
    currencies = set(frappe.get_all("Movimiento", filters={"turno_pos":turn.name,"docstatus":["<",2]},pluck="moneda"))
    currencies.add(turn.moneda_empresa)
    for currency in sorted(currencies):
        if frappe.db.exists(CLOSURE,{"turno_pos":turn.name,"pos_closing_entry":turn.pos_closing_entry,"moneda":currency,"docstatus":1}): continue
        closure = frappe.get_doc(dict(doctype=CLOSURE,turno_pos=turn.name,pos_closing_entry=turn.pos_closing_entry,
            sucursal=turn.sucursal,moneda=currency,fecha_inicio=getdate(turn.fecha_inicio),fecha_final=getdate(turn.fecha_final),
            fecha_hora_inicio=turn.fecha_inicio,fecha_hora_final=turn.fecha_final))
        closure.flags.ignore_permissions=True
        closure.insert(ignore_permissions=True);closure.submit()


def populate_closure(doc):
    if not frappe.flags.ie_pos_internal:
        frappe.throw(_("Utilice el cierre conjunto del turno POS."))
    turn = lock_turn(doc.turno_pos)
    pce = frappe.get_doc("POS Closing Entry",turn.pos_closing_entry)
    if pce.status != "Submitted" or pce.docstatus != 1:
        frappe.throw(_("ERPNext todavía no ha finalizado el cierre."))
    doc.sucursal=turn.sucursal;doc.pos_closing_entry=pce.name;doc.moneda_base=turn.moneda_base
    doc.fecha_inicio=getdate(turn.fecha_inicio);doc.fecha_final=getdate(turn.fecha_final)
    doc.fecha_hora_inicio=turn.fecha_inicio;doc.fecha_hora_final=turn.fecha_final
    doc.set("ingresos",[]);doc.set("egresos",[])
    doc.total_ingresos=doc.total_egresos=doc.total_ingresos_base=doc.total_egresos_base=0
    for row in frappe.get_all("Movimiento",filters={"turno_pos":turn.name,"moneda":doc.moneda,"docstatus":["<",2]},
            fields=["name","fecha_de_registro","clasificacion","importe","importe_base","descripcion","tipo"],order_by="fecha_operacion asc, name asc"):
        doc.append("ingresos" if row.tipo=="Ingreso" else "egresos",dict(registro=row.name,fecha=row.fecha_de_registro,
            clasificación=row.clasificacion,importe=row.importe,importe_base=row.importe_base,moneda=doc.moneda,
            moneda_base=turn.moneda_base,descripcion=row.descripcion))
        prefix="total_ingresos" if row.tipo=="Ingreso" else "total_egresos"
        doc.set(prefix,flt(doc.get(prefix))+flt(row.importe));doc.set(prefix+"_base",flt(doc.get(prefix+"_base"))+flt(row.importe_base))
    funds=[row for row in opening_funds(turn) if row["moneda"]==doc.moneda]
    doc.saldo_apertura_pos=sum(flt(row["importe"]) for row in funds)
    doc.saldo_apertura_pos_base=sum(flt(row["importe_base"]) for row in funds)
    doc.saldo_final=doc.saldo_apertura_pos+doc.total_ingresos-doc.total_egresos
    doc.saldo_final_base=doc.saldo_apertura_pos_base+doc.total_ingresos_base-doc.total_egresos_base


def link_closure_movements(doc):
    if not frappe.flags.ie_pos_internal: frappe.throw(_("Utilice el cierre conjunto POS."))
    frappe.db.sql("""UPDATE `tabMovimiento` SET vinculado=1,cierre=%s,docstatus=1
        WHERE turno_pos=%s AND moneda=%s AND docstatus<2""",(doc.name,doc.turno_pos,doc.moneda))


def validate_pos_movement(doc):
    if not frappe.flags.ie_pos_internal:
        frappe.throw(_("Los movimientos de turnos POS se gestionan desde la integración."))
    turn=lock_turn(doc.turno_pos)
    assert_open(turn)
    if doc.sucursal != turn.sucursal or doc.company != turn.company:
        frappe.throw(_("El movimiento no corresponde a la sucursal y empresa del turno."))
    if not doc.fecha_operacion or get_datetime(doc.fecha_operacion)<get_datetime(turn.fecha_inicio):
        frappe.throw(_("La fecha de operación debe pertenecer al turno."))
    if doc.medio_pago not in payment_modes(turn):
        frappe.throw(_("Medio de pago inválido para el turno."))
    if not valid_rate(doc.tasa_empresa) or not isfinite(flt(doc.importe_empresa)):
        frappe.throw(_("Importe o tasa de empresa inválidos."))
    doc.moneda_empresa=turn.moneda_empresa
    if doc.origen_pos in ("Venta","Devolucion") and turn.moneda_base==turn.moneda_empresa:
        doc.importe_base=doc.importe_empresa
