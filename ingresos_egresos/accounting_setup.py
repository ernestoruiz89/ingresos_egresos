import frappe


def setup():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({"Journal Entry": [dict(fieldname="custom_ie_movimiento", label="Movimiento de Ingresos y Egresos",
        fieldtype="Link", options="Movimiento", read_only=1, no_copy=1, search_index=1,
        insert_after="user_remark")], "Asset": [
            dict(fieldname="custom_ie_movimiento", label="Movimiento de adquisición", fieldtype="Link", options="Movimiento",
                read_only=1, no_copy=1, search_index=1, insert_after="purchase_invoice"),
            dict(fieldname="custom_ie_asiento_contable", label="Asiento de adquisición", fieldtype="Link", options="Journal Entry",
                read_only=1, no_copy=1, insert_after="custom_ie_movimiento")
        ]}, update=True)
    # Existing automatic receipts keep their native invoice accounting.
    # Populate the new display state without touching amounts or timestamps.
    frappe.db.set_value("Movimiento", {"origen_pos": ["in", ["Venta", "Devolucion"]],
        "asiento_contable": ["is", "not set"]}, "estado_contable", "Gestionado por POS", update_modified=False)
