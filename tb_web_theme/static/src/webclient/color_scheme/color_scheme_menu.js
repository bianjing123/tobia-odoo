/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { cookie } from "@web/core/browser/cookie";
import { location } from "@web/core/browser/browser";

class ThemeColorSchemeToggle extends Component {
    static template = "tb_web_theme.ColorSchemeToggle";

    get isDark() {
        return cookie.get("color_scheme") === "dark";
    }

    toggle() {
        cookie.set("color_scheme", this.isDark ? "light" : "dark");
        location.reload();
    }
}

registry.category("systray").add("tb_web_theme.ColorSchemeToggle", {
    Component: ThemeColorSchemeToggle,
}, { sequence: 45 });
