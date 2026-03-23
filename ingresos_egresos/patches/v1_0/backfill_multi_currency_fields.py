import frappe


def execute():
    moneda_base = frappe.db.get_single_value("IE Configuracion", "moneda_base")

    if not moneda_base:
        frappe.log_error("No se pudo ejecutar el backfill de multimoneda porque IE Configuracion.moneda_base no está definido.", "backfill_multi_currency_fields")
        return

    frappe.db.sql(
        """
        UPDATE `tabMovimiento`
        SET moneda = %s
        WHERE IFNULL(moneda, '') = ''
        """,
        (moneda_base,),
    )

    frappe.db.sql(
        """
        UPDATE `tabMovimiento`
        SET tasa_de_cambio = 1
        WHERE moneda = %s
          AND (tasa_de_cambio IS NULL OR tasa_de_cambio <= 0)
        """,
        (moneda_base,),
    )

    frappe.db.sql(
        """
        UPDATE `tabMovimiento`
        SET importe_base = importe * tasa_de_cambio
        WHERE importe_base IS NULL
          AND tasa_de_cambio IS NOT NULL
          AND tasa_de_cambio > 0
        """
    )
