import json
from pathlib import Path
import frappe


def ensure_roles():
    for name in ("IE Cajero POS","IE Supervisor POS"):
        if not frappe.db.exists("Role",name):
            frappe.get_doc(dict(doctype="Role",role_name=name,desk_access=1)).insert(ignore_permissions=True)


def setup():
    ensure_roles()
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({dt:[dict(fieldname="custom_ie_turno_pos",label="Turno Ingresos y Egresos",fieldtype="Link",
        options="IE Turno POS",read_only=1,no_copy=1,search_index=1,insert_after="pos_profile")] for dt in ("POS Invoice","Sales Invoice")},update=True)
    frappe.db.add_unique("Registro de Cierre de Movimiento",["turno_pos","pos_closing_entry","moneda"],
        constraint_name="unique_ie_pos_closure_currency")
    frappe.db.add_index("Movimiento",["turno_pos","fecha_operacion"],index_name="ie_pos_movement_date")
    frappe.db.add_index("IE Turno POS",["pos_profile","estado"],index_name="ie_pos_profile_state")
    if frappe.db.get_single_value("IE Configuracion","integrar_pos",cache=False) is None:
        frappe.db.set_single_value("IE Configuracion","integrar_pos",0)
    seed_concepts()


def seed_concepts():
    # Seed only missing documents: fixture imports would overwrite a site's own concepts.
    seeds=json.loads((Path(__file__).parent/'fixtures/ie_codigo.json').read_text(encoding='utf-8'))
    for seed in seeds:
        if not frappe.db.exists("IE Codigo",seed['name']):frappe.get_doc(seed).insert(ignore_permissions=True)
    for kind,value in (("Ingreso","Ventas POS"),("Egreso","Devoluciones POS")):
        doc=frappe.get_doc("IE Codigo",kind)
        if not any(row.code_value==value for row in doc.code_values):
            doc.append("code_values",dict(code_value=value,active=1));doc.save(ignore_permissions=True)
