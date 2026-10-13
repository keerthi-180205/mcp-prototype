import { Check, X, AlertTriangle, Clock, Target, Layers } from 'lucide-react'

export default function PlanCard({ card, onAction, disabled }) {
  const {
    topic,
    platforms = [],
    target_comments,
    target,
    max_minutes = 10,
    warnings = [],
    instagram_warning
  } = card

  const commentTarget = target || target_comments || 500

  return (
    <div className="llm-card plan-card">
      <div className="card-header-row">
        <div className="card-title-group">
          <Layers className="w-4 h-4" style={{ color: '#10a37f' }} />
          <h4 className="card-title">Collection Plan</h4>
        </div>
        <span className="card-status-badge badge-pending">
          Awaiting Confirmation
        </span>
      </div>

      <div className="plan-specs">
        <div className="spec-box">
          <span className="label">Topic</span>
          <span className="val">{topic}</span>
        </div>

        <div className="spec-box">
          <span className="label" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Target className="w-3.5 h-3.5" style={{ color: '#10a37f' }} /> Target per platform
          </span>
          <span className="val" style={{ color: '#34d399' }}>
            {commentTarget.toLocaleString()} comments
          </span>
        </div>

        <div className="spec-box">
          <span className="label">Platforms</span>
          <div className="platforms-tag-row">
            {platforms.map(p => (
              <span key={p} className="platform-tag">
                {p}
              </span>
            ))}
          </div>
        </div>

        <div className="spec-box">
          <span className="label" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Clock className="w-3.5 h-3.5" style={{ color: '#f59e0b' }} /> Time limit
          </span>
          <span className="val">Up to {max_minutes} mins</span>
        </div>
      </div>

      {/* Warnings & Cost Notices */}
      {(warnings.length > 0 || instagram_warning) && (
        <div className="card-notice-box">
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
            <AlertTriangle className="w-4 h-4" style={{ color: '#fbbf24' }} />
            <span>Notice</span>
          </div>
          {warnings.map((w, idx) => (
            <p key={idx}>{w}</p>
          ))}
          {instagram_warning && <p>{instagram_warning}</p>}
        </div>
      )}

      {/* Action Buttons */}
      <div className="card-actions-row">
        <button
          onClick={() => onAction('confirm')}
          disabled={disabled}
          className="btn-confirm-start"
          title="Confirm this plan and trigger background scraping"
        >
          <Check className="w-4 h-4" />
          <span>Confirm & Start Collection</span>
        </button>

        <button
          onClick={() => onAction('cancel_plan')}
          disabled={disabled}
          className="btn-cancel"
          title="Cancel this plan"
        >
          <X className="w-4 h-4" />
          <span>Cancel</span>
        </button>
      </div>
    </div>
  )
}
