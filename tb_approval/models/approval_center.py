import json

from odoo import api, models
from odoo.exceptions import AccessError, UserError


class ApprovalInstance(models.Model):
    _inherit = 'approval.instance'

    def _center_document_info(self, with_fields=False, allow_purchase_summary=False):
        self.ensure_one()
        fallback = {
            'available': False,
            'summary_available': False,
            'name': '单据不可访问',
            'model': self.res_model,
            'res_id': self.res_id,
            'fields': [],
            'lines': [],
        }
        try:
            record = self._get_record().exists()
            if not record:
                return {**fallback, 'name': '单据已删除'}
            can_open = True
            try:
                record.check_access('read')
            except AccessError:
                if not (allow_purchase_summary and self.res_model == 'purchase.order'):
                    return fallback
                # 已核验为该实例的发起人、审批人或管理员；仅提供采购决策必需的摘要。
                record = record.sudo()
                can_open = False
            result = {
                'available': can_open,
                'summary_available': True,
                'name': record.display_name,
                'model': self.res_model,
                'model_label': record._description,
                'res_id': record.id,
                'fields': [],
                'lines': [],
            }
            if with_fields:
                for field_name in ('partner_id', 'amount_total', 'currency_id',
                                   'company_id', 'date_order', 'state'):
                    if field_name not in record._fields:
                        continue
                    value = record[field_name]
                    if value is False or value is None or value == '':
                        continue
                    if hasattr(value, '_name') and not value:
                        continue
                    display = value.display_name if hasattr(value, 'display_name') else str(value)
                    result['fields'].append({
                        'label': record._fields[field_name].string,
                        'value': display,
                    })
                if self.res_model == 'purchase.order':
                    # 审批参与者只能取得当前采购单的审批摘要，订单行仅用于决策展示。
                    purchase = record.sudo()
                    lines = purchase.order_line.filtered(lambda line: not line.display_type)
                    result['line_count'] = len(lines)
                    result['lines'] = [{
                        'product': (line.product_id.display_name if line.product_id else line.name) or '',
                        'quantity': line.product_qty,
                        'unit': line.uom_id.name if line.uom_id else '',
                        'price': line.price_unit,
                        'subtotal': line.price_subtotal,
                    } for line in lines[:100]]
            return result
        except (AccessError, KeyError):
            return fallback

    def _center_row(self, task=None):
        self.ensure_one()
        document = self._center_document_info(allow_purchase_summary=True)
        return {
            'id': 'task-%s' % task.id if task else 'instance-%s' % self.id,
            'instance_id': self.id,
            'task_id': task.id if task else False,
            'task_state': task.state if task else False,
            'node_name': task.node_id.name if task else '',
            'name': self.name,
            'flow_name': self.flow_id.name,
            'flow_version': self.flow_version,
            'document_name': document['name'],
            'document_model': document.get('model_label') or self.res_model,
            'state': self.state,
            'initiator': self.initiator_id.name,
            'created_at': str(task.create_date if task else self.create_date),
        }

    @api.model
    def get_center_rows(self, tab, offset=0, limit=40):
        if tab not in ('todo', 'done', 'mine', 'all'):
            raise UserError('未知的审批视图。')
        offset = max(0, int(offset))
        limit = min(60, max(1, int(limit)))
        if tab in ('todo', 'done'):
            domain = [('user_id', '=', self.env.user.id)]
            if tab == 'todo':
                domain.append(('state', '=', 'pending'))
            else:
                domain.append(('state', 'in', ['approved', 'rejected']))
            tasks = self.env['approval.task'].search(
                domain, order='id desc', offset=offset, limit=limit + 1)
            rows = [task.instance_id._center_row(task) for task in tasks[:limit]]
            has_more = len(tasks) > limit
        else:
            domain = [] if tab == 'all' else [('initiator_id', '=', self.env.user.id)]
            instances = self.search(domain, order='id desc', offset=offset, limit=limit + 1)
            rows = [instance._center_row() for instance in instances[:limit]]
            has_more = len(instances) > limit
        return {'rows': rows, 'has_more': has_more}

    @api.model
    def get_center_detail(self, instance_id):
        instance = self.browse(int(instance_id)).exists()
        if not instance:
            raise UserError('审批实例不存在。')
        design = json.loads(instance.diagram_data or '{}')
        diagram = {
            'nodes': [{key: node.get(key) for key in
                       ('id', 'name', 'node_type', 'x', 'y', 'state', 'desc')}
                      for node in design.get('nodes', [])],
            'edges': [{key: edge.get(key) for key in
                       ('id', 'from', 'to', 'from_anchor', 'to_anchor', 'name', 'label')}
                      for edge in design.get('edges', [])],
        }
        return {
            'instance_id': instance.id,
            'name': instance.name,
            'state': instance.state,
            'flow_version': instance.flow_version,
            'document': instance._center_document_info(
                with_fields=True, allow_purchase_summary=True),
            'diagram': diagram,
            'tasks': [{
                'id': task.id,
                'node': task.node_id.name,
                'user': task.user_id.name,
                'state': task.state,
                'comment': task.comment or '',
            } for task in instance.task_ids.sorted('id')],
        }


class ApprovalTask(models.Model):
    _inherit = 'approval.task'

    def action_center_decide(self, decision, comment=''):
        self.ensure_one()
        if decision not in ('approve', 'reject'):
            raise UserError('未知的审批操作。')
        self._check_can_handle()
        self.write({'comment': (comment or '').strip()})
        return self.action_approve() if decision == 'approve' else self.action_reject()
