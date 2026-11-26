/** @odoo-module **/

import { Component, markup, onWillDestroy, proxy, useListener } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { render } from "@web/owl2/utils";

const SIDEBAR_STATE_KEY = "tb_web_theme.sidebar.collapsed";

const LETTER_COLORS = ["#3AA382", "#E8A33D", "#C4577E", "#5A9FD4", "#8E6FC0", "#59A68C", "#D4785A"];

// Inline SVG icon set. The `oi` class relies on Material Symbols ligatures,
// and any name missing from the shipped font subset falls back to the same
// default glyph (a gear), so every entry used to look alike.
const svg = (body) =>
    markup(
        `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ` +
            `stroke-linecap="round" stroke-linejoin="round">${body}</svg>`
    );

const SVG_ICONS = {
    box: svg('<path d="M12 3 21 7.5v9L12 21 3 16.5v-9Z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/>'),
    layers: svg('<path d="M12 3 3 7.5 12 12l9-4.5Z"/><path d="m3 12.5 9 4.5 9-4.5"/><path d="m3 17 9 4.5 9-4.5"/>'),
    tag: svg('<path d="M4 4h7l9 9-7 7-9-9z"/><circle cx="8" cy="8" r="1.3"/>'),
    price: svg('<path d="M4 4h7l9 9-7 7-9-9z"/><path d="m8.6 14 5-5"/><circle cx="9" cy="9.4" r="1"/><circle cx="13" cy="13.4" r="1"/>'),
    barcode: svg('<path d="M4 6v12M8 6v12M12 6v12M16 6v12M20 6v12"/>'),
    user: svg('<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>'),
    users: svg('<circle cx="9.5" cy="8" r="3.2"/><path d="M3.5 20a6 6 0 0 1 12 0"/><path d="M16.5 5.6a3.2 3.2 0 0 1 0 4.9M17.8 14.2a5.6 5.6 0 0 1 3.2 5.8"/>'),
    building: svg('<path d="M4 21V5l8-2v18"/><path d="M12 8.5h8V21"/><path d="M7 8h2M7 12h2M7 16h2M15 12h2M15 16h2"/>'),
    receipt: svg('<path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z"/><path d="M9 8h6M9 12h6"/>'),
    bill: svg('<path d="M5.5 3h13v18h-13Z"/><path d="M8.5 7.5h7M8.5 11h7"/><path d="M10 15.2h4M12 13.8v3.4"/>'),
    refund: svg('<path d="M4.5 12a7.5 7.5 0 1 0 2.3-5.4"/><path d="M4 5.2v4h4"/><path d="M9.5 12h5M12 9.5v5"/>'),
    card: svg('<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18"/><path d="M7 14h3"/>'),
    coin: svg('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v9M9.6 10h3.6a1.7 1.7 0 0 1 0 3.4H9.6"/>'),
    chart: svg('<path d="M4 20h16"/><path d="M6.5 17v-5M11 17V8M15.5 17v-3M20 17v-7"/>'),
    // real cog outline: a circle with spokes reads like a sun at 16px
    gear: svg('<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.6a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.6a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="3"/>'),
    dashboard: svg('<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>'),
    warehouse: svg('<path d="M3 21V8l9-4 9 4v13"/><path d="M8 21v-6.5h8V21"/><path d="M8 11h8"/>'),
    pin: svg('<path d="M12 21s6-5.2 6-10a6 6 0 1 0-12 0c0 4.8 6 10 6 10Z"/><circle cx="12" cy="11" r="2.2"/>'),
    route: svg('<circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="18" r="2.4"/><path d="M8.4 6H14a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h.6"/>'),
    clipboard: svg('<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2.6h6V4"/><path d="m8.6 12.2 2 2 4-4.2"/>'),
    loop: svg('<path d="M4 12a8 8 0 0 1 13.5-5.5M20 12a8 8 0 0 1-13.5 5.5"/><path d="M17 3v4h-4M7 21v-4h4"/>'),
    restock: svg('<path d="M12 20V6"/><path d="m8 10 4-4 4 4"/><path d="M5 16.5a7 7 0 0 0 14 0"/>'),
    sliders: svg('<path d="M4 7h9M18.5 7H20M4 17h3.5M12.5 17H20"/><circle cx="15.5" cy="7" r="2.1"/><circle cx="10" cy="17" r="2.1"/>'),
    list: svg('<path d="M8.5 6h11M8.5 12h11M8.5 18h11"/><circle cx="4.7" cy="6" r="1"/><circle cx="4.7" cy="12" r="1"/><circle cx="4.7" cy="18" r="1"/>'),
    percent: svg('<path d="m6.5 17.5 11-11"/><circle cx="7.8" cy="7.8" r="2.1"/><circle cx="16.2" cy="16.2" r="2.1"/>'),
    book: svg('<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v18H6.5A2.5 2.5 0 0 0 4 23Z"/><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20"/>'),
    printer: svg('<path d="M7 9V3h10v6"/><rect x="3.5" y="9" width="17" height="7" rx="2"/><path d="M7 14h10v7H7z"/>'),
    calendar: svg('<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
    mail: svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 6 8.5-6"/>'),
    trash: svg('<path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13"/>'),
    truck: svg('<path d="M3 6.5h10v9.5H3z"/><path d="M13 10.5h3.8L20 13.5V16h-7z"/><circle cx="7" cy="18" r="1.8"/><circle cx="17" cy="18" r="1.8"/>'),
    arrowIn: svg('<path d="M4 12h11"/><path d="m11.5 8 4 4-4 4"/><path d="M20 4.5v15"/>'),
    arrowOut: svg('<path d="M20 12H9"/><path d="m12.5 8-4 4 4 4"/><path d="M4 4.5v15"/>'),
    check: svg('<circle cx="12" cy="12" r="8.5"/><path d="m8.3 12.4 2.6 2.6 4.7-5.2"/>'),
    clock: svg('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.4V12l3.1 2"/>'),
    globe: svg('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/><path d="M12 3.5c2.6 2.7 2.6 14.3 0 17M12 3.5c-2.6 2.7-2.6 14.3 0 17"/>'),
    shield: svg('<path d="M12 3 20 6v6c0 4.4-3.3 7.7-8 9-4.7-1.3-8-4.6-8-9V6Z"/><path d="m8.7 12.2 2.3 2.3 4.3-4.6"/>'),
    doc: svg('<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>'),
    phone: svg('<path d="M6.6 3.5h3l1.5 4-2 1.4a11.2 11.2 0 0 0 5 5l1.4-2 4 1.5v3a2 2 0 0 1-2.2 2A16.6 16.6 0 0 1 4.4 5.7a2 2 0 0 1 2.2-2.2Z"/>'),
    dot: svg('<circle cx="12" cy="12" r="3.5"/>'),
};


// Chinese keyword → icon, first match wins. Longest / most specific names are
// listed first so that e.g. 产品类别 does not fall into 产品.
const KEYWORD_ICONS = [
    ["合作伙伴报表", "users"],
    ["对账单报表", "receipt"],
    ["按库位的库存", "pin"],
    ["产品类别", "layers"],
    ["单位和包装", "box"],
    ["会计科目表", "list"],
    ["日记账分录", "book"],
    ["分析会计", "book"],
    ["多个分类账", "book"],
    ["批次调拨", "loop"],
    ["上架规则", "list"],
    ["命名规则", "list"],
    ["付款条款", "doc"],
    ["国际贸易术语", "globe"],
    ["在线支付", "globe"],
    ["打印纸", "printer"],
    ["发送服务器", "mail"],
    ["收件服务器", "mail"],
    ["客户端动作", "gear"],
    ["用户界面", "dashboard"],
    ["销售人员", "users"],
    ["销售订单", "doc"],
    ["采购订单", "doc"],
    ["报价单", "doc"],
    ["价格表", "price"],
    ["价目", "price"],
    ["序列号", "barcode"],
    ["条码", "barcode"],
    ["批次", "barcode"],
    ["税项", "percent"],
    ["税", "percent"],
    ["币别", "coin"],
    ["日记账", "book"],
    ["会计", "book"],
    ["财务", "coin"],
    ["银行", "card"],
    ["现金", "coin"],
    ["调拨", "loop"],
    ["转移", "loop"],
    ["内部", "loop"],
    ["补货", "restock"],
    ["运行调度器", "clock"],
    ["调整", "sliders"],
    ["规则", "list"],
    ["路线", "route"],
    ["位置", "pin"],
    ["仓库", "warehouse"],
    ["库存", "warehouse"],
    ["存货", "warehouse"],
    ["盘点", "clipboard"],
    ["实物", "box"],
    ["收货", "arrowIn"],
    ["入库", "arrowIn"],
    ["出库", "arrowOut"],
    ["交货", "truck"],
    ["出货", "truck"],
    ["发运", "truck"],
    ["配送", "truck"],
    ["包裹", "box"],
    ["报废", "trash"],
    ["退货", "refund"],
    ["退款", "refund"],
    ["发票", "receipt"],
    ["账单", "bill"],
    ["付款", "card"],
    ["收款", "coin"],
    ["支付", "card"],
    ["交易", "coin"],
    ["属性", "tag"],
    ["标签", "tag"],
    ["类别", "layers"],
    ["分类", "layers"],
    ["产品", "box"],
    ["商品", "box"],
    ["物料", "box"],
    ["变体", "layers"],
    ["服务与材料", "layers"],
    ["供应商", "building"],
    ["合作伙伴", "users"],
    ["联系人", "users"],
    ["客户", "user"],
    ["顾客", "user"],
    ["用户", "user"],
    ["团队", "users"],
    ["会员", "users"],
    ["关注者", "users"],
    ["公司", "building"],
    ["报表", "chart"],
    ["报告", "chart"],
    ["分析", "chart"],
    ["统计", "chart"],
    ["概述", "dashboard"],
    ["仪表板", "dashboard"],
    ["工作期间", "calendar"],
    ["工作时间表", "calendar"],
    ["休息时间", "calendar"],
    ["日历", "calendar"],
    ["日程", "calendar"],
    ["入职", "calendar"],
    ["活动", "clock"],
    ["计划的操作", "clock"],
    ["计划行动", "clock"],
    ["日志", "doc"],
    ["审计", "shield"],
    ["视图", "layers"],
    ["字段", "list"],
    ["模型", "layers"],
    ["菜单项", "list"],
    ["服务器操作", "gear"],
    ["自动化", "gear"],
    ["动作", "gear"],
    ["序列", "list"],
    ["序号", "list"],
    ["筛选", "list"],
    ["分组", "users"],
    ["角色", "shield"],
    ["语言", "globe"],
    ["翻译", "globe"],
    ["模板", "doc"],
    ["附件", "doc"],
    ["通知", "mail"],
    ["消息", "mail"],
    ["邮件", "mail"],
    ["EMail", "mail"],
    ["邮箱", "mail"],
    ["讨论", "mail"],
    ["频道", "mail"],
    ["渠道", "mail"],
    ["别名", "mail"],
    ["服务器", "gear"],
    ["短信息", "phone"],
    ["电话", "phone"],
    ["语音", "phone"],
    ["RTC", "phone"],
    ["打印", "printer"],
    ["导入", "arrowIn"],
    ["导出", "arrowOut"],
    ["来源", "tag"],
    ["市场", "tag"],
    ["资源", "clipboard"],
    ["作业", "clipboard"],
    ["任务", "clipboard"],
    ["审查", "check"],
    ["审批", "check"],
    ["测试", "check"],
    ["控制", "shield"],
    ["安全", "shield"],
    ["权限", "shield"],
    ["访问", "shield"],
    ["隐私", "shield"],
    ["集成", "loop"],
    ["IAP", "coin"],
    ["UTM", "chart"],
    ["分享链接", "globe"],
    ["快捷方式", "dashboard"],
    ["精度", "sliders"],
    ["舍入", "sliders"],
    ["销售", "doc"],
    ["采购", "doc"],
    ["订单", "doc"],
    ["应用", "dashboard"],
    ["模块", "dashboard"],
    ["主题", "dashboard"],
    ["参考", "doc"],
    ["文档", "doc"],
    ["说明", "doc"],
    ["页眉", "doc"],
    ["预设回复", "mail"],
    ["群组", "users"],
    ["通话记录", "phone"],
    ["链接", "globe"],
    // generic words last: they must never win over a business name
    ["配置", "gear"],
    ["设置", "gear"],
    ["参数", "gear"],
    ["管理", "gear"],
];

// Optional fallback on the action *type*: the menu tree only exposes
// `actionModel` = "ir.actions.act_window" / "ir.actions.client" / ..., never
// the target model, so a window action carries no model information and falls
// back to the menu's initial.
const ACTION_ICONS = [
    ["ir.actions.report", "chart"],
    ["ir.actions.client", "dashboard"],
    ["ir.actions.act_url", "globe"],
    ["ir.actions.server", "gear"],
];

const letterSvg = (char, color) =>
    markup(
        `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9.2" fill="${color}26" ` +
            `stroke="${color}" stroke-width="1.3"/><text x="12" y="16.2" text-anchor="middle" ` +
            `font-size="11.5" font-weight="600" fill="${color}">${char}</text></svg>`
    );

export class ThemeSidebar extends Component {
    static template = "tb_web_theme.ThemeSidebar";

    setup() {
        this.menu = useService("menu");
        this.state = proxy({
            open: localStorage.getItem(SIDEBAR_STATE_KEY) !== "1",
            activeMenuId: 0,
        });
        this._syncBody();
        useListener(this.env.bus, "MENUS:APP-CHANGED", () => render(this));
        onWillDestroy(() => {
            document.body.classList.remove("tb_has_sidebar", "tb_sidebar_expanded");
        });
    }

    get apps() {
        return this.menu.getApps();
    }

    get currentApp() {
        return this.menu.getCurrentApp();
    }

    /** Sections (2nd level) of the current app — sidebar groups */
    get sections() {
        return this.currentApp
            ? this.menu.getMenuAsTree(this.currentApp.id).childrenTree || []
            : [];
    }

    /** Rows of one card: the section's subtree, flattened with a depth */
    rowsFor(section) {
        const rows = [];
        const walk = (nodes, depth) => {
            for (const node of nodes) {
                const children = node.childrenTree || [];
                if (children.length) {
                    // container menu: not clickable, only names the group below
                    rows.push({ node, depth, kind: "group" });
                    walk(children, depth + 1);
                } else if (node.actionID) {
                    rows.push({ node, depth, kind: "item" });
                }
            }
        };
        if ((section.childrenTree || []).length) {
            walk(section.childrenTree, 0);
        } else if (section.actionID) {
            rows.push({ node: section, depth: 0, kind: "item" });
        }
        return rows;
    }

    letterColor(node) {
        return LETTER_COLORS[node.id % LETTER_COLORS.length];
    }

    letter(node) {
        return (node.name || "?").slice(0, 1).toUpperCase();
    }

    /** Icon (inline svg) for a menu entry: name keyword > action model > initial */
    iconFor(node) {
        const name = node.name || "";
        for (const [keyword, icon] of KEYWORD_ICONS) {
            if (name.includes(keyword)) {
                return SVG_ICONS[icon];
            }
        }
        const actionType = node.actionModel || "";
        for (const [prefix, icon] of ACTION_ICONS) {
            if (actionType.startsWith(prefix)) {
                return SVG_ICONS[icon];
            }
        }
        // last resort: the initial keeps every unmatched entry distinct instead
        // of repeating one generic glyph
        const char = this.letter(node).replace(/[<>&"']/g, "");
        return letterSvg(char, this.letterColor(node));
    }

    onAppClick(app) {
        if (app.actionID) {
            this.menu.selectMenu(app);
        }
    }

    onMenuClick(menu) {
        if (menu.actionID) {
            this.state.activeMenuId = menu.id;
            this.menu.selectMenu(menu);
        }
    }

    toggleSidebar() {
        this.state.open = !this.state.open;
        localStorage.setItem(SIDEBAR_STATE_KEY, this.state.open ? "0" : "1");
        this._syncBody();
    }

    /** Collapsed rail: clicking a section disc expands the sidebar */
    expandSidebar() {
        this.state.open = true;
        localStorage.setItem(SIDEBAR_STATE_KEY, "0");
        this._syncBody();
    }

    _syncBody() {
        // tb_has_sidebar => the rail is present (content shifts by the collapsed width)
        // tb_sidebar_expanded => the rail is fully open (content shifts by the full width)
        document.body.classList.add("tb_has_sidebar");
        document.body.classList.toggle("tb_sidebar_expanded", this.state.open);
    }
}

registry.category("main_components").add("ThemeSidebar", { Component: ThemeSidebar });
