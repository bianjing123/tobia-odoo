/** @odoo-module **/

import { onMounted, onPatched, onWillDestroy } from "@odoo/owl";
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";

patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            this.tbOnResize = () => this.tbScheduleRecalc();
            this.tbOnDocClick = (ev) => {
                // Toggle button → toggle panel
                const toggle = ev.target.closest(".tb_apps_more_toggle");
                if (toggle) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    const more = toggle.closest(".tb_apps_more");
                    if (more) more.classList.toggle("open");
                    return;
                }
                // Outside click → close
                if (!ev.target.closest(".tb_apps_more")) {
                    const m = document.querySelector(".tb_apps_more.open");
                    if (m) m.classList.remove("open");
                }
            };
            window.addEventListener("resize", this.tbOnResize);
            document.addEventListener("click", this.tbOnDocClick, true);
            this.tbScheduleRecalc();
        });
        onPatched(() => this.tbScheduleRecalc());
        onWillDestroy(() => {
            if (this.tbOnResize) {
                window.removeEventListener("resize", this.tbOnResize);
                document.removeEventListener("click", this.tbOnDocClick, true);
            }
        });
    },

    tbScheduleRecalc() {
        if (this.tbRaf) return;
        this.tbRaf = requestAnimationFrame(() => {
            this.tbRaf = null;
            this.tbRecalc();
        });
    },

    /**
     * Overflow pills stay in the bar DOM but are taken out of flow with
     * `visibility:hidden; position:absolute` — Owl keeps managing them, so
     * re-renders never orphan anything. The "更多" panel renders every app
     * via Owl with real handlers; we only toggle display on its items so
     * exactly the overflowing ones show up.
     */
    tbRecalc() {
        const bar = document.querySelector(".tb_apps_bar");
        const more = document.querySelector(".tb_apps_more");
        if (!bar || !more) return;

        const pills = [...bar.querySelectorAll(":scope > .tb_apps_bar_item")];
        // Restore natural flow so measurements are stable.
        for (const p of pills) {
            p.style.visibility = "";
            p.style.position = "";
            p.style.pointerEvents = "";
        }
        const barW = bar.clientWidth;

        const overflowXmlids = new Set();
        for (const p of pills) {
            if (p.offsetLeft + p.offsetWidth > barW + 1) {
                overflowXmlids.add(p.dataset.menuXmlid);
                p.style.visibility = "hidden";
                p.style.position = "absolute";
                p.style.pointerEvents = "none";
            }
        }

        const panel = more.querySelector(".tb_apps_more_panel");
        if (panel) {
            for (const item of panel.querySelectorAll(".tb_apps_more_item")) {
                item.style.display = overflowXmlids.has(item.dataset.menuXmlid) ? "" : "none";
            }
        }
        more.style.display = overflowXmlids.size ? "" : "none";
    },
});
