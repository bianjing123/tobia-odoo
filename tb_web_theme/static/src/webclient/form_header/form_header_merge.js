/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onMounted, onWillUnmount } from "@odoo/owl";

/**
 * Lifts the form status bar (business buttons + state steps) out of the content
 * area and into the control panel, so a record opens with a single header row.
 *
 * The rule is generic: it only relies on the layout contract shared by every
 * view (`web.Layout` renders `.o_control_panel` then `.o_content` as siblings,
 * the form compiler renders `.o_form_statusbar` at the top of `.o_content`).
 * No model, field or button label is ever matched.
 *
 * Because the status bar belongs to the Owl-rendered form, the move is applied
 * again after every DOM update (idempotent), and a status bar left over by a
 * previous record is hidden instead of removed, so Owl keeps owning its node.
 */
export class FormHeaderMerge extends Component {
    static template = "tb_web_theme.FormHeaderMerge";

    setup() {
        this.observer = null;
        this.frame = null;
        onMounted(() => {
            this.observer = new MutationObserver(() => this.schedule());
            this.observer.observe(document.body, { childList: true, subtree: true });
            this.merge();
        });
        onWillUnmount(() => {
            this.observer?.disconnect();
            if (this.frame) {
                cancelAnimationFrame(this.frame);
            }
        });
    }

    schedule() {
        if (this.frame) {
            return;
        }
        this.frame = requestAnimationFrame(() => {
            this.frame = null;
            this.merge();
        });
    }

    merge() {
        for (const statusbar of document.querySelectorAll(".o_form_statusbar")) {
            if (statusbar.classList.contains("tb_form_header_stale")) {
                continue;
            }
            const content = statusbar.closest(".o_content");
            const host = content?.parentElement;
            const panel = host
                ? [...host.children].find((el) => el.classList.contains("o_control_panel"))
                : null;
            const header = panel?.querySelector(".o_control_panel_main");
            if (!header) {
                continue;
            }
            panel.classList.add("tb_form_header");

            // the create button ships inside the breadcrumb row; the target
            // header keeps every record action on the second line
            const create = panel.querySelector(".o_control_panel_main_buttons");
            if (create && create.parentElement !== header) {
                header.prepend(create);
            }

            const merged = header.querySelector(":scope > .o_form_statusbar");
            if (merged !== statusbar) {
                if (merged) {
                    merged.classList.add("tb_form_header_stale");
                }
                header.append(statusbar);
            }
        }
    }
}

registry.category("main_components").add("tb_web_theme.FormHeaderMerge", {
    Component: FormHeaderMerge,
});
