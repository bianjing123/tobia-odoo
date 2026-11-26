from odoo.tests.common import TransactionCase


class TestApprovalCenter(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': '审批中心测试单据'})
        model = self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
        flow = self.env['approval.flow'].create({
            'name': '审批中心测试流程', 'model_id': model.id,
        })
        start = self.env['approval.node'].create({
            'flow_id': flow.id, 'name': '开始', 'node_type': 'start',
        })
        approval = self.env['approval.node'].create({
            'flow_id': flow.id, 'name': '审批人', 'node_type': 'approval',
            'approver_user_ids': [(6, 0, self.env.user.ids)],
            'auto_pass_no_approver': False,
        })
        self.env['approval.transition'].create({
            'flow_id': flow.id, 'from_node_id': start.id,
            'to_node_id': approval.id,
        })
        self.instance = self.env['approval.instance']._start(flow, self.partner)

    def test_my_todo_contains_document(self):
        result = self.env['approval.instance'].get_center_rows('todo')
        row = next(row for row in result['rows'] if row['instance_id'] == self.instance.id)
        self.assertEqual(row['document_name'], self.partner.display_name)
        self.assertEqual(row['task_state'], 'pending')

    def test_detail_contains_document_and_progress(self):
        detail = self.env['approval.instance'].get_center_detail(self.instance.id)
        self.assertEqual(detail['document']['name'], self.partner.display_name)
        states = {node['name']: node['state'] for node in detail['diagram']['nodes']}
        self.assertEqual(states['开始'], 'approved')
        self.assertEqual(states['审批人'], 'running')

    def test_reject_from_center_saves_comment_and_finishes(self):
        task = self.instance.task_ids.filtered(lambda item: item.state == 'pending')
        task.action_center_decide('reject', '信息不完整')
        self.assertEqual(task.state, 'rejected')
        self.assertEqual(task.comment, '信息不完整')
        self.assertEqual(self.instance.state, 'rejected')
        states = {node['name']: node['state'] for node in
                  self.instance.get_center_detail(self.instance.id)['diagram']['nodes']}
        self.assertEqual(states['开始'], 'approved')
        self.assertEqual(states['审批人'], 'rejected')

    def test_internal_user_can_open_all_and_unrelated_detail(self):
        user = self.env['res.users'].create({
            'name': '审批中心普通用户', 'login': 'approval_center_regular',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('tb_approval.group_approval_user').id,
            ])],
        })
        center = self.env['approval.instance'].with_user(user)
        rows = center.get_center_rows('all')['rows']
        self.assertIn(self.instance.id, [row['instance_id'] for row in rows])
        detail = center.get_center_detail(self.instance.id)
        self.assertEqual(detail['instance_id'], self.instance.id)
