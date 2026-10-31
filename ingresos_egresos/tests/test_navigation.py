import frappe
from frappe.tests import IntegrationTestCase
from frappe.apps import get_apps
from frappe.desk.doctype.sidebar.sidebar import resolve_sidebar
from frappe.desk.doctype.dock.dock import get_app_dock

from ingresos_egresos.navigation import has_app_permission


class TestNavigation(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_standard_navigation_survives_migration(self):
        sidebar = frappe.get_doc("Sidebar", "Ingresos y Egresos")
        self.assertEqual((sidebar.module, sidebar.app, sidebar.standard),
                         ("Ingresos y Egresos", "ingresos_egresos", 1))
        for item in sidebar.items:
            if item.type == "Link":
                self.assertTrue(frappe.db.exists(item.link_type, item.link_to), item.link_to)
        resolved = resolve_sidebar(sidebar.name, "Administrator")
        self.assertFalse(resolved.computed)
        destinations = {item.get("link_to") for item in resolved.items}
        self.assertTrue({"dashboard-movimientos", "Movimiento", "Registro de Cierre de Movimiento",
                         "IE Configuracion", "IE Codigo", "IE Turno POS", "Reporte de Movimientos",
                         "Reporte de Movimientos por Concepto", "Reporte de Flujo de Caja"} <= destinations)
        self.assertIn("Configuración y POS",{item.get("label") for item in resolved.items})
        dock = get_app_dock("ingresos_egresos")
        self.assertEqual(len(dock), 1)
        self.assertEqual(dock[0]["link_to"], sidebar.name)

    def test_app_entry_opens_its_module_dashboard(self):
        self.assertTrue(has_app_permission())
        entries = [entry for entry in get_apps() if entry["name"] == "ingresos_egresos"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["route"], "/desk/ingresos-y-egresos/dashboard-movimientos")

    def test_guest_cannot_access_the_app_or_navigation(self):
        frappe.set_user("Guest")
        try:
            self.assertFalse(has_app_permission())
            self.assertIsNone(resolve_sidebar("Ingresos y Egresos", "Guest"))
        finally:
            frappe.set_user("Administrator")
