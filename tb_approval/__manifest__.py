# -*- coding: utf-8 -*-
{
    'name': 'TB 审批引擎',
    'version': '20.0.1.0.25',
    'category': 'Tools',
    'summary': '国产化审批流：会签/或签/加签/减签/排他与并行网关/子流程/抄送/流程图',
    'description': """
通用审批流程引擎（面向国产 OA 审批习惯）：
- 任何模型通过 tb.approval.mixin 接入审批
- 审批节点支持：或签、会签、加签、减签
- 路由支持：排他网关（条件分支）、并行网关（并行分支/汇聚）、子流程、抄送节点
- 流程图可视化（Owl + SVG），实例图上高亮当前节点
- 审批中心：我的待办 / 已办 / 我发起的 / 抄送我的
""",
    'depends': ['mail', 'web', 'hr'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/ir_sequence.xml',
        'views/approval_flow_views.xml',
        'views/approval_center_views.xml',
        'views/menus.xml',
        'security/cleanup.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tb_approval/static/lib/logicflow/index.min.js',
            'tb_approval/static/lib/logicflow/index.css',
            'tb_approval/static/src/flow_designer.js',
            'tb_approval/static/src/flow_workspace.js',
            'tb_approval/static/src/approval_center.js',
            'tb_approval/static/src/flow_designer.xml',
            'tb_approval/static/src/flow_workspace.xml',
            'tb_approval/static/src/approval_center.xml',
            'tb_approval/static/src/flow_designer.scss',
            'tb_approval/static/src/flow_workspace.scss',
            'tb_approval/static/src/approval_center.scss',
            'tb_approval/static/src/approval_ribbon.scss',
        ],
    },
    'application': True,
    'license': 'LGPL-3',
}
