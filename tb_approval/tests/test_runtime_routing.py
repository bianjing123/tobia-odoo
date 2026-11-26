from odoo.tests.common import TransactionCase


class TestRuntimeRouting(TransactionCase):

    def _flow(self, name):
        model = self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
        return self.env['approval.flow'].create({'name': name, 'model_id': model.id})

    def _node(self, flow, name, kind, **values):
        return self.env['approval.node'].create({
            'flow_id': flow.id, 'name': name, 'node_type': kind, **values,
        })

    def _edge(self, flow, source, target, **values):
        return self.env['approval.transition'].create({
            'flow_id': flow.id, 'from_node_id': source.id,
            'to_node_id': target.id, **values,
        })

    def test_exclusive_condition_and_default_create_correct_task(self):
        flow = self._flow('条件路由测试')
        start = self._node(flow, '开始', 'start')
        gateway = self._node(flow, '条件', 'exclusive')
        match = self._node(flow, '匹配审批', 'approval',
                           approver_user_ids=[(6, 0, self.env.user.ids)])
        fallback = self._node(flow, '默认审批', 'approval',
                              approver_user_ids=[(6, 0, self.env.user.ids)])
        self._edge(flow, start, gateway)
        self._edge(flow, gateway, match, condition="object.name == '匹配'")
        self._edge(flow, gateway, fallback, is_default=True)

        matched = self.env['approval.instance']._start(
            flow, self.env['res.partner'].create({'name': '匹配'}))
        defaulted = self.env['approval.instance']._start(
            flow, self.env['res.partner'].create({'name': '其他'}))

        self.assertEqual(matched.task_ids.filtered(lambda task: task.state == 'pending').node_id, match)
        self.assertEqual(defaulted.task_ids.filtered(lambda task: task.state == 'pending').node_id, fallback)

    def test_subflow_completion_resumes_parent(self):
        child_flow = self._flow('子流程')
        child_start = self._node(child_flow, '开始', 'start')
        child_end = self._node(child_flow, '结束', 'end')
        self._edge(child_flow, child_start, child_end)

        parent_flow = self._flow('主流程')
        parent_start = self._node(parent_flow, '开始', 'start')
        subflow = self._node(parent_flow, '子流程', 'subflow', sub_flow_id=child_flow.id)
        parent_end = self._node(parent_flow, '结束', 'end')
        self._edge(parent_flow, parent_start, subflow)
        self._edge(parent_flow, subflow, parent_end)

        parent = self.env['approval.instance']._start(
            parent_flow, self.env['res.partner'].create({'name': '子流程测试单据'}))
        child = self.env['approval.instance'].search([('parent_instance_id', '=', parent.id)])

        self.assertEqual(child.state, 'approved')
        self.assertEqual(parent.state, 'approved')
        self.assertEqual(child.flow_id, child_flow)

    def test_service_accepts_method_without_name_prefix(self):
        flow = self._flow('服务方法名称测试')
        start = self._node(flow, '开始', 'start')
        service = self._node(flow, '服务任务', 'service', service_method='ensure_one')
        end = self._node(flow, '结束', 'end')
        self._edge(flow, start, service)
        self._edge(flow, service, end)

        instance = self.env['approval.instance']._start(
            flow, self.env['res.partner'].create({'name': '服务方法测试单据'}))

        self.assertEqual(instance.state, 'approved')
