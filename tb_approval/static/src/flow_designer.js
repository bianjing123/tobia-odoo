/** @odoo-module **/

import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// ---------------------------------------------------------------------------
// 节点外观
// ---------------------------------------------------------------------------
const SHAPES = {
    start: { label: "开始", icon: "\uf04b", tone: "#10b981" },
    end: { label: "结束", icon: "\uf11e", tone: "#ef4444" },
};

const KINDS = {
    approval: { label: "审批节点", icon: "\uf007", tone: "#3b82f6" },
    cc: { label: "抄送节点", icon: "\uf003", tone: "#8b5cf6" },
    subflow: { label: "子流程", icon: "\uf0e8", tone: "#0ea5e9" },
};

const MAIN_X = 320;
const DY = 140;
const COL_GAP = 260;

let SEQ = 0;
const nextKey = (p) => (SEQ += 1, p + SEQ);

function flatCard(kind) {
    return {
        kind: "node", key: nextKey("k"), dbId: null, nodeKind: kind,
        name: KINDS[kind].label, approveMode: "or", approvers: [], autoPass: true, ccUsers: [],
    };
}

function defaultTree() {
    return {
        steps: [
            { kind: "node", key: nextKey("k"), dbId: null, shape: "start", name: "开始" },
            { kind: "node", key: nextKey("k"), dbId: null, shape: "end", name: "结束" },
        ],
    };
}

// ---------------------------------------------------------------------------
// design JSON -> 树
// ---------------------------------------------------------------------------
function parseDesign(design) {
    const nodes = (design && design.nodes) || [];
    if (!nodes.length) { return defaultTree(); }
    const byId = {}, out = {}, indeg = {};
    nodes.forEach((n) => { byId[n.id] = n; });
    ((design && design.edges) || []).forEach((e) => {
        (out[e.from] = out[e.from] || []).push(e);
        indeg[e.to] = (indeg[e.to] || 0) + 1;
    });

    const toStep = (n) => {
        if (n.node_type === "start" || n.node_type === "end") {
            return { kind: "node", key: "n" + n.id, dbId: n.id, shape: n.node_type, name: n.name };
        }
        return {
            kind: "node", key: "n" + n.id, dbId: n.id,
            nodeKind: (n.node_type === "cc" || n.node_type === "subflow") ? n.node_type : "approval",
            name: n.name,
            approveMode: n.approve_mode || "or",
            approvers: (n.approver_user_ids || []).slice(),
            autoPass: n.auto_pass_no_approver !== false,
            ccUsers: (n.cc_user_ids || []).slice(),
        };
    };

    const seen = new Set();
    const steps = [];
    let cur = nodes.find((n) => n.node_type === "start") || nodes[0];

    const walkChain = (startId) => {
        const arr = [];
        let id = startId;
        while (id && byId[id] && !seen.has(id)) {
            const n = byId[id];
            if (n.node_type === "parallel_join" || n.node_type === "exclusive_join") { break; }
            if (arr.length && indeg[id] > 1) { break; }
            seen.add(id);
            arr.push(toStep(n));
            const outs = out[id] || [];
            id = outs.length === 1 ? outs[0].to : null;
        }
        return arr;
    };

    let guard = 0;
    while (cur && !seen.has(cur.id) && guard < 500) {
        guard += 1;
        seen.add(cur.id);
        if (cur.node_type === "exclusive_join") {
            const outs = out[cur.id] || [];
            cur = outs.length ? byId[outs[0].to] : null;
            continue;
        }
        const isGw = cur.node_type === "exclusive" || cur.node_type === "parallel_split";
        if (!isGw) {
            steps.push(toStep(cur));
            if (cur.node_type === "end") { break; }
            const outs = out[cur.id] || [];
            cur = outs.length ? byId[outs[0].to] : null;
            continue;
        }
        const outs = out[cur.id] || [];
        const branches = outs.map((e, i) => ({
            key: nextKey("b"),
            name: e.name || "分支" + (i + 1),
            condition: e.condition || "",
            isDefault: !!e.is_default,
            steps: walkChain(e.to),
        }));
        steps.push({
            kind: "branch", key: "g" + cur.id, dbId: cur.id,
            mode: cur.node_type === "exclusive" ? "exclusive" : "parallel",
            branches: branches.length ? branches : [{ key: nextKey("b"), name: "分支1", condition: "", steps: [] }],
        });
        const tails = branches.map((b) => (b.steps.length ? b.steps[b.steps.length - 1].dbId : cur.id));
        let nextId = null;
        tails.forEach((tid) => {
            ((out[tid] || [])).forEach((e) => {
                const hit = tails.filter((x) => (out[x] || []).some((oe) => oe.to === e.to)).length;
                if (hit > 1) { nextId = e.to; }
            });
        });
        cur = nextId ? byId[nextId] : null;
    }

    const last = steps[steps.length - 1];
    if (!(last && last.kind === "node" && last.shape === "end")) {
        steps.push({ kind: "node", key: nextKey("k"), dbId: null, shape: "end", name: "结束" });
    }
    if (!steps.length || steps[0].shape !== "start") {
        steps.unshift({ kind: "node", key: nextKey("k"), dbId: null, shape: "start", name: "开始" });
    }
    return { steps };
}

// ---------------------------------------------------------------------------
// 树 -> design JSON（自动排版 + 并行自动汇聚）
// ---------------------------------------------------------------------------
function compileTree(tree) {
    const nodes = [];
    const edges = [];

    const pushNode = (step, x, y, nodeType, name) => {
        const key = nextKey("c");
        nodes.push({
            key,
            db_id: step.dbId || null,
            name: name || step.name || "",
            node_type: nodeType,
            x: Math.round(x),
            y: Math.round(y),
            approve_mode: step.approveMode || "or",
            approver_user_ids: (step.approvers || []).map((u) => u.id),
            auto_pass_no_approver: step.autoPass !== false,
            cc_user_ids: (step.ccUsers || []).map((u) => u.id),
        });
        return key;
    };
    const link = (from, to, opts) => {
        if (!from || !to) { return; }
        edges.push({
            key: nextKey("x"), db_id: null, from_key: from, to_key: to,
            name: (opts && opts.name) || "",
            condition: (opts && opts.condition) || "",
            is_default: !!(opts && opts.isDefault),
        });
    };

    let y = 120;
    let exits = [];

    tree.steps.forEach((step) => {
        if (step.kind === "node") {
            const type = step.shape === "start" ? "start" : step.shape === "end" ? "end" : (step.nodeKind || "approval");
            const key = pushNode(step, MAIN_X, y, type);
            exits.forEach((k) => link(k, key));
            exits = [key];
            y += DY;
            return;
        }

        const isParallel = step.mode === "parallel";
        const gwKey = pushNode(step, MAIN_X, y,
            isParallel ? "parallel_split" : "exclusive",
            isParallel ? "并行分支" : "条件分支");
        exits.forEach((k) => link(k, gwKey));
        y += DY;

        const count = Math.max(1, step.branches.length);
        const curY = y;
        const branchExits = [];
        let maxEndY = curY;
        step.branches.forEach((b, i) => {
            const x = MAIN_X + (i - (count - 1) / 2) * COL_GAP;
            let prev = null;
            let yy = curY;
            b.steps.forEach((s) => {
                const key = pushNode(s, x, yy, s.nodeKind || "approval");
                if (prev) { link(prev, key); }
                prev = key;
                yy += DY;
            });
            maxEndY = Math.max(maxEndY, yy);
            if (prev) {
                link(gwKey, nodes[nodes.length - b.steps.length].key, {
                    condition: isParallel ? "" : b.condition, isDefault: b.isDefault, name: b.name,
                });
                branchExits.push(prev);
            } else {
                branchExits.push(gwKey);
            }
        });
        y = maxEndY;

        if (isParallel) {
            const joinKey = pushNode(step, MAIN_X, y, "parallel_join", "汇聚");
            branchExits.forEach((k) => link(k, joinKey));
            exits = [joinKey];
            y += DY;
        } else {
            exits = Array.from(new Set(branchExits));
        }
    });

    return { nodes, edges };
}

// ---------------------------------------------------------------------------
// 条件编辑：表单式 -> 表达式
// ---------------------------------------------------------------------------
const OPS = { ">": "大于", ">=": "大于等于", "<": "小于", "<=": "小于等于", "=": "等于", "!=": "不等于" };

function buildExpr(field, op, value, type) {
    if (!field || value === "" || value === null || value === undefined) { return ""; }
    const num = ["integer", "float", "monetary"].indexOf(type) >= 0;
    if (num) {
        return `object.${field} ${op} ${Number(value)}`;
    }
    if (type === "boolean") {
        const truthy = value === "true" || value === true || value === "1";
        return truthy ? `object.${field}` : `not object.${field}`;
    }
    const lit = "'" + String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "'";
    if (op === "contains") { return `${lit} in (object.${field} or '')`; }
    if (op === "starts") { return `(object.${field} or '').startswith(${lit})`; }
    return `object.${field} ${op} ${lit}`;
}

// ---------------------------------------------------------------------------
// 弹窗：节点设置
// ---------------------------------------------------------------------------
class StepDialog extends Component {
    static template = "tb_approval.StepDialog";
    static components = { Dialog };
    props = useProps({
        step: t.object(),
        onChange: t.function(),
        close: t.function(),
    });
    state = proxy({ query: "", results: [] });

    setup() {
        this.orm = useService("orm");
    }

    get step() { return this.props.step; }
    get isApproval() { return this.step.nodeKind === "approval"; }
    get isCc() { return this.step.nodeKind === "cc"; }
    get list() { return this.isCc ? this.step.ccUsers : this.step.approvers; }

    async search(ev) {
        const term = ev.target.value;
        this.state.query = term;
        if (!term) { this.state.results = []; return; }
        this.state.results = await this.orm.searchRead(
            "res.users", [["active", "=", true], ["name", "ilike", term]], ["name"], { limit: 8 });
    }

    addUser(user) {
        if (!this.list.find((u) => u.id === user.id)) { this.list.push({ id: user.id, name: user.name }); }
        this.state.query = "";
        this.state.results = [];
    }

    removeUser(uid) {
        const keep = this.list.filter((u) => u.id !== uid);
        if (this.isCc) { this.step.ccUsers = keep; } else { this.step.approvers = keep; }
    }

    confirm() {
        this.props.onChange();
        this.props.close();
    }
}

// ---------------------------------------------------------------------------
// 弹窗：分支条件
// ---------------------------------------------------------------------------
class ConditionDialog extends Component {
    static template = "tb_approval.ConditionDialog";
    static components = { Dialog };
    props = useProps({
        branch: t.object(),
        flowModel: t.string().optional(""),
        onChange: t.function(),
        close: t.function(),
    });
    state = proxy({ fields: [], field: "", op: ">", value: "" });

    setup() {
        this.orm = useService("orm");
        onWillStart(async () => {
            if (!this.props.flowModel) { return; }
            const all = await this.orm.call(this.props.flowModel, "fields_get", [], {
                attributes: ["string", "type"],
            });
            const allowed = ["char", "text", "integer", "float", "monetary", "date", "boolean", "selection"];
            this.state.fields = Object.entries(all)
                .filter(([, meta]) => allowed.indexOf(meta.type) >= 0)
                .map(([name, meta]) => ({ name, label: meta.string, type: meta.type }))
                .sort((a, b) => a.label.localeCompare(b.label, "zh"));
        });
    }

    get fieldType() {
        const f = this.state.fields.find((x) => x.name === this.state.field);
        return f ? f.type : "char";
    }

    get ops() {
        const ty = this.fieldType;
        if (["integer", "float", "monetary"].indexOf(ty) >= 0) {
            return [">", ">=", "<", "<=", "=", "!="];
        }
        if (ty === "boolean") { return ["="]; }
        return ["=", "!=", "contains", "starts"];
    }

    setField(ev) {
        this.state.field = ev.target.value;
        const ops = this.ops;
        if (ops.indexOf(this.state.op) < 0) { this.state.op = ops[0]; }
    }

    get preview() {
        return buildExpr(this.state.field, this.state.op, this.state.value, this.fieldType);
    }

    confirm() {
        this.props.branch.condition = this.preview;
        this.props.onChange();
        this.props.close();
    }
}

// ---------------------------------------------------------------------------
// 组件基类
// ---------------------------------------------------------------------------
class FlowStepBase extends Component {
    tone(node) {
        const cfg = SHAPES[node.shape] || KINDS[node.nodeKind] || KINDS.approval;
        return cfg.tone;
    }

    icon(node) {
        const cfg = SHAPES[node.shape] || KINDS[node.nodeKind] || KINDS.approval;
        return cfg.icon;
    }

    names(users) { return (users || []).map((u) => u.name).join("、"); }

    get editable() { return false; }

    // 缩放
    zoomBy(delta) {
        const next = Math.round((this.state.zoom + delta) * 10) / 10;
        this.state.zoom = Math.min(1.6, Math.max(0.5, next));
    }

    zoomReset() { this.state.zoom = 1; }

    onWheel(ev) {
        if (!ev.ctrlKey) { return; }
        ev.preventDefault();
        this.zoomBy(ev.deltaY > 0 ? -0.1 : 0.1);
    }

    select() {}
    openCardMenu() {}
    removeStep() {}
    moveStep() {}
    addStep() {}
    addBranchNode() {}
    removeBranch() {}
    addBranch() {}
    openCondition() {}
    setBranchMode() {}
    setBranchName() {}
    save() {}
}

// ---------------------------------------------------------------------------
// 设计器
// ---------------------------------------------------------------------------
export class FlowDesignerField extends FlowStepBase {
    static template = "tb_approval.FlowDesignerField";
    props = useProps({ ...standardFieldProps });
    state = proxy({ steps: [], selected: null, cardMenu: null, saving: false, dirty: false, zoom: 1 });

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        try { this.loadDesign(); } catch (e) { console.error("TB DESIGNER LOAD FAIL", e); }
    }

    get design() {
        const raw = this.props.record.data[this.props.name];
        try { return raw ? JSON.parse(raw) : null; }
        catch (e) { return null; }
    }

    loadDesign() {
        this.state.steps = parseDesign(this.design).steps;
    }

    get editable() { return !!this.props.record.resId; }

    markDirty() { this.state.dirty = true; }

    /** 主链（不含末尾结束节点） */
    get mainSteps() {
        const steps = this.state.steps;
        return steps.length && steps[steps.length - 1].shape === "end"
            ? steps.slice(0, -1)
            : steps;
    }

    get endStep() {
        const steps = this.state.steps;
        const last = steps[steps.length - 1];
        return last && last.shape === "end" ? last : null;
    }

    insert(step) {
        const end = this.endStep;
        const idx = end ? this.state.steps.indexOf(end) : this.state.steps.length;
        this.state.steps.splice(idx, 0, step);
        this.state.dirty = true;
    }

    addStep() {
        const step = flatCard("approval");
        this.insert(step);
        this.state.selected = step;
    }

    addBranchBlock() {
        this.insert({
            kind: "branch", key: nextKey("g"), dbId: null, mode: "exclusive",
            branches: [
                { key: nextKey("b"), name: "条件1", condition: "", isDefault: false, steps: [] },
                { key: nextKey("b"), name: "其他", condition: "", isDefault: true, steps: [] },
            ],
        });
    }

    addBranchColumn(block) {
        block.branches.push({
            key: nextKey("b"),
            name: "分支" + (block.branches.length + 1),
            condition: "", isDefault: false, steps: [],
        });
        this.state.dirty = true;
    }

    addBranchNode(branch) {
        branch.steps.push(flatCard("approval"));
        this.state.dirty = true;
    }

    removeBranch(block, branch) {
        if (block.branches.length <= 1) { return; }
        const i = block.branches.indexOf(branch);
        if (i >= 0) { block.branches.splice(i, 1); }
        this.state.dirty = true;
    }

    async openCondition(branch) {
        let flowModel = "";
        try {
            const [rec] = await this.orm.read("approval.flow", [this.props.record.resId], ["model_name"]);
            flowModel = rec.model_name || "";
        } catch (e) { /* 读不到模型时只允许手写表达式 */ }
        this.dialog.add(ConditionDialog, { branch, flowModel, onChange: () => this.markDirty() });
    }

    setBranchMode(block, mode) {
        block.mode = mode;
        if (mode === "parallel") {
            block.branches.forEach((b) => { b.condition = ""; b.isDefault = false; });
        }
        this.state.dirty = true;
    }

    setBranchName(branch, ev) { branch.name = ev.target.value; this.state.dirty = true; }

    // 卡片交互
    select(step) {
        this.state.cardMenu = null;
        if (!this.editable) { return; }
        this.dialog.add(StepDialog, { step, onChange: () => this.markDirty() });
    }

    openCardMenu(ev, step) {
        ev.stopPropagation();
        this.state.cardMenu = this.state.cardMenu === step.key ? null : step.key;
    }

    removeStep(step) {
        const i = this.state.steps.indexOf(step);
        if (i >= 0) { this.state.steps.splice(i, 1); }
        else {
            this.state.steps.forEach((s) => {
                if (s.kind !== "branch") { return; }
                s.branches.forEach((b) => {
                    const j = b.steps.indexOf(step);
                    if (j >= 0) { b.steps.splice(j, 1); }
                });
            });
        }
        this.state.cardMenu = null;
        this.state.dirty = true;
    }

    moveStep(step, delta) {
        const arr = this.state.steps;
        const i = arr.indexOf(step);
        const j = i + delta;
        this.state.cardMenu = null;
        if (i < 0 || j < 0 || j >= arr.length) { return; }
        arr[i] = arr[j];
        arr[j] = step;
        this.state.dirty = true;
    }

    async save() {
        if (this.state.saving || !this.props.record.resId) { return; }
        this.state.saving = true;
        try {
            await this.orm.call("approval.flow", "save_design",
                [this.props.record.resId, compileTree({ steps: this.state.steps })]);
            this.notification.add("流程已保存", { type: "success" });
            this.state.dirty = false;
        } finally {
            this.state.saving = false;
        }
    }
}

// ---------------------------------------------------------------------------
// 查看器
// ---------------------------------------------------------------------------
export class FlowViewerField extends FlowStepBase {
    static template = "tb_approval.FlowViewerField";
    props = useProps({ ...standardFieldProps });
    state = proxy({ steps: [], zoom: 1 });

    setup() {
        try { this.loadDesign(); } catch (e) { console.error("TB VIEWER LOAD FAIL", e); }
    }

    get design() {
        const raw = this.props.record.data[this.props.name];
        try { return raw ? JSON.parse(raw) : null; }
        catch (e) { return null; }
    }

    loadDesign() {
        const design = this.design;
        const steps = parseDesign(design).steps;
        const stateById = {};
        ((design && design.nodes) || []).forEach((n) => { stateById[n.id] = n.state || "pending"; });
        const apply = (list) => list.forEach((s) => {
            if (s.dbId && stateById[s.dbId]) { s.state = stateById[s.dbId]; }
            if (s.kind === "branch") { s.branches.forEach((b) => apply(b.steps)); }
        });
        apply(steps);
        this.state.steps = steps;
    }
}

registry.category("fields").add("flow_designer", { component: FlowDesignerField });
registry.category("fields").add("flow_viewer", { component: FlowViewerField });
