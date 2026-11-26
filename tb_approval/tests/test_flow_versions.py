import json

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestFlowVersions(TransactionCase):

    def setUp(self):
        super().setUp()
        model = self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
        self.flow = self.env['approval.flow'].create({
            'name': '采购审批版本测试', 'model_id': model.id,
        })
        self.start = self.env['approval.node'].create({
            'flow_id': self.flow.id, 'name': '开始', 'node_type': 'start', 'x': 100, 'y': 100,
        })
        self.approval = self.env['approval.node'].create({
            'flow_id': self.flow.id, 'name': '审批', 'node_type': 'approval', 'x': 100, 'y': 250,
            'approver_user_ids': [(6, 0, self.env.user.ids)],
            'auto_pass_no_approver': False,
        })
        self.end = self.env['approval.node'].create({
            'flow_id': self.flow.id, 'name': '结束', 'node_type': 'end', 'x': 100, 'y': 400,
        })
        for priority, (source, target) in enumerate(
                ((self.start, self.approval), (self.approval, self.end)), start=1):
            self.env['approval.transition'].create({
                'flow_id': self.flow.id, 'from_node_id': source.id, 'to_node_id': target.id,
                'sequence': priority * 5,
            })
        partner = self.env['res.partner'].create({'name': 'V1 采购单'})
        self.instance = self.env['approval.instance']._start(self.flow, partner)
        self.assertEqual(self.instance.state, 'running')

    def _payload(self, flow):
        design = flow._export_design()
        return {
            'nodes': [dict(node, key='n%s' % node['id'], db_id=node['id'],
                           approver_user_ids=[u['id'] for u in node['approver_user_ids']],
                           cc_user_ids=[u['id'] for u in node['cc_user_ids']])
                      for node in design['nodes']],
            'edges': [dict(edge, key='e%s' % edge['id'], db_id=edge['id'],
                           from_key='n%s' % edge['from'], to_key='n%s' % edge['to'])
                      for edge in design['edges']],
        }

    def test_publish_keeps_running_instance_on_v1(self):
        payload = self._payload(self.flow)
        payload['nodes'].append({
            'key': 'review', 'db_id': False, 'name': '复核', 'node_type': 'approval',
            'x': 300, 'y': 350, 'approver_user_ids': self.env.user.ids,
            'auto_pass_no_approver': False,
        })
        old_edge = next(edge for edge in payload['edges']
                        if edge['from_key'] == 'n%s' % self.approval.id)
        old_edge['to_key'] = 'review'
        payload['edges'].append({
            'key': 'review-end', 'db_id': False, 'from_key': 'review',
            'to_key': 'n%s' % self.end.id,
        })

        new_id = self.flow.save_design(payload)
        new_flow = self.env['approval.flow'].browse(new_id)

        self.assertNotEqual(new_flow, self.flow)
        self.assertEqual(self.flow.version_label, 'V1.0')
        self.assertEqual(new_flow.version_label, 'V2.0')
        self.assertEqual(self.flow.superseded_by_id, new_flow)
        self.assertFalse(self.flow.active)
        self.assertTrue(new_flow.active)
        self.assertEqual(self.instance.flow_id, self.flow)
        self.assertEqual(len(self.flow.node_ids), 3)
        self.assertEqual(len(new_flow.node_ids), 4)
        self.assertEqual(sorted(new_flow.transition_ids.mapped('sequence')), [5, 10, 10])

        self.instance.task_ids.filtered(lambda task: task.state == 'pending').action_approve()
        self.assertEqual(self.instance.state, 'approved')
        self.assertEqual(len(json.loads(self.instance.diagram_data)['nodes']), 3)

        partner_v2 = self.env['res.partner'].create({'name': 'V2 采购单'})
        instance_v2 = self.env['approval.instance']._start(new_flow, partner_v2)
        self.assertEqual(instance_v2.flow_version, 'V2.0')
        self.assertEqual(instance_v2.flow_id, new_flow)
        self.assertEqual(len(json.loads(instance_v2.diagram_data)['nodes']), 4)

    def test_each_publish_increments_version(self):
        second = self.env['approval.flow'].browse(self.flow.save_design(self._payload(self.flow)))
        third = self.env['approval.flow'].browse(second.save_design(self._payload(second)))
        self.assertEqual([self.flow.version_number, second.version_number, third.version_number], [1, 2, 3])
        self.assertEqual(third.root_flow_id, self.flow)
        self.assertEqual(self.flow.action_open_designer()['params']['flow_id'], third.id)

    def test_first_publish_uses_v1(self):
        model = self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
        flow = self.env['approval.flow'].create({'name': '新流程', 'model_id': model.id})
        payload = {
            'nodes': [
                {'key': 'start', 'name': '开始', 'node_type': 'start', 'x': 100, 'y': 100},
                {'key': 'end', 'name': '结束', 'node_type': 'end', 'x': 100, 'y': 250},
            ],
            'edges': [{'key': 'start-end', 'from_key': 'start', 'to_key': 'end'}],
        }
        self.assertEqual(flow.save_design(payload), flow.id)
        self.assertEqual(flow.version_label, 'V1.0')
        self.assertEqual(self.env['approval.flow'].browse(flow.save_design(self._payload(flow))).version_label, 'V2.0')

    def test_historical_nodes_cannot_change(self):
        self.flow.save_design(self._payload(self.flow))
        with self.assertRaises(UserError):
            self.approval.write({'name': '错误改动'})
        self.assertEqual(self.approval.name, '审批')

    def test_publish_rejects_unreachable_node(self):
        payload = self._payload(self.flow)
        payload['nodes'].append({
            'key': 'orphan', 'name': '孤立审批', 'node_type': 'approval',
            'x': 300, 'y': 300,
        })
        with self.assertRaises(ValidationError):
            self.flow.save_design(payload)
        self.assertFalse(self.flow.superseded_by_id)

    def test_publish_rejects_cycle(self):
        payload = self._payload(self.flow)
        payload['nodes'].append({
            'key': 'review', 'name': '复核', 'node_type': 'approval',
            'x': 300, 'y': 350,
        })
        payload['edges'].extend([
            {'key': 'to-review', 'from_key': 'n%s' % self.approval.id, 'to_key': 'review'},
            {'key': 'back', 'from_key': 'review', 'to_key': 'n%s' % self.approval.id},
        ])
        with self.assertRaises(ValidationError):
            self.flow.save_design(payload)

    def test_publish_rejects_dead_end(self):
        payload = self._payload(self.flow)
        payload['edges'] = [edge for edge in payload['edges']
                            if edge['from_key'] != 'n%s' % self.approval.id]
        with self.assertRaises(ValidationError):
            self.flow.save_design(payload)

    def test_publish_rejects_parallel_join_without_common_split(self):
        payload = self._payload(self.flow)
        payload['nodes'].extend([
            {'key': 'branch', 'name': '排他网关', 'node_type': 'exclusive', 'x': 300, 'y': 350},
            {'key': 'left', 'name': '左审批', 'node_type': 'approval', 'x': 200, 'y': 450},
            {'key': 'right', 'name': '右审批', 'node_type': 'approval', 'x': 400, 'y': 450},
            {'key': 'join', 'name': '并行汇聚', 'node_type': 'parallel_join', 'x': 300, 'y': 550},
        ])
        payload['edges'] = [edge for edge in payload['edges']
                            if edge['from_key'] != 'n%s' % self.approval.id]
        payload['edges'].extend([
            {'key': 'a-b', 'from_key': 'n%s' % self.approval.id, 'to_key': 'branch'},
            {'key': 'b-l', 'from_key': 'branch', 'to_key': 'left'},
            {'key': 'b-r', 'from_key': 'branch', 'to_key': 'right'},
            {'key': 'l-j', 'from_key': 'left', 'to_key': 'join'},
            {'key': 'r-j', 'from_key': 'right', 'to_key': 'join'},
            {'key': 'j-e', 'from_key': 'join', 'to_key': 'n%s' % self.end.id},
        ])
        with self.assertRaises(ValidationError):
            self.flow.save_design(payload)

    def test_publish_accepts_parallel_branches_with_matching_join(self):
        payload = self._payload(self.flow)
        payload['nodes'].extend([
            {'key': 'split', 'name': '并行分支', 'node_type': 'parallel_split', 'x': 300, 'y': 350},
            {'key': 'left', 'name': '左审批', 'node_type': 'approval', 'x': 200, 'y': 450},
            {'key': 'right', 'name': '右审批', 'node_type': 'approval', 'x': 400, 'y': 450},
            {'key': 'join', 'name': '并行汇聚', 'node_type': 'parallel_join', 'x': 300, 'y': 550},
        ])
        payload['edges'] = [edge for edge in payload['edges']
                            if edge['from_key'] != 'n%s' % self.approval.id]
        payload['edges'].extend([
            {'key': 'a-s', 'from_key': 'n%s' % self.approval.id, 'to_key': 'split'},
            {'key': 's-l', 'from_key': 'split', 'to_key': 'left'},
            {'key': 's-r', 'from_key': 'split', 'to_key': 'right'},
            {'key': 'l-j', 'from_key': 'left', 'to_key': 'join'},
            {'key': 'r-j', 'from_key': 'right', 'to_key': 'join'},
            {'key': 'j-e', 'from_key': 'join', 'to_key': 'n%s' % self.end.id},
        ])
        new_flow = self.env['approval.flow'].browse(self.flow.save_design(payload))
        self.assertEqual(len(new_flow.node_ids), 7)

    def test_publish_rejects_conditional_parallel_branch(self):
        payload = self._payload(self.flow)
        payload['nodes'].extend([
            {'key': 'split', 'name': '并行分支', 'node_type': 'parallel_split', 'x': 300, 'y': 350},
            {'key': 'left', 'name': '左审批', 'node_type': 'approval', 'x': 200, 'y': 450},
            {'key': 'right', 'name': '右审批', 'node_type': 'approval', 'x': 400, 'y': 450},
            {'key': 'join', 'name': '并行汇聚', 'node_type': 'parallel_join', 'x': 300, 'y': 550},
        ])
        payload['edges'] = [edge for edge in payload['edges']
                            if edge['from_key'] != 'n%s' % self.approval.id]
        payload['edges'].extend([
            {'key': 'a-s', 'from_key': 'n%s' % self.approval.id, 'to_key': 'split'},
            {'key': 's-l', 'from_key': 'split', 'to_key': 'left',
             'condition': 'object.id > 0'},
            {'key': 's-r', 'from_key': 'split', 'to_key': 'right'},
            {'key': 'l-j', 'from_key': 'left', 'to_key': 'join'},
            {'key': 'r-j', 'from_key': 'right', 'to_key': 'join'},
            {'key': 'j-e', 'from_key': 'join', 'to_key': 'n%s' % self.end.id},
        ])
        with self.assertRaises(ValidationError):
            self.flow.save_design(payload)

    def test_publish_rejects_parallel_branch_bypassing_join(self):
        payload = self._payload(self.flow)
        payload['nodes'].extend([
            {'key': 'split', 'name': '并行分支', 'node_type': 'parallel_split', 'x': 300, 'y': 350},
            {'key': 'left', 'name': '左审批', 'node_type': 'approval', 'x': 200, 'y': 450},
            {'key': 'right', 'name': '右审批', 'node_type': 'approval', 'x': 400, 'y': 450},
            {'key': 'skip', 'name': '绕行审批', 'node_type': 'approval', 'x': 550, 'y': 450},
            {'key': 'join', 'name': '并行汇聚', 'node_type': 'parallel_join', 'x': 300, 'y': 550},
        ])
        payload['edges'] = [edge for edge in payload['edges']
                            if edge['from_key'] != 'n%s' % self.approval.id]
        payload['edges'].extend([
            {'key': 'a-s', 'from_key': 'n%s' % self.approval.id, 'to_key': 'split'},
            {'key': 's-l', 'from_key': 'split', 'to_key': 'left'},
            {'key': 's-r', 'from_key': 'split', 'to_key': 'right'},
            {'key': 's-x', 'from_key': 'split', 'to_key': 'skip'},
            {'key': 'l-j', 'from_key': 'left', 'to_key': 'join'},
            {'key': 'r-j', 'from_key': 'right', 'to_key': 'join'},
            {'key': 'j-e', 'from_key': 'join', 'to_key': 'n%s' % self.end.id},
            {'key': 'x-e', 'from_key': 'skip', 'to_key': 'n%s' % self.end.id},
        ])
        with self.assertRaises(ValidationError):
            self.flow.save_design(payload)
