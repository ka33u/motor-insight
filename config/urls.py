from django.urls import path
from app import issue_workspace_views as iw
from app import bi_field_catalog_views as field_catalog
from app import topic_page_views
from app import device_intake_views as device_intake
from app import device_collector_views as collector
from app import views,delivery_views,metric_views,lineage_views,coding_views
from app import process_quality_views
from app import analysis_pivot_views
from app import analysis_scatter_views
from app import analysis_explore_views
from app import import_mapping_views
from app import import_template_views
from app import spc_views
from app import spc_workspace_views as spc_workspace
process_quality_urls=[path('api/process-quality',process_quality_views.board),path('api/process-quality/export',process_quality_views.export),path('api/process-quality/<str:key>',process_quality_views.detail),path('api/process-quality/<str:key>/evidence',process_quality_views.evidence),path('api/process-quality/<str:key>/follow-up',process_quality_views.follow_up),path('api/process-quality/<str:key>/history',process_quality_views.history)]
urlpatterns=[path('api/metrics',metric_views.collection),path('api/metrics/<int:version_id>',metric_views.version),path('api/metrics/<int:version_id>/preview',metric_views.preview)]
urlpatterns += [path('api/topic-pages',topic_page_views.collection),path('api/topic-pages/preview',topic_page_views.preview),path('api/topic-pages/<uuid:key>',topic_page_views.detail),path('api/topic-pages/<uuid:key>/history',topic_page_views.history),path('api/topic-pages/<uuid:key>/archive',topic_page_views.archive),path('api/topic-pages/<uuid:key>/navigate',topic_page_views.navigate),path('api/topic-pages/<uuid:key>/export',topic_page_views.export)]
urlpatterns += [path('api/bi-field-catalog',field_catalog.board),path('api/bi-field-catalog/export',field_catalog.export)]
urlpatterns += [path('api/device-intake',device_intake.board),path('api/device-intake/export',device_intake.export),path('api/device-intake/rows/<str:key>',device_intake.detail)]
urlpatterns += [path('api/device-collection',collector.board),path('api/device-collection/preview',collector.preview),path('api/device-collection/runs',collector.create),path('api/device-collection/runs/<uuid:run_id>',collector.detail),path('api/device-collection/runs/<uuid:run_id>/collect',collector.collect),path('api/device-collection/runs/<uuid:run_id>/export',collector.export)]
urlpatterns+=process_quality_urls
urlpatterns += [path('api/spc',spc_views.studies),path('api/spc/<str:key>',spc_views.board),
 path('api/spc/<str:key>/export',spc_views.export),path('api/spc/<str:key>/sources',spc_views.evidence),
 path('api/spc/<str:key>/points/<str:point_id>',spc_views.detail)]
urlpatterns += [path('api/issue-workspace',iw.board),path('api/issue-workspace/export',iw.export),path('api/issue-workspace/rows/<str:key>',iw.detail),path('api/issue-workspace/rows/<str:key>/follow-up',iw.follow_up)]
urlpatterns += [path('api/catalog/design-draft/export',views.catalog_design_export)]
urlpatterns += [path('api/imports/inspect',import_mapping_views.inspect),path('api/imports/mapping/preview',import_mapping_views.inspect)]
urlpatterns += [path('api/import-templates',import_template_views.collection),path('api/import-templates/preview',import_template_views.preview),path('api/import-templates/activate',import_template_views.activate),path('api/import-templates/<uuid:template_id>',import_template_views.detail),path('api/import-templates/<uuid:template_id>/retire',import_template_views.retire)]
urlpatterns += [path('api/analyze/explore',analysis_explore_views.board),path('api/analyze/explore/evidence',analysis_explore_views.evidence),path('api/analyze/explore/export',analysis_explore_views.export)]
urlpatterns += [path('api/analyze/explore/files/<str:token>',analysis_explore_views.download)]
urlpatterns += [path('',views.index),path('api/auth',views.auth),path('api/overview',views.overview),path('api/production',views.production_board),path('api/delivery',delivery_views.board),path('api/delivery/export',delivery_views.export),path('api/delivery/<str:line_id>',delivery_views.detail),path('api/delivery/<str:line_id>/follow-up',delivery_views.follow_up),path('api/datasets',views.datasets),path('api/records/<str:dataset>',views.records),path('api/records/<str:dataset>/export',views.record_export),path('api/imports',views.imports),path('api/imports/<uuid:batch_id>',views.import_detail),path('api/imports/<uuid:batch_id>/commit',views.import_commit),path('api/imports/<uuid:batch_id>/file',views.import_file),path('api/imports/<uuid:batch_id>/recheck',views.import_recheck),path('api/imports/<uuid:batch_id>/rows/<int:row_id>/review',views.import_conflict_review),path('api/record-history/<int:record_id>',views.record_history),path('api/imports/<uuid:batch_id>/rows/<int:row_id>/repair',views.import_repair),path('api/trace/<str:unit_id>',views.trace),path('api/analyze',views.analyze),path('api/analyze/evidence',views.analysis_evidence),path('api/scopes',views.scope_options),path('api/models',views.analysis_models),path('api/topics',views.topics),path('api/coding',coding_views.collection),path('api/coding/<int:rule_id>/allocate',coding_views.allocate),path('api/issues',views.issue_update),path('api/catalog',views.catalog),path('api/catalog/download',views.catalog_document),path('bi-design',views.catalog_document),path('api/audit',views.audit),path('api/source-files',views.source_files),path('api/source-files/<str:filename>',views.source_download)]

urlpatterns += [path('api/lineage/search',lineage_views.search),path('api/lineage',lineage_views.board),path('api/lineage/evidence',lineage_views.evidence),path('api/lineage/export',lineage_views.export),path('api/lineage/unit/<str:unit_id>',lineage_views.unit_path),path('api/trace-cases',lineage_views.cases),path('api/trace-cases/<uuid:case_id>',lineage_views.case_detail),path('api/trace-cases/<uuid:case_id>/compare',lineage_views.comparison)]

from app import quality_views,supply_views
urlpatterns += [path('api/supply',supply_views.board),path('api/supply/export',supply_views.export),path('api/supply/ledger/<str:lot_id>',supply_views.ledger),path('api/supply/<str:kind>/<str:key>',supply_views.detail),path('api/supply/<str:kind>/<str:key>/evidence',supply_views.evidence),path('api/supply/<str:kind>/<str:key>/follow-up',supply_views.follow_up),path('api/supply/<str:kind>/<str:key>/history',supply_views.history)]
urlpatterns += [path('api/quality',quality_views.board),path('api/quality/export',quality_views.export),path('api/quality/distribution',quality_views.distribution),path('api/quality/distribution/export',quality_views.distribution_export),path('api/quality/units/<str:unit_id>',quality_views.detail),path('api/quality/units/<str:unit_id>/evidence',quality_views.evidence),path('api/quality/units/<str:unit_id>/follow-up',quality_views.follow_up),path('api/quality/units/<str:unit_id>/history',quality_views.history)]

urlpatterns += [path('api/coding/<int:rule_id>',coding_views.detail),path('api/coding/<int:rule_id>/draft',coding_views.draft),path('api/coding/<int:rule_id>/lifecycle',coding_views.transition),path('api/coding/<int:rule_id>/advance',coding_views.advance),path('api/coding/<int:rule_id>/allocations',coding_views.allocations)]

from app import topic_views
from app import topic_linkage_views
urlpatterns += [path('api/topics/<int:topic_id>/link-select',topic_linkage_views.select)]
from app import bi_card_summary_views as bcs
urlpatterns += [path('api/topics/<int:topic_id>/summary/export',bcs.export),path('api/topics/<int:topic_id>/snapshots/<uuid:snapshot_id>/summary/export',bcs.frozen_export)]
urlpatterns += [path('api/topics/<int:topic_id>/workspace',topic_views.context),path('api/topics/<int:topic_id>/views',topic_views.save),path('api/topics/<int:topic_id>/views/<int:view_id>',topic_views.update),path('api/topics/<int:topic_id>/views/<int:view_id>/archive',topic_views.archive),path('api/topics/<int:topic_id>/run',topic_views.run),path('api/topics/<int:topic_id>/evidence',topic_views.evidence)]
urlpatterns += [path('api/topics/<int:topic_id>/export',topic_views.export)]

from app import topic_snapshot_views
urlpatterns += [path('api/topics/<int:topic_id>/snapshots',topic_snapshot_views.collection),
 path('api/topics/<int:topic_id>/snapshots/<uuid:snapshot_id>',topic_snapshot_views.detail),
 path('api/topics/<int:topic_id>/snapshots/<uuid:snapshot_id>/evidence',topic_snapshot_views.evidence),
 path('api/topics/<int:topic_id>/snapshots/<uuid:snapshot_id>/sources',topic_snapshot_views.sources),
 path('api/topics/<int:topic_id>/snapshots/<uuid:snapshot_id>/compare',topic_snapshot_views.compare),
 path('api/topics/<int:topic_id>/snapshots/<uuid:snapshot_id>/export',topic_snapshot_views.export)]

from app import cost_scenario_views
from app import device_file_views
from app import file_sharing_views
urlpatterns += [path('api/shared-originals',file_sharing_views.listing),
 path('api/shared-originals/<uuid:file_id>',file_sharing_views.detail),path('api/shared-originals/<uuid:file_id>/original',file_sharing_views.original),
 path('api/file-sharing/<uuid:file_id>',file_sharing_views.manage),path('api/file-sharing/<uuid:file_id>/preview',file_sharing_views.preview),
 path('api/file-sharing/<uuid:file_id>/commit',file_sharing_views.commit)]
urlpatterns += [path('api/device-files',device_file_views.listing),path('api/device-files/upload',device_file_views.upload),path('api/device-files/template',device_file_views.template),
 path('api/device-files/<uuid:file_id>',device_file_views.detail),path('api/device-files/<uuid:file_id>/preview',device_file_views.preview),
 path('api/device-files/<uuid:file_id>/review',device_file_views.review),path('api/device-files/<uuid:file_id>/original',device_file_views.original),path('api/device-files/<uuid:file_id>/export',device_file_views.export)]
urlpatterns += [path('api/cost-scenarios',cost_scenario_views.options),path('api/cost-scenarios/baseline',cost_scenario_views.baseline),
 path('api/cost-scenarios/evaluate',cost_scenario_views.evaluate),path('api/cost-scenarios/save',cost_scenario_views.save),
 path('api/cost-scenarios/evidence',cost_scenario_views.evidence),path('api/cost-scenarios/<uuid:scenario_id>',cost_scenario_views.detail),
 path('api/cost-scenarios/<uuid:scenario_id>/evidence',cost_scenario_views.evidence),path('api/cost-scenarios/<uuid:scenario_id>/export',cost_scenario_views.export)]

from app import asset_views
from app import workforce_views
urlpatterns += [path('api/workforce',workforce_views.board),path('api/workforce/export',workforce_views.export),path('api/workforce/<str:eid>',workforce_views.detail),path('api/workforce/<str:eid>/evidence',workforce_views.evidence),path('api/workforce/<str:eid>/follow-up',workforce_views.follow_up),path('api/workforce/<str:eid>/history',workforce_views.history)]
urlpatterns += [path('api/assets',asset_views.board),path('api/assets/export',asset_views.export),path('api/assets/<str:kind>/<str:key>',asset_views.detail),path('api/assets/<str:kind>/<str:key>/evidence',asset_views.evidence),path('api/assets/<str:kind>/<str:key>/follow-up',asset_views.follow_up),path('api/assets/<str:kind>/<str:key>/history',asset_views.history)]

from app import receivable_views
from app import grouping_views
urlpatterns += [path('api/groupings',grouping_views.collection),path('api/groupings/preview',grouping_views.preview),path('api/groupings/<uuid:gid>',grouping_views.detail),path('api/groupings/<uuid:gid>/archive',grouping_views.archive)]
urlpatterns += [path('api/receivables',receivable_views.board),path('api/receivables/export',receivable_views.export),path('api/receivables/<str:kind>/<str:key>',receivable_views.detail),path('api/receivables/<str:kind>/<str:key>/evidence',receivable_views.evidence),path('api/receivables/<str:kind>/<str:key>/follow-up',receivable_views.follow_up),path('api/receivables/<str:kind>/<str:key>/history',receivable_views.history)]

from app import energy_views
urlpatterns += [path("api/energy",energy_views.board),path("api/energy/export",energy_views.export),path("api/energy/<str:kind>/<str:key>",energy_views.detail),path("api/energy/<str:kind>/<str:key>/evidence",energy_views.evidence),path("api/energy/<str:kind>/<str:key>/follow-up",energy_views.follow_up),path("api/energy/<str:kind>/<str:key>/history",energy_views.history)]

from app import service_views
urlpatterns += [path('api/service',service_views.board),path('api/service/export',service_views.export),path('api/service/<str:key>',service_views.detail),path('api/service/<str:key>/evidence',service_views.evidence),path('api/service/<str:key>/follow-up',service_views.follow_up),path('api/service/<str:key>/history',service_views.history)]

from app import data_health_views
urlpatterns += [path('api/data-health',data_health_views.board),path('api/data-health/run',data_health_views.run),path('api/data-health/imports',data_health_views.imports),path('api/data-health/export',data_health_views.export),path('api/data-health/record/<int:pk>',data_health_views.record),path('api/data-health/<str:ds>',data_health_views.detail),path('api/data-health/<str:ds>/policy',data_health_views.policy),path('api/data-health/<str:ds>/history',data_health_views.history)]

from app import engineering_views
urlpatterns += [path('api/engineering',engineering_views.board),path('api/engineering/export',engineering_views.export),path('api/engineering/<str:kind>/<str:key>',engineering_views.detail),path('api/engineering/<str:kind>/<str:key>/evidence',engineering_views.evidence),path('api/engineering/<str:kind>/<str:key>/follow-up',engineering_views.follow_up),path('api/engineering/<str:kind>/<str:key>/history',engineering_views.history)]

from app import sales_views
urlpatterns += [path('api/sales',sales_views.board),path('api/sales/export',sales_views.export),path('api/sales/<str:key>',sales_views.detail),path('api/sales/<str:key>/evidence',sales_views.evidence),path('api/sales/<str:key>/follow-up',sales_views.follow_up),path('api/sales/<str:key>/history',sales_views.history)]

from app import manufacturing_views
from app import wip_views
from app import metrology_views
urlpatterns += [path('api/metrology',metrology_views.board),path('api/metrology/export',metrology_views.export),path('api/metrology/instruments',metrology_views.instruments),path('api/metrology/comparison',metrology_views.comparison),path('api/metrology/rows/<str:key>',metrology_views.detail),path('api/metrology/rows/<str:key>/evidence',metrology_views.evidence)]
from app import metrology_evidence_views as me
urlpatterns += [path('api/metrology-evidence',me.board),path('api/metrology-evidence/export',me.export),path('api/metrology-evidence/template',me.template),path('api/metrology-evidence/rows/<str:key>',me.detail),path('api/metrology-evidence/rows/<str:key>/evidence',me.evidence),path('api/metrology-evidence/rows/<str:key>/original/<str:calibration_id>',me.original)]
urlpatterns += [path('api/wip-flow',wip_views.board),path('api/wip-flow/export',wip_views.export),path('api/wip-flow/positions-export',wip_views.position_export),path('api/wip-flow/rows/<str:key>',wip_views.detail),path('api/wip-flow/rows/<str:key>/evidence',wip_views.evidence)]
urlpatterns += [path('api/wip-flow/comparison',wip_views.comparison),path('api/wip-flow/comparison/export',wip_views.comparison_export),path('api/wip-flow/comparison/rows/<str:key>',wip_views.comparison_detail)]
urlpatterns += [path('api/manufacturing',manufacturing_views.board),path('api/manufacturing/export',manufacturing_views.export),path('api/manufacturing/<str:kind>/<str:key>',manufacturing_views.detail),path('api/manufacturing/<str:kind>/<str:key>/evidence',manufacturing_views.evidence),path('api/manufacturing/<str:kind>/<str:key>/follow-up',manufacturing_views.follow_up),path('api/manufacturing/<str:kind>/<str:key>/history',manufacturing_views.history)]

urlpatterns += [path('api/analyze/pivot/evidence',analysis_pivot_views.evidence),path('api/analyze/pivot/export',analysis_pivot_views.export)]
urlpatterns += [path('api/analyze/scatter/evidence',analysis_scatter_views.evidence),path('api/analyze/scatter/export',analysis_scatter_views.export)]

from app import material_planning_views as mp
from app import material_supply_views as ms
from app import stocktake_views as stk
urlpatterns += [path('api/stocktake',stk.board),path('api/stocktake/export',stk.export),path('api/stocktake/rows/<str:key>',stk.detail),path('api/stocktake/rows/<str:key>/evidence',stk.evidence)]
from app import inventory_age_views as age
from app import purchase_commitment_views as pc
from app import receipt_flow_views as rf
urlpatterns += [path('api/receipt-flow',rf.board),path('api/receipt-flow/export',rf.export),path('api/receipt-flow/jobs-export',rf.export_jobs),path('api/receipt-flow/rows/<str:key>',rf.detail),path('api/receipt-flow/rows/<str:key>/evidence',rf.evidence)]
from app import incoming_quality_views as iq
urlpatterns += [path('api/incoming-quality',iq.board),path('api/incoming-quality/export',iq.export),path('api/incoming-quality/measurements-export',iq.measurement_export),path('api/incoming-quality/rows/<str:key>',iq.detail),path('api/incoming-quality/rows/<str:key>/evidence',iq.evidence)]
urlpatterns += [path('api/purchase-commitments',pc.board),path('api/purchase-commitments/export',pc.export),path('api/purchase-commitments/segments-export',pc.export_segments),path('api/purchase-commitments/rows/<str:key>',pc.detail),path('api/purchase-commitments/rows/<str:key>/evidence',pc.evidence)]
urlpatterns += [path('api/inventory-age',age.board),path('api/inventory-age/export',age.export),path('api/inventory-age/rows/<str:key>',age.detail),path('api/inventory-age/rows/<str:key>/evidence',age.evidence)]
urlpatterns += [path('api/material-planning/lot-compare',mp.lot_compare),path('api/material-lots/export',mp.lot_export)]
urlpatterns += [path('api/material-supply/<str:key>',ms.board),path('api/material-supply/<str:key>/evidence',ms.evidence),path('api/material-supply/<str:key>/export',ms.export)]
urlpatterns += [path('api/material-planning',mp.board),path('api/material-planning/compare',mp.compare),path('api/material-planning/export',mp.export),path('api/material-planning/<str:kind>/<str:key>',mp.detail),path('api/material-planning/<str:kind>/<str:key>/evidence',mp.evidence),path('api/material-planning/<str:kind>/<str:key>/follow-up',mp.follow_up),path('api/material-planning/<str:kind>/<str:key>/history',mp.history)]

from app import account_views
from app import credential_views
urlpatterns += [path('api/credentials',credential_views.context),path('api/credentials/change',credential_views.change),path('api/accounts/<int:user_id>/password/preview',credential_views.reset_preview),path('api/accounts/<int:user_id>/password/reset',credential_views.reset)]
urlpatterns += [path('api/accounts',account_views.collection),path('api/accounts/<int:user_id>',account_views.detail),path('api/accounts/<int:user_id>/preview',account_views.preview),path('api/accounts/<int:user_id>/update',account_views.update),path('api/accounts/<int:user_id>/revoke',account_views.revoke)]

from app import action_task_views
urlpatterns += [path('api/action-tasks',action_task_views.collection),path('api/action-tasks/preview',action_task_views.preview),
 path('api/action-tasks/<uuid:task_id>',action_task_views.detail),path('api/action-tasks/<uuid:task_id>/transition',action_task_views.transition),
 path('api/action-tasks/<uuid:task_id>/export',action_task_views.export)]

from app import quality_comparison_views
urlpatterns += [path('api/quality/comparison',quality_comparison_views.board),path('api/quality/comparison/samples',quality_comparison_views.samples),path('api/quality/comparison/export',quality_comparison_views.export)]

from app import payable_views
urlpatterns += [path('api/payables',payable_views.board),path('api/payables/export',payable_views.export),path('api/payables/<str:kind>/<str:key>',payable_views.detail),path('api/payables/<str:kind>/<str:key>/evidence',payable_views.evidence),path('api/payables/<str:kind>/<str:key>/follow-up',payable_views.follow_up),path('api/payables/<str:kind>/<str:key>/history',payable_views.history)]

from app import logistics_views
urlpatterns += [path('api/logistics',logistics_views.board),path('api/logistics/export',logistics_views.export),path('api/logistics/<str:key>',logistics_views.detail),path('api/logistics/<str:key>/evidence',logistics_views.evidence),path('api/logistics/<str:key>/follow-up',logistics_views.follow_up),path('api/logistics/<str:key>/history',logistics_views.history)]

from app import target_views
urlpatterns += [path('api/targets',target_views.board),path('api/targets/export',target_views.export),path('api/targets/<str:key>',target_views.detail),path('api/targets/<str:key>/evidence',target_views.evidence),path('api/targets/<str:key>/sources',target_views.sources),path('api/targets/<str:key>/follow-up',target_views.follow_up),path('api/targets/<str:key>/history',target_views.history)]

from app import target_breakdown_views
urlpatterns += [path('api/targets/<str:key>/breakdown',target_breakdown_views.breakdown),path('api/targets/<str:key>/breakdown/evidence',target_breakdown_views.evidence),path('api/targets/<str:key>/breakdown/sources',target_breakdown_views.sources),path('api/targets/<str:key>/breakdown/export',target_breakdown_views.export)]

from app import assembly_plan_views
urlpatterns += [path('api/assembly-plans',assembly_plan_views.board),path('api/assembly-plans/export',assembly_plan_views.export),path('api/assembly-plans/dates/<str:date_key>',assembly_plan_views.version_detail),path('api/assembly-plans/rows/<str:key>',assembly_plan_views.detail),path('api/assembly-plans/rows/<str:key>/evidence',assembly_plan_views.evidence),path('api/assembly-plans/rows/<str:key>/units',assembly_plan_views.units),path('api/assembly-plans/rows/<str:key>/follow-up',assembly_plan_views.follow_up),path('api/assembly-plans/rows/<str:key>/history',assembly_plan_views.history)]

from app import coordination_hub_views
urlpatterns += [path("api/coordination-hub",coordination_hub_views.board),path("api/coordination-hub/export",coordination_hub_views.export),path("api/coordination-hub/rows/<str:key>",coordination_hub_views.detail)]

from app import material_certificate_views as mc
urlpatterns += [path("api/material-certificates",mc.board),path("api/material-certificates/export",mc.export),path("api/material-certificates/rows/<str:key>",mc.detail),path("api/material-certificates/rows/<str:key>/evidence",mc.evidence)]

urlpatterns += [path("api/material-certificates/template",mc.template)]

from app import device_transform_views as device_transform
urlpatterns += [path('api/device-transform',device_transform.board),path('api/device-transform/inspect',device_transform.inspect),path('api/device-transform/preview',device_transform.preview),path('api/device-transform/drafts',device_transform.draft),path('api/device-transform/versions/<int:version_id>/activate',device_transform.activate),path('api/device-transform/execute',device_transform.execute),path('api/device-transform/receipts/<uuid:receipt_id>',device_transform.detail),path('api/device-transform/receipts/<uuid:receipt_id>/export',device_transform.export)]

urlpatterns += [path('api/spc-analysis-views',spc_workspace.views),path('api/spc-analysis-views/<uuid:key>',spc_workspace.view),
 path('api/spc-analysis-views/<uuid:key>/archive',spc_workspace.archive),path('api/spc-analysis-views/<uuid:key>/run',spc_workspace.run),
 path('api/spc-result-snapshots',spc_workspace.snapshots),path('api/spc-result-snapshots/<uuid:key>',spc_workspace.snapshot),
 path('api/spc-result-snapshots/<uuid:key>/points/<str:point_id>',spc_workspace.snapshot_point),
 path('api/spc-result-snapshots/<uuid:key>/sources',spc_workspace.snapshot_sources),path('api/spc-result-snapshots/<uuid:key>/export',spc_workspace.export),
 path('api/spc-result-snapshots/<uuid:key>/original/<int:row_id>',spc_workspace.original),
 path('api/spc-result-snapshots/<uuid:key>/compare-current',spc_workspace.compare_current)]
from app import msa_views as msa
from app import finite_schedule_views as finite_schedule
from app import crew_schedule_views as crew_schedule
from app import joint_schedule_views as joint_schedule
from app import order_baseline_views as order_baseline
urlpatterns += [path('api/order-baselines',order_baseline.studies),path('api/order-baselines/<str:key>',order_baseline.board),path('api/order-baselines/<str:key>/sources',order_baseline.sources),path('api/order-baselines/<str:key>/links/<str:link_id>',order_baseline.detail),path('api/order-baselines/<str:key>/export',order_baseline.export)]
urlpatterns += [path('api/joint-schedule',joint_schedule.studies),path('api/joint-schedule/<str:key>',joint_schedule.board),path('api/joint-schedule/<str:key>/sources',joint_schedule.sources),path('api/joint-schedule/<str:key>/tasks/<str:task_id>',joint_schedule.detail),path('api/joint-schedule/<str:key>/export',joint_schedule.export)]
urlpatterns += [path('api/crew-schedule',crew_schedule.studies),path('api/crew-schedule/<str:key>',crew_schedule.board),path('api/crew-schedule/<str:key>/sources',crew_schedule.sources),path('api/crew-schedule/<str:key>/tasks/<str:task_id>',crew_schedule.detail),path('api/crew-schedule/<str:key>/export',crew_schedule.export)]

from app import oee_views as oee
urlpatterns += [path('api/oee',oee.studies),path('api/oee/<str:key>',oee.board),path('api/oee/<str:key>/sources',oee.sources),path('api/oee/<str:key>/windows/<str:window_id>',oee.detail),path('api/oee/<str:key>/export',oee.export)]
urlpatterns += [path('api/finite-schedule',finite_schedule.studies),path('api/finite-schedule/<str:key>',finite_schedule.board),
 path('api/finite-schedule/<str:key>/tasks/<str:task_id>',finite_schedule.detail),path('api/finite-schedule/<str:key>/sources',finite_schedule.sources),path('api/finite-schedule/<str:key>/export',finite_schedule.export)]
urlpatterns += [path('api/msa',msa.studies),path('api/msa/<str:key>',msa.board),
 path('api/msa/<str:key>/points/<str:point_id>',msa.detail),
 path('api/msa/<str:key>/cells/<str:part_id>/<str:operator_id>',msa.cell),
 path('api/msa/<str:key>/sources',msa.sources),path('api/msa/<str:key>/export',msa.export)]
from app import model_card_views as model_cards
urlpatterns += [path('api/model-cards',model_cards.collection),path('api/model-cards/preview/<int:model_id>',model_cards.preview),
 path('api/model-cards/<uuid:key>',model_cards.detail),path('api/model-cards/<uuid:key>/history',model_cards.history),
 path('api/model-cards/<uuid:key>/archive',model_cards.archive),path('api/model-cards/<uuid:key>/run',model_cards.run),
 path('api/model-cards/<uuid:key>/export',model_cards.export),path('api/model-cards/<uuid:key>/evidence',model_cards.evidence),path('api/model-cards/<uuid:key>/result-export',model_cards.result_export)]

from app import launch_views
urlpatterns += [path('api/launch-review',launch_views.studies),path('api/launch-review/<str:key>',launch_views.board),path('api/launch-review/<str:key>/sources',launch_views.sources),path('api/launch-review/<str:key>/tasks/<str:task_id>',launch_views.detail),path('api/launch-review/<str:key>/export',launch_views.export)]

from app import first_piece_views
urlpatterns += [path('api/first-piece',first_piece_views.board),path('api/first-piece/export',first_piece_views.export),path('api/first-piece/<str:key>',first_piece_views.detail)]
