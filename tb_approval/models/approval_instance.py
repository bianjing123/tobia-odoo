# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

STATE_TO_MIXIN = {
    'running': 'waiting',
    'approved': 'approved',
    'rejected': 'rejected',
    'cancelled': 'draft',
}


class ApprovalInstance(models.Model):
    _name = 'approval.instance'
    _description = '审批实例'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, copy=False,
                       default=lambda self: self.env['ir.sequence'].next_by_code('approval.instance'))
    flow_id = fields.Many2one('approval.flow', string='流程', required=True, ondelete='restrict', index=True)
    flow_version = fields.Char(related='flow_id.version_label', string='流程版本')
    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    record_name = fields.Char(compute='_compute_record_name')
    state = fields.Selection([
        ('running', '审批中'),
        ('approved', '已通过'),
        ('rejected', '已驳回'),
        ('cancelled', '已取消'),
    ], default='running', required=True, tracking=True, copy=False)
    initiator_id = fields.Many2one('res.users', string='发起人', default=lambda self: self.env.user)
    token_ids = fields.One2many('approval.token', 'instance_id', copy=False)
    task_ids = fields.One2many('approval.task', 'instance_id', copy=False)
    cc_ids = fields.One2many('approval.cc', 'instance_id', copy=False)
    # 子流程
    parent_instance_id = fields.Many2one('approval.instance', string='父实例', index=True, ondelete='cascade')
    subflow_node_id = fields.Many2one('approval.node', string='触发节点', ondelete='set null')
    diagram_data = fields.Char(compute='_compute_diagram_data')

    def write(self, vals):
        if 'flow_id' in vals and any(instance.flow_id.id != vals['flow_id'] for instance in self):
            raise UserError('审批实例绑定的流程版本不能修改。')
        return super().write(vals)

    @api.depends('res_model', 'res_id')
    def _compute_record_name(self):
        for inst in self:
            rec = inst._get_record()
            inst.record_name = rec.display_name if rec and rec.exists() else ''

    def _get_record(self):
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id)

    # ------------------------------------------------------------------
    # 流程图数据（LogicFlow 查看器）
    # ------------------------------------------------------------------
    @api.depends('state', 'token_ids.state', 'task_ids.state', 'task_ids.user_id',
                 'flow_id.node_ids', 'flow_id.transition_ids')
    def _compute_diagram_data(self):
        for inst in self:
            design = inst.flow_id._export_design()
            done_nodes = set(inst.token_ids.filtered(lambda t: t.state == 'done').mapped('node_id').ids)
            active_nodes = set(inst.token_ids.filtered(lambda t: t.state == 'active').mapped('node_id').ids)
            rejected_nodes = set(inst.task_ids.filtered(
                lambda task: task.state == 'rejected').mapped('node_id').ids)
            for node in design['nodes']:
                if node['id'] in rejected_nodes:
                    node['state'] = 'rejected'
                elif node['id'] in active_nodes:
                    node['state'] = 'running'
                elif node['id'] in done_nodes:
                    node['state'] = 'approved'
                else:
                    node['state'] = 'pending'
                if node['state'] == 'running' and node['node_type'] == 'approval':
                    tasks = inst.task_ids.filtered(
                        lambda t: t.node_id.id == node['id'] and t.state == 'pending')
                    if tasks:
                        node['desc'] = '待审批：' + '、'.join(tasks.mapped('user_id.name'))
            for edge in design['edges']:
                edge['label'] = edge.pop('condition', '')
            inst.diagram_data = json.dumps(design, ensure_ascii=False)

    # ------------------------------------------------------------------
    # 引擎
    # ------------------------------------------------------------------
    @api.model
    def _start(self, flow, record):
        """为单据 record 启动 flow 的审批实例。"""
        if self.search_count([('res_model', '=', record._name), ('res_id', '=', record.id),
                              ('state', '=', 'running')]):
            raise UserError('该单据已有进行中的审批。')
        inst = self.create({
            'flow_id': flow.id,
            'res_model': record._name,
            'res_id': record.id,
        })
        inst.message_post(body='发起审批：流程「%s」' % flow.name)
        start_nodes = flow.node_ids.filtered(lambda n: n.node_type == 'start')
        if len(start_nodes) != 1:
            raise UserError('流程「%s」没有配置开始节点，无法发起审批。' % flow.name)
        inst._activate_node(start_nodes[0])
        return inst

    def _activate_node(self, node):
        """到达节点：建 token，按节点类型分流。"""
        self.ensure_one()
        self.env['approval.token'].create({'instance_id': self.id, 'node_id': node.id})

        if node.node_type == 'cc':
            self._handle_cc(node)
            return self._complete_node(node)
        if node.node_type in ('start', 'exclusive', 'exclusive_join', 'parallel_split'):
            # 开始节点和分流网关不停留，直接沿出线流转。
            return self._complete_node(node)
        if node.node_type == 'parallel_join':
            incoming = len(node.in_transition_ids)
            active = self.token_ids.filtered(
                lambda t: t.node_id == node and t.state == 'active')
            if incoming and len(active) >= incoming:
                return self._complete_node(node)
            return  # 等待其他并行分支
        if node.node_type == 'end':
            return self._finish('approved')
        if node.node_type == 'subflow':
            return self._start_subflow(node)
        if node.node_type == 'approval':
            return self._create_tasks(node)
        if node.node_type == 'service':
            return self._run_service(node)
        raise UserError('未知的节点类型：%s' % node.node_type)

    def _run_service(self, node):
        method_name = (node.service_method or '').strip()
        if not method_name:
            raise UserError('服务任务「%s」未配置单据方法。' % node.name)
        record = self._get_record()
        if not record.exists():
            raise UserError('审批单据已被删除，服务任务无法执行。')
        method = getattr(record.with_context(_tb_approval_service_instance_id=self.id), method_name, None)
        if not callable(method):
            raise UserError('单据模型没有方法 %s。' % method_name)
        method()
        self.message_post(body='服务任务「%s」已执行。' % node.name)
        return self._complete_node(node)

    def _handle_cc(self, node):
        users = node._get_cc_users()
        for user in users:
            self.env['approval.cc'].create({
                'instance_id': self.id, 'node_id': node.id, 'user_id': user.id,
            })
        if users:
            self.message_subscribe(partner_ids=users.mapped('partner_id').ids)
            self.message_post(
                body='节点「%s」抄送' % node.name,
                partner_ids=users.mapped('partner_id').ids)

    def _start_subflow(self, node):
        if not node.sub_flow_id:
            raise UserError('子流程节点「%s」未配置子流程。' % node.name)
        if node.sub_flow_id.model_name != self.res_model:
            raise UserError('子流程「%s」的单据模型与当前实例不一致。' % node.sub_flow_id.name)
        ancestor = self
        while ancestor:
            if ancestor.flow_id == node.sub_flow_id:
                raise UserError('子流程不能递归调用自身。')
            ancestor = ancestor.parent_instance_id
        child = self.env['approval.instance'].create({
            'flow_id': node.sub_flow_id.id,
            'res_model': self.res_model,
            'res_id': self.res_id,
            'parent_instance_id': self.id,
            'subflow_node_id': node.id,
            'initiator_id': self.initiator_id.id,
        })
        child.message_post(body='作为「%s」的子流程启动。' % self.name)
        starts = node.sub_flow_id.node_ids.filtered(lambda n: n.node_type == 'start')
        if len(starts) != 1:
            raise UserError('子流程「%s」必须有且只有一个开始节点。' % node.sub_flow_id.name)
        start = starts[0]
        child._activate_node(start)

    def _create_tasks(self, node):
        users = node._get_approvers(self._get_record(), self.initiator_id)
        if not users:
            if node.auto_pass_no_approver:
                self.message_post(body='节点「%s」无审批人，自动通过。' % node.name)
                return self._complete_node(node)
            raise UserError('审批节点「%s」没有配置审批人。' % node.name)
        # 并行分支下同一节点可能被重复激活，避免重复任务
        existing = self.task_ids.filtered(
            lambda t: t.node_id == node and t.state == 'pending').mapped('user_id')
        for user in users - existing:
            self.env['approval.task'].create({
                'instance_id': self.id, 'node_id': node.id, 'user_id': user.id,
            })
        self.message_post(
            body='节点「%s」待审批（%s）' % (node.name, '、'.join(users.mapped('name'))),
            partner_ids=users.mapped('partner_id').ids)

    def _complete_node(self, node):
        """节点完成：消费 token 并路由。"""
        self.ensure_one()
        self.token_ids.filtered(
            lambda t: t.node_id == node and t.state == 'active').write({'state': 'done'})
        return self._route(node)

    def _route(self, node):
        self.ensure_one()
        doc = self._get_record()
        if not doc.exists():
            raise UserError('审批单据已被删除，流程无法继续。')
        transitions = node.out_transition_ids.sorted('sequence')
        if node.node_type == 'exclusive_join' and len(transitions) != 1:
            raise UserError('排他汇聚节点「%s」必须只有一条出线。' % node.name)
        if not transitions:
            raise UserError('节点「%s」没有出线，流程无法继续。' % node.name)
        if node.node_type == 'exclusive':
            targets = self._route_exclusive(transitions, doc)
        else:
            targets = transitions.filtered(lambda t: t._condition_ok(doc))
        if not targets:
            raise UserError('节点「%s」没有满足条件的出线。' % node.name)
        for trans in targets:
            self._activate_node(trans.to_node_id)

    def _route_exclusive(self, transitions, doc):
        matched = self.env['approval.transition']
        for trans in transitions:
            if not trans.is_default and trans._condition_ok(doc):
                matched |= trans
        if matched:
            return matched[:1]  # 按优先级取第一条
        defaults = transitions.filtered('is_default')
        if defaults:
            return defaults[:1]
        raise UserError('排他网关所有条件均不满足且没有兜底分支。')

    def _on_task_done(self, task, approved=True):
        """审批任务结束后推进节点。"""
        self.ensure_one()
        node = task.node_id
        if not approved:
            self._finish('rejected')
            return
        if node.approve_mode == 'or':
            self.task_ids.filtered(
                lambda t: t.node_id == node and t.state == 'pending'
            ).write({'state': 'cancelled'})
            return self._complete_node(node)
        pending = self.task_ids.filtered(
            lambda t: t.node_id == node and t.state == 'pending')
        if not pending:
            return self._complete_node(node)

    def _finish(self, state):
        self.ensure_one()
        self.task_ids.filtered(lambda t: t.state == 'pending').write({'state': 'cancelled'})
        self.token_ids.filtered(lambda t: t.state == 'active').write({'state': 'done'})
        self.state = state
        record = self._get_record()
        # 子流程结束只唤醒父流程；单据状态由根实例最终结束时统一回写。
        if not self.parent_instance_id and record.exists() and 'approval_state' in record._fields:
            record.sudo().write({'approval_state': STATE_TO_MIXIN[state]})
        if self.parent_instance_id:
            parent = self.parent_instance_id
            if state == 'approved':
                parent.message_post(body='子流程「%s」通过，继续流转。' % self.name)
                parent._complete_node(self.subflow_node_id)
            else:
                parent.message_post(body='子流程「%s」被驳回。' % self.name)
                parent._finish('rejected')
        return True

    # ------------------------------------------------------------------
    # 用户操作
    # ------------------------------------------------------------------
    def action_cancel(self):
        for inst in self:
            if inst.state != 'running':
                raise UserError('只能取消进行中的审批。')
            if inst.parent_instance_id:
                raise UserError('子流程不能单独取消，请取消主流程。')
        self._finish('cancelled')
        return True

    def action_open_add_signer(self):
        self.ensure_one()
        if self.state != 'running':
            raise UserError('审批已结束，不能加签。')
        return {
            'type': 'ir.actions.act_window',
            'name': '加签',
            'res_model': 'approval.add.signer',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_instance_id': self.id},
        }

    def action_view_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.record_name or '单据',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _current_approval_nodes(self):
        return self.token_ids.filtered(
            lambda t: t.state == 'active').mapped('node_id').filtered(
            lambda n: n.node_type == 'approval')


class ApprovalToken(models.Model):
    _name = 'approval.token'
    _description = '审批流程令牌'
    instance_id = fields.Many2one('approval.instance', required=True, ondelete='cascade', index=True)
    node_id = fields.Many2one('approval.node', required=True, ondelete='cascade', index=True)
    state = fields.Selection([('active', '活动'), ('done', '完成')], default='active', required=True)

    def write(self, vals):
        if 'node_id' in vals and any(token.node_id.id != vals['node_id'] for token in self):
            raise UserError('审批令牌绑定的流程节点不能修改。')
        return super().write(vals)


class ApprovalTask(models.Model):
    _name = 'approval.task'
    _description = '审批任务'
    _order = 'id desc'

    instance_id = fields.Many2one('approval.instance', required=True, ondelete='cascade', index=True)
    node_id = fields.Many2one('approval.node', required=True, ondelete='restrict', index=True)
    user_id = fields.Many2one('res.users', string='审批人', required=True, index=True)
    state = fields.Selection([
        ('pending', '待审批'), ('approved', '已通过'),
        ('rejected', '已驳回'), ('cancelled', '已取消'),
    ], default='pending', required=True, tracking=True)
    comment = fields.Text('审批意见', copy=False)
    date_done = fields.Datetime('处理时间', copy=False)

    def write(self, vals):
        if 'node_id' in vals and any(task.node_id.id != vals['node_id'] for task in self):
            raise UserError('审批任务绑定的流程节点不能修改。')
        return super().write(vals)

    def _check_can_handle(self):
        for task in self:
            if task.state != 'pending':
                raise UserError('该任务已处理。')
            if task.user_id != self.env.user:
                raise UserError('只有任务审批人可以处理。')

    def action_approve(self):
        self._check_can_handle()
        for task in self:
            task.write({'state': 'approved', 'date_done': fields.Datetime.now()})
            task.instance_id.message_post(
                body='%s 通过了节点「%s」' % (self.env.user.name, task.node_id.name))
            task.instance_id._on_task_done(task, approved=True)
        return True

    def action_reject(self):
        self._check_can_handle()
        for task in self:
            task.write({'state': 'rejected', 'date_done': fields.Datetime.now()})
            task.instance_id.message_post(
                body='%s 驳回了节点「%s」' % (self.env.user.name, task.node_id.name))
            task.instance_id._on_task_done(task, approved=False)
        return True

    def action_cancel_task(self):
        """减签：取消一个待审批任务。"""
        self._check_can_handle()
        for task in self:
            node = task.node_id
            siblings = task.instance_id.task_ids.filtered(
                lambda t: t.node_id == node and t.state == 'pending' and t != task)
            if not siblings:
                raise UserError('节点「%s」只剩这一个待审批人，不能减签。' % node.name)
            task.write({'state': 'cancelled', 'date_done': fields.Datetime.now()})
            task.instance_id.message_post(
                body='%s 被减签出节点「%s」' % (task.user_id.name, node.name))
            if node.approve_mode == 'and' and not siblings:
                task.instance_id._complete_node(node)
        return True


class ApprovalCc(models.Model):
    _name = 'approval.cc'
    _description = '审批抄送'
    _order = 'id desc'

    instance_id = fields.Many2one('approval.instance', required=True, ondelete='cascade', index=True)
    node_id = fields.Many2one('approval.node', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='抄送人', required=True, index=True)
    read_at = fields.Datetime('阅读时间')


class ApprovalAddSigner(models.TransientModel):
    _name = 'approval.add.signer'
    _description = '加签向导'

    instance_id = fields.Many2one('approval.instance', required=True)
    node_id = fields.Many2one('approval.node', string='加签节点', required=True)
    user_ids = fields.Many2many('res.users', string='加签审批人', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        inst = self.env['approval.instance'].browse(self.env.context.get('active_id'))
        if inst.exists():
            res['instance_id'] = inst.id
            nodes = inst._current_approval_nodes()
            if len(nodes) == 1:
                res['node_id'] = nodes[0].id
        return res

    def action_add(self):
        self.ensure_one()
        node = self.node_id
        if node not in self.instance_id._current_approval_nodes():
            raise UserError('该节点当前不在审批中。')
        existing = self.instance_id.task_ids.filtered(
            lambda t: t.node_id == node and t.state == 'pending').mapped('user_id')
        for user in self.user_ids - existing:
            self.env['approval.task'].create({
                'instance_id': self.instance_id.id, 'node_id': node.id, 'user_id': user.id,
            })
        self.instance_id.message_post(
            body='%s 给节点「%s」加签：%s' % (
                self.env.user.name, node.name, '、'.join(self.user_ids.mapped('name'))))
        return {'type': 'ir.actions.act_window_close'}
