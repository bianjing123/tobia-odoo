# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError
from lxml import etree


class ApprovalMixin(models.AbstractModel):
    """审批接入 mixin。

    用法：目标模型继承 tb.approval.mixin；表单按钮和审批状态由视图钩子注入。
    """
    _name = 'tb.approval.mixin'
    _description = '审批接入 Mixin'

    approval_state = fields.Selection([
        ('draft', '未提交'),
        ('waiting', '审批中'),
        ('approved', '已通过'),
        ('rejected', '已驳回'),
    ], default='draft', tracking=True, copy=False, index=True)
    approval_instance_ids = fields.One2many(
        'approval.instance', compute='_compute_approval_instances')
    current_approval_instance_id = fields.Many2one(
        'approval.instance', compute='_compute_approval_instances')
    approval_instance_count = fields.Integer(compute='_compute_approval_instances')
    approval_required = fields.Boolean(compute='_compute_approval_required')

    def _compute_approval_required(self):
        for rec in self:
            rec.approval_required = bool(rec._approval_flow())

    def _approval_submit_invisible(self):
        return "approval_state not in ('draft', 'rejected') or not approval_required"

    def _approval_customize_view(self, arch):
        """供接入模型调整自身表单按钮，通用审批控件仍由 mixin 注入。"""

    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type != 'form' or arch.tag != 'form':
            return arch, view

        header = arch.find('header')
        if header is None:
            header = etree.Element('header')
            arch.insert(0, header)
        for field_name in ('approval_state', 'approval_required', 'approval_instance_count'):
            if not arch.xpath(".//field[@name='%s' and not(ancestor::field)]" % field_name):
                etree.SubElement(header, 'field', name=field_name, invisible='1')
        if not header.xpath("./button[@name='action_submit_approval']"):
            etree.SubElement(header, 'button', {
                'name': 'action_submit_approval',
                'type': 'object',
                'string': '提交审批',
                'class': 'oe_highlight',
                'invisible': self._approval_submit_invisible(),
            })
        if not header.xpath("./button[@name='action_cancel_approval']"):
            etree.SubElement(header, 'button', {
                'name': 'action_cancel_approval',
                'type': 'object',
                'string': '撤回审批',
                'invisible': "approval_state != 'waiting'",
            })

        sheet = arch.find('sheet')
        button_box = (sheet if sheet is not None else arch).xpath("./div[@name='button_box']")
        if button_box:
            button_box = button_box[0]
        else:
            button_box = etree.Element('div', {'name': 'button_box', 'class': 'oe_button_box'})
            if sheet is not None:
                sheet.insert(0, button_box)
            else:
                arch.insert(list(arch).index(header) + 1, button_box)
        if not button_box.xpath("./button[@name='action_view_approval']"):
            button = etree.SubElement(button_box, 'button', {
                'name': 'action_view_approval',
                'type': 'object',
                'class': 'oe_stat_button',
                'icon': 'fa-sitemap',
                'invisible': 'approval_instance_count == 0',
            })
            etree.SubElement(button, 'field', {
                'name': 'approval_instance_count',
                'widget': 'statinfo',
                'string': '审批记录',
            })

        if not arch.xpath(".//widget[@name='web_ribbon' and @class='tb_approval_status_ribbon']"):
            sheet = arch.find('sheet')
            if sheet is None:
                sheet = etree.Element('div', {'class': 'tb_approval_ribbon_anchor'})
                arch.insert(list(arch).index(header) + 1, sheet)
            ribbons = (
                ('未提交', 'text-bg-secondary', "approval_state != 'draft' or not approval_required"),
                ('审批中', 'text-bg-info', "approval_state != 'waiting'"),
                ('已通过', 'text-bg-success', "approval_state != 'approved'"),
                ('已驳回', 'text-bg-danger', "approval_state != 'rejected'"),
            )
            for index, (title, color, invisible) in enumerate(ribbons):
                sheet.insert(index, etree.Element('widget', {
                    'name': 'web_ribbon',
                    'class': 'tb_approval_status_ribbon',
                    'title': title,
                    'bg_color': color,
                    'invisible': invisible,
                }))
        self._approval_customize_view(arch)
        return arch, view

    def _compute_approval_instances(self):
        for rec in self:
            instances = self.env['approval.instance'].search([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id),
            ])
            rec.approval_instance_ids = instances
            rec.current_approval_instance_id = instances.filtered(
                lambda i: i.state == 'running')[:1]
            rec.approval_instance_count = len(instances)

    # ------------------------------------------------------------------
    def _approval_flow(self):
        self.ensure_one()
        return self.env['approval.flow'].search([
            ('model_name', '=', self._name), ('active', '=', True),
        ], limit=1)

    def action_submit_approval(self):
        """提交审批：自动找该模型当前唯一的启用流程。"""
        self.ensure_one()
        if self.approval_state not in ('draft', 'rejected'):
            raise UserError('当前状态不能提交审批。')
        if not self.id:
            raise UserError('请先保存单据再提交审批。')
        flow = self._approval_flow()
        if not flow:
            raise UserError('未找到单据模型 %s 的可用审批流程，请联系管理员配置。' % self._name)
        self.write({'approval_state': 'waiting'})
        self.env['approval.instance']._start(flow, self)
        return True

    def action_cancel_approval(self):
        self.ensure_one()
        inst = self.current_approval_instance_id
        if inst:
            inst.action_cancel()
        return True

    def action_reset_approval(self):
        """驳回/取消后重新编辑，回到未提交。"""
        self.ensure_one()
        if self.approval_state not in ('rejected', 'draft'):
            raise UserError('只有被驳回的单据可以重新编辑。')
        self.approval_state = 'draft'
        return True

    def action_view_approval(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '审批记录',
            'res_model': 'approval.instance',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
        }
