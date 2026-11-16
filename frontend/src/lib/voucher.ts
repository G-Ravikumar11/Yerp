import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, BookOpen, Receipt, Wallet, type LucideIcon } from 'lucide-react'

/** The kinds of voucher accounts passes, as Tally names them, and the right each needs - the same rights the forms already ask. */
export type VoucherKind = 'payment' | 'receipt' | 'contra' | 'expense' | 'income' | 'journal'

export interface VoucherType {
  kind: VoucherKind
  label: string
  /** One line on what it is for. */
  hint: string
  /** The key that picks it while the list is open. */
  key: string
  icon: LucideIcon
  /** The permission the existing form needs. */
  perm: 'bills.pay' | 'accounts.manage'
}

export const VOUCHER_TYPES: VoucherType[] = [
  { kind: 'payment', label: 'Payment', hint: 'Money paid to a supplier or contractor: against a bill, or on account.', key: 'p', icon: ArrowUpRight, perm: 'bills.pay' },
  { kind: 'receipt', label: 'Receipt', hint: 'Money received from a client: against a bill, or on account.', key: 'r', icon: ArrowDownLeft, perm: 'bills.pay' },
  { kind: 'contra', label: 'Contra', hint: 'Cash drawn from the bank, paid in, or moved between accounts.', key: 'c', icon: ArrowLeftRight, perm: 'bills.pay' },
  { kind: 'expense', label: 'Expense', hint: 'Diesel, transport, site sundries - money out with no bill behind it.', key: 'e', icon: Wallet, perm: 'bills.pay' },
  { kind: 'income', label: 'Other receipt', hint: 'Scrap sold, interest, a deposit back - money in with no bill of ours.', key: 'o', icon: Receipt, perm: 'bills.pay' },
  { kind: 'journal', label: 'Journal', hint: 'An adjustment between ledgers that moves no money. The Master approves it.', key: 'j', icon: BookOpen, perm: 'accounts.manage' },
]

/** The vouchers this person may pass: each form's own right, so the list never offers what would be refused. */
export const voucherTypesFor = (can: (perm: string) => boolean) => VOUCHER_TYPES.filter((t) => can(t.perm))

/** Whether there is a "New voucher" for this person at all: the Accounts section, and a right to pass at least one kind. */
export const canPassVouchers = (can: (perm: string) => boolean) => can('money.view') && voucherTypesFor(can).length > 0

export const SHORTCUT = 'Alt+V'
