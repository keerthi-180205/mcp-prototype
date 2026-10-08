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
    <div className="mt-3 p-4 rounded-xl bg-slate-900/90 border border-indigo-500/30 shadow-lg text-slate-100 max-w-xl">
      <div className="flex items-center justify-between pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-400" />
          <h4 className="font-semibold text-base text-white">Collection Plan</h4>
        </div>
        <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-medium border border-indigo-500/30">
          Awaiting Confirmation
        </span>
      </div>

      <div className="py-3 space-y-2.5 text-sm">
        <div className="flex items-start justify-between gap-4">
          <span className="text-slate-400 font-medium">Topic:</span>
          <span className="text-white font-semibold text-right">{topic}</span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-slate-400 font-medium flex items-center gap-1.5">
            <Target className="w-4 h-4 text-emerald-400" /> Target per platform:
          </span>
          <span className="text-emerald-300 font-semibold">{commentTarget.toLocaleString()} comments</span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-slate-400 font-medium flex items-center gap-1.5">
            <Layers className="w-4 h-4 text-sky-400" /> Platforms:
          </span>
          <div className="flex items-center gap-1.5">
            {platforms.map(p => (
              <span
                key={p}
                className="px-2 py-0.5 rounded text-xs font-semibold uppercase bg-slate-800 border border-slate-700 text-slate-200"
              >
                {p}
              </span>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-slate-400 font-medium flex items-center gap-1.5">
            <Clock className="w-4 h-4 text-amber-400" /> Time limit:
          </span>
          <span className="text-slate-300 font-medium">Up to {max_minutes} mins</span>
        </div>
      </div>

      {/* Warnings & Cost Notices */}
      {(warnings.length > 0 || instagram_warning) && (
        <div className="my-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 space-y-1">
          <div className="flex items-center gap-1.5 font-semibold text-amber-200 mb-1">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>Important Notice</span>
          </div>
          {warnings.map((w, idx) => (
            <p key={idx} className="leading-relaxed">{w}</p>
          ))}
        </div>
      )}

      {/* Action Buttons */}
      <div className="pt-3 border-t border-slate-800 flex items-center gap-2">
        <button
          onClick={() => onAction('confirm')}
          disabled={disabled}
          className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-sm transition-all shadow-md hover:shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Check className="w-4 h-4" />
          <span>Confirm & Start</span>
        </button>

        <button
          onClick={() => onAction('cancel_plan')}
          disabled={disabled}
          className="flex items-center justify-center gap-1 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white font-medium text-sm transition-all border border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <X className="w-4 h-4" />
          <span>Cancel</span>
        </button>
      </div>
    </div>
  )
}
