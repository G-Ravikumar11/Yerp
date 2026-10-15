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
from app.models.plant import (
    DBPlantAllocation,
    DBPlantExpense,
    DBPlantFuel,
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
    DBCodeSequence,
    DBBomLine,
    DBStockMovement,
    DBStockIssue,
    DBStockIssueLine,
    DBStockBalance,
)
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
