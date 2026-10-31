"""Every table the app keeps, one file per area. `from app import models` gives them all, as it always did."""
# ruff: noqa: F401
from app.db.session import Base

from app.models.accounts import (
    DBClient,
    DBJobRun,
    DBTeamMember,
    DBPasswordReset,
    DBSettings,
    DBSuperAdmin,
    DBAdminUser,
    DBClientLoginLog,
    DBAuditLog,
    DBPortalUser,
    DBIdempotency,
)
from app.models.alerts import (
    DBNotification,
    DBDevice,
    DBAlert,
    DBAlertRead,
)
from app.models.approvals import (
    DBApprovalChain,
)
from app.models.assets import (
    DBAsset,
    DBAssetMove,
    DBAssetLog,
    DBAssetService,
    DBAssetBook,
)
from app.models.bbs import DBBbsEntry, DBBbsRevision
from app.models.plant import (
    DBFormworkHire,
    DBFormworkPayment,
    DBFormworkReturn,
    DBPlantAlert,
    DBPlantAllocation,
    DBPlantExpense,
    DBPlantFuel,
    DBPlantFuelReview,
    DBPlantMeterEvent,
    DBPlantRental,
    DBPlantRentalExtension,
    DBPlantRentalInvoice,
    DBPlantRentalProvider,
)
from app.models.boq import (
    DBBoq,
    DBBoqRevision,
    DBBoqLine,
    DBBoqVariation,
    DBBoqVariationLine,
)
from app.models.budgeting import DBBoqBudget, DBBoqBudgetItem
from app.models.client_orders import (
    DBWorkOrder,
    DBWorkOrderLine,
    DBMeasurement,
    DBRABill,
    DBRABillLine,
    DBVariationOrder,
    DBVariationLine,
)
from app.models.compliance import (
    DBBackCharge,
    DBComplianceDocument,
    DBContractorRating,
)

from app.models.crm import (
    DBQuote,
    DBQuoteLineItem,
    DBContact,
    DBEstimate,
    DBEstimateItem,
    DBRateAnalysis,
    DBLead,
    DBLeadActivity,
)
from app.models.files import (
    DBFile,
    DBDrawing,
    DBDrawingRevision,
)
from app.models.hr import (
    DBDepartment,
    DBEmployee,
    DBPayslip,
    DBPayComponent,
    DBPayslipLine,
    DBSalaryRevision,
    DBOnboardingItem,
    DBOnboardingTemplate,
    DBAttendance,
    DBAttendanceSettings,
    DBOvertimeLog,
    DBEmployeeGoal,
    DBDepartmentGoal,
    DBLeaveRequest,
    DBEmployeeSite,
    DBDepartmentSite,
    DBCustomHoliday,
    DBSiteGeofence,
)
from app.models.celebrations import DBSpecialDay, DBCelebrationReaction, DBCelebrationWish
from app.models.invoicing import (
    DBInvoice,
    DBPayment,
    DBLineItem,
    DBRecurringInvoice,
    DBRecurringLineItem,
    DBInvoiceReminder,
    DBTaxRate,
    DBBill,
    DBBillLineItem,
    DBBrandingTheme,
    DBEwayBill,
    DBEwayBillLine,
    DBTaxBlock,
    DBEinvoiceIrn,
)
from app.models.money import (
    DBBankAccount,
    DBMoneyEntry,
    DBRetentionRelease,
    DBCreditNote,
    DBCreditNoteLine,
    DBPaymentRequest,
    DBSiteCashExpense,
    DBBankStatementLine,
)
from app.models.procurement import (
    DBPurchaseOrder,
    DBPurchaseOrderLineItem,
    DBGoodsReceipt,
    DBGoodsReceiptLine,
    DBSupplier,
    DBRfq,
    DBRfqLine,
    DBRfqQuote,
    DBRfqQuoteLine,
    DBRfqInvite,
)
from app.models.invoice_tracker import (
    DBTrackerInvoice,
    DBTrackerBlock,
    DBTrackerNote,
    DBTrackerCharge,
    DBTrackerInvoiceNote,
    DBTrackerWorkingRate,
)
from app.models.projects import (
    DBJob,
    DBSiteDiary,
    DBDiaryLabour,
    DBDiaryPlant,
    DBScheduleActivity,
    DBScheduleBaseline,
    DBScheduleBaselineRow,
    DBScheduleCalendar,
    DBScheduleHoliday,
    DBScheduleLink,
    DBScheduleProgress,
    DBScheduleTask,
    DBProjectThread,
    DBProjectMessage,
    DBThreadRead,
    DBChatReaction,
    DBChatTask,
    DBChatNotice,
)
from app.models.quality import (
    DBInspection,
    DBCubeSet,
    DBCubeDueNotice,
    DBCubeResult,
    DBNcr,
    DBQcChecklist,
    DBQcCriteria,
)
from app.models.recruitment import (
    DBInterviewReminder,
    DBJobRequisition,
    DBRecruitmentForm,
    DBInterview,
    DBOffer,
    DBFormSubmission,
    DBCandidateDocument,
    DBSubmissionEvent,
    DBDocument,
    DBDocumentRequirement,
    DBDocumentRequest,
)
from app.models.error_log import DBErrorLog  # noqa: F401
from app.models.material_voucher import DBMaterialVoucher  # noqa: F401
from app.models.safety import (
    DBEquipmentCheck,
    DBSafetyIncident,
    DBToolboxTalk,
    DBWorkPermit,
    DBWorkerScreening,
)
from app.models.site_rates import (
    DBSiteItemRate,
    DBRateAuditLog,
)
from app.models.stores import (
    DBItem,
    DBItemCategory,
    DBItemMerge,
    DBCodeSequence,
    DBBomLine,
    DBStockMovement,
    DBStockIssue,
    DBStockIssueLine,
    DBStockBalance,
    DBStoreCutover,
)
from app.models.store_core import (
    DBStore,
    DBStoreBin,
    DBStoreUserAssignment,
    DBStoreItemSettings,
    DBStoreUomConversion,
    DBStoreFreeze,
    DBStoreDocSequence,
    DBStoreStockLedger,
    DBStoreStockBalance,
)
from app.models import store_inward, store_outward, store_control, store_reports, store_extras  # noqa: F401  (the Store slices' own tables)
from app.models.subcontracts import (
    DBBusinessUnit,
    DBWorkType,
    DBContractor,
    DBSubcontractOrder,
    DBProjectBudget,
    DBSubcontractItem,
    DBSubcontractTerm,
    DBOrderAccess,
    DBSubcontractApproval,
    DBSubMeasurement,
    DBMeasurementDimension,
    DBSubBill,
    DBSubBillLine,
    DBMaterialRecovery,
)
from app.models.wallet import (
    DBWallet,
    DBWalletTransaction,
    DBPricingRule,
    DBTopUpOrder,
)
