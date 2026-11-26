/** @odoo-module **/

import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { View } from "@web/views/view";

const TABS = {
    todo: "我的待办",
    done: "我的已办",
    mine: "我发起的",
    all: "全部审批",
};

const NODE_TYPES = {
    approval: "人工审批", service: "服务任务", cc: "抄送",
    subflow: "子流程", exclusive: "排他网关",
    exclusive_join: "排他汇聚", parallel_split: "并行网关",
    parallel_join: "并行汇聚",
};

function nodeSize(node) {
    if (node.node_type === "start") { return [48, 48]; }
    if (node.node_type === "end") { return [54, 54]; }
    if (["exclusive", "exclusive_join", "parallel_split", "parallel_join"].includes(node.node_type)) {
        return [68, 68];
    }
    return [190, 70];
}

function port(node, side) {
    const [width, height] = nodeSize(node);
    return {
        x: node.x + (side === "left" ? -width / 2 : side === "right" ? width / 2 : 0),
        y: node.y + (side === "top" ? -height / 2 : side === "bottom" ? height / 2 : 0),
    };
}

function inferredSides(source, target) {
    const dx = target.x - source.x, dy = target.y - source.y;
    if (Math.abs(dx) > Math.abs(dy) * 1.2) {
        return dx >= 0 ? ["right", "left"] : ["left", "right"];
    }
    return dy >= 0 ? ["bottom", "top"] : ["top", "bottom"];
}

function diagramLayout(design) {
    const nodes = (design?.nodes || []).map(node => ({
        ...node, x: Number(node.x) || 0, y: Number(node.y) || 0,
        state: node.state || "pending",
        typeLabel: NODE_TYPES[node.node_type] || "节点",
    }));
    if (!nodes.length) {
        return { nodes: [], edges: [], viewBox: "0 0 320 220", width: 320, height: 220 };
    }
    const byId = new Map(nodes.map(node => [node.id, node]));
    const edges = (design.edges || []).flatMap(edge => {
        const source = byId.get(edge.from), target = byId.get(edge.to);
        if (!source || !target) { return []; }
        const sides = inferredSides(source, target);
        const fromSide = edge.from_anchor || sides[0], toSide = edge.to_anchor || sides[1];
        const from = port(source, fromSide), to = port(target, toSide);
        let points = [from, to];
        if (Math.abs(from.x - to.x) > 2 && Math.abs(from.y - to.y) > 2) {
            points = [from, ["top", "bottom"].includes(fromSide)
                ? { x: from.x, y: to.y } : { x: to.x, y: from.y }, to];
        }
        const state = source.state === "approved" && target.state === "rejected" ? "rejected"
            : source.state === "approved" && target.state === "running" ? "running"
                : source.state === "approved" && target.state === "approved" ? "approved" : "pending";
        const label = edge.name || edge.label || "";
        return [{
            id: edge.id, state, points: points.map(point => `${point.x},${point.y}`).join(" "),
            vertices: points, name: label,
            labelX: (from.x + to.x) / 2,
            labelY: ["exclusive", "parallel_split"].includes(source.node_type)
                ? source.y - 15 : (from.y + to.y) / 2 - 9,
        }];
    });
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const node of nodes) {
        const [width, height] = nodeSize(node);
        minX = Math.min(minX, node.x - width / 2);
        minY = Math.min(minY, node.y - height / 2);
        maxX = Math.max(maxX, node.x + width / 2);
        maxY = Math.max(maxY, node.y + height / 2);
    }
    for (const edge of edges) {
        for (const point of edge.vertices) {
            minX = Math.min(minX, point.x); maxX = Math.max(maxX, point.x);
            minY = Math.min(minY, point.y); maxY = Math.max(maxY, point.y);
        }
        if (edge.name) {
            minX = Math.min(minX, edge.labelX - edge.name.length * 7);
            maxX = Math.max(maxX, edge.labelX + edge.name.length * 7);
            minY = Math.min(minY, edge.labelY - 15);
        }
    }
    const pad = 42;
    return {
        nodes, edges,
        width: Math.max(320, maxX - minX + pad * 2),
        height: Math.max(220, maxY - minY + pad * 2),
        viewBox: `${minX - pad} ${minY - pad} ${Math.max(320, maxX - minX + pad * 2)} ${Math.max(220, maxY - minY + pad * 2)}`,
    };
}

export class ApprovalCenter extends Component {
    static template = "tb_approval.ApprovalCenter";
    static components = { View };
    props = useProps({ ...standardActionServiceProps });
    state = proxy({
        tab: "todo", rows: [], hasMore: false,
        selectedId: null, selectedTaskId: null, detail: null,
        loading: false, detailLoading: false, busy: false, comment: "",
    });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.documentViewProps = null;
        this.state.tab = TABS[this.props.action.params?.tab] ? this.props.action.params.tab : "todo";
        this.detailRequest = 0;
        this.listRequest = 0;
        onWillStart(() => this.load(true));
    }

    get title() { return TABS[this.state.tab]; }
    get layout() { return diagramLayout(this.state.detail?.diagram); }

    statusLabel(value) {
        return ({ pending: "待审批", running: "审批中", approved: "已通过",
            rejected: "已驳回", cancelled: "已取消" })[value] || value || "";
    }

    async load(reset = false) {
        if (this.state.loading && !reset) { return; }
        const request = ++this.listRequest;
        const tab = this.state.tab;
        this.state.loading = true;
        if (reset) {
            this.detailRequest++;
            this.state.rows = [];
            this.state.hasMore = false;
            this.state.detail = null;
            this.documentViewProps = null;
            this.state.detailLoading = false;
            this.state.selectedId = null;
            this.state.selectedTaskId = null;
            this.state.comment = "";
        }
        try {
            const result = await this.orm.call("approval.instance", "get_center_rows",
                [tab, this.state.rows.length, 40]);
            if (request !== this.listRequest) { return; }
            this.state.rows = [...this.state.rows, ...result.rows];
            this.state.hasMore = result.has_more;
            if (reset && this.state.rows.length) { await this.select(this.state.rows[0]); }
        } catch (error) {
            if (request === this.listRequest) {
                this.notification.add(error.message || "审批列表加载失败", { type: "danger" });
            }
        } finally {
            if (request === this.listRequest) { this.state.loading = false; }
        }
    }

    async select(row) {
        const request = ++this.detailRequest;
        this.state.selectedId = row.id;
        this.state.selectedTaskId = row.task_id;
        this.state.detail = null;
        this.documentViewProps = null;
        this.state.detailLoading = true;
        try {
            const detail = await this.orm.call("approval.instance", "get_center_detail", [row.instance_id]);
            if (request !== this.detailRequest) { return; }
            if (detail.document.available) {
                this.documentViewProps = {
                    type: "form",
                    resModel: detail.document.model,
                    resId: detail.document.res_id,
                    viewId: false,
                    context: {},
                    display: { controlPanel: false },
                    readonly: true,
                    preventCreate: true,
                    preventEdit: true,
                };
            }
            this.state.detail = detail;
            this.state.comment = detail.tasks.find(task => task.id === row.task_id)?.comment || "";
        } catch (error) {
            if (request === this.detailRequest) {
                this.notification.add(error.message || "审批详情加载失败", { type: "danger" });
            }
        } finally {
            if (request === this.detailRequest) { this.state.detailLoading = false; }
        }
    }

    openDocument() {
        const document = this.state.detail?.document;
        if (!document?.available) { return; }
        this.action.doAction({
            type: "ir.actions.act_window", res_model: document.model,
            res_id: document.res_id, views: [[false, "form"]], target: "current",
        });
    }

    openInstance() {
        if (!this.state.detail) { return; }
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "approval.instance",
            res_id: this.state.detail.instance_id, views: [[false, "form"]], target: "current",
        });
    }

    async decide(method) {
        if (!this.state.selectedTaskId || this.state.busy) { return; }
        this.state.busy = true;
        try {
            const decision = method === "action_approve" ? "approve" : "reject";
            await this.orm.call("approval.task", "action_center_decide",
                [[this.state.selectedTaskId], decision, this.state.comment]);
            this.notification.add(method === "action_approve" ? "已通过审批" : "已驳回审批",
                { type: "success" });
            await this.load(true);
        } catch (error) {
            const detail = error.data?.message?.trim()
                || error.data?.debug?.trim().split("\n").at(-1)
                || error.message
                || "审批操作失败";
            this.notification.add(detail, { type: "danger", title: "审批操作失败", sticky: true });
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("actions").add("tb_approval.center", ApprovalCenter);
