/** @odoo-module **/

import { Component, onMounted, onWillStart, proxy, signal, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const Core = window.Core;
const LogicFlow = Core?.default || Core;
const TYPES = {
    start: { label: "开始", graph: "tb-start" },
    approval: { label: "人工审批", graph: "tb-card" },
    service: { label: "服务任务", graph: "tb-card" },
    cc: { label: "抄送", graph: "tb-card" },
    subflow: { label: "子流程", graph: "tb-card" },
    exclusive: { label: "排他网关", graph: "tb-gateway" },
    exclusive_join: { label: "排他汇聚", graph: "tb-gateway" },
    parallel_split: { label: "并行网关", graph: "tb-gateway" },
    parallel_join: { label: "并行汇聚", graph: "tb-gateway" },
    end: { label: "结束", graph: "tb-end" },
};

function anchors(model, width, height) {
    return [
        { x: model.x, y: model.y - height / 2, id: `${model.id}_top` },
        { x: model.x - width / 2, y: model.y, id: `${model.id}_left` },
        { x: model.x + width / 2, y: model.y, id: `${model.id}_right` },
        { x: model.x, y: model.y + height / 2, id: `${model.id}_bottom` },
    ];
}

function anchorSide(anchorId) {
    return /_(top|bottom|left|right)$/.exec(anchorId || "")?.[1] || "";
}

function inferredSides(source, target) {
    if (!source || !target) { return { from: "right", to: "left" }; }
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    if (["exclusive", "parallel_split"].includes(source.node_type) && dy > 0 && Math.abs(dx) > 60) {
        return { from: dx < 0 ? "left" : "right", to: "top" };
    }
    if (["exclusive_join", "parallel_join"].includes(target.node_type) && dy > 0 && Math.abs(dx) > 60) {
        return { from: "bottom", to: dx > 0 ? "left" : "right" };
    }
    if (Math.abs(dy) >= Math.abs(dx)) {
        return dy >= 0 ? { from: "bottom", to: "top" } : { from: "top", to: "bottom" };
    }
    return dx >= 0 ? { from: "right", to: "left" } : { from: "left", to: "right" };
}

function graphFromDesign(design) {
    const byId = new Map(design.nodes.map(n => [n.id, n]));
    return {
        nodes: design.nodes.map(n => ({
            id: `n${n.id}`, type: TYPES[n.node_type]?.graph || "tb-card",
            x: n.x ?? 180, y: n.y ?? 160,
            text: n.name, properties: { ...n, db_id: n.id, name: n.name },
        })),
        edges: design.edges.map(e => {
            const inferred = inferredSides(byId.get(e.from), byId.get(e.to));
            return {
                id: `e${e.id}`, type: "tb-edge", sourceNodeId: `n${e.from}`,
                targetNodeId: `n${e.to}`,
                sourceAnchorId: `n${e.from}_${e.from_anchor || inferred.from}`,
                targetAnchorId: `n${e.to}_${e.to_anchor || inferred.to}`,
                text: e.name || e.condition || "",
                properties: { ...e, db_id: e.id },
            };
        }),
    };
}

function positionBranchLabels(lf) {
    for (const edge of lf.graphModel.edges) {
        const source = lf.getNodeModelById(edge.sourceNodeId);
        const target = lf.getNodeModelById(edge.targetNodeId);
        if (!source || !target || !["exclusive", "parallel_split"].includes(source.properties.node_type) || !edge.text?.value) {
            continue;
        }
        const direction = Math.sign(target.x - source.x);
        if (!direction) { continue; }
        const textHalf = [...edge.text.value].reduce((sum, char) => sum + (char.charCodeAt(0) > 255 ? 6 : 4), 0);
        const distance = Math.max(Math.abs(target.x - source.x) / 2, 34 + textHalf + 12);
        edge.moveText(source.x + direction * distance - edge.text.x, source.y - 18 - edge.text.y);
    }
}

function registerShapes(lf) {
    class StartModel extends Core.CircleNodeModel {
        initNodeData(data) { super.initNodeData(data); this.r = 24; }
        getDefaultAnchor() { return anchors(this, 48, 48); }
        getNodeStyle() { return { ...super.getNodeStyle(), fill: "#eaf1ff", stroke: "#526a9d", strokeWidth: 2 }; }
        getTextStyle() { return { ...super.getTextStyle(), color: "#25385e", fontSize: 12 }; }
    }
    class EndModel extends Core.HtmlNodeModel {
        initNodeData(data) { super.initNodeData(data); this.width = 54; this.height = 54; }
        getDefaultAnchor() { return anchors(this, 54, 54); }
    }
    class EndView extends Core.HtmlNode {
        setHtml(rootEl) {
            const ring = document.createElement("div");
            ring.className = "tb-ws-end";
            ring.textContent = this.props.model.text?.value || "结束";
            rootEl.replaceChildren(ring);
        }
    }
    class GatewayModel extends Core.DiamondNodeModel {
        initNodeData(data) { super.initNodeData(data); this.rx = 34; this.ry = 34; }
        getDefaultAnchor() { return anchors(this, 68, 68); }
        getNodeStyle() { return { ...super.getNodeStyle(), fill: "#eefaf5", stroke: "#57a78a", strokeWidth: 2 }; }
        getTextStyle() { return { ...super.getTextStyle(), color: "#2e745a", fontSize: 11 }; }
    }
    class CardModel extends Core.HtmlNodeModel {
        initNodeData(data) { super.initNodeData(data); this.width = 190; this.height = 66; }
        getDefaultAnchor() { return anchors(this, 190, 66); }
    }
    class CardView extends Core.HtmlNode {
        setHtml(rootEl) {
            const model = this.props.model;
            const kind = model.properties.node_type || "approval";
            const card = document.createElement("div");
            card.className = `tb-ws-node tb-ws-node-${kind}`;
            const header = document.createElement("div");
            header.className = "tb-ws-node-head";
            header.textContent = TYPES[kind]?.label || "审批节点";
            const body = document.createElement("div");
            body.className = "tb-ws-node-body";
            body.textContent = model.text?.value || model.properties.name || "未命名节点";
            card.append(header, body);
            rootEl.replaceChildren(card);
        }
    }
    class FlowEdgeModel extends Core.PolylineEdgeModel {
        getEdgeStyle() { return { ...super.getEdgeStyle(), stroke: "#74818b", strokeWidth: 1.8 }; }
        getArrowStyle() { return { ...super.getArrowStyle(), stroke: "#74818b", fill: "#74818b", endArrowType: "solid", offset: 10, verticalLength: 5, refX: 8 }; }
        getTextStyle() { return { ...super.getTextStyle(), color: "#59676f", fontSize: 11 }; }
    }
    lf.register({ type: "tb-start", view: Core.CircleNode, model: StartModel });
    lf.register({ type: "tb-end", view: EndView, model: EndModel });
    lf.register({ type: "tb-gateway", view: Core.DiamondNode, model: GatewayModel });
    lf.register({ type: "tb-card", view: CardView, model: CardModel });
    lf.register({ type: "tb-edge", view: Core.PolylineEdge, model: FlowEdgeModel });
}

export class FlowWorkspace extends Component {
    static template = "tb_approval.FlowWorkspace";
    props = useProps({ ...standardActionServiceProps });
    canvasRef = signal.ref();
    workspaceRef = signal.ref();
    state = proxy({ flow: null, selected: null, dirty: false, saving: false, zoom: 100, users: [], userQuery: "", groups: [], groupQuery: "", subFlows: [], activeTier: -1 });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.flowId = this.props.action.params?.flow_id || this.props.action.context?.active_id;
        onWillStart(async () => {
            const fields = ["name", "model_name", "diagram_data", "active", "version_label", "superseded_by_id"];
            let [flow] = await this.orm.read("approval.flow", [this.flowId], fields);
            while (flow.superseded_by_id) {
                this.flowId = flow.superseded_by_id[0];
                [flow] = await this.orm.read("approval.flow", [this.flowId], fields);
            }
            this.state.flow = flow;
            this.state.subFlows = await this.orm.searchRead("approval.flow", [
                ["model_name", "=", flow.model_name], ["active", "=", true], ["id", "!=", this.flowId],
            ], ["name", "version_label"], { order: "name, id" });
        });
        onMounted(() => this.mountGraph());
    }

    async mountGraph() {
        if (!LogicFlow) { this.notification.add("LogicFlow 资源未加载", { type: "danger" }); return; }
        this.lf = new LogicFlow({
            container: this.canvasRef(), grid: { size: 10, visible: true, type: "dot" },
            edgeType: "tb-edge", isSilentMode: false, stopScrollGraph: false,
            stopZoomGraph: false, autoExpand: true,
        });
        registerShapes(this.lf);
        const design = JSON.parse(this.state.flow.diagram_data || '{"nodes":[],"edges":[]}');
        await this.lf.render(graphFromDesign(design));
        this.positionBranchLabels();
        this.lf.fitView(90, 90);
        this.lf.on("node:click", ({ data }) => this.select("node", data.id));
        this.lf.on("edge:click", ({ data }) => this.select("edge", data.id));
        this.lf.on("blank:click", () => { this.state.selected = null; });
        this.lf.on("node:dragend", () => this.positionBranchLabels());
        this.lf.on("edge:adjust", () => this.positionBranchLabels());
        for (const event of ["node:add", "node:delete", "node:drop", "node:dragend", "edge:add", "edge:delete", "edge:adjust"]) {
            this.lf.on(event, () => { this.state.dirty = true; });
        }
    }

    select(kind, id) {
        const item = kind === "node" ? this.lf.getNodeDataById(id) : this.lf.getEdgeDataById(id);
        const properties = item ? { ...item.properties } : {};
        if (kind === "node") { properties.approver_source = properties.approver_source || (properties.approver_group_id ? "group" : "users"); }
        this.state.selected = item ? { kind, id, name: item.text?.value || item.text || "", properties } : null;
        if (item) { this.workspaceRef()?.focus(); }
    }

    onKeyDown(ev) {
        if (ev.key !== "Delete" && ev.key !== "Backspace") { return; }
        if (!this.state.selected || ev.ctrlKey || ev.altKey || ev.metaKey) { return; }
        const target = ev.target;
        if (target?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName)) { return; }
        ev.preventDefault();
        ev.stopPropagation();
        this.removeSelected();
    }

    dragStart(ev, kind, label) {
        ev.preventDefault();
        const name = label || TYPES[kind].label;
        this.lf.dnd.startDrag({ type: TYPES[kind].graph, text: name,
            properties: { node_type: kind, name, approve_mode: "or", auto_pass_no_approver: true } });
    }

    addNode(kind, label) {
        const graph = this.lf.getGraphData();
        const x = graph.nodes.length ? Math.max(...graph.nodes.map(n => n.x)) + 230 : 180;
        const name = label || TYPES[kind].label;
        this.lf.addNode({ type: TYPES[kind].graph, x, y: 180, text: name,
            properties: { node_type: kind, name, approve_mode: "or", auto_pass_no_approver: true } });
        this.state.dirty = true;
    }

    changeName(ev) {
        const s = this.state.selected;
        s.name = ev.target.value;
        this.lf.updateText(s.id, s.name);
        if (s.kind === "node") { this.lf.setProperties(s.id, { name: s.name }); }
        else { this.lf.setProperties(s.id, { name: s.name }); }
        this.state.dirty = true;
    }

    changeProperty(key, ev) {
        const s = this.state.selected;
        const value = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        s.properties[key] = value;
        this.lf.setProperties(s.id, { [key]: value });
        if (s.kind === "edge" && key === "condition") { this.lf.updateText(s.id, value); }
        this.state.dirty = true;
    }

    setSubFlow(ev) {
        const value = Number(ev.target.value) || false;
        this.state.selected.properties.sub_flow_id = value;
        this.lf.setProperties(this.state.selected.id, { sub_flow_id: value });
        this.state.dirty = true;
    }

    async searchUsers(ev) {
        this.state.userQuery = ev.target.value;
        this.state.users = this.state.userQuery
            ? await this.orm.searchRead("res.users", [["active", "=", true], ["name", "ilike", this.state.userQuery]], ["name"], { limit: 8 }) : [];
    }
    searchTierUsers(ev, index) { this.state.activeTier = index; return this.searchUsers(ev); }

    addUser(user, key) {
        const s = this.state.selected;
        const list = [...(s.properties[key] || [])];
        if (!list.some(u => u.id === user.id)) { list.push(user); }
        s.properties[key] = list;
        this.lf.setProperties(s.id, { [key]: list });
        this.state.userQuery = "";
        this.state.users = [];
        this.state.dirty = true;
    }

    removeUser(id, key) {
        const s = this.state.selected;
        const list = (s.properties[key] || []).filter(u => u.id !== id);
        s.properties[key] = list;
        this.lf.setProperties(s.id, { [key]: list });
        this.state.dirty = true;
    }

    setApproverSource(source) {
        const s = this.state.selected;
        s.properties.approver_source = source;
        this.lf.setProperties(s.id, { approver_source: source });
        this.state.dirty = true;
    }

    updateTiers(tiers) {
        const s = this.state.selected;
        s.properties.amount_tiers = tiers;
        this.lf.setProperties(s.id, { amount_tiers: tiers });
        this.state.dirty = true;
    }
    addTier() { this.updateTiers([...(this.state.selected.properties.amount_tiers || []), { min_amount: 0, users: [] }]); }
    removeTier(index) { this.updateTiers((this.state.selected.properties.amount_tiers || []).filter((_, i) => i !== index)); }
    setTierMin(index, ev) {
        const tiers = (this.state.selected.properties.amount_tiers || []).map((t, i) => i === index ? { ...t, min_amount: Number(ev.target.value) } : t);
        this.updateTiers(tiers);
    }
    addTierUser(index, user) {
        const tiers = (this.state.selected.properties.amount_tiers || []).map((t, i) => i === index
            ? { ...t, users: [...(t.users || []).filter(u => (u.id || u) !== user.id), user] } : t);
        this.updateTiers(tiers);
        this.state.users = [];
        this.state.userQuery = "";
    }
    removeTierUser(index, id) {
        const tiers = (this.state.selected.properties.amount_tiers || []).map((t, i) => i === index
            ? { ...t, users: (t.users || []).filter(u => (u.id || u) !== id) } : t);
        this.updateTiers(tiers);
    }

    async searchGroups(ev) {
        this.state.groupQuery = ev.target.value;
        this.state.groups = this.state.groupQuery
            ? await this.orm.searchRead("res.groups", [["name", "ilike", this.state.groupQuery]], ["name"], { limit: 8 }) : [];
    }

    chooseGroup(group) {
        const s = this.state.selected;
        s.properties.approver_group_id = group.id;
        s.properties.approver_group_name = group.name;
        this.lf.setProperties(s.id, { approver_group_id: group.id, approver_group_name: group.name });
        this.state.groupQuery = "";
        this.state.groups = [];
        this.state.dirty = true;
    }

    removeSelected() {
        const s = this.state.selected;
        if (!s) { return; }
        if (s.kind === "node") { this.lf.deleteNode(s.id); }
        else { this.lf.deleteEdge(s.id); }
        this.state.selected = null;
        this.state.dirty = true;
    }

    zoom(delta) { this.lf.zoom(delta > 0); this.state.zoom = Math.round(this.lf.getTransform().SCALE_X * 100); }
    fit() { this.lf.fitView(90, 90); this.state.zoom = Math.round(this.lf.getTransform().SCALE_X * 100); }
    positionBranchLabels() {
        positionBranchLabels(this.lf);
    }
    arrange() {
        const graph = this.lf.getGraphData();
        if (!graph.nodes.length) { return; }
        const byId = new Map(graph.nodes.map(node => [node.id, node]));
        const outgoing = new Map(graph.nodes.map(node => [node.id, []]));
        const incoming = new Map(graph.nodes.map(node => [node.id, []]));
        const indegree = new Map(graph.nodes.map(node => [node.id, 0]));
        for (const edge of graph.edges) {
            if (!byId.has(edge.sourceNodeId) || !byId.has(edge.targetNodeId)) { continue; }
            outgoing.get(edge.sourceNodeId).push(edge.targetNodeId);
            incoming.get(edge.targetNodeId).push(edge.sourceNodeId);
            indegree.set(edge.targetNodeId, indegree.get(edge.targetNodeId) + 1);
        }
        const depth = new Map(graph.nodes.map(node => [node.id, 0]));
        const queue = graph.nodes.filter(node => !indegree.get(node.id))
            .sort((a, b) => (a.properties.node_type === "start" ? -1 : 0)
                - (b.properties.node_type === "start" ? -1 : 0) || a.x - b.x);
        let visited = 0;
        while (queue.length) {
            const node = queue.shift();
            visited += 1;
            for (const target of outgoing.get(node.id)) {
                depth.set(target, Math.max(depth.get(target), depth.get(node.id) + 1));
                indegree.set(target, indegree.get(target) - 1);
                if (!indegree.get(target)) { queue.push(byId.get(target)); }
            }
        }
        if (visited !== graph.nodes.length) {
            this.notification.add("流程中存在循环连线，无法一键整理", { type: "warning" });
            return;
        }
        const layers = new Map();
        for (const node of graph.nodes) {
            const level = depth.get(node.id);
            if (!layers.has(level)) { layers.set(level, []); }
            layers.get(level).push(node);
        }
        const widest = Math.max(...[...layers.values()].map(layer => layer.length));
        const centerX = Math.max((this.canvasRef()?.clientWidth || 800) / 2, 190 + (widest - 1) * 150);
        const positions = new Map();
        for (const level of [...layers.keys()].sort((a, b) => a - b)) {
            const layer = layers.get(level);
            layer.sort((a, b) => {
                const score = node => {
                    const parents = incoming.get(node.id).filter(id => positions.has(id));
                    return parents.length
                        ? parents.reduce((sum, id) => sum + positions.get(id).x, 0) / parents.length
                        : node.x;
                };
                return score(a) - score(b) || a.x - b.x;
            });
            layer.forEach((node, index) => positions.set(node.id, {
                x: Math.round(centerX + (index - (layer.length - 1) / 2) * 300),
                y: 130 + level * 125,
            }));
        }
        for (const [id, point] of positions) {
            this.lf.graphModel.moveNode2Coordinate(id, point.x, point.y);
        }
        for (const edge of graph.edges) {
            const model = this.lf.getEdgeModelById(edge.id);
            const source = this.lf.getNodeModelById(edge.sourceNodeId);
            const target = this.lf.getNodeModelById(edge.targetNodeId);
            if (!model || !source || !target) { continue; }
            const sides = inferredSides(
                { ...source.properties, x: source.x, y: source.y },
                { ...target.properties, x: target.x, y: target.y });
            const from = source.anchors.find(anchor => anchor.id === `${source.id}_${sides.from}`);
            const to = target.anchors.find(anchor => anchor.id === `${target.id}_${sides.to}`);
            if (from && to) {
                model.sourceAnchorId = from.id;
                model.targetAnchorId = to.id;
                model.updateStartPoint(from);
                model.updateEndPoint(to);
            }
        }
        this.positionBranchLabels();
        this.state.selected = null;
        this.state.dirty = true;
        this.fit();
        if (this.lf.getTransform().SCALE_X > 1) {
            this.lf.zoom(1);
            this.lf.translateCenter();
            this.state.zoom = 100;
        }
    }
    undo() { this.lf.undo(); this.state.selected = null; this.state.dirty = true; }
    redo() { this.lf.redo(); this.state.selected = null; this.state.dirty = true; }
    back() { this.action.doAction({ type: "ir.actions.act_window", res_model: "approval.flow", res_id: this.flowId, views: [[false, "form"]] }); }

    async save() {
        if (this.state.saving) { return; }
        this.state.saving = true;
        try {
            const graph = this.lf.getGraphData();
            const nodes = graph.nodes.map(n => ({
                key: n.id, db_id: n.properties.db_id || false,
                name: n.text?.value || n.text || n.properties.name || TYPES[n.properties.node_type]?.label,
                node_type: n.properties.node_type, x: n.x, y: n.y,
                sequence: n.properties.sequence ?? 10,
                approve_mode: n.properties.approve_mode || "or",
                approver_source: n.properties.approver_source || "users",
                approver_expression: n.properties.approver_expression || "",
                amount_field: n.properties.amount_field || "",
                amount_tiers: n.properties.amount_tiers || [],
                service_method: n.properties.service_method || "",
                approver_user_ids: (n.properties.approver_user_ids || []).map(u => u.id || u),
                approver_group_id: n.properties.approver_group_id || false,
                auto_pass_no_approver: n.properties.auto_pass_no_approver !== false,
                cc_user_ids: (n.properties.cc_user_ids || []).map(u => u.id || u),
                sub_flow_id: n.properties.sub_flow_id || false,
            }));
            const edges = graph.edges.map(e => ({
                key: e.id, db_id: e.properties.db_id || false,
                from_key: e.sourceNodeId, to_key: e.targetNodeId,
                sequence: e.properties.sequence ?? 10,
                name: e.properties.name || "", condition_rule: e.properties.condition_rule || "",
                condition: e.properties.condition || "",
                is_default: !!e.properties.is_default,
                from_anchor: anchorSide(e.sourceAnchorId || this.lf.getEdgeModelById(e.id)?.sourceAnchorId),
                to_anchor: anchorSide(e.targetAnchorId || this.lf.getEdgeModelById(e.id)?.targetAnchorId),
            }));
            this.flowId = await this.orm.call("approval.flow", "save_design", [this.flowId, { nodes, edges }]);
            const [flow] = await this.orm.read("approval.flow", [this.flowId], ["name", "model_name", "diagram_data", "active", "version_label"]);
            this.state.flow = flow;
            const fresh = JSON.parse(flow.diagram_data);
            await this.lf.render(graphFromDesign(fresh));
            this.positionBranchLabels();
            this.state.selected = null;
            this.state.dirty = false;
            this.notification.add(`流程已发布 ${flow.version_label}`, { type: "success" });
        } finally { this.state.saving = false; }
    }
}

export class FlowPreviewField extends Component {
    static template = "tb_approval.FlowPreviewField";
    props = useProps({ ...standardFieldProps });

    get design() {
        const raw = this.props.record.data[this.props.name];
        try { return raw ? JSON.parse(raw) : { nodes: [], edges: [] }; }
        catch { return { nodes: [], edges: [] }; }
    }

    get hasDesign() { return !!this.design.nodes?.length; }

    get layout() {
        const design = this.design;
        const nodes = (design.nodes || []).map(n => ({ ...n, x: Number(n.x) || 0, y: Number(n.y) || 0 }));
        const byId = new Map(nodes.map(n => [n.id, n]));
        const size = n => ["start", "end"].includes(n.node_type)
            ? (n.node_type === "start" ? [48, 48] : [54, 54])
            : ["exclusive", "exclusive_join", "parallel_split", "parallel_join"].includes(n.node_type)
                ? [68, 68] : [190, 66];
        const port = (n, side) => {
            const [width, height] = size(n);
            return { x: n.x + (side === "left" ? -width / 2 : side === "right" ? width / 2 : 0),
                y: n.y + (side === "top" ? -height / 2 : side === "bottom" ? height / 2 : 0) };
        };
        const edges = (design.edges || []).flatMap(e => {
            const source = byId.get(e.from), target = byId.get(e.to);
            if (!source || !target) { return []; }
            const sides = inferredSides(source, target);
            const fromSide = e.from_anchor || sides.from, toSide = e.to_anchor || sides.to;
            const a = port(source, fromSide), b = port(target, toSide);
            let points;
            if (Math.abs(a.x - b.x) < 2 || Math.abs(a.y - b.y) < 2) {
                points = [a, b];
            } else if (["top", "bottom"].includes(fromSide)) {
                points = [a, { x: a.x, y: b.y }, b];
            } else {
                points = [a, { x: b.x, y: a.y }, b];
            }
            const name = e.name || e.condition || "";
            const branch = ["exclusive", "parallel_split"].includes(source.node_type);
            const label = branch && Math.abs(target.x - source.x) > 1
                ? { x: (source.x + target.x) / 2, y: source.y - 17 }
                : { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 9 };
            const state = source.state === "approved" && target.state === "rejected" ? "rejected"
                : source.state === "approved" && target.state === "running" ? "running"
                    : source.state === "approved" && target.state === "approved" ? "approved" : "pending";
            return [{ id: e.id, points: points.map(p => `${p.x},${p.y}`).join(" "), name, label, state }];
        });
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const node of nodes) {
            const [width, height] = size(node);
            minX = Math.min(minX, node.x - width / 2);
            minY = Math.min(minY, node.y - height / 2);
            maxX = Math.max(maxX, node.x + width / 2);
            maxY = Math.max(maxY, node.y + height / 2);
        }
        for (const edge of edges) {
            if (edge.name) {
                minX = Math.min(minX, edge.label.x - edge.name.length * 7);
                maxX = Math.max(maxX, edge.label.x + edge.name.length * 7);
            }
        }
        const pad = 44;
        const width = Math.max(320, maxX - minX + pad * 2);
        const height = Math.max(220, maxY - minY + pad * 2);
        return { nodes, edges, width, height,
            viewBox: `${minX - pad} ${minY - pad} ${width} ${height}` };
    }
}

registry.category("fields").add("flow_preview", { component: FlowPreviewField });
registry.category("actions").add("tb_approval.flow_workspace", FlowWorkspace);
