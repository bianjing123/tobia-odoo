from odoo.tests.common import TransactionCase


class TestStartNode(TransactionCase):

    def test_start_node_routes_to_approval_task(self):
        partner = self.env['res.partner'].create({'name': '开始节点测试单据'})
        model = self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
        flow = self.env['approval.flow'].create({
            'name': '开始节点流转测试', 'model_id': model.id,
        })
        start = self.env['approval.node'].create({
            'flow_id': flow.id, 'name': '开始', 'node_type': 'start',
        })
        approval = self.env['approval.node'].create({
            'flow_id': flow.id, 'name': '审批', 'node_type': 'approval',
            'approver_user_ids': [(6, 0, self.env.user.ids)],
            'auto_pass_no_approver': False,
        })
        self.env['approval.transition'].create({
            'flow_id': flow.id,
            'from_node_id': start.id,
            'to_node_id': approval.id,
        })

        instance = self.env['approval.instance']._start(flow, partner)

        self.assertEqual(instance.state, 'running')
        self.assertEqual(instance.token_ids.filtered(
            lambda token: token.node_id == start).state, 'done')
        self.assertEqual(len(instance.task_ids.filtered(
            lambda task: task.node_id == approval and task.state == 'pending')), 1)
