import type { Allocation, FairnessCap, Offer } from './types';

const quantity = new Intl.NumberFormat('en', { maximumFractionDigits: 6 });
const percent = new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 2 });

export function AllocationBars({ allocation, offer, cap }: { allocation: Allocation; offer: Offer; cap?: FairnessCap | null }) {
  const total = offer.quantity;
  const amount = allocation.quantity;
  if (!Number.isFinite(total) || total <= 0 || !Number.isFinite(amount) || amount < 0) {
    return <p className="allocation-unavailable">Offer total or allocation unavailable for comparison. No percentage is inferred.</p>;
  }
  const appliedCap = cap && Number.isFinite(cap.share) && cap.share > 0 && cap.share <= 1
    && typeof cap.source === 'string' && cap.source.length > 0 ? cap : null;
  const ratio = amount / total;
  const overCap = appliedCap && ratio > appliedCap.share + Number.EPSILON;
  return <div className="allocation-bars">
    <div className="bar-heading"><span>Allocated share</span><span>{percent.format(ratio)} of this offer</span></div>
    <div className={`allocation-meter${overCap ? ' allocation-meter-over' : ''}`} role="meter"
      aria-label={`${allocation.org}: allocated share`} aria-valuemin={0} aria-valuemax={total}
      aria-valuenow={Math.min(amount, total)} aria-valuetext={`${amount} ${offer.unit} allocated out of ${total} ${offer.unit} offered`}>
      <span style={{ width: `${Math.min(ratio, 1) * 100}%` }}/>
    </div>
    {appliedCap ? <>
      <div className="bar-heading"><span>Policy ceiling</span><span>{percent.format(appliedCap.share)} · {quantity.format(total * appliedCap.share)} {offer.unit}</span></div>
      <div className="allocation-meter cap-meter" role="meter" aria-label={`${allocation.org}: policy ceiling`}
        aria-valuemin={0} aria-valuemax={total} aria-valuenow={total * appliedCap.share}
        aria-valuetext={`${percent.format(appliedCap.share)} of ${total} ${offer.unit} offered: ${quantity.format(total * appliedCap.share)} ${offer.unit}`}>
        <span style={{ width: `${appliedCap.share * 100}%` }}/>
      </div>
      {overCap && <p className="allocation-warning">Reported share exceeds the supplied policy ceiling. Review the record.</p>}
    </> : <p className="allocation-unavailable">Fairness cap unavailable in this saved result. No default is assumed.</p>}
  </div>;
}
