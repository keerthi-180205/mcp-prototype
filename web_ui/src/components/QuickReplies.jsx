export default function QuickReplies({ replies = [], onSelect, disabled }) {
  if (!replies || replies.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
      {replies.map((reply, idx) => (
        <button
          key={idx}
          onClick={() => onSelect(reply)}
          disabled={disabled}
          className="px-3 py-1 rounded-full text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/80 transition-all shadow-sm hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {reply}
        </button>
      ))}
    </div>
  )
}
