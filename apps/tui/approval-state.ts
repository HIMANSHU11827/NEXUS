export type ApprovalDecision = 'allow' | 'allow_always' | 'deny';

export const approvalDecisionFromInput = (value: string, escape = false): ApprovalDecision | null => {
    if (escape) return 'deny';
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'y' || normalized === '1') return 'allow';
    if (normalized === 'a' || normalized === '2') return 'allow_always';
    if (normalized === 'n' || normalized === '3') return 'deny';
    return null;
};
