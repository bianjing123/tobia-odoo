# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval


class ApprovalFlow(models.Model):
    _name = 'approval.flow'
    _description = '审批流程定义'
    _inherit = ['mail.thread']
    _order = 'model_id, name'

    name = fields.Char(required=True, tracking=True)
    model_id = fields.Many2one(
        'ir.model', string='审批单据模型', required=True, ondelete='cascade',
        domain=[('transient', '=', False)])
    model_name = fields.Char(related='model_id.model', store=True)
    active = fields.Boolean(default=True)
    version_number = fields.Integer(string='版本号', default=1, required=True, copy=False)
    version_label = fields.Char(string='流程版本', compute='_compute_version_label')
    root_flow_id = fields.Many2one('approval.flow', string='初始版本', copy=False, ondelete='restrict')
    superseded_by_id = fields.Many2one('approval.flow', string='后续版本', copy=False, ondelete='restrict')
    note = fields.Html()
    node_ids = fields.One2many('approval.node', 'flow_id', string='节点')
    transition_ids = fields.One2many('approval.transition', 'flow_id', string='连线')
    instance_ids = fields.One2many('approval.instance', 'flow_id', string='审批实例')
    instance_count = fields.Integer(compute='_compute_instance_count')
    diagram_data = fields.Char(compute='_compute_diagram_data')

    @api.depends('version_number')
    def _compute_version_label(self):
        for flow in self:
            flow.version_label = 'V%s.0' % flow.version_number

    def write(self, vals):
        if {'version_number', 'root_flow_id', 'superseded_by_id'}.intersection(vals) and not self.env.context.get('_approval_publishing'):
            raise UserError('流程版本号和版本关系只能由发布操作更新。')
        protected = {'name', 'model_id', 'note', 'node_ids', 'transition_ids'}
        if protected.intersection(vals) and any(flow.instance_ids or flow.superseded_by_id for flow in self):
            raise UserError('已有审批实例或历史版本的流程定义不能直接修改，请在设计器中发布新版本。')
        if 'active' in vals and any(flow.superseded_by_id and vals['active'] for flow in self):
            raise UserError('历史流程版本不能重新启用。')
        return super().write(vals)

    def unlink(self):
        if any(flow.instance_ids or flow.superseded_by_id or flow.root_flow_id
               for flow in self):
            raise UserError('流程版本已有审批历史或版本关联，不能删除。')
        return super().unlink()

    def _compute_instance_count(self):
        groups = self.env['approval.instance']._read_group(
            [('flow_id', 'in', self.ids)], ['flow_id'], ['__count'])
        counts = {flow.id: count for flow, count in groups}
        for flow in self:
            flow.instance_count = counts.get(flow.id, 0)

    @api.depends('node_ids.name', 'node_ids.node_type', 'node_ids.x', 'node_ids.y',
                 'node_ids.approve_mode', 'node_ids.approver_source',
                 'node_ids.approver_user_ids', 'node_ids.approver_group_id',
                 'node_ids.auto_pass_no_approver', 'node_ids.approver_expression',
                 'node_ids.amount_field', 'node_ids.amount_tiers',
                 'node_ids.service_method', 'node_ids.sub_flow_id', 'node_ids.cc_user_ids',
                 'transition_ids.from_node_id', 'transition_ids.to_node_id',
                 'transition_ids.condition', 'transition_ids.is_default',
                 'transition_ids.from_anchor', 'transition_ids.to_anchor')
    def _compute_diagram_data(self):
        for flow in self:
            flow.diagram_data = json.dumps(flow._export_design(), ensure_ascii=False)

    def _export_design(self):
        """导出为设计器/查看器 JSON（坐标取节点上保存的画布坐标，缺失则自动布局）。"""
        self.ensure_one()
        # onchange 阶段 node.id 可能是 NewId，取 _origin.id 的真实 id
        nodes = [{
            'id': n._origin.id or 0, 'name': n.name, 'node_type': n.node_type,
            'sequence': n.sequence,
            'x': n.x, 'y': n.y,
            'approve_mode': n.approve_mode,
            'approver_user_ids': [
                {'id': u.id, 'name': u.name} for u in n.approver_user_ids],
            'approver_group_id': n.approver_group_id.id,
            'approver_group_name': n.approver_group_id.display_name or '',
            'approver_source': 'group' if n.approver_source == 'users' and n.approver_group_id and not n.approver_user_ids else n.approver_source,
            'approver_expression': n.approver_expression or '',
            'amount_field': n.amount_field or '',
            'amount_tiers': n.amount_tiers or [],
            'service_method': n.service_method or '',
            'auto_pass_no_approver': n.auto_pass_no_approver,
            'sub_flow_id': n.sub_flow_id.id,
            'cc_user_ids': [{'id': u.id, 'name': u.name} for u in n.cc_user_ids],
        } for n in self.node_ids]
        edges = [{
            'id': t._origin.id or 0,
            'sequence': t.sequence,
            'from': t.from_node_id._origin.id or 0,
            'to': t.to_node_id._origin.id or 0,
            'from_anchor': t.from_anchor or '',
            'to_anchor': t.to_anchor or '',
            'name': t.name or '',
            'condition_rule': t.condition_rule or '',
            'condition': t.condition or '', 'is_default': t.is_default,
        } for t in self.transition_ids]
        _fallback_layout(nodes, edges)
        return {'nodes': nodes, 'edges': edges}

    def save_design(self, data):
        """保存 LogicFlow 设计器画布。

        data: {'nodes': [{'key', 'db_id', 'name', 'node_type', 'x', 'y'}],
               'edges': [{'db_id', 'from_key', 'to_key', 'condition', 'is_default'}]}
        key 为前端节点标识，用于把边关联到新建节点。
        """
        self.ensure_one()
        _validate_design_graph(data)
        for vals in data.get('nodes', []):
            if vals.get('node_type') != 'subflow':
                continue
            child_id = vals.get('sub_flow_id')
            if not child_id:
                raise UserError('子流程节点「%s」未选择子流程。' % (vals.get('name') or '未命名'))
            child = self.browse(child_id).exists()
            if not child or child == self or child.model_id != self.model_id:
                raise UserError('子流程必须是相同单据模型的其他审批流程。')
        # 同一流程的并发发布必须串行，避免产生两个 V2.0。
        self.env.cr.execute('SELECT id FROM approval_flow WHERE id = %s FOR UPDATE', (self.id,))
        self.invalidate_recordset(['superseded_by_id', 'node_ids'])
        if self.superseded_by_id:
            raise UserError('当前为历史流程版本，请打开最新版本后修改。')
        if self.node_ids:
            return self._publish_new_version(data)
        node_map = {}  # key -> node record
        for vals in data.get('nodes', []):
            node_vals = {
                'name': vals.get('name') or '未命名',
                'node_type': vals.get('node_type') or 'approval',
                'sequence': vals.get('sequence', 10),
                'x': vals.get('x') or 0.0,
                'y': vals.get('y') or 0.0,
            }
            if node_vals['node_type'] == 'approval':
                node_vals.update({
                    'approve_mode': vals.get('approve_mode') or 'or',
                    'approver_user_ids': [(6, 0, vals.get('approver_user_ids') or [])],
                    'approver_group_id': vals.get('approver_group_id') or False,
                    'approver_source': vals.get('approver_source') or 'users',
                    'approver_expression': vals.get('approver_expression') or '',
                    'amount_field': vals.get('amount_field') or '',
                    'amount_tiers': vals.get('amount_tiers') or [],
                    'auto_pass_no_approver': vals.get('auto_pass_no_approver') is not False,
                })
            if node_vals['node_type'] == 'subflow':
                node_vals['sub_flow_id'] = vals.get('sub_flow_id') or False
            if node_vals['node_type'] == 'service':
                node_vals['service_method'] = vals.get('service_method') or ''
            if node_vals['node_type'] == 'cc':
                node_vals['cc_user_ids'] = [(6, 0, vals.get('cc_user_ids') or [])]
            db_id = vals.get('db_id')
            if db_id:
                node = self.env['approval.node'].browse(db_id)
                if node.flow_id != self:
                    raise UserError('节点数据异常（不属于当前流程）。')
                node.write(node_vals)
            else:
                node = self.env['approval.node'].create(dict(node_vals, flow_id=self.id))
            node_map[vals['key']] = node

        edge_map = {}
        for vals in data.get('edges', []):
            from_node = node_map.get(vals.get('from_key'))
            to_node = node_map.get(vals.get('to_key'))
            if not from_node or not to_node:
                raise UserError('连线两端存在未知节点，请重试。')
            edge_vals = {
                'from_node_id': from_node.id,
                'to_node_id': to_node.id,
                'sequence': vals.get('sequence', 10),
                'name': vals.get('name') or '',
                'condition_rule': vals.get('condition_rule') or '',
                'condition': vals.get('condition') or '',
                'is_default': bool(vals.get('is_default')),
                'from_anchor': vals.get('from_anchor') or False,
                'to_anchor': vals.get('to_anchor') or False,
            }
            db_id = vals.get('db_id')
            if db_id:
                trans = self.env['approval.transition'].browse(db_id)
                if trans.flow_id != self:
                    raise UserError('连线数据异常（不属于当前流程）。')
                trans.write(edge_vals)
            else:
                trans = self.env['approval.transition'].create(dict(edge_vals, flow_id=self.id))
            edge_map[vals.get('key') or trans.id] = trans

        # 删除画布上已移除的元素（有审批历史的节点会被数据库约束拦住）
        node_ids = {n.id for n in node_map.values()}
        for node in self.node_ids:
            if node.id not in node_ids:
                try:
                    node.unlink()
                except Exception:
                    raise UserError('节点「%s」已有审批历史，不能删除。' % node.name)
        edge_ids = {t.id for t in edge_map.values()}
        for trans in self.transition_ids:
            if trans.id not in edge_ids:
                trans.unlink()
        return self.id

    def _publish_new_version(self, data):
        """以新记录发布，旧节点和连线继续供已有实例执行。"""
        self.ensure_one()
        values = {
            'name': self.name, 'model_id': self.model_id.id, 'note': self.note,
            'active': self.active, 'version_number': self.version_number + 1,
            'root_flow_id': (self.root_flow_id or self).id,
        }
        new_flow = self.create(values)
        fresh_data = {
            'nodes': [dict(node, db_id=False) for node in data.get('nodes', [])],
            'edges': [dict(edge, db_id=False) for edge in data.get('edges', [])],
        }
        new_flow.save_design(fresh_data)
        self.with_context(_approval_publishing=True).write({
            'active': False, 'superseded_by_id': new_flow.id,
        })
        return new_flow.id

    def action_view_instances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '审批实例',
            'res_model': 'approval.instance',
            'view_mode': 'list,form',
            'domain': [('flow_id', '=', self.id)],
            'context': {'default_flow_id': self.id},
        }

    def action_view_versions(self):
        self.ensure_one()
        root = self.root_flow_id or self
        return {
            'type': 'ir.actions.act_window',
            'name': '流程版本',
            'res_model': 'approval.flow',
            'view_mode': 'list,form',
            'domain': ['|', ('id', '=', root.id), ('root_flow_id', '=', root.id)],
            'context': {'active_test': False},
        }

    def action_open_designer(self):
        self.ensure_one()
        flow = self
        while flow.superseded_by_id:
            flow = flow.superseded_by_id
        return {
            'type': 'ir.actions.client',
            'tag': 'tb_approval.flow_workspace',
            'params': {'flow_id': flow.id},
        }

    @api.constrains('node_ids')
    def _check_start_end_nodes(self):
        for flow in self:
            if not flow.node_ids:
                continue  # 空流程允许保存（画图前先建流程头）
            starts = flow.node_ids.filtered(lambda n: n.node_type == 'start')
            ends = flow.node_ids.filtered(lambda n: n.node_type == 'end')
            if len(starts) != 1:
                raise ValidationError('每个流程必须有且只有一个「开始」节点。')
            if not ends:
                raise ValidationError('每个流程必须至少有一个「结束」节点。')


class ApprovalNode(models.Model):
    _name = 'approval.node'
    _description = '审批流程节点'
    _order = 'flow_id, sequence, id'

    @api.model_create_multi
    def create(self, vals_list):
        flow_ids = [vals.get('flow_id') for vals in vals_list if vals.get('flow_id')]
        if any(flow.instance_ids or flow.superseded_by_id
               for flow in self.env['approval.flow'].browse(flow_ids)):
            raise UserError('已有审批实例的流程节点不能直接修改，请发布新版本。')
        return super().create(vals_list)

    def write(self, vals):
        if any(node.flow_id.instance_ids or node.flow_id.superseded_by_id for node in self):
            raise UserError('已有审批实例的流程节点不能直接修改，请发布新版本。')
        return super().write(vals)

    def unlink(self):
        if any(node.flow_id.instance_ids or node.flow_id.superseded_by_id for node in self):
            raise UserError('已有审批实例的流程节点不能删除，请发布新版本。')
        return super().unlink()

    flow_id = fields.Many2one('approval.flow', required=True, ondelete='cascade', index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    node_type = fields.Selection([
        ('start', '开始'),
        ('approval', '审批节点'),
        ('service', '服务任务'),
        ('cc', '抄送节点'),
        ('exclusive', '排他网关'),
        ('exclusive_join', '排他汇聚'),
        ('parallel_split', '并行分支'),
        ('parallel_join', '并行汇聚'),
        ('subflow', '子流程'),
        ('end', '结束'),
    ], required=True, default='approval')
    # 画布坐标（LogicFlow 节点中心点）
    x = fields.Float(default=300)
    y = fields.Float(default=200)

    # ---- 审批节点配置 ----
    approve_mode = fields.Selection([
        ('or', '或签（一人通过即过）'),
        ('and', '会签（全部通过才过）'),
    ], default='or', required=True)
    approver_user_ids = fields.Many2many('res.users', string='指定审批人')
    approver_group_id = fields.Many2one('res.groups', string='审批组')
    approver_source = fields.Selection([
        ('users', '指定用户'), ('group', '用户组'),
        ('manager', '直属上级'), ('department', '部门主管'),
        ('expression', '动态表达式'), ('amount', '金额分级'),
    ], default='users', required=True)
    approver_expression = fields.Char('审批人表达式')
    amount_field = fields.Char('金额字段')
    amount_tiers = fields.Json('金额分级规则', default=list)
    service_method = fields.Char('服务方法', help='目标单据上可调用的无参方法名称。')
    auto_pass_no_approver = fields.Boolean(
        '无审批人时自动通过', default=True,
        help='审批节点没有任何审批人时自动通过；不勾选则提交时报错。')

    # ---- 子流程 ----
    sub_flow_id = fields.Many2one(
        'approval.flow', string='子流程',
        domain="[('id', '!=', flow_id)]",
        help='子流程审批通过后，本节点继续向下流转。')

    # ---- 抄送 ----
    cc_user_ids = fields.Many2many(
        'res.users', 'approval_node_cc_user_rel', string='抄送人')

    out_transition_ids = fields.One2many(
        'approval.transition', 'from_node_id', string='出线')
    in_transition_ids = fields.One2many(
        'approval.transition', 'to_node_id', string='入线')

    def _get_approvers(self, record=None, initiator=None):
        self.ensure_one()
        users = self.env['res.users']
        source = self.approver_source
        if source == 'users':
            users = self.approver_user_ids
            if not users and self.approver_group_id:
                users = self.approver_group_id.all_user_ids
        elif source == 'group' and self.approver_group_id:
            users = self.approver_group_id.all_user_ids
        elif source in ('manager', 'department'):
            if not initiator:
                raise UserError('节点「%s」缺少发起人，无法确定上级。' % self.name)
            employee = self.env['hr.employee.public'].search([('user_id', '=', initiator.id)], limit=1)
            manager = employee.parent_id if source == 'manager' else self.env['hr.employee.public'].browse(
                employee.department_id.manager_id.id)
            users = users.browse(manager.user_id.id) if manager and manager.user_id else users
        elif source == 'expression':
            if not self.approver_expression or not record:
                raise UserError('节点「%s」未配置动态审批人表达式。' % self.name)
            try:
                result = safe_eval(self.approver_expression,
                                   {'object': record, 'initiator': initiator}, mode='eval')
            except Exception as exc:
                raise UserError('节点「%s」的审批人表达式执行失败：%s' % (self.name, exc)) from exc
            if getattr(result, '_name', None) == 'res.users':
                users = result
            elif isinstance(result, int):
                users = users.browse(result)
            elif isinstance(result, (list, tuple)) and all(isinstance(uid, int) for uid in result):
                users = users.browse(result)
            else:
                raise UserError('动态审批人表达式必须返回用户记录、用户 ID 或 ID 列表。')
        elif source == 'amount':
            if not record or not self.amount_field or self.amount_field not in record._fields:
                raise UserError('节点「%s」的金额字段无效。' % self.name)
            amount = float(record[self.amount_field] or 0)
            tiers = sorted(self.amount_tiers or [], key=lambda rule: float(rule.get('min_amount') or 0))
            eligible = [rule for rule in tiers if amount >= float(rule.get('min_amount') or 0)]
            if eligible:
                ids = [u.get('id') if isinstance(u, dict) else u for u in eligible[-1].get('users', [])]
                users = users.browse([uid for uid in ids if isinstance(uid, int)])
        return users.filtered(lambda u: u.active)

    def _get_cc_users(self):
        self.ensure_one()
        return self.cc_user_ids.filtered(lambda u: u.active)


class ApprovalTransition(models.Model):
    _name = 'approval.transition'
    _description = '审批流程连线'
    _order = 'from_node_id, sequence, id'

    @api.model_create_multi
    def create(self, vals_list):
        flow_ids = [vals.get('flow_id') for vals in vals_list if vals.get('flow_id')]
        if any(flow.instance_ids or flow.superseded_by_id
               for flow in self.env['approval.flow'].browse(flow_ids)):
            raise UserError('已有审批实例的流程连线不能直接修改，请发布新版本。')
        return super().create(vals_list)

    def write(self, vals):
        if any(edge.flow_id.instance_ids or edge.flow_id.superseded_by_id for edge in self):
            raise UserError('已有审批实例的流程连线不能直接修改，请发布新版本。')
        return super().write(vals)

    def unlink(self):
        if any(edge.flow_id.instance_ids or edge.flow_id.superseded_by_id for edge in self):
            raise UserError('已有审批实例的流程连线不能删除，请发布新版本。')
        return super().unlink()

    flow_id = fields.Many2one('approval.flow', required=True, ondelete='cascade', index=True)
    from_node_id = fields.Many2one('approval.node', string='来源节点', required=True, ondelete='cascade')
    to_node_id = fields.Many2one('approval.node', string='目标节点', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10, string='优先级')
    name = fields.Char(
        '连线名称',
        help='画布连线上显示的标签；为空时显示编译后的条件表达式。')
    condition_rule = fields.Text(
        '条件规则 JSON',
        help='规则化条件配置（字段/操作符/值），前端设计器编辑；condition 为其编译结果。')
    condition = fields.Char(
        string='条件',
        help='Python 表达式，object 为单据记录，如 object.amount_total > 50000。'
             '留空表示无条件通过。排他网关按优先级取第一条满足的出线，'
             '全部不满足时走「兜底分支」。')
    is_default = fields.Boolean('兜底分支')
    from_anchor = fields.Selection([
        ('top', '上'), ('bottom', '下'), ('left', '左'), ('right', '右'),
    ], string='起点连接方向')
    to_anchor = fields.Selection([
        ('top', '上'), ('bottom', '下'), ('left', '左'), ('right', '右'),
    ], string='终点连接方向')

    def _condition_ok(self, record):
        self.ensure_one()
        if not self.condition:
            return True
        try:
            return bool(safe_eval(self.condition, {'object': record}, mode='eval'))
        except Exception as exc:
            raise UserError('连线「%s」的条件无法计算：%s' % (self.name or self.id, exc)) from exc

    @api.constrains('from_node_id', 'to_node_id')
    def _check_same_flow(self):
        for trans in self:
            if trans.from_node_id.flow_id != trans.flow_id or trans.to_node_id.flow_id != trans.flow_id:
                raise ValidationError('连线的两端节点必须属于同一个流程。')


def _validate_design_graph(data):
    """在发布前检查画布拓扑，避免无法流转的定义进入生产。"""
    nodes = data.get('nodes') or []
    edges = data.get('edges') or []
    by_key = {}
    for node in nodes:
        key = node.get('key')
        if not key or key in by_key:
            raise ValidationError('流程节点标识缺失或重复。')
        by_key[key] = node
    starts = [key for key, node in by_key.items() if node.get('node_type') == 'start']
    ends = [key for key, node in by_key.items() if node.get('node_type') == 'end']
    if len(starts) != 1 or not ends:
        raise ValidationError('流程必须有且只有一个开始节点，并至少有一个结束节点。')

    outgoing = {key: [] for key in by_key}
    outgoing_edges = {key: [] for key in by_key}
    incoming = {key: [] for key in by_key}
    for edge in edges:
        source, target = edge.get('from_key'), edge.get('to_key')
        if source not in by_key or target not in by_key:
            raise ValidationError('连线两端必须是画布中的节点。')
        if source == target:
            raise ValidationError('节点不能连接到自身。')
        if (by_key[source].get('node_type') == 'parallel_split'
                and (edge.get('condition') or edge.get('condition_rule') or edge.get('is_default'))):
            raise ValidationError('并行分支的出线不能设置条件或兜底，否则汇聚可能无法到齐。')
        outgoing[source].append(target)
        outgoing_edges[source].append(edge)
        incoming[target].append(source)

    for key, node in by_key.items():
        kind = node.get('node_type')
        name = node.get('name') or '未命名'
        if kind == 'start' and incoming[key]:
            raise ValidationError('开始节点不能有入线。')
        if kind == 'end' and outgoing[key]:
            raise ValidationError('结束节点不能有出线。')
        if kind != 'start' and not incoming[key]:
            raise ValidationError('节点「%s」没有入线。' % name)
        if kind != 'end' and not outgoing[key]:
            raise ValidationError('节点「%s」没有出线。' % name)
        if kind in ('exclusive', 'parallel_split') and len(outgoing[key]) < 2:
            raise ValidationError('分支节点「%s」至少需要两条出线。' % name)
        if kind in ('exclusive_join', 'parallel_join'):
            if len(incoming[key]) < 2 or len(outgoing[key]) != 1:
                raise ValidationError('汇聚节点「%s」至少需要两条入线和一条出线。' % name)

    def reachable(seeds, links):
        seen = set(seeds)
        pending = list(seeds)
        while pending:
            for next_key in links[pending.pop()]:
                if next_key not in seen:
                    seen.add(next_key)
                    pending.append(next_key)
        return seen

    from_start = reachable(starts, outgoing)
    to_end = reachable(ends, incoming)
    if len(from_start) != len(by_key) or len(to_end) != len(by_key):
        raise ValidationError('流程存在不可达节点或无法到达结束节点的分支。')

    degree = {key: len(incoming[key]) for key in by_key}
    pending = [key for key, count in degree.items() if not count]
    visited = 0
    while pending:
        visited += 1
        for target in outgoing[pending.pop()]:
            degree[target] -= 1
            if not degree[target]:
                pending.append(target)
    if visited != len(by_key):
        raise ValidationError('流程存在环路，当前审批引擎不支持循环流转。')

    def upstream_splits(start_key):
        """排他分支不能作为并行汇聚等待的来源。"""
        found, seen, pending = set(), set(), [start_key]
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            kind = by_key[key].get('node_type')
            if kind in ('exclusive', 'exclusive_join'):
                continue
            if kind == 'parallel_split':
                found.add(key)
            pending.extend(incoming[key])
        return found

    def all_split_paths_reach_join(split_key, join_key):
        """分支的每条路径都要到该汇聚，且中途不能被条件跳过。"""
        seen, pending = set(), list(outgoing[split_key])
        while pending:
            key = pending.pop()
            if key == join_key or key in seen:
                continue
            seen.add(key)
            if by_key[key].get('node_type') in ('exclusive', 'exclusive_join'):
                return False
            links = outgoing_edges[key]
            if not links or any(edge.get('condition') or edge.get('condition_rule')
                                or edge.get('is_default') for edge in links):
                return False
            pending.extend(edge['to_key'] for edge in links)
        return True

    for key, node in by_key.items():
        if node.get('node_type') != 'parallel_join':
            continue
        common = None
        for source in incoming[key]:
            candidates = upstream_splits(source)
            common = candidates if common is None else common & candidates
        if not common or not any(all_split_paths_reach_join(split, key)
                                 for split in common):
            raise ValidationError('并行汇聚节点「%s」的入线必须来自同一个并行分支，且所有分支路径都要到达此汇聚。' %
                                  (node.get('name') or '未命名'))


def _fallback_layout(nodes, edges):
    """坐标全为 0 时用 BFS 分层自动布局。"""
    if not nodes:
        return
    if any(n.get('x') or n.get('y') for n in nodes):
        return
    out_map = {}
    in_deg = {}
    for e in edges:
        out_map.setdefault(e['from'], []).append(e)
        in_deg[e['to']] = in_deg.get(e['to'], 0) + 1
    frontier = [n['id'] for n in nodes if not in_deg.get(n['id'])] or [nodes[0]['id']]
    depth = {nid: 0 for nid in frontier}
    while frontier:
        nid = frontier.pop(0)
        for e in out_map.get(nid, []):
            depth[e['to']] = max(depth.get(e['to'], 0), depth[nid] + 1)
            if e['to'] not in depth:
                frontier.append(e['to'])
    max_depth = max(depth.values(), default=0)
    for n in nodes:
        d = depth.get(n['id'], max_depth + 1)
        n['x'] = 200 + d * 260
    columns = {}
    for n in nodes:
        columns.setdefault(depth.get(n['id'], max_depth + 1), []).append(n)
    for col in columns.values():
        for i, n in enumerate(col):
            n['y'] = 200 + i * 120
